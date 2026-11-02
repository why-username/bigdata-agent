"""Create per-case quality and replay-readiness metrics for expanded cases."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def main() -> int:
    imported = ROOT / "data" / "imported"
    cases = json.loads((imported / "cases.json").read_text(encoding="utf-8"))
    records = json.loads((imported / "records.json").read_text(encoding="utf-8"))
    evidence = json.loads((imported / "evidence.json").read_text(encoding="utf-8"))
    matrix = json.loads((ROOT / "data" / "expanded" / "qualification_matrix.json").read_text(encoding="utf-8"))
    holdout = json.loads((ROOT / "data" / "expanded" / "holdout_records.json").read_text(encoding="utf-8")) if (ROOT / "data" / "expanded" / "holdout_records.json").exists() else {"summary": []}
    holdout_counts = {item["investigation_id"]: item.get("holdout_record_count", 0) for item in holdout.get("summary", [])}
    expanded = [case for case in cases if str(case.get("case_id", "")).startswith("MIG-ODI-")]
    rows = []
    for case in expanded:
        case_id = case["case_id"]
        cutoff = parse(case.get("cutoff_date"))
        case_records = [row for row in records if row.get("case_id") == case_id]
        case_evidence = [row for row in evidence if row.get("case_id") == case_id]
        invalid = [row.get("record_id") for row in case_records if not parse(row.get("received_date")) or (parse(row.get("occurred_date")) and parse(row.get("received_date")) and parse(row.get("occurred_date")) > parse(row.get("received_date")))]
        duplicates = [rid for rid, count in Counter(str(row.get("record_id")) for row in case_records).items() if count > 1]
        source_urls = sorted({str(row.get("source_url")) for row in case_records + case_evidence if row.get("source_url")})
        kinds = sorted({row.get("source_kind") for row in case_evidence if row.get("source_kind")})
        investigation_id = (case.get("migration_basis") or {}).get("investigation_id")
        qualifying = next((item for item in matrix.get("results", []) if item.get("investigation_id") == investigation_id), {})
        qualifying_summary = {key: qualifying.get(key) for key in ("investigation_id", "http_status", "complaint_count", "pre_close_complaint_count", "related_complaint_count", "component_match_rate", "source_url", "raw_path", "sha256", "retrieved_at", "saved_at")}
        rows.append({
            "case_id": case_id,
            "investigation_id": (case.get("migration_basis") or {}).get("investigation_id"),
            "component": case.get("component"),
            "cutoff_date": case.get("cutoff_date"),
            "record_count": len(case_records),
            "evidence_count": len(case_evidence),
            "evidence_source_kinds": kinds,
            "independent_material_kind_count": len(kinds),
            "source_url_count": len(source_urls),
            "invalid_record_date_count": len(invalid),
            "duplicate_record_id_count": len(duplicates),
            "all_records_before_cutoff": bool(cutoff and all((parse(row.get("received_date")) or date.max) <= cutoff for row in case_records)),
            "all_evidence_before_cutoff": bool(cutoff and all((parse(row.get("published_date")) or date.max) <= cutoff for row in case_evidence)),
            "holdout_record_count": holdout_counts.get((case.get("migration_basis") or {}).get("investigation_id"), 0),
            "holdout_ready": holdout_counts.get((case.get("migration_basis") or {}).get("investigation_id"), 0) > 0,
            "has_close_material": any(row.get("source_kind") == "investigation_close" and row.get("is_close_material") for row in case_evidence),
            "has_complaint_material": any(row.get("source_kind") == "nhtsa_complaint_snapshot_aggregate" for row in case_evidence),
            "has_sha256_snapshot": bool(qualifying.get("raw_path") or qualifying.get("sha256")),
            "qualification": qualifying_summary,
        })
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_count": len(rows),
        "qualified_case_count": sum(bool(row["has_close_material"] and row["has_complaint_material"] and row["record_count"] and row["all_records_before_cutoff"] and row["all_evidence_before_cutoff"]) for row in rows),
        "required_independent_materials": ["investigation_close", "nhtsa_complaint_snapshot_aggregate"],
        "cases": rows,
        "interpretation": "投诉记录证明可关联公开线索，不等同于真实故障率；结案摘要保留官方结论文本，但迁移案例仍是精简回放包。",
    }
    path = ROOT / "data" / "expanded" / "quality_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), "case_count": report["case_count"], "qualified_case_count": report["qualified_case_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
