# Tushare 数据层方案

## 背景

推荐人胜率回测需要 A 股行情数据。Tushare Pro 是当前数据源，账号 2000 积分。

## 账号权限（2000 积分）

| 接口 | 用途 | 频限 | 单次上限 |
|------|------|------|----------|
| `daily` | A股日线（未复权） | 200次/分 | 6000行 |
| `pro_bar` | A股日线（前/后复权） | 200次/分 | 8000行 |
| `stock_basic` | 股票名称↔代码映射 | 50次/分 | 6000行 |
| `index_daily` | 指数日线（沪深300基准） | 200次/分 | 8000行 |
| `trade_cal` | 交易日历 | 200次/分 | - |

**不支持**：分钟级、实时行情、港美股深度数据、新闻公告。

## 回测可行性

| 回测维度 | 所需数据 | 可行性 |
|----------|----------|--------|
| 推荐人胜率（T+N 涨跌） | daily / pro_bar | ✅ |
| 推荐人超额收益（vs 沪深300） | daily + index_daily | ✅ |
| 推荐人画像（偏好板块/风格） | daily + stock_basic | ✅ |
| 推荐强度 vs 收益相关性 | daily | ✅ |
| 日内推荐验证（分钟级） | 分钟线 | ❌（日线近似可接受） |
| 港美股推荐 | 港美股行情 | ❌（后续用 efinance 补） |

## 技术方案

### 本地缓存：SQLite

原因：
- 行情是不变的历史数据，拉一次永久有效
- 2000 积分 + 200次/分钟频限，必须缓存
- Python 标准库 `sqlite3`，零额外依赖
- 查询方便，支持日期范围、ts_code 筛选

### 表结构

```sql
-- 股票基础信息（拉一次，偶尔更新）
CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code    TEXT PRIMARY KEY,
    symbol     TEXT NOT NULL,
    name       TEXT NOT NULL,
    area       TEXT,
    industry   TEXT,
    market     TEXT,
    list_date  TEXT
);

-- 交易日历
CREATE TABLE IF NOT EXISTS trade_cal (
    cal_date      TEXT PRIMARY KEY,
    is_open       INTEGER NOT NULL,
    pretrade_date TEXT
);

-- A股日线行情（核心表）
CREATE TABLE IF NOT EXISTS daily_price (
    ts_code    TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    pre_close  REAL,
    change     REAL,
    pct_chg    REAL,
    vol        REAL,
    amount     REAL,
    PRIMARY KEY (ts_code, trade_date)
);

-- 指数日线
CREATE TABLE IF NOT EXISTS index_daily (
    ts_code    TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    pre_close  REAL,
    change     REAL,
    pct_chg    REAL,
    vol        REAL,
    amount     REAL,
    PRIMARY KEY (ts_code, trade_date)
);
```

### 数据拉取策略

```
初始化（一次性）：
  1. stock_basic 全量 → SQLite（~5000条）
  2. trade_cal 2020-2027 → SQLite

按需拉取（回测时）：
  3. 推荐涉及的 ts_code + 日期范围 → 查 SQLite
     → miss → 调 Tushare daily → 写入 SQLite → 返回
  4. 沪深300 基准同理
```

### 名称→代码映射

推荐人说"贵州茅台"，Tushare 用 `600519.SH`。映射逻辑：
1. SQLite `stock_basic` 表精确匹配 `name`
2. 支持模糊匹配（前缀/包含）
3. 未匹配到时打印警告，跳过该推荐

### 代码位置

```
src/stock_news/common/market/
├── __init__.py
├── tushare_client.py   # Tushare API 封装 + 频限控制
└── db.py               # SQLite 读写层
```

- `tushare_client.py`：封装 `tushare.pro_api()`，提供 `fetch_daily()`、`fetch_stock_basic()` 等
- `db.py`：SQLite 连接管理、建表、查询/插入/缓存 miss 拉取

### CLI 入口

```bash
sn market init              # 初始化：拉 stock_basic + trade_cal
sn market price 600519.SH   # 查/拉日线
sn market search 贵州茅台    # 名称→代码
```

## 后续

- 回测引擎基于此数据层构建
- 复权数据使用 `pro_bar(adj='qfq')`
- efinance 作为免费备选（港美股、积分不足时降级）
