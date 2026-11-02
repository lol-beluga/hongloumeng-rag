"""CLI entry point; imports never trigger paid model calls."""
import argparse
import json
from pathlib import Path

from agent_harness import AgentConfig, ResearchAgent, public_result
from rag_system import PROJECT_DIR, RagSystem, load_api_key
from run_store import RunStore


def main():
    parser = argparse.ArgumentParser(description="红楼梦原文考证 Agent")
    commands = parser.add_subparsers(dest="command", required=True)
    ask = commands.add_parser("ask", help="新建考证任务")
    ask.add_argument("question")
    ask.add_argument("--max-tools", type=int, default=8)
    resume = commands.add_parser("resume", help="从 SQLite 检查点恢复")
    resume.add_argument("run_id")
    resume.add_argument("--extend-budget", action="store_true", help="明确增加一轮预算")
    commands.add_parser("list", help="列出最近任务，不调用模型")
    show = commands.add_parser("show", help="查看/导出任务，不调用模型")
    show.add_argument("run_id")
    show.add_argument("--out", type=Path)
    args = parser.parse_args()
    store = RunStore(PROJECT_DIR / "runs" / "research.sqlite3")
    if args.command == "list":
        for state in store.recent():
            print(state["run_id"], state["status"], state["question"][:60])
        return
    if args.command == "show":
        payload = json.dumps(public_result(store.load(args.run_id)), ensure_ascii=False, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(payload, encoding="utf-8")
        else:
            print(payload)
        return
    rag = RagSystem(load_api_key())
    rag.initialize()
    config = AgentConfig(max_tool_calls=getattr(args, "max_tools", 8))
    agent = ResearchAgent(rag, store, config)
    state = agent.start(args.question) if args.command == "ask" else agent.resume(
        args.run_id, extend_budget=args.extend_budget)
    print(state["answer"] or "任务进度已保存：" + state["stop_reason"])
    print("任务编号：", state["run_id"])
    print("状态：", state["status"], "工具调用：", state["tool_calls"], "已报告Token：", state["total_tokens"])


if __name__ == "__main__":
    main()
