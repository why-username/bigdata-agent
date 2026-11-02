#!/usr/bin/env python3
"""Screen 20+ NHTSA vehicle-year candidates for migration cases.

Every candidate gets local complaint/recall API snapshots and an auditable
screening row. Selection is deliberately separate from the main-case package.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
RAW = ROOT / "data" / "imported" / "raw" / "candidate_screening"
CANDIDATES = [
    ("Ford", "Escape", 2020), ("Ford", "Explorer", 2020), ("Ford", "F-150", 2020),
    ("Toyota", "Camry", 2020), ("Toyota", "Corolla", 2020), ("Toyota", "RAV4", 2020),
    ("Tesla", "Model 3", 2021), ("Tesla", "Model Y", 2021), ("Hyundai", "Sonata", 2020),
    ("Hyundai", "Elantra", 2020), ("Kia", "Forte", 2020), ("Nissan", "Rogue", 2020),
    ("Nissan", "Altima", 2020), ("Chevrolet", "Equinox", 2020), ("Chevrolet", "Silverado 1500", 2020),
    ("Jeep", "Grand Cherokee", 2020), ("Subaru", "Outback", 2020), ("Honda", "Accord", 2020),
    ("BMW", "X3", 2020), ("Volkswagen", "Tiguan", 2020), ("Mazda", "CX-5", 2020),
    ("Ram", "1500", 2020),
]


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def fetch(url: str):
    result = subprocess.run(["curl", "-L", "--silent", "--show-error", "--max-time", "60", "-A", "vehicle-investigation-agent/1.0", url, "-w", "\n%{http_code}"], capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-500:])
    body, status = result.stdout.rsplit(b"\n", 1)
    return json.loads(body.decode("utf-8")), int(status), body, now(), hashlib.sha256(body).hexdigest()


def normalize_component(value: str) -> str:
    tokens = [part.strip().upper() for part in re.split(r"[,;/|]+", value or "") if part.strip()]
    return tokens[0] if tokens else "UNKNOWN OR OTHER"


def screen(candidate: tuple[str, str, int]) -> dict:
    make, model, year = candidate
    query = urllib.parse.urlencode({"make": make, "model": model, "modelYear": year})
    complaint_url = f"https://api.nhtsa.gov/complaints/complaintsByVehicle?{query}"
    recall_url = f"https://api.nhtsa.gov/recalls/recallsByVehicle?{query}"
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", f"{make}_{model}_{year}")
    try:
        complaints, c_status, c_raw, c_at, c_sha = fetch(complaint_url)
        recalls, r_status, r_raw, r_at, r_sha = fetch(recall_url)
    except Exception as exc:
        return {"make": make, "model": model, "model_year": year, "status": "failed", "error": str(exc), "complaint_url": complaint_url, "recall_url": recall_url}
    RAW.mkdir(parents=True, exist_ok=True)
    c_path = RAW / f"{prefix}_complaints.json"; r_path = RAW / f"{prefix}_recalls.json"
    c_path.write_bytes(c_raw); r_path.write_bytes(r_raw)
    recalls_rows = recalls.get("results", []) if isinstance(recalls, dict) else []
    complaint_rows = complaints.get("results", []) if isinstance(complaints, dict) else []
    components = []
    for recall in recalls_rows:
        comp = normalize_component(recall.get("Component", ""))
        related = [row for row in complaint_rows if comp != "UNKNOWN OR OTHER" and comp in str(row.get("components", "")).upper()]
        components.append({"component": comp, "campaign": recall.get("NHTSACampaignNumber"), "published_date": recall.get("ReportReceivedDate"), "related_complaint_count": len(related), "summary": recall.get("Summary", "")[:300]})
    components.sort(key=lambda item: (-item["related_complaint_count"], str(item.get("campaign"))))
    best = components[0] if components else None
    return {"make": make, "model": model, "model_year": year, "status": "ok" if c_status == 200 and r_status == 200 else "partial", "complaint_count": len(complaint_rows), "recall_count": len(recalls_rows), "best_component": best.get("component") if best else None, "best_campaign": best.get("campaign") if best else None, "best_published_date": best.get("published_date") if best else None, "best_related_complaint_count": best.get("related_complaint_count", 0) if best else 0, "components": components[:10], "complaint_url": complaint_url, "recall_url": recall_url, "complaints_http_status": c_status, "recalls_http_status": r_status, "complaints_retrieved_at": c_at, "recalls_retrieved_at": r_at, "sha256_complaints": c_sha, "sha256_recalls": r_sha, "raw_complaints_path": str(c_path), "raw_recalls_path": str(r_path), "screened_at": now()}


def main() -> int:
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(screen, candidate) for candidate in CANDIDATES]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: (-row.get("best_related_complaint_count", 0), -row.get("complaint_count", 0), row.get("make", ""), row.get("model", "")))
    report = {"candidate_count": len(CANDIDATES), "screened_count": len(results), "screening_rule": "候选必须有成功投诉和召回 API、公开召回处置日期；优先部件相关投诉量，再看总投诉量；最终还需与 EA23003 主要部件不同。", "results": results, "created_at": now()}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "migration_candidate_screening.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"candidate_count": len(CANDIDATES), "screened_count": len(results), "output": str(path), "top10": [{k: row.get(k) for k in ("make", "model", "model_year", "best_component", "best_campaign", "best_related_complaint_count", "complaint_count", "recall_count", "status")} for row in results[:10]]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
