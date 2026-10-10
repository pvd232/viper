"""Runtime tests for exact training-resume state."""

from __future__ import annotations

import pickle
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch
from torch.optim import Adam
from torch.utils.data import TensorDataset
from torchdata.stateful_dataloader import StatefulDataLoader

from tests.fixtures import resume_state
from viper.randomness import (
    capture_main_process_rng,
    restore_main_process_rng,
)
from viper.resume import (
    capture_resume_state,
    load_resume_state,
    restore_resume_state,
    save_resume_state,
)


def dataloader(workers: int) -> StatefulDataLoader:
    """Create the deterministic loader used before and after resume."""
    if workers > 0:
        return StatefulDataLoader(
            TensorDataset(torch.arange(24)),
            batch_size=3,
            shuffle=True,
            generator=torch.Generator().manual_seed(17),
            num_workers=workers,
            in_order=True,
            prefetch_factor=2,
            persistent_workers=False,
        )

    return StatefulDataLoader(
        TensorDataset(torch.arange(24)),
        batch_size=3,
        shuffle=True,
        generator=torch.Generator().manual_seed(17),
        num_workers=0,
        in_order=True,
    )


def train_updates(
    model: torch.nn.Module,
    optimizer: Adam,
    loader: StatefulDataLoader,
    count: int,
) -> None:
    """Apply an exact number of optimizer updates from the loader's position."""
    iterator = iter(loader)
    for _ in range(count):
        values = next(iterator)[0].to(dtype=torch.float32).reshape(-1, 1)
        targets = values * 2.0 + 1.0
        optimizer.zero_grad()
        loss = torch.nn.functional.mse_loss(model(values), targets)
        loss.backward()
        optimizer.step()


class ResumeTests(unittest.TestCase):
    """Verify exact process and DataLoader resume state."""

    def test_numpy_sampling_counters_round_trip(self) -> None:
        """Preserve numeric NumPy state without leaving safe globals enabled."""
        for dtype in (np.int32, np.uint64, np.float32, np.bool_):
            with self.subTest(dtype=dtype), tempfile.TemporaryDirectory() as directory:
                saved = resume_state()
                counters = np.array([0, 1, 1], dtype=dtype)
                saved.dataloader.state_dict["pool_seen"] = counters
                saved.optimizer_state["scalar"] = counters[0]
                path = Path(directory) / "resume.pt"
                globals_before = torch.serialization.get_safe_globals()
                save_resume_state(path, saved)
                loaded = load_resume_state(path)
                np.testing.assert_array_equal(
                    loaded.dataloader.state_dict["pool_seen"], counters
                )
                self.assertEqual(loaded.optimizer_state["scalar"], counters[0])
                self.assertCountEqual(
                    torch.serialization.get_safe_globals(), globals_before
                )
                with self.assertRaises(pickle.UnpicklingError):
                    torch.load(path, weights_only=True)

    def test_object_arrays_remain_rejected(self) -> None:
        """Keep arbitrary object state outside restricted resume deserialization."""
        with tempfile.TemporaryDirectory() as directory:
            saved = resume_state()
            saved.dataloader.state_dict["objects"] = np.array([1], dtype=object)
            path = Path(directory) / "resume.pt"
            save_resume_state(path, saved)
            with self.assertRaises(pickle.UnpicklingError):
                load_resume_state(path)

    def test_main_process_rng_round_trip(self) -> None:
        """Restore the next Python, NumPy, and PyTorch random values exactly."""
        random.seed(17)
        np.random.seed(17)
        torch.manual_seed(17)
        generators = {"training": np.random.default_rng(17)}

        saved = capture_main_process_rng(
            generators,
            capture_legacy_global=True,
        )
        expected = (
            random.random(),
            float(np.random.random()),
            float(generators["training"].random()),
            float(torch.rand(())),
        )

        random.random()
        np.random.random()
        generators["training"].random()
        torch.rand(())

        restore_main_process_rng(saved, generators)
        actual = (
            random.random(),
            float(np.random.random()),
            float(generators["training"].random()),
            float(torch.rand(())),
        )

        self.assertEqual(actual, expected)

    def test_training_resume_restores_next_batch(self) -> None:
        """Restore the next shuffled batch with zero or multiple workers."""
        for workers in (0, 2):
            with self.subTest(workers=workers):
                loader = dataloader(workers)
                optimizer = Adam([torch.nn.Parameter(torch.tensor(1.0))], lr=0.01)
                generators = {"training": np.random.default_rng(17)}
                iterator = iter(loader)
                next(iterator)

                resume = capture_resume_state(
                    optimizer,
                    loader,
                    generators,
                    capture_legacy_global=True,
                )
                expected_batch = next(iterator)[0]

                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "resume_state.pt"
                    save_resume_state(path, resume)
                    loaded = load_resume_state(path)

                restored_loader = dataloader(workers)
                restored_optimizer = Adam(
                    [torch.nn.Parameter(torch.tensor(1.0))],
                    lr=0.5,
                )
                restored_generators = {
                    "training": np.random.default_rng(999),
                }
                restore_resume_state(
                    loaded,
                    restored_optimizer,
                    restored_loader,
                    restored_generators,
                )

                actual_batch = next(iter(restored_loader))[0]
                self.assertTrue(torch.equal(actual_batch, expected_batch))
                self.assertEqual(
                    restored_optimizer.param_groups[0]["lr"],
                    0.01,
                )

    def test_resumed_training_matches_uninterrupted_terminal_state(self) -> None:
        """Match terminal parameters after one saved interruption boundary."""
        for workers in (0, 2):
            with self.subTest(workers=workers):
                torch.manual_seed(23)
                initial_model = torch.nn.Linear(1, 1)
                initial_parameters = {
                    name: value.detach().clone()
                    for name, value in initial_model.state_dict().items()
                }

                uninterrupted_model = torch.nn.Linear(1, 1)
                uninterrupted_model.load_state_dict(initial_parameters)
                uninterrupted_optimizer = Adam(
                    uninterrupted_model.parameters(),
                    lr=0.01,
                )
                uninterrupted_loader = dataloader(workers)
                train_updates(
                    uninterrupted_model,
                    uninterrupted_optimizer,
                    uninterrupted_loader,
                    4,
                )

                interrupted_model = torch.nn.Linear(1, 1)
                interrupted_model.load_state_dict(initial_parameters)
                interrupted_optimizer = Adam(
                    interrupted_model.parameters(),
                    lr=0.01,
                )
                interrupted_loader = dataloader(workers)
                generators = {"training": np.random.default_rng(17)}
                train_updates(
                    interrupted_model,
                    interrupted_optimizer,
                    interrupted_loader,
                    2,
                )
                saved_parameters = {
                    name: value.detach().clone()
                    for name, value in interrupted_model.state_dict().items()
                }
                resume = capture_resume_state(
                    interrupted_optimizer,
                    interrupted_loader,
                    generators,
                    capture_legacy_global=True,
                )

                resumed_model = torch.nn.Linear(1, 1)
                resumed_model.load_state_dict(saved_parameters)
                resumed_optimizer = Adam(resumed_model.parameters(), lr=0.5)
                resumed_loader = dataloader(workers)
                resumed_generators = {"training": np.random.default_rng(999)}
                restore_resume_state(
                    resume,
                    resumed_optimizer,
                    resumed_loader,
                    resumed_generators,
                )
                train_updates(
                    resumed_model,
                    resumed_optimizer,
                    resumed_loader,
                    2,
                )

                for name, expected in uninterrupted_model.state_dict().items():
                    torch.testing.assert_close(
                        resumed_model.state_dict()[name],
                        expected,
                        rtol=0,
                        atol=0,
                    )


if __name__ == "__main__":
    unittest.main()
