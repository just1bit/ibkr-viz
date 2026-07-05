# IBKR Portfolio Viz

轻量级多用户投资组合可视化工具，通过 IBKR Flex Web Service 拉取真实持仓，**围绕「每个持仓的占比」展开**：环形图展示权重分布、再平衡表计算买卖建议。现金作为一种持仓纳入统计，所有扇区之和恒为 100%。支持 Google OAuth 登录，每个用户绑定自己的 IBKR Flex 凭证，数据严格隔离。

> A lightweight multi-tenant portfolio allocation & rebalancing tool for Interactive Brokers accounts. Google OAuth login, per-user IBKR Flex credentials, strict data isolation.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-black?logo=flask)
![React](https://img.shields.io/badge/React-18-61dafb?logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178c6?logo=typescript&logoColor=white)
![ECharts](https://img.shields.io/badge/ECharts-5-aa344d?logo=apache-echarts&logoColor=white)

---

## 功能 Features

- **Google OAuth 登录** — 每个用户独立账号，数据严格隔离
- **IBKR 凭证绑定** — 登录后在 UI 中输入 Flex Token 和 Query ID，加密存储
- **持仓占比环形图** — Holdings / Asset class 双视图，图例与扇区双向高亮联动，Holdings 视图悬浮显示单持仓当日盈亏
- **当日盈亏归因图** — 每持仓一根分叉横条（MTM 直取），悬浮显示前收→收盘价与涨跌%
- **持仓明细表** — 数量、市价、当日涨跌%、当日盈亏、市值、权重条；期权显示行权价/到期/剩余天数；当日有交易自动标记；可排序
- **现金即持仓** — Cash 纳入所有视图，占比分母为「证券市值 + 现金」
- **再平衡表** — 当前占比 / 目标占比 / 偏离 / 买卖建议，目标按账户持久化保存
- **NAV 构成** — 股票 / 期权 / 现金 / 股息·利息应计分解，合并视图下按账户拆分并展示 SYEP/DRIP 等档案徽章
- **收支汇总** — MTD/YTD 股息、代付股息、预扣税、佣金、融资利息、出入金、买卖额（CashReport 直取）
- **KPI 概览** — 净值、当日盈亏、市值（附股票/期权拆分）、现金余额（附应计小计）
- **多子账户** — 自动识别并显示账户别名，支持单账户或合并查看
- **深浅双主题** + **响应式布局** + **一键隐藏金额**

---

## 快速开始 Quick Start

```bash
# 1. 安装 Python 依赖
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt

# 2. 初始化数据库（仅首次）
psql -d <dbname> -f backend/schema.sql

# 3. 创建配置文件
cp config.example.yaml config.local.yaml
# 编辑 config.local.yaml，填入 PostgreSQL URL、Google OAuth 凭证等

# 4. 构建前端（产物由 Flask 托管）
cd frontend && npm install && npm run build && cd ..

# 5. 启动（默认端口 5123）
python backend/app.py
# 访问 http://localhost:5123
```

启动后，用户需通过 Google 登录，然后在 Setup 页面输入自己的 IBKR Flex Token 和 Query ID。数据按用户隔离存储。

---

## 配置 Configuration

所有可配置项集中在 `config.local.yaml`（从 `config.example.yaml` 复制）。该文件已被 `.gitignore` 忽略，**请勿提交真实密钥**。

### 必需的部署配置

| 配置组 | 键 | 说明 |
|--------|----|------|
| Google OAuth | `google_client_id` / `google_client_secret` | Google Cloud Console → OAuth 2.0 客户端 ID |
| Google OAuth | `base_url` | 应用公网 URL，用于构建 OAuth 回调地址 |
| 安全 | `secret_key` | Flask 会话签名密钥（`secrets.token_hex(32)` 生成）|
| 安全 | `flex_encryption_key` | IBKR Flex Token 加密密钥（`Fernet.generate_key()` 生成）|

### 数据库、存储、调度

| 配置组 | 键 | 说明 |
|--------|----|------|
| 数据库 | `postgres_url` | PostgreSQL 连接 URL。先执行 `psql -d <db> -f backend/schema.sql` 初始化表 |
| 对象存储 | `s3_*` | 原始 XML 按报表日存档到 S3/R2/MinIO（可选）|
| 调度 | `market_timezone` / `report_ready_hour` | 报告周期判断以市场时区为基准 |
| 调度 | `fetch_retry_backoff` / `refresh_cooldown` / `scheduler_max_workers` | 节流与并发控制 |
| 管理 | `admin_emails` | 拥有管理员权限的 Google 账号邮箱列表 |

### 用户级配置

以下配置不再出现在 YAML 中，改为用户登录后在 UI 中输入：
- **Flex Web Service Token** — 每个用户在 IBKR Client Portal 生成的个人 Token
- **Flex Query ID** — 每个用户的 IBKR Flex Query ID

Token 使用 Fernet 加密后存储在数据库中，仅在刷新数据时解密到内存使用。

### Google OAuth 设置

1. 前往 [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. 创建 OAuth 2.0 Client ID，应用类型选择 **Web application**
3. 在 Authorized redirect URIs 中添加：`{base_url}/auth/callback`
   - 本地开发：`http://localhost:5123/auth/callback`
   - 生产环境：`https://your-domain.com/auth/callback`
4. 将生成的 Client ID 和 Client Secret 填入 `config.local.yaml`

### IBKR Flex Query 设置

用户在登录后的 Setup 页面中输入凭证。需确保 Flex Query 包含以下 Sections：

| Section | 级别 | 说明 |
|---------|------|------|
| AccountInformation | — | 账户类型（Margin / Cash） |
| EquitySummaryInBase | — | 净值、现金、持仓价值（NAV 数据来源） |
| MTMPerformanceSummaryInBase | — | 当日盈亏与前收盘价 |
| OpenPositions | **Detailed** | 持仓明细 + 成本基础（必须选 Detailed） |

---

## API 端点

所有 `/api/*` 端点需要登录（Cookie 会话）。

| 端点 | 方法 | Auth | 说明 |
|------|------|------|------|
| `/auth/login` | GET | — | 重定向到 Google OAuth |
| `/auth/callback` | GET | — | OAuth 回调，建立会话 |
| `/auth/me` | GET | Session | 当前用户信息 |
| `/auth/logout` | POST | Session | 登出，清除会话 |
| `/api/setup/test-flex` | POST | Required | 测试 Flex 凭证（不保存）|
| `/api/setup/configure` | POST | Required | 保存 Flex 凭证并触发首次拉取 |
| `/api/setup/status` | GET | Required | Flex 配置状态 |
| `/api/portfolio` | GET | Required | 最新持仓与分类汇总 |
| `/api/targets` | GET/POST | Required | 读取/保存目标占比 |
| `/api/accounts` | GET | Required | 子账户列表 |
| `/api/status` | GET | Required | 上次刷新时间、冷却剩余、连接状态 |
| `/api/trigger-refresh` | GET | Required | 手动触发刷新（带冷却限制）|
| `/api/admin/users` | GET | Admin | 列出所有用户及其状态 |

---

## 数据架构

```
IBKR Flex Web Service
        │  flex_client.py  (两步轮询，到达即落盘)
        ▼
   原始 XML ──→ S3（可选，用于审计与重解析）
        │  flex_parser.py
        ▼
   结构化数据 ──→ storage.py ──→ PostgreSQL
        │  (所有数据表以 user_id 分区)
        ▼
   Flask API ──→ React SPA（ECharts 渲染）
        │  (需 Google OAuth 登录)
```

**数据表（全部按 `user_id` 隔离）：**

| 表 | 用途 |
|----|------|
| `users` | 用户身份、加密 Flex 凭证、刷新状态 |
| `sessions` | 服务端会话记录 |
| `accounts` | 每账户 NAV 组成 + 档案元数据 |
| `positions` | 每日持仓快照 |
| `targets` | 每用户每账户的目标占比 |
| `fetch_log` | 数据拉取审计日志 |

- **按报表周期拉取**：后台每小时使用 `ThreadPoolExecutor` 并行刷新所有已配置用户
- **S3 冗余**：原始 XML 上传 S3 并验证后再写 DB

---

## 技术栈

| 层 | 方案 |
|----|------|
| 认证 | Google OAuth 2.0 (auth code flow) + Flask signed cookies + 服务端会话表 |
| 加密 | Fernet (cryptography) 对称加密用户 Flex Token |
| 前端 | Vite + React 18 + TypeScript + Tailwind CSS v4，ECharts 5 |
| 后端 | Python Flask 3 + APScheduler + ThreadPoolExecutor |
| 数据库 | PostgreSQL（连接池）|
| 原始存储 | S3 兼容（AWS S3 / Cloudflare R2 / MinIO），可选 |
| 部署 | 前端构建产物由 Flask 托管，单进程启动 |

---

## Roadmap

- [ ] **T-01** 持仓占比日变动 — 图例/再平衡表中展示各持仓相较前一交易日的占比变化（±pp）
- [ ] **T-02** 下单清单导出 — 把买卖金额换算成股数，便于直接下单
- [ ] **T-03** 目标归一化 — 一键将目标按比例缩放到合计 100%
- [ ] **T-04** 多币种现金明细（CashReport Currency 级 CNH/HKD 行）
- [ ] **T-05** 股票借出视图（SYEP 借出量）

---

## License

MIT
