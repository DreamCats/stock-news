# 策略快报 Workflow 设计

## 目标

老板目标不是“每天生成一份报告”，而是盘中 `09:00-23:00` 每 20 分钟收到一次可行动的策略快报。

策略快报需要回答：

- 这 20 分钟有什么新增机会？
- 哪些标的或方向出现多人共识？
- 哪些观点发生强化、修正、反转或分歧？
- 相关推荐人近 30 天表现如何，可信度够不够？
- 当前最值得优先看的 3-5 个标的是什么，风险是什么？

## 命令边界

### analyze

`sn analyze` 负责把消息变成结构化事实。

- `classify`：消息分类，增量处理。
- `extract`：推荐抽取，增量处理。
- `opinion`：观点链归并，增量处理；只判断推荐人观点如何变化，不做推荐人可信度评分。
- `backtest`：生成单日推荐回测明细。
- `backtest refresh`：扫描近 N 天推荐，补齐已经成熟的 T+1/T+2/T+3/T+5/T+10 窗口。
- `backtest summary`：汇总近 N 天推荐人表现。

`opinion` 不消费 `backtest summary`。观点链只关心“这个推荐人现在说了什么、和他之前说法相比发生了什么变化”。

### strategy

新增 `sn strategy generate`，负责生成老板看的策略快报。

建议命令：

```bash
sn strategy generate --date today --window-minutes 20 --top 5
```

默认行为：

- 读取已有 `backtest_summary/sender_stats.json`。
- 读取 recommendations、opinions、sender_stats。
- 生成中间策略结构 `strategy/strategy.json`。
- 生成可投递内容 `strategy/strategy.md`。
- 默认不调用 LLM；加 `--with-llm` 后，只把压缩后的 Top N 候选送给 LLM 做强推逻辑链。

不建议 `strategy generate` 默认运行回测刷新，因为它可能拉行情数据、耗时更长。这个重活由 workflow 显式编排。

### delivery

`sn delivery` 只负责把已有内容发到渠道，不理解投研业务。

示例：

```bash
sn delivery send --route boss --markdown-file ~/.config/stock-news/data/2026-05-25/strategy/strategy.md
```

## 20 分钟 Workflow

盘中每 20 分钟执行一轮：

```text
fetch
→ classify
→ extract
→ opinion
→ backtest refresh --as-of today --window-days 30
→ backtest summary --window-days 30
→ strategy generate
→ delivery send
```

当前入口：

```bash
sn workflow run --date today --window-minutes 20
sn workflow run --execute --delivery-route boss
sn workflow status --date today
```

`workflow run` 默认 dry-run；加 `--execute` 后才执行真实 API / LLM / 行情 / delivery。
不传 delivery 参数时只生成策略快报。

其中：

- `fetch` 用当天窗口加去重，避免漏消息。
- `classify/extract/opinion` 都应按 `message_id` 增量处理。
- `backtest refresh` 补齐过去 30 天推荐里已经成熟的 T+N 窗口；当天推荐通常没有 T+1 结果，只进入策略候选和盘中跟踪，不进入完整回测。
- `backtest summary` 刷新近 30 天推荐人统计。
- `strategy generate` 读取已有推荐人统计并生成快报。
- `delivery` 发送 markdown 产物。

如果本轮没有新增推荐或观点变化，`strategy` 应输出 `has_updates=false`。workflow 可以选择不发送，或发送极短的“本轮无新增有效推荐”。

## Strategy 输入

`strategy generate` 消费这些文件：

```text
~/.config/stock-news/data/<date>/extracted/recommendations.json
~/.config/stock-news/data/<date>/opinions/opinions.json
~/.config/stock-news/data/backtest_summary/sender_stats.json
```

可选输入：

- 当天 raw messages：只用于短引用或追溯，不大段送给 LLM。
- 行情数据：用于判断推荐标的是否已经大幅上涨、是否仍有观察价值。

## 程序先做的确定性聚合

LLM 不直接吃全量文件。程序先聚合出高价值候选集：

- 本轮新增推荐：按 `message_id` 或 strategy state 对比上一轮。
- 标的共识：按 `target_type + target_name` 聚合推荐人数、推荐人、动作、强度、置信度、最新时间。
- 推荐人可信度：关联近 30 天样本数、T+5 胜率、平均收益、超额收益。
- 观点变化：从 opinions 中提取 `new/reinforce/revise/reverse/withdraw`。
- 分歧：同一标的/主题出现相反动作或 stance。
- 候选排序：共识人数、推荐强度、抽取置信度、推荐人可信度、新鲜度、观点变化权重。
- 可交易候选：只从 `target_type=stock` 的推荐中选出。
- 主题/板块线索：`sector/theme/macro` 单独输出，不参与个股回测和交易候选排名。

## Score 与 Confidence 口径

`strategy` 当前不调用 LLM 做最终排序。每个标的或主题先按
`target_type + target_name` 聚合，再用确定性规则计算 `score` 和
`confidence`。

### confidence

`confidence` 表示抽取层对该标的/主题的结构化置信度。聚合时取同一目标下
所有推荐的平均值：

```text
confidence = avg(recommendation.confidence)
```

它不是投资胜率，也不是上涨概率，只代表“这条消息被抽成该标的/主题和动作”的可靠程度。

### score

`score` 用于在同一轮快报内排序，核心是“多人共识 + 推荐人历史质量”：

```text
score =
  推荐人数量 * 20
  + 推荐人历史质量均值
  + 推荐强度分
  + confidence * 10
```

推荐人历史质量：

```text
sender_quality =
  T+5 胜率 * 30
  + min(近 30 天样本数, 10) * 1.5
  + T+5 平均超额收益 * 100
```

推荐强度分：

```text
高/强/strong = 18
中/medium = 10
低/弱/low = 4
其他 = 8
```

解释口径：

- 多人共识权重最高，每多一位推荐人加 20 分。
- 推荐人历史胜率、样本数、平均超额收益会影响排序。
- 推荐强度只做辅助加权，避免单条“强推”压过多人共识。
- `confidence` 最多贡献 10 分，只用于降低低置信抽取的排序权重。
- `score` 是本轮线索优先级，不是收益预测，也不是买卖建议。

输出中间结构：

```json
{
  "date": "2026-05-25",
  "window": {"minutes": 20},
  "has_updates": true,
  "candidate_trades": [],
  "theme_clues": [],
  "consensus": [],
  "opinion_changes": [],
  "conflicts": [],
  "sender_stats": {}
}
```

## 送给 LLM 的内容

LLM 输入是压缩后的 strategy payload，而不是原始文件全文。

当前让 LLM 先做策略主线，再做强推逻辑解释：

- `strategy_view.market_summary`：今日最重要的主线，以及为什么这些线索集中出现。
- `strategy_view.mainlines`：主线拆解、相关标的、验证点。
- `strategy_view.priority_targets`：最值得优先看的 2-4 个标的。
- `strategy_view.baskets`：同主题、同证据、同推荐逻辑的标的合并为主题篮子。
- `strategy_view.watchlist`：证据薄、单条推荐、主题跟随的待验证观察。
- `strong_reason`：为什么优先看这个标的。
- `boss_pitch`：写给老板看的连续判断，讲清变化、传导、为什么现在值得看、证伪点。
- `score_driver`：解释排序靠前的结构化原因，而不是复述分数。
- `logic_chain`：变化/触发 → 传导机制 → 为什么可能影响股价或关注度。
- `information_increment`：今天相比普通推荐或历史观点新增了什么。
- `validation_points`：后续验证点。
- `risks`：最可能证伪该逻辑的风险。

排序仍由程序完成，LLM 不改 `score`，也不决定哪些标的进入候选池。不开 `--with-llm` 时，报告使用本地模板从证据、共识、风险字段生成兜底逻辑。

不要让 LLM 负责：

- 重新选股或重排候选。
- 全量去重。
- 计算胜率。
- 判断哪些消息已处理。
- 直接读取原始敏感消息全文。

## Markdown 输出结构

`strategy.md` 建议结构：

```markdown
# 盘中策略快报 HH:MM

## 结论
- 最值得优先看的 3-5 个标的或方向。
- 每个结论说明触发原因和风险。

## 强推逻辑
- 今日主线：先讲本轮最重要的产业或主题变化。
- 主线拆解：说明每条主线为什么重要，以及相关标的。
- 优先关注：只放最值得老板先看的 2-4 个。
- 主题篮子：同主题标的合并展示，说明共同逻辑和差异。
- 待验证观察：证据薄或主题跟随的标的，说明升级需要什么证据。
- 逻辑强度：强 / 中 / 弱 / 待验证。
- 给老板的判断：连续段落，讲清为什么现在值得看。
- 为什么排前：共识、证据、观点变化、推荐人历史表现分别贡献了什么。
- 关键证据：来自原始抽取的短证据。
- 后续验证：接下来跟踪什么。
- 主要风险：什么情况会证伪这个逻辑。

## 新增机会
| 类型 | 标的 | 动作 | 推荐人 | 30d T+5胜率 | 样本 | 证据 | 风险 |
| --- | --- | --- | --- | ---: | ---: | --- | --- |

## 主题/板块线索
- 不参与交易候选和回测，只作为方向观察。

## 共识增强
- 多人推荐、同一推荐人观点强化的标的。

## 观点变化
- 反转、修正、撤退、明显分歧。

## 推荐人可信度
- 只展示本轮涉及推荐人，不铺全量排行榜。

## 风险提示
- 高分歧、样本不足、已大幅上涨、逻辑不完整的标的。
```

## 实施步骤

1. 保持 `opinion` 增量语义：新增推荐才调用 LLM，失败不写 processed。
2. 新增 `strategy` 命令组和 `generate` 子命令。
3. 增加 strategy state，用于识别本轮新增内容和避免重复发送。
4. 实现 `strategy.json` 聚合，不调用 LLM，先让排序和字段可测试。
5. 实现 `strategy.md` 生成，先用模板渲染。
6. 再接入 LLM，对候选集做结论排序和文字归纳。
7. workflow 中串联 `strategy generate` 和 `delivery send`。

## 非目标

- `opinion` 不展示推荐人胜率。
- `delivery` 不做策略判断。
- `strategy generate` 默认不跑 `backtest refresh`。
- 不把 raw message 全文直接送给 strategy LLM。
