# 在线 Demo 部署路线

## 推荐方案

将仓库部署到 Streamlit Community Cloud 或 Hugging Face Spaces，入口为 `app.py`。Demo 默认使用仓库中的精简公开案例包和离线策略；Qwen API 只通过平台 Secrets 配置，不写入代码，也不把实验室服务器地址暴露给访问者。

部署配置：

- Python 3.11+
- `pip install -r requirements.txt`
- 启动：`streamlit run app.py --server.address=0.0.0.0 --server.port=8501`
- API Secrets：`MODEL_BASE_URL`、`MODEL_NAME`、`MODEL_API_KEY`
- 没有 API 或 API 超时时，页面仍可切换离线演示；在没有 `data/imported/` 的云端 checkout 中，程序会自动使用提交的 `data/public_demo/`。

## 本地生成公开 Demo 数据包

`data/imported/` 包含完整原始快照，默认不提交。部署前可以运行：

```bash
python scripts/build_public_demo.py
AGENT_DATA_DIR=data/public_demo streamlit run app.py --server.address=0.0.0.0 --server.port=8501
```

脚本只保留三个案例在各自公开截点前的记录和材料，排除 EA23003 结案留出文件，不包含 API 密钥或企业内部数据。云平台可将 `AGENT_DATA_DIR` 配置为 `data/public_demo`；页面支持离线规则和主动信息增益两种无需外部服务的演示模式。

## 展示流程

1. 选择 EA23003，设置 2023-11-28 截点；
2. 输入“核查转向投诉趋势、寻找替代解释并提出下一步补查”；
3. 展示计划、工具调用、证据台账和来源；
4. 打开反证任务，查看待确认状态；
5. 录入模拟维修反馈，展示状态续跑；
6. 下载报告和运行轨迹；
7. 打开冻结评测结果，比较固定流程、RAG 和主动策略。

## 车企接入路线

当前 Demo 只读本地公开快照，不调用企业接口。车企试点需要在企业内网部署同一容器，增加 SSO/RBAC、数据脱敏、审计日志、人工审批和只读/写入工具分级；企业接口只允许由审批后的工具执行。展示时用“可迁移接口层”说明未来接入方式，不声称已经接入车企。
