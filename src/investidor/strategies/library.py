"""Biblioteca de estratégias (somente compra; sem alavancagem nem venda a descoberto).

Todos os parâmetros-padrão são valores convencionais fixados ANTES de olhar os resultados.
"""
from __future__ import annotations

import numpy as np

from ..data.panel import Panel
from ..indicators import bollinger_z, macd, realized_vol, rsi, sma
from .base import (Ctx, Strategy, equal_weights, finite, lagged_return, monday_mask, per_asset,
                   rolling_cdi, state_machine, sticky_topk)
from .models import (FEATURES, GBMClassifier, Ridge, auc_score, build_features, forward_return,
                     ml_gate, walk_forward_predict)

def _decide_all(panel: Panel) -> np.ndarray:
    return np.ones(panel.T, dtype=bool)


# ------------------------------------------------------------------------------ passivas
class BuyHold(Strategy):
    family = "passiva"
    hold_only = True
    paper_ok = True  # pode virar carteira de paper trading com capital pequeno

    def __init__(self, sid: str, name: str, targets: dict[str, float], description: str,
                 paper_ok: bool = True):
        super().__init__(targets=targets)
        self.id, self.name, self.description, self.targets = sid, name, description, targets
        self.paper_ok = paper_ok

    def weights(self, panel: Panel, ctx: Ctx) -> np.ndarray:
        w = np.zeros((panel.T, panel.N))
        if "*" in self.targets:  # universo inteiro, pesos iguais entre ativos já existentes
            have = ~np.isnan(panel.close_ff)
            n = have.sum(axis=1, keepdims=True)
            return np.where(have, 1.0 / np.maximum(n, 1), 0.0)
        present = {a: v for a, v in self.targets.items() if a in panel.ids}
        tot = sum(present.values())
        for a, v in present.items():
            w[:, panel.col(a)] = v / tot  # investe 100% (passivo puro, sem caixa mínimo)
        return w


class EqualWeightBand(BuyHold):
    """Pesos iguais constantes; o motor rebalanceia quando o desvio passa da banda."""
    hold_only = False


# ------------------------------------------------------------------------------ momentum
class DualMomentum(Strategy):
    id, name, family = "dual_momentum", "Momentum dual (relativo + absoluto)", "momentum"
    description = ("Toda segunda-feira: mantém até k ativos com maior retorno em N dias, só se o "
                   "retorno superar o CDI do mesmo período (momentum absoluto); senão fica em caixa.")

    def __init__(self, lookback: int = 90):
        super().__init__(lookback=lookback)
        self.lookback = lookback

    def weights(self, panel: Panel, ctx: Ctx) -> np.ndarray:
        mom = lagged_return(panel, self.lookback)
        rf = rolling_cdi(panel, self.lookback)[:, None]
        with np.errstate(invalid="ignore"):
            S = finite(mom) & (mom > rf) & (mom > 0)
        held = sticky_topk(S, mom, ctx.k, monday_mask(panel), buffer=1)
        return equal_weights(held, ctx)


# ------------------------------------------------------------------------------ tendência
class TrendSMA(Strategy):
    id, name, family = "trend_sma", "Médias móveis 50/200 (cruzamento)", "tendência"
    description = "Posicionado enquanto a média de 50 dias estiver acima da de 200 dias."

    def __init__(self, fast: int = 50, slow: int = 200):
        super().__init__(fast=fast, slow=slow)
        self.fast, self.slow = fast, slow

    def weights(self, panel: Panel, ctx: Ctx) -> np.ndarray:
        f = per_asset(panel, lambda s: sma(s, self.fast))
        sl = per_asset(panel, lambda s: sma(s, self.slow))
        with np.errstate(invalid="ignore", divide="ignore"):
            S = finite(f, sl) & (f > sl)
            score = f / sl - 1.0
        held = sticky_topk(S, score, ctx.k, monday_mask(panel), buffer=1)
        return equal_weights(held, ctx)


class MacdTrend(Strategy):
    id, name, family = "macd_trend", "MACD 12/26/9", "tendência"
    description = "Posicionado quando o histograma do MACD é positivo (decisão semanal)."

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__(fast=fast, slow=slow, signal=signal)
        self.fast, self.slow, self.signal = fast, slow, signal

    def weights(self, panel: Panel, ctx: Ctx) -> np.ndarray:
        hist = per_asset(panel, lambda s: macd(s, self.fast, self.slow, self.signal)[2])
        with np.errstate(invalid="ignore", divide="ignore"):
            score = hist / np.where(panel.close_ff > 0, panel.close_ff, np.nan)
            S = finite(score) & (hist > 0)
        held = sticky_topk(S, score, ctx.k, monday_mask(panel), buffer=1)
        return equal_weights(held, ctx)


# ------------------------------------------------------------------------------ reversão à média
class MeanRevBB(Strategy):
    id, name, family = "meanrev_bb", "Reversão à média (Bollinger 20, -2σ)", "reversão"
    description = ("Compra quando o preço cai 2 desvios abaixo da média de 20 dias; sai ao voltar "
                   "à média ou após 30 dias.")

    def __init__(self, n: int = 20, z_in: float = 2.0, z_out: float = 0.0, max_hold: int = 30):
        super().__init__(n=n, z_in=z_in, z_out=z_out, max_hold=max_hold)
        self.n, self.z_in, self.z_out, self.max_hold = n, z_in, z_out, max_hold

    def weights(self, panel: Panel, ctx: Ctx) -> np.ndarray:
        z = per_asset(panel, lambda s: bollinger_z(s, self.n))
        with np.errstate(invalid="ignore"):
            entry = finite(z) & (z < -self.z_in)
            exit_ = finite(z) & (z >= self.z_out)
        inpos = state_machine(entry, exit_, self.max_hold)
        held = sticky_topk(inpos, -np.nan_to_num(z, nan=0.0), ctx.k, _decide_all(panel))
        return equal_weights(held, ctx)


class RsiMR(Strategy):
    id, name, family = "rsi_mr", "RSI(14) sobrevendido", "reversão"
    description = "Compra com RSI < 30; sai com RSI > 55 ou após 30 dias."

    def __init__(self, n: int = 14, entry: float = 30.0, exit: float = 55.0, max_hold: int = 30):
        super().__init__(n=n, entry=entry, exit=exit, max_hold=max_hold)
        self.n, self.entry, self.exit, self.max_hold = n, entry, exit, max_hold

    def weights(self, panel: Panel, ctx: Ctx) -> np.ndarray:
        r = per_asset(panel, lambda s: rsi(s, self.n))
        with np.errstate(invalid="ignore"):
            entry = finite(r) & (r < self.entry)
            exit_ = finite(r) & (r > self.exit)
        inpos = state_machine(entry, exit_, self.max_hold)
        held = sticky_topk(inpos, 100.0 - np.nan_to_num(r, nan=50.0), ctx.k, _decide_all(panel))
        return equal_weights(held, ctx)


# ------------------------------------------------------------------------------ estatística
class LowVol(Strategy):
    id, name, family = "lowvol", "Baixa volatilidade (inverso da vol.)", "estatística"
    description = ("Toda segunda: os k ativos de menor volatilidade realizada (60 dias), "
                   "ponderados pelo inverso da volatilidade. Estratégia defensiva.")

    def __init__(self, window: int = 60):
        super().__init__(window=window)
        self.window = window

    def weights(self, panel: Panel, ctx: Ctx) -> np.ndarray:
        vol = per_asset(panel, lambda s: realized_vol(s, self.window, 252))
        S = finite(vol) & (vol > 0)
        held = sticky_topk(S, -np.nan_to_num(vol, nan=np.inf), ctx.k, monday_mask(panel), buffer=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            inv = np.where(held, 1.0 / vol, 0.0)
        tot = inv.sum(axis=1, keepdims=True)
        w = np.where(tot > 0, inv / np.where(tot > 0, tot, 1.0), 0.0)
        return w * (1.0 - ctx.min_cash)


class _ModelStrategy(Strategy):
    horizon = 5
    retrain = 63
    first = 504

    def _signals(self, panel: Panel, make_model, gate):
        X = build_features(panel)
        y = forward_return(panel, self.horizon)
        pred, fits = walk_forward_predict(X, y, make_model, self.horizon, self.first, self.retrain, gate)
        label = np.where(np.isfinite(y), (y > self.hurdle).astype(float), np.nan)
        m = np.isfinite(pred)
        self.diagnostics = {
            "n_refits": fits, "oos_auc": auc_score(pred[m], label[m]) if m.any() else None,
            "oos_rows": int((np.isfinite(pred) & np.isfinite(y)).sum()),
            "features": FEATURES, "horizon_days": self.horizon, "hurdle": self.hurdle,
        }
        return pred

    def _to_weights(self, panel: Panel, ctx: Ctx, pred: np.ndarray, threshold: float) -> np.ndarray:
        with np.errstate(invalid="ignore"):
            S = finite(pred) & (pred > threshold)
        held = sticky_topk(S, pred, ctx.k, monday_mask(panel))
        return equal_weights(held, ctx)


class StatRidge(_ModelStrategy):
    id, name, family = "stat_ridge", "Regressão ridge (modelo estatístico)", "estatística"
    description = ("Regressão ridge em painel (7 variáveis) prevendo o retorno de 5 dias; "
                   "re-treinada a cada 63 dias só com alvos já realizados (walk-forward). "
                   "Compra os k ativos com previsão acima do custo estimado.")

    def __init__(self, hurdle: float = 0.005):
        super().__init__(hurdle=hurdle)
        self.hurdle = hurdle

    def weights(self, panel: Panel, ctx: Ctx) -> np.ndarray:
        pred = self._signals(panel, lambda: Ridge(0.1), None)
        return self._to_weights(panel, ctx, pred, self.hurdle)


class MLGradientBoosting(_ModelStrategy):
    id, name, family = "ml_gbm", "Gradient boosting (ML, experimental)", "ml"
    experimental = True
    description = ("Classificador de gradient boosting raso/regularizado em painel; só treina com "
                   "dados suficientes (porta de justificativa) e compra os k ativos com maior "
                   "probabilidade acima da taxa-base + 5 p.p. Experimental: só vale se superar "
                   "o modelo linear e as referências passivas fora da amostra.")
    retrain = 126

    def __init__(self, hurdle: float = 0.005, edge: float = 0.05):
        super().__init__(hurdle=hurdle, edge=edge)
        self.hurdle, self.edge = hurdle, edge

    def weights(self, panel: Panel, ctx: Ctx) -> np.ndarray:
        try:
            import sklearn  # noqa: F401
        except ImportError:
            self.diagnostics = {"disabled": "scikit-learn não instalado"}
            return np.zeros((panel.T, panel.N))
        pred = self._signals(panel, lambda: GBMClassifier(self.hurdle), ml_gate)
        if self.diagnostics["n_refits"] == 0:
            self.diagnostics["disabled"] = "dados insuficientes (porta de justificativa de ML não satisfeita)"
        return self._to_weights(panel, ctx, pred, self.edge)
