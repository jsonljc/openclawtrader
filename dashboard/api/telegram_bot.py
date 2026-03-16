# dashboard/api/telegram_bot.py
"""Telegram bot command handlers for OpenClaw dashboard."""
from __future__ import annotations

import os
import logging
from dashboard.api.data_readers import (
    read_portfolio, read_alerts, read_trades, read_signals, read_health, read_regime,
)

logger = logging.getLogger(__name__)


def format_status() -> str:
    try:
        p = read_portfolio()
        acct = p.get("account", {})
        pnl = p.get("pnl", {})
        equity = acct.get("equity_usd", 0)
        today = pnl.get("total_today_usd", 0)
        today_pct = pnl.get("total_today_pct", 0)
        dd = pnl.get("portfolio_dd_pct", 0)
        posture = p.get("sentinel_posture", "?")
        positions = len(p.get("positions", []))
        sign = "+" if today >= 0 else ""
        return (
            f"Equity: ${equity:,.0f} | "
            f"Today: {sign}${today:,.0f} ({sign}{today_pct:.2f}%) | "
            f"DD: {dd:.1f}% | "
            f"Posture: {posture} | "
            f"Positions: {positions}"
        )
    except Exception as e:
        return f"Error reading status: {e}"


def format_positions() -> str:
    try:
        p = read_portfolio()
        positions = p.get("positions", [])
        if not positions:
            return "No open positions"
        lines = []
        for pos in positions:
            sym = pos.get("symbol", "?")
            side = pos.get("side", "?")
            contracts = pos.get("contracts", 0)
            entry = pos.get("entry_price", 0)
            current = pos.get("current_price", 0)
            pnl = pos.get("unrealized_pnl_usd", 0)
            stop = pos.get("stop_price", 0)
            sign = "+" if pnl >= 0 else ""
            lines.append(
                f"{sym} {side} {contracts}x @ {entry:,.2f} → {current:,.2f} "
                f"({sign}${pnl:,.0f}) stop:{stop:,.2f}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading positions: {e}"


def format_signals() -> str:
    try:
        signals = read_signals()
        lines = []
        for s in signals.get("news", [])[:5]:
            tier = s.get("tier", "?")
            headline = s.get("headline", "")[:80]
            instruments = s.get("instruments", [])
            lines.append(f"{tier}: \"{headline}\" [{' '.join(instruments)}]")
        for s in signals.get("polymarket", [])[:3]:
            sig_type = s.get("type", "?")
            strength = s.get("strength", "?")
            market = s.get("market_question", "")[:60]
            lines.append(f"Polymarket {sig_type} ({strength}): {market}")
        if not lines:
            return "No active signals"
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading signals: {e}"


def format_alerts() -> str:
    try:
        alerts = read_alerts(limit=5)
        if not alerts:
            return "No recent alerts"
        lines = []
        for a in alerts:
            ts = a.get("ts", "?")[:19]
            level = a.get("level", "?")
            msg = a.get("message", "")
            lines.append(f"[{ts}] {level}: {msg}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading alerts: {e}"


def format_pnl() -> str:
    try:
        p = read_portfolio()
        acct = p.get("account", {})
        pnl = p.get("pnl", {})
        opening = acct.get("opening_equity_usd", 0)
        equity = acct.get("equity_usd", 0)
        realized = pnl.get("realized_today_usd", 0)
        unrealized = pnl.get("unrealized_usd", 0)
        total = pnl.get("total_today_usd", 0)
        pct = pnl.get("total_today_pct", 0)
        positions = p.get("positions", [])
        lines = [
            f"Opening: ${opening:,.0f}",
            f"Current: ${equity:,.0f}",
            f"Realized: ${realized:+,.0f}",
            f"Unrealized: ${unrealized:+,.0f}",
            f"Total: ${total:+,.0f} ({pct:+.2f}%)",
        ]
        if positions:
            lines.append("\nBy position:")
            for pos in positions:
                sym = pos.get("symbol", "?")
                upnl = pos.get("unrealized_pnl_usd", 0)
                lines.append(f"  {sym}: ${upnl:+,.0f}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading PnL: {e}"


def format_health() -> str:
    try:
        registry = read_health()
        if not registry:
            return "No strategies loaded"
        lines = []
        for sid, cfg in sorted(registry.items()):
            status = cfg.get("status", "?")
            incub = cfg.get("incubation", {})
            is_incub = incub.get("is_incubating", False)
            badge = " [INCUB]" if is_incub else ""
            lines.append(f"{sid}: {status}{badge}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading health: {e}"


def format_regime() -> str:
    try:
        regime = read_regime()
        if not regime:
            return "No regime data"
        lines = []
        for sym, r in sorted(regime.items()):
            rtype = r.get("regime_type", "?")
            driver = r.get("vol_driver", "?")
            val = r.get("vol_value", 0)
            score = r.get("score", 0)
            lines.append(f"{sym}: {rtype} ({driver}: {val}) score={score}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading regime: {e}"


async def setup_telegram_bot(app) -> None:
    """Start the Telegram bot as a background task in the FastAPI app."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.info("Telegram bot not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return

    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes, filters

        tg_app = Application.builder().token(token).build()

        # Only respond to the configured chat
        chat_filter = filters.Chat(chat_id=int(chat_id))

        async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_status())

        async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_positions())

        async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_signals())

        async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_alerts())

        async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_pnl())

        async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_health())

        async def cmd_regime(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_regime())

        tg_app.add_handler(CommandHandler("status", cmd_status, filters=chat_filter))
        tg_app.add_handler(CommandHandler("positions", cmd_positions, filters=chat_filter))
        tg_app.add_handler(CommandHandler("signals", cmd_signals, filters=chat_filter))
        tg_app.add_handler(CommandHandler("alerts", cmd_alerts, filters=chat_filter))
        tg_app.add_handler(CommandHandler("pnl", cmd_pnl, filters=chat_filter))
        tg_app.add_handler(CommandHandler("health", cmd_health, filters=chat_filter))
        tg_app.add_handler(CommandHandler("regime", cmd_regime, filters=chat_filter))

        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling()
        logger.info("Telegram bot started")

    except ImportError:
        logger.warning("python-telegram-bot not installed -- Telegram bot disabled")
    except Exception as e:
        logger.error(f"Failed to start Telegram bot: {e}")
