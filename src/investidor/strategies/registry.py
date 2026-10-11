"""Registro das estratégias do projeto e das grades usadas no walk-forward."""
from __future__ import annotations

from ..config import Config
from .base import Strategy
from .library import (BuyHold, DualMomentum, EqualWeightBand, LowVol, MacdTrend, MeanRevBB,
                      MLGradientBoosting, RsiMR, StatRidge, TrendSMA)


def build_strategies(cfg: Config) -> dict[str, Strategy]:
    ew = {a: 1.0 for a in cfg.ew_assets}
    ew_label = "/".join(cfg.ew_assets)
    items: list[Strategy] = [
        BuyHold("bh_btc", "Passiva: comprar e segurar BTC", {"BTC": 1.0},
                "Referência passiva de cripto: compra BTC uma vez e não faz mais nada."),
        BuyHold("bh_spy", "Passiva: comprar e segurar S&P 500 (SPY)", {"SPY": 1.0},
                "Referência passiva de ações dos EUA (retorno de preço, sem dividendos)."),
        BuyHold("bh_ew", f"Passiva: {ew_label} pesos iguais (sem rebalancear)", ew,
                "Cesta diversificada simples: compra uma vez e segura."),
        EqualWeightBand("ew_rebal", f"Passiva: {ew_label} com rebalanceamento por banda", ew,
                        "Mesma cesta, mas rebalanceada quando o desvio passa da banda configurada."),
        EqualWeightBand("ew_all", "Passiva: universo inteiro, pesos iguais (referência de viés)", {"*": 1.0},
                        "Compra TODOS os ativos do universo em partes iguais (rebalanceando por banda). "
                        "É o comparador justo das estratégias que escolhem ativos dentro desse universo; "
                        "só existe no backtest (com R$ 50 não há como comprar tantos ativos).",
                        paper_ok=False),
        DualMomentum(), TrendSMA(), MacdTrend(), MeanRevBB(), RsiMR(), LowVol(), StatRidge(),
        MLGradientBoosting(),
    ]
    return {s.id: s for s in items}


PASSIVE_IDS = ("bh_btc", "bh_spy", "bh_ew", "ew_rebal", "ew_all")

# Famílias ajustáveis no walk-forward: (classe, lista de combinações de parâmetros)
GRIDS: dict[str, tuple[type[Strategy], list[dict]]] = {
    "dual_momentum": (DualMomentum, [{"lookback": n} for n in (30, 60, 90, 120, 180, 252)]),
    "trend_sma": (TrendSMA, [{"fast": f, "slow": s} for f, s in
                             ((20, 100), (30, 150), (50, 200), (50, 100), (100, 250))]),
    "meanrev_bb": (MeanRevBB, [{"n": n, "z_in": z} for n in (10, 20, 40) for z in (1.5, 2.0, 2.5)]),
    "rsi_mr": (RsiMR, [{"entry": e, "exit": x} for e in (20, 25, 30, 35) for x in (50, 55, 60)]),
}
