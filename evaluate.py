"""Run a fixed, reviewed case list. Never mistake automatic evidence checks for answer accuracy."""
import argparse
import csv
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from agent_harness import AgentConfig, ResearchAgent, public_result
from rag_system import PROJECT_DIR, RagSystem, load_api_key
from run_store import RunStore


def validate_cases(cases, rag):
    seen = set()
    for case in cases:
        if case["id"] in seen or case.get("reviewed") is not True:
            raise ValueError("评测题编号重复或尚未经人工核对。")
        seen.add(case["id"])
        ids, quotes = case["gold_evidence_ids"], case["reference_quotes"]
        if len(ids) != len(quotes):
            raise ValueError("参考片段编号与摘录数量不一致。")
        for evidence_id, quote in zip(ids, quotes):
            if evidence_id not in rag._by_id or quote not in rag._by_id[evidence_id]["content"]:
                raise ValueError(f"参考原文不匹配当前语料：{case['id']}")


def evidence_recall(case, evidence_ids):
    gold = set(case["gold_evidence_ids"])
    return len(gold & set(evidence_ids)) / len(gold) if gold else None


def main():
    parser = argparse.ArgumentParser(description="固定用例评测：普通 RAG 对比原文考证 Agent")
    parser.add_argument("--cases", type=Path, default=PROJECT_DIR / "eval" / "cases.jsonl")
    parser.add_argument("--mode", choices=["baseline", "agent", "both"], default="baseline")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="仅校验参考原文，不请求API")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit 必须大于0")
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8-sig").splitlines() if line.strip()][:args.limit]
    rag = RagSystem()
    rag.initialize()
    validate_cases(cases, rag)
    if args.dry_run:
        print(json.dumps({"validated_cases": len(cases), "corpus_id": rag.corpus_id,
                          "api_calls": 0}, ensure_ascii=False))
        return
    keyed = RagSystem(load_api_key())
    rag.client = keyed.client
    directory = args.out_dir or PROJECT_DIR / "outputs" / datetime.now().strftime("eval-%Y%m%d-%H%M%S")
    directory.mkdir(parents=True, exist_ok=False)
    store = RunStore(directory / "runs.sqlite3")
    config = AgentConfig()
    (directory / "config.json").write_text(json.dumps({
        "model": rag.model, "corpus_id": rag.corpus_id, "cases": cases,
        "agent_config": config.__dict__, "baseline": {"top_k": 10, "similarity_threshold": 0.01},
        "note": "普通问答不使用对话历史；起步集全为开发题，不能用于宣称泛化性能。"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    modes = ["baseline", "agent"] if args.mode == "both" else [args.mode]
    rows = []
    for case in cases:
        for mode in modes:
            started = time.monotonic()
            try:
                if mode == "baseline":
                    result = rag.ask(case["question"])
                    sources = [s["evidence_id"] for s in result["sources"]]
                    tokens = result["usage"].get("total_tokens", 0)
                    status, citation_valid = "completed", None
                else:
                    state = ResearchAgent(rag, store, config).start(case["question"], history=case.get("history"))
                    result = public_result(state)
                    sources, tokens, status = list(state["evidence"]), state["total_tokens"], state["status"]
                    citation_valid = True if status == "completed" and state["report"]["claims"] else None
                row = {"id": case["id"], "mode": mode, "question": case["question"],
                       "reference": case["reference"], "status": status, "result": result,
                       "gold_evidence_recall": evidence_recall(case, sources),
                       "citation_text_valid": citation_valid, "total_tokens": tokens,
                       "seconds": round(time.monotonic() - started, 3),
                       "human_answer_correct": None, "human_evidence_support": None}
            except Exception as exc:
                row = {"id": case["id"], "mode": mode, "status": "error", "error_type": type(exc).__name__,
                       "seconds": round(time.monotonic() - started, 3)}
            rows.append(row)
            with (directory / "predictions.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(case["id"], mode, row["status"], flush=True)
    summary = {}
    for mode in modes:
        group = [r for r in rows if r["mode"] == mode]
        recalls = [r["gold_evidence_recall"] for r in group if r.get("gold_evidence_recall") is not None]
        summary[mode] = {"cases": len(group), "completed": sum(r["status"] == "completed" for r in group),
                         "mean_gold_evidence_recall": statistics.mean(recalls) if recalls else None,
                         "reported_tokens": sum(r.get("total_tokens", 0) for r in group),
                         "seconds": round(sum(r["seconds"] for r in group), 3), "answer_accuracy": None}
    summary["note"] = "原文召回与引用文字校验不是答案准确率；请填写review.csv中的人工判断。"
    (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (directory / "review.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["id", "mode", "question", "reference", "prediction", "answer_correct", "evidence_support", "notes"])
        for row in rows:
            writer.writerow([row["id"], row["mode"], row.get("question", ""), row.get("reference", ""),
                             row.get("result", {}).get("answer", ""), "", "", ""])
    print("评测文件：", directory)


if __name__ == "__main__":
    main()
