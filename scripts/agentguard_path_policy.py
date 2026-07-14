"""Validate host paths exposed to the AgentGuard rollback worker."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _absolute_root(value: str | Path | None, variable: str) -> Path:
    if value is None or not str(value).strip():
        raise ValueError(f"{variable} must be set")

    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{variable} must be an absolute path: {path}")

    resolved = path.resolve()
    if not resolved.is_dir():
        raise ValueError(f"{variable} must be an existing directory: {resolved}")
    if resolved == Path(resolved.anchor):
        raise ValueError(f"{variable} must not be the host root directory: {resolved}")
    return resolved


def _path_within(value: str | Path, root: Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path: {path}")

    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{label} is outside configured root {root}: {resolved}")
    return resolved


def validate_agentguard_paths(
    *,
    workspace: str | Path,
    state_home: str | Path,
    workspace_root: str | Path | None,
    state_root: str | Path | None,
) -> tuple[Path, Path]:
    """Return canonical paths after enforcing the configured host allowlists."""

    allowed_workspace_root, allowed_state_root = validate_agentguard_roots(
        workspace_root=workspace_root,
        state_root=state_root,
    )
    return (
        _path_within(workspace, allowed_workspace_root, "workspace"),
        _path_within(state_home, allowed_state_root, "nono state home"),
    )


def validate_agentguard_roots(
    *,
    workspace_root: str | Path | None,
    state_root: str | Path | None,
) -> tuple[Path, Path]:
    """Return distinct canonical roots that are safe to bind into the worker."""

    allowed_workspace_root = _absolute_root(workspace_root, "AGENTGUARD_WORKSPACE_ROOT")
    allowed_state_root = _absolute_root(state_root, "AGENTGUARD_NONO_STATE_ROOT")
    if allowed_workspace_root == allowed_state_root:
        raise ValueError("AGENTGUARD_WORKSPACE_ROOT and AGENTGUARD_NONO_STATE_ROOT must be different directories")
    return allowed_workspace_root, allowed_state_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace")
    parser.add_argument("--state-home")
    parser.add_argument("--roots-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        roots = {
            "workspace_root": os.getenv("AGENTGUARD_WORKSPACE_ROOT"),
            "state_root": os.getenv("AGENTGUARD_NONO_STATE_ROOT"),
        }
        if args.roots_only:
            validate_agentguard_roots(**roots)
        else:
            if not args.workspace or not args.state_home:
                parser.error("--workspace and --state-home are required unless --roots-only is used")
            validate_agentguard_paths(workspace=args.workspace, state_home=args.state_home, **roots)
    except ValueError as exc:
        print(f"AgentGuard path validation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
