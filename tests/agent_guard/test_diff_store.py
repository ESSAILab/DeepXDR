from __future__ import annotations

import hashlib

import pytest

from ai_agent.agent_guard.diff_store import DiffEvidenceError, DiffRef, load_diff_text


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
