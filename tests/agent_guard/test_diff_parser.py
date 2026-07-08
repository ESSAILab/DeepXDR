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


def test_parse_nono_multi_file_unified_diff_without_git_headers():
    diff = """--- /repo/policy.yaml
+++ b//repo/policy.yaml
@@ -1 +1 @@
-mode: observe
+mode: enforce
--- a//repo/service.py
+++ b//repo/service.py
@@ -1 +1 @@
-return 'old'
+return 'new'
"""

    files = parse_unified_diff(diff)

    assert [file.path for file in files] == ["/repo/policy.yaml", "/repo/service.py"]
    assert [file.added_lines for file in files] == [1, 1]
    assert [file.deleted_lines for file in files] == [1, 1]
