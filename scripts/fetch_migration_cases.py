#!/usr/bin/env python3
"""Fetch two small independent NHTSA migration case packages."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "imported"
RAW = OUT / "raw" / "migrations"
CANDIDATES = [
    {"case_id": "MIG-FORD-EXPLORER-2020-20V788000", "make": "Ford", "model": "Explorer", "model_year": 2020, "campaign": "20V788000", "component_token": "ENGINE", "component": "engine", "title": "Ford Explorer 2020 发动机召回"},
    {"case_id": "MIG-TESLA-MODEL3-2021-21V387000", "make": "Tesla", "model": "Model 3", "model_year": 2021, "campaign": "21V387000", "component_token": "SERVICE BRAKES", "component": "service brakes", "title": "Tesla Model 3 2021 制动卡钳召回"},
]


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get(url: str):
    result = subprocess.run(["curl", "-L", "--silent", "--show-error", "--max-time", "60", "-A", "vehicle-investigation-agent/1.0", url, "-w", "\n%{http_code}"], capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-500:])
    body, status_text = result.stdout.rsplit(b"\n", 1)
    return json.loads(body.decode("utf-8")), int(status_text), body, now(), hashlib.sha256(body).hexdigest()


def date_iso(value: str) -> str:
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True); RAW.mkdir(parents=True, exist_ok=True)
    paths = {name: OUT / name for name in ("cases.json", "records.json", "evidence.json", "manifest.json")}
    cases, records, evidence, manifest = [json.loads(paths[name].read_text(encoding="utf-8")) for name in paths]
    ids = {item["case_id"] for item in CANDIDATES}
    ids.update({"MIG-FORD-ESCAPE-2020-19V633000", "MIG-TESLA-MODEL3-2021-21V835000"})
    cases = [row for row in cases if row.get("case_id") not in ids]
    records = [row for row in records if row.get("case_id") not in ids]
    evidence = [row for row in evidence if row.get("case_id") not in ids]
    results = []
    for candidate in CANDIDATES:
        query = urllib.parse.urlencode({"make": candidate["make"], "model": candidate["model"], "modelYear": candidate["model_year"]})
        complaints_url = f"https://api.nhtsa.gov/complaints/complaintsByVehicle?{query}"
        recalls_url = f"https://api.nhtsa.gov/recalls/recallsByVehicle?{query}"
        complaints, complaints_status, complaints_raw, complaints_at, complaints_sha = get(complaints_url)
        recalls, recalls_status, recalls_raw, recalls_at, recalls_sha = get(recalls_url)
        recall = next((row for row in recalls.get("results", []) if str(row.get("NHTSACampaignNumber")) == candidate["campaign"]), None)
        if recall is None:
            raise RuntimeError(f"未找到召回处置材料：{candidate['campaign']}")
        prefix = re.sub(r"[^A-Za-z0-9]+", "_", candidate["case_id"])
        complaints_path = RAW / f"{prefix}_complaints.json"; recalls_path = RAW / f"{prefix}_recalls.json"
        complaints_path.write_bytes(complaints_raw); recalls_path.write_bytes(recalls_raw)
        saved_at = now()
        manifest.extend([
            {"kind": "migration_complaints_api", "case_id": candidate["case_id"], "source_url": complaints_url, "http_status": complaints_status, "count": complaints.get("count"), "retrieved_at": complaints_at, "saved_at": saved_at, "sha256": complaints_sha, "raw_json_path": str(complaints_path), "status": "ok" if complaints_status == 200 else "failed"},
            {"kind": "migration_recall_api", "case_id": candidate["case_id"], "source_url": recalls_url, "campaign": candidate["campaign"], "http_status": recalls_status, "retrieved_at": recalls_at, "saved_at": saved_at, "sha256": recalls_sha, "raw_json_path": str(recalls_path), "status": "ok" if recalls_status == 200 else "failed"},
        ])
        filtered = [row for row in complaints.get("results", []) if candidate["component_token"] in str(row.get("components", "")).upper()]
        cases.append({"case_id": candidate["case_id"], "title": candidate["title"], "make": candidate["make"], "models": [candidate["model"]], "component": candidate["component"], "cutoff_date": date_iso(recall.get("ReportReceivedDate", "")), "data_status": "public_snapshot_migration", "source_url": recalls_url, "retrieved_at": saved_at, "saved_at": saved_at, "fixture_notice": "精简迁移案例：使用 NHTSA 公开召回处置材料与部件筛选后的投诉快照，不等同于完整 ODI 调查结案档案。", "migration_basis": {"campaign": candidate["campaign"], "component_token": candidate["component_token"], "related_complaint_count": len(filtered), "public_material_type": "public_recall_disposition"}})
        evidence.append({"evidence_id": f"{candidate['case_id']}-RECALL", "case_id": candidate["case_id"], "title": f"NHTSA Recall {candidate['campaign']} public disposition", "content": recall.get("Summary", "") + "\n" + recall.get("Consequence", "") + "\n" + recall.get("Remedy", ""), "published_date": date_iso(recall.get("ReportReceivedDate", "")), "source_kind": "public_recall_disposition", "citation_locator": f"NHTSACampaignNumber={candidate['campaign']}", "source_url": recalls_url, "is_close_material": True, "holdout_only": False, "is_demo_fixture": False, "retrieved_at": saved_at, "saved_at": saved_at, "raw_recall": recall})
        for row in filtered:
            record_id = str(row.get("odiNumber"))
            records.append({"record_id": record_id, "case_id": candidate["case_id"], "record_type": "complaint", "make": candidate["make"], "model": candidate["model"], "official_model": candidate["model"].upper(), "source_models": [candidate["model"].upper()], "model_year": candidate["model_year"], "component": row.get("components", ""), "occurred_date": date_iso(row.get("dateOfIncident", "")), "received_date": date_iso(row.get("dateComplaintFiled", "")), "text": row.get("summary", ""), "source_id": record_id, "source_url": complaints_url, "retrieved_at": complaints_at, "saved_at": saved_at, "raw_nhtsa": row, "is_demo_fixture": False})
        results.append({"case_id": candidate["case_id"], "campaign": candidate["campaign"], "component": candidate["component"], "related_complaint_count": len(filtered), "public_material": "public_recall_disposition"})
    for name, value in (("cases.json", cases), ("records.json", records), ("evidence.json", evidence), ("manifest.json", manifest)):
        paths[name].write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
