"""Expand the research data package from the 51 ODI close candidates.

The script is deliberately sequential: NHTSA is a public service and the
resulting snapshots must be auditable.  It writes an independent package under
``data/expanded`` so the validated three-case package is never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "expanded"
INVESTIGATION_URL = "https://static.nhtsa.gov/odi/ffdd/inv/FLAT_INV.zip"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def get_json(url: str) -> tuple[dict, int, bytes, str, str]:
    result = subprocess.run(
        ["curl", "-L", "--silent", "--show-error", "--max-time", "60", "-A", "vehicle-investigation-agent/1.0", url, "-w", "\n%{http_code}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-500:])
    body, status = result.stdout.rsplit(b"\n", 1)
    return json.loads(body.decode("utf-8")), int(status), body, now(), sha256(body)


def component_family(value: str) -> str:
    text = re.sub(r"[^A-Z0-9 ]+", " ", (value or "").upper())
    tokens = [token for token in text.split() if token not in {"SYSTEM", "ASSEMBLY", "OTHER", "AND", "THE"}]
    return tokens[0] if tokens else "UNKNOWN"


def component_match(candidate_component: str, complaint_component: str) -> bool:
    wanted = {token for token in re.split(r"[^A-Z0-9]+", (candidate_component or "").upper()) if len(token) >= 4}
    actual = {token for token in re.split(r"[^A-Z0-9]+", (complaint_component or "").upper()) if len(token) >= 4}
    return bool(wanted & actual)


def load_candidates() -> list[dict]:
    path = ROOT / "data" / "processed" / "odi_case_candidates.json"
    return json.loads(path.read_text(encoding="utf-8"))["candidates"]


def screen_candidate(candidate: dict, raw_dir: Path) -> dict:
    make, model, year = candidate["make"], candidate["model"], int(candidate["model_year"])
    query = urllib.parse.urlencode({"make": make, "model": model, "modelYear": year})
    url = f"https://api.nhtsa.gov/complaints/complaintsByVehicle?{query}"
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", f"{candidate['investigation_id']}_{make}_{model}_{year}")
    result = {
        "investigation_id": candidate["investigation_id"],
        "make": make,
        "model": model,
        "model_year": year,
        "component": candidate.get("component", ""),
        "component_family": component_family(candidate.get("component", "")),
        "opened_date": parse_date(candidate.get("opened_date")),
        "closed_date": parse_date(candidate.get("closed_date")),
        "title": candidate.get("title", "").strip(),
        "source_url": url,
        "investigation_source_url": INVESTIGATION_URL,
        "screened_at": now(),
    }
    try:
        payload, status, body, retrieved_at, digest = get_json(url)
    except Exception as exc:
        result.update({"status": "fetch_failed", "error": str(exc), "complaint_count": 0, "related_complaint_count": 0})
        return result
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{prefix}_complaints.json"
    raw_path.write_bytes(body)
    rows = payload.get("results", []) if isinstance(payload, dict) else []
    cutoff = result["closed_date"]
    in_window = [row for row in rows if not cutoff or (parse_date(row.get("dateComplaintFiled")) or "9999-12-31") <= cutoff]
    related = [row for row in in_window if component_match(candidate.get("component", ""), str(row.get("components", "")))]
    result.update({
        "status": "ok" if status == 200 else "http_error",
        "http_status": status,
        "complaint_count": len(rows),
        "pre_close_complaint_count": len(in_window),
        "related_complaint_count": len(related),
        "component_match_rate": round(len(related) / max(1, len(in_window)), 4),
        "retrieved_at": retrieved_at,
        "saved_at": now(),
        "sha256": digest,
        "raw_path": str(raw_path),
        "rows": rows,
    })
    return result


def choose(results: list[dict], limit: int = 8) -> list[dict]:
    # EA23003 and its PE predecessor remain the main-case chain.  They are
    # deliberately excluded from the migration pool even when their complaint
    # counts dominate the ranking.
    eligible = [row for row in results if row.get("investigation_id") not in {"EA23003", "PE23005"} and row.get("component_family") not in {"STEERING", "UNKNOWN"} and row.get("status") == "ok" and row.get("pre_close_complaint_count", 0) > 0 and row.get("related_complaint_count", 0) > 0 and row.get("closed_date")]
    eligible.sort(key=lambda row: (-row["related_complaint_count"], -row["pre_close_complaint_count"], row["investigation_id"]))
    selected: list[dict] = []
    families: set[str] = set()
    for row in eligible:
        family = row["component_family"]
        if family in families:
            continue
        selected.append(row)
        families.add(family)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        for row in eligible:
            if row["investigation_id"] not in {item["investigation_id"] for item in selected}:
                selected.append(row)
            if len(selected) >= limit:
                break
    return selected


def build_package(selected: list[dict], output: Path) -> dict:
    cases: list[dict] = []
    records: list[dict] = []
    evidence: list[dict] = []
    manifest: list[dict] = []
    source_candidates = {item["investigation_id"]: item for item in load_candidates()}
    for item in selected:
        inv_id = item["investigation_id"]
        source = source_candidates[inv_id]
        case_id = f"MIG-ODI-{inv_id}"
        cutoff = item["closed_date"]
        rows = item.get("rows", [])
        eligible_rows = [row for row in rows if not cutoff or (parse_date(row.get("dateComplaintFiled")) or "9999-12-31") <= cutoff]
        cases.append({
            "case_id": case_id,
            "title": f"{item['make']} {item['model']} {item['model_year']}：{item['title']}",
            "make": item["make"],
            "models": [item["model"]],
            "component": item["component"].lower(),
            "cutoff_date": cutoff,
            "data_status": "public_snapshot_migration_expanded",
            "source_url": INVESTIGATION_URL,
            "retrieved_at": item["retrieved_at"],
            "saved_at": item["saved_at"],
            "fixture_notice": "研究扩展迁移案例：投诉 API 快照与 ODI 结案摘要，适用于公开资料历史回放。",
            "migration_basis": {
                "investigation_id": inv_id,
                "component_family": item["component_family"],
                "related_complaint_count": item["related_complaint_count"],
                "public_material_type": "odi_close_resume_plus_nhtsa_complaints",
            },
        })
        source_ids: list[str] = []
        for row in eligible_rows:
            rid = str(row.get("odiNumber") or row.get("ODINumber") or "")
            if not rid:
                continue
            received = parse_date(row.get("dateComplaintFiled"))
            source_ids.append(rid)
            records.append({
                "record_id": rid,
                "case_id": case_id,
                "record_type": "complaint",
                "make": item["make"],
                "model": item["model"],
                "official_model": item["model"].upper(),
                "model_year": item["model_year"],
                "component": row.get("components", ""),
                "received_date": received,
                "occurred_date": parse_date(row.get("dateOfIncident")),
                "text": row.get("summary", ""),
                "source_id": rid,
                "source_url": item["source_url"],
                "source_publication_date": received,
                "retrieved_at": item["retrieved_at"],
                "saved_at": item["saved_at"],
                "raw_nhtsa": row,
                "is_demo_fixture": False,
            })
        evidence.append({
            "evidence_id": f"{case_id}-ODI-CLOSE",
            "case_id": case_id,
            "title": f"NHTSA ODI {inv_id} close resume",
            "content": source.get("summary", ""),
            "published_date": cutoff,
            "source_kind": "investigation_close",
            "source_url": INVESTIGATION_URL,
            "citation_locator": f"investigation_id={inv_id}",
            "source_record_ids": sorted(set(source_ids)),
            "is_close_material": True,
            "holdout_only": False,
            "retrieved_at": item["retrieved_at"],
            "saved_at": item["saved_at"],
        })
        evidence.append({
            "evidence_id": f"{case_id}-COMPLAINT-SNAPSHOT",
            "case_id": case_id,
            "title": f"NHTSA complaints before ODI close for {inv_id}",
            "content": f"API snapshot contains {len(eligible_rows)} complaints filed on or before {cutoff}; {item['related_complaint_count']} match the investigation component family.",
            "published_date": cutoff,
            "source_kind": "nhtsa_complaint_snapshot_aggregate",
            "source_url": item["source_url"],
            "citation_locator": "complaintsByVehicle results",
            "source_record_ids": sorted(set(source_ids)),
            "is_close_material": False,
            "holdout_only": False,
            "retrieved_at": item["retrieved_at"],
            "saved_at": item["saved_at"],
        })
        manifest.append({"kind": "expanded_case", "case_id": case_id, "investigation_id": inv_id, "source_url": item["source_url"], "investigation_source_url": INVESTIGATION_URL, "raw_path": item.get("raw_path"), "sha256": item.get("sha256"), "saved_at": item.get("saved_at")})
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("cases.json", cases), ("records.json", records), ("evidence.json", evidence), ("manifest.json", manifest)):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"selected_count": len(selected), "case_ids": [case["case_id"] for case in cases], "record_count": len(records), "evidence_count": len(evidence), "output": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description="从 51 个 ODI 结案候选扩展研究案例包")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--refresh", action="store_true", help="重新请求候选投诉 API")
    args = parser.parse_args()
    raw_dir = args.output / "raw_complaints"
    report_path = args.output / "qualification_matrix.json"
    if report_path.exists() and not args.refresh:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        results = report["results"]
    else:
        results = []
        seen = set()
        for candidate in load_candidates():
            key = (candidate["investigation_id"], candidate["make"], candidate["model"], candidate["model_year"])
            if key in seen:
                continue
            seen.add(key)
            result = screen_candidate(candidate, raw_dir)
            results.append(result)
            print(json.dumps({k: result.get(k) for k in ("investigation_id", "make", "model", "closed_date", "status", "pre_close_complaint_count", "related_complaint_count")}, ensure_ascii=False), flush=True)
        report = {"created_at": now(), "candidate_count": len(results), "source_url": INVESTIGATION_URL, "results": results}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    selected = choose(results, max(1, args.limit))
    package = build_package(selected, args.output)
    report["selected"] = [{k: item.get(k) for k in ("investigation_id", "make", "model", "model_year", "component", "closed_date", "pre_close_complaint_count", "related_complaint_count", "component_family")} for item in selected]
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"qualification_matrix": str(report_path), **package}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
