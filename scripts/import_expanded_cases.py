"""Merge the independently validated expanded package into local imported data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def merge(expanded: Path, imported: Path) -> dict:
    imported.mkdir(parents=True, exist_ok=True)
    cases = load(imported / "cases.json")
    records = load(imported / "records.json")
    evidence = load(imported / "evidence.json")
    extra_cases = load(expanded / "cases.json")
    extra_records = load(expanded / "records.json")
    extra_evidence = load(expanded / "evidence.json")
    ids = {row["case_id"] for row in extra_cases}
    cases = [row for row in cases if row.get("case_id") not in ids] + extra_cases
    records = [row for row in records if row.get("case_id") not in ids] + extra_records
    evidence = [row for row in evidence if row.get("case_id") not in ids] + extra_evidence
    dump(imported / "cases.json", cases)
    dump(imported / "records.json", records)
    dump(imported / "evidence.json", evidence)
    manifest_path = imported / "manifest.json"
    manifest = load(manifest_path) if manifest_path.exists() else []
    manifest.extend(load(expanded / "manifest.json"))
    dump(manifest_path, manifest)
    return {"added_cases": len(extra_cases), "added_records": len(extra_records), "added_evidence": len(extra_evidence), "total_cases": len(cases), "total_records": len(records), "total_evidence": len(evidence), "imported_dir": str(imported)}


def main() -> int:
    parser = argparse.ArgumentParser(description="导入研究扩展案例，同时保留现有主案和迁移案")
    parser.add_argument("--expanded", type=Path, default=Path("data/expanded"))
    parser.add_argument("--imported", type=Path, default=Path("data/imported"))
    args = parser.parse_args()
    print(json.dumps(merge(args.expanded, args.imported), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
