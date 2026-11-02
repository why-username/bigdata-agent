"""Generate the frozen research-scale task matrix.

The matrix is derived from the local snapshots, so rerunning it after a data
refresh makes the date choices explicit instead of silently using today's
records.  It intentionally emits tasks only; evaluation remains in
``agent.evaluation`` and applies the same cutoff to every strategy.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.core import DATA_DIR, DataStore


GOALS = [
    ("trend", "汇总截点内投诉趋势，并说明投诉统计不能代表真实故障率。", ["search_records", "analyze_trend"]),
    ("links", "检查车型、年款和主要部件之间是否存在值得核查的共同线索。", ["search_records", "link_entities"]),
    ("counterevidence", "提出竞争性解释并寻找支持与反证材料，避免确认偏差。", ["search_records", "retrieve_evidence", "link_entities"]),
    ("evidence", "检查症状文本相似性是否足以支持关联，并保留不确定性。", ["search_records", "retrieve_evidence"]),
    ("followup", "根据当前证据缺口提出带依据和验收条件的下一步补查。", ["search_records", "retrieve_evidence", "create_followup"]),
    ("report", "形成带来源登记、截点说明和限制条件的调查摘要。", ["search_records", "retrieve_evidence"]),
    ("data_quality", "检查缺失字段、重复候选和来源元数据，区分记录质量问题与故障线索。", ["search_records", "analyze_trend", "link_entities"]),
    ("temporal", "核对多个历史截点的结果是否只使用当时可得的记录和证据。", ["search_records", "retrieve_evidence", "analyze_trend"]),
]


def _cutoffs(store: DataStore, case: dict) -> list[str]:
    rows = [row for row in store.records(case["case_id"]) if row.get("received_date")]
    dates = sorted(date.fromisoformat(row["received_date"]) for row in rows)
    end = date.fromisoformat(case["cutoff_date"])
    before = [value for value in dates if value <= end]
    start = before[0] if before else end
    span = (end - start).days
    # 50%, 75% and 100% of the available replay interval.  The final date is
    # always the case's registered public replay cutoff.
    values = [start + timedelta(days=round(span * ratio)) for ratio in (0.5, 0.75)] + [end]
    return sorted({value.isoformat() for value in values})


def build(output: Path) -> dict:
    store = DataStore()
    cases = sorted(
        [case for case in store.cases() if case.get("data_status", "").startswith("public_snapshot")],
        key=lambda item: item.get("case_id", ""),
    )
    if len(cases) < 9:
        raise RuntimeError(f"研究基准扩展需要主案加至少 8 个迁移案例，当前只有 {len(cases)} 个公开快照案例")
    tasks = []
    for case in cases:
        for cutoff_index, cutoff in enumerate(_cutoffs(store, case), start=1):
            for goal_index, (focus, goal, expected_tools) in enumerate(GOALS, start=1):
                tasks.append({
                    "task_id": f"R-{case['case_id']}-{cutoff_index:02d}-{goal_index:02d}",
                    "case_id": case["case_id"],
                    "kind": "research_investigation",
                    "goal": goal,
                    "focus": focus,
                    "cutoff_date": cutoff,
                    "expected_tools": expected_tools,
                    "budget": {"max_steps": 8, "max_tool_retries": 2},
                    "case_component": case.get("component", "unknown"),
                })
    expected_count = len(cases) * len(GOALS) * 3
    if len(tasks) != expected_count:
        raise AssertionError(f"预期 {expected_count} 条任务，实际 {len(tasks)} 条")
    payload = {
        "schema_version": "research-benchmark-v1",
        "created_at": date.today().isoformat(),
        "selection": "all public snapshot cases, eight objectives, three cutoff dates per case",
        "cases": [{"case_id": case["case_id"], "title": case.get("title"), "cutoffs": _cutoffs(store, case)} for case in cases],
        "tasks": tasks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"output": str(output), "case_count": len(cases), "task_count": len(tasks), "cases": payload["cases"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 72 条研究级离线评测任务")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "eval" / "research_tasks.json")
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
