"""Ciclo diário do INVESTIDOR AI: dados -> sinais -> paper trading -> alertas -> relatório -> painel."""
from __future__ import annotations

import logging
import os
import shutil
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import alerts as alerts_mod
from .config import Config, assert_paper_mode
from .data import providers as P
from .data.panel import build_panel
from .data.store import load_market, quality_summary
from .export import build_snapshot
from .paper.control import load_control
from .paper.ledger import append_jsonl, read_json, read_jsonl, write_json
from .paper.runner import PaperRunner
from .report import render_markdown
from .sim.backtest import run_full_backtest
from .strategies.base import Ctx
from .strategies.registry import build_strategies

log = logging.getLogger("investidor.cycle")
SITE_SRC = Path(__file__).resolve().parents[2] / "site"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _backtest_due(path: Path, cfg: Config, force: bool) -> bool:
    if force or not path.exists():
        return True
    bt = read_json(path, {})
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(bt["generated_at"])
    except (KeyError, ValueError):
        return True
    return age >= timedelta(days=cfg.backtest_refresh_days)


def run_cycle(cfg: Config, state_dir: str | Path, cache_dir: str | Path, out_dir: str | Path,
              as_of=None, offline: bool = False, force_backtest: bool = False, skip_backtest: bool = False,
              brapi_token: str | None = None) -> dict:
    assert_paper_mode(cfg)
    state_dir, out_dir = Path(state_dir), Path(out_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    brapi_token = brapi_token or os.environ.get("BRAPI_TOKEN") or None
    t0 = time.time()
    run_info = {"ts": _now(), "status": "started"}
    try:
        control = load_control(state_dir)
        md = load_market(cfg, cache_dir, as_of=as_of, brapi_token=brapi_token, offline=offline)
        panel = build_panel(md.frames, cfg.assets, md.usdbrl, md.cdi, cfg.history_start, md.as_of)
        as_of_idx = panel.T - 1
        strategies = build_strategies(cfg)
        ctx = Ctx(cfg.execution.max_positions, cfg.execution.min_cash)
        weights = {sid: s.weights(panel, ctx) for sid, s in strategies.items()}
        diagnostics = {sid: s.diagnostics for sid, s in strategies.items() if s.diagnostics}

        # --- paper trading
        runner = PaperRunner(cfg, panel, strategies, weights, state_dir)
        runner.process(control, as_of_idx)

        # --- alertas (antes de salvar: atualizam o estado de alertas por carteira)
        existing = read_jsonl(state_dir / "alerts.jsonl", last=2000)
        new_alerts = alerts_mod.evaluate(cfg, runner.paper, runner.events, runner.new_equity, md, panel,
                                         as_of_idx, {a["id"] for a in existing})
        runner.save()
        write_json(state_dir / "control.json", control)
        append_jsonl(state_dir / "alerts.jsonl", new_alerts)
        alerts_mod.notify(new_alerts)
        write_json(out_dir / "new_alerts.json", new_alerts)
        all_alerts = existing + new_alerts

        # --- backtest histórico (semanal) - nunca bloqueia o paper trading
        bt_path = state_dir / "backtest.json"
        backtest = read_json(bt_path)
        if not skip_backtest and _backtest_due(bt_path, cfg, force_backtest):
            log.info("recalculando backtest completo (walk-forward)...")
            try:
                backtest = run_full_backtest(panel, cfg, strategies, md.as_of)
                write_json(bt_path, backtest)
            except Exception as exc:  # noqa: BLE001
                log.exception("backtest falhou")
                err = alerts_mod.make("BACKTEST_ERRO", "warning", f"Backtest falhou: {exc}", str(md.as_of))
                append_jsonl(state_dir / "alerts.jsonl", [err])
                all_alerts.append(err)

        # --- snapshot, relatório e site
        write_json(state_dir / "data_quality.json", quality_summary(md))
        run_info.update({"status": "ok", "as_of": str(md.as_of), "assets": len(panel.ids),
                         "new_trades": len(runner.new_trades), "new_alerts": len(new_alerts),
                         "seconds": round(time.time() - t0, 1)})
        append_jsonl(state_dir / "runs.jsonl", [run_info])
        snap = build_snapshot(cfg, state_dir, panel, md, strategies, control, runner.paper, all_alerts,
                              backtest, diagnostics, as_of_idx)
        report = render_markdown(snap)
        rep_dir = state_dir / "reports"
        rep_dir.mkdir(parents=True, exist_ok=True)
        (rep_dir / f"{snap['as_of']}.md").write_text(report, encoding="utf-8")
        (rep_dir / "latest.md").write_text(report, encoding="utf-8")
        publish_site(out_dir, snap, report)
        return {"run": run_info, "snapshot": snap}
    except Exception as exc:  # noqa: BLE001
        run_info.update({"status": "error", "error": f"{type(exc).__name__}: {exc}",
                         "seconds": round(time.time() - t0, 1)})
        append_jsonl(state_dir / "runs.jsonl", [{**run_info, "traceback": traceback.format_exc()[-1500:]}])
        err = alerts_mod.make("CICLO_ERRO", "critical", f"O ciclo falhou: {type(exc).__name__}: {str(exc)[:300]}",
                              str(P.utc_today()), key=f"CICLO_ERRO:{_now()}")
        append_jsonl(state_dir / "alerts.jsonl", [err])
        write_json(out_dir / "new_alerts.json", [err])
        alerts_mod.notify([err])
        raise


def publish_site(out_dir: Path, snap: dict, report_md: str) -> None:
    """Copia o painel estático e grava os dados que ele consome."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if SITE_SRC.exists():
        for f in SITE_SRC.iterdir():
            if f.is_file():
                shutil.copy2(f, out_dir / f.name)
    write_json(out_dir / "data" / "dashboard.json", snap)
    (out_dir / "data" / "relatorio.md").write_text(report_md, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

