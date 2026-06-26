import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UTILS_PATH = REPO_ROOT / "ai_agent" / "ttp_generator" / "dx_analyzer" / "utils.py"
RESEARCHER_PATH = REPO_ROOT / "ai_agent" / "ttp_generator" / "dx_analyzer" / "deep_researcher.py"


def _function_node(path: Path, name: str) -> ast.AsyncFunctionDef:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path}")


def test_truncate_does_not_call_compression_model_or_import_prompt():
    function = _function_node(UTILS_PATH, "truncate_messages_by_length")
    source = ast.get_source_segment(UTILS_PATH.read_text(encoding="utf-8"), function)

    assert "model.ainvoke" not in source
    assert "compress_prompt" not in source
    assert "[Compressed history]" not in source
    assert "未进行模型摘要" in source


def test_researchers_do_not_pass_compression_model_to_truncation():
    source = RESEARCHER_PATH.read_text(encoding="utf-8")

    assert "truncate_messages_by_length(messages, max_total_chars=360000, model=" not in source
    assert "Configure compression model for message truncation" not in source
