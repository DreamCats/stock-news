# 回测流程详解

## 命令

```bash
sn analyze backtest --date 2026-05-08
sn analyze backtest-summary --window-days 30 --min-count 3 --top 20
```

## 内部流程

```
sn analyze backtest --date 2026-05-08
│
├── 1. 加载推荐数据
│   └── 读取 ~/.config/stock-news/data/2026-05-08/extracted/recommendations.json
│       → N 条 Recommendation（含 ticker, sender, action, message_time）
│
├── 2. 名称→代码映射（逐条）
│   ├── "贵州茅台" → 查 SQLite stock_basic → "600519.SH" ✓
│   ├── "光华科技" → 查 SQLite stock_basic → "002741.SZ" ✓
│   ├── "科技股"   → 查 SQLite stock_basic → 无匹配 ✗ 跳过
│   ├── "nebius"   → 查 SQLite stock_basic → 无匹配 ✗ 跳过
│   └── ... 能匹配个股的保留，板块/概念/海外股跳过
│
├── 3. 逐条回测（对每条匹配成功的推荐）
│   │
│   ├── 3a. 取基准价
│   │   ├── 查 SQLite daily_price: ts_code + 推荐日收盘价
│   │   ├── 命中 → 直接用（本地缓存）
│   │   └── 未命中 → 调 Tushare daily API → 写入 SQLite → 用
│   │
│   ├── 3b. 取未来价格
│   │   ├── 查 SQLite trade_cal → 算出 T+1/T+2/T+3/T+5/T+10/T+20 对应的交易日
│   │   │   （自动跳过周末和节假日）
│   │   ├── 查 SQLite daily_price: ts_code + 未来日期范围
│   │   └── 未命中 → Tushare 拉取 → 写入 SQLite
│   │
│   ├── 3c. 取沪深300基准（同样的缓存逻辑）
│   │   └── 查/拉 index_daily 表，代码 000300.SH
│   │
│   └── 3d. 计算各窗口收益
│       ├── ret_t5    = (T+5收盘价 - 推荐日收盘价) / 推荐日收盘价
│       ├── win_t5    = 买入/加仓/关注 ? ret > 0 : ret < 0
│       │               （看多方向涨了算赢，看空方向跌了算赢）
│       ├── bench_ret = 沪深300同期涨跌幅
│       └── excess    = ret_t5 - bench_ret（超额收益，剔除大盘涨跌影响）
│
├── 4. 保存逐条结果
│   └── → backtest/results.json
│       每条记录包含: ts_code, ticker, sender, action, rec_date, base_close,
│       ret_t1, win_t1, ret_t3, win_t3, ..., ret_t20, win_t20,
│       bench_ret_t5, excess_t5
│
├── 5. 按推荐人聚合统计
│   ├── 按 sender 分组
│   ├── 每个 sender 计算:
│   │   ├── count      — 推荐次数（样本量）
│   │   ├── win_rate_tN — 各窗口胜率 = 赢的次数 / 总次数
│   │   ├── avg_ret_tN  — 各窗口平均收益率
│   │   └── avg_excess_tN — 各窗口平均超额收益（vs 沪深300）
│   ├── 按 T+5 胜率降序排序
│   └── → backtest/sender_stats.json
│
└── 6. 输出排行榜表格
    └── 推荐人 | 次数 | T+1胜率 | T+2胜率 | ... | T+5均收益 | T+5超额
```

## 缓存机制

行情数据通过 SQLite 本地缓存，同一数据只拉一次 Tushare：

```
第一次跑 5/8 回测:
  → ~640 只股票各拉一次日线 = ~640 次 Tushare API
  → 受 350ms 频限控制，约需 3-4 分钟
  → 全部写入 SQLite daily_price 表

第二次跑 5/8 回测（或其他日期涉及相同股票）:
  → SQLite 全部命中，0 次 Tushare 请求
  → 几秒钟完成
```

## 评估窗口说明

`sn analyze backtest-summary` 默认按滚动近 30 天汇总已有单日回测结果。例如当前日期为 2026-05-25 时，默认窗口为 2026-04-25 至 2026-05-25。这个口径更关注推荐人的近期有效性，避免长期历史胜率掩盖分析师在不同阶段、不同板块上的能力变化。

如需查看历史累计口径，可使用：

```bash
sn analyze backtest-summary --all
```

| 窗口 | 含义 | 适用场景 |
|------|------|---------|
| T+1 | 次日收盘 | 验证短线信号 |
| T+2 | 第 2 个交易日 | 短线延续性 |
| T+3 | 第 3 个交易日 | 短线窗口 |
| T+5 | 一周后 | 最核心指标，波段验证 |
| T+10 | 两周后 | 中线验证 |
| T+20 | 一个月后 | 趋势验证 |

## 胜率计算逻辑

```
推荐动作为 买入/加仓/关注（看多方向）:
  → 未来价格涨了 = 胜 ✓
  → 未来价格跌了 = 败 ✗

推荐动作为 减仓/卖出（看空方向）:
  → 未来价格跌了 = 胜 ✓
  → 未来价格涨了 = 败 ✗

胜率 = 胜的次数 / 总推荐次数
```

## 超额收益

光看绝对涨跌不够 — 牛市里所有股票都涨，推荐人可能只是跟着大盘走。

```
超额收益 = 个股收益率 - 沪深300同期收益率

超额 > 0 → 跑赢大盘，推荐人真有选股能力
超额 < 0 → 跑输大盘，还不如买指数
```

## 数据依赖

```
前置条件:
  sn market init                    → SQLite 有 stock_basic + trade_cal
  sn analyze classify --date xxx    → 有 classified.json
  sn analyze extract --date xxx     → 有 recommendations.json

回测时自动完成:
  名称→代码映射                       → 查 stock_basic 表
  日线数据拉取+缓存                   → 查/写 daily_price 表
  沪深300基准拉取+缓存                → 查/写 index_daily 表
```

## 输出文件

```
~/.config/stock-news/data/2026-05-08/backtest/
├── results.json       # 逐条回测结果（每条推荐的各窗口收益）
└── sender_stats.json  # 推荐人聚合统计（胜率、均收益、超额）
```
