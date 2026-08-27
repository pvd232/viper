"""Compute mean squared error for training measurements."""

import torch


def compute(predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    """Return scalar mean squared error for equal-shaped real tensors."""
    if predictions.shape != targets.shape:
        raise ValueError("predictions and targets must have the same shape")

    if predictions.numel() == 0:
        raise ValueError("mean squared error requires at least one value")

    if predictions.device != targets.device:
        raise ValueError("predictions and targets must use the same device")

    if predictions.is_complex() or targets.is_complex():
        raise ValueError("predictions and targets must be real")
    if not predictions.isfinite().all() or not targets.isfinite().all():
        raise ValueError("predictions and targets must be finite")

    return (predictions.to(torch.float64) - targets.to(torch.float64)).square().mean()
