#Local application
from .components.cnn_blocks import PeriodicConv2D
from .components.pos_embed import get_2d_sincos_pos_embed
from .utils import register

#Third Party
import torch
import torch.nn as nn
import torchvision
import sys
import ipdb
import timm
from transformers import ViTModel, AutoConfig, AutoModel, CLIPModel
from timm.models.vision_transformer import Block, PatchEmbed, trunc_normal_



@register('vit_pretrained')
class ViTPretrained(nn.Module):

    def __init__(self, 
        in_img_size,
        out_img_size, 
        in_channels, 
        out_channels, 
        use_pretrained_weights=False,
        use_pretrained_embeddings=False,
        freeze_backbone=False, 
        freeze_embeddings=False,
        learn_pos_emb=False,
        resize_img=False,
        patch_size=16, 
        embed_dim=1024,
        decoder_depth=2,
        pretrained_model=None,
        mlp_embed_depth=0,
        num_backbone_blocks=1000,
    ):
        super().__init__()
        self.patch_size = patch_size
        self.in_img_size = in_img_size
        self.out_img_size = out_img_size
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.num_patches = (in_img_size[0] * in_img_size[1]) // (patch_size)**2
        self.embed_dim = embed_dim
        self.use_pretrained_embeddings = use_pretrained_embeddings
        self.use_pretrained_weights = use_pretrained_weights
        self.freeze_embeddings= freeze_embeddings
        self.freeze_backbone = freeze_backbone
        self.pretrained_model_name = pretrained_model
        self.resize_img = resize_img
        self.eff_patch_size = [int((patch_size / in_img_size[0]) * out_img_size[0]), int((patch_size / in_img_size[1]) * out_img_size[1])]
        self.num_backbone_blocks = num_backbone_blocks

        self.load_pretrained_model()
        
        if not use_pretrained_embeddings:
            self.patch_embed = PatchEmbed(in_img_size, patch_size, in_channels, embed_dim)
            self.pos_embed = nn.Parameter(
                torch.zeros(1, self.num_patches+1, embed_dim), requires_grad=learn_pos_emb,
            )
            self.pos_drop = nn.Dropout(p=0.1)

            self.mlp_embed = nn.ModuleList()
            for _ in range(mlp_embed_depth):
                self.mlp_embed.append(nn.GELU())
                self.mlp_embed.append(nn.Linear(embed_dim, embed_dim))
            self.mlp_embed = nn.Sequential(*self.mlp_embed)

            print('Using new embeddings')

        
        # prediction head
        self.head = nn.ModuleList()
        for _ in range(decoder_depth):
            self.head.append(nn.Linear(embed_dim, embed_dim))
            self.head.append(nn.GELU())
        self.head.append(nn.Linear(embed_dim, out_channels*self.eff_patch_size[0]*self.eff_patch_size[1]))
        self.head = nn.Sequential(*self.head)

        self.initialize_weights()

    def load_pretrained_model(self):
        if 'google/vit' in self.pretrained_model_name:
            print('Loading google/vit')
            if self.use_pretrained_weights:
                self.pretrained_backbone = AutoModel.from_pretrained(self.pretrained_model_name)
                if self.freeze_backbone:
                    for name, param in self.pretrained_backbone.named_parameters():
                        if 'embeddings' in name and not self.freeze_embeddings:
                            continue
                        param.requires_grad = False
            else:
                print(f'Loading randomly initialized model like {self.pretrained_model_name}')
                ViTModelConfig = AutoConfig.from_pretrained(self.pretrained_model_name)
                self.pretrained_backbone = AutoModel.from_config(ViTModelConfig)
        elif 'dinov2' in self.pretrained_model_name:
            if self.use_pretrained_weights:
                print('Loading dinov2 weights')
                self.pretrained_backbone = torch.hub.load('facebookresearch/dinov2', self.pretrained_model_name)
            else:
                print('Loading randomly initialized model like DINOv2')
                self.pretrained_backbone = torch.hub.load('facebookresearch/dinov2', self.pretrained_model_name, pretrained=False)
            if self.freeze_backbone:
                print('Freezing Backbone')
                if self.freeze_embeddings:
                    print('Freezing Embeddings')
                for name, param in self.pretrained_backbone.named_parameters():
                    if 'norm' in name or '.ls' in name or 'bias' in name:
                        continue
                    if ('embed' in name or 'token' in name) and not self.freeze_embeddings:
                        continue
                    param.requires_grad = False

        elif 'clip' in self.pretrained_model_name:
            print('Loading clip')
            if self.use_pretrained_weights:
                self.pretrained_backbone = CLIPModel.from_pretrained(self.pretrained_model_name)
                if self.freeze_backbone:
                    print('Freezing Backbone')
                    for name, param in self.pretrained_backbone.named_parameters():
                        if 'norm' in name or 'bias' in name:
                            continue
                        if 'embeddings' in name and not self.freeze_embeddings:
                            continue
                        param.requires_grad = False
            else:
                print(f'Loading randomly initialized model like {self.pretrained_model_name}')
                CLIPModelConfig = AutoConfig.from_pretrained(self.pretrained_model_name)
                self.pretrained_backbone = AutoModel.from_config(CLIPModelConfig)
        else:
            print('Not Implemented')
            exit()

    def initialize_weights(self):
        if not self.use_pretrained_embeddings:
            pos_embed = get_2d_sincos_pos_embed(
                self.pos_embed.shape[-1],
                self.in_img_size[0] // self.patch_size,
                self.in_img_size[1] // self.patch_size,
                cls_token=True,
            )
            self.pos_embed.data.copy_(torch.from_numpy(pos_embed).float().unsqueeze(0))
        if not self.use_pretrained_weights:
            self.apply(self._init_weights)

    def _init_weights(self, m):
        if isinstance(m, nn.Linear):
            trunc_normal_(m.weight, std=0.02)
            if m.bias is not None:
                nn.init.constant_(m.bias, 0)
        elif isinstance(m, nn.LayerNorm):
            nn.init.constant_(m.bias, 0)
            nn.init.constant_(m.weight, 1.0)

    def unpatchify(self, x: torch.Tensor, h=None, w=None):
        """
        x: (B, L, V * patch_size**2)
        return imgs: (B, V, H, W)
        """
        p = self.patch_size
        v = self.out_channels
        h = self.out_img_size[0] // self.eff_patch_size[0] if h is None else h // p
        w = self.out_img_size[1] // self.eff_patch_size[1] if w is None else w // p
        assert h * w == x.shape[1]

        x = x.reshape(shape=(x.shape[0], h, w, self.eff_patch_size[0], self.eff_patch_size[1], v))
        x = torch.einsum("nhwpqv->nvhpwq", x)
        imgs = x.reshape(shape=(x.shape[0], v, h * self.eff_patch_size[0], w * self.eff_patch_size[1]))
        return imgs


    def forward_encoder(self, x):
        # x.shape = [B,T*in_channels,H,W]
        if 'dino' not in self.pretrained_model_name:
            print('CHECK')
            exit()
        if self.resize_img:
            x = torchvision.transforms.Resize((self.in_img_size[0] ,self.in_img_size[1]))(x)
        if not self.use_pretrained_embeddings:
            x = self.patch_embed(x)
            # x.shape = [B,num_patches,embed_dim]
            x = torch.cat((self.pretrained_backbone.cls_token.expand(x.shape[0], -1, -1), x), dim=1)
            # x.shape = [B,num_patches+1,embed_dim]
            x = x + self.pos_embed
            x = self.mlp_embed(x)
            x = self.pos_drop(x)
            # x.shape = [B,num_patches+1,embed_dim]
        
        if 'google/vit' in self.pretrained_model_name:
            # print('Forward Encoder 1')
            if self.use_pretrained_embeddings:
                # x.shape = [B,3,H,W]
                x = self.pretrained_backbone(x, interpolate_pos_encoding=True)
                x = x.last_hidden_state
                x = x[:, 1:]
            else:
                # x.shape = [B,num_patches,embed_dim]
                x = self.pretrained_backbone.encoder(x)
                x = x[0]
                x = self.pretrained_backbone.layernorm(x)
        elif 'dinov2' in self.pretrained_model_name:
            # print('Forward Encoder 2')
            if self.use_pretrained_embeddings:
                # x.shape = [B,3,H,W]
                x = self.pretrained_backbone.prepare_tokens_with_masks(x)
            # x.shape = [B,num_patches+1,embed_dim]
            for blk in self.pretrained_backbone.blocks[:self.num_backbone_blocks]:
                x = blk(x)
            # x.shape = [B,num_patches+1,embed_dim]
            x = self.pretrained_backbone.norm(x)
            # x.shape = [B,num_patches+1,embed_dim]
            x = x[:, 1:]
            # x.shape = [B,num_patches,embed_dim]
        elif 'clip' in self.pretrained_model_name:
            # print('Forward Encoder 3')
            if self.use_pretrained_embeddings:
                # x.shape = [B,3,H,W]
                print("Doesn't allow different patch size")
                exit()
            else:
                # x.shape = [B,num_patches,embed_dim]
                x = self.pretrained_backbone.vision_model.pre_layrnorm(x)
                x = self.pretrained_backbone.vision_model.encoder(x)
                x = x.last_hidden_state
        else:
            print('Not Implemented')
            exit()
        return x

    def forward(self, x):
        # x.shape = [B,T*in_channels,H,W]
        # x = x.flatten(1, 2)
        # x.shape = [B,T*in_channels,H,W]
        x = self.forward_encoder(x)
        # x.shape = [B, num_patches, embed_dim]
        x = self.head(x)
        # x.shape = [B, num_patches, out_channels*patch_size**2]
        x = self.unpatchify(x)
        # x.shape = [B, out_channels, H, W]
        return x

