# AGENTS.md

This guide is for coding agents working in this repository. It explains the current project shape, safe modification paths, and risk boundaries for the投研信息流 CLI 工具 (`stock-news` / `sn`).

## 1. Repository Snapshot

- Root: `/Users/bytedance/Work/tools/cli/stock-news`
- Repository status: **是 git 仓库**，remote `origin git@github.com:DreamCats/stock-news.git`，主分支 `main`。有 `git diff` / `git revert` 安全网；编辑前仍建议先 `Read`，但改坏了可以回滚。
- 提交习惯：直接在 `main` 上提交，commit message 用**英文**祈使句。**只有用户明确说"commit / push"时才提交**，不要擅自 commit。
- Runtime: Python 3.10+，由 `uv` 管理（`pyproject.toml` + `uv.lock`）。
- Form: 单一可安装包 `stock-news`，暴露 `sn` 命令行入口。
- 依赖栈: `click` / `pydantic v2` / `pyyaml` / `httpx` / `openai` / `tushare` / `efinance`；dev: `ruff` / `mypy` / `pytest` / `types-pyyaml`。
- 工程阶段: 微信消息采集 → LLM 分类/抽取/观点链 → 推荐人回测 → 盘中策略快报 → 源头雷达 → 多渠道投递 → 本地定时调度。详见 `docs/` 与 `README.md`。

## 2. CLI Entrypoint (`sn`)

`sn` 由 `src/stock_news/cli.py` 暴露（`cli_main` 入口，`_register_commands()` 注册 12 个子命令组）：

```text
sn fetch                                  # 拉取微信 API 消息
sn data {stats|list|dedup}                # 本地数据查询/去重
sn backfill                               # 顺序补齐历史窗口数据
sn analyze {classify|extract|opinion|show|pipeline|backtest}
sn analyze backtest {refresh|summary}     # 回测刷新与汇总（注意：是子组）
sn strategy generate                      # 盘中策略快报 JSON + Markdown
sn workflow {run|status}                  # 盘中增量 workflow（fetch→…→delivery 一键编排）
sn source {extract|scan}                  # 源头雷达
sn llm {add|list|set-default|test|chat|route}
sn market {set-token|init|search|price|info}
sn config {show|set}
sn schedule {start|restart|stop|serve|list|enable|disable|run|tick|status|logs}
sn delivery {send|test|provider|route|target}
```

全局 flag：`--json`（结构化输出，Agent 友好）、`--verbose`（完整错误栈）。注意 `--json` 是 `main` 组级 flag，须写在子命令前：`sn --json data stats ...`。

典型链路：

```text
微信 API (sn fetch)
  → ~/.config/stock-news/data/<date>/raw/
  → sn analyze classify  → classified/
  → sn analyze extract   → extracted/recommendations.json
  → sn analyze opinion   → opinions/
  → sn analyze backtest  → backtest/      （需先 sn market init）
  → sn strategy generate → strategy/

源头雷达：
  classified/ → sn source extract → source_extract/candidates.json
              → sn source scan    → source_scan/radar.md（--markdown）

编排与投递：
  sn workflow run    # fetch→classify→extract→backtest summary→strategy→可选 delivery
  sn delivery send   # 推送到 feishu_bot / wecom_bot（外发！）
  sn schedule serve  # 项目进程内持续 tick，按 schedule.yaml 跑 due job
```

## 3. Code Layout (`src/stock_news/`)

- `cli.py` — click 入口，仅 `add_command` 接线 + 全局异常捕获；不写业务逻辑。
- `models.py` — Pydantic 共享模型（`RawMessage` / `ClassifiedMessage` / `Recommendation` / `OpinionNode`）和配置模型（`AppConfig` / `LLMConfig` / ...）。改字段名/类型要同步检查所有 `commands/`。
- **接线 / 业务分离约定**：多数命令组拆成 `xxx_cli.py`（click 选项与分组，瘦）+ `xxx.py` / `xxx_cmd.py`（业务实现，厚）。改 click 接口看 `_cli`，改逻辑看业务文件。
- `commands/`
  - 接线层：`analyze_cli.py`、`fetch_cli.py`、`data_cli.py`、`config_cli.py`、`llm_cli.py`、`market_cli.py`、`source_cli.py`、`strategy_cli.py`、`workflow_cli.py`、`backfill_cli.py`。
  - `analyze/` — **已从单文件拆成包**：`classify.py` / `extract.py` / `opinion.py` / `pipeline.py` / `show.py` / `_common.py`。含批量 + 并发 + 增量落盘，最复杂，优先精读。
  - `backtest.py` — 推荐人回测、`refresh`、`summary`。
  - `source.py` / `source_extract.py` — 源头雷达：scan 适配层（含 markdown 渲染）/ LLM 抽取层。
  - `strategy/` — 盘中策略快报包：`scoring.py` / `payload.py` / `llm.py` / `render.py` / `excel.py` / `storage.py` / `entrypoint.py`。
  - `workflow.py` — 盘中增量编排（fetch→classify→extract→backtest summary→strategy→可选 delivery）。
  - `schedule_cmd.py` — 本地定时调度命令层。
  - `delivery.py` — 投递命令层（send/test/provider/route/target）。
  - `fetch.py`、`data.py`、`config_cmd.py`、`llm_cmd.py`、`market_cmd.py`、`backfill.py`。
- `source/`（顶层包，非 commands 子目录）— `models.py` / `features.py` / `scanner.py` / `storage.py`：源头雷达的纯本地特征与扫描算法（0 token）。
- `common/`
  - `config.py` — 配置加载（`~/.config/stock-news/config.yaml`，懒 merge 默认值）。
  - `storage.py` — 数据目录约定 + 增量 JSON 读写 + `processed_ids` 去重。
  - `wechat_api.py` — 微信 API 客户端。
  - `exceptions.py` — `ConfigError` 等。
  - `llm/client.py` — OpenAI 兼容客户端，封装 **全局 RPM 限速器（90/min）**、**429 指数退避（2/4/8/16/32s, 共 5 次）**、`chat` / `chat_json` / `chat_json_list`。
  - `llm/prompts.py` — prompt 模板，可被 `~/.config/stock-news/prompts/` 覆盖。
  - `market/db.py`、`market/tushare_client.py` — Tushare + SQLite 缓存层。
  - `scheduler/` — `config.py`（schedule.yaml 解析）/ `engine.py`（due 判定）/ `runner.py`（执行）/ `service.py`（项目进程内循环）/ `lock.py` / `state.py`。
  - `delivery/` — `service.py`（路由分发）/ `feishu_bot.py` / `wecom_bot.py`。

## 4. Data Directories

运行时数据（**敏感、请勿外发**）：

```text
~/.config/stock-news/
├── config.yaml                  # 含 LLM api_key、API base_url、delivery providers/routes
├── tushare_token                # Tushare token
├── market.db                    # SQLite 行情缓存
├── prompts/                     # 用户覆盖的 prompt
├── schedule.yaml                # 定时 job 定义（tick_interval / jobs[]）
├── schedule/                    # logs/ + state.json + locks/ + job 产物（如 source-radar.md）
└── data/<YYYY-MM-DD>/
    ├── raw/                     # 原始消息
    │   └── .fetched.json        # fetch 切片缓存清单（隐藏，glob 不命中）
    ├── classified/              # 分类结果（增量）
    ├── extracted/               # recommendations.json + processed_ids.json
    ├── opinions/                # 观点链
    ├── backtest/                # 回测明细
    ├── source_extract/          # candidates.json + processed_ids.json（LLM 抽取）
    ├── source_scan/             # radar.md（scan --markdown 落盘）
    └── strategy/                # 策略快报 JSON + Markdown + Excel
```

> 注意：早期文档里的 `report/`（`sn analyze report` HTML 报告）已废弃移除，不要再引用。

仓库内数据：

- `data/wechat_api/{raw,reports}/` — 项目早期的人工采样数据，**只读保留**，不要重写。

当前活跃 docs（`docs/`）：

- `source-radar-design.md`、`source-event-roadmap.md`、`strategy-workflow.md`。

> `docs/archive/` 目录当前不存在（早期归档已清理），如遇引用以实际为准。

## 5. High-Risk Boundaries

- **活 API 调用 / 烧 token** — 未授权不要运行：`sn fetch`、`sn market init/price`、`sn analyze {classify,extract,opinion,pipeline,backtest}`、`sn source extract`、`sn strategy generate`（含 LLM 摘要）、`sn workflow run`、`sn llm test/chat`。优先读现有数据。`sn source scan` 是纯本地、0 token，安全。
- **外发投递（新增高危）** — `sn delivery send` / `sn delivery test` 会**真的把内容推送到飞书/企微机器人**。`sn schedule run/tick` 会跑整条链路并可能触发 delivery。未经授权不要执行；尤其不要把原始消息或凭证推出去。
- **原始微信消息敏感** — 不要在最终回答中粘贴大段原文、不要外传、不要 push 到任何外部服务。引用时压到几十字以内。
- **凭证敏感** — `~/.config/stock-news/config.yaml`（含 LLM api_key + delivery webhook）和 `tushare_token` 是明文密钥，不要打印到日志/回答，不要复制到 git tracked 文件。
- **LLM 客户端约束**（踩过的坑）：
  - `LLMProviderConfig.max_tokens` 必须为 `None`（YAML 里 `max_tokens: null`）。曾设为 `4096` 导致 batch 抽取 JSON 被截断 → JSONDecodeError → 大量 fallback。**不要随手补回 max_tokens 默认值**。
  - 全局 RPM 限速器写在 `client.py`，多线程共享。要并发就复用 `chat*` 函数，不要绕过它直接调 `OpenAI().chat...`。
  - 429 重试已在客户端内做，业务层不要再叠加 sleep。
- **增量落盘语义** — `analyze.{classify,extract,opinion}` 和 `source extract` 都按 `processed_ids` 去重。要"重跑"应**删目标 `<date>/<阶段>/` 子目录的 JSON**（或删 `processed_ids.json` 局部条目），而不是给 LLM 多调一次。删数据前先确认日期对。
- **fetch 切片缓存** — `sn fetch` 默认 1h 切片 + 4 并发 + 切片级缓存（`raw/.fetched.json`）。已"安全过去"（slice_end + 5min < now）的切片写入清单，下次同窗口跳过 HTTP，提速 ~5×。强制重拉用 `--refresh`，**不要直接删 `.fetched.json`**。调参用 `--slice-hours` / `--workers`，实测 workers>4 收益递减。
- **回测结果**（`data/<date>/backtest/` 与 `backtest_summary/`）一旦用于汇报，重算前保留备份。
- **schedule.yaml 不在 git 里** — 它在 `~/.config/stock-news/`，是运行时配置。改 job（如 `every` / `active_hours` / `command`）直接编辑该文件即可，不会进版本库；`schedule run` 手动强跑会**绕过 active_hours**，`tick` 才受护栏约束。

## 6. Commands

安全 / 只读类（无需用户额外授权）：

```bash
uv sync                                 # 同步依赖（含 .venv）
uv run sn --version
uv run sn config show
uv run sn data stats --date <YYYY-MM-DD>
uv run sn data list  --date <YYYY-MM-DD>
uv run sn analyze show --date <YYYY-MM-DD>
uv run sn source scan --start <date> --end <date>   # 纯本地 0 token
uv run sn market info
uv run sn market search <关键字>
uv run sn schedule list|status|logs
uv run sn delivery route|target|provider            # 仅查看/配置，不发送
rg -n "<pattern>" src docs
```

需用户显式授权才能跑（会打外网 / 消耗 token / 改本地数据 / 外发）：

```bash
uv run sn fetch ...
uv run sn analyze classify|extract|opinion|pipeline ...
uv run sn analyze backtest refresh|summary ...
uv run sn source extract ...
uv run sn strategy generate ...
uv run sn workflow run ...
uv run sn market init
uv run sn market price <code> --start ... --end ...
uv run sn llm test|chat ...
uv run sn delivery send|test ...        # 外发飞书/企微
uv run sn schedule start|restart|serve  # 会按 due job 持续触发，可能外发 delivery
uv run sn schedule run|tick             # 会跑整条链路并可能触发 delivery
```

谨慎 / 破坏性：

```bash
rm -rf ~/.config/stock-news/data/<date>/{classified,extracted,opinions,backtest,source_extract,source_scan,strategy}
rm    ~/.config/stock-news/market.db
sn config set llm.providers.<name>.api_key <...>   # 别打印到日志
git commit / git push                              # 仅在用户明确要求时
```

避免运行（除非显式要求）：

```bash
curl https://example.com/api...          # 用 sn fetch 走客户端
任何形式的远程上传 (scp / rsync / 网盘 / paste 站)
git commit / git push（未经用户要求）
```

## 7. Verification

- 代码改完，按以下顺序自检：

```bash
uv run ruff check src/
uv run ruff format --check src/
uv run mypy src/stock_news/
uv run pytest                           # 注意：tests/ 目前仅占位，无真实用例
```

> 现状：`src/` 全量 `ruff` + `mypy` 已清零，应保持绿。若只想检查自己改的文件，可对具体路径单独跑。

- 仅文档改动：用 `Read` 复看修改段，检查相对路径、章节锚点。
- 行为类改动：如果不能复跑真实 pipeline，必须**显式声明未验证的部分**，不要假装跑过。
- 不要声称 "已拉取最新数据" / "已生成报告" / "已推送"，除非对应 `sn` 命令真的执行过且回显成功。

## 8. Coding And Document Constraints

- 新加依赖必须更新 `pyproject.toml` 并跑 `uv sync` 确认 lock 一致；不要静默引入。
- 命令的业务逻辑放在 `commands/`（业务文件）或 `common/`；`cli.py` 与 `*_cli.py` 只做 click 接线。
- 共享数据结构走 `models.py`（或 `source/models.py` 等领域模型），不要在 `commands/` 里散落同义 dataclass。
- 所有面向用户的字符串保持中文；error/log 也是中文 + 必要英文堆栈。
- Prompt 模板改动优先放 `common/llm/prompts.py`；如果用户已有 `~/.config/stock-news/prompts/` 覆盖，提示他可能需要同步删/更新。
- 不要在源码里硬编码绝对路径或日期，统一通过 `storage.py` / `source/storage.py` 的辅助函数获取。
- `data/wechat_api/` 视为只读历史，不要"顺手清理"。

## 9. Git State

- **是 git 仓库**（`origin` = github.com:DreamCats/stock-news，主分支 `main`）。改坏可以 `git diff` / `git checkout -- <file>` 回滚；但编辑前仍建议先 `Read`。
- **不要擅自 commit/push** —— 仅在用户明确说"commit / push"时执行。提交直接在 `main`，message 用英文。
- 用户的本地数据 (`~/.config/stock-news/data/`) 是真实跑出来的，删除前必须双重确认。
- 多次"清掉重跑"踩过坑，删数据前优先增量补跑（删 `processed_ids.json` 局部条目而非整目录）。

## 10. Final Response Expectations

完成任务时报告：

- 改了哪些文件（绝对路径）。
- 关键行为/逻辑差异（功能点、性能、并发参数等）。
- 跑过哪些验证（`ruff` / `mypy` / `pytest` / 手动命令），未跑的明说原因。
- 因敏感性 / 凭证 / 真实 API / 外发投递而**未运行**的命令，及对应假设。
- 待用户确认的下一步（如"是否清掉 `<date>/extracted/` 重跑"、"是否 commit"）。
