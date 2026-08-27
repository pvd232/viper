"""Tests for source-controlled metric implementations."""

import unittest

import torch
from example_project.metrics.evaluation.pearson_correlation.compute import (
    compute as pearson_correlation,
)
from example_project.metrics.training.mean_squared_error.compute import (
    compute as mean_squared_error,
)


class MetricImplementationTests(unittest.TestCase):
    """Verify metric values and their input validation."""

    def test_mean_squared_error_returns_scalar_average(self) -> None:
        """Average squared error across every tensor element."""
        predictions = torch.tensor([1.0, 3.0])
        targets = torch.tensor([1.0, 1.0])

        self.assertEqual(mean_squared_error(predictions, targets).item(), 2.0)

    def test_pearson_correlation_uses_selected_dimension(self) -> None:
        """Compute one perfect correlation for each prediction row."""
        predictions = torch.tensor([[1.0, 2.0], [4.0, 2.0]])
        targets = torch.tensor([[2.0, 4.0], [8.0, 4.0]])

        actual = pearson_correlation(predictions, targets, dim=1)

        torch.testing.assert_close(actual, torch.ones(2, dtype=torch.float64))

    def test_metrics_reject_nonfinite_values(self) -> None:
        """Reject nonfinite prediction or target values before reduction."""
        predictions = torch.tensor([1.0, float("nan")])
        targets = torch.tensor([1.0, 2.0])

        with self.assertRaisesRegex(ValueError, "finite"):
            mean_squared_error(predictions, targets)
