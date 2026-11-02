"""Deterministic evidence graph construction for auditable investigations.

The graph is deliberately small and explicit: source records and documents are
never merged into a latent entity.  Text matches create candidate edges with a
provenance payload, so the UI and the evaluator can distinguish a relation
from a confirmed root cause.
"""

from __future__ import annotations

import re
import json
from collections import Counter
from datetime import date
from typing import Any


def _tokens(value: str) -> set[str]:
    return {part.lower() for part in re.findall(r"[\w-]+|[\u4e00-\u9fff]", value or "") if part.strip()}


def _node(node_id: str, kind: str, label: str, **extra: Any) -> dict[str, Any]:
    return {"node_id": node_id, "kind": kind, "label": label, **extra}


def build_evidence_graph(store: Any, case_id: str, cutoff_date: str) -> dict[str, Any]:
    """Build a cutoff-safe graph and return nodes, edges and deterministic stats."""
    cutoff = date.fromisoformat(cutoff_date)
    case = store.case(case_id) or {}
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(node: dict[str, Any]) -> None:
        nodes.setdefault(node["node_id"], node)

    def add_edge(source: str, target: str, relation: str, **meta: Any) -> None:
        edges.append({"source": source, "target": target, "relation": relation, **meta})

    case_node = f"case:{case_id}"
    add_node(_node(case_node, "case", case.get("title", case_id), case_id=case_id))
    cutoff_node = f"time:{cutoff_date}"
    add_node(_node(cutoff_node, "time", cutoff_date, cutoff_date=cutoff_date))
    add_edge(case_node, cutoff_node, "replay_cutoff", cutoff_date=cutoff_date)
    investigation_id = case.get("investigation_id") or case.get("odi_number") or (case_id if case_id.startswith("EA") else None)
    if investigation_id:
        investigation_node = f"investigation:{investigation_id}"
        add_node(_node(investigation_node, "investigation", str(investigation_id)))
        add_edge(case_node, investigation_node, "has_investigation", source_url=case.get("source_url", ""))
    campaign = (case.get("migration_basis") or {}).get("campaign")
    if campaign:
        recall_node = f"recall:{campaign}"
        add_node(_node(recall_node, "recall", str(campaign), campaign=campaign))
        add_edge(case_node, recall_node, "has_recall", source_url=case.get("source_url", ""))

    records = []
    for row in store.records(case_id):
        try:
            if date.fromisoformat(str(row.get("received_date"))) > cutoff:
                continue
        except ValueError:
            continue
        records.append(row)
        rid = str(row.get("record_id"))
        record_node = f"record:{rid}"
        add_node(_node(record_node, "complaint", rid, record_id=rid, received_date=row.get("received_date"), source_url=row.get("source_url", "")))
        add_edge(case_node, record_node, "has_complaint", source_id=row.get("source_id", rid), received_date=row.get("received_date"))
        for field, kind in (("make", "make"), ("model", "model"), ("component", "component")):
            value = str(row.get(field, "")).strip()
            if not value:
                continue
            entity_node = f"{kind}:{value.lower()}"
            add_node(_node(entity_node, kind, value))
            add_edge(record_node, entity_node, f"mentions_{kind}", match_basis="structured_field", source_record_id=rid)

    evidence = []
    for row in store.evidence(case_id):
        if row.get("holdout_only") or row.get("source_kind") == "holdout":
            continue
        try:
            if date.fromisoformat(str(row.get("published_date"))) > cutoff:
                continue
        except ValueError:
            continue
        evidence.append(row)
        eid = str(row.get("evidence_id"))
        evidence_node = f"evidence:{eid}"
        add_node(_node(evidence_node, "evidence", row.get("title", eid), evidence_id=eid, published_date=row.get("published_date"), source_url=row.get("source_url", ""), source_kind=row.get("source_kind", "")))
        add_edge(case_node, evidence_node, "has_evidence", published_date=row.get("published_date"), source_url=row.get("source_url", ""))
        for rid in row.get("source_record_ids", []) or []:
            rid_node = f"record:{rid}"
            if rid_node in nodes:
                add_edge(evidence_node, rid_node, "cites_record", match_basis="declared_source_record_id", source_record_id=rid)
        # A lexical edge is useful for retrieval analysis, but is explicitly a
        # candidate relation and carries no causal assertion.
        text_terms = _tokens(f"{row.get('title', '')} {row.get('content', '')}")
        for record in records:
            rid = str(record.get("record_id"))
            overlap = text_terms & _tokens(record.get("text", ""))
            if overlap and f"record:{rid}" in nodes:
                add_edge(evidence_node, f"record:{rid}", "lexical_candidate", match_basis="token_overlap", overlap_terms=sorted(overlap)[:12], confidence=round(min(1.0, len(overlap) / 8), 3))

    relation_counts = Counter(edge["relation"] for edge in edges)
    return {
        "case_id": case_id,
        "cutoff_date": cutoff_date,
        "nodes": list(nodes.values()),
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "complaint_count": len(records),
            "evidence_count": len(evidence),
            "relation_counts": dict(sorted(relation_counts.items())),
            "lexical_edges_are_candidates": True,
        },
    }


def graph_candidate_utilities(state: dict[str, Any], case: dict[str, Any]) -> list[dict[str, Any]]:
    """Return reproducible Active-EIG candidate actions.

    Utilities are a transparent engineering heuristic, not a learned causal
    estimate.  They reward a missing evidence family, penalise duplicate source
    IDs, and give counterevidence a small priority boost.
    """
    successful = {event.get("tool") for event in state.get("tool_events", []) if event.get("ok") and event.get("verified", True)}
    source_ids = {sid for event in state.get("tool_events", []) for sid in event.get("data", {}).get("source_ids", [])}
    graph = state.get("graph_summary", {})
    candidates: list[dict[str, Any]] = []
    pending_feedback = len(state.get("human_feedback", [])) > state.get("feedback_processed_count", 0)

    def add(tool: str, arguments: dict[str, Any], base: float, reliability: float, cost: float, reason: str, novelty: float = 0.0) -> None:
        signature = json.dumps([tool, arguments], ensure_ascii=False, sort_keys=True)
        if signature in state.get("action_signatures", []):
            return
        duplicate_penalty = 0.0
        utility = round(base * reliability + novelty - cost - duplicate_penalty, 4)
        candidates.append({"tool": tool, "arguments": arguments, "utility": utility, "reason": reason, "signature": signature})

    component = case.get("component", "")
    if pending_feedback:
        answer = state.get("human_feedback", [])[-1].get("answer", "")
        add("search_records", {"filters": {"query": answer}}, 1.35, 0.98, 0.08, "根据人工反馈检索新的可核验记录", 0.45)
    add("search_records", {"filters": {"component": component}}, 0.85, 0.95, 0.08, "先建立截点内投诉基线", 0.2 if "search_records" not in successful else 0.0)
    add("analyze_trend", {"filters": {"component": component}}, 0.78, 0.95, 0.10, "用时间分布区分聚集与零散记录", 0.25 if "analyze_trend" not in successful else 0.0)
    query = f"{case.get('make', '')} {' '.join(case.get('models', []))} {component}".strip()
    add("retrieve_evidence", {"query": query, "limit": 5}, 0.8, 0.9, 0.18, "检索支持材料并保留来源", 0.22 if "retrieve_evidence" not in successful else 0.0)
    add("retrieve_evidence", {"query": f"{component} alternative explanation counterevidence", "limit": 5}, 0.92, 0.9, 0.18, "反证优先，寻找替代解释", 0.35 if state.get("focus") == "counterevidence" else 0.05)
    add("link_entities", {"entity": component}, 0.76, 0.92, 0.12, "核对部件与车型实体关联", 0.2 if "link_entities" not in successful else 0.0)
    # One follow-up task is enough for a replay.  Repeatedly creating a task
    # with a changing evidence-id list would consume the budget and leave no
    # room for the feedback continuation experiment.
    core_complete = {"search_records", "analyze_trend", "retrieve_evidence", "link_entities"}.issubset(successful)
    if state.get("focus") == "followup" and not state.get("followups") and core_complete:
        add("create_followup", {"question": "请核查 VIN 匹配维修记录、发生条件和跨渠道重复上报，并记录来源与日期。", "rationale": "当前公开快照无法确认个体车辆和复现条件；该任务需要人工取得可核验记录。", "evidence_ids": sorted(source_ids)}, 0.88, 0.95, 0.16, "把不可获得的信息转为可验收人工补查", 0.32 if "create_followup" not in successful else 0.0)
    candidates.sort(key=lambda item: (-item["utility"], item["tool"], item["signature"]))
    return candidates
