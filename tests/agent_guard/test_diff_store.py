from __future__ import annotations

import hashlib

import pytest

from ai_agent.agent_guard.diff_store import (
    DiffEvidenceError,
    DiffRef,
    S3DiffEvidenceStore,
    load_diff_text,
)


def test_load_diff_text_reads_local_file_and_verifies_sha256(tmp_path):
    diff_text = "diff --git a/README.md b/README.md\n+hello\n"
    path = tmp_path / "run.diff"
    path.write_text(diff_text, encoding="utf-8")
    digest = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()

    loaded = load_diff_text(DiffRef(storage="local", uri=str(path), sha256=digest))

    assert loaded == diff_text


def test_load_diff_text_rejects_sha256_mismatch(tmp_path):
    path = tmp_path / "run.diff"
    path.write_text("diff --git a/app.py b/app.py\n+unsafe\n", encoding="utf-8")

    with pytest.raises(DiffEvidenceError, match="sha256 mismatch"):
        load_diff_text(DiffRef(storage="local", uri=str(path), sha256="0" * 64))


def test_load_diff_text_supports_s3_like_storage_with_injected_reader():
    diff_text = "diff --git a/app.py b/app.py\n+change\n"
    digest = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()

    loaded = load_diff_text(
        DiffRef(storage="s3", uri="s3://bucket/run.diff", sha256=digest),
        object_reader=lambda uri: diff_text,
    )

    assert loaded == diff_text


def test_load_diff_text_rejects_evidence_larger_than_limit(tmp_path):
    diff_text = "diff --git a/app.py b/app.py\n+" + ("x" * 20)
    path = tmp_path / "run.diff"
    path.write_text(diff_text, encoding="utf-8")
    digest = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()

    with pytest.raises(DiffEvidenceError, match="exceeds max bytes"):
        load_diff_text(DiffRef(storage="local", uri=str(path), sha256=digest), max_bytes=10)


class FakeS3Client:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

    def head_object(self, **kwargs):
        body = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"ContentLength": len(body)}

    def get_object(self, **kwargs):
        from io import BytesIO

        body = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"Body": BytesIO(body)}


def test_s3_diff_evidence_store_writes_s3_uri_and_reads_with_size_limit():
    client = FakeS3Client()
    store = S3DiffEvidenceStore(client=client, bucket="agent-diffs", prefix="diffs")
    diff_text = "diff --git a/README.md b/README.md\n+hello\n"

    diff_ref = store.write(run_id="run-1", diff_text=diff_text)

    assert diff_ref["storage"] == "s3"
    assert diff_ref["uri"] == "s3://agent-diffs/diffs/run-1.diff"
    assert store.read_text(DiffRef(**{k: diff_ref[k] for k in ("storage", "uri", "sha256")}), max_bytes=1024) == diff_text


def test_s3_diff_evidence_store_rejects_remote_object_larger_than_limit():
    client = FakeS3Client()
    store = S3DiffEvidenceStore(client=client, bucket="agent-diffs", prefix="diffs")
    diff_ref = store.write(run_id="run-1", diff_text="diff\n+" + ("x" * 50))

    with pytest.raises(DiffEvidenceError, match="exceeds max bytes"):
        store.read_text(DiffRef(**{k: diff_ref[k] for k in ("storage", "uri", "sha256")}), max_bytes=10)
