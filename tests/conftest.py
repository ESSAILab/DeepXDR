from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AI_AGENT_ROOT = REPO_ROOT / "ai_agent"

for path in (REPO_ROOT, AI_AGENT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
