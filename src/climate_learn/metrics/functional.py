# Standard library
from typing import Optional, Union

# Third party
import torch
import torch.nn.functional as F


def mse(
    pred: Union[torch.FloatTensor, torch.DoubleTensor],
    target: Union[torch.FloatTensor, torch.DoubleTensor],
    aggregate_only: bool = False,
    lat_weights: Optional[Union[torch.FloatTensor, torch.DoubleTensor]] = None,
) -> Union[torch.FloatTensor, torch.DoubleTensor]:
    error = (pred - target).square()
    if lat_weights.shape[2] != error.shape[2]:
        lat_weights = torch.nn.functional.interpolate(lat_weights, size=(error.shape[2], 1))
    if lat_weights is not None:
        error = error * lat_weights
    per_channel_losses = error.mean([0, 2, 3])
    loss = error.mean()
    if aggregate_only:
        return loss
    return torch.cat((per_channel_losses, loss.unsqueeze(0)))


def rmse(
    pred: Union[torch.FloatTensor, torch.DoubleTensor],
    target: Union[torch.FloatTensor, torch.DoubleTensor],
    aggregate_only: bool = False,
    lat_weights: Optional[Union[torch.FloatTensor, torch.DoubleTensor]] = None,
) -> Union[torch.FloatTensor, torch.DoubleTensor]:
    error = (pred - target).square()
    if lat_weights is not None:
        error = error * lat_weights
    per_channel_losses = error.mean([2, 3]).sqrt().mean(0)
    loss = per_channel_losses.mean()
    if aggregate_only:
        return loss
    return torch.cat((per_channel_losses, loss.unsqueeze(0)))


def nrmses(
    pred: Union[torch.FloatTensor, torch.DoubleTensor],
    target: Union[torch.FloatTensor, torch.DoubleTensor],
    clim: Union[torch.FloatTensor, torch.DoubleTensor],
    aggregate_only: bool = False,
    lat_weights: Optional[Union[torch.FloatTensor, torch.DoubleTensor]] = None,
) -> Union[torch.FloatTensor, torch.DoubleTensor]:
    y_normalization = clim.squeeze()
    error = (pred.mean(dim=0) - target.mean(dim=0))**2 # (C, H, W)
    if lat_weights is not None:
        error = error * lat_weights.squeeze(0)
    per_channel_losses = error.mean(dim=(-2,-1)).sqrt() / y_normalization # C
    loss = per_channel_losses.mean()
    if aggregate_only:
        return loss
    return torch.cat((per_channel_losses, loss.unsqueeze(0)))


def nrmseg(
    pred: Union[torch.FloatTensor, torch.DoubleTensor],
    target: Union[torch.FloatTensor, torch.DoubleTensor],
    clim: Union[torch.FloatTensor, torch.DoubleTensor],
    aggregate_only: bool = False,
    lat_weights: Optional[Union[torch.FloatTensor, torch.DoubleTensor]] = None,
) -> Union[torch.FloatTensor, torch.DoubleTensor]:
    y_normalization = clim.squeeze()
    if lat_weights is not None:
        pred = pred * lat_weights
        target = target * lat_weights
    pred = pred.mean(dim=(-2, -1)) # N, C
    target = target.mean(dim=(-2, -1)) # N, C
    error = (pred - target)**2
    per_channel_losses = error.mean(0).sqrt() / y_normalization # C
    loss = per_channel_losses.mean()
    if aggregate_only:
        return loss
    return torch.cat((per_channel_losses, loss.unsqueeze(0)))


def acc(
    pred: Union[torch.FloatTensor, torch.DoubleTensor],
    target: Union[torch.FloatTensor, torch.DoubleTensor],
    climatology: Optional[Union[torch.FloatTensor, torch.DoubleTensor]],
    aggregate_only: bool = False,
    lat_weights: Optional[Union[torch.FloatTensor, torch.DoubleTensor]] = None,
) -> Union[torch.FloatTensor, torch.DoubleTensor]:
    pred = pred - climatology
    target = target - climatology
    per_channel_acc = []
    for i in range(pred.shape[1]):
        pred_prime = pred[:,i] - pred[:,i].mean()
        target_prime = target[:,i] - target[:,i].mean()
        numer = (lat_weights * pred_prime * target_prime).sum()
        denom1 = (lat_weights * pred_prime.square()).sum()
        denom2 = (lat_weights * target_prime.square()).sum()
        per_channel_acc.append(numer / (denom1 * denom2).sqrt())
    per_channel_acc = torch.stack(per_channel_acc)
    result = per_channel_acc.mean()
    if aggregate_only:
        return result
    return torch.cat((per_channel_acc, result.unsqueeze(0)))


def pearson(
    pred: Union[torch.FloatTensor, torch.DoubleTensor],
    target: Union[torch.FloatTensor, torch.DoubleTensor],
    aggregate_only: bool = False,
) -> Union[torch.FloatTensor, torch.DoubleTensor]:
    pred = _flatten_channel_wise(pred)
    target = _flatten_channel_wise(target)
    pred = pred - pred.mean(1, keepdims=True)
    target = target - target.mean(1, keepdims=True)
    per_channel_coeffs = F.cosine_similarity(pred, target)
    coeff = torch.mean(per_channel_coeffs)
    if not aggregate_only:
        coeff = coeff.unsqueeze(0)
        coeff = torch.cat((per_channel_coeffs, coeff))
    return coeff


def mean_bias(
    pred: Union[torch.FloatTensor, torch.DoubleTensor],
    target: Union[torch.FloatTensor, torch.DoubleTensor],
    aggregate_only: bool = False,
) -> Union[torch.FloatTensor, torch.DoubleTensor]:
    result = target.mean() - pred.mean()
    if not aggregate_only:
        per_channel_mean_bias = target.mean([0, 2, 3]) - pred.mean([0, 2, 3])
        result = result.unsqueeze(0)
        result = torch.cat((per_channel_mean_bias, result))
    return result


def _flatten_channel_wise(x: torch.Tensor) -> torch.Tensor:
    """
    :param x: A tensor of shape [B,C,H,W].
    :type x: torch.Tensor

    :return: A tensor of shape [C,B*H*W].
    :rtype: torch.Tensor
    """
    return torch.stack([xi.flatten() for xi in torch.tensor_split(x, 2, 1)])
