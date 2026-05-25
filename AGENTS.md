# AGENTS.md

This guide is for coding agents working in this repository. It explains the current project shape, safe modification paths, and risk boundaries for the投研信息流 CLI 工具 (`stock-news` / `sn`).

## 1. Repository Snapshot

- Root: `/Users/bytedance/Work/tools/cli/stock-news`
- Repository status: this directory is currently **not** a git repository — there is no `git diff` safety net.
- Runtime: Python 3.10+，由 `uv` 管理（`pyproject.toml` + `uv.lock`）。
- Form: 单一可安装包 `stock-news`，暴露 `sn` 命令行入口。
- 依赖栈: `click` / `pydantic v2` / `httpx` / `openai` / `tushare` / `efinance` / `pyyaml`；dev: `ruff` / `mypy` / `pytest`。
- 工程阶段: 微信消息采集 → LLM 分类/抽取/观点链 → HTML 报告 → 行情数据缓存 → 推荐人回测（部分进行中）。详见 `README.md` 路线图。

## 2. CLI Entrypoint (`sn`)

`sn` 由 `src/stock_news/cli.py` 暴露，子命令分组：

```text
sn fetch                          # 拉取微信 API 消息
sn data {stats|list|dedup}        # 本地数据查询/去重
sn analyze {classify|extract|opinion|show|report|pipeline|backtest|backtest-summary}
sn llm {add|list|set-default|test|chat|route}
sn market {set-token|init|search|price|info}
sn config {show|set}
```

全局 flag：`--json`（结构化输出，Agent 友好）、`--verbose`（完整错误栈）。

典型链路：

```text
微信 API (sn fetch)
  → ~/.config/stock-news/data/<date>/raw/
  → sn analyze classify  → classified/
  → sn analyze extract   → extracted/recommendations.json
  → sn analyze opinion   → opinions/
  → sn analyze report    → report/daily-report.html

Tushare (sn market init/price)
  → ~/.config/stock-news/market.db
  → sn analyze backtest  → ~/.config/stock-news/data/<date>/backtest/
```

## 3. Code Layout (`src/stock_news/`)

- `cli.py` — click 入口，仅做参数解析与转发；不写业务逻辑。
- `models.py` — Pydantic 共享模型（`RawMessage` / `ClassifiedMessage` / `Recommendation` / `OpinionNode`）和配置模型（`AppConfig` / `LLMConfig` / ...）。改字段名/类型要同步检查所有 `commands/`。
- `commands/`
  - `fetch.py`、`data.py`、`config_cmd.py`、`llm_cmd.py`、`market_cmd.py`
  - `analyze.py` — 分类 / 抽取 / 观点链 / 一键 pipeline，含批量 + 并发 + 增量落盘。最复杂的文件，优先精读。
  - `backtest.py` — 推荐人回测与汇总。
  - `report.py` — HTML 报告生成（含 LLM 摘要）。
- `common/`
  - `config.py` — 配置加载（`~/.config/stock-news/config.yaml`，懒 merge 默认值）。
  - `storage.py` — 数据目录约定 + 增量 JSON 读写 + `processed_ids` 去重。
  - `wechat_api.py` — 微信 API 客户端。
  - `exceptions.py` — `ConfigError` 等。
  - `llm/client.py` — OpenAI 兼容客户端，封装 **全局 RPM 限速器（90/min）**、**429 指数退避（2/4/8/16/32s, 共 5 次）**、`chat` / `chat_json` / `chat_json_list`。
  - `llm/prompts.py` — prompt 模板，可被 `~/.config/stock-news/prompts/` 覆盖。
  - `market/db.py`、`market/tushare_client.py` — Tushare + SQLite 缓存层。

## 4. Data Directories

运行时数据（**敏感、请勿外发**）：

```text
~/.config/stock-news/
├── config.yaml                  # 含 LLM api_key、API base_url
├── tushare_token                # Tushare token
├── market.db                    # SQLite 行情缓存
├── prompts/                     # 用户覆盖的 prompt
└── data/<YYYY-MM-DD>/
    ├── raw/                     # 原始消息
    │   └── .fetched.json        # fetch 切片缓存清单（隐藏，glob 不命中）
    ├── classified/              # 分类结果（增量）
    ├── extracted/               # recommendations.json + processed_ids.json
    ├── opinions/                # 观点链
    ├── backtest/                # 回测明细
    └── report/                  # 生成的 HTML
```

仓库内数据：

- `data/wechat_api/{raw,reports}/` — 项目早期的人工采样数据，**只读保留**，不要重写。
- `docs/archive/` — 早期 `scripts/`、boss-facing HTML/PDF/PNG、过往规划文档（`problem-analysis.md`、`wechat-api-protocol.md`、`window-data-model-insights.md`、`delivery-vision.md`、`boss-facing-deliverable.{md,py,html,pdf}` 等）。**不要修改**，除非用户明确要求复活。

当前活跃 docs（`docs/`）：

- `cli-technical-design.md`、`implementation-plan.md`、`classification-analysis.md`、`backtest-flow.md`、`tushare-data-layer.md`。

## 5. High-Risk Boundaries

- **活 API 调用** — 不要在未授权情况下运行 `sn fetch`、`sn market init/price`、`sn analyze {classify,extract,opinion,report,pipeline,backtest}`，这些都会打到真实 API 或消耗 LLM token。优先读现有数据。
- **原始微信消息敏感** — 不要在最终回答中粘贴大段原文、不要外传、不要 push 到任何外部服务。引用时压到几十字以内。
- **凭证敏感** — `~/.config/stock-news/config.yaml` 和 `tushare_token` 包含明文密钥，不要打印到日志/回答，不要复制到 git tracked 文件。
- **LLM 客户端约束**（踩过的坑）：
  - `LLMProviderConfig.max_tokens` 必须为 `None`（即 YAML 里 `max_tokens: null`）。曾经设为 `4096`，导致 batch 抽取 JSON 被截断 → JSONDecodeError → 大量 fallback。**不要随手补回 max_tokens 默认值**。
  - 全局 RPM 限速器写在 `client.py`，多线程共享。如要并发，复用 `chat*` 函数即可，不要绕过它直接调 `OpenAI().chat...`。
  - 429 重试已在客户端内做，业务层不要再叠加 sleep。
- **增量落盘语义** — `analyze.{classify,extract,opinion}` 都按 `processed_ids` 去重。如要"重跑"，应当**删除目标 `<date>/<阶段>/` 子目录下的 JSON 文件**，而不是给 LLM 多调用一次。删数据前先确认日期对。
- **fetch 切片缓存** — `sn fetch` 默认按 1h 切片 + 4 并发 + 切片级缓存（`raw/.fetched.json`）。已"安全过去"（slice_end + 5min < now）的切片写入清单，下次同窗口自动跳过 HTTP，提速 ~5×。需要强制重拉用 `--refresh`（读忽略 + 写覆盖），**不要直接删 `.fetched.json`**，否则全部历史切片都要重打服务端。调参用 `--slice-hours` / `--workers`，实测 workers>4 收益递减（瓶颈在最慢切片本身）。
- **回测结果**（`data/<date>/backtest/` 与 `backtest_summary/`）一旦用于汇报，重算前要保留备份。
- **HTML 报告** 路径默认在 `data/<date>/report/`；如用户给了 `-o` 输出到其它路径，注意别覆盖已有文件。

## 6. Commands

安全 / 只读类（无需用户额外授权）：

```bash
uv sync                                 # 同步依赖（含 .venv）
uv run sn --version
uv run sn config show
uv run sn data stats --date <YYYY-MM-DD>
uv run sn data list  --date <YYYY-MM-DD>
uv run sn analyze show --date <YYYY-MM-DD>
uv run sn market info
uv run sn market search <关键字>
rg -n "<pattern>" src docs
find . -maxdepth 3 -type f -not -path "./.venv/*" -not -path "./data/*" | sort
```

需用户显式授权才能跑（会打外网 / 消耗 token / 改本地数据）：

```bash
uv run sn fetch ...
uv run sn analyze classify|extract|opinion|report|pipeline ...
uv run sn analyze backtest ...
uv run sn market init
uv run sn market price <code> --start ... --end ...
uv run sn llm test|chat ...
```

谨慎 / 破坏性：

```bash
rm -rf ~/.config/stock-news/data/<date>/{classified,extracted,opinions,report,backtest}
rm    ~/.config/stock-news/market.db
sn config set llm.providers.<name>.api_key <...>   # 别打印到日志
```

避免运行（除非显式要求）：

```bash
git init / git add / git commit             # 项目当前不是 git 仓库
curl https://example.com/api...      # 用 sn fetch 走客户端
任何形式的远程上传 (scp / rsync / 网盘 / paste 站)
```

## 7. Verification

- 代码改完，按以下顺序自检：

```bash
uv run ruff check src/
uv run ruff format --check src/
uv run mypy src/stock_news/
uv run pytest                           # 注意：tests/ 目前仅占位，无真实用例
```

- 仅文档改动：用 `Read` 复看修改段，检查相对路径、章节锚点。
- 行为类改动：如果不能复跑真实 pipeline，必须**显式声明未验证的部分**，不要假装跑过。
- 不要声称 "已拉取最新数据" / "已重新生成报告"，除非对应 `sn` 命令真的执行过且回显成功。

## 8. Coding And Document Constraints

- 新加依赖必须更新 `pyproject.toml` 并跑 `uv sync` 确认 lock 一致；不要静默引入。
- 命令的业务逻辑放在 `commands/` 或 `common/`；`cli.py` 只做 click 接线。
- 共享数据结构走 `models.py`，不要在 `commands/` 里散落同义 dataclass。
- 所有面向用户的字符串保持中文；error/log 也是中文 + 必要英文堆栈。
- Prompt 模板改动优先放 `common/llm/prompts.py`；如果用户已经有 `~/.config/stock-news/prompts/` 覆盖，注意提示他可能需要同步删/更新。
- 不要在源码里硬编码绝对路径或日期，统一通过 `storage.py` 的辅助函数获取。
- `docs/archive/` 与 `data/wechat_api/` 视为只读历史，不要"顺手清理"。

## 9. Existing Changes / Git State

- 不是 git 仓库 → 任何改动都不可逆，编辑前先 `Read` 一遍当前文件，不要靠"回滚"。
- 用户的本地数据 (`~/.config/stock-news/data/`) 是真实跑出来的，删除前必须双重确认。
- 多次"清掉重跑"已经踩过坑，删数据前优先尝试增量补跑（删 `processed_ids.json` 局部条目而非整目录）。

## 10. Final Response Expectations

完成任务时报告：

- 改了哪些文件（绝对路径）。
- 关键行为/逻辑差异（功能点、性能、并发参数等）。
- 跑过哪些验证（`ruff` / `mypy` / `pytest` / 手动命令），未跑的明说原因。
- 因敏感性 / 凭证 / 真实 API 而**未运行**的命令，及对应假设。
- 待用户确认的下一步（如"是否清掉 `<date>/extracted/` 重跑"）。
