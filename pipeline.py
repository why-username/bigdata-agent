from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.core import DATA_DIR, DataStore, load_state, run_investigation
from agent.evaluation import evaluate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="车辆缺陷主动调查决策 Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="运行一轮调查")
    run.add_argument("--case-id", default="EA23003")
    run.add_argument("--goal", default="核查转向异常投诉的共同线索，寻找反证并提出下一步补查建议。")
    run.add_argument("--cutoff", default=None)
    run.add_argument("--mode", choices=("offline", "active_eig", "api"), default="offline")
    run.add_argument("--focus", choices=("general", "trend", "links", "counterevidence", "evidence", "followup", "report"), default="general")
    run.add_argument("--resume", default=None, help="从调查编号加载已保存状态并继续")
    ev = sub.add_parser("eval", help="运行冻结评测套件")
    ev.add_argument("--mode", choices=("offline", "active_eig", "api"), default="offline")
    ev.add_argument("--suite", choices=("fast", "research", "research_api_pilot", "research_api"), default="fast", help="fast 为回归套件，research 为扩展离线基准，research_api_pilot 为每案两条 API 试验，research_api 为全部最新截点任务")
    imp = sub.add_parser("import-data", help="导入符合 README 结构的本地案例 JSON")
    imp.add_argument("directory", type=Path)
    sub.add_parser("list-cases", help="列出可用案例与数据状态")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            resume = load_state(args.resume) if args.resume else None
            state = run_investigation(args.case_id, args.goal, args.cutoff, args.mode, args.focus, resume)
            print(json.dumps({"investigation_id": state["investigation_id"], "status": state["status"], "tool_calls": state["usage"]["tool_calls"], "report_path": state["report_path"], "state_path": str(DATA_DIR.parent / "outputs" / "states" / f"{state['investigation_id']}.json")}, ensure_ascii=False, indent=2))
            return 0 if state["status"] == "completed" else 1
        if args.command == "eval":
            summary = evaluate(args.mode, args.suite)
            print(json.dumps({key: summary[key] for key in ("mode", "task_count", "executed_count", "passed_count", "blocked_count", "failed_count", "json_path", "csv_path", "markdown_path")}, ensure_ascii=False, indent=2))
            return 0 if summary["failed_count"] == 0 else 1
        if args.command == "import-data":
            result = DataStore().import_directory(args.directory)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "list-cases":
            print(json.dumps([{key: case.get(key) for key in ("case_id", "title", "component", "cutoff_date", "data_status", "fixture_notice")} for case in DataStore().cases()], ensure_ascii=False, indent=2))
            return 0
    except Exception as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
