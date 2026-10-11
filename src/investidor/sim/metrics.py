"""Métricas de desempenho e risco a partir de uma curva de patrimônio diária (dias corridos)."""
from __future__ import annotations

import numpy as np
import pandas as pd

PERIODS = 365  # a curva tem uma observação por dia corrido


def daily_returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def years_between(equity: pd.Series) -> float:
    return max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)


def max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1.0).min())


def performance(equity: pd.Series, rf_daily: pd.Series | None = None) -> dict:
    """Métricas principais. Sharpe/Sortino usam excesso sobre o CDI quando `rf_daily` é dado."""
    eq = equity.dropna()
    if len(eq) < 3 or eq.iloc[0] <= 0:
        return {"n_days": len(eq)}
    r = daily_returns(eq)
    yrs = years_between(eq)
    total = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1.0 / yrs) - 1.0) if eq.iloc[-1] > 0 else -1.0
    vol = float(r.std(ddof=1) * np.sqrt(PERIODS))
    ex = r - (rf_daily.reindex(r.index).fillna(0.0) if rf_daily is not None else 0.0)
    sd = float(ex.std(ddof=1))
    sharpe = float(ex.mean() / sd * np.sqrt(PERIODS)) if sd > 0 else float("nan")
    dn = ex[ex < 0]
    dsd = float(np.sqrt((dn ** 2).sum() / len(ex))) if len(ex) else 0.0
    sortino = float(ex.mean() / dsd * np.sqrt(PERIODS)) if dsd > 0 else float("nan")
    mdd = max_drawdown(eq)
    return {
        "n_days": int(len(eq)), "years": round(yrs, 3), "total_return": total, "cagr": cagr,
        "vol": vol, "sharpe": sharpe, "sortino": sortino, "max_drawdown": mdd,
        "calmar": float(cagr / abs(mdd)) if mdd < 0 else float("nan"),
        "best_day": float(r.max()), "worst_day": float(r.min()),
        "final": float(eq.iloc[-1]),
    }


def period_returns(equity: pd.Series, freq: str = "YE") -> dict[str, float]:
    ends = equity.resample(freq).last()
    prev = ends.shift(1)
    prev.iloc[0] = equity.iloc[0]
    out = (ends / prev - 1.0).dropna()
    return {str(i.year) if freq == "YE" else str(i.date()): float(v) for i, v in out.items()}


def risk_summary(equity: pd.Series) -> dict:
    """Risco de uma carteira: volatilidade, VaR/CVaR histórico 95%, drawdown atual e máximo."""
    eq = equity.dropna()
    out = {"current_drawdown": float(eq.iloc[-1] / eq.cummax().iloc[-1] - 1.0),
           "max_drawdown": max_drawdown(eq) if len(eq) > 1 else 0.0,
           "days_since_peak": int((eq.index[-1] - eq.idxmax()).days)}
    r = daily_returns(eq)
    if len(r) >= 20:
        out["vol_annual"] = float(r.std(ddof=1) * np.sqrt(PERIODS))
        q = float(np.quantile(r, 0.05))
        out["var95_1d"] = q
        out["cvar95_1d"] = float(r[r <= q].mean())
    return out
