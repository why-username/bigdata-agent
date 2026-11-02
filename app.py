from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from agent.core import DataStore, add_human_feedback, load_state, run_investigation
from agent.evaluation import evaluate


st.set_page_config(page_title="车辆缺陷主动调查 Agent", page_icon="🔎", layout="wide")
st.title("车辆缺陷主动调查 Agent")
st.caption("公开资料历史回放原型 · 只提供调查辅助，不自动判定安全缺陷")

store = DataStore()
cases = store.cases()
case_by_id = {case["case_id"]: case for case in cases}

with st.sidebar:
    st.header("调查设置")
    case_id = st.selectbox("调查案例", list(case_by_id), format_func=lambda key: case_by_id[key].get("title", key))
    selected_case = case_by_id[case_id]
    cutoff = st.date_input("资料截点", value=__import__("datetime").date.fromisoformat(selected_case.get("cutoff_date", "2023-11-28")))
    mode_label = st.radio("运行模式", ["离线规则", "主动信息增益", "模型 API"], help="离线规则验证普通工具循环；主动信息增益启用证据图和候选动作评分；模型 API 从环境变量读取兼容接口配置。")
    mode = {"离线规则": "offline", "主动信息增益": "active_eig", "模型 API": "api"}[mode_label]
    focus = st.selectbox("调查重点", ["general", "trend", "links", "counterevidence", "evidence", "followup", "report"], format_func=lambda value: {"general": "综合核查", "trend": "投诉趋势", "links": "跨车型关联", "counterevidence": "寻找反证", "evidence": "证据检索", "followup": "生成补查任务", "report": "调查摘要"}[value])

if selected_case.get("data_status") == "synthetic_demo_fixture":
    st.warning(selected_case.get("fixture_notice", "当前案例数据为演示夹具。"))
else:
    st.info(f"数据状态：{selected_case.get('data_status', '未标注')} · 请在报告中核对本地快照来源和发布日期。")

st.markdown("**调查边界**：工具只访问本地快照并遵守所选资料截点。待补查任务仅写入本地记录，不会发送给企业或外部人员。")

goal = st.text_area("调查目标", value="核查转向异常投诉的共同线索，寻找反证并提出下一步补查建议。", height=88)
left, right = st.columns([1, 1])
with left:
    run_clicked = st.button("开始调查", type="primary", use_container_width=True)
with right:
    eval_clicked = st.button("运行冻结评测", use_container_width=True)

if run_clicked:
    try:
        state = run_investigation(case_id, goal, cutoff.isoformat(), mode, focus)
        st.session_state["active_investigation_id"] = state["investigation_id"]
    except Exception as exc:
        st.error(str(exc))

if eval_clicked:
    with st.spinner("正在运行冻结评测…"):
        try:
            result = evaluate(mode)
            st.session_state["latest_evaluation"] = result
        except Exception as exc:
            st.error(str(exc))

evaluation = st.session_state.get("latest_evaluation")
if evaluation:
    st.subheader("最近评测")
    metrics = st.columns(4)
    metrics[0].metric("用例", evaluation["task_count"])
    metrics[1].metric("已运行", evaluation["executed_count"])
    metrics[2].metric("通过", evaluation["passed_count"])
    metrics[3].metric("数据阻塞", evaluation["blocked_count"])
    st.caption(evaluation["interpretation"])
    st.dataframe([{key: row.get(key) for key in ("task_id", "kind", "status", "passed", "tool_calls", "detail")} for row in evaluation["rows"]], use_container_width=True, hide_index=True)
    st.markdown(f"评测结果：[{Path(evaluation['markdown_path']).name}]({Path(evaluation['markdown_path']).as_uri()})")

investigation_id = st.session_state.get("active_investigation_id")
if investigation_id:
    state = load_state(investigation_id)
    case = store.case(state["case_id"]) or {}
    st.divider()
    st.subheader("调查结果")
    cols = st.columns(6)
    cols[0].metric("状态", state["status"])
    cols[1].metric("调查轮次", state["steps"])
    cols[2].metric("工具调用", state["usage"]["tool_calls"])
    cols[3].metric("登记证据", len(state["evidence_ledger"]))
    cols[4].metric("待补查", sum(item["status"] == "pending_human_review" for item in state["followups"]))
    cols[5].metric("证据图边数", state.get("graph_summary", {}).get("edge_count", 0))

    if state.get("fixture_notice"):
        st.warning(state["fixture_notice"])
    st.markdown("**计划**：" + " → ".join(item.get("title", item.get("subtask_id", "")) if isinstance(item, dict) else str(item) for item in state.get("plan", [])))
    tab_process, tab_evidence, tab_graph, tab_followups, tab_report, tab_trace = st.tabs(["调查过程", "证据登记", "证据图", "补查与反馈", "报告", "运行轨迹"])
    with tab_process:
        for event in state.get("tool_events", []):
            label = f"第 {event['step']} 轮 · {event['tool']} · {'完成' if event['ok'] else '失败'}"
            with st.expander(label, expanded=False):
                if event.get("error"):
                    st.error(event["error"])
                if event.get("data"):
                    st.json(event["data"])
        if state.get("errors"):
            st.error("\n".join(item.get("error", "未知错误") for item in state["errors"]))
    with tab_evidence:
        if state.get("evidence_ledger"):
            st.dataframe(state["evidence_ledger"], use_container_width=True, hide_index=True)
        else:
            st.info("当前没有检索到截点内证据。")
    with tab_graph:
        st.json(state.get("graph_summary", {}))
        graph_path = Path(state.get("evidence_graph_path", ""))
        if graph_path.exists():
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            if graph.get("edges"):
                st.dataframe(graph["edges"][:300], use_container_width=True, hide_index=True)
            st.caption("词法匹配边只表示候选关系，不代表共同根因；图已按当前资料截点生成。")
    with tab_followups:
        if state.get("followups"):
            for followup in state["followups"]:
                st.markdown(f"**{followup['followup_id']} · {followup['status']}**")
                st.write(followup["question"])
                if followup.get("rationale"):
                    st.caption(followup["rationale"])
                if followup.get("answer"):
                    st.success(f"人工反馈：{followup['answer']}")
                elif followup["status"] == "pending_human_review":
                    with st.form(f"feedback-{followup['followup_id']}"):
                        answer = st.text_area("模拟补查结果", key=f"answer-{followup['followup_id']}")
                        submitted = st.form_submit_button("记录反馈并继续调查")
                    if submitted:
                        try:
                            updated = add_human_feedback(investigation_id, followup["followup_id"], answer)
                            continued = run_investigation(updated["case_id"], updated["goal"], updated["cutoff_date"], updated["mode"], updated["focus"], updated)
                            st.success("反馈已保存，Agent 已根据反馈继续运行并刷新报告。")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
        else:
            st.info("本轮没有生成待补查任务。")
    with tab_report:
        report_path = Path(state.get("report_path", ""))
        if report_path.exists():
            st.markdown(report_path.read_text(encoding="utf-8"))
            st.download_button("下载 report.md", report_path.read_bytes(), file_name="report.md", mime="text/markdown")
        st.caption(f"状态文件：{investigation_id}.json · 日志追加至 outputs/logs/run_log.jsonl")
    with tab_trace:
        st.json(state)

st.divider()
st.caption("结论限制：系统只提供公开资料调查辅助，不自动判定安全缺陷；每条事实观察必须回到本地快照或确定性工具结果。")
