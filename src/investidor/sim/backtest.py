"""Backtest completo: placar das estratégias, referências passivas, walk-forward e robustez.

Todos os números daqui são HISTÓRICOS/SIMULADOS (com custos), não resultados reais, e sofrem
de viés de sobrevivência/retrospecto (o universo foi escolhido hoje). O teste decisivo é o
paper trading "para frente".
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..config import Config
from ..data.panel import Panel
from ..strategies.base import Ctx, Strategy
from ..strategies.registry import GRIDS, PASSIVE_IDS
from . import stats
from .engine import SimResult, cdi_benchmark, run_simulation
from .metrics import daily_returns, performance, period_returns

EVAL_START_IDX = 505  # ~1,4 ano de aquecimento: todas as estratégias já têm sinal
WF_TRAIN_DAYS = 730
WF_TEST_DAYS = 182


def _clean(x):
    """Converte NaN/inf/numpy para JSON."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if (math.isnan(x) or math.isinf(x)) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def rf_series(panel: Panel) -> pd.Series:
    return pd.Series(panel.rf, index=panel.dates)


def sample_curve(eq: pd.Series, base: float = 100.0, step: int = 7) -> list[list]:
    idx = list(range(0, len(eq), step))
    if idx[-1] != len(eq) - 1:
        idx.append(len(eq) - 1)
    v = eq.iloc[idx] / eq.iloc[0] * base
    return [[str(d.date()), round(float(x), 3)] for d, x in v.items()]


def _row(sid: str, strat: Strategy, res: SimResult, rf: pd.Series, panel: Panel) -> dict:
    perf = performance(res.equity, rf)
    yrs = max(perf.get("years", 0), 1e-9)
    mean_eq = float(res.equity.mean())
    perf.update({
        "id": sid, "name": strat.name, "family": strat.family, "experimental": strat.experimental,
        "passive": sid in PASSIVE_IDS, "n_trades": int(len(res.trades)),
        "trades_per_year": len(res.trades) / yrs,
        "turnover_per_year": res.notional_traded / mean_eq / yrs if mean_eq > 0 else None,
        "cost_drag_per_year": res.total_costs / mean_eq / yrs if mean_eq > 0 else None,
        "costs_brl": res.total_costs, "dividends_brl": res.dividends_received,
        "avg_exposure": float(res.exposure.mean()),
    })
    half = len(res.equity) // 2
    for tag, part in (("h1", res.equity.iloc[: half + 1]), ("h2", res.equity.iloc[half:])):
        pp = performance(part, rf)
        perf[f"cagr_{tag}"] = pp.get("cagr")
        perf[f"sharpe_{tag}"] = pp.get("sharpe")
    perf["by_year"] = period_returns(res.equity)
    return perf


def run_leaderboard(panel: Panel, cfg: Config, strategies: dict[str, Strategy], weights: dict[str, np.ndarray],
                    initial: float, min_order: float, start_idx: int = EVAL_START_IDX,
                    n_grid_trials: int = 0) -> tuple[list[dict], dict[str, SimResult], pd.Series]:
    rf = rf_series(panel)
    results: dict[str, SimResult] = {}
    for sid, s in strategies.items():
        results[sid] = run_simulation(panel, weights[sid], cfg.execution, cfg.costs, initial,
                                      start_idx=start_idx, hold_only=s.hold_only, min_order=min_order)
    cdi = cdi_benchmark(panel, initial, start_idx)
    rows = [_row(sid, strategies[sid], results[sid], rf, panel) for sid in strategies]
    # estatística de múltiplas tentativas (DSR)
    sr_all = []
    for sid in strategies:
        r = daily_returns(results[sid].equity).to_numpy()
        sr_all.append(stats.sharpe_period(r))
    var_sr = float(np.nanvar(sr_all, ddof=1)) if len(sr_all) > 2 else 0.0
    n_trials = len(strategies) + n_grid_trials
    bench = daily_returns(results["ew_all"].equity).to_numpy() if "ew_all" in results else None
    cdi_r = daily_returns(cdi).to_numpy()
    for row in rows:
        r = daily_returns(results[row["id"]].equity).to_numpy()
        sk, ku = stats.moments(r)
        row["psr_vs_zero"] = stats.psr(stats.sharpe_period(r), len(r), sk, ku, 0.0)
        row["dsr"] = stats.dsr(r, n_trials, var_sr)
        row["excess_cagr_vs_cdi"] = row["cagr"] - performance(cdi)["cagr"]
        bs_cdi = stats.block_bootstrap_diff(r, cdi_r)
        row["vs_cdi"] = bs_cdi
        if bench is not None and row["id"] != "ew_all":
            row["vs_ew_all"] = stats.block_bootstrap_diff(r, bench)
    return rows, results, cdi


def robustness_without_winners(panel: Panel, cfg: Config, strategies: dict[str, Strategy], ctx: Ctx,
                               initial: float, min_order: float, start_idx: int, n_remove: int = 4) -> dict:
    """Reroda as estratégias SEM os `n_remove` ativos de maior retorno comprar-e-segurar.
    Se o resultado desaba, ele dependia de poucos vencedores escolhidos com retrospecto."""
    close = panel.close_ff * panel.fx
    tot = {}
    for j in range(panel.N):
        ok = np.flatnonzero(np.isfinite(close[start_idx:, j]))
        if len(ok) > 30:  # ativos listados depois do início contam a partir da 1ª cotação
            tot[panel.ids[j]] = close[-1, j] / close[start_idx + ok[0], j]
    winners = sorted(tot, key=lambda a: -tot[a])[:n_remove]
    keep = [a for a in panel.ids if a not in winners]
    sub = panel.subset(keep)
    rf = rf_series(sub)
    out: dict = {"removed": winners, "results": {}}
    for sid, s in strategies.items():
        if s.hold_only or sid in PASSIVE_IDS or s.experimental:
            continue
        W = s.weights(sub, ctx)
        r = run_simulation(sub, W, cfg.execution, cfg.costs, initial, start_idx=start_idx, min_order=min_order)
        p = performance(r.equity, rf)
        out["results"][sid] = {"cagr": p.get("cagr"), "sharpe": p.get("sharpe"), "max_drawdown": p.get("max_drawdown")}
    if "ew_all" in strategies:
        W = strategies["ew_all"].weights(sub, ctx)
        r = run_simulation(sub, W, cfg.execution, cfg.costs, initial, start_idx=start_idx, min_order=min_order)
        p = performance(r.equity, rf)
        out["ew_all_cagr"] = p.get("cagr")
    return out


# ------------------------------------------------------------------------------ walk-forward
def walk_forward(panel: Panel, cfg: Config, ctx: Ctx, family: str, initial: float, min_order: float,
                 start_idx: int = EVAL_START_IDX, train_days: int = WF_TRAIN_DAYS,
                 test_days: int = WF_TEST_DAYS) -> dict:
    """Escolhe parâmetros na janela de treino (Sharpe) e mede SOMENTE na janela de teste seguinte.
    Os pesos de cada combinação são calculados com dados até a data (causais); a seleção usa
    apenas o treino; o resultado reportado é a concatenação dos testes (fora da amostra)."""
    cls, grid = GRIDS[family]
    rf = rf_series(panel)
    combos = [cls(**p) for p in grid]
    W = [c.weights(panel, ctx) for c in combos]
    T = panel.T
    segments: list[pd.Series] = []
    chosen: list[dict] = []
    test_start = start_idx + train_days
    while test_start < T - 1:
        test_end = min(test_start + test_days - 1, T - 1)
        tr_s, tr_e = test_start - train_days, test_start - 1
        scores = []
        for w in W:
            r = run_simulation(panel, w, cfg.execution, cfg.costs, initial, start_idx=tr_s, end_idx=tr_e,
                               min_order=min_order)
            sh = performance(r.equity, rf).get("sharpe", float("nan"))
            scores.append(-np.inf if sh is None or math.isnan(sh) else sh)
        best = int(np.argmax(scores))
        rt = run_simulation(panel, W[best], cfg.execution, cfg.costs, initial, start_idx=test_start,
                            end_idx=test_end, min_order=min_order)
        segments.append(rt.equity / rt.equity.iloc[0])
        chosen.append({"train": [str(panel.dates[tr_s].date()), str(panel.dates[tr_e].date())],
                       "test": [str(panel.dates[test_start].date()), str(panel.dates[test_end].date())],
                       "params": grid[best], "train_sharpe": scores[best],
                       "test_return": float(rt.equity.iloc[-1] / rt.equity.iloc[0] - 1)})
        test_start = test_end + 1
    if not segments:
        return {"family": family, "error": "histórico insuficiente para walk-forward"}
    level = initial
    parts = [pd.Series([initial], index=[segments[0].index[0]])]
    for seg in segments:
        scaled = seg.iloc[1:] * level
        parts.append(scaled)
        level = float(scaled.iloc[-1])
    oos = pd.concat(parts)
    oos = oos[~oos.index.duplicated(keep="last")]
    oos_start_idx = panel.index_of(oos.index[0]) + 1
    # referências SOBRE A MESMA JANELA
    default = cls()
    r_def = run_simulation(panel, default.weights(panel, ctx), cfg.execution, cfg.costs, initial,
                           start_idx=oos_start_idx, min_order=min_order)
    cdi = cdi_benchmark(panel, initial, oos_start_idx)
    return {
        "family": family, "n_combos": len(grid), "windows": chosen,
        "oos_start": str(oos.index[0].date()), "oos_end": str(oos.index[-1].date()),
        "oos": performance(oos, rf), "default_params_same_window": performance(r_def.equity, rf),
        "cdi_same_window": performance(cdi),
        "oos_curve": sample_curve(oos), "cdi_curve": sample_curve(cdi),
        "_oos_equity": oos,
    }


def run_full_backtest(panel: Panel, cfg: Config, strategies: dict[str, Strategy], as_of,
                      with_walk_forward: bool = True) -> dict:
    ctx = Ctx(cfg.execution.max_positions, cfg.execution.min_cash)
    weights = {sid: s.weights(panel, ctx) for sid, s in strategies.items()}
    n_grid = sum(len(g) for _, g in GRIDS.values())
    ref_init, ref_min = cfg.reference_initial, 1.0
    rows, results, cdi = run_leaderboard(panel, cfg, strategies, weights, ref_init, ref_min,
                                         EVAL_START_IDX, n_grid_trials=n_grid)
    # mesma coisa com as restrições REAIS de R$ 50 (lote mínimo, ordem mínima)
    rows50, results50, cdi50 = run_leaderboard(panel, cfg, strategies, weights, cfg.paper_initial,
                                               cfg.execution.min_order_brl, EVAL_START_IDX, n_grid)
    by50 = {r["id"]: {"final": r["final"], "cagr": r.get("cagr"), "n_trades": r["n_trades"],
                      "max_drawdown": r.get("max_drawdown"), "avg_exposure": r["avg_exposure"]} for r in rows50}
    for r in rows:
        r["r50"] = by50.get(r["id"])
    robust = robustness_without_winners(panel, cfg, strategies, ctx, ref_init, ref_min, EVAL_START_IDX)
    for r in rows:
        r["ex_winners"] = robust["results"].get(r["id"])
    wf = {}
    if with_walk_forward:
        for fam in GRIDS:
            wf[fam] = walk_forward(panel, cfg, ctx, fam, ref_init, ref_min)
    cdi_perf = performance(cdi)
    curves = {sid: sample_curve(res.equity) for sid, res in results.items()}
    curves["cdi"] = sample_curve(cdi)
    wf_public = {}
    for fam, d in wf.items():
        d = dict(d)
        d.pop("_oos_equity", None)
        wf_public[fam] = d
    out = {
        "kind": "BACKTEST_HISTORICO",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": str(as_of),
        "period": {"start": str(results["bh_btc"].equity.index[0].date()),
                   "end": str(results["bh_btc"].equity.index[-1].date()),
                   "years": rows[0].get("years")},
        "initial_brl": ref_init, "paper_initial_brl": cfg.paper_initial,
        "universe": panel.ids, "n_trials": len(strategies) + n_grid,
        "cdi": cdi_perf,
        "leaderboard": rows, "curves": curves, "walk_forward": wf_public,
        "robustness": robust,
        "assumptions": {
            "costs_bps": {k: {"fee": v.fee_bps, "spread": v.spread_bps, "slippage": v.slippage_bps,
                              "entry_extra": v.entry_extra_bps, "exit_extra": v.exit_extra_bps}
                          for k, v in cfg.costs.items()},
            "execution": "sinal no fechamento de t, ordem na abertura de t+1",
            "taxes": "não modelados (resultado antes de impostos)",
            "survivorship": "universo escolhido em 2026 (viés de sobrevivência/retrospecto)",
        },
    }
    return _clean(out)
