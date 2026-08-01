# IBKR Portfolio Viz

A multi-tenant portfolio allocation & rebalancing tool for Interactive Brokers accounts. Google OAuth login, per-user IBKR Flex credentials, strict data isolation.

## Quick Start

```bash
# Install dependencies
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt

# Initialize database (first time only)
psql -d <dbname> -f backend/schema.sql

# Configure
cp config.example.yaml config.local.yaml
# Fill in PostgreSQL URL, Google OAuth credentials, encryption keys

# Build frontend
cd frontend && npm install && npm run build && cd ..

# Run
python backend/app.py
```

After startup, users sign in with Google and enter their IBKR Flex credentials on the Setup page.

## Configuration

All settings in `config.local.yaml` (git-ignored). Required keys:

| Key | Purpose |
|-----|---------|
| `postgres_url` | PostgreSQL connection string |
| `google_client_id` / `google_client_secret` | OAuth 2.0 credentials from Google Cloud Console |
| `base_url` | Public URL of the app, used for OAuth redirect |
| `secret_key` | Flask session signing key |
| `flex_encryption_key` | Fernet key for encrypting user Flex tokens at rest |

Flex credentials (token + query ID) are entered by each user through the UI and stored encrypted in the database.

## Architecture

```
IBKR Flex Web Service
        │  flex_client.py
        ▼
   Raw XML ──→ S3 archive ──→ Local cache
        │  flex_parser.py
        ▼
   PostgreSQL ──→ Flask API ──→ React SPA
```

**Data flow:** IBKR is called exactly once per fetch. XML is saved locally, archived to S3, parsed into PostgreSQL. Subsequent reads use DB → S3 → local cache fallback chain without calling IBKR.

**Scheduler:** Background job refreshes all users hourly, based on market timezone (America/New_York by default).

**One-time release tasks:** Run the `Run release task` GitHub Actions
workflow manually and enter a directory name under `release_tasks/`. The
workflow validates the name and executes that directory's `run.sh`. Each task
owns its dependencies and behavior, so new one-time requirements do not need
changes to the workflow. The runner supplies the repository's scoped Azure
identity; each task obtains only the settings it needs. No application table
or custom execution history is created; rerunning a task executes it again.

For the XML-native data release, run `xml-native-values` before deploying the
business-code change. It adds the two required columns, downloads every stored
snapshot's exact raw XML from S3, validates all keys and values, and commits the
backfill only after the complete source set passes validation.

**Tables (all scoped by `user_id`):**

| Table | Purpose |
|-------|---------|
| `users` | Identity, encrypted Flex credentials, refresh state |
| `sessions` | Server-side session records |
| `accounts` | Per-account NAV breakdown + metadata |
| `positions` | Daily position snapshots |
| `targets` | Per-user per-account target allocations |
| `fetch_log` | Refresh audit trail |

## Features

- Google OAuth login with server-side session validation
- Per-user IBKR Flex credentials, encrypted at rest
- Donut chart: holdings & asset class views with linked legend interaction
- Day P&L attribution bar chart per position
- Sortable positions table with cost basis, option details, day-change indicators
- Cash included as a position in all views
- Rebalance table: current vs. target weight, drift, buy/sell suggestions; targets saved per account
- NAV composition: equity, options, cash, dividend & interest accruals
- Multi-account support with aliases, account type, SYEP/DRIP badges
- Light/dark theme, responsive layout, one-click hide amounts

## Tech Stack

| Layer | Stack |
|-------|-------|
| Auth | Google OAuth 2.0 + Flask signed cookies |
| Frontend | React 18 + TypeScript + Tailwind CSS v4 + ECharts 5 |
| Backend | Python Flask + APScheduler + gunicorn |
| Database | PostgreSQL |
| Object storage | S3-compatible (optional) |
| Encryption | Fernet (cryptography) |

## License

MIT
