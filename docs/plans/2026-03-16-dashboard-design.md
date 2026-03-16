# Trading Dashboard — Design Document

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create the implementation plan from this design.

**Goal:** Build a mobile-friendly web dashboard and Telegram bot to monitor the OpenClaw trading system — live cockpit during RTH, review tool after hours.

**Architecture:** FastAPI backend reads existing data files + Redis streams (read-only), React SPA frontend with TradingView Lightweight Charts + Recharts, Telegram bot in same API process. No new database.

---

## 1. Architecture

Three logical components, two Docker containers:

1. **FastAPI backend + Telegram bot** (`dashboard-api`) — REST API reading existing data files (`portfolio.json`, `ledger.jsonl`, `posture_state.json`, etc.) and Redis streams. Telegram bot runs as background task in same process.
2. **React frontend** (`dashboard-ui`) — Vite + React SPA served by nginx. TailwindCSS, TradingView Lightweight Charts, Recharts.

Data flow:
```
portfolio.json ─┐
ledger.jsonl   ─┤
posture_state  ─┼──▶ FastAPI ──▶ React SPA (browser)
alerts.log     ─┤       │
slippage.json  ─┤       └──▶ Telegram Bot
Redis streams  ─┘
```

No new database. Pure read-only layer on existing data. Separate `docker-compose.dashboard.yaml` — does not modify existing trading docker-compose.

---

## 2. Web Dashboard Layout

### Page 1: Live Overview (default)

```
┌─────────────────────────────────┬──────────────────────────┐
│  Portfolio Summary              │  Sentinel Posture        │
│  - Equity / Opening / Peak      │  - Current posture       │
│  - Today P&L ($ and %)          │  - DD% vs thresholds     │
│  - Drawdown % with bar          │  - Streak count          │
│  - Heat (open risk %)           │  - Time in posture       │
├─────────────────────────────────┴──────────────────────────┤
│  Open Positions Table                                      │
│  Symbol | Side | Contracts | Entry | Current | Unreal P&L  │
│  Stop | Target | Strategy | Hold Time                      │
├────────────────────────────┬───────────────────────────────┤
│  Active Signals            │  Alert History                │
│  - News (tier, headline,   │  - Last 20 alerts            │
│    instruments)            │  - Color by level            │
│  - Polymarket (drift,      │  - Timestamp + message       │
│    strength)               │                               │
└────────────────────────────┴───────────────────────────────┘
```

### Page 2: Analytics & Review

```
┌───────────────────────────────────────────────────────────┐
│  Equity Curve (TradingView Lightweight Charts)            │
│  - Line chart from DAILY_SNAPSHOT ledger events           │
│  - Drawdown overlay                                       │
├─────────────────────────────┬─────────────────────────────┤
│  Recent Trades              │  Strategy Health             │
│  - Last 50 POSITION_CLOSED  │  - Per-strategy health score │
│  - Slippage per fill        │  - Win rate, trade count    │
│  - P&L per trade            │  - Incubation progress bar  │
├─────────────────────────────┴─────────────────────────────┤
│  Regime State (Recharts)                                   │
│  - Per-instrument current regime (bar chart)               │
│  - Vol driver values (VIX/ATR/MOVE)                       │
│  - Regime history over last 5 days (stacked area)         │
└───────────────────────────────────────────────────────────┘
```

Navigation: Top nav with "Live" and "Analytics" tabs, manual refresh button, "last updated" timestamp. Mobile: panels stack vertically, tables become scrollable cards.

---

## 3. API Endpoints

| Endpoint | Returns | Source |
|---|---|---|
| `GET /api/portfolio` | Equity, PnL, positions, heat, posture | `portfolio.json` + `posture_state.json` |
| `GET /api/signals` | Active news + Polymarket signals | Redis streams |
| `GET /api/alerts?limit=20` | Recent alerts | `alerts.log` |
| `GET /api/trades?limit=50` | Recent closed trades with P&L, slippage | `ledger.jsonl` (POSITION_CLOSED + FILL_SLIPPAGE) |
| `GET /api/equity-curve?days=30` | Daily equity snapshots | `ledger.jsonl` (DAILY_SNAPSHOT) |
| `GET /api/health` | Per-strategy health + incubation | `strategies/*.json` + ledger |
| `GET /api/regime` | Per-instrument regime + drivers | `intraday_regime.json` + ledger |

All GET-only. No authentication for v1 (localhost). Plain JSON responses.

---

## 4. Telegram Bot Commands

| Command | Output |
|---|---|
| `/status` | Equity, today P&L, DD%, posture, position count |
| `/positions` | Per-position: symbol, side, contracts, entry, current, unrealized P&L, stop |
| `/signals` | Active news + Polymarket signals |
| `/alerts` | Last 5 alerts with timestamp and level |
| `/pnl` | Today's P&L: realized, unrealized, by-position, vs opening equity |
| `/health` | Per-strategy: health score, win rate, trade count, status |
| `/regime` | Per-instrument: regime type, vol driver, score |

Bot responds only to configured `TELEGRAM_CHAT_ID`. Reuses same data-reading functions as API.

---

## 5. Tech Stack

**Backend:** FastAPI, uvicorn, python-telegram-bot, redis
**Frontend:** React 18, react-router-dom, Vite, TailwindCSS, lightweight-charts (TradingView), Recharts, axios
**Docker:** dashboard-api (Python), dashboard-ui (nginx), extends existing docker-compose

---

## 6. File Structure

```
dashboard/
├── api/
│   ├── main.py
│   ├── routers/
│   │   ├── portfolio.py
│   │   ├── signals.py
│   │   ├── alerts.py
│   │   ├── trades.py
│   │   ├── equity_curve.py
│   │   ├── health.py
│   │   └── regime.py
│   ├── telegram_bot.py
│   ├── data_readers.py
│   ├── requirements.txt
│   └── Dockerfile
├── ui/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── LiveOverview.tsx
│   │   │   └── Analytics.tsx
│   │   ├── components/
│   │   │   ├── PortfolioSummary.tsx
│   │   │   ├── PostureCard.tsx
│   │   │   ├── PositionsTable.tsx
│   │   │   ├── SignalsPanel.tsx
│   │   │   ├── AlertsPanel.tsx
│   │   │   ├── EquityCurve.tsx
│   │   │   ├── TradesTable.tsx
│   │   │   ├── HealthPanel.tsx
│   │   │   └── RegimePanel.tsx
│   │   ├── hooks/
│   │   │   └── useApi.ts
│   │   └── api.ts
│   ├── index.html
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   ├── package.json
│   ├── Dockerfile
│   └── nginx.conf
└── docker-compose.dashboard.yaml
```

---

## 7. Testing

- ~30-40 backend pytest tests: data_readers, each router endpoint, telegram command handlers
- fakeredis for signal tests
- No frontend unit tests for v1 — visual verification
- Manual smoke test: docker-compose up, verify endpoints + Telegram commands + mobile layout
