#!/usr/bin/env python3
"""Fetch NHTSA public snapshots and create an importable local data directory.

This script never deduplicates or overwrites raw rows. It stores the source URL,
retrieval timestamp, API payload metadata, and original NHTSA fields in the
generated JSON rows. Run it on a machine with outbound HTTPS access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path


API_ROOT = "https://api.nhtsa.gov"
VEHICLES = [
    {"make": "Honda", "model": "Civic", "model_year": 2022},
    {"make": "Honda", "model": "Civic", "model_year": 2023},
    {"make": "Honda", "model": "CR-V", "model_year": 2023},
    {"make": "Acura", "model": "Integra", "model_year": 2023},
]
CATALOG_ROOT = "https://vpic.nhtsa.dot.gov/api/vehicles"
HONDA_CIVIC_VARIANTS = ["CIVIC SEDAN", "CIVIC HATCHBACK", "CIVIC SEDAN SI", "CIVIC HATCHBACK TYPE R"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_date(value: object) -> str:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def get_json(url: str) -> tuple[object, str, int, bytes, str]:
    retrieved_at = now()
    # Capture status and raw bytes so even a structured HTTP 400 response is auditable.
    completed = subprocess.run(
        ["curl", "-L", "--silent", "--show-error", "--max-time", "60", "-A", "vehicle-investigation-agent/1.0", url, "-w", "\n%{http_code}"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip()[-500:])
    body, status_text = completed.stdout.rsplit(b"\n", 1)
    status = int(status_text)
    return json.loads(body.decode("utf-8")), retrieved_at, status, body, hashlib.sha256(body).hexdigest()


def catalog_models(make: str, model_year: int) -> tuple[list[str], dict]:
    query = urllib.parse.urlencode({"make": make, "modelyear": model_year, "format": "json"})
    url = f"{CATALOG_ROOT}/GetModelsForMakeYear/make/{urllib.parse.quote(make)}/modelyear/{model_year}?format=json"
    payload, retrieved_at, status, raw, sha256 = get_json(url)
    if status != 200:
        raise RuntimeError(f"车型目录 API HTTP {status}")
    names = [str(row.get("Model_Name", "")).upper() for row in payload.get("Results", []) if row.get("Model_Name")]
    return names, {"source_url": url, "retrieved_at": retrieved_at, "saved_at": retrieved_at, "http_status": status, "sha256": sha256, "raw_json": payload}


def expand_official_models(user_model: str, make: str, model_year: int, catalog_names: list[str]) -> list[str]:
    normalized = " ".join(user_model.upper().split())
    if make.upper() == "HONDA" and model_year == 2023 and normalized == "CIVIC":
        if "CIVIC" not in catalog_names:
            raise ValueError("车型目录未确认 2023 HONDA CIVIC")
        return HONDA_CIVIC_VARIANTS.copy()
    return [name for name in catalog_names if name == normalized]


def classify_complaints_response(payload: object, http_status: int) -> str:
    if isinstance(payload, dict) and http_status == 400 and payload.get("count") == 0 and "success" in str(payload.get("message", "")).lower():
        return "EMPTY_RESPONSE_UNVERIFIED"
    if http_status != 200:
        return "failed"
    return "ok"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("data/imported"))
    parser.add_argument("--cutoff", default="2023-11-28")
    parser.add_argument("--case-id", default="EA23003")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    snapshot_saved_at = now()

    cases = [{
        "case_id": args.case_id,
        "title": "Honda/Acura 转向阻力调查 EA23003（NHTSA API 快照）",
        "make": "Honda",
        "models": ["Civic", "CR-V", "Integra"],
        "component": "steering",
        "cutoff_date": args.cutoff,
        "data_status": "public_snapshot",
        "source_url": "https://www.nhtsa.gov/nhtsa-datasets-and-apis",
        "retrieved_at": snapshot_saved_at,
        "saved_at": snapshot_saved_at,
        "fixture_notice": "",
    }]
    records: list[dict] = []
    evidence: list[dict] = []
    manifest: list[dict] = []
    raw_api_dir = args.out / "raw" / "api"
    raw_api_dir.mkdir(parents=True, exist_ok=True)
    seen_complaints: dict[str, list[str]] = {}
    for vehicle in VEHICLES:
        try:
            catalog_names, catalog_meta = catalog_models(vehicle["make"], vehicle["model_year"])
        except (RuntimeError, ValueError) as exc:
            manifest.append({"kind": "model_catalog", "vehicle": vehicle, "status": "failed", "error": str(exc), "saved_at": snapshot_saved_at})
            continue
        manifest.append({"kind": "model_catalog", "vehicle": vehicle, "status": "ok", **catalog_meta})
        try:
            official_models = expand_official_models(vehicle["model"], vehicle["make"], vehicle["model_year"], catalog_names)
        except ValueError as exc:
            manifest.append({"kind": "model_mapping", "vehicle": vehicle, "status": "failed", "error": str(exc), "saved_at": snapshot_saved_at})
            continue
        for official_model in official_models:
            query = urllib.parse.urlencode({"make": vehicle["make"], "model": official_model, "modelYear": vehicle["model_year"]})
            url = f"{API_ROOT}/complaints/complaintsByVehicle?{query}"
            try:
                payload, retrieved_at, http_status, raw, sha256 = get_json(url)
            except (RuntimeError, ValueError) as exc:
                manifest.append({"kind": "complaints_api", "vehicle": vehicle, "official_model": official_model, "source_url": url, "status": "failed", "error": str(exc), "saved_at": snapshot_saved_at})
                continue
            raw_name = f"complaints_{vehicle['make']}_{vehicle['model_year']}_{official_model.replace(' ', '_')}.json"
            (raw_api_dir / raw_name).write_bytes(raw)
            count = payload.get("count") if isinstance(payload, dict) else None
            message = str(payload.get("message", "")) if isinstance(payload, dict) else ""
            query_status = classify_complaints_response(payload, http_status)
            manifest.append({"kind": "complaints_api", "vehicle": vehicle, "official_model": official_model, "source_url": url, "status": query_status, "http_status": http_status, "count": count, "message": message, "retrieved_at": retrieved_at, "saved_at": snapshot_saved_at, "sha256": sha256, "raw_json_path": str(raw_api_dir / raw_name)})
            if query_status != "ok":
                continue
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            for index, row in enumerate(rows):
                record_id = str(row.get("odiNumber") or row.get("ODINumber") or f"{vehicle['make']}-{official_model}-{vehicle['model_year']}-{index}")
                source_models = seen_complaints.setdefault(record_id, [])
                if official_model not in source_models:
                    source_models.append(official_model)
                if any(existing.get("record_id") == record_id for existing in records):
                    existing = next(existing for existing in records if existing.get("record_id") == record_id)
                    existing["source_models"] = source_models.copy()
                    continue
                received = normalize_date(row.get("dateOfComplaint") or row.get("dateComplaintFiled") or row.get("dateReceived") or "")
                occurred = normalize_date(row.get("dateOfIncident") or row.get("dateOfCrash") or received)
                records.append({
                    "record_id": record_id, "case_id": args.case_id, "record_type": "complaint",
                    "make": vehicle["make"], "model": vehicle["model"], "official_model": official_model,
                    "source_models": source_models.copy(), "model_year": vehicle["model_year"],
                    "component": row.get("components") or "steering", "occurred_date": occurred,
                    "received_date": received, "text": row.get("summary") or row.get("complaintDescription") or "",
                    "source_id": record_id, "source_url": url, "retrieved_at": retrieved_at,
                    "saved_at": snapshot_saved_at, "raw_nhtsa": row, "is_demo_fixture": False,
                })
    # The investigation close PDF remains holdout-only. It is indexed as metadata,
    # not as runtime evidence, because its publication date is after the replay cutoff.
    evidence.append({
        "evidence_id": "GOLD-EA23003-CLOSE",
        "case_id": args.case_id,
        "title": "EA23003 Close Resume（留出评测资料）",
        "content": "",
        "published_date": "2025-01-28",
        "source_kind": "holdout",
        "source_url": "https://static.nhtsa.gov/odi/inv/2023/INCLA-EA23003-11060.pdf",
        "citation_locator": "NHTSA official close resume",
        "holdout_only": True,
        "is_demo_fixture": False,
        "retrieved_at": snapshot_saved_at,
        "saved_at": snapshot_saved_at,
    })
    pdf_url = "https://static.nhtsa.gov/odi/inv/2023/INCLA-EA23003-11060.pdf"
    raw_dir = args.out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = raw_dir / "EA23003-INCLA-EA23003-11060.pdf"
    try:
        pdf_result = subprocess.run(
            ["curl", "-L", "--fail", "--silent", "--show-error", "--max-time", "60", "-A", "vehicle-investigation-agent/1.0", pdf_url, "-o", str(pdf_path)],
            check=True,
            capture_output=True,
        )
        manifest.append({"source_url": pdf_url, "retrieved_at": now(), "kind": "investigation_pdf", "status": "ok", "local_path": str(pdf_path)})
    except subprocess.CalledProcessError as exc:
        manifest.append({"source_url": pdf_url, "retrieved_at": now(), "kind": "investigation_pdf", "status": "failed", "error": exc.stderr.decode("utf-8", errors="replace").strip()[-500:]})
    civic_required = set(HONDA_CIVIC_VARIANTS)
    civic_statuses = {
        item.get("official_model"): item.get("status")
        for item in manifest
        if item.get("kind") == "complaints_api"
        and item.get("vehicle", {}).get("make", "").upper() == "HONDA"
        and item.get("vehicle", {}).get("model", "").upper() == "CIVIC"
        and item.get("vehicle", {}).get("model_year") == 2023
    }
    complete_civic = civic_required.issubset(civic_statuses) and all(civic_statuses[name] in {"ok", "EMPTY_RESPONSE_UNVERIFIED"} for name in civic_required)
    cases[0]["official_model_mapping"] = {"input": "Civic", "make": "HONDA", "model_year": 2023, "official_models": HONDA_CIVIC_VARIANTS}
    cases[0]["civic_series_statistics_status"] = "complete" if complete_civic else "incomplete_unverified"
    cases[0]["civic_series_query_statuses"] = civic_statuses
    cases[0]["civic_series_record_count"] = len([row for row in records if row.get("make", "").upper() == "HONDA" and row.get("model_year") == 2023 and row.get("official_model") in civic_required]) if complete_civic else None
    for name, value in (("cases.json", cases), ("records.json", records), ("evidence.json", evidence), ("manifest.json", manifest)):
        (args.out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "case_count": len(cases), "record_count": len(records), "evidence_count": len(evidence), "manifest_count": len(manifest)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
