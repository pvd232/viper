"""Check disk space before copying saved experiment files."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import httpx
from huggingface_hub import constants, set_client_factory
from requests.adapters import HTTPAdapter

from .._source import RunFetcher
from ..cloud import ViperCloud
from ..gcs import GcsProvider
from ..huggingface import HuggingFaceProvider
from ..storage import TransferLimits
from .errors import RunPromotionError


def directory_bytes(root: Path) -> int:
    """Count file bytes once per inode, including temporary downloads."""
    return _directory_totals(root)[0]


def _directory_totals(root: Path, cache: Path | None = None) -> tuple[int, int]:
    """Count staging and nested cache bytes in one walk with separate inode sets."""
    seen = set()
    cache_seen = set()
    size = cached = 0
    directories = [(root, root == cache)] if root.is_dir() else []
    while directories:
        directory, in_cache = directories.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    path = Path(entry.path)
                    boundary = (
                        cache
                        if cache is not None and (in_cache or path == cache)
                        else root
                    )
                    if not path.resolve().is_relative_to(boundary):
                        raise RunPromotionError(
                            "cached file escapes the copy directory"
                        )
                elif entry.is_dir(follow_symlinks=False):
                    path = Path(entry.path)
                    directories.append((path, in_cache or path == cache))
                if entry.is_file():
                    stat = entry.stat()
                    identity = (stat.st_dev, stat.st_ino)
                    if identity not in seen:
                        seen.add(identity)
                        size += stat.st_size
                    if in_cache and identity not in cache_seen:
                        cache_seen.add(identity)
                        cached += stat.st_size
    return size, cached


class TransferSpace:
    """Reserve space for a snapshot and its destination verification."""

    def __init__(self, root: Path, limits: TransferLimits) -> None:
        """Use a new directory for this copy's temporary files."""
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        self.cache = self.root / "cache"
        self.limits = limits
        self.peak_bytes = 0
        self.peak_cache_bytes = 0
        self._configured: set[ViperCloud] = set()

    def check(
        self,
        snapshot_bytes: int = 0,
        largest_file: int = 0,
        *,
        reclaim: RunFetcher | None = None,
    ) -> None:
        """Reserve space, releasing owned downloads only when a budget requires it."""
        current, cached = _directory_totals(self.root, self.cache)
        self.peak_bytes = max(self.peak_bytes, current)
        self.peak_cache_bytes = max(self.peak_cache_bytes, cached)
        required = snapshot_bytes + largest_file
        if current + required > self.limits.staging_bytes:
            failure = "staging budget is insufficient"
        elif cached + snapshot_bytes > self.limits.cache_bytes:
            failure = "cache budget is insufficient"
        elif required > shutil.disk_usage(self.root).free:
            failure = "available disk space is insufficient"
        else:
            return
        if reclaim is None:
            raise RunPromotionError(failure)
        self.release(reclaim)
        self.check(snapshot_bytes, largest_file)

    def configure_cloud(self, cloud: ViperCloud) -> None:
        """Use one upload worker and stream files into the copy directory."""
        if cloud in self._configured:
            return
        provider = cloud.provider
        if isinstance(provider, HuggingFaceProvider):
            provider.stream_files = True
            provider.upload_threads = 1
            provider.cache_dir = self.cache / "destination-hub"
        elif isinstance(provider, GcsProvider):
            provider.max_workers = 1
            provider.sliced_fetch_min_bytes = sys.maxsize
            provider.client._http.mount(
                "https://",
                HTTPAdapter(
                    pool_connections=2,
                    pool_maxsize=self.limits.connections,
                    pool_block=True,
                ),
            )

        self._configured.add(cloud)

    def prepare_reader(self, fetcher: RunFetcher) -> None:
        """Configure the source clients used by the selected graph."""
        if not fetcher.cache_root.is_relative_to(self.cache):
            raise RunPromotionError("source reader must use the copy's cache")
        for cloud in fetcher._cloud_services.values():
            self.configure_cloud(cloud)

    def release(self, fetcher: RunFetcher) -> None:
        """Remove owned downloads after the caller checks peak usage and limits."""
        if not fetcher.cache_root.is_relative_to(self.cache):
            raise RunPromotionError("cleanup requires the copy's cache")
        cache = fetcher._verified_objects
        completed = {}
        for reference, path in fetcher._verified_paths.items():
            if path.is_relative_to(cache.root):
                if path != cache.path(reference) or path.is_symlink():
                    raise RunPromotionError("cached file path changed")
                completed[reference] = path
        for path in set(completed.values()):
            path.unlink(missing_ok=True)
        for reference in completed:
            del fetcher._verified_paths[reference]

    def configure_network(self) -> None:
        """Use a small shared HTTP pool in the dedicated copy process."""
        if not constants.HF_HUB_DISABLE_XET:
            raise RunPromotionError("copy process requires HF_HUB_DISABLE_XET=1")
        connections = self.limits.connections

        def client() -> httpx.Client:
            """Create the HTTP client used for Hub calls and file reads."""
            return httpx.Client(
                limits=httpx.Limits(
                    max_connections=connections,
                    max_keepalive_connections=connections,
                    keepalive_expiry=120,
                ),
                timeout=httpx.Timeout(120, connect=20),
                follow_redirects=True,
            )

        set_client_factory(client)
