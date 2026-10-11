"""Coleta de todos os dados do universo, com cache local e degradação controlada.

Política: sempre tenta baixar dados novos; se a API falhar, usa o cache (marcado como
"cache") e registra aviso; se não houver cache, o ativo fica de fora do ciclo.
Dados atrasados além do limite são excluídos (nunca decide com dados velhos).
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import AssetSpec, Config
from . import providers as P
from .quality import BLOCKING, assess

log = logging.getLogger("investidor.data")


@dataclass
class MarketData:
    as_of: date
    frames: dict[str, pd.DataFrame]
    usdbrl: pd.Series
    cdi: pd.Series
    quality: dict[str, dict]
    skipped: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    crosscheck: dict = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)  # asset -> "api" | "cache"
    fetched_at: str = ""


def _cache_path(cache_dir: Path, name: str) -> Path:
    return cache_dir / f"{name}.csv"


def _read_cache(cache_dir: Path, name: str) -> pd.DataFrame | None:
    p = _cache_path(cache_dir, name)
    if not p.exists():
        return None
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    df.index.name = "date"
    return df


def _write_cache(cache_dir: Path, name: str, df: pd.DataFrame | pd.Series) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(_cache_path(cache_dir, name))


def _fetch_asset(spec: AssetSpec, cfg: Config, brapi_token: str | None) -> pd.DataFrame:
    if spec.provider == "binance":
        return P.fetch_binance(spec.symbol, cfg.history_start)
    if spec.provider == "nasdaq":
        return P.fetch_nasdaq(spec.symbol, spec.assetclass, cfg.history_start)
    if spec.provider == "brapi":
        return P.fetch_brapi(spec.symbol, brapi_token, cfg.brapi_range)
    raise P.DataError(f"provider desconhecido {spec.provider}")


def stale_limit(spec: AssetSpec, cfg: Config) -> int:
    return 2 if spec.klass == "crypto" else cfg.stale_after_days


def load_market(cfg: Config, cache_dir: str | Path, as_of: date | None = None,
                brapi_token: str | None = None, offline: bool = False) -> MarketData:
    cache_dir = Path(cache_dir)
    as_of = as_of or P.default_as_of()
    usable, skipped_specs = cfg.active_assets(brapi_token)
    md = MarketData(as_of=as_of, frames={}, usdbrl=pd.Series(dtype=float), cdi=pd.Series(dtype=float),
                    quality={}, fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    for s in skipped_specs:
        md.skipped.append({"asset": s.id, "reason": "requer BRAPI_TOKEN (gratuito em brapi.dev)"})

    def get(spec: AssetSpec) -> tuple[AssetSpec, pd.DataFrame | None, str, str | None]:
        err = None
        if not offline:
            try:
                df = _fetch_asset(spec, cfg, brapi_token)
                _write_cache(cache_dir, f"asset_{spec.id}", df)
                return spec, df, "api", None
            except Exception as exc:  # noqa: BLE001 - qualquer falha cai para o cache
                err = f"{type(exc).__name__}: {exc}"
        cached = _read_cache(cache_dir, f"asset_{spec.id}")
        return spec, cached, "cache", err

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(get, usable))

    for spec, df, source, err in results:
        if err:
            md.notes.append(f"{spec.id}: falha ao baixar ({err[:160]}); usando cache" if df is not None
                            else f"{spec.id}: falha ao baixar ({err[:160]}) e sem cache")
        if df is None:
            md.skipped.append({"asset": spec.id, "reason": "sem dados (API falhou, sem cache)"})
            continue
        df = df[df.index <= pd.Timestamp(as_of)]
        q = assess(df, spec, as_of, stale_limit(spec, cfg))
        md.quality[spec.id] = q
        if source == "cache":
            q["issues"].append({"severity": "aviso", "message": "dados vindos do cache local"})
        if not q["ok"]:
            reason = "; ".join(i["message"] for i in q["issues"] if i["severity"] == BLOCKING)
            md.skipped.append({"asset": spec.id, "reason": reason})
            continue
        md.frames[spec.id] = df
        md.sources[spec.id] = source

    # --- câmbio e CDI (essenciais: sem eles não há ciclo confiável)
    for name, fetch in (("usdbrl", P.fetch_usdbrl), ("cdi", P.fetch_cdi_daily)):
        series = None
        if not offline:
            try:
                series = fetch(cfg.history_start)
                _write_cache(cache_dir, name, series.rename(name).to_frame())
            except Exception as exc:  # noqa: BLE001
                md.notes.append(f"{name}: falha ao baixar ({str(exc)[:160]}); usando cache")
        if series is None:
            cached = _read_cache(cache_dir, name)
            if cached is None:
                raise P.DataError(f"série {name} indisponível e sem cache")
            series = cached.iloc[:, 0]
        series = series[series.index <= pd.Timestamp(as_of)]
        setattr(md, name, series)
        lag = (pd.Timestamp(as_of) - series.index.max()).days
        if lag > 5:
            md.notes.append(f"{name}: última observação {series.index.max().date()} ({lag} dias de defasagem)")

    if not offline:
        md.crosscheck = crosscheck_crypto(cfg, md)
    return md


def crosscheck_crypto(cfg: Config, md: MarketData, tol: float = 0.015) -> dict:
    """Compara o preço spot Binance com o CoinGecko (fonte independente). Falha é não-fatal."""
    out: dict = {"checked": {}, "ok": None}
    try:
        cg_ids = {a.id: a.coingecko for a in cfg.assets if a.klass == "crypto" and a.coingecko and a.id in md.frames}
        if not cg_ids:
            return out
        bn = P.fetch_binance_spot([cfg.asset(i).symbol for i in cg_ids])
        cg = P.fetch_coingecko_spot(list(cg_ids.values()))
        worst = 0.0
        for aid, cgid in cg_ids.items():
            b, c = bn.get(cfg.asset(aid).symbol), cg.get(cgid)
            if b and c:
                dev = abs(b / c - 1)
                worst = max(worst, dev)
                out["checked"][aid] = {"binance": b, "coingecko": c, "desvio_pct": round(dev * 100, 3)}
        out["ok"] = worst <= tol
        if not out["ok"]:
            md.notes.append(f"checagem cruzada cripto: desvio máximo {worst:.2%} > {tol:.1%}")
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


def quality_summary(md: MarketData) -> dict:
    return json.loads(json.dumps({
        "as_of": str(md.as_of), "fetched_at": md.fetched_at, "assets": md.quality,
        "skipped": md.skipped, "notes": md.notes, "crosscheck": md.crosscheck, "sources": md.sources,
    }, default=str))
