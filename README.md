# 红楼梦原文考证助手

在本地TF-IDF RAG的基础上，增加带执行控制的单Agent：拆解问题、多步检索、阅读上下文、逐字校验引用、保存与恢复任务。界面保留普通问答模式，便于比较。

技术：Python / Streamlit / jieba / scikit-learn / DeepSeek API / LangGraph / SQLite。

## 在这台电脑启动

双击项目目录中的 **start_app.cmd**，浏览器打开 `http://localhost:8501`。关闭命令窗口会停止服务。

也可以在PowerShell中运行：

```powershell
Set-Location 'E:\smart lib'
& '.venv\Scripts\python.exe' -X utf8 -m streamlit run streamlit_app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

现有 `.env` 继续使用；也可以在网页侧栏填写密钥。无密钥时仍可加载和校验本地索引。模型默认`deepseek-chat`，可通过`DEEPSEEK_MODEL`或侧栏设置为账户实际可用且支持工具调用的模型。

在新环境安装：

```powershell
python -m venv .venv
& '.venv\Scripts\python.exe' -m pip install -r requirements.txt
```

以 `.env.example` 为模板创建本地 `.env`，填入自己的密钥。不要将密钥提交到Git。

## 怎么使用

1. 选择“原文考证（Agent）”，输入需要查证的问题。例如：“依据第三十四回，比较宝钗和黛玉在宝玉挨打后的探望表现，分别给出原文依据。”
2. 查看执行步骤、子问题、最终结论与原文片段。每个结论区分事实和解读。
3. 可以继续追问；考证模式会带上最近几轮对话，但需要重新检索证据。
4. 达到预算或API未成功时，任务保存为暂停状态。在“最近的考证任务”中查看并继续。
5. 用完预算后，勾选“恢复时增加一轮调用与时间预算”再继续；普通恢复不会自动增加预算。
6. 完成后下载JSON任务记录或Markdown报告。已完成任务不会再次请求模型。

“普通问答”只做一次检索、生成回答，处理当前问题；它的引用没有Agent的逐字校验。

## 默认控制

每任务8次工具调用、10次模型请求、180秒执行预算，单次请求30秒、临时错误最多重试2次。单次输出上限3000 Token，最终最多4项带引用的结论。Token停止阈值40000，按API实际报告的用量累计；它不是账户计费硬上限。失败请求的用量可能未知。

工具包括三个只读原文工具（`search_text`、`read_passage`、`list_chapters`），以及任务计划和最终提交工具。模型不能执行shell、指定任意文件路径或修改原文。

引用校验仅证明编号和摘录文字真实，**不证明原文足以支持结论**。语料是一个120回文本版本，不能据此声称完成了脂评本、论文或不同版本的考证。

## 命令行

```powershell
# 创建任务，会调用DeepSeek API
& '.venv\Scripts\python.exe' -X utf8 agent_cli.py ask '第三十四回中宝钗如何给宝玉送药？'

# 查看最近任务，不调用模型
& '.venv\Scripts\python.exe' -X utf8 agent_cli.py list

# 将下面的 TASK_ID 换成实际任务编号
& '.venv\Scripts\python.exe' -X utf8 agent_cli.py resume TASK_ID
& '.venv\Scripts\python.exe' -X utf8 agent_cli.py resume TASK_ID --extend-budget
& '.venv\Scripts\python.exe' -X utf8 agent_cli.py show TASK_ID --out outputs\task.json
```

## 验证与评测

```powershell
# 离线功能测试，不调用API
& '.venv\Scripts\python.exe' -X utf8 -m unittest discover -s tests -v

# 核对6条开发用例的参考原文，不调用API
& '.venv\Scripts\python.exe' -X utf8 evaluate.py --dry-run

# 真实对比，会调用API；先用1题检查，再扩大规模
& '.venv\Scripts\python.exe' -X utf8 evaluate.py --mode both --limit 1
```

评测产物在`outputs/eval-时间戳/`：配置及语料指纹、逐题预测、用量、原文召回统计、`review.csv`人工判定表。答案准确率在人工核对前留空；召回率、引用文字校验率不能替代答案准确率。当前6题全是开发用例，后续需要另外构建独立测试集。

## 数据和文件

- `docs/`：原有120回文本，约86.9万字。
- `rag_system.py`：按句切分至最多300字、TF-IDF 5000特征、余弦相似度、章节和邻接阅读。
- `agent_harness.py`：LangGraph执行流程、预算、API重试、上下文整理、恢复。
- `research_tools.py`：工具协议、参数和引用校验。
- `run_store.py`：SQLite应用状态和执行锁。
- `app_ui.py` / `streamlit_app.py`：网页界面与启动入口。
- `agent_cli.py` / `evaluate.py`：命令行和对照评测。
- `cache/indices/语料指纹/`：3110个片段及索引缓存，随语料/设置变化建立新版本。
- `runs/research.sqlite3`：本地任务状态；`outputs/`为导出与评测结果。两者均被Git忽略。
- `UPGRADE.md`：实现说明、能力边界与面试讲解。

2026-11-02升级前的核心文件备份在 `E:\smart-lib-backups\before-agent-20261102\`。原文、已有密钥、旧缓存和`test2.1.py`保留。
