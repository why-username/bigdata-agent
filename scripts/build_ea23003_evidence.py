"""Build auditable pre-cutoff complaint evidence for EA23003."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORTED = ROOT / "data" / "imported"
CUTOFF = "2023-11-28"


def main() -> None:
    records = json.loads((IMPORTED / "records.json").read_text(encoding="utf-8"))
    evidence_path = IMPORTED / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    steering = [
        row for row in records
        if row.get("case_id") == "EA23003"
        and row.get("record_type") == "complaint"
        and row.get("received_date", "") <= CUTOFF
        and "steer" in str(row.get("component", "")).lower()
    ]
    by_model = Counter(row.get("official_model", "UNKNOWN") for row in steering)
    source_urls = sorted({row.get("source_url", "") for row in steering if row.get("source_url")})
    ids = [str(row.get("record_id")) for row in steering]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    generated = [
        {
            "evidence_id": "EA23003-PRE-CUTOFF-STEERING-COHORT",
            "case_id": "EA23003",
            "title": "EA23003 截点前转向投诉队列（官方记录统计）",
            "content": f"截至 {CUTOFF}，本地官方 NHTSA 投诉快照中筛得 {len(steering)} 条 component=STEERING 且 dateComplaintFiled 不晚于截点的记录。按官方车型字段统计：{dict(sorted(by_model.items()))}。该证据描述投诉记录队列，不代表故障发生率、共同根因或缺陷成立。",
            "published_date": CUTOFF,
            "source_kind": "nhtsa_complaint_snapshot_aggregate",
            "source_url": source_urls[0] if len(source_urls) == 1 else "https://api.nhtsa.gov/complaints/complaintsByVehicle",
            "citation_locator": "records.json: record_id 列表见 source_record_ids",
            "source_record_ids": ids,
            "source_urls": source_urls,
            "cutoff_date": CUTOFF,
            "is_close_material": False,
            "holdout_only": False,
            "is_demo_fixture": False,
            "retrieved_at": now,
            "saved_at": now,
            "review_status": "待人工研判",
            "stance": "neutral",
            "stance_basis": "确定性筛选和计数；不推断因果",
        },
        {
            "evidence_id": "EA23003-PRE-CUTOFF-STEERING-SAMPLES",
            "case_id": "EA23003",
            "title": "EA23003 pre-cutoff Honda Civic CR-V Integra steering complaint samples",
            "content": "截至 2023-11-28 的 Honda Civic, CR-V and Integra STEERING complaint samples，用于核查症状、发生条件和维修状态；每个样本保留原始 ODI 投诉编号，文本仍是投诉人陈述，未经 NHTSA 事实认定。",
            "published_date": CUTOFF,
            "source_kind": "nhtsa_complaint_snapshot_sample",
            "source_url": source_urls[0] if len(source_urls) == 1 else "https://api.nhtsa.gov/complaints/complaintsByVehicle",
            "citation_locator": "records.json: 前 50 条截点前 STEERING 记录",
            "source_record_ids": ids[:50],
            "source_urls": source_urls,
            "cutoff_date": CUTOFF,
            "is_close_material": False,
            "holdout_only": False,
            "is_demo_fixture": False,
            "retrieved_at": now,
            "saved_at": now,
            "review_status": "待人工研判",
            "stance": "needs_review",
            "stance_basis": "投诉文本需逐条核验，不能直接作为缺陷结论",
        },
    ]
    by_id = {item.get("evidence_id"): item for item in evidence}
    by_id.update({item["evidence_id"]: item for item in generated})
    evidence_path.write_text(json.dumps(list(by_id.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cutoff": CUTOFF, "steering_records": len(steering), "models": dict(by_model), "evidence_added": [x["evidence_id"] for x in generated]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
