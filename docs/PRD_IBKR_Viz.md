# Product specification — IBKR Portfolio Viz

## Purpose

IBKR Portfolio Viz turns each user's latest Interactive Brokers Flex statement into a private dashboard for daily portfolio visibility and ticker-level target allocation.

## Capabilities

### Access and dashboard

- Google OAuth, server-side sessions, encrypted Flex credentials and `user_id` data isolation provide private access.
- Consolidated and per-account views show NAV, cash, daily P&L, holdings and account metadata.
- Linked charts, sortable holdings, amount masking, responsive layouts and light/dark themes support portfolio analysis.

### Allocation

- Securities values drive ticker allocation, target weights, drift and buy/sell estimates; portfolio totals include cash and margin balances.
- Targets are stored per user and account view. Largest-remainder rounding produces displayed weights totalling 100.0%.

### Refresh

- `fetch_and_store` serves credential tests, manual refreshes and the hourly scheduler.
- Refreshes check PostgreSQL, local XML and canonical S3/R2 storage in sequence, then request IBKR Flex data.
- Parsed reports update PostgreSQL, local cache and canonical report-date archives.
- Market-timezone scheduling, expanding refresh intervals and per-user serialization coordinate updates.

## Flex data contract

The parser expects one or more `FlexStatement` elements containing:

| Flex section | Stored or displayed data |
| --- | --- |
| `AccountInformation` | Alias, account type, SYEP/DRIP state, tax-lot method, open date |
| `EquitySummaryInBase` | Current and previous NAV, stock/options values, cash and accruals |
| `MTMPerformanceSummaryInBase` | Account and per-position daily P&L, previous close data |
| `OpenPositions` | Position value, quantity, cost/P&L data, asset and option metadata |

The report date comes from each statement's `toDate`. Current dashboard totals use the latest stored position date and account summary rows.

## Architecture

```mermaid
flowchart TD
    USER["User"] --> UI["React dashboard"]
    UI --> API["Flask API"]
    OAUTH["Google OAuth"] --> API
    API --> DB[("PostgreSQL")]
    AUTO["Hourly scheduler"] --> REFRESH["Refresh pipeline"]
    MANUAL["Manual refresh"] --> REFRESH
    REFRESH --> CACHE["PostgreSQL → local XML → S3/R2"]
    CACHE --> IBKR["IBKR Flex API"]
    IBKR --> PARSER["Flex parser"]
    PARSER --> DB
    PARSER --> ARCHIVE[("Local XML and S3/R2 archive")]
```

Flask serves the React bundle and API, APScheduler runs hourly refreshes, and PostgreSQL stores users, sessions, accounts, positions, targets and fetch history.
