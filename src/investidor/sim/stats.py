"""Estatística para evitar autoengano: PSR, Deflated Sharpe Ratio e bootstrap em blocos.

Referências: Bailey & López de Prado (2012) "The Sharpe Ratio Efficient Frontier" e
(2014) "The Deflated Sharpe Ratio". Os Sharpe aqui são POR PERÍODO (diários), não anualizados.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def sharpe_period(r: np.ndarray) -> float:
    r = np.asarray(r, dtype=float)
    sd = r.std(ddof=1)
    return float(r.mean() / sd) if sd > 0 else float("nan")


def moments(r: np.ndarray) -> tuple[float, float]:
    """(assimetria, curtose NÃO-excesso)."""
    r = np.asarray(r, dtype=float)
    m, sd = r.mean(), r.std(ddof=0)
    if sd == 0:
        return 0.0, 3.0
    z = (r - m) / sd
    return float((z ** 3).mean()), float((z ** 4).mean())


def psr(sr: float, n: int, skew: float, kurt: float, sr_ref: float = 0.0) -> float:
    """Probabilidade de o Sharpe verdadeiro exceder `sr_ref`, dado o Sharpe observado."""
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr ** 2
    if n < 3 or denom <= 0 or math.isnan(sr):
        return float("nan")
    return _N.cdf((sr - sr_ref) * math.sqrt(n - 1) / math.sqrt(denom))


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """Sharpe máximo esperado entre n_trials estratégias SEM nenhum poder preditivo."""
    if n_trials < 2 or var_sr <= 0:
        return 0.0
    return math.sqrt(var_sr) * (
        (1 - EULER_GAMMA) * _N.inv_cdf(1 - 1.0 / n_trials)
        + EULER_GAMMA * _N.inv_cdf(1 - 1.0 / (n_trials * math.e))
    )


def dsr(r: np.ndarray, n_trials: int, var_sr_trials: float) -> float:
    """Deflated Sharpe Ratio: PSR contra o Sharpe esperado por pura sorte entre as tentativas."""
    r = np.asarray(r, dtype=float)
    sr = sharpe_period(r)
    skew, kurt = moments(r)
    return psr(sr, len(r), skew, kurt, sr_ref=expected_max_sharpe(n_trials, var_sr_trials))


def block_bootstrap_diff(r_a: np.ndarray, r_b: np.ndarray, n_boot: int = 2000, block: int = 20,
                         seed: int = 7) -> dict:
    """Bootstrap em blocos circulares da diferença média diária (a - b), anualizada."""
    d = np.asarray(r_a, dtype=float) - np.asarray(r_b, dtype=float)
    T = len(d)
    if T < 2 * block:
        return {"mean_annual": float("nan"), "ci90": [float("nan")] * 2, "prob_a_better": float("nan")}
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(T / block))
    starts = rng.integers(0, T, size=(n_boot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % T
    means = d[idx.reshape(n_boot, -1)[:, :T]].mean(axis=1)
    return {
        "mean_annual": float(d.mean() * 365),
        "ci90": [float(np.quantile(means, 0.05) * 365), float(np.quantile(means, 0.95) * 365)],
        "prob_a_better": float((means > 0).mean()),
    }
