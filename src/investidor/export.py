"""Monta o 'snapshot' consumido pelo painel (JSON) e pelo relatório (Markdown)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import __version__
from .config import Config
from .data.panel import Panel
from .data.store import MarketData, quality_summary
from .feasibility import asset_feasibility, golive_gate, scenarios
from .paper import analytics
from .paper.ledger import read_json, read_jsonl, verify_ledger
from .sim.backtest import _clean
from .strategies.base import Strategy


def _curve(s: pd.Series) -> list[list]:
    return [[str(d.date()), round(float(v), 4)] for d, v in s.items()]


def _slim_backtest(bt: dict | None) -> dict | None:
    if not bt:
        return None
    keep = ["id", "name", "family", "experimental", "passive", "cagr", "vol", "sharpe", "sortino", "max_drawdown",
            "calmar", "total_return", "final", "n_trades", "trades_per_year", "turnover_per_year",
            "cost_drag_per_year", "avg_exposure", "psr_vs_zero", "dsr", "excess_cagr_vs_cdi", "vs_cdi",
            "vs_ew_all", "cagr_h1", "cagr_h2", "sharpe_h1", "sharpe_h2", "by_year", "r50", "ex_winners"]
    out = {k: bt.get(k) for k in ("kind", "generated_at", "as_of", "period", "initial_brl", "paper_initial_brl",
                                  "universe", "n_trials", "cdi", "curves", "robustness", "assumptions")}
    out["leaderboard"] = [{k: r.get(k) for k in keep} for r in bt.get("leaderboard", [])]
    wf = {}
    for fam, d in (bt.get("walk_forward") or {}).items():
        wf[fam] = {k: d.get(k) for k in ("family", "n_combos", "oos_start", "oos_end", "oos",
                                         "default_params_same_window", "cdi_same_window", "oos_curve",
                                         "cdi_curve", "windows", "error")}
    out["walk_forward"] = wf
    return out


def build_snapshot(cfg: Config, state_dir: Path, panel: Panel, md: MarketData, strategies: dict[str, Strategy],
                   control: dict, paper: dict, alerts_all: list[dict], backtest: dict | None,
                   diagnostics: dict, as_of_idx: int) -> dict:
    run_id = paper.get("run_id") if paper.get("active") or paper.get("run_id") else None
    series = analytics.equity_series(state_dir, run_id) if run_id else {}
    statuses = analytics.status_series(state_dir, run_id) if run_id else {}
    initial = paper.get("initial", cfg.paper_initial)
    portfolios = []
    for sid, port in paper.get("portfolios", {}).items():
        s = series.get(sid)
        if s is None or s.empty:
            continue
        dd = (s / s.cummax() - 1.0)
        info = strategies[sid].info()
        portfolios.append({
            "id": sid, "name": info["name"], "family": info["family"], "description": info["description"],
            "passive": info["family"] == "passiva", "experimental": info["experimental"],
            "status": statuses.get(sid, port["status"]), "halt_reason": port.get("halt_reason"),
            "summary": analytics.summarize_portfolio(s, port["sim"]["initial"]),
            "positions": port.get("positions", []), "cash": port["sim"]["cash"],
            "fees_paid": port["sim"]["fees_paid"], "slippage_paid": port["sim"]["slippage_paid"],
            "dividends": port["sim"]["dividends_received"],
            "curve": _curve(s), "dd_curve": _curve(dd),
        })
    cdi_curve = []
    start = paper.get("start_date")
    if start:
        i0 = panel.index_of(start)
        eq = initial * (1 + pd.Series(panel.rf[i0 + 1:as_of_idx + 1], index=panel.dates[i0 + 1:as_of_idx + 1])).cumprod()
        eq = pd.concat([pd.Series([initial], index=[panel.dates[i0]]), eq])
        cdi_curve = _curve(eq)
    primary = next((p for p in portfolios if p["id"] == cfg.primary_strategy), None)
    paper_days = primary["summary"]["days"] if primary else 0
    feas = asset_feasibility(cfg, panel, cfg.paper_initial)
    crit30 = sum(1 for a in alerts_all[-500:] if a["severity"] == "critical"
                 and a["date"] >= str((panel.dates[as_of_idx] - pd.Timedelta(days=30)).date()))
    gate = golive_gate(cfg, primary, backtest, paper_days, crit30, feas)
    ok, why = verify_ledger(state_dir / "trades.csv")
    runs = read_jsonl(state_dir / "runs.jsonl", last=12)
    snap = {
        "schema": 1, "version": __version__, "repo": os.environ.get("GITHUB_REPOSITORY"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": str(panel.dates[as_of_idx].date()),
        "labels": {
            "modo": "PAPER (simulação)", "dinheiro_real_movimentado_brl": 0.0,
            "capital_real_reservado_brl": cfg.paper_initial,
            "aviso": "Todos os valores de carteira são FICTÍCIOS. Preços de mercado são dados reais. "
                     "Backtests são histórico simulado. Nenhuma ordem real é enviada.",
        },
        "control": {k: control.get(k) for k in ("state", "updated_at", "updated_by", "history")},
        "run": {"run_id": paper.get("run_id"), "active": paper.get("active", False),
                "start_date": paper.get("start_date"), "initial": initial,
                "closed_runs": paper.get("closed_runs", [])[-5:]},
        "primary": cfg.primary_strategy, "portfolios": portfolios, "cdi_curve": cdi_curve,
        "trades": analytics.recent_trades(state_dir, run_id),
        "alerts": alerts_all[-60:][::-1],
        "backtest": _slim_backtest(backtest),
        "feasibility": {"capital": cfg.paper_initial, "assets": feas, "scenarios": scenarios(cfg.paper_initial),
                        "max_positions": cfg.execution.max_positions, "min_order_brl": cfg.execution.min_order_brl},
        "golive": gate,
        "data": {**quality_summary(md), "universe_used": panel.ids},
        "diagnostics": diagnostics,
        "ledger": {"integrity_ok": ok, "detail": why},
        "last_runs": runs,
        "risk_limits": {"max_drawdown_halt": cfg.risk.max_drawdown_halt,
                        "alert_levels": list(cfg.risk.drawdown_alert_levels),
                        "max_positions": cfg.execution.max_positions, "min_cash": cfg.execution.min_cash,
                        "leverage": "proibida", "short": "proibido", "martingale": "proibido",
                        "saque_automatico": "inexistente"},
        "costs": {k: {"fee_bps": v.fee_bps, "spread_bps": v.spread_bps, "slippage_bps": v.slippage_bps,
                      "entry_extra_bps": v.entry_extra_bps, "exit_extra_bps": v.exit_extra_bps}
                  for k, v in cfg.costs.items()},
        "strategies": {sid: s.info() for sid, s in strategies.items()},
    }
    return _clean(snap)
