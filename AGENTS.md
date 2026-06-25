# AGENTS.md

This guide is for coding agents working in `/Users/bytedance/Work/tools/cli/stock-news`.

## 当前项目形态

- 当前分支处于重构早期，保留配置能力和微信 SQLite 增量存储底座。
- CLI 入口只注册 `sn config`。
- 旧的微信拉取命令、LLM 执行、行情、本地历史数据、策略、source-radar、workflow、delivery 执行和 scheduler 执行层都已移除。
- 后续业务入口会从 `usecases/` 重新设计后再接回 CLI。

## 目录

```text
src/stock_news/
├── cli.py                    # CLI 总入口，只接 config
├── models.py                 # 配置数据模型
├── commands/config_cli.py     # config 命令 click 接线
├── commands/config_cmd.py     # config 命令实现
├── common/config.py           # 运行时配置加载/保存兼容入口
├── core/concurrency/          # 通用固定 worker 任务池
├── core/config/store.py       # YAML 配置读写与点号路径修改
├── core/db/                   # 通用 SQLite 连接工具
├── core/market/               # 股票公司和代码的 market.db 存储
├── core/tushare/              # Tushare 代理协议客户端
├── core/wechat/               # 微信原始消息模型和 SQLite 增量存储
└── usecases/configs/          # 分文件配置加载、保存、模板
```

## 配置文件

运行时配置在 `~/.config/stock-news/`：

```text
config.yaml              # 旧单文件配置，只作为读取兼容来源
schedule.yaml            # 定时任务配置
configs/models.yaml      # 模型供应商
configs/wechat.yaml      # 微信数据源 API / 鉴权 / 拉取参数 / SQLite 路径
configs/tushare.yaml     # Tushare 代理 / token / market.db 配置
configs/channel.yaml     # 飞书 / 企业微信渠道配置
```

`sn config set` 写入拆分后的配置文件，不再回写旧 `config.yaml`。旧根字段会映射到新名字：

```text
llm -> models
api -> wechat
market -> tushare
delivery -> channel
```

## 命令边界

安全命令：

```bash
rtk .venv/bin/sn --version
rtk .venv/bin/sn config show
rtk .venv/bin/sn --json config show
```

谨慎命令：

```bash
rtk .venv/bin/sn config set models.providers.<name>.api_key <secret>
rtk .venv/bin/sn config set channel.providers.<name>.webhook_url <secret>
```

不要在回答里打印 api key、token、webhook、app_secret。

## 微信 SQLite 增量语义

- 默认 DB 路径：`~/.config/stock-news/wechat.db`。
- `wechat_messages.message_id` 是唯一键，重复运行不重复插入。
- `wechat_fetch_windows` 用 `source + window_start + window_end` 记录窗口状态。
- 成功且超过 `safety_margin_minutes` 的窗口跳过；失败窗口和最近窗口允许重拉。
- 切片默认按 `slice_hours=1` 小时拆分，最后一片可以短于 1 小时。
- 切片并发执行使用 `core/concurrency` 固定 worker 池，任意切片完成后立刻补入下一个待执行切片。

## Tushare 和 market.db

- Tushare 代理不保存 token；每次请求都从本地 `tushare.token` 传给代理。
- 默认 DB 路径：`~/.config/stock-news/market.db`。
- 当前只保存股票公司和代码映射：`stock_companies`。
- 不保存历史行情，不提供 daily/price/trade_cal 命令。

## 开发规则

- 使用 `rtk` 前缀运行 shell 命令。
- 非平凡代码任务先尝试 `rtk codegraph ...`，失败后再用 `rg` / 直接读文件。
- 新增或保留的源码文件头部要有中文注释或中文 docstring。
- 手工改文件用 `apply_patch`。
- 不要擅自 commit / push。
- 不要删除 `~/.config/stock-news/` 下的真实运行数据或密钥，除非用户再次明确确认具体路径。

## 验证

```bash
rtk .venv/bin/ruff check src/ tests/
rtk .venv/bin/ruff format --check src/ tests/
rtk .venv/bin/mypy src/stock_news/
rtk .venv/bin/pytest
```
