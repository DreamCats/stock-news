# stock-news (sn)

投研信息流 CLI 的重构起点。当前版本只保留配置能力，旧的采集、分析、策略、回测、投递执行、SQLite 缓存和历史样例数据已经移除。

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
    ├── wechat.yaml          # 微信数据源 API、鉴权、拉取参数
    ├── tushare.yaml         # Tushare 代理配置
    └── channel.yaml         # 飞书 bot / 企业微信渠道配置
```

`sn config set` 会写入拆分后的配置文件，不再回写旧 `config.yaml`。

## 开发验证

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
.venv/bin/mypy src/stock_news/
.venv/bin/pytest
```
