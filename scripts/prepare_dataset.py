#!/usr/bin/env python3
"""Prepare the imported NHTSA snapshot for the investigation tools.

The raw import is never rewritten. This produces derived, auditable artifacts
under data/processed/ and keeps duplicate candidates separate from records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path


REQUIRED_RECORD_FIELDS = ("record_id", "case_id", "make", "model", "model_year", "official_model", "component", "occurred_date", "received_date", "text", "source_id", "source_url", "saved_at")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\u4e00-\u9fff]+", " ", (value or "").lower())).strip()


def normalize_components(value: str) -> list[str]:
    return sorted({part.strip().upper() for part in re.split(r"[,;/|]+", value or "") if part.strip()}) or ["UNKNOWN OR OTHER"]


def parse_iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(input_dir: Path, output_dir: Path) -> dict:
    cases = load(input_dir / "cases.json")
    records = load(input_dir / "records.json")
    evidence = load(input_dir / "evidence.json")
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared_at = now()

    normalized = []
    missing_counts: Counter[str] = Counter()
    invalid_date_ids = []
    text_groups: dict[str, list[str]] = defaultdict(list)
    id_counts = Counter(str(row.get("record_id", "")) for row in records)
    for raw in records:
        missing = [field for field in REQUIRED_RECORD_FIELDS if raw.get(field) in (None, "")]
        for field in missing:
            missing_counts[field] += 1
        occurred = parse_iso(raw.get("occurred_date"))
        received = parse_iso(raw.get("received_date"))
        if not occurred or not received:
            invalid_date_ids.append(raw.get("record_id"))
        if occurred and received and occurred > received:
            invalid_date_ids.append(raw.get("record_id"))
        normalized_text = canonical_text(raw.get("text", ""))
        if normalized_text:
            text_groups[normalized_text].append(str(raw.get("record_id")))
        derived = dict(raw)
        derived["normalized_make"] = str(raw.get("make", "")).strip().upper()
        derived["normalized_model"] = str(raw.get("model", "")).strip().upper()
        derived["normalized_official_model"] = str(raw.get("official_model", raw.get("model", ""))).strip().upper()
        derived["normalized_components"] = normalize_components(raw.get("component", ""))
        derived["normalized_text"] = normalized_text
        derived["missing_fields"] = missing
        derived["date_valid"] = bool(occurred and received and occurred <= received)
        derived["official_id_duplicate_count"] = id_counts[str(raw.get("record_id", ""))]
        normalized.append(derived)

    duplicate_candidates = [
        {"normalized_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "record_ids": ids, "candidate_type": "exact_normalized_text", "action": "retain_all_and_review"}
        for text, ids in text_groups.items() if len(ids) > 1
    ]
    # Build a small deterministic inverted index. The full source text remains in
    # normalized records; index entries only point to IDs and field types.
    index: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"record_ids": [], "evidence_ids": []})
    for row in normalized:
        for token in set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", row.get("normalized_text", ""))):
            if row["record_id"] not in index[token]["record_ids"]:
                index[token]["record_ids"].append(row["record_id"])
    for item in evidence:
        text = canonical_text(f"{item.get('title', '')} {item.get('content', '')}")
        for token in set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text)):
            if item.get("evidence_id") not in index[token]["evidence_ids"]:
                index[token]["evidence_ids"].append(item.get("evidence_id"))
    index = {token: value for token, value in sorted(index.items())}

    primary_id = cases[0].get("case_id") if cases else None
    eligible = []
    for case in cases:
        if case.get("case_id") == primary_id:
            continue
        case_records = [row for row in normalized if row.get("case_id") == case.get("case_id")]
        case_evidence = [item for item in evidence if item.get("case_id") == case.get("case_id") and item.get("source_kind") in {"investigation_close", "public_recall_disposition"}]
        if case_records and case_evidence and case.get("component") != (cases[0].get("component") if cases else None):
            eligible.append({"case_id": case.get("case_id"), "record_count": len(case_records), "component": case.get("component"), "selection_basis": "has_complaints_and_public_close_material_and_different_component"})
    eligible.sort(key=lambda item: (-item["record_count"], item["case_id"]))
    migration = {
        "selection_rule": "最多两个；有投诉记录、有公开结案材料、主要部件不同；按投诉记录数降序、case_id 升序",
        "selected": eligible[:2],
        "blocked_reason": None if eligible else "当前导入快照只有 EA23003，没有第二个独立案例；未创建虚构迁移案例。",
        "prepared_at": prepared_at,
    }
    quality = {
        "prepared_at": prepared_at,
        "input_dir": str(input_dir),
        "case_count": len(cases),
        "raw_record_count": len(records),
        "normalized_record_count": len(normalized),
        "unique_official_id_count": len({str(row.get("record_id")) for row in records}),
        "duplicate_official_id_groups": {key: count for key, count in id_counts.items() if count > 1},
        "missing_field_counts": dict(missing_counts),
        "invalid_or_inverted_date_record_ids": sorted(set(invalid_date_ids)),
        "exact_normalized_text_duplicate_candidate_group_count": len(duplicate_candidates),
        "exact_normalized_text_duplicate_candidate_records": sum(len(item["record_ids"]) for item in duplicate_candidates),
        "component_value_count_raw": len({str(row.get("component", "")) for row in records}),
        "component_value_count_normalized": len({component for row in normalized for component in row["normalized_components"]}),
        "source_url_missing_count": sum(not row.get("source_url") for row in records),
        "text_missing_count": sum(not row.get("text") for row in records),
        "interpretation": "文本相似和完全相同的归一化文本只形成候选组，未删除或合并投诉；官方投诉编号是唯一去重依据。",
    }
    for name, value in (("records_normalized.json", normalized), ("evidence_index.json", index), ("duplicate_candidates.json", duplicate_candidates), ("data_quality_report.json", quality), ("migration_cases.json", migration)):
        (output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"output_dir": str(output_dir), "raw_record_count": len(records), "normalized_record_count": len(normalized), "index_token_count": len(index), "duplicate_candidate_groups": len(duplicate_candidates), "migration_selected": len(eligible[:2]), "migration_blocked": bool(migration["blocked_reason"])}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/imported"))
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    print(json.dumps(prepare(args.input, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
