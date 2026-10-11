"""Garantia central: nenhum sinal em t depende de dados posteriores a t."""
import numpy as np
import pytest

from investidor.strategies.base import Ctx
from investidor.strategies.registry import build_strategies

CTX = Ctx(k=3, min_cash=0.02)


@pytest.mark.parametrize("sid", ["bh_btc", "bh_ew", "ew_all", "dual_momentum", "trend_sma", "macd_trend",
                                 "meanrev_bb", "rsi_mr", "lowvol", "stat_ridge", "ml_gbm"])
def test_weights_do_not_use_future_data(sid, panel, cfg):
    strat = build_strategies(cfg)[sid]
    full = strat.weights(panel, CTX)
    assert full.shape == (panel.T, panel.N)
    assert np.all(full >= -1e-12) and np.all(full.sum(axis=1) <= 1 + 1e-9)  # sem alavancagem/short
    for cut in (700, 950, 1233, 1400):
        part = build_strategies(cfg)[sid].weights(panel.head(cut + 1), CTX)
        assert np.allclose(part[cut], full[cut], atol=1e-12), f"{sid}: peso em {cut} mudou com dados futuros"
        assert np.allclose(part[: cut + 1], full[: cut + 1], atol=1e-12)


def test_perturbing_the_future_does_not_change_the_past(panel, cfg):
    """Altera brutalmente os preços APÓS t e confere que os pesos até t permanecem iguais."""
    from copy import deepcopy

    t = 1000
    p2 = deepcopy(panel)
    for arr in (p2.open, p2.high, p2.low, p2.close, p2.close_ff):
        arr[t + 1:] *= 3.7
    for sid in ("dual_momentum", "trend_sma", "rsi_mr", "stat_ridge", "lowvol"):
        a = build_strategies(cfg)[sid].weights(panel, CTX)
        b = build_strategies(cfg)[sid].weights(p2, CTX)
        assert np.allclose(a[: t + 1], b[: t + 1], atol=1e-12), sid


def test_ml_gate_blocks_small_samples():
    from investidor.strategies.models import ml_gate
    assert not ml_gate(500, 7) and not ml_gate(1999, 7) and ml_gate(5000, 7)


def test_ml_requires_oos_refits_with_realized_targets(panel):
    """O alvo de t só é usado em treinos feitos depois de t+horizonte."""
    from investidor.strategies.models import Ridge, build_features, forward_return, walk_forward_predict

    X = build_features(panel); y = forward_return(panel, 5)
    y_spoiled = y.copy(); y_spoiled[1100:] = 999.0  # corrompe alvos "do futuro"
    p1, _ = walk_forward_predict(X, y, lambda: Ridge(0.1), 5, 504, 63)
    p2, _ = walk_forward_predict(X, y_spoiled, lambda: Ridge(0.1), 5, 504, 63)
    first_affected = next(t0 for t0 in range(504, panel.T, 63) if t0 - 5 >= 1100)
    m = np.isfinite(p1[:first_affected])
    assert m.sum() > 1000
    assert np.allclose(p1[:first_affected][m], p2[:first_affected][m])
    assert not np.allclose(p1[first_affected:][np.isfinite(p1[first_affected:])],
                           p2[first_affected:][np.isfinite(p2[first_affected:])])  # o teste é sensível


def test_leak_detector_actually_catches_a_leaky_strategy(panel):
    """Mutation test: uma estratégia que espia o retorno de amanhã TEM que reprovar no teste de truncamento."""
    from investidor.strategies.base import Strategy, equal_weights, sticky_topk

    class Leaky(Strategy):
        id = "leaky"
        def weights(self, pnl, ctx):
            c = pnl.close_ff
            fut = np.full_like(c, np.nan); fut[:-1] = c[1:] / c[:-1] - 1  # retorno de AMANHÃ (vazamento)
            S = np.isfinite(fut) & (fut > 0)
            return equal_weights(sticky_topk(S, fut, ctx.k, np.ones(pnl.T, bool)), ctx)

    full = Leaky().weights(panel, CTX)
    part = Leaky().weights(panel.head(1001), CTX)
    assert not np.allclose(part[1000], full[1000]), "o detector deveria flagrar o vazamento"
