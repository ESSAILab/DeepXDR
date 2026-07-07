from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ChangedFile:
    path: str
    change_type: str
    added_lines: int
    deleted_lines: int
    diff: str


def parse_unified_diff(diff_text: str) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    current_path: str | None = None
    current_lines: list[str] = []
    pending_old_path: str | None = None

    def flush_current() -> None:
        nonlocal current_path, current_lines
        if current_path is None:
            return
        file_diff = "\n".join(current_lines)
        added = sum(1 for line in current_lines if line.startswith("+") and not line.startswith("+++"))
        deleted = sum(1 for line in current_lines if line.startswith("-") and not line.startswith("---"))
        files.append(
            ChangedFile(
                path=current_path,
                change_type="modified",
                added_lines=added,
                deleted_lines=deleted,
                diff=file_diff,
            )
        )
        current_path = None
        current_lines = []

    def normalize_path(raw: str) -> str:
        path = raw.strip()
        if "\t" in path:
            path = path.split("\t", 1)[0]
        if path.startswith("a/") or path.startswith("b/"):
            return path[2:]
        return path

    ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    for raw_line in diff_text.splitlines():
        line = ansi_re.sub("", raw_line)
        if line.startswith("diff --git "):
            flush_current()
            parts = line.split()
            if len(parts) >= 4:
                b_path = parts[3]
                current_path = b_path[2:] if b_path.startswith("b/") else b_path
            else:
                current_path = "unknown"
            current_lines = [line]
        elif line.startswith("--- "):
            if current_path is not None:
                current_lines.append(line)
            pending_old_path = normalize_path(line[4:])
        elif line.startswith("+++ "):
            if current_path is not None:
                current_lines.append(line)
                continue
            current_path = normalize_path(line[4:])
            if current_path == "/dev/null" and pending_old_path:
                current_path = pending_old_path
            current_lines = []
            if pending_old_path:
                current_lines.append(f"--- {pending_old_path}")
            current_lines.append(line)
        elif current_path is not None:
            current_lines.append(line)

    flush_current()
    return files


def estimate_token_count(text: str) -> int:
    return max(1, len(text) // 4)
