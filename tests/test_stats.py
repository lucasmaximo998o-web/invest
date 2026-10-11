import math

import numpy as np
import pytest

from investidor.sim import stats
from investidor.sim.metrics import max_drawdown, performance
import pandas as pd


def test_psr_basic_properties():
    # SR observado = SR de referência -> 50%
    assert stats.psr(0.1, 500, 0.0, 3.0, sr_ref=0.1) == pytest.approx(0.5)
    assert stats.psr(0.2, 500, 0.0, 3.0) > stats.psr(0.05, 500, 0.0, 3.0)
    assert stats.psr(0.1, 5000, 0.0, 3.0) > stats.psr(0.1, 100, 0.0, 3.0)


def test_psr_matches_closed_form():
    sr, n = 0.15, 300
    z = sr * math.sqrt(n - 1)  # skew=0, kurt=3 -> denominador = sqrt(1 + sr^2/2)
    z /= math.sqrt(1 + sr ** 2 / 2)
    from statistics import NormalDist
    assert stats.psr(sr, n, 0.0, 3.0) == pytest.approx(NormalDist().cdf(z))


def test_expected_max_sharpe_grows_with_trials():
    a, b = stats.expected_max_sharpe(10, 0.01), stats.expected_max_sharpe(1000, 0.01)
    assert 0 < a < b
    assert stats.expected_max_sharpe(1, 0.01) == 0.0


def test_dsr_penalizes_many_trials():
    rng = np.random.default_rng(0)
    r = rng.normal(0.0008, 0.01, 1500)
    few = stats.dsr(r, 2, 0.0004 ** 2)
    many = stats.dsr(r, 500, 0.0004 ** 2)
    assert many < few


def test_noise_strategies_rarely_pass_dsr():
    rng = np.random.default_rng(1)
    srs, passes = [], 0
    rets = [rng.normal(0.0, 0.01, 1500) for _ in range(40)]
    var = np.var([stats.sharpe_period(r) for r in rets], ddof=1)
    passes = sum(stats.dsr(r, 40, var) > 0.95 for r in rets)
    assert passes <= 2  # ruído puro não deve "passar" no DSR


def test_bootstrap_detects_real_edge_and_not_noise():
    rng = np.random.default_rng(2)
    base = rng.normal(0.0003, 0.01, 1500)
    better = base + 0.002
    res = stats.block_bootstrap_diff(better, base)
    assert res["prob_a_better"] > 0.99 and res["ci90"][0] > 0
    noise = stats.block_bootstrap_diff(base + rng.normal(0, 0.001, 1500), base)
    assert 0.02 < noise["prob_a_better"] < 0.98


def test_metrics_known_series():
    idx = pd.date_range("2024-01-01", periods=366, freq="D")
    eq = pd.Series(100 * (1.001) ** np.arange(366), index=idx)
    p = performance(eq)
    assert p["cagr"] == pytest.approx(1.001 ** 365 - 1, rel=2e-3)
    assert p["max_drawdown"] == 0
    dd = pd.Series([100, 120, 90, 100.0], index=pd.date_range("2024-01-01", periods=4))
    assert max_drawdown(dd) == pytest.approx(-0.25)
