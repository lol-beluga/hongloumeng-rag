# 任务服务

Spring Boot 接收查阅请求，保存任务记录，再把工作交给 Python。浏览器不需要一直保持请求连接，刷新页面后可以继续查看任务。

## 启动与配置

需要 JDK 21，以及已经安装根目录 `requirements.txt` 依赖的 Python 环境。完整的初次安装命令见[项目首页](../README.md#开始使用)。

从本目录启动：

```powershell
# Windows，先在项目根目录设置 RESEARCH_PYTHON 和 RESEARCH_PROJECT_DIR
.\mvnw.cmd spring-boot:run
```

```bash
# Linux / macOS
sh mvnw spring-boot:run
```

网页默认位于 [http://127.0.0.1:8080](http://127.0.0.1:8080)。Ctrl+C 停止服务，任务数据库保留在本目录的 `data/` 中。

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `RESEARCH_PYTHON` | `python` | 安装了项目依赖的 Python 可执行文件路径，含空格的路径也支持 |
| `RESEARCH_PROJECT_DIR` | `..` | 项目根目录，建议设置为绝对路径 |
| `PORT` | `8080` | HTTP 端口 |
| `research.workers` | `2` | 同时执行的任务数 |
| `research.queue-capacity` | `8` | 等待队列容量 |
| `research.timeout-seconds` | `240` | 单个 Python 进程的最长执行时间 |

最后三个配置位于 `src/main/resources/application.properties`，也可以使用 Spring Boot 的环境变量形式覆盖，例如 `RESEARCH_WORKERS=1`。每个执行中的任务对应一个 Python 进程，需要分别加载索引；增加并发前应测量内存和模型接口额度。

数据库为 H2 文件库，任务包括问题、模式、状态、结果、执行次数和时间戳。Agent 的中间检查点保存在项目根目录的 `runs/research.sqlite3`，备份时需要同时保留两处数据。服务不保存或接收浏览器传来的模型密钥。

## 接口

### 提交任务

```http
POST /api/jobs
Content-Type: application/json
Idempotency-Key: research-example-001

{"question":"黛玉 葬花","mode":"lookup"}
```

`question` 为1至2000字；`mode` 为 `lookup`（只检索原文）或 `research`（多步考证）。请求编号为16至128位字母、数字、下划线或连字符，建议使用 UUID。

首次提交返回 `202 Accepted`，响应体包含 `id`、`status`，`Location` 指向任务查询接口。`202` 表示已接收，不表示已经查阅完成。

同一个请求编号、相同问题和模式重放时返回原任务，状态码为 `200`，附带 `Idempotency-Replayed: true`。同一个编号换成不同问题或模式返回 `409`。重新查询同一个问题时，应使用新的请求编号。

PowerShell 示例：

```powershell
$requestKey = [guid]::NewGuid().ToString()
$payload = @{ question = '黛玉 葬花'; mode = 'lookup' } | ConvertTo-Json
$job = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/jobs' -Method Post `
  -Headers @{ 'Idempotency-Key' = $requestKey } `
  -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($payload))
Invoke-RestMethod -Uri ('http://127.0.0.1:8080/api/jobs/' + $job.id)
```

### 查询和重试

| 接口 | 用途 |
| --- | --- |
| `GET /api/jobs?limit=20` | 最近任务，`limit` 范围1至100 |
| `GET /api/jobs/{id}` | 查询状态和结果 |
| `POST /api/jobs/{id}/retry` | 重试失败、暂停或中断的任务 |

重试请求体为 `{"extendBudget":false}`；需要增加一轮 Agent 预算时改为 `true`。已完成、运行中或排队中的任务不能重复重试，返回 `409`。考证重试沿用原任务编号；已有检查点时恢复检查点，没有检查点时才新建考证过程。

状态为 `QUEUED`、`RUNNING`、`COMPLETED`、`PAUSED`、`FAILED` 或 `INTERRUPTED`。`PAUSED` 通常需要查看结果中的 `stop_reason`，再决定修正配置还是增加预算。强制中止后 Python 执行锁可能尚未到期，立即重试可能失败，稍后可再次重试。

队列满时返回 `429`；关闭服务等情况下队列不可用会返回 `503`；参数不合法返回 `400`。收到 `202` 后应查询原任务；网络断开、无法确认是否提交成功时，应携带原请求编号重放。

## 排查问题

- **Java 版本不符：** 检查 `java -version` 与 `JAVA_HOME`，编译目标为 Java 21。
- **Python 执行失败：** 确认 `RESEARCH_PYTHON` 指向项目虚拟环境，`RESEARCH_PROJECT_DIR` 下有 `java_worker.py` 和 `docs/`。
- **查原文成功，考证失败或暂停：** 检查服务端 `DEEPSEEK_API_KEY`、模型名称及工具调用支持情况，再看任务的停止原因。
- **端口被占用：** 修改 `PORT`；同一任务数据库只能由一个服务实例打开。

默认只监听回环地址，当前没有登录和任务权限隔离，适合个人使用。跨用户部署需要先补充认证、授权与请求配额。

## 测试

```powershell
.\mvnw.cmd test
```

Java 测试使用内存 H2 和可控的执行器替身，覆盖 HTTP 校验、唯一键冲突、队列容量、重试状态和旧执行结果覆盖保护。真实 Python 原文检索需要另行通过网页或接口验证；这些自动化测试不会调用模型。
