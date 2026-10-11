"""Carregamento e validação da configuração (config/investidor.toml)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "investidor.toml"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class CostModel:
    """Custos em bps (1 bps = 0,01%) sobre o valor financeiro da ordem."""

    fee_bps: float
    spread_bps: float
    slippage_bps: float
    entry_extra_bps: float = 0.0
    exit_extra_bps: float = 0.0

    @property
    def slip_bps(self) -> float:
        """Deslocamento do preço de execução contra nós (meio spread + derrapagem)."""
        return self.spread_bps / 2.0 + self.slippage_bps

    @property
    def buy_fee_bps(self) -> float:
        return self.fee_bps + self.entry_extra_bps

    @property
    def sell_fee_bps(self) -> float:
        return self.fee_bps + self.exit_extra_bps

    @property
    def round_trip_bps(self) -> float:
        return 2 * self.slip_bps + self.buy_fee_bps + self.sell_fee_bps


@dataclass(frozen=True)
class AssetSpec:
    id: str
    name: str
    klass: str  # crypto | us | b3
    provider: str  # binance | nasdaq | brapi
    symbol: str
    currency: str  # USD | BRL
    qty_step: float
    assetclass: str = ""  # nasdaq: etf | stocks
    coingecko: str = ""
    total_return: bool = True
    requires_token: bool = False


@dataclass(frozen=True)
class Execution:
    min_order_brl: float
    rebalance_threshold: float  # fração do patrimônio
    max_positions: int
    min_cash: float  # fração


@dataclass(frozen=True)
class Risk:
    max_drawdown_halt: float  # fração, ex.: 0.25
    drawdown_alert_levels: tuple[float, ...]
    daily_loss_alert: float
    asset_move_alert: float
    stale_hours: float


@dataclass
class Config:
    raw: dict
    mode: str
    history_start: str
    primary_strategy: str
    brapi_range: str
    stale_after_days: int
    backtest_refresh_days: int
    paper_initial: float
    reference_initial: float
    execution: Execution
    risk: Risk
    costs: dict[str, CostModel]
    assets: list[AssetSpec]
    ew_assets: list[str]
    path: Path = field(default=DEFAULT_CONFIG)

    def asset(self, asset_id: str) -> AssetSpec:
        for a in self.assets:
            if a.id == asset_id:
                return a
        raise KeyError(asset_id)

    def active_assets(self, brapi_token: str | None) -> tuple[list[AssetSpec], list[AssetSpec]]:
        """(ativos usáveis, ativos pulados por falta de token)."""
        ok, skipped = [], []
        for a in self.assets:
            if a.requires_token and not brapi_token:
                skipped.append(a)
            else:
                ok.append(a)
        return ok, skipped


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path or os.environ.get("INVESTIDOR_CONFIG") or DEFAULT_CONFIG)
    with open(p, "rb") as fh:
        raw = tomllib.load(fh)

    g, cap, ex, rk = raw["general"], raw["capital"], raw["execution"], raw["risk"]
    if g.get("mode") != "paper":
        # Barreira de segurança: este projeto só opera em simulação.
        raise ConfigError(
            "mode deve ser 'paper'. Operação com dinheiro real NÃO é suportada "
            "(ver docs/INTEGRACAO_REAL.md)."
        )
    costs = {k: CostModel(**{kk: float(vv) for kk, vv in v.items()}) for k, v in raw["costs"].items()}
    assets = [AssetSpec(**a) for a in raw["assets"]]
    ids = [a.id for a in assets]
    if len(ids) != len(set(ids)):
        raise ConfigError("ids de ativos duplicados")
    for a in assets:
        if a.klass not in costs:
            raise ConfigError(f"sem modelo de custos para a classe '{a.klass}'")
        if a.provider not in ("binance", "nasdaq", "brapi"):
            raise ConfigError(f"provider desconhecido: {a.provider}")
    execution = Execution(
        min_order_brl=float(ex["min_order_brl"]),
        rebalance_threshold=float(ex["rebalance_threshold_pct"]) / 100.0,
        max_positions=int(ex["max_positions"]),
        min_cash=float(ex["min_cash_pct"]) / 100.0,
    )
    risk = Risk(
        max_drawdown_halt=float(rk["max_drawdown_halt_pct"]) / 100.0,
        drawdown_alert_levels=tuple(float(x) / 100.0 for x in rk["drawdown_alert_levels_pct"]),
        daily_loss_alert=float(rk["daily_loss_alert_pct"]) / 100.0,
        asset_move_alert=float(rk["asset_move_alert_pct"]) / 100.0,
        stale_hours=float(rk["benchmarks_stale_hours"]),
    )
    return Config(
        raw=raw,
        mode="paper",
        history_start=g["history_start"],
        primary_strategy=g["primary_strategy"],
        brapi_range=g.get("brapi_range", "10y"),
        stale_after_days=int(g.get("stale_after_days", 4)),
        backtest_refresh_days=int(g.get("backtest_refresh_days", 7)),
        paper_initial=float(cap["paper_initial_brl"]),
        reference_initial=float(cap["reference_initial_brl"]),
        execution=execution,
        risk=risk,
        costs=costs,
        assets=assets,
        ew_assets=list(raw["passive"]["ew_assets"]),
        path=p,
    )


def assert_paper_mode(cfg: Config) -> None:
    """Chamado antes de qualquer execução; falha se algo tentar sair do modo paper."""
    if cfg.mode != "paper":
        raise ConfigError("Somente paper trading é permitido.")
    if os.environ.get("INVESTIDOR_LIVE") or os.environ.get("INVESTIDOR_MODE", "paper") != "paper":
        raise ConfigError(
            "Variável de ambiente tentou habilitar modo real. Operação real está "
            "bloqueada por design (ver docs/INTEGRACAO_REAL.md)."
        )
