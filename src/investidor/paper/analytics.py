"""Leitura do livro-razão/equity e métricas da simulação em andamento."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..sim.metrics import performance, risk_summary
from .ledger import read_equity, read_trades


def equity_series(state_dir: Path, run_id: str | None) -> dict[str, pd.Series]:
    rows = [r for r in read_equity(state_dir / "equity.csv") if run_id is None or r["run_id"] == run_id]
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r["portfolio"], []).append((pd.Timestamp(r["date"]), float(r["equity"])))
    series = {}
    for sid, pts in out.items():
        s = pd.Series({d: v for d, v in pts}).sort_index()
        series[sid] = s
    return series


def status_series(state_dir: Path, run_id: str | None) -> dict[str, str]:
    st = {}
    for r in read_equity(state_dir / "equity.csv"):
        if run_id is None or r["run_id"] == run_id:
            st[r["portfolio"]] = r["status"]
    return st


def summarize_portfolio(s: pd.Series, initial: float) -> dict:
    cur = float(s.iloc[-1])
    out = {"initial": initial, "equity": cur, "pnl": cur - initial, "return": cur / initial - 1.0,
           "days": int(len(s) - 1)}
    out.update(risk_summary(s) if len(s) > 1 else {"current_drawdown": 0.0, "max_drawdown": 0.0})
    if len(s) >= 30:
        out["performance"] = performance(s)
    return out


def recent_trades(state_dir: Path, run_id: str | None, limit: int = 200) -> list[dict]:
    rows = read_trades(state_dir / "trades.csv")
    if run_id:
        rows = [r for r in rows if r["run_id"] == run_id]
    keep = ["seq", "date", "portfolio", "asset", "side", "qty", "price_native", "fx", "fill_price_brl",
            "notional_brl", "fee_brl", "reason", "mode"]
    return [{k: r[k] for k in keep} for r in rows[-limit:]][::-1]
