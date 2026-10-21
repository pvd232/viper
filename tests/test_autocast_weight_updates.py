"""Keep updated weights visible throughout worker precision contexts."""

from typing import Literal

import pytest
import torch

from viper.runtime import autocast_context, resolve_execution_policy


@pytest.mark.parametrize("backend", ["cpu", "cuda"])
@pytest.mark.parametrize("worker_autocast", [False, True])
def test_worker_autocast_refreshes_updated_weights(
    backend: Literal["cpu", "cuda"], worker_autocast: bool
) -> None:
    """Observe a weight update through user or worker controlled autocast."""
    if backend == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA device required")
    _, settings = resolve_execution_policy()
    if worker_autocast:
        settings = settings.model_copy(
            update={
                "precision": settings.precision.model_copy(
                    update={"autocast_enabled": True, "autocast_dtype": "bfloat16"}
                )
            }
        )
    layer = torch.nn.Linear(4, 4, bias=False, device=backend)
    inputs = torch.ones(1, 4, device=backend)
    with torch.no_grad():
        layer.weight.copy_(torch.eye(4, device=backend))
    with autocast_context(settings, backend=backend):
        with torch.autocast(backend, dtype=torch.bfloat16):
            before = layer(inputs).detach().float()
        with torch.no_grad():
            layer.weight.mul_(2)
        with torch.autocast(backend, dtype=torch.bfloat16):
            after = layer(inputs).detach().float()
    torch.testing.assert_close(after, 2 * before)


@pytest.mark.parametrize("backend", ["cpu", "cuda"])
@pytest.mark.parametrize("worker_autocast", [False, True])
def test_worker_autocast_allows_multiple_backward_steps(
    backend: Literal["cpu", "cuda"], worker_autocast: bool
) -> None:
    """Build a fresh gradient graph after every optimizer update."""
    if backend == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA device required")
    _, settings = resolve_execution_policy()
    if worker_autocast:
        settings = settings.model_copy(
            update={
                "precision": settings.precision.model_copy(
                    update={"autocast_enabled": True, "autocast_dtype": "bfloat16"}
                )
            }
        )
    layer = torch.nn.Linear(4, 4, bias=False, device=backend)
    optimizer = torch.optim.SGD(layer.parameters(), lr=0.1)
    inputs = torch.ones(1, 4, device=backend)
    losses = []
    with autocast_context(settings, backend=backend):
        for _ in range(3):
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(backend, dtype=torch.bfloat16):
                loss = layer(inputs).float().square().mean()
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
    assert losses[2] < losses[0]


def test_worker_autocast_restores_callers_cache_setting() -> None:
    """Restore the process cache setting when the worker context exits."""
    _, settings = resolve_execution_policy()
    settings = settings.model_copy(
        update={
            "precision": settings.precision.model_copy(
                update={"autocast_enabled": True, "autocast_dtype": "bfloat16"}
            )
        }
    )
    original = torch.is_autocast_cache_enabled()
    with autocast_context(settings, backend="cpu"):
        assert torch.is_autocast_cache_enabled() is False
    assert torch.is_autocast_cache_enabled() is original
