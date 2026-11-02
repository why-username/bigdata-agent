# 研究级数据包就绪度

更新时间：2026-11-01

| 要求 | 当前状态 | 证据 | 结论 |
| --- | --- | --- | --- |
| NHTSA FLAT_INV 结案候选 | 已完成 | `data/processed/odi_case_candidates.json` | 51 个有结案日期候选已解析并保留来源、保存时间和 SHA-256。 |
| 至少 8 个高质量迁移案例 | 已完成首轮目标 | `data/expanded/quality_report.json` | 新增 8 个跨部件案例，均有结案摘要、截点前投诉记录和明确部件族；原有 2 个迁移案仍保留。 |
| 每案 2–3 个历史截点 | 已完成 | `data/eval/research_tasks.json` | 当前 11 个公开案例各有 3 个截点，共 264 条研究任务。 |
| 原始投诉、调查/召回文件和来源快照 | 已完成首轮目标 | `data/expanded/raw_complaints/`、`data/imported/raw/` | 8 个扩展案例保存投诉原始响应；ODI 结案材料来自 FLAT_INV 快照，保留调查编号和定位信息。 |
| 日期、来源、SHA-256、质量报告 | 已完成首轮目标 | `data/expanded/quality_report.json`、`data/expanded/qualification_matrix.json` | 8/8 扩展案例通过日期、来源、部件、投诉和证据检查，并保存 API SHA-256。 |
| 规则生成异常样本 | 已完成 | `data/eval/anomalies.json`、`data/eval/tasks.json` | 已形成 6 类独立异常样本，并保留原有边界评测。 |
| 替代主案资格审查 | 主案维持 EA23003 | `docs/stage4-and-case-assessment.md` | 扩展案例满足迁移回放条件；EA23003 仍因调查链、主案例材料和选题一致性保留为主案。 |

因此，研究级数据扩展首轮目标已完成：当前有主案、10 个迁移案例、264 条研究任务，以及独立异常和截点后 holdout。扩展案例仍属于公开资料精简回放包，不能解释为完整车企质量数据库。

下一步按以下顺序执行：

1. 对 264 条任务运行 API 代表子集，比较离线规则策略与 Qwen 的真实工具选择；
2. 按案例和部件族分析主动策略的证据覆盖、反证动作和引用可核验率；
3. 将扩展数据包、质量报告、holdout 和评测结果纳入最终说明文档与展示 PPT。
