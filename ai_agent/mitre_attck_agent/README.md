---
title: MITRE Agentic Threat Investigation
emoji: 🎯
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: 6.2.0
python_version: "3.12"
app_file: app.py
pinned: false
license: apache-2.0
short_description: AI threat investigation with local MITRE ATT&CK RAG.
---

# MITRE ATT&CK Agentic Threat Investigation

AI-powered incident analysis that maps EDR/SIEM alert text to likely **MITRE ATT&CK** techniques with local STIX data and RAG caches, suggests detections and mitigations, and generates an executive report.

## Configuration (Secrets/Variables)
Set these in **Space → Settings → Secrets/Variables**.

### Secrets
- `OPENAI_API_KEY` (required)

### Variables
- `MITRE_ATTACK_CACHE_DIR` (optional; defaults to the package `.cache/mitre_attack` directory)
- `MITRE_RAG_LLM_MODEL` (optional; defaults to `gpt-4.1-mini`)
