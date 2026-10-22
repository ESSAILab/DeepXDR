# DeepXDR Long TTP Offline Dataset v2.0

This release contains clean, synthetic laboratory attack-chain fixtures for
reproducing Long TTP investigations. It does not contain a separate Short TTP
benchmark. The per-chain trigger file is included only because the Long TTP
API requires a fixed investigation entry point.

## Layout

Each directory under `chains/` is one independent attack-chain sample. Directory
names now use human-readable scenario IDs. The original identifiers are kept in
`legacy_chain_id` and `chain_id_mapping.json`.

- `events.jsonl`: raw OpenRASP, Suricata, Falco, and application events.
- `trigger_short_ttp.json`: fixed Long TTP trigger input.
- `long_ttp_ground_truth.json`: chain-level ATT&CK ground truth.
- `file_actions.json`: synthetic files required by file-investigation tools.
- `run_config.json`: replay and experiment configuration.
- `sample_manifest.json`: sample metadata and counts.
- `event_id_map.json`: event-to-step and telemetry-source mapping.

## Replaying a sample

1. Import the sample events into an isolated Elasticsearch fixture.
2. Apply `file_actions.json` in the disposable laboratory container.
3. Register or import `trigger_short_ttp.json`.
4. Trigger the selected Long TTP variant.
5. Compare the generated techniques with `long_ttp_ground_truth.json`.

The files are fixtures only. Do not connect the replay scripts to production
systems or real credentials.

## License

The dataset files are released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The validation and utility scripts are released under the MIT License. See
`LICENSE-DATA.txt` and `LICENSE-CODE.txt` for the notices and attribution
requirements.

MITRE ATT&CK content, if reproduced in a fixture, remains subject to the
MITRE terms of use and is not an endorsement by MITRE.

## Integrity

`SHA256SUMS` records the digest of every published data and documentation
file. Run the validation script before using a sample:

```powershell
python tools/validate_long_ttp_dataset.py
```

## Scope

This v2.0 release contains clean chains only. Noise experiments can be constructed
by injecting events from multiple chain directories into the same disposable
fixture while retaining the target chain ground truth.



