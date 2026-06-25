# AGENTS.md

This guide is for coding agents working in `/Users/bytedance/Work/tools/cli/stock-news`.

## 当前项目形态

- 当前分支处于重构早期，保留配置、微信 SQLite 增量存储、Tushare 股票基础信息和项目进程内定时任务底座。
- CLI 入口注册 `sn config`、`sn wechat`、`sn tushare`、`sn schedule`。
- 旧的 LLM 执行、历史数据文件、策略、source-radar、workflow 和 delivery 执行层都已移除。
- 后续业务入口会从 `usecases/` 重新设计后再接回 CLI。

## 目录

```text
src/stock_news/
├── cli.py                    # CLI 总入口
├── models.py                 # 配置数据模型
├── commands/config_cli.py     # config 命令 click 接线
├── commands/config_cmd.py     # config 命令实现
├── commands/wechat_cli.py     # 微信拉取命令
├── commands/tushare_cli.py    # Tushare/market 命令
├── commands/schedule_cli.py   # 项目进程内定时任务命令
├── core/concurrency/          # 通用固定 worker 任务池
├── core/channels/             # 飞书 / 企业微信统一发送能力
├── core/config/               # YAML 配置读写、运行时加载/保存与点号路径修改
├── core/db/                   # 通用 SQLite 连接工具
├── core/llm/                  # OpenAI / Anthropic 协议客户端和 provider 选择
├── core/market/               # 股票公司和代码的 market.db 存储
├── core/scheduler/            # 定时判断和状态 JSON 存储
├── core/source_messages/       # 源头消息归一化、去重和催化词匹配
├── core/tushare/              # Tushare 代理协议客户端
├── core/wechat/               # 微信原始消息模型和 SQLite 增量存储
├── usecases/configs/          # 分文件配置加载、保存、模板
├── usecases/market_sync/      # Tushare 同步用例
├── usecases/scheduler/        # 固定定时任务执行用例
└── usecases/wechat_fetch/     # 微信拉取用例
```

## 配置文件

运行时配置在 `~/.config/stock-news/`：

```text
config.yaml              # 旧单文件配置，只作为读取兼容来源
schedule_state.json      # 定时任务最近运行状态
schedule.pid             # 后台定时进程 pid
schedule.log             # 后台定时进程日志
configs/models.yaml      # 模型供应商
configs/wechat.yaml      # 微信数据源 API / 鉴权 / 拉取参数 / SQLite 路径
configs/tushare.yaml     # Tushare 代理 / token / market.db 配置
configs/aly.yaml         # 阿里云主机 / 远端目录 / URL 前缀
configs/schedule.yaml    # 项目内定时任务配置
configs/channel.yaml     # 飞书 / 企业微信渠道配置
configs/catalysts.yaml   # 催化词内置开关、增量词和自定义分类
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
rtk .venv/bin/sn tushare info
rtk .venv/bin/sn tushare search 平安
rtk .venv/bin/sn schedule status
```

谨慎命令：

```bash
rtk .venv/bin/sn config set models.providers.<name>.api_key <secret>
rtk .venv/bin/sn config set channel.providers.<name>.webhook_url <secret>
rtk .venv/bin/sn config set aly.password <secret>
rtk .venv/bin/sn wechat fetch --last 30m      # 真实访问微信 API 并写 wechat.db
rtk .venv/bin/sn tushare sync-stocks          # 真实访问 Tushare 代理并写 market.db
rtk .venv/bin/sn schedule run wechat|market   # 手动触发真实任务
rtk .venv/bin/sn schedule start               # 后台常驻，会按配置触发真实任务
rtk .venv/bin/sn schedule restart             # 重启后台常驻进程
rtk .venv/bin/sn schedule stop                # 停止后台常驻进程
rtk .venv/bin/sn schedule serve               # 前台常驻，主要用于调试
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
- 股票状态同步 `L/D/P`，用 `list_status` 区分上市、退市、暂停上市。
- 不保存历史行情，不提供 daily/price/trade_cal 命令。

## 项目内定时任务

- 定时任务不是系统级 cron；日常用 `sn schedule start` 后台启动项目自己的 `schedule serve` 进程。
- 固定任务：`wechat_fetch` 和 `tushare_sync`，不要恢复通用 `jobs[].command` workflow。
- 默认 `wechat_fetch` 每 30 分钟拉最近 30 分钟；默认 `tushare_sync` 每天 08:30 跑一次。
- 状态写入 `~/.config/stock-news/schedule_state.json`，只记录最近一次执行状态。
- 后台进程文件是 `~/.config/stock-news/schedule.pid`，日志是 `~/.config/stock-news/schedule.log`。
- 进程重启后按当前时间继续判断，不补跑所有错过窗口。

## 源头消息和催化词

- `core/source_messages` 是可复用底座，只做文本归一化、去重 key、催化词库合并和匹配。
- 催化词默认用内置词库，`configs/catalysts.yaml` 只表达禁用、追加和自定义分类。
- core matcher 不读 DB、不强制“有标的才保留”；是否过滤无标的消息由具体 usecase 决定。

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
