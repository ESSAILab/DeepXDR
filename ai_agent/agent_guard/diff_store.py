from __future__ import annotations

import hashlib
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse


class DiffEvidenceError(RuntimeError):
    """Raised when diff evidence cannot be trusted or loaded."""


@dataclass(frozen=True)
class DiffRef:
    storage: str
    uri: str
    sha256: str


@dataclass(frozen=True)
class S3DiffEvidenceStore:
    client: object
    bucket: str
    prefix: str = ""
    storage: str = "s3"

    def write(self, *, run_id: str, diff_text: str) -> dict:
        body = diff_text.encode("utf-8")
        key = self._key_for_run(run_id)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="text/x-diff; charset=utf-8",
            Metadata={"sha256": hashlib.sha256(body).hexdigest()},
        )
        return {
            "storage": self.storage,
            "uri": f"{self.storage}://{self.bucket}/{key}",
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
        }

    def read_text(self, diff_ref: DiffRef, *, max_bytes: int | None = None) -> str:
        bucket, key = _parse_object_uri(diff_ref.uri)
        if bucket != self.bucket:
            raise DiffEvidenceError(f"unexpected diff evidence bucket: {bucket}")
        try:
            size = int(self.client.head_object(Bucket=bucket, Key=key).get("ContentLength", 0))
        except Exception as exc:
            raise DiffEvidenceError(f"failed to stat diff evidence object: {exc}") from exc
        if max_bytes is not None and size > max_bytes:
            raise DiffEvidenceError(f"diff evidence exceeds max bytes: {size} > {max_bytes}")

        try:
            body = self.client.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as exc:
            raise DiffEvidenceError(f"failed to read diff evidence object: {exc}") from exc
        if max_bytes is not None and len(body) > max_bytes:
            raise DiffEvidenceError(f"diff evidence exceeds max bytes: {len(body)} > {max_bytes}")

        text = body.decode("utf-8")
        _verify_sha256(text, diff_ref.sha256)
        return text

    def _key_for_run(self, run_id: str) -> str:
        safe_run_id = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in run_id)
        filename = f"{safe_run_id}.diff"
        return f"{self.prefix.strip('/')}/{filename}" if self.prefix.strip("/") else filename


def create_boto3_diff_store(
    *,
    bucket: str,
    prefix: str = "",
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region_name: str | None = None,
    storage: str = "s3",
) -> S3DiffEvidenceStore:
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region_name,
    )
    return S3DiffEvidenceStore(client=client, bucket=bucket, prefix=prefix, storage=storage)


def load_diff_text(
    diff_ref: DiffRef,
    object_reader: Callable[[str], str] | None = None,
    *,
    max_bytes: int | None = None,
) -> str:
    if diff_ref.storage == "local":
        if max_bytes is not None:
            size = Path(diff_ref.uri).stat().st_size
            if size > max_bytes:
                raise DiffEvidenceError(f"diff evidence exceeds max bytes: {size} > {max_bytes}")
        text = Path(diff_ref.uri).read_text(encoding="utf-8")
    elif diff_ref.storage in {"s3", "minio"}:
        if object_reader is None:
            raise DiffEvidenceError(f"object reader is required for {diff_ref.storage} diff evidence")
        text = object_reader(diff_ref.uri)
        if max_bytes is not None and len(text.encode("utf-8")) > max_bytes:
            raise DiffEvidenceError(
                f"diff evidence exceeds max bytes: {len(text.encode('utf-8'))} > {max_bytes}"
            )
    else:
        raise DiffEvidenceError(f"unsupported diff storage: {diff_ref.storage}")
    _verify_sha256(text, diff_ref.sha256)
    return text


def _parse_object_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme not in {"s3", "minio"} or not parsed.netloc or not parsed.path:
        raise DiffEvidenceError(f"invalid diff evidence object uri: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _verify_sha256(text: str, expected: str) -> None:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != expected:
        raise DiffEvidenceError("sha256 mismatch for diff evidence")
