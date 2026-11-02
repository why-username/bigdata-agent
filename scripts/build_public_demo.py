"""Build a small public-only deployment bundle from local NHTSA snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.core import DataStore, write_json


def build(output: Path) -> dict:
    store = DataStore()
    output.mkdir(parents=True, exist_ok=True)
    cases = [case for case in store.cases() if case.get("data_status", "").startswith("public_snapshot")]
    case_ids = {case["case_id"] for case in cases}
    records = []
    for case in cases:
        cutoff = date.fromisoformat(case["cutoff_date"])
        for row in store.records(case["case_id"]):
            try:
                if date.fromisoformat(str(row.get("received_date"))) <= cutoff:
                    records.append(row)
            except ValueError:
                continue
    evidence = []
    for case in cases:
        cutoff = date.fromisoformat(case["cutoff_date"])
        for row in store.evidence(case["case_id"]):
            if row.get("holdout_only") or row.get("source_kind") == "holdout":
                continue
            try:
                if date.fromisoformat(str(row.get("published_date"))) <= cutoff:
                    evidence.append(row)
            except ValueError:
                continue
    write_json(output / "cases.json", cases)
    write_json(output / "records.json", records)
    write_json(output / "evidence.json", evidence)
    manifest = {
        "bundle": "public_demo",
        "source": "local NHTSA public snapshots",
        "holdout_excluded": True,
        "case_count": len(cases),
        "record_count": len(records),
        "evidence_count": len(evidence),
        "case_ids": sorted(case_ids),
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="生成不含留出资料的在线 Demo 数据包")
    parser.add_argument("--output", type=Path, default=Path("data/public_demo"))
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
