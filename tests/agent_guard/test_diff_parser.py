from __future__ import annotations

from ai_agent.agent_guard.diff_parser import parse_unified_diff


def test_parse_nono_unified_diff_without_git_header():
    diff = """--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""

    files = parse_unified_diff(diff)

    assert len(files) == 1
    assert files[0].path == "README.md"
    assert files[0].added_lines == 1
    assert files[0].deleted_lines == 1
