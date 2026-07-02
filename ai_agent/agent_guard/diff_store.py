from __future__ import annotations

import hashlib
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path


class DiffEvidenceError(RuntimeError):
    """Raised when diff evidence cannot be trusted or loaded."""


@dataclass(frozen=True)
class DiffRef:
    storage: str
    uri: str
    sha256: str


def load_diff_text(diff_ref: DiffRef, object_reader: Callable[[str], str] | None = None) -> str:
    if diff_ref.storage == "local":
        text = Path(diff_ref.uri).read_text(encoding="utf-8")
    elif diff_ref.storage in {"s3", "minio"}:
        if object_reader is None:
            raise DiffEvidenceError(f"object reader is required for {diff_ref.storage} diff evidence")
        text = object_reader(diff_ref.uri)
    else:
        raise DiffEvidenceError(f"unsupported diff storage: {diff_ref.storage}")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != diff_ref.sha256:
        raise DiffEvidenceError("sha256 mismatch for diff evidence")
    return text
