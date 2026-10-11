"""Indicadores técnicos/estatísticos CAUSAIS: o valor em t usa apenas dados até t."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    """RSI de Wilder."""
    d = s.diff()
    up = d.clip(lower=0.0).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0.0)).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    out[(dn == 0) & (up > 0)] = 100.0
    return out


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(s, fast) - ema(s, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def bollinger_z(s: pd.Series, n: int = 20) -> pd.Series:
    """Distância do preço à média móvel em desvios-padrão."""
    m = s.rolling(n, min_periods=n).mean()
    sd = s.rolling(n, min_periods=n).std(ddof=0)
    return (s - m) / sd.replace(0.0, np.nan)


def realized_vol(s: pd.Series, n: int = 60, periods: int = 365) -> pd.Series:
    r = np.log(s).diff()
    return r.rolling(n, min_periods=n).std(ddof=1) * np.sqrt(periods)


def drawdown(equity: pd.Series) -> pd.Series:
    peak = equity.cummax()
    return equity / peak - 1.0
