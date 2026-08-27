"""Compute Pearson correlation for evaluation measurements."""

import torch


def compute(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    dim: int = -1,
) -> torch.Tensor:
    """Return Pearson correlation along one dimension of equal-shaped tensors."""
    if predictions.shape != targets.shape:
        raise ValueError("predictions and targets must have the same shape")

    if predictions.ndim == 0 or predictions.shape[dim] < 2:
        raise ValueError("Pearson correlation requires at least two values")

    if predictions.device != targets.device:
        raise ValueError("predictions and targets must use the same device")

    if predictions.is_complex() or targets.is_complex():
        raise ValueError("predictions and targets must be real")
    if not predictions.isfinite().all() or not targets.isfinite().all():
        raise ValueError("predictions and targets must be finite")

    predictions = predictions.to(torch.float64)
    targets = targets.to(torch.float64)

    prediction_residuals = predictions - predictions.mean(dim=dim, keepdim=True)
    target_residuals = targets - targets.mean(dim=dim, keepdim=True)
    numerator = torch.sum(prediction_residuals * target_residuals, dim=dim)

    prediction_ss = torch.sum(prediction_residuals.square(), dim=dim)
    target_ss = torch.sum(target_residuals.square(), dim=dim)
    if torch.any(prediction_ss == 0) or torch.any(target_ss == 0):
        raise ValueError("Pearson correlation is undefined for a constant vector")

    denominator = (prediction_ss * target_ss).sqrt()
    return (numerator / denominator).clamp(-1, 1)
