from __future__ import annotations

import csv
import json
import random
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .core import DATA_DIR, OUTPUT_DIR, DataStore, ToolBox, add_human_feedback, run_fixed_baseline, run_investigation, run_rag_baseline, run_react_baseline, utc_now


def evidence_source_record_ids(documents: list[dict[str, Any]]) -> list[str]:
    return sorted({str(record_id) for item in documents for record_id in item.get("source_record_ids", [])})


def citations_are_verifiable(ledger: list[dict[str, Any]], store: DataStore, case_id: str, cutoff: str) -> bool:
    available = {str(row.get("record_id")): row for row in store.records(case_id)}
    for item in ledger:
        if not item.get("evidence_id") or not (item.get("source_url") or item.get("source_urls") or item.get("citation_locator")):
            return False
        if item.get("published_date", "9999-12-31") > cutoff:
            return False
        for record_id in item.get("source_record_ids", []):
            row = available.get(str(record_id))
            if row is None or row.get("received_date", "9999-12-31") > cutoff:
                return False
    return True


def source_conflict_status(rows: list[dict[str, Any]]) -> str:
    grouped: dict[str, set[str]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("evidence_id", "")), set()).update(url for url in (row.get("source_url"), *row.get("source_urls", [])) if url)
    return "needs_review" if any(len(urls) > 1 for urls in grouped.values() if urls) else "consistent"


def automated_investigation_score(state: dict[str, Any], task: dict[str, Any], citation_valid: bool) -> dict[str, Any]:
    """Pre-registered, model-independent score; no human semantic judgment."""
    tools = [event.get("tool") for event in state.get("tool_events", []) if event.get("ok") and event.get("verified", True)]
    expected = task.get("expected_tools", [])
    components = {
        "plan_execution": int(all(tool in tools for tool in expected[:2])) if expected else int(bool(tools)),
        "evidence_traceability": int(citation_valid and bool(state.get("evidence_ledger"))),
        "counterevidence_action": int(task.get("focus") == "counterevidence" and "retrieve_evidence" in tools),
        "followup_action": int(task.get("focus") == "followup" and bool(state.get("followups"))),
        "bounded_stop": int(state.get("status") in {"completed", "needs_human_review", "max_steps_reached"} and bool(state.get("stop_reason") or state.get("finished_at"))),
    }
    return {"score": sum(components.values()), "max_score": len(components), "components": components, "scoring": "deterministic_tool_trace_v1"}


def automated_baseline_score(result: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    tools = [item.get("tool") for item in result.get("results", []) if item.get("ok")]
    expected = task.get("expected_tools", [])
    components = {
        "plan_execution": int(all(tool in tools for tool in expected[:2])) if expected else int(bool(tools)),
        "evidence_traceability": int(bool(result.get("evidence_ids"))),
        "counterevidence_action": int(task.get("focus") == "counterevidence" and "retrieve_evidence" in tools),
        "followup_action": int(task.get("focus") == "followup" and "create_followup" in tools),
        "bounded_stop": int(result.get("ok", False)),
    }
    return {"score": sum(components.values()), "max_score": len(components), "components": components, "scoring": "deterministic_tool_trace_v1"}


def decision_quality_score(state: dict[str, Any], task: dict[str, Any], citation_valid: bool) -> dict[str, Any]:
    """User-centered V3 score for an auditable investigation decision.

    Quality is based only on decision value. Tool count, latency and tokens
    are reported as cost diagnostics and never increase this score.
    """
    events = [event for event in state.get("tool_events", []) if event.get("ok") and event.get("verified", True)]
    tools = [event.get("tool") for event in events]
    focus = task.get("focus", state.get("focus", "general"))
    expected_by_focus = {
        "trend": {"search_records", "analyze_trend"},
        "links": {"search_records", "link_entities"},
        "counterevidence": {"retrieve_evidence", "link_entities"},
        "evidence": {"search_records", "retrieve_evidence"},
        "followup": {"retrieve_evidence", "create_followup"},
        "report": {"retrieve_evidence", "link_entities"},
        "data_quality": {"search_records", "analyze_trend"},
        "temporal": {"search_records", "retrieve_evidence"},
        "transfer": {"retrieve_evidence", "link_entities"},
    }
    expected = expected_by_focus.get(focus, {"search_records"})
    goal_coverage = len(expected & set(tools)) / len(expected)
    counterevidence_query = any(
        event.get("tool") == "retrieve_evidence"
        and any(term in str((event.get("arguments") or {}).get("query", "")).lower() for term in ("counter", "alternative", "反证", "替代"))
        for event in events
    )
    followups = state.get("followups", [])
    actionable_followup = any(item.get("question") and item.get("rationale") and item.get("evidence_ids") is not None for item in followups)
    next_step = (1.0 if focus == "counterevidence" and counterevidence_query else 0.0)
    next_step = max(next_step, 1.0 if focus == "followup" and actionable_followup else 0.0)
    if focus not in {"counterevidence", "followup"}:
        next_step = 1.0 if (tools and state.get("stop_reason")) else 0.0
    source_families = set()
    stances = set()
    for item in state.get("evidence_ledger", []):
        source_families.add(item.get("source_kind") or item.get("source_url") or item.get("evidence_id"))
        if item.get("stance") in {"support", "oppose", "neutral"}:
            stances.add(item["stance"])
    evidence_quality = min(1.0, len(source_families) / 2.0) if state.get("evidence_ledger") else 0.0
    if focus == "counterevidence" and len(stances & {"support", "oppose"}) >= 2:
        evidence_quality = min(1.0, evidence_quality + 0.25)
    safety = 1.0 if citation_valid and not any("未来" in str(error) or "cutoff" in str(error).lower() for error in state.get("errors", [])) else 0.0
    components = {
        "safety_and_traceability": round(safety, 3),
        "goal_coverage": round(goal_coverage, 3),
        "evidence_quality": round(evidence_quality, 3),
        "next_step_value": round(next_step, 3),
    }
    weights = {"safety_and_traceability": 30, "goal_coverage": 25, "evidence_quality": 20, "next_step_value": 25}
    score = round(sum(components[key] * weight for key, weight in weights.items()), 2)
    return {"score": score, "max_score": 100, "components": components, "weights": weights, "scoring": "decision_value_v3"}


def dynamic_decision_metrics(state: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    """Metrics for V3 branch decisions; independent of tool count."""
    events = [e for e in state.get("tool_events", []) if e.get("ok") and e.get("verified", True)]
    actions = [e.get("tool") for e in events]
    scenario = task.get("scenario", "")
    gold = task.get("gold_next_action")
    first = actions[0] if actions else ("done" if state.get("stop_reason") in {"plan_verified", "incomplete_plan"} else None)
    expected = {
        "empty_recovery": {"retrieve_evidence", "search_records"},
        "source_conflict": {"link_entities", "retrieve_evidence"},
        "competing_hypotheses": {"retrieve_evidence"},
        "evidence_sufficiency": {"done"},
        "cutoff_leakage": {"done", "create_followup"},
        "followup_gap": {"create_followup", "retrieve_evidence"},
    }.get(scenario, {gold} if gold else set())
    # A dynamic action is correct when it matches the state-specific gold
    # action family; no reward is attached to performing extra calls.
    branch_correct = int(first in expected) if expected else 0
    has_guard = bool(state.get("decision_guards"))
    return {"scenario": scenario, "first_action": first, "gold_next_action": gold, "branch_correct": branch_correct, "guard_intervention": int(has_guard), "safe_stop": int(state.get("stop_reason") in {"plan_verified", "duplicate_followup_blocked", "incomplete_plan", "max_steps_reached"})}


def aggregate_metric(values: list[float], seed: int = 17) -> dict[str, float | int | None]:
    """Mean, sample SD and a reproducible percentile bootstrap interval."""
    if not values:
        return {"n": 0, "mean": None, "std": None, "ci95_low": None, "ci95_high": None}
    mean = statistics.mean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    rng = random.Random(seed)
    samples = [statistics.mean(rng.choices(values, k=len(values))) for _ in range(1000)]
    samples.sort()
    return {"n": len(values), "mean": round(mean, 4), "std": round(std, 4), "ci95_low": round(samples[25], 4), "ci95_high": round(samples[974], 4)}


def evaluate(mode: str = "offline", suite: str = "fast") -> dict[str, Any]:
    tasks_path = DATA_DIR / "eval" / ("research_tasks.json" if suite in {"research", "research_api_pilot", "research_api"} else "tasks.json")
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks", []) if isinstance(payload, dict) else payload
    if suite in {"research_api", "research_api_pilot"} and isinstance(payload, dict):
        latest = {item["case_id"]: max(item.get("cutoffs", [])) for item in payload.get("cases", [])}
        tasks = [task for task in tasks if task.get("cutoff_date") == latest.get(task.get("case_id"))]
        if suite == "research_api_pilot":
            # Two complementary objectives per case: trend/coverage and
            # counterevidence/follow-up. This keeps one pilot representative
            # of every expanded case while bounding shared-server usage.
            chosen = []
            for case_id in sorted(latest):
                case_tasks = [task for task in tasks if task.get("case_id") == case_id]
                chosen.extend([task for task in case_tasks if task.get("focus") in {"trend", "counterevidence"}][:2])
            tasks = chosen
    store = DataStore()
    rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    primary = store.case("EA23003") or {}
    cutoff = primary.get("cutoff_date", "2023-11-28")
    migration_candidates = store.migration_candidates("EA23003")
    transfer_index = 0

    def evidence_metrics(result: dict[str, Any]) -> dict[str, Any]:
        ids = sorted(set(result.get("evidence_ids", [])))
        docs = []
        for item in result.get("results", []):
            if item.get("ok"):
                docs.extend(item.get("data", {}).get("evidence", []))
        docs_by_id = {item.get("evidence_id"): item for item in docs if item.get("evidence_id")}
        record_ids = evidence_source_record_ids(list(docs_by_id.values()))
        return {"evidence_document_count": len(ids), "source_record_count": len(record_ids), "source_record_ids": record_ids}

    for task in tasks:
        task_id, kind, case_id = task["task_id"], task["kind"], task["case_id"]
        if kind in {"investigation", "research_investigation"}:
            if not store.case(case_id):
                rows.append({"task_id": task_id, "kind": kind, "status": "blocked_data_missing", "passed": False, "detail": "案例数据包尚未导入。"})
                continue
            task_cutoff = task.get("cutoff_date") or store.case(case_id).get("cutoff_date")
            state = run_investigation(case_id, task["goal"], cutoff_date=task_cutoff, mode=mode, focus=task["focus"])
            evidence_ids = [item["evidence_id"] for item in state["evidence_ledger"]]
            citation_valid = citations_are_verifiable(state["evidence_ledger"], store, case_id, state["cutoff_date"])
            rows.append({
                "task_id": task_id,
                "kind": kind,
                "status": state["status"],
                "passed": state["status"] in {"completed", "needs_human_review"} and citation_valid,
                "mode": mode,
                "tool_calls": state["usage"]["tool_calls"],
                "evidence_count": len(evidence_ids),
                "citation_valid": citation_valid,
                "advice_score_0_2": None,
                "manual_advice_score_required": True,
                "detail": "建议质量需人工按 0-2 分量表评分；自动检查只验证执行与证据引用结构。",
                "automated_score": automated_investigation_score(state, task, citation_valid),
            })
            task_cutoff = task.get("cutoff_date") or store.case(case_id).get("cutoff_date", cutoff)
            fixed_started = time.perf_counter(); fixed = run_fixed_baseline(case_id, task_cutoff, task["goal"]); fixed_latency = round((time.perf_counter() - fixed_started) * 1000)
            rag_started = time.perf_counter(); rag = run_rag_baseline(case_id, task_cutoff, task["goal"]); rag_latency = round((time.perf_counter() - rag_started) * 1000)
            react_started = time.perf_counter(); react = run_react_baseline(case_id, task_cutoff, task["goal"], task.get("focus", "general")); react_latency = round((time.perf_counter() - react_started) * 1000)
            react_state = react["state"]
            react_citation_valid = citations_are_verifiable(react_state.get("evidence_ledger", []), store, case_id, task_cutoff)
            comparisons.append({
                "task_id": task_id,
                "fixed_workflow_tool_calls": fixed["tool_calls"],
                "fixed_workflow_evidence_count": len(set(fixed["evidence_ids"])),
                "plain_rag_tool_calls": rag["tool_calls"],
                "plain_rag_evidence_count": len(set(rag["evidence_ids"])),
                "agent_tool_calls": state["usage"]["tool_calls"],
                "agent_evidence_count": len(set(evidence_ids)),
                "mode": mode,
                "quality_judgment": "pending_manual_review",
                "fixed_workflow_source_record_count": evidence_metrics(fixed)["source_record_count"],
                "plain_rag_source_record_count": evidence_metrics(rag)["source_record_count"],
                "agent_source_record_count": len(evidence_source_record_ids(state["evidence_ledger"])),
                "fixed_workflow_latency_ms": fixed_latency,
                "plain_rag_latency_ms": rag_latency,
                "react_baseline_tool_calls": react["tool_calls"],
                "react_baseline_evidence_count": len(set(react["evidence_ids"])),
                "react_baseline_source_record_count": len(evidence_source_record_ids(react_state.get("evidence_ledger", []))),
                "react_baseline_latency_ms": react_latency,
                "agent_latency_ms": state["usage"]["latency_ms"],
                "agent_total_tokens": state["usage"]["total_tokens"],
                "model_cost_usd": None,
                "fixed_workflow_automated_score": automated_baseline_score(fixed, task),
                "plain_rag_automated_score": automated_baseline_score(rag, task),
                "react_baseline_automated_score": automated_investigation_score(react_state, task, react_citation_valid),
                "agent_automated_score": automated_investigation_score(state, task, citation_valid),
                "react_decision_value_v3": decision_quality_score(react_state, task, react_citation_valid),
                "agent_decision_value_v3": decision_quality_score(state, task, citation_valid),
            })
        elif kind == "transfer":
            if transfer_index >= len(migration_candidates):
                rows.append({"task_id": task_id, "kind": kind, "status": "blocked_data_missing", "passed": False, "detail": "缺少不同主要部件类别且带公开结案材料和投诉记录的迁移案例快照。"})
            else:
                migration_case = migration_candidates[transfer_index]
                transfer_index += 1
                transfer_id = migration_case["case_id"]
                transfer_cutoff = migration_case.get("cutoff_date", "")
                state = run_investigation(transfer_id, task["goal"], cutoff_date=transfer_cutoff, mode=mode, focus="transfer")
                rows.append({"task_id": task_id, "case_id": transfer_id, "kind": kind, "status": state["status"], "passed": state["status"] in {"completed", "needs_human_review"}, "mode": mode, "tool_calls": state["usage"]["tool_calls"], "evidence_count": len(state["evidence_ledger"]), "detail": "已按公开投诉量与不同部件类别筛选并运行精简迁移回放。"})
                fixed_started = time.perf_counter(); fixed = run_fixed_baseline(transfer_id, transfer_cutoff, task["goal"]); fixed_latency = round((time.perf_counter() - fixed_started) * 1000)
                rag_started = time.perf_counter(); rag = run_rag_baseline(transfer_id, transfer_cutoff, task["goal"]); rag_latency = round((time.perf_counter() - rag_started) * 1000)
                react_started = time.perf_counter(); react = run_react_baseline(transfer_id, transfer_cutoff, task["goal"], "transfer"); react_latency = round((time.perf_counter() - react_started) * 1000)
                react_state = react["state"]
                comparisons.append({
                    "task_id": task_id,
                    "fixed_workflow_tool_calls": fixed["tool_calls"],
                    "fixed_workflow_evidence_count": len(set(fixed["evidence_ids"])),
                    "plain_rag_tool_calls": rag["tool_calls"],
                    "plain_rag_evidence_count": len(set(rag["evidence_ids"])),
                    "agent_tool_calls": state["usage"]["tool_calls"],
                    "agent_evidence_count": len(set(item["evidence_id"] for item in state["evidence_ledger"])),
                    "mode": mode,
                    "quality_judgment": "pending_manual_review",
                    "fixed_workflow_source_record_count": evidence_metrics(fixed)["source_record_count"],
                    "plain_rag_source_record_count": evidence_metrics(rag)["source_record_count"],
                    "agent_source_record_count": len(evidence_source_record_ids(state["evidence_ledger"])),
                    "fixed_workflow_latency_ms": fixed_latency,
                    "plain_rag_latency_ms": rag_latency,
                    "react_baseline_tool_calls": react["tool_calls"],
                    "react_baseline_evidence_count": len(set(react["evidence_ids"])),
                    "react_baseline_source_record_count": len(evidence_source_record_ids(react_state.get("evidence_ledger", []))),
                    "react_baseline_latency_ms": react_latency,
                    "agent_latency_ms": state["usage"]["latency_ms"],
                    "agent_total_tokens": state["usage"]["total_tokens"],
                    "model_cost_usd": None,
                    "fixed_workflow_automated_score": automated_baseline_score(fixed, task),
                    "plain_rag_automated_score": automated_baseline_score(rag, task),
                    "react_baseline_automated_score": automated_investigation_score(react_state, task, citations_are_verifiable(react_state.get("evidence_ledger", []), store, transfer_id, transfer_cutoff)),
                    "agent_automated_score": automated_investigation_score(state, task, citations_are_verifiable(state["evidence_ledger"], store, transfer_id, transfer_cutoff)),
                })
        elif kind == "edge_empty":
            result = ToolBox(store).call("search_records", {"filters": {"model": "NO_SUCH_MODEL"}}, case_id, cutoff)
            passed = result.get("ok") and result.get("data", {}).get("count") == 0
            rows.append({"task_id": task_id, "kind": kind, "status": "passed" if passed else "failed", "passed": bool(passed), "tool_calls": 1, "detail": "不存在的车型返回空结果。" if passed else result.get("error", "空结果断言失败")})
        elif kind == "edge_cutoff":
            result = ToolBox(store).call("retrieve_evidence", {"query": "EA23003 close resume", "case_id": case_id, "cutoff_date": "2023-11-28"}, case_id, cutoff)
            future = [row for row in result.get("data", {}).get("evidence", []) if row.get("published_date", "") > cutoff]
            passed = result.get("ok") and not future
            rows.append({"task_id": task_id, "kind": kind, "status": "passed" if passed else "failed", "passed": bool(passed), "tool_calls": 1, "detail": "截点后材料被检索层排除。" if passed else "发现截点后材料泄漏。"})
        elif kind == "edge_invalid_date":
            result = ToolBox(store).call("search_records", {"cutoff_date": "2023/11/28", "filters": {}}, case_id, "2023/11/28")
            passed = not result.get("ok") and "YYYY-MM-DD" in result.get("error", "")
            rows.append({"task_id": task_id, "kind": kind, "status": "passed" if passed else "failed", "passed": bool(passed), "tool_calls": 1, "detail": result.get("error", "无效日期处理断言失败")})
        elif kind == "edge_tool_failure":
            result = ToolBox(store).call("delete_records", {}, case_id, cutoff)
            passed = not result.get("ok") and "未知工具" in result.get("error", "")
            rows.append({"task_id": task_id, "kind": kind, "status": "passed" if passed else "failed", "passed": bool(passed), "tool_calls": 1, "detail": result.get("error", "未知工具处理断言失败")})
        elif kind == "edge_missing_fields":
            malformed = {"evidence_id": "E-MISSING", "title": "malformed", "published_date": "2023-01-01"}
            passed = not citations_are_verifiable([malformed], store, case_id, cutoff)
            rows.append({"task_id": task_id, "kind": kind, "status": "passed" if passed else "failed", "passed": bool(passed), "tool_calls": 0, "detail": "缺少来源定位或关联原始记录时拒绝作为可核验证据。"})
        elif kind == "edge_source_conflict":
            conflict = [{"evidence_id": "E-CONFLICT", "source_url": "https://a.example"}, {"evidence_id": "E-CONFLICT", "source_url": "https://b.example"}]
            passed = source_conflict_status(conflict) == "needs_review"
            rows.append({"task_id": task_id, "kind": kind, "status": "passed" if passed else "failed", "passed": passed, "tool_calls": 0, "detail": "冲突来源被标记为 needs_review，未覆盖原值。"})
        elif kind == "feedback_loop":
            state = run_investigation(case_id, task["goal"], mode=mode, focus="followup")
            before = len(state.get("tool_events", []))
            if state.get("followups"):
                updated = add_human_feedback(state["investigation_id"], state["followups"][0]["followup_id"], "人工反馈：未发现维修更换记录，建议核查原始工单。")
                continued = run_investigation(case_id, task["goal"], updated["cutoff_date"], mode, "followup", updated)
                passed = bool(continued.get("human_feedback")) and len(continued.get("tool_events", [])) > before and continued.get("status") == "completed"
                rows.append({"task_id": task_id, "kind": kind, "status": "passed" if passed else "failed", "passed": passed, "tool_calls": continued["usage"]["tool_calls"], "detail": "已生成补查任务、录入人工反馈并继续调查。" if passed else "反馈闭环未完成。"})
            else:
                rows.append({"task_id": task_id, "kind": kind, "status": "failed", "passed": False, "tool_calls": state["usage"]["tool_calls"], "detail": "未生成补查任务。"})
        elif kind == "edge_cutoff_early":
            result = ToolBox(store).call("retrieve_evidence", {"query": "steering", "limit": 10}, case_id, task.get("cutoff_date", "2023-06-30"))
            passed = result.get("ok") and all(item.get("published_date", "9999-12-31") <= task["cutoff_date"] for item in result.get("data", {}).get("evidence", []))
            rows.append({"task_id": task_id, "kind": kind, "status": "passed" if passed else "failed", "passed": bool(passed), "tool_calls": 1, "detail": "早期截点过滤通过。" if passed else "发现早期截点泄漏。"})
        elif kind == "edge_empty_evidence":
            result = ToolBox(store).call("retrieve_evidence", {"query": "NO_SUCH_EVIDENCE_TERM", "limit": 10}, case_id, cutoff)
            passed = result.get("ok") and result.get("data", {}).get("count") == 0
            rows.append({"task_id": task_id, "kind": kind, "status": "passed" if passed else "failed", "passed": bool(passed), "tool_calls": 1, "detail": "不存在的证据查询返回空集合。" if passed else "空证据查询异常。"})
        elif kind == "edge_plan_stop":
            state = run_investigation(case_id, task["goal"], mode=mode, focus="general")
            passed = bool(state.get("stop_reason")) and state.get("steps", 0) <= 8
            rows.append({"task_id": task_id, "kind": kind, "status": "passed" if passed else "failed", "passed": passed, "tool_calls": state["usage"]["tool_calls"], "detail": f"停止原因：{state.get('stop_reason')}"})

    metric_keys = {
        "fixed_workflow": "fixed_workflow_automated_score",
        "plain_rag": "plain_rag_automated_score",
        "react": "react_baseline_automated_score",
        "active_eig_or_api": "agent_automated_score",
    }
    aggregate_scores = {
        strategy: aggregate_metric([float(item[key]["score"]) for item in comparisons if item.get(key)])
        for strategy, key in metric_keys.items()
    }
    aggregate_latency = {
        strategy: aggregate_metric([float(item[key]) for item in comparisons if item.get(key) is not None])
        for strategy, key in {
            "fixed_workflow": "fixed_workflow_latency_ms",
            "plain_rag": "plain_rag_latency_ms",
            "react": "react_baseline_latency_ms",
            "active_eig_or_api": "agent_latency_ms",
        }.items()
    }
    decision_value_aggregates = {
        "react": aggregate_metric([float(item["react_decision_value_v3"]["score"]) for item in comparisons if item.get("react_decision_value_v3")]),
        "active_eig_or_api": aggregate_metric([float(item["agent_decision_value_v3"]["score"]) for item in comparisons if item.get("agent_decision_value_v3")]),
    }
    summary = {
        "created_at": utc_now(),
        "mode": mode,
        "suite": suite,
        "task_count": len(rows),
        "executed_count": sum(row.get("status") not in {"blocked_data_missing", "ready_not_run"} for row in rows),
        "passed_count": sum(bool(row.get("passed")) for row in rows),
        "blocked_count": sum(row.get("status") == "blocked_data_missing" for row in rows),
        "failed_count": sum(row.get("status") == "failed" for row in rows),
        "rows": rows,
        "comparisons": comparisons,
        "aggregate_scores": aggregate_scores,
        "aggregate_latency_ms": aggregate_latency,
        "aggregate_decision_value_v2": decision_value_aggregates,
        "interpretation": "固定流程、普通 RAG 和主动调查 Agent 使用同一案例快照和截点；自动评分只衡量预注册的工具轨迹、证据可追溯性、反证动作、补查动作和停止边界，不等同于语义正确性或企业效率收益。",
    }
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUTPUT_DIR / "evaluations"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"eval-{suite}-{run_id}"
    json_path = out_dir / f"{stem}.json"
    csv_path = out_dir / f"{stem}.csv"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    columns = sorted({key for row in rows for key in row})
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    scored = [row["automated_score"]["score"] for row in rows if row.get("automated_score")]
    lines = ["# Agent 评测结果", "", f"- 评测套件：`{suite}`", f"- 运行模式：`{mode}`", f"- 用例数：{summary['task_count']}", f"- 已运行：{summary['executed_count']}", f"- 通过：{summary['passed_count']}", f"- 数据缺失阻塞：{summary['blocked_count']}", f"- 失败：{summary['failed_count']}", f"- 自动轨迹评分：{sum(scored)}/{len(scored)*5 if scored else 0}", "", f"> {summary['interpretation']}", "", "## 用例明细", "", "| 用例 | 类型 | 状态 | 自动评分 | 结果 | 说明 |", "| --- | --- | --- | ---: | --- | --- |"]
    for row in rows:
        score = f"{row['automated_score']['score']}/{row['automated_score']['max_score']}" if row.get("automated_score") else "—"
        lines.append(f"| {row['task_id']} | {row['kind']} | {row['status']} | {score} | {'通过' if row.get('passed') else '未通过/未运行'} | {row.get('detail', '')} |")
    lines.extend(["", "## 基线比较", "", "证据数是唯一证据文档数；来源记录数是这些文档关联的去重原始投诉编号数。两者不能混为一谈。", "", "| 用例 | 固定流程调用/文档/记录 | 普通 RAG 调用/文档/记录 | ReAct 调用/文档/记录 | 主动 Agent 调用/文档/记录 |", "| --- | ---: | ---: | ---: | ---: |"])
    for row in comparisons:
        lines.append(f"| {row['task_id']} | {row['fixed_workflow_tool_calls']}/{row['fixed_workflow_evidence_count']}/{row['fixed_workflow_source_record_count']} | {row['plain_rag_tool_calls']}/{row['plain_rag_evidence_count']}/{row['plain_rag_source_record_count']} | {row['react_baseline_tool_calls']}/{row['react_baseline_evidence_count']}/{row['react_baseline_source_record_count']} | {row['agent_tool_calls']}/{row['agent_evidence_count']}/{row['agent_source_record_count']} |")
    lines.extend(["", "## 聚合结果", "", "自动分数为预注册的执行与可追溯行为分数，不等同于语义正确性。均值后面的区间是固定随机种子的 bootstrap 95% 区间。", "", "| 策略 | 自动分数均值（95% CI） | 平均耗时 ms（95% CI） |", "| --- | ---: | ---: |"])
    for strategy in aggregate_scores:
        score = aggregate_scores[strategy]
        latency = aggregate_latency.get(strategy, {})
        lines.append(f"| {strategy} | {score.get('mean')} ({score.get('ci95_low')}, {score.get('ci95_high')}) | {latency.get('mean')} ({latency.get('ci95_low')}, {latency.get('ci95_high')}) |")
    lines.extend(["", "建议质量评分：由人工按预先固定的 0-2 分量表完成；不要把工具调用量或检索数量当成答案质量。", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    summary["json_path"] = str(json_path)
    summary["csv_path"] = str(csv_path)
    summary["markdown_path"] = str(md_path)
    return summary
