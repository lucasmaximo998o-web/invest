"""Infraestrutura comum das estratégias.

Contrato: `Strategy.weights(panel, ctx)` devolve uma matriz (T, N) de pesos-alvo em [0, 1]
(soma por linha <= 1; o resto fica em caixa). A linha t usa SOMENTE dados até o fechamento
de t. O motor executa essa linha na abertura de t+1. Isso é verificado em
tests/test_no_lookahead.py truncando o painel e comparando os pesos.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from ..data.panel import Panel


@dataclass(frozen=True)
class Ctx:
    k: int  # máximo de posições simultâneas
    min_cash: float  # fração mínima de caixa


class Strategy:
    id = "base"
    name = "base"
    family = "base"
    description = ""
    experimental = False
    hold_only = False  # True = compra uma vez e segura (sem rebalancear)
    paper_ok = True  # False = só existe no backtest (ex.: universo inteiro)

    def __init__(self, **params):
        self.params = params
        self.diagnostics: dict = {}

    def weights(self, panel: Panel, ctx: Ctx) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    def info(self) -> dict:
        return {"id": self.id, "name": self.name, "family": self.family,
                "description": self.description, "experimental": self.experimental,
                "hold_only": self.hold_only, "paper_ok": self.paper_ok, "params": self.params}


# ----------------------------------------------------------------------------- helpers
def per_asset(panel: Panel, fn: Callable[[pd.Series], pd.Series]) -> np.ndarray:
    """Aplica `fn` à série de fechamentos NATIVOS (só dias com pregão) de cada ativo e
    propaga o último valor para os dias sem pregão. Causal se `fn` for causal."""
    out = np.full((panel.T, panel.N), np.nan)
    for j in range(panel.N):
        s = pd.Series(panel.close[:, j], index=panel.dates).dropna()
        if len(s) < 3:
            continue
        out[:, j] = fn(s).reindex(panel.dates).ffill().to_numpy()
    return out


def lagged_return(panel: Panel, n: int) -> np.ndarray:
    """Retorno em n dias corridos usando o último fechamento conhecido."""
    c = panel.close_ff
    out = np.full_like(c, np.nan)
    if n < len(c):
        out[n:] = c[n:] / c[:-n] - 1.0
    return out


def rolling_cdi(panel: Panel, n: int) -> np.ndarray:
    """Retorno composto do CDI nos últimos n dias corridos (causal)."""
    lg = np.log1p(panel.rf)
    cs = np.concatenate([[0.0], np.cumsum(lg)])
    out = np.full(panel.T, np.nan)
    if n < panel.T:
        out[n:] = np.expm1(cs[n + 1:] - cs[1:panel.T - n + 1])
    return out


def monday_mask(panel: Panel) -> np.ndarray:
    return np.asarray(panel.dates.dayofweek == 0)


def sticky_topk(S: np.ndarray, score: np.ndarray, k: int, decide: np.ndarray,
                buffer: int | None = None) -> np.ndarray:
    """Seleciona até k ativos elegíveis (S) com maior `score`.

    Decisões só nos dias `decide` (entre eles, mantém o estado). Reduz giro:
      * buffer=None: posição é mantida enquanto elegível (adequado a estratégias com regra de
        saída própria, como RSI/Bollinger);
      * buffer=b: posição é mantida enquanto elegível E dentro dos k+b melhores do ranking
        (histerese; evita que ativos antigos fiquem presos para sempre)."""
    T, N = S.shape
    held = np.zeros(N, dtype=bool)
    out = np.zeros((T, N), dtype=bool)
    for t in range(T):
        if decide[t]:
            held = held & S[t]
            if buffer is not None and held.any():
                elig = np.flatnonzero(S[t])
                sc = np.where(np.isnan(score[t, elig]), -np.inf, score[t, elig])
                top = set(elig[np.argsort(-sc, kind="stable")][: k + buffer].tolist())
                held = np.array([bool(held[j]) and (j in top) for j in range(N)])
            free = k - int(held.sum())
            if free > 0:
                cand = np.flatnonzero(S[t] & ~held)
                if cand.size:
                    sc = np.where(np.isnan(score[t, cand]), -np.inf, score[t, cand])
                    held[cand[np.argsort(-sc, kind="stable")][:free]] = True
        out[t] = held
    return out


def equal_weights(held: np.ndarray, ctx: Ctx) -> np.ndarray:
    return held.astype(float) * ((1.0 - ctx.min_cash) / ctx.k)


def state_machine(entry: np.ndarray, exit_: np.ndarray, max_hold: int) -> np.ndarray:
    """Posição por ativo: entra no sinal `entry`, sai em `exit_` ou após max_hold dias."""
    T, N = entry.shape
    out = np.zeros((T, N), dtype=bool)
    for j in range(N):
        inpos, days = False, 0
        for t in range(T):
            if inpos:
                days += 1
                if exit_[t, j] or days >= max_hold:
                    inpos = False
            if not inpos and entry[t, j]:
                inpos, days = True, 0
            out[t, j] = inpos
    return out


def finite(*arrays: np.ndarray) -> np.ndarray:
    ok = np.ones_like(arrays[0], dtype=bool)
    for a in arrays:
        ok &= np.isfinite(a)
    return ok
