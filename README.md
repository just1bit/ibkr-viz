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
- **KPI 概览** — 净值、当日盈亏、总盈亏、市值、现金余额、保证金占用率
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

在项目根目录创建 `config.local.yaml`（已被 `.gitignore` 忽略，**请勿提交真实密钥**）：

```yaml
# 设为 false 并填入凭证即可拉取真实数据
mock_mode: true

# IBKR Flex Web Service（mock_mode: false 时必填）
flex_token: "<your-flex-token>"
flex_query_id: "<your-query-id>"

# 数据库：sqlite（默认/本地）或 postgres（生产）
db_type: "sqlite"
db_path: "ibkr_portfolio.db"
# postgres_url: "postgresql://user:password@host:5432/dbname"

# 原始 XML 备份，可选（留空则关闭）
s3_bucket: ""
s3_endpoint: ""          # 留空则使用 AWS；填入自定义地址支持 R2/MinIO
s3_region: "auto"
s3_access_key: ""
s3_secret_key: ""

# 每日定时刷新（24h 制）与手动刷新冷却（秒）
refresh_hour: 17
refresh_minute: 0
refresh_cooldown: 600
```

### IBKR Flex Query 设置

在 IBKR Client Portal → Reports → Flex Queries 中创建 Query，需包含以下 Sections：

| Section | 级别 | 说明 |
|---------|------|------|
| AccountInformation | — | 账户类型（Margin / Cash） |
| EquitySummaryInBase | — | 净值、现金、持仓价值（NAV 数据来源） |
| CashReport | — | 现金余额 |
| OpenPositions | **Detailed** | 持仓明细 + 成本基础（必须选 Detailed，Summary 级别无 cost basis）|

> 详细的 Flex Query 优化建议见 [`IBKR_FLEX_REDUNDANCY.md`](./IBKR_FLEX_REDUNDANCY.md)。

---

## API 端点

所有 GET 端点接受 `?account_id=<id>` 参数；`ALL` 表示合并所有子账户。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/portfolio` | GET | 最新持仓与分类汇总（含 `summary.allocation_total` = 证券市值 + 现金）|
| `/api/targets` | GET | 读取该账户的目标占比 `{ticker: pct}` |
| `/api/targets` | POST | 保存目标占比，body：`{account_id, targets}` |
| `/api/margin` | GET | 保证金占用率 |
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

- **DB 优先**：当日已有数据则跳过 IBKR 请求，一天最多拉取一次
- **S3 冗余**：原始 XML 上传 S3 并验证后再写 DB，本地文件成功后清理
- **双数据库**：`storage.py` 自动处理 SQLite `?` 与 PostgreSQL `%s` 占位符差异

---

## 技术栈

| 层 | 方案 |
|----|------|
| 前端 | Vite + React 18 + TypeScript + Tailwind CSS v4，ECharts 5 按需引入 |
| 后端 | Python Flask 3 + APScheduler（每日定时）|
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
