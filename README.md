# stock-news (sn)

投研信息流 CLI 的重构起点。当前版本保留配置能力，并新增微信数据源 SQLite 增量存储底座。旧的采集命令、分析、策略、回测、投递执行和历史样例数据已经移除。

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
sn tushare sync-stocks
sn tushare search 贵州茅台
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
├── schedule.yaml            # 定时任务配置
└── configs/
    ├── models.yaml          # 模型供应商：glm/kimi/mimo/minimax
    ├── wechat.yaml          # 微信数据源 API、鉴权、拉取参数、SQLite 路径
    ├── tushare.yaml         # Tushare 代理配置、本地 token、market.db 路径
    └── channel.yaml         # 飞书 bot / 企业微信渠道配置
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

## 开发验证

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
.venv/bin/mypy src/stock_news/
.venv/bin/pytest
```
