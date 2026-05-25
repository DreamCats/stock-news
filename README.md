# stock-news (sn)

投研信息流 CLI 工具。从微信消息采集 → LLM 分类/抽取 → 观点链归并 → 报告生成 → 行情回测，全链路沉淀在命令行里，人和 Agent 都能用。

## 安装

一键安装（推荐）：

```bash
curl -fsSL https://raw.githubusercontent.com/DreamCats/stock-news/main/install.sh | bash
sn --version
```

本地安装：

```bash
git clone https://github.com/DreamCats/stock-news.git
cd stock-news
./install.sh
sn --version
```

脚本会构建 wheel，并通过 `uv tool install` 全局注册 `sn` 命令。
如果已经 clone 到本地，直接在项目目录执行 `./install.sh` 即可。安装前需要本机已有 `uv`；使用 curl 安装时还需要 `git`。

开发模式：

```bash
uv sync
uv run sn --version
```

全局安装（可选）：

```bash
uv tool install .
sn --version
```

## 快速开始

```bash
# 1. 配置 LLM（OpenAI 兼容接口）
sn llm add mimo --base-url https://xxx/v1 --model mimo-v2.5 --api-key xxx --default

# 2. 拉取消息
sn fetch --source all --last 30m

# 3. 分析流水线
sn analyze classify --date today     # 消息分类
sn analyze extract --date today      # 推荐抽取
sn analyze opinion --date today      # 观点链归并
sn strategy generate --date today    # 生成盘中策略快报

# 4. 行情数据（回测准备）
sn market set-token <TUSHARE_TOKEN>
sn market init                       # 同步股票列表 + 交易日历
sn market search 贵州茅台             # 名称→代码
sn market price 600519.SH --start 20260501 --end 20260523
```

## 命令一览

### 数据采集 `sn fetch`

```bash
sn fetch --source all --last 30m
sn fetch --source 个人消息 --start 20260523090000 --end 20260523113000
sn fetch --source 个人群 --last 2h
sn fetch --source all --date today --time-range 09:00-23:00
```

### 数据查询 `sn data`

```bash
sn data stats --date today           # 数据统计
sn data list --date today            # 列出消息
sn data list --date today --source 个人群
sn data dedup --date today --dry-run # 预览去重
sn data dedup --date today           # 执行去重
```

### 消息分析 `sn analyze`

```bash
sn analyze classify --date today           # LLM 消息分类（增量）
sn analyze classify --date today --no-llm  # 规则降级
sn analyze extract --date today            # 推荐抽取（增量）
sn analyze opinion --date today            # 观点链归并（按发送人并行）
sn analyze show --date today               # 查看分析摘要
sn analyze backtest --date today           # 回测单日推荐表现
sn analyze backtest refresh --as-of today --window-days 30  # 补齐已成熟 T+N 回测窗口
sn analyze backtest summary --window-days 30 --min-count 3 --top 20  # 近 30 天推荐人胜率
```

分析流水线为增量设计：classify 和 extract 只处理新消息，重复运行不会重复消耗 LLM。
推荐人胜率汇总默认只看滚动近 30 天，避免历史擅长阶段稀释近期有效性；如需历史累计，可加 `--all`。

### 策略快报 `sn strategy`

```bash
sn strategy generate --date today --window-minutes 20 --top 5
```

默认生成结构化输入和可投递 Markdown：

```text
~/.config/stock-news/data/<date>/strategy/strategy.json
~/.config/stock-news/data/<date>/strategy/strategy.md
```

### LLM 管理 `sn llm`

```bash
sn llm add deepseek --base-url https://api.deepseek.com/v1 --model deepseek-chat --api-key xxx
sn llm list                          # 查看 provider
sn llm set-default deepseek          # 切换默认
sn llm test                          # 测试连通性
sn llm chat "你好"                   # 直接对话（调试）
sn llm route classify deepseek       # 按任务路由到不同 provider
```

支持任意 OpenAI 兼容接口。可按任务（classify/extract/opinion）路由到不同 provider。

### 行情数据 `sn market`

```bash
sn market set-token <TUSHARE_TOKEN>  # 配置 Tushare Pro token
sn market init                       # 同步股票列表（~5500只）+ 交易日历
sn market search 贵州茅台             # 名称→代码映射
sn market price 600519.SH --start 20260501 --end 20260523  # 查/拉日线
sn market info                       # 本地缓存统计
```

行情数据通过 SQLite 本地缓存，同一数据只拉一次，不重复消耗 Tushare 积分。

### 配置管理 `sn config`

```bash
sn config show
sn config set api.timeout 60
sn config set storage.data_dir ~/my-data
```

### 定时调度 `sn schedule`

```bash
sn schedule install                  # 安装 launchd 10 分钟 tick
sn schedule list                     # 列出 job 和最近状态
sn schedule tick                     # 手动执行一轮 due 检查
sn schedule run fetch                # 手动强跑某个 job
sn schedule logs --job fetch --tail 20
sn schedule disable fetch            # 临时停用，不改 yaml
sn schedule enable fetch
sn schedule uninstall
```

配置文件在 `~/.config/stock-news/schedule.yaml`。首次运行会生成空配置，
默认不预置任何会打 API 的 job；需要手动填 `jobs` 后再安装或 tick。

持续运行的盘中任务建议把采集和分析拆开：采集每 20 分钟跑当天
`09:00-23:00` 的窗口；分析继续使用 `--date today`，第二天会自动滚动。
回测建议单独放到收盘后的一日一次 job，避免盘中反复拉行情。

```yaml
jobs:
  - id: fetch-day-window
    command: cd /path/to/stock-news && uv run sn fetch --source all --date today --time-range 09:00-23:00
    every: 20m
    active_hours: "09:00-23:00"
    timeout: 10m

  - id: analyze-today
    command: cd /path/to/stock-news && uv run sn analyze classify --date today && uv run sn analyze extract --date today
    every: 20m
    active_hours: "09:05-23:10"
    timeout: 20m

  - id: backtest-daily
    command: cd /path/to/stock-news && uv run sn analyze backtest refresh --as-of today --window-days 30
    at: "16:30"
    timeout: 20m
```

### JSON 输出

所有命令加 `--json` 即可输出结构化 JSON，方便 Agent 解析：

```bash
sn --json fetch --source all --last 30m
sn --json data stats --date today
sn --json analyze show --date today
```

## 数据流

```
微信 API → sn fetch → raw messages (JSON)
  → sn analyze classify → classified.json（5 类: recommendation/research/event/tool/noise）
  → sn analyze extract  → recommendations.json（结构化推荐: ticker/action/strength/reasoning）
  → sn analyze opinion  → opinions.json（观点链: new/reinforce/revise/reverse/withdraw）
  → sn strategy generate → strategy.md（盘中策略快报: 新增机会 + 共识 + 观点变化）

Tushare → sn market → SQLite 缓存 → 回测引擎（TODO）
```

## 去重机制

每条消息按 `sha256(sender + message_time + raw_content)` 生成唯一 ID。`sn fetch` 写入时自动跳过已有 ID，重复拉取不会产生重复数据。

## 配置文件

路径：`~/.config/stock-news/config.yaml`

```yaml
api:
  base_url: "https://example.com/api"
  sources: ["个人消息", "个人群"]
  timeout: 30
llm:
  default_provider: mimo
  providers:
    mimo:
      base_url: "https://xxx/v1"
      model: "mimo-v2.5"
      api_key: "xxx"
  task_routing:
    classify: mimo
    extract: mimo
storage:
  data_dir: "~/.config/stock-news/data"
  format: "json"
```

## 数据目录

```
~/.config/stock-news/
├── config.yaml              # 配置
├── schedule.yaml            # 定时调度配置
├── market.db                # 行情 SQLite 缓存
├── tushare_token            # Tushare token
├── prompts/                 # LLM prompt 模板（可自定义覆盖）
├── schedule/                # 调度日志 / 状态 / 锁
└── data/
    └── 2026-05-21/
        ├── raw/             # 原始消息
        ├── classified/      # 分类结果
        ├── extracted/       # 推荐抽取
        ├── opinions/        # 观点链
        └── strategy/         # 策略快报 JSON / Markdown / state
```

## 路线图

- [x] P0：项目骨架 + 数据采集 + 去重
- [x] P1：LLM 集成 + 消息分类/推荐抽取/观点链
- [x] P1.5：HTML 报告生成（已从 CLI 入口移除，后续再议）
- [x] P2a：行情数据层（Tushare + SQLite 缓存）
- [x] P2b：推荐人回测 + 胜率评分
- [ ] P3：报告发布（阿里云 OSS）
- [x] P4：定时调度
- [ ] P5：Channel 推送
- [x] P6a：盘中策略快报（确定性 strategy JSON + markdown）
- [ ] P6b：20 分钟 workflow 串联与发送

详见 [技术方案](docs/cli-technical-design.md) 和 [实施计划](docs/implementation-plan.md)。
策略快报设计见 [策略快报 Workflow](docs/strategy-workflow.md)。

## 开发

```bash
uv sync --all-extras
uv run ruff check src/
uv run ruff format src/
uv run mypy src/stock_news/
uv run pytest
```

## 技术栈

Python 3.10+ / click / pydantic v2 / httpx / openai / tushare / SQLite / pyyaml / hatchling + uv
