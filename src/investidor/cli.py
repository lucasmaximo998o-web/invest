"""Linha de comando: investidor <comando>."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

from .config import load_config
from .paper.control import ACTIONS, apply_action

ISSUE_PREFIX = "/investidor "


def _dirs(args):
    state = Path(args.state_dir or os.environ.get("INVESTIDOR_STATE_DIR", "state"))
    cache = Path(args.cache_dir or os.environ.get("INVESTIDOR_CACHE_DIR", "data_cache"))
    out = Path(args.out_dir or os.environ.get("INVESTIDOR_OUT_DIR", "_site"))
    return state, cache, out


def cmd_cycle(args) -> int:
    from .cycle import run_cycle

    cfg = load_config(args.config)
    state, cache, out = _dirs(args)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    res = run_cycle(cfg, state, cache, out, as_of=as_of, offline=args.offline,
                    force_backtest=args.force_backtest, skip_backtest=args.skip_backtest)
    r = res["run"]
    print(f"[ok] ciclo concluído: as_of={r['as_of']} ativos={r['assets']} "
          f"novas_operacoes={r['new_trades']} novos_alertas={r['new_alerts']} ({r['seconds']}s)")
    return 0


def cmd_control(args) -> int:
    state, _, _ = _dirs(args)
    c = apply_action(state, args.action, args.actor)
    print(f"[ok] estado da simulação: {c['state']}")
    return 0


def cmd_control_from_title(args) -> int:
    """Interpreta o título de uma Issue '/investidor <ação>' (lista fechada de ações)."""
    title = (args.title or "").strip()
    if not title.lower().startswith(ISSUE_PREFIX):
        print("[ignorado] título não é um comando", file=sys.stderr)
        return 2
    action = title[len(ISSUE_PREFIX):].strip().lower()
    if action not in ACTIONS:
        print(f"[erro] ação inválida: {action[:30]!r}. Válidas: {', '.join(ACTIONS)}", file=sys.stderr)
        return 3
    state, _, _ = _dirs(args)
    c = apply_action(state, action, args.actor)
    print(f"[ok] ação '{action}' aplicada; estado: {c['state']}")
    return 0


def cmd_backtest(args) -> int:
    from .data.panel import build_panel
    from .data.store import load_market
    from .sim.backtest import run_full_backtest
    from .strategies.registry import build_strategies

    cfg = load_config(args.config)
    _, cache, _ = _dirs(args)
    md = load_market(cfg, cache, offline=args.offline)
    panel = build_panel(md.frames, cfg.assets, md.usdbrl, md.cdi, cfg.history_start, md.as_of)
    bt = run_full_backtest(panel, cfg, build_strategies(cfg), md.as_of, with_walk_forward=not args.fast)
    if args.out:
        Path(args.out).write_text(json.dumps(bt, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Backtest {bt['period']['start']} → {bt['period']['end']} | CDI {bt['cdi']['cagr']:.1%} a.a. | "
          f"universo: {', '.join(bt['universe'])}")
    print(f"{'estratégia':<15}{'CAGR':>8}{'Vol':>8}{'Sharpe':>8}{'MaxDD':>9}{'DSR':>7}{'R$50→':>9}")
    for r in sorted(bt["leaderboard"], key=lambda r: -(r.get("sharpe") or -9)):
        r50 = (r.get("r50") or {}).get("final")
        print(f"{r['id']:<15}{r['cagr']:>8.1%}{r['vol']:>8.1%}{r['sharpe']:>8.2f}{r['max_drawdown']:>9.1%}"
              f"{(r.get('dsr') or 0):>7.2f}{(r50 or 0):>9.1f}")
    print("\n[aviso] histórico simulado com viés de retrospecto; não é promessa de resultado.")
    return 0


def cmd_verify(args) -> int:
    from .paper.ledger import verify_ledger

    state, _, _ = _dirs(args)
    ok, why = verify_ledger(state / "trades.csv")
    print(("[ok] livro-razão íntegro" if ok else f"[ERRO] {why}"))
    return 0 if ok else 1


def cmd_serve(args) -> int:
    import functools
    import http.server

    _, _, out = _dirs(args)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"painel em http://127.0.0.1:{args.port}  (Ctrl+C para sair)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="investidor", description="INVESTIDOR AI - somente simulação (paper trading)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--state-dir")
    ap.add_argument("--cache-dir")
    ap.add_argument("--out-dir")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("cycle", help="executa o ciclo diário completo")
    c.add_argument("--as-of")
    c.add_argument("--offline", action="store_true")
    c.add_argument("--force-backtest", action="store_true")
    c.add_argument("--skip-backtest", action="store_true")
    c.set_defaults(fn=cmd_cycle)

    c = sub.add_parser("control", help="iniciar/pausar/retomar/interromper a simulação")
    c.add_argument("action", choices=ACTIONS)
    c.add_argument("--actor", default="cli")
    c.set_defaults(fn=cmd_control)

    c = sub.add_parser("control-from-title", help="aplica comando vindo do título de uma Issue")
    c.add_argument("--title", required=True)
    c.add_argument("--actor", default="issue")
    c.set_defaults(fn=cmd_control_from_title)

    c = sub.add_parser("backtest", help="backtest completo + walk-forward (imprime placar)")
    c.add_argument("--offline", action="store_true")
    c.add_argument("--fast", action="store_true", help="pula o walk-forward")
    c.add_argument("--out")
    c.set_defaults(fn=cmd_backtest)

    c = sub.add_parser("verify", help="verifica a integridade do livro-razão")
    c.set_defaults(fn=cmd_verify)

    c = sub.add_parser("serve", help="serve o painel localmente (pré-visualização)")
    c.add_argument("--port", type=int, default=8000)
    c.set_defaults(fn=cmd_serve)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
