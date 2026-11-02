# 车辆缺陷主动调查决策 Agent

面向《设计大数据基础》课程作业的公开资料历史回放原型。系统协助质量调查人员组织线索、检索证据、保留反证和生成待人工补查任务。

## 数据状态

当前仓库附带的 EA23003 记录是**合成演示夹具**，只用于验证程序闭环，不是 NHTSA 投诉或调查原始数据。夹具行均有 `is_demo_fixture: true`。选题材料摘要对应的后续调查结论单独保存在 `data/gold/ea23003.json`；运行期检索器不会读取该留出文件，也会排除标为 `holdout_only` 的材料。

请先从 NHTSA 官方数据/API 与公开调查文件获取原始快照，再整理成 `cases.json`、`records.json`、`evidence.json` 三个 UTF-8 JSON 数组，运行 `python pipeline.py import-data <目录>` 导入。导入前应保留原始 ID、来源 URL、发布日期/接收日期和保存日期；去重结果不能覆盖原始记录。`data/imported/` 不纳入版本控制，便于保存用户取得的真实快照。

在可访问 NHTSA 的网络环境中，可直接运行 `python scripts/fetch_nhtsa.py` 自动取得 Honda Civic、Honda CR-V 和 Acura Integra 的公开投诉 API 快照。脚本先访问 NHTSA vPIC 官方车型目录 `GetModelsForMakeYear`，确认年份和品牌下存在基础车型；对于用户输入的 2023 Honda Civic，再展开为 `CIVIC SEDAN`、`CIVIC HATCHBACK`、`CIVIC SEDAN SI` 和 `CIVIC HATCHBACK TYPE R`，分别请求 Complaints API。每个请求的 URL、HTTP 状态、原始 JSON、采集时间和 SHA-256 都写入 `data/imported/raw/api/` 与 `manifest.json`。

投诉 API 的 `HTTP 400 + count=0 + 成功消息` 会标记为 `EMPTY_RESPONSE_UNVERIFIED`，不能当作零投诉。脚本使用官方投诉编号去重并保留 `source_models`；只有四个 Civic 子车型都成功或完成独立核验时，`cases.json` 才会将 Civic 系列统计标记为 `complete`。原始 API 行仍保存在 `raw_nhtsa`，并另写入 `manifest.json`、来源 URL、抓取时间和保存时间。脚本不把 2025 年结案文件放进截点内运行证据。抓取后执行 `python pipeline.py import-data data/imported` 完成导入。

数据导入后运行 `python scripts/prepare_dataset.py` 完成第二阶段处理。该命令在 `data/processed/` 生成 `records_normalized.json`、`data_quality_report.json`、`duplicate_candidates.json`、`evidence_index.json` 和 `migration_cases.json`。Agent 查询会优先读取规范化记录；原始 `data/imported/records.json` 和 API 响应保持不变。

运行 `python scripts/expand_research_cases.py --refresh --limit 8` 会顺序核验 51 个 ODI 结案候选对应的 35 个车型年款组合，建立资格矩阵并生成独立扩展包。当前新增 8 个跨部件 ODI 迁移案例，另保留原有 Ford Explorer 和 Tesla Model 3 召回案例。扩展包保存投诉原始 JSON、ODI FLAT_INV 结案摘要、来源 URL、公开日期、保存时间和 SHA-256；质量结果见 `data/expanded/quality_report.json`。运行 `python scripts/import_expanded_cases.py && python scripts/prepare_dataset.py` 合并到本地导入库。

质量报告将日期、缺失字段、官方投诉编号重复、组件拆分和来源完整性分开统计。完全归一化文本只形成重复候选组并保留全部记录。扩展迁移案例还单独保存每案 2–3 个截点和 `data/expanded/holdout_records.json`，把截点后的投诉隔离为评测答案。快速流程仍按原规则选择最多两个迁移案例；研究级评测使用全部扩展案例。

第三阶段已接入评测：固定流程基线执行筛选、趋势、证据和实体关联；普通 RAG 基线只执行一次证据检索；主动调查 Agent 按目标动态决定工具调用。`python pipeline.py eval --mode offline` 会在同一案例、同一截点和同一数据快照上运行三种方案，并写入每个任务的调用次数、证据覆盖、状态和人工质量评分待办。当前评测结果见 `outputs/evaluations/`；迁移案例也纳入基线比较。

评测严格区分历史回放截点和验证材料：EA23003 仍以 2023-11-28 回放，2025 年公开结案文件保持 holdout，不进入检索；迁移案例使用各自公开处置材料的发布日期作为回放边界。主案索引了截至截点的 528 条 NHTSA `STEERING` 投诉，并以证据文档保存其来源投诉编号；这些是投诉线索，不是 ODI 调查结论。评测分别统计证据文档数和其关联的去重投诉编号数。固定流程、RAG 和离线 Agent 当前命中相同索引属于共同数据与词法检索策略的结果，不能证明质量等价；三者建议质量仍需按 0–2 分人工评审。迁移案例可用于验证工具契约和流程，不代表完整 ODI 结案调查质量。

### 导入格式

`cases.json` 至少包含：

```json
[{"case_id":"EA23003","title":"...","component":"steering","cutoff_date":"2023-11-28","data_status":"public_snapshot","fixture_notice":""}]
```

`records.json` 每行至少包含 `record_id`、`case_id`、`record_type`、`received_date`、`text`、`source_id`。推荐字段还包括 `make`、`model`、`model_year`、`component`、`occurred_date`、`source_url`、`source_publication_date` 和 `duplicate_group`。

`evidence.json` 每行至少包含 `evidence_id`、`case_id`、`title`、`content`、`published_date`、`source_kind`、`source_url`、`citation_locator`。调查截点之后的结案材料只能进入单独评测参考，不可放进运行证据包。

导入器会检查文件形状和案例外键，并将与导入案例同 ID 的演示行替换。所有检索工具还会强制使用本次任务截点，不接受模型通过参数放宽截点。

## 运行

Python 3.10 或更新版本。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### 无模型 API 的演示路径

没有 Qwen API 时，使用公开 Demo 快照和离线策略即可完成展示，不会访问实验室服务器：

```bash
AGENT_DATA_DIR=data/public_demo python webapp.py
```

浏览器打开 <http://127.0.0.1:8765>，建议按以下顺序演示：选择 EA23003 → 保留默认截点 → 调查重点选择“寻找反证”或“生成补查任务” → 开始调查 → 查看调查过程、证据登记、补查与报告 → 录入模拟反馈并继续调查。页面中的“运行12项评测”用于离线工程回归，不代表真实模型质量。

如果已经安装 Streamlit，也可以运行：

```bash
AGENT_DATA_DIR=data/public_demo streamlit run app.py
```

Streamlit 页面支持离线规则、主动信息增益和模型 API 三种模式；没有 API 时不要选择“模型 API”，使用“离线规则”或“主动信息增益”。

### 使用 DeepSeek API

Demo 推荐使用 DeepSeek 的 OpenAI-compatible API。先在 DeepSeek 控制台创建 API Key，然后只在本机终端设置环境变量：

```bash
export MODEL_API_KEY="你的DeepSeek_API_Key"
export MODEL_BASE_URL="https://api.deepseek.com"
export MODEL_NAME="deepseek-chat"
export MODEL_MAX_TOKENS=512
export MODEL_REQUEST_TIMEOUT=120
AGENT_DATA_DIR=data/public_demo WEBAPP_HOST=0.0.0.0 python webapp.py
```

浏览器打开 `http://127.0.0.1:8765`，调查模式选择“模型 API”。API Key 不要写入仓库、截图或提交到 `.env` 文件；如果 API 不可用，选择“离线 Agent 演示”仍可完成完整流程。

也可以使用持久化的本地配置：复制 `.env.local.example` 为 `.env.local`，填入自己的 DeepSeek Key 后直接运行 `python webapp.py`。网页启动时会自动读取该文件；`.env.local` 已加入 Git 忽略列表。

如果当前环境不能安装 Streamlit，标准库网页后备入口无需额外依赖：

```bash
python webapp.py
```

它只绑定 `127.0.0.1:8765`，提供同样的案例选择、调查、冻结评测、证据查看、补查反馈和报告下载。

命令行调查与评测不需要 Streamlit：

```bash
python pipeline.py list-cases
python pipeline.py run --case-id EA23003 --mode offline --focus followup
python pipeline.py eval --mode offline
# 生成研究级 72 条任务并运行主动信息增益策略
python scripts/build_research_benchmark.py
python pipeline.py eval --suite research --mode active_eig
# 选择 24 条最新截点任务供 Qwen API 代表性实验使用（并发由外部执行器保持为 1）
python pipeline.py eval --suite research_api --mode api
```

有兼容 Chat Completions API 时复制 `.env.example` 中变量到 shell 环境，再以 `--mode api` 运行；不要把 API 密钥提交到仓库。API 模式也只允许调用本地五个工具，不提供对外发送或企业系统写入能力。失败调用最多重试两次，整轮最多八步。

## 架构

- `app.py`：Streamlit 交互页面，查看计划、工具轨迹、证据、待补查任务和报告。
- `agent/core.py`：数据存取、截点强制、工具箱、ReAct/主动信息增益/模型策略、任务状态和续跑。
- `agent/evidence_graph.py`：截点安全的投诉—证据关系图和可解释候选动作 utility 计算。
- `agent/evaluation.py`：冻结实验矩阵、固定流程/普通 RAG/ReAct/主动 Agent 对比、自动行为评分、bootstrap 区间和 JSON/CSV/Markdown 结果。
- `agent/report.py`：可追溯调查报告。
- `data/demo/`：明确标记的演示夹具；`data/gold/`：留出评测参考；`data/imported/`：本地真实快照。
- `outputs/states/`、`outputs/logs/run_log.jsonl`、`outputs/reports/`、`outputs/evaluations/`：运行产物，默认不提交。

## 测试

运行 `python -m unittest discover -s tests -v`。测试覆盖截点后数据过滤、留出答案隔离、参数截点覆盖防护、空结果、无效日期、未知工具失败关闭、导入外键校验，以及人工反馈后继续运行。

## 评测解释

第四阶段新增：工具动作参数校验、逐步确定性验证、失败后恢复任务（最多两次重规划）、相同已验证动作无新信息时停止、累计最多八轮、续跑锁定案例和截点、按案例加载并去重写入失败记忆。证据立场受控为 `support/oppose/neutral/needs_review`，无依据的立场降为待确认；竞争性解释保持未证实状态。报告只展示通过验证的工具观察，不采用模型自由文本作为缺陷事实。离线策略仍是规则策略，不能视为真实 LLM 调查增益验证。

本轮官方调查全量快照保存于 `data/imported/raw/investigations/`，51 个结案调查候选见 `data/processed/odi_case_candidates.json`。研究扩展资格矩阵见 `data/expanded/qualification_matrix.json`，逐案质量报告见 `data/expanded/quality_report.json`，截点后 holdout 见 `data/expanded/holdout_records.json`。数据充分性与替代案例评估见 [阶段四与主案评估](docs/stage4-and-case-assessment.md)。EA23003 仍是主案；迁移案例用于跨部件泛化，不代表完整 ODI 结案调查质量。

自动化实验矩阵和预注册评分见 [主动调查 Agent 自动化实验方案](docs/autonomous-experiment-plan.md)。当前冻结任务扩展为 24 条，评分只依赖工具轨迹、来源和边界检查，不依赖人工语义评分；人工复核仍可作为附加分析，不再是自动验收前提。

当前冻结矩阵包含 24 条快速回归任务（12 条主案变体、2 条迁移任务和 10 条异常/边界/反馈任务）。运行 `scripts/build_research_benchmark.py` 会从 11 个公开案例按案例×8 个调查目标×3 个历史截点生成 264 条研究任务；每次运行保持相同案例、截点和工具预算，并比较固定流程、普通 RAG、ReAct 和主动信息增益 Agent。迁移案例必须从本地导入的真实公开快照中筛选：存在公开结案材料和投诉记录，且主要部件不同；没有合格数据时用例明确标记为 `blocked_data_missing`，不会生成假案例。

报告指标区分程序可自动检查的执行状态与必须人工判断的建议质量（0–2 分）。离线策略只能证明状态、工具、日志和评测流程可运行，不能证明 LLM 的调查能力或车企运营效率提升。所有结论必须在导入真实资料并完成人工复核后再作解释。

## 课程交付与版本分支

本项目按四个迭代版本组织：

- `v1-baseline`：最小调查闭环，包含工具调用、计划、状态、日志和报告。
- `v2-data-contracts`：修复 NHTSA 车型映射、工具参数、来源字段、截点过滤和数据导入契约。
- `v3-dynamic-policy`：加入竞争性假设、反证优先、信息增益动作和反馈后续跑。
- `v4-final-demo`：统一四种方案对照，加入验证器、安全停止、企业调查员 Demo、文档和展示材料。
- `main`：最终可提交版本。

最终材料：

- `docs/project-report.pdf` / `docs/project-report.docx`：项目说明文档。
- `output/vehicle-defect-agent.pptx`：12 页展示稿。
- `webapp.py`：本地 Demo，默认访问 `http://127.0.0.1:8765`。

快速启动：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python webapp.py
```

DeepSeek API 只在本机 `.env.local` 中配置，密钥不会进入 Git。没有 API 时选择离线 Agent 模式即可完成 Demo。
