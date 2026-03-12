# dashboard/database.py
import aiosqlite
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = Path(__file__).parent / "trades.db"


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     TEXT    NOT NULL,
                mode          TEXT    NOT NULL,
                symbol        TEXT    NOT NULL,
                direction     TEXT    NOT NULL,
                entry         REAL,
                sl            REAL,
                tp            REAL,
                contracts     INTEGER,
                risk_usd      REAL,
                status        TEXT    DEFAULT 'open',
                exit_price    REAL,
                pnl_usd       REAL,
                closed_at     TEXT
            )
        """)
        await db.commit()


async def insert_trade(trade: Dict[str, Any]) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO trades
                (timestamp, mode, symbol, direction, entry, sl, tp,
                 contracts, risk_usd, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """,
            (
                trade["timestamp"],
                trade["mode"],
                trade["symbol"],
                trade["direction"],
                trade.get("entry"),
                trade.get("sl"),
                trade.get("tp"),
                trade.get("contracts"),
                trade.get("risk_usd"),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def close_trade(
    trade_id: int,
    status: str,
    exit_price: Optional[float],
    pnl_usd: Optional[float],
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE trades
            SET status = ?, exit_price = ?, pnl_usd = ?, closed_at = ?
            WHERE id = ?
            """,
            (status, exit_price, pnl_usd, datetime.utcnow().isoformat(), trade_id),
        )
        await db.commit()


async def get_all_trades() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_stats() -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cur = await db.execute("SELECT COUNT(*) as total FROM trades")
        total = (await cur.fetchone())["total"]

        cur = await db.execute(
            "SELECT COUNT(*) as n FROM trades WHERE status = 'tp_hit'"
        )
        wins = (await cur.fetchone())["n"]

        cur = await db.execute(
            "SELECT COUNT(*) as n FROM trades WHERE status = 'sl_hit'"
        )
        losses = (await cur.fetchone())["n"]

        cur = await db.execute(
            "SELECT COALESCE(SUM(pnl_usd), 0) as total_pnl FROM trades WHERE pnl_usd IS NOT NULL"
        )
        total_pnl = (await cur.fetchone())["total_pnl"]

        cur = await db.execute(
            "SELECT COALESCE(MAX(pnl_usd), 0) as best FROM trades WHERE pnl_usd IS NOT NULL"
        )
        best = (await cur.fetchone())["best"]

        cur = await db.execute(
            "SELECT COALESCE(MIN(pnl_usd), 0) as worst FROM trades WHERE pnl_usd IS NOT NULL"
        )
        worst = (await cur.fetchone())["worst"]

        # PnL por día para la curva de equity
        cur = await db.execute(
            """
            SELECT substr(timestamp, 1, 10) as day,
                   COALESCE(SUM(pnl_usd), 0) as day_pnl
            FROM trades
            WHERE pnl_usd IS NOT NULL
            GROUP BY day
            ORDER BY day
            """
        )
        daily_pnl = [dict(r) for r in await cur.fetchall()]

        closed = wins + losses
        win_rate = round(wins / closed * 100, 1) if closed else 0

        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "open": total - closed,
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "best_trade": round(best, 2),
            "worst_trade": round(worst, 2),
            "daily_pnl": daily_pnl,
        }
