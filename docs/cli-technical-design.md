# stock-news CLI 技术方案

## 1. 定位

stock-news CLI（命令名 `sn`）是投研信息流的本地命令行工具。两个核心用户：

1. **人** — 在终端手动执行，查看结果。
2. **Agent** — Claude Code 等 AI agent 通过 `bash` 直接调用，解析 JSON 输出。

所有能力都通过 CLI 子命令暴露，不做 TUI。Agent 友好是第一优先级。

## 2. 命令设计

### 全局选项

```bash
sn --json <subcommand>    # 所有命令的 JSON 结构化输出
sn --verbose <subcommand> # 显示完整错误栈
sn --version              # 版本
```

### 数据采集

```bash
# 拉取微信 API 消息，按时间窗口增量采集
sn fetch --source 个人消息 --start 20260523090000 --end 20260523113000
sn fetch --source 个人群 --start 20260523090000 --end 20260523113000
sn fetch --source all --last 30m          # 拉取最近 30 分钟

# 查看已采集数据的统计信息
sn data stats                             # 本地数据概览
sn data stats --date 2026-05-23 --json    # 指定日期，JSON 输出
sn data list --date today --source 个人群  # 列出消息
sn data dedup --date today --dry-run      # 预览去重结果
sn data dedup --date today                # 执行去重
```

fetch 自动去重：每条消息按 `sha256(sender + message_time + raw_content)` 生成 ID，写入时跳过已存在的 ID。`sn data dedup` 用于清理历史数据中的重复。

### 分析与分类

```bash
# 对已采集消息做分类（有效推荐 / 研究观点 / 噪声）
sn analyze classify --date today
sn analyze classify --date 2026-05-23 --json

# 从有效推荐中抽取结构化字段（推荐人、标的、动作、强度、周期）
sn analyze extract --date today
sn analyze extract --date today --json

# 查看分析结果
sn analyze show --date today              # 人类可读的今日分析摘要
sn analyze show --date today --json       # Agent 用
```

### 报告生成

```bash
# 生成今日推荐池页面
sn report generate --date today --format html
sn report generate --date today --format json
sn report generate --date today --format pdf

# 生成推荐人排行榜
sn report senders --json

# 生成并上传到阿里云
sn report publish --date today
```

### 定时任务

```bash
# 注册定时任务
sn schedule add --name "早盘采集" --cron "30 9 * * 1-5" -- sn fetch --source all --last 60m
sn schedule add --name "午盘分析" --cron "5 13 * * 1-5" -- sn analyze classify --date today

# 管理
sn schedule list --json          # 列出所有定时任务
sn schedule remove <id>          # 删除任务
sn schedule enable <id>          # 启用
sn schedule disable <id>         # 禁用
sn schedule logs <id> --lines 50 # 查看任务执行日志

# 守护进程
sn schedule daemon start         # 启动调度守护进程
sn schedule daemon stop          # 停止
sn schedule daemon status --json # 查询状态
```

### 配置

```bash
sn config show                   # 显示当前配置
sn config set api.base_url https://example.com/api
sn config set api.sources '["个人消息", "个人群"]'
sn config set storage.data_dir ~/.stock-news/data
sn config set aliyun.host 阿里云IP
sn config set aliyun.deploy_dir /var/www/stock-news
```

### 行情数据

```bash
# 查询个股价格（回测和评分的基础）
sn market price 贵州茅台                    # 最新价
sn market price 600519 --days 20 --json    # 最近 20 个交易日行情
sn market price 600519 --start 2026-05-01 --end 2026-05-23

# 批量拉取推荐标的的行情（配合 analyze extract 的结果）
sn market fetch-recommendations --date today  # 自动拉取今日推荐涉及的所有标的行情
sn market fetch-recommendations --date today --json

# 回测：计算推荐后 N 日表现
sn market backtest --date 2026-05-20 --json  # 回测 5 月 20 日的推荐
sn market backtest --sender 某推荐人 --days 30 --json  # 某人最近 30 天推荐的回测

# 推荐人评分（基于回测数据）
sn market score --json                       # 所有推荐人评分
sn market score --sender 某推荐人 --json     # 单人画像

# 数据源管理
sn market config                             # 查看行情数据源配置
sn market config --provider efinance          # 默认，免费
sn market config --provider tushare --token xxx  # TODO: 付费开通后切换，更快更稳
```

### 使用统计

```bash
sn stats                         # 命令使用统计
sn stats --json
```

## 3. LLM 集成

### 定位

LLM 是 CLI 的核心能力层，不是附加功能。消息分类、推荐抽取、观点链归并、摘要生成都依赖 LLM 做结构化理解。

### 接口协议

统一走 OpenAI 兼容接口（`/v1/chat/completions`），支持任何兼容服务商：

| 服务商 | base_url 示例 |
| --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` |
| Moonshot | `https://api.moonshot.cn/v1` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 硅基流动 | `https://api.siliconflow.cn/v1` |
| 本地 Ollama | `http://localhost:11434/v1` |

### 命令

```bash
# 模型配置
sn llm config                             # 查看当前 LLM 配置
sn llm config --provider deepseek --model deepseek-chat --api-key sk-xxx
sn llm config --provider custom --base-url http://xxx/v1 --model xxx --api-key xxx

# 多 provider 管理（不同任务可以用不同模型）
sn llm add deepseek --base-url https://api.deepseek.com/v1 --api-key sk-xxx --model deepseek-chat
sn llm add glm --base-url https://open.bigmodel.cn/api/paas/v4 --api-key xxx --model glm-4-flash
sn llm list --json
sn llm set-default deepseek

# 测试连通性
sn llm test                               # 测试默认 provider
sn llm test --provider glm                # 测试指定 provider

# 直接对话（调试用）
sn llm chat "这条消息是否包含股票推荐：XXX"
sn llm chat "..." --provider glm --json
```

### LLM 在各环节的作用

| 环节 | CLI 命令 | LLM 任务 | 备选（无 LLM） |
| --- | --- | --- | --- |
| 消息分类 | `sn analyze classify` | 判断消息类型：推荐 / 研究 / 活动 / 噪声 | 关键词规则 |
| 推荐抽取 | `sn analyze extract` | 抽取标的、动作、强度、周期、理由 | 正则匹配 |
| 标的识别 | `sn analyze extract` | 模糊公司名 → 股票代码/名称 | 本地词典匹配 |
| 观点链归并 | `sn analyze opinion` | 判断同一推荐人对同一标的的观点变化 | 无 |
| 摘要生成 | `sn report generate` | 生成今日投研简报 | 模板拼接 |
| 信号排序理由 | `sn report generate` | 解释为什么这个信号排在前面 | 无 |

每个命令都支持 `--no-llm` 降级到规则模式，保证在 LLM 不可用时 CLI 仍能运行。

### Prompt 管理

Prompt 模板存储在配置目录，可以自定义和迭代：

```
~/.config/stock-news/prompts/
├── classify.txt          # 消息分类 prompt
├── extract.txt           # 推荐抽取 prompt
├── opinion.txt           # 观点链归并 prompt
└── summary.txt           # 摘要生成 prompt
```

每个 prompt 要求 LLM 返回 JSON，CLI 用 pydantic 校验：

```
你是一个投研消息分类器。请判断以下消息的类型，返回 JSON：
{"category": "recommendation|research|event|tool|noise", "confidence": 0.0-1.0, "reason": "..."}

消息：{raw_content}
发送人：{sender}
来源：{source}
```

### 架构实现

```
common/
├── llm/
│   ├── __init__.py
│   ├── client.py         # OpenAI 兼容客户端，统一封装
│   ├── providers.py      # provider 配置管理
│   └── prompts.py        # prompt 模板加载与渲染
```

`client.py` 核心接口：

```python
class LLMClient:
    def chat(self, messages: list[dict], model: str | None = None) -> str: ...
    def chat_json(self, messages: list[dict], response_model: type[T]) -> T: ...
```

`chat_json` 发送请求后用 pydantic 解析返回，解析失败自动重试一次。

### 成本控制

- 分类和抽取优先用便宜的小模型（deepseek-chat、glm-4-flash）。
- 摘要和复杂归并可选用大模型。
- 配置里可以按任务指定不同 provider：

```yaml
llm:
  default_provider: deepseek
  task_routing:
    classify: deepseek       # 便宜，量大
    extract: deepseek
    opinion: glm             # 复杂推理用更强的
    summary: deepseek
```

- `sn llm stats` 统计 token 用量和成本。

## 4. 项目结构

复用 dev-connect 的分层模式：

```
stock-news/
├── pyproject.toml
├── src/stock_news/
│   ├── __init__.py
│   ├── cli.py                   # click group 入口，全局 --json/--verbose
│   ├── models.py                # pydantic 数据模型
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── fetch.py             # 数据采集（微信 API 拉取）
│   │   ├── data.py              # 本地数据查询（stats/list）
│   │   ├── analyze.py           # 消息分类、推荐抽取、观点链
│   │   ├── market.py            # 行情数据、回测、推荐人评分
│   │   ├── report.py            # 报告生成与发布
│   │   ├── schedule.py          # 定时任务管理
│   │   ├── llm.py               # LLM 配置与调试命令
│   │   └── config.py            # 配置管理
│   └── common/
│       ├── __init__.py
│       ├── config.py            # YAML 配置读写
│       ├── storage.py           # 本地数据存储（JSON/SQLite）+ 去重
│       ├── wechat_api.py        # 微信 API 客户端
│       ├── market.py            # 行情数据源客户端（akshare 等）
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── client.py        # OpenAI 兼容客户端
│       │   ├── providers.py     # 多 provider 管理
│       │   └── prompts.py       # prompt 模板加载
│       ├── scheduler.py         # APScheduler 封装
│       └── exceptions.py        # 统一异常
├── tests/
├── data/                        # 默认本地数据目录（可配置）
│   ├── raw/                     # 原始 API 响应
│   ├── classified/              # 分类结果
│   ├── extracted/               # 结构化推荐
│   └── market/                  # 行情缓存
└── docs/
```

### 依赖方向

```
cli.py → commands/ → common/
```

- 上层导入下层，下层禁止导入上层。
- `commands/` 之间互不依赖。
- 共享逻辑下沉到 `common/`。

## 5. 数据模型

### 原始消息

```python
class RawMessage(BaseModel):
    source: str                  # "个人消息" | "个人群"
    sender: str                  # 发送人
    message_time: datetime       # 消息时间
    raw_content: str             # 原始正文
    group_name: str | None       # 群名称，仅群消息
    fetch_time: datetime         # 采集时间
    fetch_window: str            # 采集窗口标识
```

### 分类结果

```python
class ClassifiedMessage(BaseModel):
    message_id: str              # 关联原始消息
    category: MessageCategory    # recommendation | research | event | tool | noise
    confidence: float            # 分类置信度
    reason: str                  # 分类依据
    llm_provider: str | None     # 使用的 LLM provider，规则分类时为 None
```

### 结构化推荐

```python
class Recommendation(BaseModel):
    message_id: str              # 关联原始消息
    sender: str                  # 推荐人
    ticker: str                  # 股票名称或代码
    market: str | None           # A股 / 港股 / 美股
    action: str                  # 关注 / 买入 / 加仓 / 减仓 / 卖出
    strength: str                # 高 / 中 / 低
    horizon: str | None          # 日内 / 短线 / 波段 / 中线
    reasoning: str | None        # 推荐理由摘要
    risk_note: str | None        # 风险提示
    raw_content: str             # 原文
```

### 观点链

```python
class OpinionNode(BaseModel):
    opinion_id: str              # 观点链 ID
    version: int                 # 同一观点链的第几次更新
    message_id: str              # 关联原始消息
    sender: str                  # 推荐人
    topic_key: str               # 标的/主题归并 key
    stance: str                  # bullish / bearish / neutral / mixed
    update_type: str             # new / reinforce / supplement / revise / reverse / withdraw
    previous_id: str | None      # 上一条观点 ID
    summary: str                 # LLM 生成的观点摘要
```

### 行情数据

```python
class DailyPrice(BaseModel):
    ticker: str                  # 股票代码，如 600519
    name: str                    # 股票名称，如 贵州茅台
    date: date                   # 交易日
    open: float
    close: float
    high: float
    low: float
    volume: int
    change_pct: float            # 涨跌幅 %
```

### 回测结果

```python
class BacktestResult(BaseModel):
    recommendation_id: str       # 关联推荐
    sender: str                  # 推荐人
    ticker: str                  # 标的
    recommend_date: date         # 推荐日期
    recommend_price: float       # 推荐时价格
    returns: dict[str, float]    # {"1d": 0.02, "3d": -0.01, "5d": 0.05, "10d": 0.08, "20d": 0.12}
    max_drawdown: float          # 跟踪期内最大回撤
    hit: bool                    # 是否达到预设收益
    chasing_high: bool           # 推荐时是否处于短期高位
```

### 推荐人评分

```python
class SenderScore(BaseModel):
    sender: str
    total_recommendations: int   # 有效推荐总数
    win_rate: dict[str, float]   # {"1d": 0.6, "3d": 0.55, ...} 各周期胜率
    avg_return: dict[str, float] # 各周期平均收益
    profit_loss_ratio: float     # 盈亏比
    max_drawdown: float          # 推荐的平均最大回撤
    best_sectors: list[str]      # 擅长板块
    best_horizon: str            # 最优周期
    consistency: float           # 稳定性评分
    score: float                 # 综合评分
    last_updated: datetime
```

### LLM Provider

```python
class LLMProvider(BaseModel):
    name: str                    # 别名，如 deepseek / glm
    base_url: str                # OpenAI 兼容接口地址
    api_key: str                 # API key
    model: str                   # 默认模型名
    max_tokens: int = 4096
    temperature: float = 0.1     # 结构化抽取用低温度
```

### 定时任务

```python
class ScheduledTask(BaseModel):
    id: str
    name: str
    cron: str                    # cron 表达式
    command: str                 # 要执行的 sn 子命令
    enabled: bool
    last_run: datetime | None
    last_status: str | None      # success / failed
    created_at: datetime
```

## 6. 配置文件

路径：`~/.config/stock-news/config.yaml`

```yaml
api:
  base_url: "https://example.com/api"
  sources:
    - "个人消息"
    - "个人群"
  timeout: 30

llm:
  default_provider: deepseek
  providers:
    deepseek:
      base_url: "https://api.deepseek.com/v1"
      api_key: "sk-xxx"
      model: "deepseek-chat"
      max_tokens: 4096
      temperature: 0.1
    glm:
      base_url: "https://open.bigmodel.cn/api/paas/v4"
      api_key: "xxx"
      model: "glm-4-flash"
      max_tokens: 4096
      temperature: 0.1
  task_routing:
    classify: deepseek
    extract: deepseek
    opinion: deepseek
    summary: deepseek

market:
  provider: "efinance"           # efinance（默认，免费） | tushare（付费，需老板开通）
  tushare_token: ""              # TODO: tushare 付费开通后填入 token 即可切换
  cache_days: 30                 # 行情本地缓存天数
  backtest_periods:              # 回测周期
    - 1
    - 3
    - 5
    - 10
    - 20
  win_threshold: 0.02            # 胜率判定阈值（涨 2% 算赢）

storage:
  data_dir: "~/.stock-news/data"
  format: "json"                 # json | sqlite（后续支持）

aliyun:
  host: ""
  user: ""
  deploy_dir: "/var/www/stock-news"
  auth: "basic"                  # basic | token | none

channel:
  webhook_url: ""
  type: "feishu"                 # feishu | wechat_work

schedule:
  pid_file: "~/.stock-news/scheduler.pid"
  log_dir: "~/.stock-news/logs"
```

## 7. 存储方案

第一阶段使用 JSON 文件，按日期分目录：

```
~/.stock-news/data/
├── 2026-05-23/
│   ├── raw/
│   │   ├── 个人消息_093000_113000.json
│   │   └── 个人群_093000_113000.json
│   ├── classified/
│   │   └── classified.json
│   └── extracted/
│       └── recommendations.json
├── 2026-05-24/
│   └── ...
```

后续数据量增长时，`storage.format` 切换为 `sqlite`，接口不变。

## 8. 定时调度方案

### 方案：APScheduler + daemon 进程

```
sn schedule daemon start
```

启动一个后台守护进程，读取已注册的任务列表，按 cron 表达式触发执行。

实现要点：

1. daemon 进程写 PID 文件，`sn schedule daemon status` 检查是否存活。
2. 每个任务执行时 fork 子进程运行对应的 `sn` 命令。
3. 执行日志写入 `~/.stock-news/logs/<task-id>/<timestamp>.log`。
4. Agent 通过 `sn schedule list --json` 和 `sn schedule logs <id> --json` 查询状态。

### 备选：纯 crontab 模式

如果不想维护 daemon，也可以：

```bash
sn schedule export-cron    # 导出为 crontab 格式
sn schedule import-cron    # 从 sn 任务列表写入系统 crontab
```

两种模式可以共存，用户按需选择。

## 9. Agent 调用模式

Agent 通过 `--json` 获取结构化输出：

```python
import subprocess, json

def sn(cmd: str) -> dict:
    result = subprocess.run(
        f"sn --json {cmd}", shell=True,
        capture_output=True, text=True
    )
    return json.loads(result.stdout)

# 采集最近 30 分钟
sn("fetch --source all --last 30m")

# 分析今天的消息
sn("analyze classify --date today")

# 获取今日推荐
recommendations = sn("analyze show --date today")

# 查看定时任务状态
tasks = sn("schedule list")

# 查看某任务的最近日志
logs = sn("schedule logs morning-fetch --lines 20")
```

典型 Agent 工作流：

```
1. sn fetch --source all --last 60m --json         → 采集消息
2. sn analyze classify --date today --json         → LLM 分类
3. sn analyze extract --date today --json          → LLM 结构化抽取
4. sn market fetch-recommendations --date today    → 拉取推荐标的行情
5. sn market backtest --date 2026-05-20 --json     → 回测历史推荐
6. sn market score --json                          → 推荐人评分
7. sn analyze show --date today --json             → 生成摘要给用户
```

## 10. 技术栈

| 组件 | 选型 | 理由 |
| --- | --- | --- |
| CLI 框架 | click | 与 dev-connect 一致，成熟稳定 |
| 数据模型 | pydantic v2 | 校验 + 序列化，JSON 输出天然支持 |
| 配置 | pyyaml | 与 dev-connect 一致 |
| HTTP | httpx | 微信 API + LLM API 统一用，比 requests 现代 |
| LLM 客户端 | openai (Python SDK) | OpenAI 兼容接口的事实标准客户端，所有兼容服务商都能用 |
| 行情数据 | efinance（默认） | 免费无 token，东方财富数据源；TODO: tushare 付费开通后配置切换 |
| 定时调度 | APScheduler 3.x | 轻量，支持 cron 表达式，可内嵌 |
| 打包 | hatchling + uv | 与 dev-connect 一致 |
| Lint | ruff | 行宽 88 |
| 类型检查 | mypy --strict | 与 dev-connect 一致 |
| 测试 | pytest | 与 dev-connect 一致 |

## 11. 输出格式约定

所有命令在 `--json` 模式下返回统一结构：

```json
{
  "ok": true,
  "data": { ... },
  "message": "采集完成，共 42 条消息"
}
```

错误时：

```json
{
  "ok": false,
  "error": "API 请求超时",
  "detail": "..."
}
```

人类模式下直接输出可读文本，不包装。

## 12. 与现有项目的关系

当前 `stock-news/` 下已有的 `scripts/` 和 `data/` 是前期探索产物（已归档到 `docs/archive/`）。CLI 工具是正式工程化重构：

- `scripts/inspect_wechat_api.py` → `sn fetch` + `sn data stats`
- `scripts/fetch_and_analyze_wechat_windows.py` → `sn fetch` + `sn analyze classify`
- `docs/boss-facing-deliverable.py` → `sn report generate` + `sn report publish`

旧脚本保留在 `docs/archive/` 作为参考，不再维护。

## 13. 实现节奏

### P0：骨架 + 采集（1-2 天）

1. `pyproject.toml` + 项目结构 + `sn` 入口。
2. `sn config show/set`。
3. `sn fetch` — 拉取微信 API，存 JSON，写入去重。
4. `sn data stats/list/dedup`。
5. 全局 `--json` 支持。

### P1：LLM 集成 + 分析（2-3 天）

1. `sn llm config/add/list/test` — LLM provider 管理。
2. `common/llm/` — OpenAI 兼容客户端 + prompt 模板。
3. `sn analyze classify` — LLM 分类 + `--no-llm` 规则降级。
4. `sn analyze extract` — LLM 结构化推荐抽取。
5. `sn analyze opinion` — 观点链归并。
6. `sn analyze show` — 分析结果展示。

### P2：行情 + 回测（2-3 天）

1. `common/market.py` — akshare 行情客户端 + 本地缓存。
2. `sn market price` — 个股行情查询。
3. `sn market fetch-recommendations` — 批量拉取推荐标的行情。
4. `sn market backtest` — 回测推荐后 N 日表现。
5. `sn market score` — 推荐人评分与画像。

### P3：报告 + 发布（1-2 天）

1. `sn report generate` — 静态 HTML 生成（含 LLM 摘要 + 回测数据）。
2. `sn report senders` — 推荐人排行。
3. `sn report publish` — 上传阿里云。

### P4：定时调度（1-2 天）

1. `sn schedule add/list/remove`。
2. `sn schedule daemon start/stop/status`。
3. `sn schedule logs`。

### P5：Channel 推送（0.5-1 天）

1. `sn notify` — 推送飞书/企微机器人。

总计约 **9-13 天**。
