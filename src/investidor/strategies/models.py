"""Modelos estatísticos / aprendizado de máquina com validação walk-forward.

Regras anti-vazamento:
  * features em t usam só dados até t;
  * o alvo é o retorno futuro de `horizon` dias; um modelo treinado em t0 só usa linhas
    cujo alvo já era conhecido em t0 (t <= t0 - horizon);
  * o modelo é re-treinado em datas fixas (índices ancorados no início do painel) e
    aplicado apenas ao bloco seguinte (expanding window, nunca olha para frente).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.panel import Panel
from ..indicators import rsi, sma
from .base import lagged_return, per_asset

FEATURES = ["r1", "r5", "r20", "r60", "vol20", "rsi14", "dist_sma50"]


def build_features(panel: Panel) -> np.ndarray:
    c = panel.close_ff
    dlog = pd.DataFrame(np.log(c)).diff()
    vol20 = dlog.rolling(20, min_periods=20).std(ddof=1).to_numpy() * np.sqrt(365)
    rsi14 = per_asset(panel, lambda s: rsi(s, 14)) / 100.0 - 0.5
    sma50 = per_asset(panel, lambda s: sma(s, 50))
    with np.errstate(invalid="ignore", divide="ignore"):
        dist = c / sma50 - 1.0
    cols = [lagged_return(panel, 1), lagged_return(panel, 5), lagged_return(panel, 20),
            lagged_return(panel, 60), vol20, rsi14, dist]
    return np.stack(cols, axis=-1)


def forward_return(panel: Panel, horizon: int) -> np.ndarray:
    c = panel.close_ff
    y = np.full_like(c, np.nan)
    y[:-horizon] = c[horizon:] / c[:-horizon] - 1.0
    return y


def ml_gate(n_rows: int, n_features: int, min_rows: int = 2000, rows_per_feature: int = 100) -> bool:
    """Só treina ML com dados suficientes (regra do projeto: justificar antes de usar)."""
    return n_rows >= min_rows and n_rows >= rows_per_feature * n_features


def auc_score(score: np.ndarray, label: np.ndarray) -> float:
    """AUC (Mann-Whitney) sem dependências. 0.5 = sem poder preditivo."""
    m = np.isfinite(score) & np.isfinite(label)
    s, y = score[m], label[m].astype(bool)
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = pd.Series(s).rank(method="average").to_numpy()
    return float((ranks[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


class Ridge:
    def __init__(self, alpha_per_row: float = 0.1):
        self.alpha_per_row = alpha_per_row

    def fit(self, X: np.ndarray, y: np.ndarray) -> "Ridge":
        self.mu = X.mean(axis=0)
        self.sd = X.std(axis=0)
        self.sd[self.sd == 0] = 1.0
        Z = (X - self.mu) / self.sd
        self.ymu = float(y.mean())
        alpha = self.alpha_per_row * len(y)
        self.w = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - self.ymu))
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return ((X - self.mu) / self.sd) @ self.w + self.ymu


class GBMClassifier:
    """HistGradientBoosting raso e fortemente regularizado; devolve prob - taxa-base."""

    def __init__(self, hurdle: float):
        self.hurdle = hurdle

    def fit(self, X: np.ndarray, y: np.ndarray) -> "GBMClassifier":
        from sklearn.ensemble import HistGradientBoostingClassifier

        lab = (y > self.hurdle).astype(int)
        self.base = float(lab.mean())
        self.m = HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.05, max_iter=120, l2_regularization=5.0,
            min_samples_leaf=200, random_state=0)
        self.m.fit(X, lab)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.m.predict_proba(X)[:, 1] - self.base


def walk_forward_predict(X: np.ndarray, y: np.ndarray, make_model, horizon: int, first: int,
                         retrain: int, gate=None) -> tuple[np.ndarray, int]:
    """Previsões fora da amostra (T, N). Devolve (pred, n_ajustes)."""
    T, N, F = X.shape
    valid = np.isfinite(X).all(axis=2)
    pred = np.full((T, N), np.nan)
    fits = 0
    for t0 in range(first, T, retrain):
        last_train = t0 - horizon  # alvo de t só é conhecido em t + horizon <= t0
        if last_train < 1:
            continue
        m = valid[: last_train + 1] & np.isfinite(y[: last_train + 1])
        Xtr = X[: last_train + 1][m]
        ytr = y[: last_train + 1][m]
        if gate is not None and not gate(len(ytr), F):
            continue
        if len(ytr) < 200:
            continue
        model = make_model().fit(Xtr, ytr)
        fits += 1
        hi = min(t0 + retrain, T)
        blk = X[t0:hi]
        ok = valid[t0:hi]
        p = np.full(ok.shape, np.nan)
        if ok.any():
            p[ok] = model.predict(blk[ok])
        pred[t0:hi] = p
    return pred, fits
