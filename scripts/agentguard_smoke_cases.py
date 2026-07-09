from __future__ import annotations

import argparse
import json
from pathlib import Path


def prepare_smoke_case(case: str, workspace: str | Path) -> list[str]:
    workspace_path = Path(workspace)
    workspace_path.mkdir(parents=True, exist_ok=True)
    before = workspace_path / "before"
    after = workspace_path / "after"
    before.mkdir(exist_ok=True)
    after.mkdir(exist_ok=True)

    if case == "small":
        _write_small_case(workspace_path, before, after)
        return ["/bin/sh", "-c", "cp after/README.md README.md"]
    if case == "medium":
        _write_medium_case(workspace_path, before, after)
        return ["/bin/sh", "-c", "cp after/service.py service.py && cp after/policy.yaml policy.yaml"]
    if case == "large":
        _write_large_case(workspace_path, before, after)
        return ["/bin/sh", "-c", "cp after/generated_policy.json generated_policy.json"]
    if case == "agent":
        _write_agent_case(workspace_path)
        return [
            "opencode",
            "run",
            "--model",
            "deepxdr/deepseek-v3-2-251201",
            "--auto",
            original_request_for_case("agent"),
        ]
    raise ValueError(f"unknown smoke case: {case}")


def original_request_for_case(case: str) -> str:
    requests = {
        "small": "smoke small: update README wording",
        "medium": "smoke medium: update service logic and policy config",
        "large": "smoke large: regenerate policy dataset",
        "agent": (
            "Edit README.md. Add a short section titled Agent Result explaining that this file "
            "was modified by a real opencode agent under nono. Keep it concise."
        ),
    }
    if case not in requests:
        raise ValueError(f"unknown smoke case: {case}")
    return requests[case]


def _write_small_case(workspace: Path, before: Path, after: Path) -> None:
    _write_pair(workspace, before, after, "README.md", "old title\n", "new title\n")


def _write_medium_case(workspace: Path, before: Path, after: Path) -> None:
    before_service = "\n".join(f"def rule_{idx}(): return 'old-{idx}'" for idx in range(10)) + "\n"
    after_service = "\n".join(f"def rule_{idx}(): return 'new-{idx}'" for idx in range(10)) + "\n"
    before_policy = "\n".join(f"policy_{idx}: disabled" for idx in range(16)) + "\n"
    after_policy = "\n".join(f"policy_{idx}: enabled" for idx in range(16)) + "\n"
    _write_pair(workspace, before, after, "service.py", before_service, after_service)
    _write_pair(workspace, before, after, "policy.yaml", before_policy, after_policy)


def _write_large_case(workspace: Path, before: Path, after: Path) -> None:
    old_payload = [{"id": idx, "action": "observe", "enabled": False} for idx in range(80)]
    new_payload = [{"id": idx, "action": "enforce", "enabled": True, "description": f"generated rule {idx}"} for idx in range(80)]
    _write_pair(
        workspace,
        before,
        after,
        "generated_policy.json",
        json.dumps(old_payload, indent=2, ensure_ascii=False) + "\n",
        json.dumps(new_payload, indent=2, ensure_ascii=False) + "\n",
    )


def _write_agent_case(workspace: Path) -> None:
    (workspace / "README.md").write_text("# Smoke target\n\nThis file is intentionally incomplete.\n", encoding="utf-8")
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": "deepxdr/deepseek-v3-2-251201",
        "provider": {
            "deepxdr": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "DeepXDR Ark",
                "options": {
                    "baseURL": "https://ark.cn-beijing.volces.com/api/v3",
                    "apiKey": "{env:OPENAI_API_KEY}",
                },
                "models": {
                    "deepseek-v3-2-251201": {
                        "name": "deepseek-v3-2-251201",
                    }
                },
            }
        },
    }
    (workspace / "opencode.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_pair(workspace: Path, before: Path, after: Path, relative_path: str, before_text: str, after_text: str) -> None:
    for root, text in ((workspace, before_text), (before, before_text), (after, after_text)):
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare AgentGuard smoke case workspace")
    parser.add_argument("case", choices=("small", "medium", "large", "agent"))
    parser.add_argument("workspace")
    args = parser.parse_args()
    command = prepare_smoke_case(args.case, args.workspace)
    print(json.dumps({"case": args.case, "original_request": original_request_for_case(args.case), "command": command}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
