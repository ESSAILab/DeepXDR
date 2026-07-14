"""Prompts used by the MITRE ATT&CK Report Agent."""

# =============================================================================
# Report Agent Prompts
# =============================================================================

report_system_prompt = """\
You are a senior Incident Response lead writing an executive report.\n\
Use ONLY the provided structured context.\n\
Return ONLY valid JSON (no code fences) matching the required schema.\n\
Be specific and actionable. Do NOT invent facts.\
"""

report_user_prompt_template = """\
Write the entire report in Chinese, including all headings and source descriptions.\n\n\
Do NOT mention event status (e.g., contained, under investigation, resolved, in progress, etc.) in the report. \n\n\
Schema fields (must include all):\n\
- title, you must clearly describe the observed behavior. Do not use vague workflow/status terms like 'Unknown' or 'In Progress.' (<=300)\n\
- executive_summary (<=900)\n\
- likely_attack_flow (3-12 bullet lines)\n\
- mapped_techniques (1-20 lines)\n\
- notable_groups_software (0-30 lines)\n\
- detection_recommendations (3-20 lines)\n\
- immediate_actions (3-15 lines)\n\
- iocs: {{ suspected_artifacts[], suspicious_processes[], suspicious_network[] }}\n\
- localized source section: at the end with referenced event evidence only when actual event_id values are available\n\n\
- markdown (full report in Markdown, <=12000)\n\n\
<Citation Rules>\n\
- Sources must contain only concrete security event evidence returned by investigation tools.\n\
- Every numbered source must contain at least one actual event_id from tool results.\n\
- Use the format: [n] Specific observed behavior: event_id1, event_id2.\n\
- Do not cite research scope, index names, query templates, investigation methods, tool configuration, tool errors, missing evidence, or negative search results as sources.\n\
- Do not invent, transform, or infer event IDs.\n\
- Cite a source only when it directly supports a claim in the report body.\n\
- Every evidence-based claim in the report body must cite its supporting source using the matching [n] marker.\n\
- Place each citation marker immediately after the sentence or claim it supports.\n\
- Every numbered source must be cited at least once in the report body using its matching [n] marker.\n\
- Do not include source entries that are never cited in the report body.\n\
- The same event_id may appear in multiple evidence groups only when it supports multiple claims.\n\
- If no valid event IDs were retrieved, state that no verifiable event evidence was obtained and do not create numbered sources.\n\
- Use a level-3 Markdown source heading localized into Chinese; do not output the English headings "Sources(Events ID)" or "Evidence References(Events ID)".\n\
- Place the source heading on its own line, followed by a blank line.\n\
- Each source must be a Markdown bullet in the form "- [n] ...".\n\
- Number valid sources sequentially without gaps.\n\
- Example format:\n\
  ### <source heading localized into Chinese>\n\n\
  - [1] <specific observed behavior in Chinese>: 83d6aa1f-69fb-4d28-afa6-18afd3335386\n\
  - [2] <specific observed behavior in Chinese>: 42edbb7a-b46b-4d43-b9d5-c31a2a769e7f\n\
</Citation Rules>\n\n\
CONTEXT JSON:\n\
{context_json}"""
