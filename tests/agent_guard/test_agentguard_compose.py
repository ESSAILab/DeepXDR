from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose-agentguard.yml"
ALL_IN_ONE_COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose-agent-all-in-one.yml"
COMPOSE_WRAPPER = REPO_ROOT / "scripts" / "agentguard-compose"
WORKSPACE_ROOT_EXPR = "${AGENTGUARD_WORKSPACE_ROOT:?AGENTGUARD_WORKSPACE_ROOT must be set}"
STATE_ROOT_EXPR = "${AGENTGUARD_NONO_STATE_ROOT:?AGENTGUARD_NONO_STATE_ROOT must be set}"
VALIDATED_EXPR = "${AGENTGUARD_PATHS_VALIDATED:?Use scripts/agentguard-compose to validate host rollback paths}"


def _compose_env(tmp_path: Path) -> dict[str, str]:
    workspace_root = tmp_path / "workspaces"
    state_root = tmp_path / "state"
    workspace_root.mkdir(exist_ok=True)
    state_root.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "AGENTGUARD_WORKSPACE_ROOT": str(workspace_root.resolve()),
            "AGENTGUARD_NONO_STATE_ROOT": str(state_root.resolve()),
            "AGENTGUARD_PATHS_VALIDATED": "1",
            "OPENAI_MODEL": "test-model",
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BASE_URL": "http://llm.invalid/v1",
        }
    )
    return env


@pytest.mark.parametrize("compose_file", [COMPOSE_FILE, ALL_IN_ONE_COMPOSE_FILE])
def test_ai_agent_mounts_configured_workspace_and_state_roots_at_same_paths(compose_file):
    config = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    mounts = config["services"]["ai-agent"]["volumes"]

    assert {
        "type": "bind",
        "source": WORKSPACE_ROOT_EXPR,
        "target": WORKSPACE_ROOT_EXPR,
    } in mounts
    assert config["services"]["ai-agent"]["environment"]["AGENTGUARD_PATHS_VALIDATED"] == VALIDATED_EXPR
    assert {
        "type": "bind",
        "source": STATE_ROOT_EXPR,
        "target": STATE_ROOT_EXPR,
    } in mounts


def test_all_in_one_ai_agent_mounts_nono_runtime():
    config = yaml.safe_load(ALL_IN_ONE_COMPOSE_FILE.read_text(encoding="utf-8"))
    mounts = config["services"]["ai-agent"]["volumes"]

    assert "/root/.local/bin/nono:/usr/local/bin/nono:ro" in mounts
    assert "/lib64:/lib64:ro" in mounts
    assert "/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:ro" in mounts


@pytest.mark.skipif(shutil.which("docker-compose") is None, reason="docker-compose is unavailable")
@pytest.mark.parametrize(
    ("missing_variable", "expected_error"),
    [
        ("AGENTGUARD_WORKSPACE_ROOT", "AGENTGUARD_WORKSPACE_ROOT must be set"),
        ("AGENTGUARD_NONO_STATE_ROOT", "AGENTGUARD_NONO_STATE_ROOT must be set"),
    ],
)
def test_compose_requires_host_rollback_roots(tmp_path, missing_variable, expected_error):
    env = _compose_env(tmp_path)
    env.pop(missing_variable)

    result = subprocess.run(
        ["docker-compose", "-f", str(COMPOSE_FILE), "config", "--quiet"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr


@pytest.mark.skipif(shutil.which("docker-compose") is None, reason="docker-compose is unavailable")
def test_compose_renders_same_absolute_host_paths(tmp_path):
    env = _compose_env(tmp_path)

    result = subprocess.run(
        ["docker-compose", "-f", str(COMPOSE_FILE), "config"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    rendered = yaml.safe_load(result.stdout)
    mounts = rendered["services"]["ai-agent"]["volumes"]
    expected_paths = {
        env["AGENTGUARD_WORKSPACE_ROOT"],
        env["AGENTGUARD_NONO_STATE_ROOT"],
    }
    actual_same_path_mounts = {
        mount["source"]
        for mount in mounts
        if isinstance(mount, dict) and mount.get("source") == mount.get("target")
    }
    assert expected_paths <= actual_same_path_mounts


@pytest.mark.skipif(shutil.which("docker-compose") is None, reason="docker-compose is unavailable")
def test_compose_requires_validated_path_marker(tmp_path):
    env = _compose_env(tmp_path)
    env.pop("AGENTGUARD_PATHS_VALIDATED")

    result = subprocess.run(
        ["docker-compose", "-f", str(COMPOSE_FILE), "config", "--quiet"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Use scripts/agentguard-compose to validate host rollback paths" in result.stderr


def _fake_compose_path(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker = bin_dir / "docker"
    fake_docker.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake_docker.chmod(0o755)
    fake_compose = bin_dir / "docker-compose"
    fake_compose.write_text(
        """#!/bin/sh
{
  printf '%s\\n' "$AGENTGUARD_WORKSPACE_ROOT"
  printf '%s\\n' "$AGENTGUARD_NONO_STATE_ROOT"
  printf '%s\\n' "$AGENTGUARD_PATHS_VALIDATED"
  printf '%s\\n' "$@"
} > "$AGENTGUARD_TEST_CAPTURE"
""",
        encoding="utf-8",
    )
    fake_compose.chmod(0o755)
    return bin_dir


def test_agentguard_compose_validates_and_canonicalizes_roots(tmp_path):
    workspace_root = tmp_path / "actual-workspaces"
    state_root = tmp_path / "actual-state"
    workspace_root.mkdir()
    state_root.mkdir()
    workspace_link = tmp_path / "workspace-link"
    state_link = tmp_path / "state-link"
    workspace_link.symlink_to(workspace_root, target_is_directory=True)
    state_link.symlink_to(state_root, target_is_directory=True)
    capture = tmp_path / "compose-call.txt"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{_fake_compose_path(tmp_path)}:{env['PATH']}",
            "AGENTGUARD_WORKSPACE_ROOT": str(workspace_link),
            "AGENTGUARD_NONO_STATE_ROOT": str(state_link),
            "AGENTGUARD_TEST_CAPTURE": str(capture),
        }
    )

    result = subprocess.run(
        [str(COMPOSE_WRAPPER), "config", "--quiet"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = capture.read_text(encoding="utf-8").splitlines()
    assert lines[:3] == [str(workspace_root.resolve()), str(state_root.resolve()), "1"]
    assert lines[3:] == ["-f", str(COMPOSE_FILE), "config", "--quiet"]


def test_agentguard_compose_selects_all_in_one_file(tmp_path):
    workspace_root = tmp_path / "workspaces"
    state_root = tmp_path / "state"
    workspace_root.mkdir()
    state_root.mkdir()
    capture = tmp_path / "compose-call.txt"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{_fake_compose_path(tmp_path)}:{env['PATH']}",
            "AGENTGUARD_WORKSPACE_ROOT": str(workspace_root),
            "AGENTGUARD_NONO_STATE_ROOT": str(state_root),
            "AGENTGUARD_COMPOSE_FILE": "deploy/docker-compose-agent-all-in-one.yml",
            "AGENTGUARD_TEST_CAPTURE": str(capture),
        }
    )

    result = subprocess.run(
        [str(COMPOSE_WRAPPER), "config", "--quiet"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = capture.read_text(encoding="utf-8").splitlines()
    assert lines[3:] == ["-f", str(ALL_IN_ONE_COMPOSE_FILE), "config", "--quiet"]


def test_agentguard_compose_rejects_unapproved_compose_file(tmp_path):
    workspace_root = tmp_path / "workspaces"
    state_root = tmp_path / "state"
    workspace_root.mkdir()
    state_root.mkdir()
    capture = tmp_path / "compose-call.txt"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{_fake_compose_path(tmp_path)}:{env['PATH']}",
            "AGENTGUARD_WORKSPACE_ROOT": str(workspace_root),
            "AGENTGUARD_NONO_STATE_ROOT": str(state_root),
            "AGENTGUARD_COMPOSE_FILE": "deploy/docker-compose-unapproved.yml",
            "AGENTGUARD_TEST_CAPTURE": str(capture),
        }
    )

    result = subprocess.run(
        [str(COMPOSE_WRAPPER), "config", "--quiet"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Unsupported AgentGuard Compose file" in result.stderr
    assert not capture.exists()


def test_agentguard_compose_rejects_unsafe_roots_before_docker(tmp_path):
    valid_workspace = tmp_path / "workspaces"
    valid_state = tmp_path / "state"
    valid_workspace.mkdir()
    valid_state.mkdir()
    capture = tmp_path / "compose-call.txt"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{_fake_compose_path(tmp_path)}:{env['PATH']}",
            "AGENTGUARD_TEST_CAPTURE": str(capture),
        }
    )
    cases = [
        ("/", str(valid_state)),
        ("relative/workspaces", str(valid_state)),
        (str(tmp_path / "missing"), str(valid_state)),
        (str(valid_workspace), str(valid_workspace)),
    ]

    for workspace_root, state_root in cases:
        capture.unlink(missing_ok=True)
        env["AGENTGUARD_WORKSPACE_ROOT"] = workspace_root
        env["AGENTGUARD_NONO_STATE_ROOT"] = state_root
        result = subprocess.run(
            [str(COMPOSE_WRAPPER), "config", "--quiet"],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 2
        assert not capture.exists()


@pytest.mark.parametrize("document", ["README.md", "README_EN.md", "deploy/AGENTGUARD_SMOKE.md"])
def test_agentguard_docs_define_host_rollback_roots(document):
    text = (REPO_ROOT / document).read_text(encoding="utf-8")

    assert "AGENTGUARD_WORKSPACE_ROOT" in text
    assert "AGENTGUARD_NONO_STATE_ROOT" in text
    assert "--allow" in text
    assert "scripts/agentguard-compose" in text

    if document == "README.md":
        assert "相同绝对路径" in text
        assert "不要将这两个变量设为 `/`" in text
    else:
        assert "same absolute" in text
        assert "must not" in text or "Do not set either variable to `/`" in text
