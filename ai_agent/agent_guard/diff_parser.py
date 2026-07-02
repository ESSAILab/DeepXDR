from __future__ import annotations

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

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            flush_current()
            parts = line.split()
            if len(parts) >= 4:
                b_path = parts[3]
                current_path = b_path[2:] if b_path.startswith("b/") else b_path
            else:
                current_path = "unknown"
            current_lines = [line]
        elif current_path is not None:
            current_lines.append(line)

    flush_current()
    return files


def estimate_token_count(text: str) -> int:
    return max(1, len(text) // 4)
