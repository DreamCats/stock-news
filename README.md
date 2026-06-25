# stock-news (sn)

投研信息流 CLI 的重构起点。当前版本保留配置能力，并新增微信数据源、
Tushare 股票基础信息和项目进程内定时任务底座。旧的分析、策略、回测、投递
执行和历史样例数据已经移除。

## 安装

```bash
uv sync
uv run sn --version
```

全局安装：

```bash
uv tool install .
sn --version
```

## 当前命令

```bash
sn config show
sn --json config show
sn config set wechat.timeout 60
sn config set models.default_provider glm
sn config set tushare.token <tushare-token>
sn wechat fetch --last 30m
sn tushare sync-stocks
sn tushare search 贵州茅台
sn schedule start
sn schedule restart
sn schedule stop
sn schedule status
sn schedule serve     # 前台调试
```

旧字段名仍做兼容映射：

```bash
sn config set api.timeout 60       # 等价于 wechat.timeout
sn config set llm.default_provider glm
sn config set market.timeout 30    # 等价于 tushare.timeout
sn config set delivery.routes.default.format markdown
```

## 配置文件布局

运行时配置在 `~/.config/stock-news/`：

```text
~/.config/stock-news/
├── config.yaml              # 旧单文件配置，仅作为读取兼容来源
├── schedule_state.json      # 定时任务最近运行状态
├── schedule.pid             # 后台定时进程 pid
├── schedule.log             # 后台定时进程日志
└── configs/
    ├── models.yaml          # 模型供应商：glm/kimi/mimo/minimax
    ├── wechat.yaml          # 微信数据源 API、鉴权、拉取参数、SQLite 路径
    ├── tushare.yaml         # Tushare 代理配置、本地 token、market.db 路径
    ├── aly.yaml             # 阿里云主机、远端目录和 URL 前缀
    ├── schedule.yaml        # 项目内定时任务配置
    ├── channel.yaml         # 飞书 bot / 企业微信渠道配置
    └── catalysts.yaml       # 催化词内置开关、增量词和自定义分类
```

`sn config set` 会写入拆分后的配置文件，不再回写旧 `config.yaml`。

微信原始消息的默认 SQLite 路径是 `~/.config/stock-news/wechat.db`。增量规则是：

- `message_id` 唯一，重复消息不会重复写入。
- `source + window_start + window_end` 记录拉取窗口状态。
- 已成功且超过安全延迟的窗口会跳过；失败窗口和最近窗口会重拉。
- 默认按 `wechat.fetch.slice_hours: 1` 拆成 1 小时切片，最后一片允许不足 1 小时。
- 并发执行复用 `core/concurrency` 的固定 worker 池，任意切片完成后立刻补入下一个切片。

Tushare 代理不会保存 token；`sn tushare sync-stocks` 会把本地
`tushare.token` 放进每次代理请求。`market.db` 默认路径是
`~/.config/stock-news/market.db`，当前只保存股票公司和代码映射，不保存历史行情。

`core/llm` 提供后续 usecase 可复用的模型调用能力：统一 `chat` 入口，
底层支持 OpenAI chat completions 协议和 Anthropic messages 协议，并按
`models.yaml` 的 `default_provider`、`task_routing`、`provider_pools` 选择 provider。

`core/channels` 提供后续 usecase 可复用的渠道发送能力：统一 `ChannelSender`
入口，底层支持飞书应用和企业微信群机器人，消息模型支持文本、富文本和文件。

`core/source_messages` 提供后续 usecase 可复用的源头消息处理能力：当前包含
催化词库合并、催化词匹配、微信装饰文本归一化和内容去重 key。催化词配置采用
内置词库 + `configs/catalysts.yaml` 用户增量覆盖的方式。

项目内定时任务不依赖系统 cron。日常用 `sn schedule start` 后台启动；
`sn schedule serve` 保留为前台调试入口。后台进程仍然只是项目自己的
`schedule serve` 进程：

- `wechat_fetch`：默认每 30 分钟拉一次最近 30 分钟微信数据。
- `tushare_sync`：默认每天 08:30 同步一次股票基础信息。

配置文件保持固定结构，不做通用 job/workflow：

```yaml
enabled: true
tick_interval: 30s
wechat_fetch:
  enabled: true
  every: 30m
  window: 30m
tushare_sync:
  enabled: true
  at: "08:30"
```

后台管理：

```bash
sn schedule start
sn schedule restart
sn schedule stop
sn schedule status
```

## 开发验证

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
.venv/bin/mypy src/stock_news/
.venv/bin/pytest
```
