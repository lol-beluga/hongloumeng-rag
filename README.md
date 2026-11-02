# 红楼梦原文考证助手

基于《红楼梦》120回文本的检索问答应用，支持普通RAG问答和多步原文考证。检索层使用jieba分词、TF-IDF与余弦相似度，回答由DeepSeek生成，Streamlit提供交互界面。

考证模式通过LangGraph组织工具调用，支持问题拆解、补充检索、上下文阅读和引用校验。任务状态保存在SQLite中，可查看执行记录、恢复未完成任务并导出报告。

执行流程和状态管理见[架构说明](ARCHITECTURE.md)。

## 功能

- 普通问答：一次检索后生成回答，展示命中的原文片段。
- 原文考证：按问题需要多次检索，支持限定回数和阅读相邻片段。
- 证据引用：结论区分事实与解读，校验引用编号和原文摘录。
- 任务管理：限制调用次数和执行时间，处理临时API错误，保存与恢复进度。
- 报告导出：下载Markdown报告或包含执行记录的JSON文件。

## 安装

开发环境为Python 3.14，依赖版本见[requirements.txt](requirements.txt)。

```bash
git clone https://github.com/lol-beluga/hongloumeng-rag.git
cd hongloumeng-rag
python -m venv .venv
```

激活虚拟环境：

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# Linux / macOS
source .venv/bin/activate
```

安装依赖：

```bash
python -m pip install -r requirements.txt
```

复制`.env.example`为`.env`，填写API密钥：

```dotenv
DEEPSEEK_API_KEY=your-api-key
DEEPSEEK_MODEL=deepseek-chat
```

也可以通过环境变量配置，或在网页侧栏填写密钥与模型名称。考证模式需要模型支持工具调用。

## 运行

```bash
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

打开[http://localhost:8501](http://localhost:8501)。Windows也可运行`start_app.cmd`启动应用。

在侧栏选择“普通问答”或“原文考证（Agent）”。例如：

> 依据第三十四回，比较宝钗和黛玉在宝玉挨打后的探望表现，分别给出原文依据，并区分事实与解读。

考证模式会结合最近几轮对话处理追问。达到调用或时间限制时，任务保存为暂停状态，可从侧栏的任务列表恢复；需要继续查证时，可选择增加一轮预算。完成后可查看原文、执行记录并下载报告。

## 命令行

```bash
# 新建考证任务
python agent_cli.py ask "第三十四回中宝钗如何给宝玉送药？"

# 查看最近任务
python agent_cli.py list

# 恢复任务，TASK_ID为任务编号
python agent_cli.py resume TASK_ID
python agent_cli.py resume TASK_ID --extend-budget

# 导出任务记录
python agent_cli.py show TASK_ID --out outputs/task.json
```

## 测试与评测

```bash
# 离线测试
python -m unittest discover -s tests -v

# 校验开发用例与参考原文，不请求API
python evaluate.py --dry-run

# 对比普通RAG和考证模式，会请求API
python evaluate.py --mode both --limit 1
```

评测结果保存在`outputs/eval-时间戳/`，包含配置、逐题预测、原文召回统计、Token用量和人工复核表`review.csv`。附带的6条用例用于开发验证；答案正确性与证据支持程度需要人工复核，不以引用文字校验率代替答案准确率。

## 项目结构

```text
├── docs/                 # 按回存放的原著文本
├── rag_system.py         # 文档切分、索引与原文检索
├── agent_harness.py      # Agent执行流程、调用限制与恢复
├── research_tools.py     # 工具定义、参数及引用校验
├── run_store.py          # SQLite任务状态与执行锁
├── app_ui.py             # Streamlit界面
├── streamlit_app.py      # 网页启动入口
├── agent_cli.py          # 命令行入口
├── evaluate.py           # 对照评测
├── eval/                 # 开发用例与参考原文
├── tests/                # 功能与界面测试
└── ARCHITECTURE.md       # 执行流程与设计说明
```

语料约86.9万字，切分为3110个不超过300字的片段，TF-IDF特征上限为5000。缓存随语料和索引版本变化建立新版本；任务记录、索引缓存和评测结果均不纳入版本控制。

引用校验检查摘录文字是否来自对应片段，不能自动证明结论被原文充分支持。当前语料为单一120回文本，不包含不同版本、脂批或研究论文。
