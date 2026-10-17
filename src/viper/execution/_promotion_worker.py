"""Copy selected run graphs in a process with its own caches and HTTP pool."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field

from .._schema import AbsolutePath, ProtocolModel
from .._source import RunFetcher
from ..cloud import ViperCloud
from ..evidence import VerificationPolicy
from ..references import ResolvedRunRef
from ..runs import ResolvedRun, RunSpec
from ..serialization import document_digest, parse_yaml_bytes
from ..storage import (
    LocalArtifactStore,
    RunPromotionPolicy,
    TransferLimits,
    ViperCloudDestination,
)
from ..verification import verify_run_result
from ._promotion import PromotionInventory, RunGraphPromoter
from ._promotion_compare import GraphComparison
from ._promotion_journal import PublicationJournal
from ._promotion_transfer import TransferSpace
from ._publication import replace_synchronized
from .errors import RunPromotionError


class CopyRequest(ProtocolModel):
    """Describe one additional publication and its required source files."""

    schema_version: Literal[1] = Field(default=1, description="Copy request format.")
    repository_root: AbsolutePath = Field(
        description="Workspace used to read the original run and source code."
    )
    inventory: PromotionInventory = Field(
        description="Selected runs and required file identities."
    )
    policy: RunPromotionPolicy = Field(
        description="Cloud hosts receiving the additional graph."
    )
    destination: ViperCloudDestination = Field(
        description="Owner and workspace used inside each target host."
    )
    limits: TransferLimits = Field(
        description="Disk and connection budgets for the copy process."
    )
    trusted_source_repositories: frozenset[str] = Field(
        default_factory=frozenset,
        description="Additional code repositories permitted during verification.",
    )


def copy_graphs(request: CopyRequest) -> dict:
    """Discover, publish, and independently compare every requested graph."""
    root = request.repository_root.resolve(strict=True)
    operation = document_digest(request)
    directory = root / ".viper/promotion" / operation
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(dir=directory, prefix="work-") as work:
        space = TransferSpace(Path(work) / "files", request.limits)
        space.configure_network()
        for host in request.policy.hosts:
            target_directory = directory / document_digest(host)
            target_directory.mkdir(parents=True, exist_ok=True)
            cloud = ViperCloud(root, host)
            space.configure_cloud(cloud)
            fetcher = RunFetcher(
                root, LocalArtifactStore(root), "", cache_root=space.cache / "source"
            )
            with PublicationJournal(
                target_directory / "progress.json",
                operation,
                cloud,
                request.destination,
            ) as journal:
                promoter = RunGraphPromoter(
                    root,
                    cloud,
                    request.destination,
                    fetcher=fetcher,
                    journal=journal,
                    space=space,
                )
                order = promoter.discover_inventory(request.inventory)
                trusted = set(request.trusted_source_repositories)
                records = []
                for reference in request.inventory.roots:
                    record = ResolvedRun.model_validate(
                        parse_yaml_bytes(fetcher.read(reference))
                    )
                    plan = RunSpec.model_validate(
                        parse_yaml_bytes(fetcher.read(record.spec))
                    )
                    trusted.add(str(plan.source.repository))
                    if not fetcher.source_repository:
                        fetcher.source_repository = str(plan.source.repository)
                    records.append(record)
                policy = VerificationPolicy(
                    trusted_source_repositories=frozenset(trusted)
                )
                # Ordinary verification may load several related artifacts together.
                unique_sizes = {}
                for size, digest in promoter.source_files.values():
                    if digest is not None:
                        unique_sizes[digest] = size
                space.check(sum(unique_sizes.values()))
                for record in records:
                    verify_run_result(record, policy=policy, fetcher=fetcher)
                space.check()
                space.release(fetcher)
                for snapshot in order:
                    if (
                        snapshot in promoter.source_members
                        or snapshot in promoter.documents
                    ):
                        promoter.promote_snapshot(snapshot)
                published = []
                for reference in request.inventory.roots:
                    result = promoter.promote_reference(reference)
                    published.append(ResolvedRunRef(**result.model_dump()))
                source_check = RunFetcher(
                    root,
                    LocalArtifactStore(root),
                    fetcher.source_repository,
                    cache_root=space.cache / "source-check",
                )
                destination_check = RunFetcher(
                    root,
                    LocalArtifactStore(root),
                    fetcher.source_repository,
                    cache_root=space.cache / "destination-check",
                )
                documents = []
                for copy in journal.progress.copies.values():
                    for member in copy.source_files:
                        if member.path in promoter.documents.get(copy.source, {}):
                            documents.append(
                                promoter.file_in_snapshot(copy.source, member).stored_at
                            )
                comparison = GraphComparison(
                    tuple(journal.progress.copies.values()),
                    documents,
                    source_check,
                    destination_check,
                    destination_repository=host,
                    space=space,
                ).verify(request.inventory.roots, request.inventory.required_files)
                # Save the comparison before the more expensive loader checks.
                replace_synchronized(
                    target_directory / "comparison.json",
                    (json.dumps(comparison, sort_keys=True, indent=2) + "\n").encode(),
                )
                for reference in published:
                    record = ResolvedRun.model_validate(
                        parse_yaml_bytes(destination_check.read(reference))
                    )
                    verify_run_result(record, policy=policy, fetcher=destination_check)
                space.check()
                space.release(destination_check)
                receipt = {
                    **comparison,
                    "operation_sha256": operation,
                    "inventory_sha256": document_digest(request.inventory),
                    "policy_sha256": document_digest(request.policy),
                    "mapping_sha256": document_digest(journal.progress),
                    "host": host.model_dump(mode="json"),
                    "peak_staging_bytes": space.peak_bytes,
                    "peak_cache_bytes": space.peak_cache_bytes,
                    "connection_limit": request.limits.connections,
                    "source_settings_changed": False,
                }
                replace_synchronized(
                    target_directory / "verified.json",
                    (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode(),
                )
                results.append(receipt)
    result = {
        "schema_version": 1,
        "operation_sha256": operation,
        "publications": results,
    }
    replace_synchronized(
        directory / "result.json",
        (json.dumps(result, sort_keys=True, indent=2) + "\n").encode(),
    )
    return result


def main() -> None:
    """Read one copy request from stdin and report its verified publications."""
    request = CopyRequest.model_validate_json(sys.stdin.buffer.read())
    result = copy_graphs(request)
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = (
            str(error) if isinstance(error, RunPromotionError) else type(error).__name__
        )
        print(
            json.dumps({"error": message, "cause": type(error.__cause__).__name__}),
            file=sys.stderr,
        )
        raise SystemExit(1) from None
