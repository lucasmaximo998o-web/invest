import numpy as np
import pandas as pd

from investidor import indicators as I


def series(n=300, seed=0):
    r = np.random.default_rng(seed).normal(0.0005, 0.02, n)
    return pd.Series(100 * np.exp(np.cumsum(r)), index=pd.date_range("2024-01-01", periods=n))


def test_rsi_bounds_and_extremes():
    s = series()
    r = I.rsi(s).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    up = pd.Series(np.arange(1.0, 60.0)); assert I.rsi(up).iloc[-1] == 100.0
    dn = pd.Series(np.arange(60.0, 1.0, -1)); assert I.rsi(dn).iloc[-1] < 1.0


def test_indicators_are_causal():
    s = series()
    for fn in (lambda x: I.sma(x, 20), lambda x: I.ema(x, 20), I.rsi, lambda x: I.macd(x)[2], I.bollinger_z,
               lambda x: I.realized_vol(x, 30)):
        full = fn(s); part = fn(s.iloc[:200])
        pd.testing.assert_series_equal(full.iloc[:200], part, check_names=False)


def test_sma_and_macd_values():
    s = pd.Series(np.arange(1.0, 11.0))
    assert I.sma(s, 5).iloc[-1] == 8.0
    line, sig, hist = I.macd(series())
    assert np.allclose((line - sig).dropna(), hist.dropna())


def test_drawdown():
    e = pd.Series([100, 110, 99, 120.0])
    d = I.drawdown(e)
    assert d.iloc[2] == (99 / 110 - 1) and d.iloc[3] == 0
