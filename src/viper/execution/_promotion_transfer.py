"""Check disk space before copying saved experiment files."""

from __future__ import annotations

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
    seen = set()
    size = 0
    if root.exists():
        for path in root.rglob("*"):
            if path.is_symlink() and not path.resolve().is_relative_to(root):
                raise RunPromotionError("cached file escapes the copy directory")
            if path.is_file():
                stat = path.stat()
                identity = (stat.st_dev, stat.st_ino)
                if identity not in seen:
                    seen.add(identity)
                    size += stat.st_size
    return size


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

    def check(self, snapshot_bytes: int = 0, largest_file: int = 0) -> None:
        """Check current use and reserve space for files awaiting verification."""
        current = directory_bytes(self.root)
        cached = directory_bytes(self.cache)
        self.peak_bytes = max(self.peak_bytes, current)
        self.peak_cache_bytes = max(self.peak_cache_bytes, cached)
        required = snapshot_bytes + largest_file
        if current + required > self.limits.staging_bytes:
            raise RunPromotionError("staging budget is insufficient")
        if cached + snapshot_bytes > self.limits.cache_bytes:
            raise RunPromotionError("cache budget is insufficient")
        if required > shutil.disk_usage(self.root).free:
            raise RunPromotionError("available disk space is insufficient")

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
        """Remove verified downloads owned by this copy after publication succeeds."""
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
        self.check()

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
