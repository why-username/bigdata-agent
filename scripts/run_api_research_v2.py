"""Run the latest-cutoff API suite with per-task checkpointing.

This runner is intentionally sequential and can be restarted after a local
process or SSH tunnel interruption without losing completed tasks.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.core import DataStore, run_fixed_baseline, run_investigation, run_rag_baseline, run_react_baseline
from agent.evaluation import automated_baseline_score, automated_investigation_score, citations_are_verifiable, decision_quality_score, evidence_source_record_ids

OUT = ROOT / "outputs" / "evaluations"
PROGRESS = OUT / "api-research-88-v2-progress.json"


def load_tasks() -> list[dict]:
    payload = json.loads((ROOT / "data" / "eval" / "research_tasks.json").read_text(encoding="utf-8"))
    latest = {item["case_id"]: max(item.get("cutoffs", [])) for item in payload["cases"]}
    return [task for task in payload["tasks"] if task.get("cutoff_date") == latest.get(task.get("case_id"))]


def transient(state: dict) -> bool:
    text = json.dumps(state.get("errors", []), ensure_ascii=False).lower()
    return any(token in text for token in ("网络错误", "connection refused", "timed out", "timeout", "temporary", "502", "503", "504"))


def evidence_count(state: dict) -> int:
    return len({item.get("evidence_id") for item in state.get("evidence_ledger", []) if item.get("evidence_id")})


def run_task(task: dict) -> dict:
    store = DataStore()
    case_id, cutoff = task["case_id"], task["cutoff_date"]
    state = run_investigation(case_id, task["goal"], cutoff_date=cutoff, mode="api", focus=task["focus"])
    citation_valid = citations_are_verifiable(state.get("evidence_ledger", []), store, case_id, cutoff)
    fixed = run_fixed_baseline(case_id, cutoff, task["goal"])
    rag = run_rag_baseline(case_id, cutoff, task["goal"])
    react = run_react_baseline(case_id, cutoff, task["goal"], task["focus"])
    react_state = react["state"]
    return {
        "task_id": task["task_id"], "case_id": case_id, "kind": task["kind"], "status": state["status"],
        "passed": state["status"] in {"completed", "needs_human_review"} and citation_valid,
        "mode": "api", "tool_calls": state["usage"]["tool_calls"], "evidence_count": evidence_count(state),
        "citation_valid": citation_valid, "automated_score": automated_investigation_score(state, task, citation_valid),
        "agent_latency_ms": state["usage"]["latency_ms"], "agent_total_tokens": state["usage"]["total_tokens"],
        "errors": state.get("errors", []),
        "fixed_workflow_automated_score": automated_baseline_score(fixed, task),
        "plain_rag_automated_score": automated_baseline_score(rag, task),
        "react_baseline_automated_score": automated_investigation_score(react_state, task, citations_are_verifiable(react_state.get("evidence_ledger", []), store, case_id, cutoff)),
        "decision_value_v2": decision_quality_score(state, task, citation_valid),
        "react_decision_value_v2": decision_quality_score(react_state, task, citations_are_verifiable(react_state.get("evidence_ledger", []), store, case_id, cutoff)),
        "fixed_workflow_tool_calls": fixed["tool_calls"], "plain_rag_tool_calls": rag["tool_calls"], "react_baseline_tool_calls": react["tool_calls"],
        "agent_source_record_count": len(evidence_source_record_ids(state.get("evidence_ledger", []))),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = load_tasks()
    progress = json.loads(PROGRESS.read_text(encoding="utf-8")) if PROGRESS.exists() else {"suite": "research_api", "created_at": datetime.now(timezone.utc).isoformat(), "rows": []}
    completed = {row["task_id"] for row in progress.get("rows", [])}
    for index, task in enumerate(tasks, start=1):
        if task["task_id"] in completed:
            continue
        attempts = 0
        while True:
            attempts += 1
            try:
                row = run_task(task)
                if row["status"] == "needs_human_review" and transient({"errors": row.get("errors", [])}) and attempts < 100:
                    time.sleep(min(60, 5 * attempts)); continue
                break
            except Exception as exc:
                if attempts >= 100:
                    row = {"task_id": task["task_id"], "case_id": task["case_id"], "kind": task["kind"], "status": "failed", "passed": False, "mode": "api", "errors": [{"error": str(exc), "attempts": attempts}]}
                    break
                time.sleep(min(60, 5 * attempts))
        progress["rows"].append(row)
        progress["rows"].sort(key=lambda item: item["task_id"])
        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        progress["completed_count"] = len(progress["rows"])
        progress["task_count"] = len(tasks)
        tmp = PROGRESS.with_suffix(".tmp")
        tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(PROGRESS)
        print(json.dumps({"index": index, "task_count": len(tasks), "task_id": task["task_id"], "status": row["status"], "passed": row["passed"], "attempts": attempts}, ensure_ascii=False), flush=True)
    final = OUT / "eval-research_api-88-v2.json"
    final.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(final), "task_count": len(tasks), "completed_count": len(progress["rows"]), "failed_count": sum(not row.get("passed") for row in progress["rows"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
