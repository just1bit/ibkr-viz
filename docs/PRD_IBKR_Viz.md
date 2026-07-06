# PRD — IBKR Portfolio Viz

A lightweight web tool for IBKR investors to visualize position weights, monitor allocation drift, and plan rebalancing. Cash is treated as a position — every dollar of the portfolio is accounted for.

## Users

- Individual IBKR investors managing equity/option portfolios
- Those with target asset allocations who rebalance periodically
- Multi-account holders who need consolidated or per-account views

## Features

### Data Pipeline

- Fetch from IBKR Flex Web Service on demand or via scheduled refresh
- XML saved locally, archived to S3, parsed into PostgreSQL
- Fallback chain: DB → S3 → local cache (IBKR called at most once per fetch cycle)
- Hourly background scheduler, market-timezone-aware, with retry backoff

### Accounts & Overview

- Multi-account detection with aliases and metadata badges
- KPI cards: net liquidation, day P&L, equity breakdown, cash with accruals
- One-click hide amounts for privacy

### Positions & Allocation

- Donut chart: ticker and asset class views with hover-linked legend
- Day P&L attribution bar chart per position
- Sortable positions table with cost basis, option details, day-change tags

### Rebalancing

- Side-by-side current vs. target weight, drift in percentage points, buy/sell suggestions
- Targets persist per account to the server
- Reset to current weights, save to keep

### NAV & Income

- NAV composition: stock, options, cash, dividend/interest accruals
- Income summary from CashReport with MTD/YTD toggle

### UX

- Light/dark theme with system preference detection
- Responsive layout
- Google OAuth login with per-user data isolation

## Data Architecture

```
IBKR Flex → Raw XML → Local cache → S3 archive
                  ↓
              Parser → PostgreSQL (user-scoped)
                  ↓
              Flask API → React SPA
```

**Six tables:** users, sessions, accounts (NAV + metadata), positions, targets, fetch_log. All scoped by `user_id`.

## Tech Stack

| Layer | Stack |
|-------|-------|
| Frontend | React + TypeScript + Tailwind CSS + ECharts |
| Backend | Python Flask + APScheduler + gunicorn |
| Database | PostgreSQL |
| Storage | S3-compatible (optional) |
| Auth | Google OAuth 2.0 + server-side sessions |

## Roadmap

- Position weight day-over-day change display
- Rebalance export as order-ready share quantities
- Target weight normalization
- Multi-currency cash breakdown
- Stock lending (SYEP) view
