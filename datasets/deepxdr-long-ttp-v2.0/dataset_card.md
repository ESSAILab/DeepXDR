# Dataset Card

## Summary

The DeepXDR Long TTP Offline Dataset is a collection of synthetic,
multi-step web-application attack-chain fixtures for reproducible security
investigation experiments.

## Contents

- 16 clean attack-chain samples.
- Multi-source telemetry from OpenRASP, Suricata, Falco, and application logs.
- Chain-level ATT&CK ground truth.
- Synthetic file evidence for MCP-backed investigations.
- Replay metadata and stable event identifiers.

## Intended use

The dataset is intended for:

- Long TTP generation and investigation research.
- ATT&CK technique-set evaluation.
- Ablation studies of retrieval, event organization, and investigation tools.
- Reproducible offline demonstrations.

It is not intended for production detection, live exploitation, or training
systems to access real services.

## Data generation

Samples were generated in a disposable dotCMS-based laboratory environment.
The public copy uses documentation IP addresses, synthetic credential/PII
markers, and removes local source-result paths from sample manifests. Review
all fixture contents before redistribution.

## Ground truth

Ground truth is stored in `long_ttp_ground_truth.json`. Unless an experiment
explicitly evaluates sub-techniques, compare parent technique IDs by removing
the suffix after the first period.

## Limitations

- The dataset is synthetic and may not represent production traffic.
- Telemetry coverage is controlled by the laboratory probes.
- The trigger file is a fixed investigation input, not an independent Short TTP
  benchmark.
- Results can vary with model, prompt, retrieval index, and tool configuration.

## Security and privacy

Do not add real secrets, credentials, session cookies, personal data, internal
hostnames, or production logs to a derivative copy. Use synthetic replacements
and preserve referential consistency when redacting.

## License and attribution

The original dataset material is released under **CC BY 4.0**. See
`LICENSE-DATA.txt` for the license notice and suggested attribution. The
validation and utility scripts are released under the MIT License in
`LICENSE-CODE.txt`.

Any reproduced MITRE ATT&CK material must retain MITRE's copyright and license
notices. This dataset is not affiliated with or endorsed by MITRE.

## Version

Release: v2.0
Scope: clean Long TTP chains only

## Identifier migration

The public directory and `chain_id` values use readable scenario names. The
previous identifiers are preserved as `legacy_chain_id` in each manifest and
in `chain_id_mapping.json` so historical experiment results remain traceable.



