from __future__ import annotations

import json
import mimetypes
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from agent.core import OUTPUT_DIR, DataStore, add_human_feedback, append_jsonl, load_state, run_investigation
from agent.evaluation import evaluate


def load_local_env() -> None:
    """Load uncommitted local demo settings without adding a dependency."""
    env_path = Path(__file__).with_name(".env.local")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if key and value and key not in os.environ:
            os.environ[key] = value


load_local_env()


# Bind locally by default. Set WEBAPP_HOST=0.0.0.0 when the browser is on
# another device or when the desktop app proxies the port externally.
HOST = os.environ.get("WEBAPP_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEBAPP_PORT", "8765"))


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    """Allow quick stop/restart during local Demo iteration."""

    allow_reuse_address = True


def enterprise_overview(case_id: str, cutoff_date: str) -> dict:
    """Return a deterministic, clearly labelled enterprise connector mock.

    The demo never claims these rows came from a real OEM system. The shape is
    intentionally close to what a read-only adapter would return so the UI can
    demonstrate the investigator workflow without an API or credentials.
    """
    store = DataStore()
    case = store.case(case_id) or {}
    records = store.records(case_id)
    evidence = store.evidence(case_id)
    complaints = [row for row in records if row.get("record_type") == "complaint"]
    models = sorted({str(row.get("model")) for row in complaints if row.get("model")})
    component = case.get("component", "unknown")
    complaint_count = len(complaints)
    repair_count = max(3, round(complaint_count * 0.34)) if complaint_count else 0
    field_count = max(1, round(complaint_count * 0.04)) if complaint_count else 0
    batch_count = max(1, len(models)) if models else 1
    sources = [
        {"id": "complaint_crm", "name": "投诉中心 CRM", "kind": "complaint", "status": "已同步", "count": complaint_count, "description": "投诉、症状、地区和时间"},
        {"id": "warranty_repair", "name": "保修与维修工单", "kind": "repair", "status": "可查询", "count": repair_count, "description": f"模拟匹配 {component} 维修记录"},
        {"id": "vehicle_config", "name": "VIN/车辆配置", "kind": "config", "status": "可查询", "count": batch_count, "description": "车型、批次、零件版本"},
        {"id": "field_incident", "name": "道路事件平台", "kind": "incident", "status": "可查询", "count": field_count, "description": "故障码、救援和严重度"},
        {"id": "engineering_docs", "name": "工程文档库", "kind": "engineering", "status": "可查询", "count": len(evidence), "description": "试验、服务公告和变更记录"},
        {"id": "regulatory_public", "name": "监管公开资料", "kind": "regulatory", "status": "已索引", "count": len(evidence), "description": "NHTSA 调查、召回和公开文件"},
        {"id": "case_workflow", "name": "调查工作流", "kind": "workflow", "status": "需审批写入", "count": 0, "description": "8D/CAPA/工程核查任务"},
    ]
    plan = [
        {"source": "complaint_crm", "action": "汇总投诉并去重", "reason": "建立当前案例的信号基线", "state": "已完成"},
        {"source": "warranty_repair", "action": "自动匹配维修工单", "reason": "验证投诉描述是否对应实际维修现象", "state": "待执行"},
        {"source": "vehicle_config", "action": "关联车型、批次和零件版本", "reason": "判断问题是否集中在特定配置", "state": "待执行"},
        {"source": "field_incident", "action": "核查道路事件和故障码", "reason": "评估安全严重度与现场证据", "state": "待执行"},
        {"source": "engineering_docs", "action": "检索支持与反证材料", "reason": "区分共同缺陷和替代解释", "state": "待执行"},
        {"source": "regulatory_public", "action": "关联外部调查与公开处置", "reason": "补充独立来源并检查来源冲突", "state": "待执行"},
    ]
    if complaint_count == 0:
        plan[1]["state"] = "优先执行"
    return {
        "demo_only": True,
        "case_id": case_id,
        "cutoff_date": cutoff_date,
        "case_title": case.get("title", case_id),
        "component": component,
        "models": models or case.get("models", []),
        "sources": sources,
        "plan": plan,
        "metrics": {"complaints": complaint_count, "repair_matches": repair_count, "field_events": field_count, "evidence": len(evidence), "models": len(models or case.get("models", []))},
        "access_note": "演示连接器使用本地脱敏模拟数据；真实部署需替换为企业只读 API，并由权限和审计层控制。",
    }


def enterprise_action(body: dict) -> dict:
    """Record an approval-style action in a local simulated workflow."""
    case_id = str(body.get("case_id", ""))
    action = str(body.get("action", "工程核查任务"))
    task = {
        "audit_id": f"AUDIT-{uuid.uuid4().hex[:8].upper()}",
        "task_id": f"SIM-{uuid.uuid4().hex[:8].upper()}",
        "case_id": case_id,
        "action": action,
        "system": "case_workflow_simulator",
        "status": "已审批（模拟）",
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "demo_only": True,
    }
    append_jsonl(OUTPUT_DIR / "logs" / "enterprise_workflow_simulator.jsonl", task)
    return task


def enterprise_source_query(case_id: str, source_id: str, cutoff_date: str) -> dict:
    """Simulate one investigator-approved read-only enterprise query."""
    overview = enterprise_overview(case_id, cutoff_date)
    source = next((item for item in overview["sources"] if item["id"] == source_id), None)
    if source is None:
        raise ValueError(f"未知企业数据源：{source_id}")
    messages = {
        "complaint_crm": "已汇总投诉并按官方编号去重，形成当前案例信号基线。",
        "warranty_repair": "已匹配维修工单；结果需要结合零件号和维修日期继续核验。",
        "vehicle_config": "已返回车型、批次和零件版本候选关联。",
        "field_incident": "已检索道路事件、救援和故障码；严重度仍需工程确认。",
        "engineering_docs": "已检索工程文档和服务公告，材料来源已进入证据台账。",
        "regulatory_public": "已检索公开调查和召回材料，截点后材料已过滤。",
        "case_workflow": "该连接器只允许审批后写入，不能直接执行只读查询。",
    }
    return {"demo_only": True, "source": source, "message": messages.get(source_id, "查询完成"), "cutoff_date": cutoff_date, "query_id": f"Q-{uuid.uuid4().hex[:8].upper()}"}


PAGE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>车辆缺陷主动调查 Agent</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#202622;background:#f5f7f4;font-synthesis:none;text-rendering:optimizeLegibility}*{box-sizing:border-box}body{margin:0}header{background:#153e35;color:#f4fbf7;padding:20px max(24px,calc((100vw - 1320px)/2));border-bottom:4px solid #d7a449}header h1{font-size:22px;line-height:1.3;margin:0 0 5px}header p{margin:0;color:#c8ddd5;font-size:13px}.wrap{max-width:1320px;margin:0 auto;padding:22px 24px 48px}.notice{padding:12px 15px;margin-bottom:18px;border-left:4px solid #bd7b20;background:#fff5df;color:#523d1a;line-height:1.5;font-size:14px}.toolbar{display:grid;grid-template-columns:1.1fr .7fr 1.4fr .9fr auto auto;gap:12px;align-items:end;padding:0 0 20px;border-bottom:1px solid #d8dfda}.field label{display:block;font-size:12px;font-weight:650;color:#536159;margin-bottom:6px}.field input,.field select,.field textarea{width:100%;border:1px solid #bfcac3;border-radius:4px;background:#fff;padding:9px 10px;font:inherit;color:#202622;min-height:38px}.field textarea{min-height:40px;resize:vertical}.button{height:38px;padding:0 14px;border:1px solid #174c40;border-radius:4px;background:#174c40;color:white;font:inherit;font-weight:600;cursor:pointer;white-space:nowrap}.button.secondary{background:white;color:#174c40}.button:disabled{opacity:.55;cursor:wait}.section{padding:22px 0;border-bottom:1px solid #d8dfda}.section h2{font-size:17px;margin:0 0 14px}.metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;background:#d8dfda;border:1px solid #d8dfda}.metric{background:#fff;padding:13px 15px;min-height:75px}.metric span{display:block;color:#637068;font-size:12px;margin-bottom:6px}.metric strong{font-size:17px;font-variant-numeric:tabular-nums}.tabs{display:flex;gap:4px;margin:18px 0 0;border-bottom:1px solid #bac6be;overflow:auto}.tab{border:0;background:transparent;padding:10px 13px;color:#526058;font:inherit;cursor:pointer;border-bottom:3px solid transparent;white-space:nowrap}.tab.active{color:#16493d;border-color:#16493d;font-weight:650}.pane{display:none;padding:16px 0}.pane.active{display:block}.row{padding:11px 0;border-bottom:1px solid #e2e8e3}.row strong{font-size:14px}.muted{font-size:12px;color:#647168;margin-top:5px;line-height:1.5}.pill{display:inline-block;margin-left:8px;border-radius:3px;padding:3px 7px;background:#e4efe9;color:#245a4b;font-size:11px}.pill.warn{background:#fff0d4;color:#805016}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #dfe5e0;padding:9px 8px;overflow-wrap:anywhere}th{font-size:12px;color:#59665e;font-weight:650}.feedback{margin:10px 0;padding:14px 0;border-bottom:1px solid #dfe5e0}.feedback textarea{display:block;width:min(700px,100%);height:72px;margin:9px 0;border:1px solid #bdc8c1;border-radius:4px;padding:9px;font:inherit}.report{white-space:pre-wrap;line-height:1.6;background:white;border-left:3px solid #d7a449;padding:16px;max-height:600px;overflow:auto;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}.status{margin-left:10px;color:#426151;font-size:13px}.empty{padding:20px 0;color:#68756d;font-size:14px}.error{color:#a1382b;padding:10px 0}.footer{padding-top:20px;color:#657169;font-size:12px}@media(max-width:1000px){.toolbar{grid-template-columns:repeat(2,minmax(0,1fr))}.toolbar .wide{grid-column:1/-1}.metrics{grid-template-columns:repeat(3,1fr)}}@media(max-width:600px){header{padding:17px 18px}.wrap{padding:16px 18px 36px}.toolbar{grid-template-columns:1fr}.toolbar .wide{grid-column:auto}.metrics{grid-template-columns:repeat(2,1fr)}.button{width:100%}}
</style>
</head>
<body>
<header><h1>车辆缺陷主动调查 Agent</h1><p>公开资料历史回放原型 · 调查辅助，不自动判定车辆存在安全缺陷</p></header>
<main class="wrap">
<div id="caseNotice" class="notice">正在读取案例状态…</div>
<section class="toolbar" aria-label="调查设置">
<div class="field"><label for="case">调查案例</label><select id="case"></select></div>
<div class="field"><label for="cutoff">资料截点</label><input id="cutoff" type="date"></div>
<div class="field wide"><label for="goal">调查目标</label><input id="goal" value="核查转向异常投诉的共同线索，寻找反证并提出下一步补查建议。"></div>
<div class="field"><label for="focus">调查重点</label><select id="focus"><option value="general">综合核查</option><option value="trend">投诉趋势</option><option value="links">跨车型关联</option><option value="counterevidence">寻找反证</option><option value="evidence">证据检索</option><option value="followup">生成补查任务</option><option value="report">调查摘要</option></select></div>
<div class="field"><label for="mode">运行模式</label><select id="mode"><option value="offline">离线演示</option><option value="api">模型 API</option></select></div>
<button id="run" class="button">开始调查</button><button id="eval" class="button secondary">运行 12 项评测</button>
</section>
<div id="status" class="status" role="status" aria-live="polite"></div>
<section id="evaluation" class="section" hidden><h2>最近评测</h2><div id="evalMetrics" class="metrics"></div><div id="evalRows" style="overflow:auto;margin-top:14px"></div><p id="evalNote" class="muted"></p></section>
<section id="investigation" class="section" hidden><h2>调查结果</h2><div id="metrics" class="metrics"></div>
<nav class="tabs" aria-label="调查结果视图"><button class="tab active" data-pane="process">调查过程</button><button class="tab" data-pane="evidence">证据登记</button><button class="tab" data-pane="followups">补查与反馈</button><button class="tab" data-pane="report">报告</button><button class="tab" data-pane="trace">运行轨迹</button></nav>
<div id="process" class="pane active"></div><div id="evidence" class="pane"></div><div id="followups" class="pane"></div><div id="report" class="pane"></div><div id="trace" class="pane"></div></section>
<div class="footer">工具只访问本地快照，待补查任务仅记录在本地。投诉数量不代表故障发生率；离线模式只验证工程闭环。当前合成演示数据不可用于真实缺陷判断。</div>
</main>
<script>
const $=id=>document.getElementById(id);let currentState=null;let cases=[];
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
async function api(url,body){const response=await fetch(url,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{});const data=await response.json();if(!response.ok)throw new Error(data.error||"请求失败");return data}
function setStatus(text,error=false){$("status").textContent=text;$("status").className=error?"status error":"status"}
async function init(){try{cases=await api("/api/cases");$("case").innerHTML=cases.map(c=>`<option value="${esc(c.case_id)}">${esc(c.title||c.case_id)}</option>`).join("");syncCase();$("case").addEventListener("change",syncCase);$("caseNotice").textContent=noticeFor(cases[0]);}catch(e){$("caseNotice").textContent=e.message;}}
function noticeFor(c){return c.data_status==="synthetic_demo_fixture"?c.fixture_notice:`数据状态：${c.data_status||"未标注"}。请在报告中核对本地快照来源与发布日期。`}
function syncCase(){const c=cases.find(x=>x.case_id===$("case").value);if(c){$("cutoff").value=c.cutoff_date||"2023-11-28";$("caseNotice").textContent=noticeFor(c)}}
function metric(label,value){return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`}
function renderState(s){currentState=s;$("investigation").hidden=false;$("metrics").innerHTML=[metric("状态",s.status),metric("调查轮次",s.steps),metric("工具调用",s.usage.tool_calls),metric("登记证据",s.evidence_ledger.length),metric("待补查",s.followups.filter(x=>x.status==="pending_human_review").length)].join("");
$("process").innerHTML=s.tool_events.length?s.tool_events.map(e=>`<div class="row"><strong>第 ${e.step} 轮 · ${esc(e.tool)}</strong><span class="pill ${e.ok?"":"warn"}">${e.ok?"完成":"失败"}</span><div class="muted">${esc(e.error||JSON.stringify(e.data||{}))}</div></div>`).join(""):`<div class="empty">本轮没有工具调用。</div>`;
$("evidence").innerHTML=s.evidence_ledger.length?`<div style="overflow:auto"><table><thead><tr><th>证据 ID</th><th>材料</th><th>发布日期</th><th>来源</th><th>状态</th></tr></thead><tbody>${s.evidence_ledger.map(e=>`<tr><td>${esc(e.evidence_id)}</td><td>${esc(e.title)}</td><td>${esc(e.published_date)}</td><td>${esc(e.source_url||e.citation_locator||"未提供")}</td><td>${esc(e.review_status)}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty">没有检索到截点内证据。</div>`;
$("followups").innerHTML=s.followups.length?s.followups.map(f=>`<div class="feedback"><strong>${esc(f.followup_id)} · ${esc(f.status)}</strong><p>${esc(f.question)}</p><div class="muted">${esc(f.rationale||"")}</div>${f.answer?`<p>人工反馈：${esc(f.answer)}</p>`:`<label for="fb-${esc(f.followup_id)}">模拟补查结果</label><textarea id="fb-${esc(f.followup_id)}"></textarea><button class="button" onclick="submitFeedback('${esc(f.followup_id)}')">记录反馈并继续调查</button>`}</div>`).join(""):`<div class="empty">本轮没有生成待补查任务。</div>`;
$("report").innerHTML=`<pre class="report">${esc(s.report_text||"报告正在准备…")}</pre><button id="download" class="button secondary" style="margin-top:10px">下载 report.md</button>`;
$("download").onclick=()=>{const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([s.report_text],{type:"text/markdown"}));a.download="report.md";a.click();URL.revokeObjectURL(a.href)};
$("trace").innerHTML=`<pre class="report">${esc(JSON.stringify(s,null,2))}</pre>`;
}
async function run(){const btn=$("run");btn.disabled=true;setStatus("调查运行中…");try{const s=await api("/api/run",{case_id:$("case").value,cutoff_date:$("cutoff").value,goal:$("goal").value,focus:$("focus").value,mode:$("mode").value});renderState(s);setStatus(`完成 · ${s.investigation_id}`)}catch(e){setStatus(e.message,true)}finally{btn.disabled=false}}
async function submitFeedback(id){try{const answer=$(`fb-${id}`).value;setStatus("保存反馈并继续调查…");const s=await api("/api/feedback",{investigation_id:currentState.investigation_id,followup_id:id,answer});renderState(s);setStatus("反馈已保存，调查已继续运行。")}catch(e){setStatus(e.message,true)}}
async function runEval(){const btn=$("eval");btn.disabled=true;setStatus("评测运行中…");try{const r=await api("/api/evaluate",{mode:$("mode").value});$("evaluation").hidden=false;$("evalMetrics").innerHTML=[metric("用例",r.task_count),metric("已运行",r.executed_count),metric("通过",r.passed_count),metric("数据阻塞",r.blocked_count),metric("失败",r.failed_count)].join("");$("evalRows").innerHTML=`<table><thead><tr><th>用例</th><th>类型</th><th>状态</th><th>结果</th><th>说明</th></tr></thead><tbody>${r.rows.map(x=>`<tr><td>${esc(x.task_id)}</td><td>${esc(x.kind)}</td><td>${esc(x.status)}</td><td>${x.passed?"通过":"未通过/未运行"}</td><td>${esc(x.detail||"")}</td></tr>`).join("")}</tbody></table>`;$("evalNote").textContent=r.interpretation;setStatus(`评测完成 · ${r.passed_count} 项通过，${r.blocked_count} 项等待真实案例数据`)}catch(e){setStatus(e.message,true)}finally{btn.disabled=false}}
$("run").addEventListener("click",run);$("eval").addEventListener("click",runEval);document.querySelectorAll(".tab").forEach(btn=>btn.addEventListener("click",()=>{document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));document.querySelectorAll(".pane").forEach(x=>x.classList.remove("active"));btn.classList.add("active");$(btn.dataset.pane).classList.add("active")}));init();
</script>
</body></html>'''

# The investigator-facing page lives separately so it can be edited and
# reviewed as ordinary HTML/CSS/JS without touching the legacy report view.
ENTERPRISE_PAGE = Path(__file__).with_name("enterprise_demo.html").read_text(encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "VehicleAgent/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: object) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("请求内容过大")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        return value

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(200, ENTERPRISE_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/cases":
            self._json(200, DataStore().cases())
            return
        if parsed.path == "/api/state":
            params = parse_qs(parsed.query)
            try:
                self._json(200, load_state(params.get("id", [""])[0]))
            except Exception as exc:
                self._json(404, {"error": str(exc)})
            return
        if parsed.path == "/api/latest-evaluation":
            files = sorted((OUTPUT_DIR / "evaluations").glob("eval-*.json"), reverse=True)
            if not files:
                self._json(404, {"error": "尚无评测结果"})
                return
            self._json(200, json.loads(files[0].read_text(encoding="utf-8")))
            return
        self._json(404, {"error": "未找到页面"})

    def do_POST(self) -> None:
        try:
            body = self._body()
            if self.path == "/api/enterprise/overview":
                self._json(200, enterprise_overview(str(body.get("case_id", "")), str(body.get("cutoff_date", ""))))
                return
            if self.path == "/api/enterprise/approve":
                self._json(200, enterprise_action(body))
                return
            if self.path == "/api/enterprise/source":
                self._json(200, enterprise_source_query(str(body.get("case_id", "")), str(body.get("source_id", "")), str(body.get("cutoff_date", ""))))
                return
            if self.path == "/api/run":
                state = run_investigation(str(body.get("case_id", "")), str(body.get("goal", "")), str(body.get("cutoff_date", "")), str(body.get("mode", "offline")), str(body.get("focus", "general")))
                case = DataStore().case(state["case_id"]) or {}
                report_path = Path(state["report_path"])
                state["report_text"] = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
                state["fixture_notice"] = case.get("fixture_notice", "")
                self._json(200, state)
                return
            if self.path == "/api/feedback":
                updated = add_human_feedback(str(body.get("investigation_id", "")), str(body.get("followup_id", "")), str(body.get("answer", "")))
                state = run_investigation(updated["case_id"], updated["goal"], updated["cutoff_date"], updated["mode"], updated["focus"], updated)
                report_path = Path(state["report_path"])
                state["report_text"] = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
                state["fixture_notice"] = state.get("fixture_notice", "")
                self._json(200, state)
                return
            if self.path == "/api/evaluate":
                self._json(200, evaluate(str(body.get("mode", "offline"))))
                return
            self._json(404, {"error": "未知接口"})
        except Exception as exc:
            self._json(400, {"error": str(exc)})


def main() -> None:
    try:
        server = ReusableThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        if getattr(exc, "errno", None) == 48:
            raise SystemExit(
                f"端口 {PORT} 已被占用。请直接打开 http://127.0.0.1:{PORT}，"
                f"或先停止旧服务后再启动：lsof -tiTCP:{PORT} | xargs kill"
            ) from exc
        raise
    print(f"Vehicle investigation agent is running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
