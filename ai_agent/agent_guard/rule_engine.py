from __future__ import annotations

from dataclasses import dataclass

from .diff_parser import ChangedFile


SENSITIVE_PATH_MARKERS = (
    ".env",
    ".github/workflows/",
    "deploy/",
    "dockerfile",
    "docker-compose",
    "auth",
    "iam",
    "rbac",
    "secret",
    "secrets",
)

DANGEROUS_PATTERNS = (
    "chmod 777",
    "verify=false",
    "verify = false",
    "strict_ssl=false",
    "disable auth",
    "skip tests",
)


@dataclass(frozen=True)
class RiskSignal:
    type: str
    severity: str
    reason: str
    path: str


def detect_risk_signals(changed_file: ChangedFile) -> list[RiskSignal]:
    signals: list[RiskSignal] = []
    path_lower = changed_file.path.lower().replace("\\", "/")
    diff_lower = changed_file.diff.lower()

    if any(marker in path_lower for marker in SENSITIVE_PATH_MARKERS):
        signals.append(
            RiskSignal(
                type="sensitive_path",
                severity="high",
                reason=f"sensitive path changed: {changed_file.path}",
                path=changed_file.path,
            )
        )

    for pattern in DANGEROUS_PATTERNS:
        if pattern in diff_lower:
            signals.append(
                RiskSignal(
                    type="dangerous_pattern",
                    severity="high",
                    reason=f"dangerous pattern matched: {pattern}",
                    path=changed_file.path,
                )
            )
            break

    return signals
