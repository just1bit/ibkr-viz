# IBKR Portfolio Viz

轻量级投资组合可视化工具，通过 IBKR Flex Web Service 拉取真实持仓，**围绕「每个持仓的占比」展开**：环形图展示权重分布、再平衡表计算买卖建议。现金作为一种持仓纳入统计，所有扇区之和恒为 100%。

> A lightweight portfolio allocation & rebalancing tool for Interactive Brokers accounts. Visualizes position weights, tracks drift from target allocations, and suggests buy/sell amounts to rebalance.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-black?logo=flask)
![React](https://img.shields.io/badge/React-18-61dafb?logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178c6?logo=typescript&logoColor=white)
![ECharts](https://img.shields.io/badge/ECharts-5-aa344d?logo=apache-echarts&logoColor=white)

---

## 功能 Features

- **持仓占比环形图** — Holdings / Sector / Asset class 三视图，图例与扇区双向高亮联动
- **现金即持仓** — Cash 纳入所有视图，占比分母为「证券市值 + 现金」
- **再平衡表** — 当前占比 / 目标占比 / 偏离 / 买卖建议，目标按账户持久化保存
- **KPI 概览** — 净值、当日盈亏、市值、现金余额
- **多子账户** — 自动识别，支持单账户或合并查看
- **深浅双主题** + **响应式布局** + **一键隐藏金额**
- **Mock 模式** — 无需 IBKR 凭证即可运行，内置模拟数据

---

## 快速开始 Quick Start

```bash
# 1. 安装 Python 依赖
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. 构建前端（产物由 Flask 托管）
cd frontend && npm install && npm run build && cd ..

# 3. 启动（默认端口 5123）
python app.py
# 访问 http://localhost:5123
```

无配置文件时自动以 **mock 模式**运行，全部功能开箱即用。

---

## 配置 Configuration

所有可配置项集中在一个文件，复制模板并按需修改（每个键的含义与取值见模板内注释）：

```bash
cp config.example.yaml config.local.yaml
```

`config.local.yaml` 已被 `.gitignore` 忽略，**请勿提交真实密钥**。省略的键按默认值运行。要点：

| 配置组 | 键 | 说明 |
|--------|----|------|
| 模式 | `mock_mode` | true 用内置模拟数据，false 拉取真实 IBKR 数据 |
| IBKR | `flex_token` / `flex_query_id` / `flex_max_wait` | Flex Web Service 凭证与轮询超时 |
| 数据库 | `db_type` / `db_path` / `postgres_url` | sqlite（本地）或 postgres（生产） |
| 对象存储 | `s3_*` | 原始 XML 按报表日存档，兼容 S3/R2/MinIO，可选 |
| 刷新节流 | `market_timezone` / `report_ready_hour` / `fetch_retry_backoff` / `refresh_cooldown` | 报告周期判断全部以**市场时区**（默认美东）为基准，与部署地无关；后台每小时自检，已是最新则零请求 |
| 服务 | `port` / `debug` | 监听端口（环境变量 `PORT` 优先）与 Flask debug |

### IBKR Flex Query 设置

在 IBKR Client Portal → Reports → Flex Queries 中创建 Query，需包含以下 Sections：

| Section | 级别 | 说明 |
|---------|------|------|
| AccountInformation | — | 账户类型（Margin / Cash） |
| EquitySummaryInBase | — | 净值、现金、持仓价值（NAV 数据来源） |
| CashReport | — | 现金余额 |
| OpenPositions | **Detailed** | 持仓明细 + 成本基础（必须选 Detailed，Summary 级别无 cost basis）|

---

## API 端点

所有 GET 端点接受 `?account_id=<id>` 参数；`ALL` 表示合并所有子账户。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/portfolio` | GET | 最新持仓与分类汇总（含 `summary.allocation_total` = 证券市值 + 现金）|
| `/api/targets` | GET | 读取该账户的目标占比 `{ticker: pct}` |
| `/api/targets` | POST | 保存目标占比，body：`{account_id, targets}` |
| `/api/accounts` | GET | 子账户列表 |
| `/api/status` | GET | 上次刷新时间、模式、冷却剩余 |
| `/api/trigger-refresh` | GET | 手动触发刷新（带冷却限制）|

---

## 数据架构

```
IBKR Flex Web Service
        │  flex_client.py  (两步轮询，到达即落盘)
        ▼
   原始 XML ──→ S3（可选，用于审计与重解析）
        │  flex_parser.py
        ▼
   结构化数据 ──→ storage.py ──→ SQLite / PostgreSQL
        │
        ▼
   Flask API ──→ React SPA（ECharts 渲染）
```

**三张表：**

| 表 | 用途 |
|----|------|
| `daily_snapshot` | 每日持仓快照（占比与再平衡的数据来源）|
| `nav_history` | 每日净值 / 现金（KPI 盈亏计算基线）|
| `config` | 键值配置，含按账户保存的目标占比 `targets_<account_id>` |

- **按报表周期拉取**：所有数据按报表日（XML `toDate`）入库与命名；后台每小时自检，仅当「应已发布的最新报表」（以市场时区美东 01:00 后为界，跳过周末）尚未入库时才请求 IBKR，报表缺失（节假日/生成延迟）时按 `fetch_retry_backoff` 退避重试；判断状态存于数据库，多实例共享同库时自动全局去重
- **S3 冗余**：原始 XML 上传 S3 并验证后再写 DB，本地文件成功后清理
- **双数据库**：`storage.py` 自动处理 SQLite `?` 与 PostgreSQL `%s` 占位符差异

---

## 技术栈

| 层 | 方案 |
|----|------|
| 前端 | Vite + React 18 + TypeScript + Tailwind CSS v4，ECharts 5 按需引入 |
| 后端 | Python Flask 3 + APScheduler（每小时自检，按市场时区判断是否拉取）|
| 数据库 | SQLite（本地）/ PostgreSQL（生产）|
| 原始存储 | S3 兼容（AWS S3 / Cloudflare R2 / MinIO），可选 |
| 部署 | 前端构建产物由 Flask 托管，单进程启动 |

---

## Roadmap

- [ ] **T-01** 持仓占比日变动 — 图例/再平衡表中展示各持仓相较前一交易日的占比变化（±pp）
- [ ] **T-02** 下单清单导出 — 把买卖金额换算成股数，便于直接下单
- [ ] **T-03** 目标归一化 — 一键将目标按比例缩放到合计 100%

---

## License

MIT
