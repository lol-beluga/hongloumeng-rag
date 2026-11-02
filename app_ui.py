"""Streamlit UI for the baseline and bounded research agent."""
import copy
import hashlib
import json
import os

import streamlit as st
from openai import OpenAI

from agent_harness import AgentConfig, ResearchAgent, public_result
from rag_system import PROJECT_DIR, RagSystem, load_api_key
from run_store import RunStore

REASONS = {"tool_budget": "工具调用次数已用完", "model_budget": "模型请求次数已用完",
           "token_budget": "Token 用量已达到停止阈值", "time_budget": "执行时间已到",
           "context_budget": "上下文达到长度限制", "api_key_missing": "尚未配置密钥",
           "api_retry_exhausted": "API 超时或限流，重试后仍未成功",
           "api_configuration_error": "API 配置、模型名称或账户状态需要检查"}


def index_revision():
    paths = sorted((PROJECT_DIR / "docs").glob("*.txt")) + [PROJECT_DIR / "中文停用词库.txt"]
    return hashlib.sha256(repr([(p.name, p.stat().st_size, p.stat().st_mtime_ns)
                               for p in paths if p.exists()]).encode()).hexdigest()


@st.cache_resource(show_spinner="正在加载原文索引…")
def load_index(revision):
    rag = RagSystem()
    rag.initialize()
    return rag


def session_runtime(index, api_key, model):
    # Retrieval is shared; credentials and API clients are isolated per browser session.
    signature = (api_key, model, index.corpus_id)
    if st.session_state.get("runtime_signature") != signature:
        old = st.session_state.get("runtime")
        if old and old.client:
            old.client.close()
        rag = copy.copy(index)
        rag.model = model
        rag.client = OpenAI(base_url="https://api.deepseek.com", api_key=api_key,
                            timeout=30, max_retries=0) if api_key else None
        st.session_state.runtime = rag
        st.session_state.runtime_signature = signature
    return st.session_state.runtime


def render_result(result, key):
    if "run_id" not in result:
        st.markdown(result["answer"])
        st.caption("普通问答：一次检索后生成，引用尚未经逐字校验。")
    elif result["status"] == "completed":
        st.markdown(result["answer"])
        st.caption("引用编号和摘录文字已校验；原文是否足以支持结论，仍需阅读核对。")
    else:
        st.warning(REASONS.get(result["stop_reason"], "任务尚未完成") + "。已保存进度，可在侧栏恢复。")
    if "metrics" in result:
        metrics = result["metrics"]
        cols = st.columns(4)
        for col, label, value in zip(cols, ["工具调用", "模型请求", "已报告 Token", "累计用时"],
                                     [metrics["tool_calls"], metrics["model_calls"], metrics["total_tokens"],
                                      f"{metrics['elapsed_seconds']:.1f}s"]):
            col.metric(label, value)
        st.caption(f"任务编号：{result['run_id']}")
        if metrics["usage_unknown_requests"]:
            st.caption("部分请求未返回用量，显示的 Token 可能少于实际计费用量。")
        with st.expander("执行记录与子问题"):
            for question in result["plan"]:
                st.write("• " + question)
            st.json(result["events"])
    if result.get("sources"):
        with st.expander(f"查看原文证据（{len(result['sources'])} 个片段）"):
            for source in result["sources"]:
                st.markdown(f"**{source['source']}** · `{source['evidence_id']}`")
                if "similarity" in source:
                    st.caption(f"检索相似度 {source['similarity']:.3f}（不是答案置信度）")
                st.text(source["content"])
    if "run_id" in result:
        st.download_button("下载任务记录 JSON", json.dumps(result, ensure_ascii=False, indent=2),
                           file_name=f"research-{result['run_id'][:8]}.json",
                           mime="application/json", key=f"export-{key}")
        if result["answer"]:
            st.download_button("下载考证报告 Markdown", result["answer"],
                               file_name=f"report-{result['run_id'][:8]}.md", key=f"report-{key}")


def main():
    st.set_page_config(page_title="红楼梦原文考证助手", page_icon="📚", layout="wide")
    st.markdown("<style>" + (PROJECT_DIR / "assets" / "style.css").read_text(encoding="utf-8")
                + "</style>", unsafe_allow_html=True)
    st.markdown('<h1 class="main-header">📚 红楼梦原文考证助手</h1>', unsafe_allow_html=True)
    st.caption("普通问答用于快速查阅；原文考证支持拆解问题、多步查证和进度恢复。")
    st.session_state.setdefault("chat", [])
    with st.sidebar:
        st.header("⚙️ 系统配置")
        api_key = st.text_input("DeepSeek API 密钥", value=load_api_key(required=False), type="password")
        model = st.text_input("模型名称", value=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))
        mode = st.radio("工作模式", ["原文考证（Agent）", "普通问答"])
        if st.button("重新检查语料与索引"):
            load_index.clear()
        max_tools = st.slider("每轮最多工具调用", 4, 16, 8)
        with st.expander("普通问答检索参数"):
            top_k = st.slider("召回数量", 1, 20, 10)
            threshold = st.slider("相似度阈值", 0.0, 1.0, 0.01, 0.01)
        if st.button("清空当前对话"):
            st.session_state.chat = []
            st.session_state.pop("inspection", None)
            st.rerun()
    try:
        index = load_index(index_revision())
    except Exception as exc:
        st.error(f"原文索引加载失败（{type(exc).__name__}）。请检查 docs 中的 UTF-8 文本。")
        st.stop()
    rag = session_runtime(index, api_key.strip(), model.strip())
    store = RunStore(PROJECT_DIR / "runs" / "research.sqlite3")
    config = AgentConfig(max_tool_calls=max_tools, max_model_calls=max_tools + 2)
    with st.sidebar:
        st.caption(f"原文 {len(index.documents)} 回 · {len(index.doc_chunks)} 个片段")
        st.header("最近的考证任务")
        recent = store.recent(15)
        selected = st.selectbox("选择任务", [s["run_id"] for s in recent],
                                format_func=lambda rid: next(
                                    f"{s['question'][:18]} · {s['status']} · {rid[:6]}"
                                    for s in recent if s["run_id"] == rid)) if recent else None
        view = st.button("查看任务", disabled=not selected)
        extend = st.checkbox("恢复时增加一轮调用与时间预算", value=False)
        resume = st.button("继续所选任务", disabled=not selected or not api_key)
        st.caption("已完成的任务不会重复调用模型。异常退出后执行锁最长约数分钟释放。")
    if view:
        st.session_state.inspection = public_result(store.load(selected))
    if resume:
        with st.status("正在恢复任务…", expanded=True) as progress:
            try:
                state = ResearchAgent(rag, store, config).resume(
                    selected, extend_budget=extend,
                    on_event=lambda event: progress.write(event_text(event)))
                st.session_state.inspection = public_result(state)
                progress.update(label="任务已完成" if state["status"] == "completed" else "进度已保存",
                                state="complete")
            except Exception as exc:
                show_error(exc)
                progress.update(label="恢复未完成", state="error")
    for i, message in enumerate(st.session_state.chat):
        with st.chat_message(message["role"]):
            if "result" in message:
                render_result(message["result"], f"chat-{i}")
            else:
                st.markdown(message["content"])
    if st.session_state.get("inspection"):
        with st.expander("所选任务详情", expanded=True):
            st.write(st.session_state.inspection["question"])
            render_result(st.session_state.inspection, "inspection")
    st.caption("可以问：比较黛玉与宝钗在宝玉挨打后的反应，分别给出原文依据。")
    if not api_key:
        st.info("原文索引已就绪。在侧栏填写密钥后可以开始问答。")
    prompt = st.chat_input("输入问题，也可以继续追问…", disabled=not api_key)
    if prompt:
        history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat[-6:]]
        st.session_state.chat.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        result = None
        with st.status("正在查阅原文…", expanded=True) as progress:
            try:
                if mode == "普通问答":
                    result = rag.ask(prompt, top_k=top_k, similarity_threshold=threshold)
                else:
                    state = ResearchAgent(rag, store, config).start(
                        prompt, history=history, on_event=lambda event: progress.write(event_text(event)))
                    result = public_result(state)
                progress.update(label="本轮完成" if result.get("status", "completed") == "completed"
                                else "已保存进度", state="complete")
            except Exception as exc:
                show_error(exc)
                progress.update(label="本轮未完成", state="error")
        if result:
            text = result["answer"] or "考证尚未完成，任务进度已保存。"
            st.session_state.chat.append({"role": "assistant", "content": text, "result": result})
            st.rerun()


def event_text(event):
    if event["kind"] == "tool":
        names = {"plan_research": "拆解问题", "search_text": "检索原文", "read_passage": "阅读上下文",
                 "list_chapters": "查看目录", "submit_answer": "校验并提交答案"}
        suffix = "完成" if event["success"] else "需要调整"
        query = event["arguments"].get("query", "") if isinstance(event["arguments"], dict) else ""
        return f"{names.get(event['name'], event['name'])}：{query} {suffix}"
    return {"model_request": "正在选择下一步…", "context_compacted": "已整理任务上下文",
            "paused": "任务已暂停并保存", "model_error": "模型请求未成功"}.get(event["kind"], "进度已保存")


def show_error(exc):
    if type(exc) in (ValueError, RuntimeError):
        st.error(str(exc))
    else:
        st.error(f"操作未完成（{type(exc).__name__}）。考证任务可在侧栏查看和恢复。")
