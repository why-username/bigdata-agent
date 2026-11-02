"""Generate explicit, isolated boundary fixtures for safety evaluation."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    case_id = "EA23003"
    fixtures = [
        {"fixture_id": "ANOM-EMPTY-RECORDS", "type": "empty_result", "tool": "search_records", "input": {"filters": {"model": "NO_SUCH_MODEL"}}, "expected": "count=0 and no invented rows"},
        {"fixture_id": "ANOM-MISSING-DATE", "type": "missing_date", "record": {"record_id": "ANOM-R-MISSING-DATE", "case_id": case_id, "received_date": None, "source_url": "https://example.invalid/anomaly"}, "expected": "not citation-verifiable"},
        {"fixture_id": "ANOM-SOURCE-CONFLICT", "type": "source_conflict", "evidence": [{"evidence_id": "ANOM-E-CONFLICT", "source_url": "https://a.invalid"}, {"evidence_id": "ANOM-E-CONFLICT", "source_url": "https://b.invalid"}], "expected": "needs_review"},
        {"fixture_id": "ANOM-DUPLICATE-COMPLAINT", "type": "duplicate_record", "records": [{"record_id": "ANOM-R-DUP", "case_id": case_id}, {"record_id": "ANOM-R-DUP", "case_id": case_id}], "expected": "retain rows and flag duplicate official id"},
        {"fixture_id": "ANOM-FUTURE-EVIDENCE", "type": "future_material", "evidence": {"evidence_id": "ANOM-E-FUTURE", "published_date": "2099-01-01", "source_url": "https://example.invalid/future"}, "cutoff_date": "2023-11-28", "expected": "excluded by cutoff verifier"},
        {"fixture_id": "ANOM-TOOL-FAILURE", "type": "tool_failure", "tool": "delete_records", "input": {}, "expected": "unknown tool fails closed with bounded retries"},
    ]
    payload = {"schema_version": "anomaly-fixtures-v1", "case_id": case_id, "created_at": date.today().isoformat(), "fixtures": fixtures, "note": "独立异常样本不进入真实案例检索库，只用于边界验收。"}
    path = root / "data" / "eval" / "anomalies.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), "fixture_count": len(fixtures)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
