# 源头雷达信号设计：低频拐点 + T+3 验证

## 背景

老板看 5/11—5/12 的原始群消息时给出的核心判断：**一个成熟产业链词后面，紧跟一个大家都没听过的新词 / 新概念**——这才是值钱的信号。新概念**首次出现**的那一刻，就是"做铺垫 / 提前埋伏"的窗口：他拿着这个新词去找大佬交流、提前布局；等过几天这个词再次刷屏，再去追个股就晚了。

所以源头雷达要回答的不是"今天群里都聊了啥"，而是三个问题：

- **是不是新？** —— 这个词在本地历史上到底冷不冷。
- **是不是够早？** —— 我们是在它刚起量、还没扩散开的时候看到的吗。
- **会不会变成交易机会？** —— 它有没有从"概念"扩散到"别人接力 + 落到个股"。

`sn source scan` 就是围绕这三问做的本地扫描（纯本地，不调外部 API、不消耗 token）。

## 数据链路

```text
微信 raw（个人群）
  → sn source extract（LLM 抽取，仅这步花 token）
      → source_extract/candidates.json   # 当日源头候选词（带 source_type）
  → sn source scan（纯本地）
      → 全量语料子串统计：历史基线 / 当日放量 / 后续扩散 / T+3 回看
      → 同源折叠 + 信号分层 + 排序
      → TOP N 榜单（plain / --json）
```

关键设计：**抽取（LLM）与统计（本地）分离**。`extract` 负责把"哪些消息是源头候选、切出哪些词"沉淀成 `candidates.json`；`scan` 不再受限于只有少数几天的候选产物，而是回到**全量群消息原文**里按子串匹配，统计每个候选词的历史/扩散曲线。

## 三步演进

雷达的信号质量是分三步迭代出来的，每一步都用 5/11 历史数据自证。

### 第 1 步：全量语料基线（解决"是不是新"）

最初 `scan` 判断"全新/历史提及"时，只跟 `source_extract/candidates.json` 比——而候选产物只有少数几天，于是几乎一切词都被误判成"全新"。

修正：新增 `load_corpus()`，加载 `[首现日 − lookback_days, 观察结束]` 的**全量个人群原文**作基准语料；`_corpus_mentions()` 按原文子串统计首现前的真实提及数。

自证：老板举例的"算电协同"在全量语料里其实已发酵约一个月（百次量级提及）——**证明"纯全新"是错的信号方向**，真正值钱的是下面的"低频→放量"。

### 第 2 步：低频拐点（解决"是不是够早"）

"全新"不可靠，改成度量**放量拐点**：一个低频词在某天突然跨群放量，才是窗口。

`_surge_metrics()` 产出三个量：

- `baseline_daily` —— 首现日前 `lookback_days` 天的日均提及（不含当天）。
- `surge_count` —— 首现当天的提及次数。
- `surge_groups` —— 首现当天覆盖的独立群数。
- `surge_ratio = surge_count / max(baseline_daily, 0.5)` —— **放量倍率**，主权重。

据此分层（`signal_type` / `signal_priority`，优先级 0 最高）：

| 信号 | 优先级 | 判据 | 含义 |
|------|:--:|------|------|
| 低频拐点 | 0 | `baseline≤2` + `ratio≥3` + `groups≥3` | 冷词突然跨群放量，最佳埋伏窗口 |
| 放量加速 | 1 | `2<baseline≤10` + `ratio≥2` + `groups≥3` | 中频题材二次催化 |
| 扩散带股 | 2 | 已带个股 + 后续提及≥3 | 概念已落地标的 |
| 全新首现 | 3 | 历史提及=0 | 首现但还没放量，可能哑火 |
| 普通线索 | 4 | 其它 | 兜底 |
| 高频旧主题 | 5 | `baseline>10` | 刷屏噪音，**只降权不剔除** |

设计决定（站在老板视角）：

- **放量窗口取"当日突量"**，不做平滑——产品的命脉是抢跑，当天就要拿到新词去交流；过滤偶发交给第 3 步。
- **高频旧主题只降权、不过滤**——过滤是不可逆的信息损失，宁可沉底保留可见性，符合本仓库谨慎删数据的风格。

### 第 3 步：同源折叠 + T+3 事后验证（解决"会不会变成交易机会"）

第 2 步的榜单还有两个病：①同一条消息切出的多个词各占一行刷屏；②"全新首现"尾部全是单条长消息切出、0 扩散的噪音词。

**同源折叠（`_fold_aliases`）**：按首现消息的 `message_id` 分组——
`message_id = sha256(sender | message_time | raw_content)[:16]`，
同一条物理消息切出的多个词主键必然相同。每组只保留信号优先级最高、分最高的词作主词，其余进 `aliases` 挂在主词下。**这是确定性的物理去重，不依赖任何语义猜测**，所以可靠：一条消息 = 一个发布动作 = 一个信号。

**T+3 事后验证（`_t3_metrics` + `t3_verdict`）**：回看首现后 `lookahead_days` 天内的真实扩散——

- `t3_groups` —— 接力提及覆盖的独立群数。
- `t3_senders` —— **排除首现发布人**后的独立接力人数（防单人在多群刷屏虚高）。
- `t3_stocks` —— 这些接力消息里抽出的个股名（链路终点是个股埋伏）。

裁决口径（站在老板视角）：

```text
落地个股（t3_stocks 非空）           → 验证为真，最硬命中
接力 senders≥2 且 groups≥3          → 验证为真，别人自发接棒才算真起势
接力 senders≥1                       → 弱扩散
无人接力                              → 单点哑火
```

验证为真（`verified`）的候选在排序里顶到最前。**注意**：实时跑（`--since-minutes`）时窗口内没有"未来"数据，T+3 全为空，排序自动退回第 2 步的"低频拐点"优先级，不影响抢跑；T+3 仅在事后回看（指定历史 `--start` + 较大 `--lookahead-days`）时发挥校验作用。

## 5/11 自证结果（节选）

`uv run sn source scan --start 2026-05-11 --end 2026-05-11 --lookback-days 30 --lookahead-days 5`

| 词 | 倍率 | T+3 接力 | 落地个股 |
|----|:--:|------|------|
| 半导体化的PCB | 36× | 3人/12群 | —（强扩散） |
| AI购物 | 16× | 5人/5群 | 三江购物、值得买…（5只） |
| 法拉第旋光片 | 10× | 8人/8群 | 东田微、中润光学…（4只） |
| 光入柜内 | 7× | 5人/6群 | 天孚通信、太辰光…（12只） |

TOP1「半导体化的PCB」正是老板"成熟链（PCB）+ 紧跟新词（半导体化）"的原话例子——**由系统自动排到第一**，且 3 天内验证了跨群扩散。

## 关键文件

- `src/stock_news/source/features.py` —— 切词、触发词、`signal_type` / `signal_priority` / `score_candidate` / `novelty_level` / `evidence` / `t3_verdict`。
- `src/stock_news/source/scanner.py` —— 扫描编排：`load_corpus` / `_corpus_mentions` / `_surge_metrics` / `_t3_metrics` / `_fold_aliases` / `scan_source_candidates`。
- `src/stock_news/source/models.py` —— `SourceCandidate`（含 surge / aliases / t3 字段）、`SourceScanResult`。
- `src/stock_news/commands/source.py` —— 业务适配 + plain / JSON 输出。
- `src/stock_news/commands/source_cli.py` —— `sn source extract` / `sn source scan` 的 click 接线。

## 复现命令

```bash
# 事后回看验证（纯本地，0 token）——需当日已有 source_extract/candidates.json
uv run sn source scan --start <YYYY-MM-DD> --end <YYYY-MM-DD> \
    --lookback-days 30 --lookahead-days 5 --top 15

# 实时抢跑（T+3 退化为空，按低频拐点优先级排）
uv run sn source scan --since-minutes 240

# 若目标日还没有候选产物，先抽取（LLM，需授权，消耗 token）
uv run sn source extract --date <YYYY-MM-DD>
```

## 可调参数与边界

- `--lookback-days`（默认 30）：基线回看窗口，越长基线越稳但越吃历史数据。
- `--lookahead-days`（默认 5）：T+3 / 扩散回看窗口，实时跑时该窗口内无数据属正常。
- `--max-message-chars`（默认 300）：源头候选消息最大长度，过滤长纪要 / 日报。
- 语料口径只取 `个人群`，与 `is_source_like` 的来源约束一致。
- 子串匹配是召回优先的近似口径，可能把"算力"匹进"算电算力"等包含串；分层 + T+3 验证会把这类弱信号自然沉底，但极端歧义词仍需人工复核。

## 后续方向

参见 `source-event-roadmap.md`：把一次性 TOP 榜单升级成增量事件流（状态流转 + 定时提醒 + 半日摘要），并沉淀"哪些群 / 哪些人是真源头"的可信度画像。
