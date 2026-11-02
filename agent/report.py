from __future__ import annotations

from pathlib import Path
from typing import Any

from .core import OUTPUT_DIR


def render_report(state: dict[str, Any], case: dict[str, Any]) -> str:
    fixture_warning = case.get("fixture_notice") or ""
    lines = [
        f"# 调查记录：{case.get('title', state['case_id'])}",
        "",
        f"- 调查编号：`{state['investigation_id']}`",
        f"- 调查目标：{state['goal']}",
        f"- 资料截点：{state['cutoff_date']}",
        f"- 运行模式：{state['mode']}",
        f"- 状态：{state['status']}",
        f"- 工具调用：{state['usage']['tool_calls']} 次；总耗时：{state['usage']['latency_ms']} ms；模型 token：{state['usage']['total_tokens']}",
        f"- 证据图：{state.get('graph_summary', {}).get('node_count', 0)} 个节点、{state.get('graph_summary', {}).get('edge_count', 0)} 条边（截点安全）",
        "",
        "> 解释边界：投诉数量仅描述公开记录，不等同真实故障发生率。相关性或文本相似性不能单独证明共同根因。",
    ]
    if fixture_warning:
        lines.extend(["", f"> 数据警示：{fixture_warning}"])
    lines.extend(["", "## 竞争性假设（尚未证实）", ""])
    for hypothesis in state.get("hypotheses", []):
        lines.append(f"- `{hypothesis['hypothesis_id']}` {hypothesis['text']}（{hypothesis['status']}）")
    lines.extend(["", "## 经工具验证的观察", ""])
    for claim in state.get("claims", []):
        if claim.get("kind") == "fact" and claim.get("verified") and any(event.get("step") == claim.get("result_step") and event.get("verified") for event in state.get("tool_events", [])):
            lines.append(f"- {claim['text']} [工具结果：第 {claim['result_step']} 步]")
        else:
            lines.append("- 一项未经验证的表述已隔离，需人工复核。")
    lines.extend(["", "## 调查过程", ""])
    for event in state.get("tool_events", []):
        if event.get("ok") and event.get("verified", True):
            data = event.get("data") or {}
            if event["tool"] == "search_records":
                detail = f"筛选到 {data.get('count', 0)} 条记录。"
            elif event["tool"] == "analyze_trend":
                detail = f"分析 {data.get('record_count', 0)} 条记录，按月分布：`{data.get('monthly_counts', {})}`。"
            elif event["tool"] == "retrieve_evidence":
                detail = f"检索到 {data.get('count', 0)} 条材料。"
            elif event["tool"] == "link_entities":
                detail = f"找到 {data.get('matched_record_count', 0)} 条候选关联。"
            elif event["tool"] == "create_followup":
                detail = f"生成待人工复核任务 `{data.get('followup_id')}`。"
            else:
                detail = "工具执行完成。"
            lines.append(f"{event['step']}. `{event['tool']}`：{detail}")
        else:
            lines.append(f"{event['step']}. `{event['tool']}`：未通过执行或验证，结果不作为已核验观察。")
    if not state.get("tool_events"):
        lines.append("本轮没有成功执行工具调用。")

    lines.extend(["", "## 证据登记", ""])
    if state.get("evidence_ledger"):
        for item in state["evidence_ledger"]:
            source = item.get("source_url") or item.get("citation_locator") or "未提供外部来源"
            lines.append(f"- **{item.get('evidence_id')} - {item.get('title')}**（发布日期：{item.get('published_date')}；立场：`{item.get('stance', 'needs_review')}`；{item.get('review_status')}）  ")
            lines.append(f"  来源：{source}")
    else:
        lines.append("没有检索到截点内可引用的证据材料。")

    lines.extend(["", "## 待补查任务", ""])
    if state.get("followups"):
        for task in state["followups"]:
            lines.append(f"- **{task['status']} - {task['question']}**")
            if task.get("rationale"):
                lines.append(f"  - 理由：{task['rationale']}")
            if task.get("answer"):
                lines.append(f"  - 人工反馈：{task['answer']}")
    else:
        lines.append("本轮未创建待补查任务。")
    lines.extend(["", "## 计划与验证", ""])
    for item in state.get("plan", []):
        lines.append(f"- `{item.get('subtask_id')}` {item.get('title')}：{item.get('status')}；验收：{item.get('acceptance')}")
    for item in state.get("verifications", []):
        lines.append(f"- 第 {item.get('step')} 步 `{item.get('tool')}` 验证：{'通过' if item.get('passed') else '未通过'}（{item.get('checks')}）")
    if state.get("selected_utilities"):
        lines.extend(["", "## 主动信息增益轨迹", ""])
        for item in state["selected_utilities"]:
            lines.append(f"- 第 {item.get('step')} 步选择 `{item.get('tool')}`，utility={item.get('utility')}；理由：{item.get('reason')}")
    if state.get("human_feedback"):
        lines.extend(["", "## 人工反馈", ""])
        for item in state["human_feedback"]:
            lines.append(f"- `{item['followup_id']}`：{item['answer']}")

    lines.extend(["", "## 失败与限制", ""])
    if state.get("errors"):
        lines.extend(f"- {item.get('error', item)}" for item in state["errors"])
    else:
        lines.append("未记录运行错误。")
    lines.append(f"- 本报告来自 `{state['mode']}` 模式；规则策略只验证工程闭环，不代表模型调查质量。" if state["mode"] in {"offline", "react", "active_eig"} else "- 模型生成的工具选择仍需人工复核；运行结果不能替代工程调查结论。")
    return "\n".join(lines) + "\n"


def write_report(state: dict[str, Any], case: dict[str, Any]) -> Path:
    path = OUTPUT_DIR / "reports" / f"{state['investigation_id']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(state, case), encoding="utf-8")
    return path
