# 源头雷达事件驱动落地规划

## 背景

老板关心的不是“消息列表”，而是能否更早发现有交易价值的新概念、新方向和催化事件。

现有 `sn source scan` 已经能从本地微信数据里扫描源头候选，但目前仍偏一次性 TOP 列表。下一步需要把它升级成事件驱动的源头信号流：

```text
raw / classified / extracted
  -> source scan 增量扫描
  -> 源头候选池
  -> 状态流转
  -> 20 分钟提醒 / 半日摘要 / 日终复盘
  -> LLM / ML 离线增强可信度
```

核心目标是回答三个问题：

- 这个东西是不是新？
- 我们是不是足够早看到？
- 它有没有可能从信息变成交易机会？

## 汇报节奏

### 20 分钟扫描

20 分钟是系统扫描频率，不等于每 20 分钟都给老板推一堆内容。

盘中每 20 分钟运行一次增量扫描，只在出现高置信信号时提醒：

- 新概念 / 新方向 / 从 0 到 1 / 预期差 / 催化等强触发词。
- 历史提及很少，具备新鲜度。
- 来源群、发送人、消息形态有一定质量。
- 最好已经关联公司、产业链、政策、订单、产品或个股。
- 如果只是普通周报标题、会议通知、泛行业表达，则进入观察池或降噪。

示例输出：

```text
【源头雷达】电碳协同
时间：2026-05-12 20:25
来源：《金牛会》核心群 / 软硬
判断：新词源头，高新鲜度，暂未带股
依据：出现“新概念”，历史 0 次，后续待观察
建议：进入观察池，后续若出现带股或扩散自动升级
```

### 半日摘要

建议上午和下午各一次，面向老板展示“今天值得盯的池子”：

- 今天新增的新概念。
- 哪些候选开始多群扩散。
- 哪些从“概念”升级到“概念 + 个股”。
- 哪些来源最早、最可信。
- 哪些被判定为噪音或普通旧题材。

半日摘要适合帮助老板决定当天剩余时间重点盯什么。

### 日终复盘

每天收盘后或晚上生成一次复盘：

- 当天最早出现的高价值候选。
- 哪些候选后续被更多群转发。
- 哪些候选出现个股映射。
- 哪些已经盘中反应，哪些可能仍有预期差。
- 哪些误报需要降权。

日终复盘也是 LLM / ML 离线增强的主要输入。

## 状态模型

`scan` 不应只返回 TOP N，而应返回候选的状态变化。

建议状态：

```text
new_source   新概念或新方向首次出现，证据较强
watching     证据不足但值得观察
upgraded     后续出现带股、多群扩散或强催化
confirmed    多证据确认，可信度较高
dismissed    噪音、旧题材、普通周报或低质量表达
```

状态流转示例：

```text
new_source -> watching -> upgraded -> confirmed
watching   -> dismissed
new_source -> dismissed
```

老板最值得被打扰的是 `new_source` 和 `upgraded`：

- `new_source` 代表足够早。
- `upgraded` 代表早期信号开始被验证。

## 数据与证据

实时链路的可信度不能只靠 LLM 判断，应先由确定性证据支撑。

候选需要沉淀这些字段：

```text
term               概念或方向
status             当前状态
confidence         可信度分数
novelty_level      新鲜度
first_seen         首次出现时间
first_group        首次出现群
first_sender       首次发送人
first_message_id   首次消息 ID
first_stock_seen   首次带股时间
stock_names        关联个股
previous_mentions  历史提及次数
later_mentions     后续扩散次数
later_groups       后续覆盖群数
later_senders      后续覆盖发送人数
triggers           触发词
evidence           可解释依据
```

可信度主要来自：

- 新鲜度：历史是否少见。
- 触发词：是否有强源头表达。
- 来源质量：群、发送人、消息类型是否可信。
- 结构质量：是否包含产业链、政策、产品、订单、公司、个股。
- 扩散验证：后续是否被更多群、人、消息形态验证。
- 市场验证：后续是否进入推荐、行情或策略快报候选。

## 命令规划

### 增量扫描

```bash
sn source scan --since-minutes 20
```

行为：

- 只扫描最近窗口的新消息。
- 结合历史数据判断新鲜度。
- 返回本轮新增和状态变化。
- 默认不调用 LLM，不拉外部 API。

### 持续扫描

```bash
sn source watch --interval-minutes 20
```

行为：

- 周期性运行增量扫描。
- 根据本地状态判断是否需要输出提醒。
- 后续可接 delivery，但 source 本身不直接负责投递。

### 半日摘要

```bash
sn source summary --period morning
sn source summary --period afternoon
```

行为：

- 读取本日源头状态池。
- 聚合新增、升级、确认和剔除的候选。
- 输出适合老板快速阅读的摘要。

### 日终复盘

```bash
sn source review --date 2026-05-13
```

行为：

- 回看当天源头候选。
- 汇总后续扩散、带股、市场反馈。
- 标记误报和有效信号。
- 为离线 LLM / ML 增强准备数据。

### 离线数据集

```bash
sn source export-dataset --start 2026-05-01 --end 2026-05-31
sn source judge --date 2026-05-13
```

行为：

- 导出历史候选和证据链。
- 供人工、LLM 或 ML 打标签。
- 标签结果反哺实时扫描的可信度评分。

## 本地状态存储

建议新增 source 独立状态目录：

```text
~/.config/stock-news/source/
├── state.json
├── events.jsonl
└── datasets/
```

`state.json` 保存当前候选池、水位和状态：

```json
{
  "last_scan_at": "2026-05-13T15:20:00",
  "terms": {
    "电碳协同": {
      "status": "watching",
      "confidence": 0.72,
      "first_seen": "2026-05-12T20:25:57",
      "last_seen": "2026-05-12T20:25:57"
    }
  }
}
```

`events.jsonl` 记录每次状态变化，方便复盘和训练：

```json
{"time":"2026-05-12T20:25:57","term":"电碳协同","event":"new_source","confidence":0.72}
{"time":"2026-05-13T09:45:00","term":"电碳协同","event":"upgraded","reason":"出现带股"}
```

## LLM / ML 定位

LLM 和 ML 不应该成为 20 分钟实时链路的强依赖。

合理分工：

- 实时 scan：规则、统计、历史频次、来源质量，保证快、稳、可解释。
- 离线 LLM：帮忙判断语义质量、概念边界、噪音类型、标签建议。
- 离线 ML：根据历史标签学习权重，优化实时 confidence。

优先做离线增强，而不是一开始就把每条消息送给 LLM。

## 分阶段落地

### 第一阶段：增量扫描

实现：

- `sn source scan --since-minutes 20`
- 返回本轮候选和状态建议。
- 保持现有全量时间段扫描能力。

验收：

- 能在已有本地数据上按最近窗口扫描。
- 能结合历史数据判断 `previous_mentions`。
- 不调用外部 API。

### 第二阶段：候选池与状态流转

实现：

- `~/.config/stock-news/source/state.json`
- `~/.config/stock-news/source/events.jsonl`
- `new_source / watching / upgraded / confirmed / dismissed` 状态。

验收：

- 同一个概念跨多轮扫描不会重复打扰。
- 新增带股或多群扩散时能产生 `upgraded` 事件。
- 噪音候选能降权或剔除。

### 第三阶段：分层汇报

实现：

- `sn source summary --period morning|afternoon`
- `sn source review --date <date>`

验收：

- 半日摘要能展示观察池变化。
- 日终复盘能回看源头、扩散、带股和误报。

### 第四阶段：离线增强

实现：

- `sn source export-dataset`
- `sn source judge`
- 人工或 LLM 标签格式。

验收：

- 能导出可标注样本。
- 能把标签回灌到评分策略。
- 实时扫描仍能在无 LLM 情况下运行。

## 近期优先级

建议下一步先做：

1. `scan --since-minutes 20`
2. source 状态池
3. `upgraded` 事件识别

这三步完成后，系统就从“一次性扫描列表”升级为“持续观察源头信号”，后续再接摘要、复盘和离线增强会更顺。
