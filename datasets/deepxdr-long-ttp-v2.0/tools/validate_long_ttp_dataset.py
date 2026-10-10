"""Validate the published DeepXDR Long TTP fixture layout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = (
    "events.jsonl",
    "trigger_short_ttp.json",
    "long_ttp_ground_truth.json",
    "file_actions.json",
    "run_config.json",
    "sample_manifest.json",
    "event_id_map.json",
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_chain(chain_dir: Path) -> list[str]:
    errors: list[str] = []
    missing = [name for name in REQUIRED if not (chain_dir / name).is_file()]
    if missing:
        return [f"{chain_dir.name}: missing {', '.join(missing)}"]

    try:
        manifest = load_json(chain_dir / "sample_manifest.json")
        ground_truth = load_json(chain_dir / "long_ttp_ground_truth.json")
        trigger = load_json(chain_dir / "trigger_short_ttp.json")
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{chain_dir.name}: invalid JSON ({exc})"]

    chain_id = manifest.get("chain_id")
    if not chain_id:
        errors.append("manifest.chain_id is missing")
    if ground_truth.get("chain_id") != chain_id:
        errors.append("ground-truth chain_id does not match manifest")
    if trigger.get("fixture_chain_id") not in (None, chain_id):
        errors.append("trigger fixture_chain_id does not match manifest")

    event_ids: set[str] = set()
    fixture_refs: set[str] = set()
    events_path = chain_dir / "events.jsonl"
    for line_number, line in enumerate(events_path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"events.jsonl:{line_number}: invalid JSON ({exc})")
            continue
        event_id = event.get("event_id")
        if not event_id:
            errors.append(f"events.jsonl:{line_number}: event_id is missing")
        elif event_id in event_ids:
            errors.append(f"events.jsonl:{line_number}: duplicate event_id {event_id}")
        else:
            event_ids.add(event_id)
        fixture_ref = event.get("fixture_event_ref")
        if fixture_ref:
            if fixture_ref in fixture_refs:
                errors.append(f"events.jsonl:{line_number}: duplicate fixture_event_ref {fixture_ref}")
            fixture_refs.add(fixture_ref)

    declared_count = manifest.get("event_count")
    if isinstance(declared_count, int) and declared_count != len(event_ids):
        errors.append(f"manifest.event_count={declared_count}, actual={len(event_ids)}")

    for step in ground_truth.get("steps", []):
        for event_ref in step.get("expected_event_refs", []):
            if event_ref not in fixture_refs and event_ref not in event_ids:
                errors.append(f"GT references missing event {event_ref}")

    return [f"{chain_dir.name}: {error}" for error in errors]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=Path(__file__).parents[1], type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    chain_root = root / "chains"
    chains = sorted(path for path in chain_root.iterdir() if path.is_dir())
    if not chains:
        print(f"no chain directories found under {chain_root}")
        return 1

    errors = [error for chain in chains for error in validate_chain(chain)]
    print(f"checked {len(chains)} chain(s)")
    if errors:
        print("\n".join(errors))
        return 1
    print("dataset validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
