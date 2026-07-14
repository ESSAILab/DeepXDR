from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.agentguard_path_policy import validate_agentguard_paths


def test_validate_agentguard_paths_accepts_children(tmp_path):
    workspace_root = tmp_path / "workspaces"
    state_root = tmp_path / "state"
    workspace_root.mkdir()
    state_root.mkdir()

    workspace, state_home = validate_agentguard_paths(
        workspace=workspace_root / "project-a",
        state_home=state_root / "nono-run-1",
        workspace_root=workspace_root,
        state_root=state_root,
    )

    assert workspace == (workspace_root / "project-a").resolve()
    assert state_home == (state_root / "nono-run-1").resolve()


@pytest.mark.parametrize("field", ["workspace", "state_home"])
def test_validate_agentguard_paths_rejects_paths_outside_roots(tmp_path, field):
    workspace_root = tmp_path / "workspaces"
    state_root = tmp_path / "state"
    workspace_root.mkdir()
    state_root.mkdir()
    values = {
        "workspace": workspace_root / "project-a",
        "state_home": state_root / "nono-run-1",
    }
    values[field] = tmp_path / "outside"

    with pytest.raises(ValueError, match="outside configured root"):
        validate_agentguard_paths(
            **values,
            workspace_root=workspace_root,
            state_root=state_root,
        )


def test_validate_agentguard_paths_rejects_similar_prefix(tmp_path):
    workspace_root = tmp_path / "agents"
    state_root = tmp_path / "state"
    workspace_root.mkdir()
    state_root.mkdir()

    with pytest.raises(ValueError, match="outside configured root"):
        validate_agentguard_paths(
            workspace=tmp_path / "agents-escaped" / "project-a",
            state_home=state_root / "run-1",
            workspace_root=workspace_root,
            state_root=state_root,
        )


def test_validate_agentguard_paths_requires_absolute_existing_roots(tmp_path):
    with pytest.raises(ValueError, match="AGENTGUARD_WORKSPACE_ROOT must be an absolute path"):
        validate_agentguard_paths(
            workspace=tmp_path / "project-a",
            state_home=tmp_path / "state" / "run-1",
            workspace_root="relative/workspaces",
            state_root=tmp_path,
        )

    with pytest.raises(ValueError, match="AGENTGUARD_NONO_STATE_ROOT must be an existing directory"):
        validate_agentguard_paths(
            workspace=tmp_path / "project-a",
            state_home=tmp_path / "missing-state" / "run-1",
            workspace_root=tmp_path,
            state_root=tmp_path / "missing-state",
        )


@pytest.mark.parametrize("root_field", ["workspace_root", "state_root"])
def test_validate_agentguard_paths_rejects_host_root(tmp_path, root_field):
    workspace_root = tmp_path / "workspaces"
    state_root = tmp_path / "state"
    workspace_root.mkdir()
    state_root.mkdir()
    values = {
        "workspace": workspace_root / "project-a",
        "state_home": state_root / "run-1",
        "workspace_root": workspace_root,
        "state_root": state_root,
    }
    values[root_field] = Path("/")

    with pytest.raises(ValueError, match="must not be the host root directory"):
        validate_agentguard_paths(**values)


def test_validate_agentguard_paths_rejects_symlink_to_host_root(tmp_path):
    root_link = tmp_path / "root-link"
    root_link.symlink_to("/", target_is_directory=True)
    state_root = tmp_path / "state"
    state_root.mkdir()

    with pytest.raises(ValueError, match="must not be the host root directory"):
        validate_agentguard_paths(
            workspace=tmp_path / "workspace",
            state_home=state_root / "run-1",
            workspace_root=root_link,
            state_root=state_root,
        )


def test_validate_agentguard_paths_rejects_identical_roots(tmp_path):
    shared_root = tmp_path / "shared"
    shared_root.mkdir()

    with pytest.raises(ValueError, match="must be different directories"):
        validate_agentguard_paths(
            workspace=shared_root / "workspace",
            state_home=shared_root / "state",
            workspace_root=shared_root,
            state_root=shared_root,
        )


def test_validate_agentguard_paths_allows_nested_distinct_roots(tmp_path):
    workspace_root = tmp_path / "managed"
    state_root = workspace_root / "state"
    state_root.mkdir(parents=True)

    workspace, state_home = validate_agentguard_paths(
        workspace=workspace_root / "workspace",
        state_home=state_root / "run-1",
        workspace_root=workspace_root,
        state_root=state_root,
    )

    assert workspace == (workspace_root / "workspace").resolve()
    assert state_home == (state_root / "run-1").resolve()


def test_smoke_script_rejects_host_root_before_resetting_workspace(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = workspace / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    state_root = tmp_path / "state"
    state_root.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "DEEPXDR_REAL_NONO": "/bin/true",
            "AGENTGUARD_SMOKE_WORKSPACE": str(workspace),
            "DEEPXDR_NONO_STATE_HOME": str(state_root / "run-1"),
            "AGENTGUARD_WORKSPACE_ROOT": "/",
            "AGENTGUARD_NONO_STATE_ROOT": str(state_root),
        }
    )

    result = subprocess.run(
        [str(repo_root / "scripts" / "agentguard-smoke-nono.sh"), "small"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "must not be the host root directory" in result.stderr
    assert marker.read_text(encoding="utf-8") == "keep"


def test_agent_smoke_requires_api_key_before_resetting_workspace(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    workspace_root = tmp_path / "workspaces"
    workspace = workspace_root / "workspace"
    workspace.mkdir(parents=True)
    marker = workspace / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    state_root = tmp_path / "state"
    state_root.mkdir()
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.update(
        {
            "DEEPXDR_REAL_NONO": "/bin/true",
            "AGENTGUARD_SMOKE_WORKSPACE": str(workspace),
            "DEEPXDR_NONO_STATE_HOME": str(state_root / "run-1"),
            "AGENTGUARD_WORKSPACE_ROOT": str(workspace_root),
            "AGENTGUARD_NONO_STATE_ROOT": str(state_root),
        }
    )

    result = subprocess.run(
        [str(repo_root / "scripts" / "agentguard-smoke-nono.sh"), "agent"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Set OPENAI_API_KEY" in result.stderr
    assert marker.read_text(encoding="utf-8") == "keep"


def test_smoke_script_rejects_workspace_outside_configured_root(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    workspace_root = tmp_path / "allowed"
    state_root = tmp_path / "state"
    workspace_root.mkdir()
    state_root.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "DEEPXDR_REAL_NONO": "/bin/true",
            "AGENTGUARD_SMOKE_WORKSPACE": str(tmp_path / "outside" / "workspace"),
            "DEEPXDR_NONO_STATE_HOME": str(state_root / "run-1"),
            "AGENTGUARD_WORKSPACE_ROOT": str(workspace_root),
            "AGENTGUARD_NONO_STATE_ROOT": str(state_root),
        }
    )

    result = subprocess.run(
        [str(repo_root / "scripts" / "agentguard-smoke-nono.sh"), "small"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "workspace is outside configured root" in result.stderr
