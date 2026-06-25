# 源头雷达当前设计方案

更新时间：2026-06-03

这份文档说明当前源头雷达到底在解决什么问题、怎么跑、模型怎么判断、最终产物每个指标是什么意思。它不是旧方案草案，而是当前代码和本机定时任务的实际口径。

## 1. 目标

源头雷达不是热点榜，也不是“今天群里聊了什么”的摘要。

它要回答三个问题：

1. **是不是新？**
   这个表达在本地历史语料里到底冷不冷。不是看单词新不新，而是看“成熟锚点 + 陌生修饰”的组合新不新。

2. **是不是够早？**
   我们是在它刚出现、还没大范围扩散时看到的吗。

3. **会不会变成交易机会？**
   后面有没有别人接力、跨群扩散，或者落到个股。

老板要的信号可以概括为：

```text
成熟产业链词后面，紧跟一个大家没怎么听过的新表达。
```

例如：

```text
PCB 是成熟锚点。
半导体化 是陌生修饰。
半导体化的 PCB 是组合信号。
```

如果 09:14 第一次出现，这是“源头种子”。如果 12:00 已经多群扩散，这是“扩散验证”。如果后面开始带股票，就是“个股映射”。

## 2. 总体链路

当前链路分成四段：

```text
raw 原始消息
  -> analyze classify
  -> source extract
  -> source scan
  -> markdown 推送
```

各阶段职责不同：

| 阶段 | 是否调用 LLM | 作用 |
| --- | --- | --- |
| `raw` | 否 | 微信 API 拉回来的原始消息 |
| `analyze classify` | 是 | 把消息分成 research / event / recommendation / noise 等 |
| `source extract` | 是 | 从 research/event 里拆出“锚点 + 修饰词 + 组合表达” |
| `source scan` | 否 | 查本地历史、算新颖度、早期度、扩散、个股映射 |
| `delivery` | 否 | 推送 scan 生成的 Markdown |

核心原则：

- LLM 只负责“拆结构”，不负责判断新不新。
- 新颖度、早期度、扩散、映射都由本地历史和截至 `as_of` 的真实数据计算。
- `scan` 是 0 token 的本地计算。

## 3. 为什么要先 classify

`source extract` 不直接吃所有 raw。它先看 classified，只处理：

- `research`
- `event`

这样做是为了减少垃圾输入。`recommendation` 通常已经带股票，偏交易推荐，不适合当“源头新概念”的第一入口。

如果当天只有 raw、没有 `classified/classified.json`，`source extract` 会直接提示：

```bash
sn analyze classify --date <date>
```

不会再静默跳过。

## 4. source extract 怎么做

命令：

```bash
uv run sn source extract --date today
```

它的输入：

```text
~/.config/stock-news/data/<date>/raw/
~/.config/stock-news/data/<date>/classified/classified.json
```

它的输出：

```text
~/.config/stock-news/data/<date>/source_extract/structures.json
~/.config/stock-news/data/<date>/source_extract/structures_processed_ids.json
```

处理流程：

1. 读取当天 raw。
2. 读取当天 classified。
3. 只保留 `research/event`，且分类置信度达到阈值。
4. 程序先过滤明显噪音，例如会议通知、报名、日报、周报。
5. 程序再找“可能有新表达”的消息，例如含有：
   - 新概念
   - 新方向
   - 从 0 到 1
   - 预期差
   - 突破
   - 替代
   - 半导体化
6. 按 10 条一批，并发调用 LLM。
7. LLM 只输出能回指原文的结构字段。
8. 每批完成后立即落盘，任务中断后可以增量续跑。

当前 source extract 的 LLM provider pool：

```text
xiaomi-anthropic
kimi-anthropic
glm-coding-plan
minimax
```

其中 `minimax` 当前模型为：

```text
MiniMax-M3
```

## 5. structures.json 字段

`structures.json` 里的每条结构大致长这样：

```json
{
  "message_id": "...",
  "source": "个人群",
  "sender": "祁丽媛",
  "message_time": "2026-05-11T09:14:49",
  "group_name": "🌈交银基金重点推荐",
  "is_candidate": true,
  "anchor_span": "PCB",
  "modifier_span": "半导体化",
  "novel_span": "半导体化的PCB",
  "relation_type": "A化B",
  "relation_evidence": "正在半导体化的PCB",
  "ask_question": "PCB如何实现半导体化？",
  "confidence": 0.9,
  "reject_reason": null,
  "llm_provider": "xiaomi-anthropic"
}
```

字段解释：

| 字段 | 含义 |
| --- | --- |
| `message_id` | 原始消息 ID，用来回指证据 |
| `source` | 来源类型，例如个人群、个人消息 |
| `sender` | 发送人 |
| `message_time` | 消息时间 |
| `group_name` | 群名 |
| `is_candidate` | LLM 是否认为这条有源头结构 |
| `anchor_span` | 成熟锚点，例如 PCB、CPU、陶瓷基板 |
| `modifier_span` | 陌生修饰，例如 半导体化、OAM 变革方向 |
| `novel_span` | 原文中的组合表达 |
| `relation_type` | 锚点和修饰之间的关系类型 |
| `relation_evidence` | 原文里能证明关系的片段 |
| `ask_question` | 看到这个信号后可以问大佬的问题 |
| `confidence` | LLM 对结构抽取的置信度 |
| `reject_reason` | 如果不是候选，说明为什么拒绝 |
| `llm_provider` | 哪个模型抽出来的 |

注意：`source extract` 不判断“新不新”。它只负责把结构切出来。

## 6. 关系类型

`relation_type` 当前有 5 类：

| 类型 | 例子 | 说明 |
| --- | --- | --- |
| `A化B` | 半导体化的 PCB | 某个行业/技术正在被另一种属性改造 |
| `prefix-anchor` | CIPB-PCB | 前缀和成熟锚点组合 |
| `modifier-anchor` | 液态金属液冷板 | 修饰词 + 锚点 |
| `anchor-extension` | Token 消耗变现路径 | 锚点后接延展表达 |
| `other` | - | 其他或不确定 |

`scan` 会做归一。例如：

```text
正在半导体化的PCB
半导体化的PCB
```

都会归一成：

```text
anchor=PCB
modifier=半导体化
novel=半导体化的PCB
relation=A化B
```

## 7. source scan 怎么做

命令：

```bash
uv run sn source scan --date today --top 5
```

回看历史：

```bash
uv run sn source scan \
  --date 2026-05-11 \
  --as-of 2026-05-11T12:00:00 \
  --lookback-days 30 \
  --top 10
```

`scan` 的输入：

```text
~/.config/stock-news/data/<date>/source_extract/structures.json
~/.config/stock-news/data/<date>/raw/
~/.config/stock-news/data/<date>/classified/classified.json
~/.config/stock-news/data/<date>/extracted/recommendations.json
```

其中 `recommendations.json` 只用来判断后续有没有映射到个股。

`scan` 的输出可以直接打印，也可以落 Markdown：

```bash
uv run sn source scan \
  --date today \
  --top 5 \
  --markdown-out ~/.config/stock-news/schedule/source-radar.md
```

处理流程：

1. 确认目标日期有 `source_extract/structures.json`。
2. 加载 `lookback_days` 范围内、截至 `as_of` 的 raw。
3. 加载 classified 和 recommendations。
4. 读取结构候选，只保留：
   - `is_candidate=true`
   - 结构置信度足够
   - anchor / modifier / novel 可用
5. 做 canonical 归一，合并同义表达。
6. 过滤抽象锚点，例如：
   - 拐点
   - 共振
   - 瓶颈
   - 平台
   - 时代
7. 计算历史冷度。
8. 计算截至 `as_of` 的扩散。
9. 计算是否映射个股。
10. 输出三榜单。

## 8. scan 输出三榜单

当前默认输出三类：

```text
源头种子
扩散验证
个股映射
```

### 8.1 源头种子

状态名：

```text
source_seed
```

含义：

这个组合还处在早期。它不一定已经能交易，但值得拿去问人。

典型特征：

- 成熟锚点历史出现过。
- 组合本身历史很少出现。
- 截至 `as_of` 还没有大范围扩散。
- 暂时没有明显个股映射。

老板看到这一类，重点不是问“买什么”，而是问：

```text
这个新表达是不是真的有产业变化？
谁最懂？
哪些公司会受益？
市场还没意识到什么？
```

### 8.2 扩散验证

状态名：

```text
spreading_watch
```

含义：

源头信号已经开始被别人接力，或者跨群扩散。它正在从“值得问”变成“可能要盯交易”。

当前判断条件：

```text
followup_groups >= 3
或
followup_senders >= 2
```

解释：

- `followup_groups >= 3`：首现之后，至少 3 个群继续出现。
- `followup_senders >= 2`：首现之后，至少 2 个不同发送人接力。

注意：同一个人多群转发也算扩散，但不等于“独立多人验证”。所以要同时看 `followup_senders` 和 `followup_groups`。

### 8.3 个股映射

状态名：

```text
mapped
```

含义：

这个组合已经和股票推荐或个股逻辑发生关联。

进入这个状态，说明它可能已经从“概念/问题”走向“交易机会”。

但也要警惕：一旦大量带股，可能已经不够早。

## 9. status 判断逻辑

当前状态优先级：

```text
old_theme
mapped
spreading_watch
source_seed
```

判断规则：

| 状态 | 条件 | 含义 |
| --- | --- | --- |
| `old_theme` | `prior_combo > 8` | 历史组合已经多次出现，偏老主题 |
| `mapped` | 有 `mapped_stocks` | 已经映射个股 |
| `spreading_watch` | `followup_groups >= 3` 或 `followup_senders >= 2` | 已开始扩散验证 |
| `source_seed` | 其他可行动候选 | 早期源头种子 |

当前默认输出不展示 `old_theme`。

## 10. 核心指标解释

### 10.1 结构字段

| 指标 | 说明 | 怎么看 |
| --- | --- | --- |
| `signal_id` | 唯一信号 ID，通常是 `anchor::relation::modifier` | 用来识别同一个组合 |
| `anchor_span` | 成熟锚点 | 应该是产业链、产品、材料、技术、工艺等 |
| `modifier_span` | 陌生修饰 | 应该是新解法、新属性、新路径、新场景 |
| `novel_span` | 展示用新组合 | 最终榜单里的“新组合” |
| `relation_type` | 组合关系 | `A化B` 通常价值较高 |

### 10.2 历史冷度指标

| 指标 | 说明 | 解读 |
| --- | --- | --- |
| `prior_anchor_mentions` | as_of 前，锚点出现次数 | 高说明锚点成熟；太低说明锚点本身可能不是成熟产业词 |
| `prior_modifier_mentions` | as_of 前，修饰词出现次数 | 低说明修饰词相对新 |
| `prior_exact_mentions` | as_of 前，完整组合出现次数 | 越低越新 |
| `prior_combo_mentions` | as_of 前，同一锚点和修饰词共同出现次数 | 越低越新；大于 8 会降为 old_theme |

例子：

```text
PCB 出现 1869 次
半导体化 出现 17 次
半导体化的 PCB 完整组合出现 0 次
PCB + 半导体化 共同出现 4 次
```

这说明：

- PCB 是成熟锚点。
- 半导体化不是完全没出现过。
- 但 “PCB + 半导体化” 这个组合仍然很新。

### 10.3 as_of 扩散指标

| 指标 | 说明 | 解读 |
| --- | --- | --- |
| `asof_mentions` | 首现到 as_of 出现次数 | 多说明开始热 |
| `asof_groups` | 首现到 as_of 出现群数 | 多说明跨群扩散 |
| `asof_senders` | 首现到 as_of 发送人数 | 多说明不是单人刷屏 |
| `followup_groups` | 首现之后继续出现的群数 | 看接力扩散 |
| `followup_senders` | 首现之后继续出现的发送人数 | 看独立接力 |
| `mapped_stocks` | 后续映射到的个股 | 看交易落点 |

注意：这些指标只看截至 `as_of` 已经发生的数据。当天 10 点跑，不会假装知道 T+3/T+5。

### 10.4 分数指标

当前有 4 个分数：

| 指标 | 范围 | 说明 |
| --- | --- | --- |
| `novelty_strength` | 0-1 | 新颖度 |
| `earliness_score` | 0-1 | 早期度 |
| `askability_score` | 0-1 | 值不值得拿去问 |
| `trade_potential_score` | 0-1 | 是否出现交易化迹象 |

#### novelty_strength

衡量组合新不新。

它主要受这些因素影响：

- 完整组合历史出现越多，分越低。
- 锚点 + 修饰词共同出现越多，分越低。
- 锚点本身完全没历史，也会扣分，因为这可能不是成熟锚点。

#### earliness_score

衡量现在还早不早。

当前规则：

| 情况 | 早期度 |
| --- | --- |
| 还很少出现 | 1.0 |
| 已出现 3 次以上 | 0.75 |
| 已扩散到 3 个群以上 | 0.55 |
| 已扩散到 5 个群以上 | 0.35 |

所以早期度不是越热越高。越热说明越可能已经晚了。

#### askability_score

衡量老板看到后值不值得问。

它综合：

```text
新颖度
早期度
消息质量
```

消息质量包括：

- 是否 research/event。
- 是否含有新方向、预期差、突破、替代等线索。
- 消息是否短而清楚。

#### trade_potential_score

衡量交易化迹象。

它主要看：

- 有没有多人接力。
- 有没有多群扩散。
- 有没有映射个股。

映射个股后，交易潜力分会明显提高。

### 10.5 总分 score

`score` 是排序用，不是价值判断本身。

它大致由三部分组成：

```text
score = askability_score * 60
      + trade_potential_score * 25
      + 群扩散加分
```

含义：

- 先保证“值得问”。
- 再考虑有没有交易化迹象。
- 最后给一定扩散加分。

## 11. Markdown 输出产物

当前定时任务会生成：

```text
~/.config/stock-news/schedule/source-radar.md
```

scan 也可以写到日期目录：

```text
~/.config/stock-news/data/<date>/source_scan/radar.md
```

Markdown 内容结构：

```text
# 源头雷达 · <date>

- 证据截止
- 历史回看
- 扫描消息数
- 源头候选数

## TOP N

### 源头种子
表格

### 扩散验证
表格

### 个股映射
表格

## 明细
每条候选的详细证据
```

表格字段：

| 字段 | 含义 |
| --- | --- |
| 新组合 | `novel_span` |
| 结构 | `anchor_span + modifier_span` |
| 新颖度 | `novelty_strength` |
| 早期度 | `earliness_score` |
| as_of 扩散 | `asof_mentions / asof_groups` |
| 接力/个股 | `followup_senders / followup_groups / mapped_stocks` |

## 12. 用 6.3 实际产物读一遍

2026-06-03 手动触发后，系统生成了一份真实推送：

```text
~/.config/stock-news/schedule/source-radar.md
```

当时摘要是：

```text
证据截止：2026-06-03 15:47:39
历史回看：30 天
扫描消息数：41
源头候选数：8
```

这几个数字要这样理解：

| 字段 | 这次的值 | 怎么理解 |
| --- | --- | --- |
| 证据截止 | 15:47:39 | 只看这个时间之前已经发生的消息 |
| 历史回看 | 30 天 | 判断新旧时，往前查 30 天本地语料 |
| 扫描消息数 | 41 | 当天截至 as_of，真正进入 source scan 的结构消息数 |
| 源头候选数 | 8 | 最后认为值得展示的组合信号数 |

### 12.1 先把指标名翻译成人话

看一条候选时，先不要被字段名吓住。它其实只是在回答几个朴素问题。

以下用 6.3 的 `AI时代连接性瓶颈` 这一条举例：

```text
新组合：AI时代连接性瓶颈
结构：连接性 + AI时代
新颖度：1.0
早期度：1.0
as_of 扩散：2次/2群

明细：
anchor=连接性
modifier=AI时代
历史：anchor 8 次，modifier 461 次，exact 0 次，combo 0 次
as_of：2次/2群/1人；接力 1人/1群
```

逐个字段解释：

| 字段 | 例子里的值 | 人话解释 | 该怎么判断 |
| --- | --- | --- | --- |
| `anchor` | 连接性 | 被修饰的成熟锚点，通常是产业、技术、产品、材料、环节 | 这里的锚点不算特别强，因为 30 天只出现 8 次 |
| `modifier` | AI时代 | 加在锚点前面的新修饰、新场景、新解法 | 这个修饰很常见，历史 461 次，不是新词 |
| `novel_span` | AI时代连接性瓶颈 | 榜单展示的新组合，来自原文表达 | 不一定是正式概念名，更像“待问表达” |
| `exact` | 0 | 完整组合过去出现过几次 | 0 说明这句话本身过去没出现过 |
| `combo` | 0 | anchor 和 modifier 在同一条历史消息里共同出现过几次 | 0 说明“连接性 + AI时代”这个搭配过去没出现过 |
| `as_of` | 2次/2群/1人 | 从首现到证据截止，已经出现几次、几个群、几个人 | 2群但只有1人，说明可能是同一人多群同步，还不是强验证 |
| `followup` | 1人/1群 | 首现之后的接力情况 | 有一点接力，但很弱 |
| `新颖度` | 1.0 | 组合冷不冷 | exact=0、combo=0，所以非常新 |
| `早期度` | 1.0 | 现在晚不晚 | 只有2次/2群，还没明显刷屏，所以仍然早 |

这条的核心判断不是“AI时代连接性瓶颈”这个词一定值钱，而是：

```text
连接性这个锚点 + AI时代这个场景，在本地历史里第一次清楚组合出现。
现在还没明显扩散。
所以它值得拿去问，但还不能直接当交易结论。
```

再看一条质量较弱的 `业界领先的算力利用率水平`：

```text
anchor=算力利用率水平
modifier=业界领先
历史：exact 6 次，combo 6 次
新颖度：0.22
早期度：0.35
as_of：6次/6群/1人
```

这条为什么弱？

| 字段 | 值 | 说明 |
| --- | --- | --- |
| `exact=6` | 完整表达历史出现 6 次 | 不是第一次出现 |
| `combo=6` | 锚点和修饰历史共同出现 6 次 | 组合也不新 |
| `as_of=6次/6群/1人` | 已经跨 6 个群，但只有 1 个发送人 | 更像同一内容多群转发 |
| `新颖度=0.22` | 很低 | 系统认为它不够新 |
| `早期度=0.35` | 很低 | 已经扩散到多群，不算早 |

所以它虽然出现在 `扩散验证`，但更像一个提醒：

```text
这个说法正在传播，但已经不早，也不够新。
```

后续规则应该考虑降低这种候选的展示优先级。

### 12.2 指标之间的关系

几个指标不要孤立看，要组合看：

| 组合 | 含义 |
| --- | --- |
| `anchor 高 + exact 低 + combo 低` | 典型好信号：老赛道里出现新说法 |
| `anchor 低 + exact 低 + combo 低` | 可能是新东西，也可能只是锚点不成熟，需要人工判断 |
| `exact 高 + combo 高` | 老表达，通常不该当源头 |
| `as_of 少 + 早期度高` | 还早，适合问 |
| `as_of 多 + 早期度低` | 已扩散，可能开始晚 |
| `followup_senders 多` | 多人接力，比单人多群更有价值 |
| `followup_groups 多但 senders 少` | 可能只是同一人多群同步，价值要打折 |
| 有 `mapped_stocks` | 已经落个股，但也可能说明市场开始明牌 |

最理想的源头种子通常长这样：

```text
anchor_mentions 高
modifier_mentions 低或中等
exact_mentions = 0
combo_mentions 很低
asof_mentions 少
asof_groups 少
followup_senders 暂时少
mapped_stocks 暂时无
```

这代表：

```text
老赛道里刚出现一个新表达，还没扩散、还没带股，适合提前问。
```

最理想的扩散验证通常长这样：

```text
之前是 source_seed
现在 followup_senders 增加
followup_groups 增加
exact/combo 仍然不高
mapped_stocks 可能开始出现
```

这代表：

```text
早期看到的东西开始被别人接力，值得继续盯。
```

### 12.3 先说明一个容易误解的点

榜单里的“新组合”不是系统拍脑袋造词。

它来自 LLM 从原文里切出来的 `novel_span`，然后 scan 再做少量归一。也就是说，它是“原文里出现过的表达”，不是系统自己总结出来的新名词。

但这也带来一个问题：有些表达会看起来别扭，例如：

```text
内容+AItoken运营
业界领先的算力利用率水平
适配人工智能智能体的中央处理器
```

这类词不一定是“正式概念名”。它们更像系统抓到的“待问表达”。看到它们时，不应该马上理解成“这就是一个确定题材”，而应该理解成：

```text
这里可能有一个新说法，值得人工判断它是不是有效。
```

当前阶段我们选择完整三榜单推送，就是为了把这些边界样本暴露出来，方便后续调规则。

### 12.4 6.3 源头种子怎么看

6.3 的 `源头种子` 前 5 条是：

| 新组合 | 结构 | 新颖度 | 早期度 | as_of 扩散 |
| --- | --- | ---: | ---: | --- |
| AI时代连接性瓶颈 | 连接性 + AI时代 | 1.0 | 1.0 | 2次/2群 |
| 自研TileRT推理引擎 | 推理引擎 + 自研TileRT | 1.0 | 1.0 | 2次/2群 |
| 适配人工智能智能体的中央处理器 | 中央处理器 + 适配人工智能智能体 | 1.0 | 1.0 | 1次/1群 |
| Token消耗变现路径 | Token + 消耗变现路径 | 0.61 | 1.0 | 2次/2群 |
| 碳化硅大周期拐点 | 碳化硅 + 大周期拐点 | 1.0 | 1.0 | 1次/0群 |

逐条解释：

#### AI时代连接性瓶颈

```text
anchor=连接性
modifier=AI时代
历史：anchor 8 次，modifier 461 次，exact 0 次，combo 0 次
```

这条的意思不是“AI时代连接性瓶颈”已经是成熟题材，而是：

- `AI时代` 这个修饰词很常见。
- `连接性` 这个锚点在本地历史里不算特别热，只出现 8 次。
- 但 `AI时代 + 连接性` 这个组合在过去 30 天没有出现过。

所以它被放进 `source_seed`。人工要问的是：

```text
AI 时代的瓶颈是不是从算力转向连接性？
如果是，受益环节是交换芯片、光互联、SerDes，还是别的？
```

这类就是“可以问”，但还不是“可以买”。

#### 自研TileRT推理引擎

```text
anchor=推理引擎
modifier=自研TileRT
历史：anchor 10 次，modifier 0 次，exact 0 次，combo 0 次
```

这条更像典型源头种子：

- `推理引擎` 是能理解的技术锚点。
- `自研TileRT` 在本地历史没出现过。
- 组合也没出现过。

人工要问的是：

```text
TileRT 是什么？
是谁自研？
它解决的是推理成本、推理速度，还是部署能力？
有没有上市公司映射？
```

#### 适配人工智能智能体的中央处理器

```text
anchor=中央处理器
modifier=适配人工智能智能体
历史：anchor 5 次，modifier 0 次，exact 0 次，combo 0 次
```

这条看起来很长，不像一个自然题材名。它更像一句报告里的描述被切成了组合。

系统把它推出来的原因是：

- `中央处理器` 是硬件锚点。
- `适配人工智能智能体` 是新修饰。
- 历史里没见过这个组合。

人工要做的判断是：

```text
这是 CPU 的真实新需求，还是报告里的一句泛化表达？
```

如果后续没有别人接力、没有更清晰的产业链落点，这类就应该被降权。

#### Token消耗变现路径

```text
anchor=Token
modifier=消耗变现路径
历史：anchor 1560 次，modifier 3 次，exact 3 次，combo 3 次
新颖度：0.61
```

这条不是特别新，因为：

- `Token` 历史非常多。
- `消耗变现路径` 和 exact 组合也出现过几次。

所以它的新颖度只有 `0.61`，低于前面几条。

但它仍然在 `source_seed`，因为截至当时还比较早，且是“AI 应用如何变现”的可问问题。人工要问的是：

```text
这是新商业模式，还是已有 AI 应用叙事的重复表述？
```

#### 碳化硅大周期拐点

```text
anchor=碳化硅
modifier=大周期拐点
历史：anchor 331 次，modifier 1 次，exact 0 次，combo 0 次
```

这条的锚点很成熟：`碳化硅` 出现 331 次。

组合很新：`大周期拐点` 和碳化硅组合几乎没出现。

人工要问的是：

```text
碳化硅是行业周期真的变了，还是某个卖方的拐点话术？
供需、价格、库存、订单哪个指标支撑它？
```

这种信号的关键不是“拐点”两个字，而是它有没有基本面证据。

### 12.5 6.3 扩散验证怎么看

6.3 的 `扩散验证` 有 3 条：

| 新组合 | 结构 | 新颖度 | 早期度 | as_of 扩散 | 接力 |
| --- | --- | ---: | ---: | --- | --- |
| 内容+AItoken运营 | 内容资产 + AItoken运营 | 0.87 | 0.55 | 4次/4群 | 1人/3群 |
| 硫化锂布局领先 | 硫化锂 + 布局领先 | 0.74 | 0.75 | 3次/1群 | 2人/0群 |
| 业界领先的算力利用率水平 | 算力利用率水平 + 业界领先 | 0.22 | 0.35 | 6次/6群 | 1人/5群 |

#### 内容+AItoken运营

```text
anchor=内容资产
modifier=AItoken运营
as_of：4次/4群/1人
接力：1人/3群
```

这条进入 `spreading_watch`，不是因为它一定更好，而是因为它已经跨群扩散。

注意这里的 `1人/3群`：

- 说明它主要还是同一个发送人或同一条内容在多个群传播。
- 这叫“群扩散”，但还不是强独立验证。

人工要问的是：

```text
内容资产 + AI token 运营，是不是一个新的商业模式？
还是同一篇推荐在多个群同步传播？
```

#### 硫化锂布局领先

```text
anchor=硫化锂
modifier=布局领先
as_of：3次/1群/2人
接力：2人/0群
```

这条和上一条相反：

- 群数不多。
- 但发送人有 2 个。

这说明可能有独立接力，但扩散范围还小。

人工要问的是：

```text
硫化锂是不是固态电池链条的新卡点？
布局领先对应哪家公司？
是不是已经有股票推荐了？
```

#### 业界领先的算力利用率水平

```text
anchor=算力利用率水平
modifier=业界领先
历史：exact 6 次，combo 6 次
新颖度：0.22
早期度：0.35
```

这条其实质量偏弱。

原因：

- 历史已经出现过多次，所以新颖度只有 `0.22`。
- 已经 6 次/6 群扩散，所以早期度只有 `0.35`。

它出现在 `扩散验证`，更多是在提醒：

```text
这个说法正在刷屏，但不早，也不够新。
```

这类后续应该考虑降权，避免占用名额。

### 12.6 为什么 6.3 没有个股映射

这次产物里没有 `个股映射` 榜。

这不代表这些信号一定没有股票，只代表截至 `15:47:39`，scan 没有从本地 recommendation 产物里找到对应的 `mapped_stocks`。

常见原因有三个：

1. 当天推荐抽取还没跑完。
2. 相关消息没有被识别成 recommendation。
3. 概念还停留在问题阶段，没有明确股票落点。

所以没有 `mapped` 时，应该理解为：

```text
目前还没有本地证据证明它已经落到个股。
```

不是说它一定没有投资机会。

### 12.7 看榜单的正确顺序

建议每次按这个顺序看：

1. **先看源头种子。**
   问自己：这里有没有“成熟锚点 + 新修饰”的组合？有没有值得问大佬的问题？

2. **再看扩散验证。**
   问自己：这是多人接力，还是同一人多群转发？如果只是同人多群，权重低一点。

3. **最后看个股映射。**
   问自己：是不是已经开始进入交易机会？如果已经满屏带股，可能反而晚了。

4. **看到别扭词不要马上否定。**
   先拆结构：

   ```text
   anchor 是什么？
   modifier 是什么？
   组合以前出现过吗？
   有没人接力？
   有没有股票落点？
   ```

   如果拆完还是说不清，那就是噪音样本，后续要用来调规则。

## 13. 当前定时推送

本机当前已恢复 `source-radar` 定时任务。

频率：

```text
每天 09:00-23:00
每 30 分钟一次
```

当前命令链路：

```bash
uv run sn analyze classify --date today
uv run sn source extract --date today
uv run sn source scan --date today --top 5 --markdown-out ~/.config/stock-news/schedule/source-radar.md
uv run sn delivery send --route wechat-radar --markdown-file ~/.config/stock-news/schedule/source-radar.md
```

推送路由：

```text
wechat-radar
```

当前策略：

- 三榜单完整推送。
- 不按 `askability_score` 过滤。
- 不做同一 `signal_id` 只推一次。
- 不只推状态升级。

原因：

当前还在校准模型和指标。先完整推送，方便人审和复盘。等看几天结果后，再决定是否加去重、状态升级、低分过滤。

## 14. 用 5.11 案例理解

### 09:20 视角

```bash
uv run sn source scan \
  --date 2026-05-11 \
  --as-of 2026-05-11T09:20:00 \
  --lookback-days 30 \
  --top 10
```

`半导体化的PCB` 是 `source_seed`：

```text
首现：2026-05-11 09:14:49
anchor=PCB
modifier=半导体化
```

这时它还早，适合问人。

### 12:00 视角

```bash
uv run sn source scan \
  --date 2026-05-11 \
  --as-of 2026-05-11T12:00:00 \
  --lookback-days 30 \
  --top 10
```

`半导体化的PCB` 进入 `spreading_watch`：

```text
截至 as_of：9 次 / 9 群 / 2 人
接力：1 人 / 8 群
```

这说明它已经从早期种子进入扩散验证。

### 全天视角

截至 23:59，它仍然显示为扩散验证，且首现仍然回指 09:14。

这就是当前模型想捕捉的路径：

```text
早上首现 -> 上午扩散 -> 后续观察是否带股
```

## 15. 当前局限

当前版本仍有几个明显局限：

1. **LLM 结构抽取仍会有伪概念。**
   例如把普通描述切成新组合。scan 已经过滤一部分抽象锚点，但还需要继续看真实样本。

2. **独立接力和同人多群转发仍需更细分。**
   现在 `followup_groups` 能看扩散，`followup_senders` 能看独立人接力，但排序还没有完全区分“同一个人复制到很多群”和“多人独立接力”。

3. **个股映射依赖 recommendation 产物。**
   如果当天 recommendation 没跑或没抽到，`mapped_stocks` 可能为空。

4. **当前推送没有去重。**
   每 30 分钟完整推三榜单，可能重复。现在是为了校准；后面可以加状态池。

5. **历史新颖度依赖本地数据覆盖。**
   如果某段历史没有 raw 或没有 classify，冷度判断会偏乐观。

## 16. 后续可加的规则

等看几天推送后，再考虑加：

1. **状态池**
   同一 `signal_id` 记录首次推送时间、上次状态、是否已推送。

2. **只推升级**
   从 `source_seed` 到 `spreading_watch`、从 `spreading_watch` 到 `mapped` 再推。

3. **低分过滤**
   例如只推：

   ```text
   askability_score >= 0.75
   novelty_strength >= 0.6
   ```

4. **独立接力加权**
   多人接力权重大于同人多群转发。

5. **老板 gold sample 校准**
   每周维护：
   - 老板觉得有价值的样本
   - 系统误报样本
   - 系统漏报但后来被市场验证的样本

这些样本比复杂模型更重要。没有 gold sample，系统只能学“市场热不热”；有 gold sample，才能学“什么值得老板提前问”。
