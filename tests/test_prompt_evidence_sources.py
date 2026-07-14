import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(relative_path: str):
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_prompts_require_sources_to_contain_real_event_ids() -> None:
    prompts = _load_module("ai_agent/ttp_generator/dx_analyzer/prompts.py")
    report_prompts = _load_module("ai_agent/mitre_attck_agent/agents/report_prompts.py")
    source_prompts = [
        prompts.compress_research_system_prompt,
        prompts.final_report_generation_prompt,
        prompts.final_threathunting_generation_prompt,
        report_prompts.report_user_prompt_template,
    ]

    required_rules = [
        "Every numbered source must contain at least one actual event_id from tool results.",
        "Do not cite research scope, index names, query templates, investigation methods, tool configuration, tool errors, missing evidence, or negative search results as sources.",
        "If no valid event IDs were retrieved, state that no verifiable event evidence was obtained and do not create numbered sources.",
    ]
    forbidden_source_rule = "Evidence groups may contain event IDs, Elasticsearch indices, file paths"

    for prompt in source_prompts:
        for rule in required_rules:
            assert rule in prompt
        assert forbidden_source_rule not in prompt


def test_final_report_prompts_require_chinese_markdown_source_lists() -> None:
    prompts = _load_module("ai_agent/ttp_generator/dx_analyzer/prompts.py")
    report_prompts = _load_module("ai_agent/mitre_attck_agent/agents/report_prompts.py")
    final_report_prompts = [
        prompts.final_report_generation_prompt,
        prompts.final_threathunting_generation_prompt,
        report_prompts.report_user_prompt_template,
    ]
    source_prompts = [prompts.compress_research_system_prompt, *final_report_prompts]

    for prompt in final_report_prompts:
        assert "Write the entire report in Chinese, including all headings and source descriptions." in prompt
        assert "do not output the English headings" in prompt

    for prompt in source_prompts:
        assert "Place the source heading on its own line, followed by a blank line." in prompt
        assert 'Each source must be a Markdown bullet in the form "- [n] ...".' in prompt


def test_final_report_prompts_require_bidirectional_inline_citations() -> None:
    prompts = _load_module("ai_agent/ttp_generator/dx_analyzer/prompts.py")
    report_prompts = _load_module("ai_agent/mitre_attck_agent/agents/report_prompts.py")
    final_report_prompts = [
        prompts.final_report_generation_prompt,
        prompts.final_threathunting_generation_prompt,
        report_prompts.report_user_prompt_template,
    ]
    required_rules = [
        "Every evidence-based claim in the report body must cite its supporting source using the matching [n] marker.",
        "Place each citation marker immediately after the sentence or claim it supports.",
        "Every numbered source must be cited at least once in the report body using its matching [n] marker.",
        "Do not include source entries that are never cited in the report body.",
    ]

    for prompt in final_report_prompts:
        for rule in required_rules:
            assert rule in prompt
