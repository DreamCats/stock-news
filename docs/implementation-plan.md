# stock-news CLI 分阶段实施计划

## 总览

```
P0 骨架+采集 → P1 LLM+分析 → P2 行情+回测 → P3 报告+发布 → P4 定时调度 → P5 Channel推送
```

每阶段结束时都有可验证的交付物，可以随时停下来给老板演示。

---

## P0：项目骨架 + 数据采集（1-2 天）

### 目标

`sn` 命令能用，能拉微信 API 消息并存到本地，Agent 能通过 `--json` 调用。

### 任务

| # | 任务 | 验证方式 |
| --- | --- | --- |
| 1 | `pyproject.toml` + `src/stock_news/` 目录结构 + `sn` 入口 | `uv run sn --version` 正常输出 |
| 2 | `common/config.py` + `~/.config/stock-news/config.yaml` | `sn config show` 正常输出 |
| 3 | `sn config set` 修改配置项 | `sn config set api.timeout 60` 后 `sn config show` 确认生效 |
| 4 | `common/wechat_api.py` 微信 API 客户端 | 单元测试 mock API 通过 |
| 5 | `sn fetch --source 个人消息 --last 30m` | 本地 `~/.stock-news/data/<date>/raw/` 下生成 JSON |
| 6 | `sn fetch` 写入去重（sha256 hash） | 重复执行 fetch，消息数不翻倍 |
| 7 | `sn data stats --date today` | 输出当日消息数、来源分布、时间范围 |
| 8 | `sn data list --date today --source 个人群` | 输出消息列表 |
| 9 | `sn data dedup --date today --dry-run` | 输出重复消息数 |
| 10 | 所有命令支持 `--json` | `sn --json data stats` 返回合法 JSON |

### 交付物

- `sn` 可安装可运行。
- 微信 API 数据能稳定拉取并去重存储。
- Agent 能通过 `sn --json fetch/data` 完成数据采集链路。

### 依赖

- 确认微信 API 地址可用（`https://example.com/api`）。

---

## P1：LLM 集成 + 消息分析（2-3 天）

### 目标

接入 OpenAI 兼容 LLM，能对消息做分类、推荐抽取和观点链归并。

### 任务

| # | 任务 | 验证方式 |
| --- | --- | --- |
| 1 | `common/llm/client.py` OpenAI 兼容客户端 | `sn llm test` 返回模型响应 |
| 2 | `common/llm/providers.py` 多 provider 管理 | `sn llm add deepseek --base-url ... --api-key ...` 后 `sn llm list` 显示 |
| 3 | `common/llm/prompts.py` prompt 模板加载 | 模板文件存在，渲染输出正确 |
| 4 | `~/.config/stock-news/prompts/classify.txt` 分类 prompt | 手动检查 prompt 合理 |
| 5 | `sn analyze classify --date today` | `classified/` 下生成分类结果，每条消息有 category + confidence |
| 6 | `sn analyze classify --date today --no-llm` | 规则降级模式正常运行 |
| 7 | `~/.config/stock-news/prompts/extract.txt` 抽取 prompt | 手动检查 prompt 合理 |
| 8 | `sn analyze extract --date today` | `extracted/recommendations.json` 生成，字段完整 |
| 9 | `~/.config/stock-news/prompts/opinion.txt` 观点链 prompt | 手动检查 prompt 合理 |
| 10 | `sn analyze opinion --date today` | 观点链数据生成，同一推荐人+标的能归并 |
| 11 | `sn analyze show --date today` | 输出今日分析摘要（分类分布 + 推荐列表 + 观点变化） |
| 12 | LLM task_routing 配置生效 | 不同任务使用配置指定的 provider |

### 交付物

- LLM 分类准确率初步可用（目标 >80%）。
- 结构化推荐数据能被 Agent 和下游命令消费。
- 观点链归并能识别同一推荐人对同一标的的立场变化。

### 依赖

- 至少一个 OpenAI 兼容 LLM 服务可用（推荐先用 DeepSeek）。
- P0 采集的数据已有一定量（至少一个交易日的消息）。

### 关键决策

- 分类 prompt 需要根据实际消息样本反复调优，第一版先跑通链路再迭代。
- 标的识别（模糊公司名 → 股票代码）第一版用 LLM 做，后续考虑本地股票代码词典加速。

---

## P2：行情数据 + 回测（2-3 天）

### 目标

接入行情数据，能计算推荐后 N 日表现，产出推荐人胜率和评分。

### 任务

| # | 任务 | 验证方式 |
| --- | --- | --- |
| 1 | `common/market.py` efinance 行情客户端 | `sn market price 600519 --days 5` 返回贵州茅台近 5 日行情 |
| 2 | 行情本地缓存（按 ticker+date 缓存） | 第二次查询同一标的不再请求远程 |
| 3 | `sn market fetch-recommendations --date today` | 自动读取 extracted 推荐，批量拉取所有涉及标的行情 |
| 4 | `sn market backtest --date 2026-05-20` | 输出该日推荐的 1/3/5/10/20 日收益、最大回撤、是否命中 |
| 5 | `sn market score --json` | 输出所有推荐人的胜率、平均收益、盈亏比、擅长板块、综合评分 |
| 6 | `sn market score --sender 某推荐人 --json` | 输出单人详细画像 |
| 7 | tushare provider 预留（`--provider tushare`） | 代码里有 tushare 分支，无 token 时给出明确提示 |

### 交付物

- 推荐后多周期收益可量化。
- 推荐人胜率榜和画像数据可用。
- Agent 能通过 `sn market score --json` 获取评分结果。

### 依赖

- P1 的结构化推荐数据（需要有 ticker 字段）。
- 推荐数据需积累至少数个交易日，回测才有意义。

### 关键决策

- efinance 免费先用，速度不够再让老板开 tushare（TODO 已标记）。
- 胜率判定阈值初始设 2%（`win_threshold: 0.02`），后续可按老板反馈调。
- 回测周期 1/3/5/10/20 日，覆盖日内到波段。

---

## P3：报告生成 + 发布（1-2 天）

### 目标

把分析和回测结果变成老板能看的页面，能一键发布到阿里云。

### 任务

| # | 任务 | 验证方式 |
| --- | --- | --- |
| 1 | `sn report generate --date today --format html` | 生成今日推荐池 HTML，浏览器打开样式正常 |
| 2 | `sn report generate --date today --format json` | 生成结构化数据 JSON |
| 3 | `sn report senders --json` | 输出推荐人排行榜数据 |
| 4 | HTML 页面包含：今日推荐池、推荐人排行、观点链变化、原文追溯链接 | 手动检查页面内容完整 |
| 5 | LLM 生成今日投研简报摘要 | 页面顶部有 AI 简报 |
| 6 | `sn report publish --date today` | 文件上传到阿里云，浏览器可访问 |
| 7 | 阿里云 Nginx 配置 + Basic Auth | 访问需要密码 |

### 交付物

- 老板手机能打开链接看到今日推荐池和推荐人排行。
- 页面包含回测数据、胜率、原文追溯。

### 依赖

- 阿里云 ECS IP、SSH 权限、Nginx 已安装。
- P2 的回测和评分数据。

---

## P4：定时调度（1-2 天）

### 目标

日常采集、分析、生成、发布全链路自动化运行。

### 任务

| # | 任务 | 验证方式 |
| --- | --- | --- |
| 1 | `sn schedule add --name "早盘采集" --cron "30 9 * * 1-5" -- sn fetch --source all --last 60m` | `sn schedule list` 显示任务 |
| 2 | `sn schedule daemon start` | 守护进程启动，PID 文件写入 |
| 3 | `sn schedule daemon status --json` | 返回进程状态、已注册任务数 |
| 4 | 任务按 cron 触发执行 | 查看日志确认执行 |
| 5 | `sn schedule logs <id> --lines 20` | 输出最近执行日志 |
| 6 | `sn schedule remove/enable/disable` | 任务管理操作生效 |
| 7 | `sn schedule export-cron` 备选 | 输出 crontab 格式 |

### 交付物

- 注册以下日常任务链：

```
09:30  sn fetch --source all --last 60m        # 早盘消息采集
11:35  sn fetch --source all --last 125m       # 上午盘消息补采
13:05  sn analyze classify --date today        # 午间分析
15:05  sn fetch --source all --last 125m       # 下午盘消息补采
15:10  sn analyze classify --date today        # 全天分析
15:15  sn analyze extract --date today         # 推荐抽取
15:20  sn market fetch-recommendations --date today  # 拉行情
15:25  sn report generate --date today --format html # 生成报告
15:30  sn report publish --date today          # 发布
15:35  sn notify                               # 推送（P5）
```

### 依赖

- P0-P3 所有命令已可用。

---

## P5：Channel 推送（0.5-1 天）

### 目标

老板不用主动打开页面，收到推送消息就能看到今日摘要和链接。

### 任务

| # | 任务 | 验证方式 |
| --- | --- | --- |
| 1 | `sn notify --channel feishu` | 飞书机器人收到推送消息 |
| 2 | 推送内容包含：重点推荐数、高胜率推荐人动态、多人共振标的、页面链接 | 手动检查消息格式 |
| 3 | 配置 `channel.webhook_url` | `sn config set channel.webhook_url https://...` |
| 4 | 支持飞书 / 企业微信两种 webhook | `sn notify --channel wechat_work` 可用 |

### 交付物

- 每日收盘后老板自动收到投研简报推送。

### 依赖

- 飞书或企微机器人 webhook URL。
- P3 的报告已发布到阿里云。

---

## 里程碑对照

| 里程碑 | 对应阶段 | 老板能看到什么 |
| --- | --- | --- |
| **能采数据** | P0 完成 | "系统能自动抓消息了" |
| **能看分析** | P1 完成 | "消息被分类了，推荐被结构化了" |
| **能看胜率** | P2 完成 | "知道谁历史准不准了" |
| **能看页面** | P3 完成 | "手机打开链接就能看今日推荐池" |
| **全自动** | P4 完成 | "不用手动跑了，每天自动出结果" |
| **自动推送** | P5 完成 | "飞书/微信直接收到简报" |

## 时间估算

| 阶段 | 估时 | 累计 |
| --- | --- | --- |
| P0 骨架+采集 | 1-2 天 | 1-2 天 |
| P1 LLM+分析 | 2-3 天 | 3-5 天 |
| P2 行情+回测 | 2-3 天 | 5-8 天 |
| P3 报告+发布 | 1-2 天 | 6-10 天 |
| P4 定时调度 | 1-2 天 | 7-12 天 |
| P5 Channel推送 | 0.5-1 天 | 8-13 天 |

P0-P1 完成后（约 3-5 天）就可以给老板演示第一版效果。
