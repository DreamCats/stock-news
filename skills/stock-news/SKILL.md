---
name: stock-news
description: "投研信息流 CLI 工具。当用户需要使用或修改 sn/stock-news，处理微信消息采集、本地数据查询、LLM 分类抽取、观点链、HTML 报告、行情缓存、推荐回测、定时调度时使用此 skill。"
---

# stock-news 投研信息流 CLI

`stock-news` 提供 `sn` 命令，把微信消息采集、本地分析、LLM 结构化、报告生成、行情缓存、推荐回测和定时调度串在一个 Python CLI 里。

## 项目形态

- 根目录通常是 `/Users/bytedance/Work/tools/cli/stock-news`。
- Python 3.10+，依赖由 `uv` 管理。
- 包入口：`src/stock_news/cli.py`，业务逻辑放在 `src/stock_news/commands/` 和 `src/stock_news/common/`。
- 用户配置和运行数据在 `~/.config/stock-news/`，包含明文 API key、Tushare token、原始微信消息和分析产物。
- 历史样例数据 `data/wechat_api/` 与归档文档 `docs/archive/` 默认只读。

## 常用安全命令

只读查询优先加 `--json`，方便 Agent 解析：

```bash
uv sync
uv run sn --version
uv run sn --json config show
uv run sn --json data stats --date today
uv run sn --json data list --date today
uv run sn --json analyze show --date today
uv run sn --json market info
uv run sn --json market search 贵州茅台
uv run sn schedule list
uv run sn schedule logs --tail 20
```

代码搜索使用 `rg`：

```bash
rg -n "PATTERN" src tests docs README.md
```

## 需要明确授权的命令

这些命令会打真实 API、消耗 LLM/Tushare 额度，或改写本地运行数据；除非用户明确要求，不要主动运行：

```bash
uv run sn fetch ...
uv run sn analyze classify|extract|opinion|report|pipeline ...
uv run sn analyze backtest ...
uv run sn market init
uv run sn market price <code> --start YYYYMMDD --end YYYYMMDD
uv run sn llm test|chat ...
uv run sn schedule tick
uv run sn schedule run <job-id>
```

配置写入也要谨慎，尤其不要在日志或回复中暴露 token：

```bash
uv run sn llm add ...
uv run sn market set-token <TUSHARE_TOKEN>
uv run sn config set ...
```

## 高风险边界

- 不要输出大段原始微信消息；必要引用压到几十字内。
- 不要打印、复制或提交 `~/.config/stock-news/config.yaml`、`tushare_token`、`market.db`。
- 不要删除 `~/.config/stock-news/data/<date>/` 下的阶段目录，除非用户确认具体日期和阶段。
- `LLMProviderConfig.max_tokens` 默认应保持 `None`；不要补成固定数值，避免批量 JSON 被截断。
- LLM 限速、429 退避在 `common/llm/client.py` 内统一处理，业务层不要绕过客户端直连 OpenAI。
- `classify`、`extract`、`opinion` 都有增量 `processed_ids` 语义；重跑前先判断是否能局部补跑。
- `sn fetch` 使用切片缓存 `raw/.fetched.json`；强制重拉用 `--refresh`，不要直接删缓存清单。
- 已用于汇报的 `backtest/` 与 `backtest_summary/` 重算前先让用户确认是否备份。

## 代码修改指引

- `cli.py` 只接 click 参数和转发，不放业务逻辑。
- 共享结构放 `models.py`；改字段要同步检查所有 `commands/`。
- 数据目录和路径约定走 `common/storage.py`，不要硬编码绝对路径或日期。
- Prompt 模板优先改 `common/llm/prompts.py`；提醒用户本地 `~/.config/stock-news/prompts/` 覆盖可能需要同步。
- 新依赖必须更新 `pyproject.toml` 并跑 `uv sync` 确认 lock。
- 面向用户输出保持中文。

## 验证

代码改动后按风险选择验证：

```bash
uv run ruff check src/
uv run ruff format --check src/
uv run mypy src/stock_news/
uv run pytest
```

如果没有运行真实 pipeline，不要声称已重新拉取数据、重新分析或重新生成报告；明确说明未运行的命令和原因。
