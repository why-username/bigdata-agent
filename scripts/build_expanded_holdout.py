"""Materialize post-cutoff complaint rows as an isolated evaluation holdout."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path


def parse(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d/%m/%y"):
            try:
                return datetime.strptime(str(value), fmt).date()
            except ValueError:
                pass
        return None


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    matrix = json.loads((root / "data" / "expanded" / "qualification_matrix.json").read_text(encoding="utf-8"))
    selected_ids = {item.get("investigation_id") for item in matrix.get("selected", [])}
    rows = []
    summary = []
    for item in matrix.get("results", []):
        if item.get("investigation_id") not in selected_ids:
            continue
        cutoff = parse(item.get("closed_date"))
        if cutoff is None:
            continue
        future = []
        for raw in item.get("rows", []):
            received = parse(raw.get("dateComplaintFiled"))
            if received and received > cutoff:
                future.append({
                    "record_id": str(raw.get("odiNumber") or raw.get("ODINumber") or ""),
                    "investigation_id": item["investigation_id"],
                    "case_id": f"MIG-ODI-{item['investigation_id']}",
                    "received_date": received.isoformat(),
                    "raw_nhtsa": raw,
                    "source_url": item.get("source_url"),
                    "holdout_only": True,
                })
        rows.extend(future)
        summary.append({"investigation_id": item["investigation_id"], "cutoff_date": cutoff.isoformat(), "holdout_record_count": len(future)})
    payload = {"schema_version": "expanded-holdout-v1", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "records": rows, "summary": summary, "note": "仅供截点后答案评测，不得加入运行期 DataStore。"}
    path = root / "data" / "expanded" / "holdout_records.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), "case_count": len(summary), "holdout_record_count": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
