# 扩展数据 Qwen API 试验报告

当前阶段：阶段 5，扩展数据上的模型 API 试验。

本轮使用本地端口转发访问实验室服务器的 OpenAI 兼容接口，模型为 `/model`，并发保持为 1。任务来自扩展后的 11 个公开案例，每案取最新历史截点，选择趋势和反证两个目标，共 22 条任务。

```bash
MODEL_API_KEY=local \
MODEL_BASE_URL=http://127.0.0.1:30000/v1 \
MODEL_NAME=/model \
python pipeline.py eval --suite research_api_pilot --mode api
```

结果文件：[eval-research_api_pilot-20261101-005106.json](/Users/davinci/Documents/ChatGPT/设计大数据基础agent构建/outputs/evaluations/eval-research_api_pilot-20261101-005106.json)。22/22 任务通过自动验收，其中 20 条正常完成，2 条进入 `needs_human_review`。两条人工复核任务都发生在 Ford Explorer 2020 和 Tesla Model 3 2021 的迁移案例上，原因是模型在 `analyze_trend` 中生成了 `modelYear`/`year` 字段别名，最初工具契约未归一化；这不是截点泄漏或数据缺失。

修复后，工具层会归一化 `case_id`、`cutoff_date`、`date_from`、`date_to`、`modelYear` 和 `year`，并新增回归测试。两个失败案例随后单独重跑，均完成并通过。

API 轨迹的平均耗时约 40.4 秒，平均 token 约 26,123，最大单任务 token 95,213。自动行为分数均值为 3.23/5；固定流程和 ReAct 在同一批任务上的均值为 3.50，普通 RAG 为 2.50。这个结果表明真实模型已经能在扩展案例上完成大部分工具调查，但当前提示和预算下主动 Agent 仍有计划执行不完整的情况，不能宣称已经优于基线。模型成本因服务器接口没有返回价格，仍记录为未知。

这次试验是 22 条跨案例 pilot。完整最新截点 API 套件共有 88 条任务，下一步在确认共享服务器可承受的总调用量后再运行，结果会单独保存，不覆盖本轮 pilot。
