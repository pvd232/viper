"""Execute the pinned learned journal encoder in a separate numerical process."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from transformers import AutoModel, AutoTokenizer

from .journals import JournalEncodingResult
from .knowledge import JournalEncoderFile, JournalEncoderSpec, JournalEncoding
from .serialization import document_digest

MODEL_ID = "Qwen/Qwen3-Embedding-0.6B"
REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"


def _file_identity(snapshot: Path, path: Path) -> JournalEncoderFile:
    """Hash one downloaded model file while closing its file descriptor."""
    with path.open("rb") as stream:
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    return JournalEncoderFile(
        path=path.relative_to(snapshot).as_posix(),
        sha256=sha256,
        bytes=path.stat().st_size,
    )


def encode(texts: tuple[str, ...]) -> JournalEncodingResult:
    """Encode exact text with untruncated last-token pooling and L2 normalization."""
    if not texts or any(not text for text in texts):
        raise ValueError("journal encoder requires nonempty passages")
    snapshot = Path(
        snapshot_download(
            MODEL_ID,
            revision=REVISION,
            allow_patterns=["*.safetensors", "*.json", "*.txt"],
        )
    )
    files = tuple(
        _file_identity(snapshot, path)
        for path in sorted(snapshot.rglob("*"))
        if path.is_file() and path.suffix in {".json", ".txt", ".safetensors"}
    )
    encoder = JournalEncoderSpec(
        files=files,
        transformers_version=version("transformers"),
        torch_version=version("torch"),
        python_version=platform.python_version(),
        platform=platform.platform(),
        tokenizers_version=version("tokenizers"),
        safetensors_version=version("safetensors"),
    )
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True)
    tokenizer = AutoTokenizer.from_pretrained(
        snapshot, padding_side="left", local_files_only=True, trust_remote_code=False
    )
    model = AutoModel.from_pretrained(
        snapshot,
        dtype=torch.float32,
        attn_implementation="eager",
        local_files_only=True,
        trust_remote_code=False,
    ).eval()
    values: list[tuple[float, ...]] = []
    encodings: list[JournalEncoding] = []
    for text in texts:
        tokens = tokenizer(text, return_tensors="pt", truncation=False)
        count = tokens["input_ids"].shape[1]
        if count > encoder.max_tokens:
            raise ValueError(
                "journal passage exceeds 8192 tokens; split it into paragraphs"
            )
        with torch.inference_mode():
            hidden = model(**tokens).last_hidden_state[:, -1, :]
            vector = torch.nn.functional.normalize(hidden, p=2, dim=1)[0]
        values.append(tuple(vector.tolist()))
        encodings.append(
            JournalEncoding(
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                encoder_sha256=document_digest(encoder),
                token_count=count,
            )
        )
    return JournalEncodingResult(
        encoder=encoder, values=tuple(values), encodings=tuple(encodings)
    )


def main() -> None:
    """Read exact passages from stdin and emit a typed encoding result."""
    payload = json.load(sys.stdin)
    texts = payload["texts"]
    if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
        raise ValueError("texts must be an array of strings")
    print(encode(tuple(texts)).model_dump_json())


if __name__ == "__main__":
    main()
