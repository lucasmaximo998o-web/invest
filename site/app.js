/* INVESTIDOR AI - painel mobile (JS puro, sem dependências). Lê data/dashboard.json. */
(() => {
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const BRL = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const brl = x => (x == null || isNaN(x)) ? 'n/d' : BRL.format(x);
const num = (x, d = 2) => (x == null || isNaN(x)) ? 'n/d' : Number(x).toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (x, d = 1, sign = false) => (x == null || isNaN(x)) ? 'n/d' : (sign && x > 0 ? '+' : '') + num(x * 100, d) + '%';
const sgn = x => x > 0 ? 'pos' : x < 0 ? 'neg' : '';
const safe = fn => { try { return fn(); } catch (e) { return null; } };

let D = null;                 // dashboard.json
let tab = 'resumo';
const TABS = [['resumo', 'Resumo'], ['carteiras', 'Carteiras'], ['operacoes', 'Operações'], ['risco', 'Risco'],
              ['alertas', 'Alertas'], ['estudo', 'Estudo'], ['controle', 'Controle']];

/* ---------- procedência: ícone + texto (nunca só cor) ---------- */
const chip = k => ({
  real: '<span class="chip real" title="Dados reais de mercado (preços e câmbio)">● DADOS REAIS</span>',
  sim: '<span class="chip sim" title="Simulação com dinheiro fictício (paper trading)">◆ SIMULAÇÃO</span>',
  hist: '<span class="chip hist" title="Histórico simulado (backtest) - não é resultado real">▲ HISTÓRICO</span>',
}[k]);
const head = (t, ...chips) => `<div class="row" style="justify-content:space-between;align-items:center"><h2>${esc(t)}</h2><div class="row" style="gap:6px">${chips.map(chip).join('')}</div></div>`;

/* ---------- cores: categóricas FIXAS por entidade (não mudam ao filtrar) ---------- */
const FIXED = ['dual_momentum', 'bh_btc', 'bh_spy', 'bh_ew', 'ew_all'];
const dyn = {};
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function slotOf(id, selected) {
  if (id === 'cdi') return -1;
  const f = FIXED.indexOf(id);
  if (f >= 0) return f;
  if (dyn[id] != null) return dyn[id];
  const used = new Set(Object.entries(dyn).filter(([k]) => selected.includes(k)).map(([, v]) => v));
  for (let i = FIXED.length; i < 8; i++) if (!used.has(i)) { dyn[id] = i; return i; }
  return FIXED.length;
}
const colorOf = (id, selected) => { const s = slotOf(id, selected); return s < 0 ? cssVar('--muted') : cssVar('--s' + (s + 1)); };

/* ---------- gráfico de linhas ---------- */
const T = d => Date.parse(d + 'T00:00:00Z');
function bisect(arr, t) { let lo = 0, hi = arr.length - 1, r = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m][0] <= t) { r = m; lo = m + 1; } else hi = m - 1; } return r; }
function niceTicks(min, max, n = 4) {
  const span = (max - min) || Math.abs(max) || 1, s0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(s0))), e = s0 / mag;
  const step = (e >= 5 ? 10 : e >= 2 ? 5 : e >= 1 ? 2 : 1) * mag, out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) out.push(+v.toFixed(10));
  return out;
}
function logTicks(min, max) {
  const out = []; for (let k = Math.floor(Math.log10(min)); k <= Math.ceil(Math.log10(max)); k++) for (const m of [1, 2, 5]) { const v = m * Math.pow(10, k); if (v >= min && v <= max) out.push(v); }
  return out.length >= 2 ? out : [min, max];
}
const compact = v => Math.abs(v) >= 1000 ? num(v / 1000, 1) + 'K' : num(v, Math.abs(v) < 10 ? 2 : 0);

/* cfg: {series:[{id,name,pts:[[ms,v]]}], fmt, log, h, selected:Set, onToggle} */
function lineChart(host, cfg) {
  host._cfg = cfg;
  const draw = () => {
    const c = host._cfg, vis = c.series.filter(s => c.visible.has(s.id) && s.pts.length);
    const W = Math.max(300, host.clientWidth || 340), H = c.h || 220, m = { l: 46, r: 14, t: 10, b: 24 };
    const sel = c.series.map(s => s.id);
    vis.forEach(s => { s.color = colorOf(s.id, sel); });
    c.series.forEach(s => { s.color = s.color || colorOf(s.id, sel); });
    if (!vis.length) { host.querySelector('svg')?.remove(); return; }
    let t0 = Infinity, t1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    vis.forEach(s => s.pts.forEach(([t, v]) => { t0 = Math.min(t0, t); t1 = Math.max(t1, t); if (isFinite(v) && (!c.log || v > 0)) { y0 = Math.min(y0, v); y1 = Math.max(y1, v); } }));
    if (t0 === t1) { t0 -= 864e5; t1 += 864e5; }
    const pad = (y1 - y0) * 0.06 || Math.abs(y1) * 0.02 || 1;
    if (!c.log) { y0 -= pad; y1 += pad; } else { y0 *= 0.93; y1 *= 1.07; }
    const fy = c.log ? Math.log : (v => v);
    const X = t => m.l + (t - t0) / (t1 - t0) * (W - m.l - m.r);
    const Y = v => m.t + (1 - (fy(v) - fy(y0)) / (fy(y1) - fy(y0))) * (H - m.t - m.b);
    const yt = c.log ? logTicks(y0, y1) : niceTicks(y0, y1, 4);
    const long = (t1 - t0) > 150 * 864e5;
    const xl = t => new Date(t).toLocaleDateString('pt-BR', long ? { month: 'short', year: '2-digit', timeZone: 'UTC' } : { day: '2-digit', month: '2-digit', timeZone: 'UTC' });
    let g = '';
    yt.forEach(v => { g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)" stroke-width="1"/><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${esc((c.yAxis || compact)(v))}</text>`; });
    for (let i = 0; i < 4; i++) { const t = t0 + (t1 - t0) * i / 3; g += `<text x="${X(t)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === 3 ? 'end' : 'middle'}" font-size="11" fill="var(--muted)">${esc(xl(t))}</text>`; }
    g += `<line x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}" stroke="var(--axis)"/>`;
    vis.forEach(s => {
      const d = s.pts.filter(p => isFinite(p[1]) && (!c.log || p[1] > 0)).map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('');
      const last = s.pts[s.pts.length - 1];
      g += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
      g += `<circle cx="${X(last[0])}" cy="${Y(last[1])}" r="4" fill="${s.color}" stroke="var(--surface)" stroke-width="2"/>`;
    });
    g += `<line id="xh" y1="${m.t}" y2="${H - m.b}" stroke="var(--axis)" stroke-width="1" style="display:none"/>`;
    host.querySelector('svg')?.remove();
    host.insertAdjacentHTML('afterbegin', `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(c.label || 'gráfico de linhas')}">${g}<rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent" id="hit"/></svg>`);
    const svg = host.querySelector('svg'), xh = svg.querySelector('#xh'), tt = host.querySelector('.tt');
    const allT = [...new Set(vis.flatMap(s => s.pts.map(p => p[0])))].sort((a, b) => a - b);
    const show = ev => {
      const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) / r.width * W;
      const t = t0 + (px - m.l) / (W - m.l - m.r) * (t1 - t0);
      let k = bisect(allT.map(x => [x]), t); if (k < 0) k = 0; if (k + 1 < allT.length && Math.abs(allT[k + 1] - t) < Math.abs(allT[k] - t)) k++;
      const tm = allT[k]; xh.setAttribute('x1', X(tm)); xh.setAttribute('x2', X(tm)); xh.style.display = '';
      const rows = vis.map(s => { const i = bisect(s.pts, tm); return i < 0 ? '' : `<div class="r"><span><i class="sw" style="background:${s.color}"></i>${esc(s.name)}</span><b>${esc(c.fmt(s.pts[i][1]))}</b></div>`; }).join('');
      tt.innerHTML = `<div class="d">${new Date(tm).toLocaleDateString('pt-BR', { timeZone: 'UTC' })}</div>${rows}`;
      tt.style.display = 'block';
      const left = Math.min(Math.max(px / W * host.clientWidth - 75, 0), host.clientWidth - tt.offsetWidth);
      tt.style.left = left + 'px'; tt.style.top = '4px';
    };
    const hide = () => { xh.style.display = 'none'; tt.style.display = 'none'; };
    const hit = svg.querySelector('#hit');
    hit.addEventListener('pointermove', show); hit.addEventListener('pointerdown', show);
    hit.addEventListener('pointerleave', hide); hit.addEventListener('pointercancel', hide);
    // legenda e tabela
    const lg = host.parentElement.querySelector('.legend');
    if (lg) lg.innerHTML = c.series.map(s => `<button type="button" data-id="${esc(s.id)}" aria-pressed="${c.visible.has(s.id)}"><i class="sw" style="background:${s.color}"></i>${esc(s.name)}</button>`).join('');
    const tb = host.parentElement.querySelector('.tv .tablewrap');
    if (tb) {
      const step = Math.max(1, Math.floor(allT.length / 40)), rows = allT.filter((_, i) => i % step === 0 || i === allT.length - 1);
      tb.innerHTML = `<table><thead><tr><th>Data</th>${vis.map(s => `<th>${esc(s.name)}</th>`).join('')}</tr></thead><tbody>${rows.map(t => `<tr><td>${new Date(t).toLocaleDateString('pt-BR', { timeZone: 'UTC' })}</td>${vis.map(s => { const i = bisect(s.pts, t); return `<td class="num">${i < 0 ? '' : esc(c.fmt(s.pts[i][1]))}</td>`; }).join('')}</tr>`).join('')}</tbody></table>`;
    }
  };
  draw();
  if (!host._ro && window.ResizeObserver) { host._lastW = host.clientWidth; host._ro = new ResizeObserver(() => { if (Math.abs(host.clientWidth - host._lastW) > 8) { host._lastW = host.clientWidth; draw(); } }); host._ro.observe(host); }
  host._redraw = draw;
}
function chartBlock(id, h = 220) {
  return `<div class="chartbox"><div class="chart" id="${id}" style="min-height:${h}px"><div class="tt" style="display:none"></div></div><div class="legend" aria-label="Legenda (toque para ocultar/mostrar)"></div><details class="tv"><summary>Ver como tabela</summary><div class="tablewrap"></div></details></div>`;
}
function mountChart(id, series, opts = {}) {
  const host = $('#' + id); if (!host) return;
  const visible = new Set(opts.visible || series.map(s => s.id));
  lineChart(host, { series, visible, fmt: opts.fmt || brl, yAxis: opts.yAxis, log: !!opts.log, h: opts.h || 220, label: opts.label });
  const lg = host.parentElement.querySelector('.legend');
  lg.onclick = ev => { const b = ev.target.closest('button[data-id]'); if (!b) return; const k = b.dataset.id; visible.has(k) ? visible.delete(k) : visible.add(k); host._redraw(); opts.onToggle && opts.onToggle(visible); };
  return { host, visible };
}
const toPts = curve => (curve || []).map(([d, v]) => [T(d), v]);

/* ---------- utilitários de dados ---------- */
const byId = id => (D.portfolios || []).find(p => p.id === id);
const prim = () => byId(D.primary);
const repoSlug = () => {
  if (D && D.repo) return D.repo;
  const m = location.hostname.match(/^([^.]+)\.github\.io$/); const r = location.pathname.split('/')[1];
  return m && r ? `${m[1]}/${r}` : null;
};
const STATE = { running: ['▶ EM EXECUÇÃO', 'state-running'], paused: ['⏸ PAUSADA', 'state-paused'], stopped: ['⏹ INTERROMPIDA', 'state-stopped'] };
const statePill = s => { const [t, c] = STATE[s] || [s, '']; return `<span class="chip ${c}">${t}</span>`; };
const ageH = () => (Date.now() - Date.parse(D.generated_at)) / 36e5;

/* ---------- seções ---------- */
function vResumo() {
  const p = prim(), ctl = D.control || {}, stale = ageH() > 36;
  let h = '';
  if (stale) h += `<div class="banner crit" role="alert"><b>Dados atrasados.</b> Última atualização há ${num(ageH(), 0)} h. Verifique a aba Actions do GitHub (o agendamento pode ter falhado).</div>`;
  h += `<div class="card">${head('Simulação', 'sim')}<div class="row" style="align-items:center;gap:8px">${statePill(ctl.state)}<small>Rodada <b>${esc(D.run.run_id || '—')}</b> desde ${esc(D.run.start_date || '—')}</small></div>`;
  if (!p) {
    h += `<p class="muted">Nenhuma simulação ativa. Vá em <b>Controle</b> e toque em “Iniciar”.</p></div>`;
  } else {
    const s = p.summary;
    h += `<small>${esc(p.name)} · patrimônio simulado</small><div class="hero">${brl(s.equity)}</div>
      <div class="${sgn(s.return)}"><b>${pct(s.return, 2, true)}</b> · ${s.pnl >= 0 ? 'lucro' : 'prejuízo'} de <b>${brl(Math.abs(s.pnl))}</b> em ${s.days} dia(s)</div>
      ${p.halt_reason ? `<div class="banner crit" style="margin-top:8px">🛑 ${esc(p.status)} — ${esc(p.halt_reason)}</div>` : ''}</div>`;
    h += `<div class="tiles">
      <div class="tile"><div class="l">Capital inicial simulado</div><div class="v">${brl(s.initial)}</div></div>
      <div class="tile"><div class="l">Lucro / prejuízo</div><div class="v ${sgn(s.pnl)}">${brl(s.pnl)}</div></div>
      <div class="tile"><div class="l">Rentabilidade</div><div class="v ${sgn(s.return)}">${pct(s.return, 2, true)}</div></div>
      <div class="tile"><div class="l">Drawdown atual</div><div class="v">${pct(s.current_drawdown)}</div></div>
      <div class="tile"><div class="l">Drawdown máximo</div><div class="v">${pct(s.max_drawdown)}</div></div>
      <div class="tile"><div class="l">Posições abertas</div><div class="v">${p.positions.length}</div></div></div>`;
    h += `<div class="card">${head('Desempenho vs referências passivas', 'sim')}<small>Cada linha parte de ${brl(s.initial)} fictícios. Passivas = comprar e segurar, com os mesmos custos.</small>${chartBlock('c-res')}</div>`;
  }
  h += `<div class="card">${head('Dinheiro real', 'real')}<div class="kv"><div>Movimentado pelo sistema</div><div><b>${brl(D.labels.dinheiro_real_movimentado_brl)}</b></div><div>Reservado por você</div><div>${brl(D.labels.capital_real_reservado_brl)} (intocado)</div><div>Operação real</div><div><b>DESABILITADA</b></div></div>
    <small>${esc(D.labels.aviso)}</small></div>`;
  const al = (D.alerts || []).filter(a => a.severity !== 'info').slice(0, 3);
  h += `<div class="card"><h2>Alertas recentes</h2>${al.length ? '<ul class="clean">' + al.map(alertItem).join('') + '</ul>' : '<small>Nenhum alerta de aviso/crítico.</small>'}</div>`;
  h += `<div class="card">${head('Dados de mercado', 'real')}<div class="kv"><div>Último pregão/candle fechado</div><div>${esc(D.as_of)}</div><div>Ativos no ciclo</div><div>${(D.data.universe_used || []).length}</div><div>Atualizado em</div><div>${new Date(D.generated_at).toLocaleString('pt-BR')}</div></div>
    ${(D.data.skipped || []).length ? `<small>Fora do ciclo: ${D.data.skipped.map(s => esc(s.asset)).join(', ')} (ver aba Risco)</small>` : ''}</div>`;
  $('#view').innerHTML = h;
  if (p) {
    const ids = ['bh_btc', 'bh_spy', 'bh_ew'], ser = [{ id: p.id, name: p.name.split(' (')[0], pts: toPts(p.curve) }];
    ids.forEach(i => { const q = byId(i); if (q) ser.push({ id: i, name: q.name.replace('Passiva: ', ''), pts: toPts(q.curve) }); });
    if (D.cdi_curve?.length) ser.push({ id: 'cdi', name: 'CDI (100%)', pts: toPts(D.cdi_curve) });
    mountChart('c-res', ser, { label: 'Patrimônio simulado vs referências', yAxis: v => num(v, 0) });
  }
}

const alertItem = a => `<li><span class="sev ${esc(a.severity)}">${{ critical: 'CRÍTICO', warning: 'AVISO', info: 'INFO' }[a.severity] || esc(a.severity)}</span> <small>${esc(a.date)}</small><br>${esc(a.message)}</li>`;

function vCarteiras() {
  const L = [...(D.portfolios || [])].sort((a, b) => b.summary.return - a.summary.return);
  let h = `<div class="card">${head('Carteiras simuladas', 'sim')}<small>${L.length} carteiras, cada uma com ${brl(D.run.initial)} fictícios, rodando estratégias diferentes sob as mesmas regras de risco. Toque para ver detalhes.</small></div>`;
  if (!L.length) h += '<p class="muted">Sem carteiras ainda.</p>';
  L.forEach(p => {
    const s = p.summary;
    h += `<details class="card" data-pid="${esc(p.id)}"><summary style="cursor:pointer;min-height:44px"><b>${esc(p.name)}</b>${p.id === D.primary ? ' <span class="pill">principal</span>' : ''}${p.experimental ? ' <span class="pill">experimental</span>' : ''}<br>
      <span class="${sgn(s.return)}"><b>${brl(s.equity)}</b> (${pct(s.return, 2, true)})</span> <small>· DD ${pct(s.current_drawdown)} · ${esc(p.status)} · ${esc(p.family)}</small></summary>
      <p class="small">${esc(p.description)}</p>
      <div class="kv"><div>Caixa</div><div>${brl(p.cash)}</div><div>Taxas pagas</div><div>${brl(p.fees_paid)}</div><div>Derrapagem/spread</div><div>${brl(p.slippage_paid)}</div><div>Proventos recebidos</div><div>${brl(p.dividends)}</div></div>
      <h3>Posições (fictícias)</h3>${p.positions.length ? `<div class="tablewrap"><table><thead><tr><th>Ativo</th><th>Qtd</th><th>Preço</th><th>Valor</th></tr></thead><tbody>${p.positions.map(x => `<tr><td>${esc(x.asset)}</td><td class="num">${num(x.qty, 6)}</td><td class="num">${brl(x.price_brl)}</td><td class="num">${brl(x.value_brl)}</td></tr>`).join('')}</tbody></table></div>` : '<small>100% em caixa.</small>'}
      ${p.halt_reason ? `<div class="banner crit">🛑 ${esc(p.halt_reason)}</div>` : ''}
      ${chartBlock('c-' + p.id, 180)}</details>`;
  });
  $('#view').innerHTML = h;
  document.querySelectorAll('details[data-pid]').forEach(d => d.addEventListener('toggle', () => {
    if (!d.open) return; const p = byId(d.dataset.pid), ser = [{ id: p.id, name: p.name.split(' (')[0], pts: toPts(p.curve) }];
    if (D.cdi_curve?.length) ser.push({ id: 'cdi', name: 'CDI (100%)', pts: toPts(D.cdi_curve) });
    mountChart('c-' + p.id, ser, { h: 180, yAxis: v => num(v, 0), label: 'Evolução de ' + p.name });
  }));
}

function vOperacoes() {
  const tr = D.trades || [], ports = [...new Set(tr.map(t => t.portfolio))];
  let h = `<div class="card">${head('Operações fictícias', 'sim')}<small>Livro-razão de papel com hash encadeado: ${D.ledger.integrity_ok ? '✔ íntegro' : '✖ ' + esc(D.ledger.detail)}. Preços de execução = abertura do dia seguinte ao sinal ± spread/derrapagem, mais taxas.</small>
    <div style="margin-top:8px"><label>Carteira: <select id="fp"><option value="">Todas</option>${ports.map(p => `<option>${esc(p)}</option>`).join('')}</select></label></div></div><div class="card"><div class="tablewrap" id="trt"></div></div>`;
  $('#view').innerHTML = h;
  const draw = () => {
    const f = $('#fp').value, rows = tr.filter(t => !f || t.portfolio === f).slice(0, 120);
    $('#trt').innerHTML = rows.length ? `<table><thead><tr><th>Data</th><th>Carteira</th><th>Ativo</th><th>Lado</th><th>Qtd</th><th>Preço R$</th><th>Taxa R$</th></tr></thead><tbody>${rows.map(t => `<tr><td>${esc(t.date)}</td><td>${esc(t.portfolio)}</td><td>${esc(t.asset)}</td><td>${esc(t.side)}</td><td class="num">${num(+t.qty, 6)}</td><td class="num">${num(+t.fill_price_brl, 2)}</td><td class="num">${num(+t.fee_brl, 2)}</td></tr>`).join('')}</tbody></table>` : '<small>Nenhuma operação registrada ainda. As ordens são executadas na abertura do dia seguinte ao sinal.</small>';
  };
  $('#fp').onchange = draw; draw();
}

function vRisco() {
  const L = (D.portfolios || []).filter(p => !p.passive || ['bh_btc', 'bh_spy'].includes(p.id));
  let h = `<div class="card">${head('Drawdown (queda desde o pico)', 'sim')}${chartBlock('c-dd')}</div>`;
  h += `<div class="card">${head('Risco por carteira', 'sim')}<div class="tablewrap"><table><thead><tr><th>Carteira</th><th>DD atual</th><th>DD máx.</th><th>Vol. a.a.</th><th>VaR 95% 1d</th><th>CVaR 95%</th></tr></thead><tbody>${(D.portfolios || []).map(p => { const s = p.summary; return `<tr><td>${esc(p.id)}</td><td class="num">${pct(s.current_drawdown)}</td><td class="num">${pct(s.max_drawdown)}</td><td class="num">${pct(s.vol_annual)}</td><td class="num">${pct(s.var95_1d)}</td><td class="num">${pct(s.cvar95_1d)}</td></tr>`; }).join('')}</tbody></table></div><small>Volatilidade/VaR só aparecem com 20+ dias de simulação. VaR histórico não prevê perdas piores que as já vistas.</small></div>`;
  const r = D.risk_limits;
  h += `<div class="card"><h2>Limites de risco ativos</h2><div class="kv"><div>Interrupção por drawdown</div><div><b>${pct(r.max_drawdown_halt, 0)}</b></div><div>Alertas de drawdown</div><div>${r.alert_levels.map(x => pct(x, 0)).join(' · ')}</div><div>Máx. posições</div><div>${r.max_positions}</div><div>Caixa mínimo</div><div>${pct(r.min_cash, 0)}</div><div>Alavancagem</div><div>${esc(r.leverage)}</div><div>Venda a descoberto</div><div>${esc(r.short)}</div><div>Martingale</div><div>${esc(r.martingale)}</div><div>Saque automático</div><div>${esc(r.saque_automatico)}</div></div><small>Carteiras passivas (referência) não são interrompidas por drawdown, para servir de comparação.</small></div>`;
  const dq = D.data;
  h += `<div class="card">${head('Qualidade dos dados', 'real')}<div class="tablewrap"><table><thead><tr><th>Ativo</th><th>Barras</th><th>Último</th><th>Fonte</th><th>Avisos</th></tr></thead><tbody>${Object.values(dq.assets || {}).map(a => `<tr><td>${esc(a.asset)}</td><td class="num">${a.rows}</td><td>${esc(a.last || '')}</td><td>${esc((dq.sources || {})[a.asset] || '')}</td><td style="white-space:normal;text-align:left">${esc((a.issues || []).map(i => i.message).join('; ') || '—')}</td></tr>`).join('')}</tbody></table></div>
    ${(dq.skipped || []).length ? '<h3>Fora do ciclo</h3><ul class="clean">' + dq.skipped.map(s => `<li><b>${esc(s.asset)}</b>: ${esc(s.reason)}</li>`).join('') + '</ul>' : ''}
    ${dq.crosscheck && dq.crosscheck.checked ? `<small>Checagem cruzada de preços cripto (Binance × CoinGecko): ${dq.crosscheck.ok ? '✔ ok' : '✖ divergência'} — desvio máx. ${num(Math.max(0, ...Object.values(dq.crosscheck.checked).map(x => x.desvio_pct)), 2)}%.</small>` : ''}</div>`;
  $('#view').innerHTML = h;
  const ser = (D.portfolios || []).filter(p => p.id === D.primary || ['bh_btc', 'bh_spy', 'bh_ew'].includes(p.id)).map(p => ({ id: p.id, name: p.name.replace('Passiva: ', '').split(' (')[0], pts: toPts(p.dd_curve) }));
  mountChart('c-dd', ser, { fmt: v => pct(v), yAxis: v => pct(v, 0), label: 'Drawdown das carteiras' });
}

function vAlertas() {
  const A = D.alerts || [];
  $('#view').innerHTML = `<div class="card"><h2>Alertas</h2><small>Perdas, mudanças importantes de mercado, falhas de dados e eventos do sistema. Notificações push opcionais (ntfy) — ver guia.</small>${A.length ? '<ul class="clean">' + A.map(alertItem).join('') + '</ul>' : '<p class="muted">Sem alertas.</p>'}</div>`;
}

function vEstudo() {
  const B = D.backtest, F = D.feasibility, G = D.golive;
  let h = `<div class="banner info"><b>▲ HISTÓRICO, não é resultado real.</b> Backtest com custos e execução no dia seguinte, sem olhar o futuro. Mesmo assim: o universo foi escolhido hoje (viés de sobrevivência/retrospecto) e testamos várias estratégias (risco de achar “sorte”). Só o paper trading acima é teste para frente.</div>`;
  if (!B) { h += '<p class="muted">O backtest ainda não foi calculado (roda no primeiro ciclo e depois semanalmente).</p>'; }
  else {
    h += `<div class="card">${head('Placar das estratégias', 'hist')}<small>${esc(B.period.start)} → ${esc(B.period.end)} · ${num(B.period.years, 1)} anos · capital de referência ${brl(B.initial_brl)} · CDI no período: ${pct(B.cdi.cagr)} a.a. · ${B.n_trials} tentativas (para o DSR)</small>
      <div style="margin:8px 0"><label>Ordenar por: <select id="so"><option value="sharpe">Sharpe</option><option value="cagr">CAGR</option><option value="max_drawdown">Menor queda</option><option value="dsr">DSR</option></select></label></div>
      <div class="tablewrap" id="lbt"></div>
      <small><b>CAGR</b> = ganho anual composto · <b>Sharpe</b> = retorno acima do CDI por unidade de risco · <b>DSR</b> = probabilidade de o Sharpe ser real depois de corrigir pelo número de estratégias testadas (≥ 0,95 = evidência forte) · <b>R$50→</b> = quanto R$ 50 viraria com lote/ordem mínima reais.</small></div>`;
    h += `<div class="card">${head('Curvas históricas (base 100)', 'hist')}<label class="small"><input type="checkbox" id="logs" checked> escala logarítmica</label>${chartBlock('c-bt', 260)}</div>`;
    const wf = B.walk_forward || {};
    h += `<div class="card">${head('Fora da amostra (walk-forward)', 'hist')}<small>Parâmetros escolhidos só com os 2 anos anteriores e medidos nos 6 meses seguintes, repetido ao longo da história. Compara com os parâmetros padrão e o CDI na mesma janela.</small><div class="tablewrap"><table><thead><tr><th>Família</th><th>OOS CAGR</th><th>OOS Sharpe</th><th>Padrão</th><th>CDI</th></tr></thead><tbody>${Object.values(wf).filter(w => w.oos).map(w => `<tr><td>${esc(w.family)}</td><td class="num ${sgn(w.oos.cagr)}">${pct(w.oos.cagr)}</td><td class="num">${num(w.oos.sharpe)}</td><td class="num">${pct(w.default_params_same_window.cagr)}</td><td class="num">${pct(w.cdi_same_window.cagr)}</td></tr>`).join('')}</tbody></table></div></div>`;
    const rb = B.robustness;
    h += `<div class="card">${head('Teste de robustez', 'hist')}<small>Refeito SEM os 4 ativos que mais subiram (${esc(rb.removed.join(', '))}), que só conhecemos com retrospecto. Se o resultado desaba, a estratégia dependia de sorte na escolha do universo.</small><div class="tablewrap"><table><thead><tr><th>Estratégia</th><th>CAGR completo</th><th>CAGR sem vencedores</th></tr></thead><tbody>${(B.leaderboard || []).filter(r => r.ex_winners).map(r => `<tr><td>${esc(r.id)}</td><td class="num">${pct(r.cagr)}</td><td class="num">${pct(r.ex_winners.cagr)}</td></tr>`).join('')}${rb.ew_all_cagr != null ? `<tr><td>ew_all (referência)</td><td class="num">${pct((B.leaderboard.find(r => r.id === 'ew_all') || {}).cagr)}</td><td class="num">${pct(rb.ew_all_cagr)}</td></tr>` : ''}</tbody></table></div></div>`;
  }
  h += `<div class="card">${head('Viabilidade com ' + brl(F.capital), 'real', 'sim')}<small>Posição-alvo = ${brl(F.capital * 0.98 / F.max_positions)} por ativo (máx. ${F.max_positions} posições); ordem mínima ${brl(F.min_order_brl)}. Preços reais de hoje.</small>
    <div class="tablewrap"><table><thead><tr><th>Ativo</th><th>Preço</th><th>Viável?</th><th>Custo ida+volta</th><th>Vol. 90d</th></tr></thead><tbody>${F.assets.map(a => `<tr><td>${esc(a.asset)}</td><td class="num">${brl(a.price_brl)}</td><td>${a.feasible ? '✔ sim' : '✖ não'}</td><td class="num">${num(a.round_trip_cost_pct, 2)}%</td><td class="num">${pct(a.vol_annual_90d, 0)}</td></tr>`).join('')}</tbody></table></div>
    <h3>Ordem de grandeza em 12 meses (NÃO são previsões)</h3><div class="tablewrap"><table><thead><tr><th>Cenário</th><th>Retorno</th><th>Resultado</th><th>Lucro/prejuízo</th></tr></thead><tbody>${F.scenarios.map(s => `<tr><td>${esc(s.label)}</td><td class="num">${pct(s.annual_return, 0, true)}</td><td class="num">${brl(s.final_brl)}</td><td class="num ${sgn(s.pnl_brl)}">${brl(s.pnl_brl)}</td></tr>`).join('')}</tbody></table></div>
    <small>Com R$ 50, até um ano excelente rende poucos reais; taxas e spread podem consumir uma parte relevante.</small></div>`;
  h += `<div class="card"><h2>Porta para dinheiro real</h2><div class="banner crit"><b>Operação real: DESABILITADA.</b> ${esc(G.note)}</div>${G.criteria.map(c => `<div class="check"><b>${c.ok === true ? '✔ OK' : c.ok === false ? '✖ NÃO' : '⏳ MANUAL'}</b><span>${esc(c.criterio)}<br><small>${esc(c.detalhe)}</small></span></div>`).join('')}</div>`;
  $('#view').innerHTML = h;
  if (B) {
    const lb = B.leaderboard, ord = $('#so'), body = $('#lbt');
    const key = { sharpe: r => -r.sharpe, cagr: r => -r.cagr, max_drawdown: r => -r.max_drawdown, dsr: r => -(r.dsr ?? -1) };
    const tbl = () => { const rows = [...lb].sort((a, b) => key[ord.value](a) - key[ord.value](b)); body.innerHTML = `<table><thead><tr><th>Estratégia</th><th>CAGR</th><th>Sharpe</th><th>Máx. DD</th><th>DSR</th><th>R$50→</th></tr></thead><tbody>${rows.map(r => `<tr><td>${esc(r.id)}${r.passive ? ' <span class="pill">passiva</span>' : ''}${r.experimental ? ' <span class="pill">exp.</span>' : ''}</td><td class="num ${sgn(r.cagr)}">${pct(r.cagr)}</td><td class="num">${num(r.sharpe)}</td><td class="num">${pct(r.max_drawdown, 0)}</td><td class="num">${num(r.dsr)}</td><td class="num">${r.r50 ? num(r.r50.final, 0) : 'n/d'}</td></tr>`).join('')}</tbody></table>`; };
    ord.onchange = tbl; tbl();
    const names = Object.fromEntries(lb.map(r => [r.id, r.id])); names.cdi = 'CDI';
    const ser = Object.entries(B.curves).map(([id, c]) => ({ id, name: names[id] || id, pts: toPts(c) }));
    const def = ['dual_momentum', 'ew_all', 'bh_btc', 'bh_spy', 'lowvol', 'cdi'].filter(i => B.curves[i]);
    const ch = mountChart('c-bt', ser, { visible: def, fmt: v => num(v, 0), yAxis: v => num(v, 0), log: true, h: 260, label: 'Curvas históricas base 100' });
    $('#logs').onchange = e => { ch.host._cfg.log = e.target.checked; ch.host._redraw(); };
  }
}

function vControle() {
  const slug = repoSlug(), ctl = D.control || {}, st = ctl.state;
  const link = a => slug ? `https://github.com/${slug}/issues/new?title=${encodeURIComponent('/investidor ' + a)}&body=${encodeURIComponent('Comando enviado pelo painel do Investidor AI. Basta tocar em "Submit new issue".')}` : '#';
  const btn = (a, label, cls, enabled, msg) => `<a class="btn ${cls}" href="${link(a)}" ${enabled && slug ? '' : 'aria-disabled="true"'} data-confirm="${esc(msg || '')}" target="_blank" rel="noopener">${label}</a>`;
  let h = `<div class="card"><h2>Controle da simulação</h2><div class="row" style="align-items:center">${statePill(st)}<small>desde ${esc(ctl.updated_at || '—')} por ${esc(ctl.updated_by || '—')}</small></div>
    <p class="small">Os botões abrem o GitHub com o comando pronto. Toque em <b>“Submit new issue”</b>; em cerca de 1 minuto o estado muda e o painel é republicado. Só o dono do repositório consegue executar.</p>
    ${st === 'stopped' ? btn('start', '▶ Iniciar nova simulação', 'primary', true, 'Iniciar uma NOVA simulação com R$ 50 fictícios por carteira?') : ''}
    ${st === 'paused' ? btn('resume', '▶ Retomar simulação', 'primary', true) : ''}
    ${st === 'running' ? btn('pause', '⏸ Pausar (mantém posições, sem novas ordens)', '', true) : ''}
    ${st !== 'stopped' ? btn('stop', '⏹ Interromper (vende tudo na próxima abertura e encerra)', 'danger', true, 'Interromper a simulação? Todas as posições fictícias serão liquidadas.') : ''}
    ${slug ? `<a class="btn" href="https://github.com/${slug}/actions/workflows/cycle.yml" target="_blank" rel="noopener">↻ Rodar o ciclo agora (Actions → Run workflow)</a>` : '<div class="banner warn">Não consegui descobrir o repositório. Abra este painel pelo endereço do GitHub Pages.</div>'}
    <small>O ciclo roda sozinho todo dia (~01:30 UTC / 22:30 em Brasília), com o celular desligado.</small></div>`;
  h += `<div class="card"><h2>Histórico de comandos</h2>${(ctl.history || []).length ? '<ul class="clean">' + [...ctl.history].reverse().map(x => `<li><small>${esc(x.at)}</small><br>${esc(x.action)} · ${esc(x.from)} → ${esc(x.to)} · por ${esc(x.by)}</li>`).join('') + '</ul>' : '<small>Sem comandos manuais.</small>'}</div>`;
  h += `<div class="card"><h2>Relatórios e auditoria</h2><ul class="clean"><li><a href="data/relatorio.md">Relatório diário mais recente (Markdown)</a></li>${slug ? `<li><a href="https://github.com/${slug}/blob/state/state/trades.csv">Livro-razão de operações fictícias (CSV)</a></li><li><a href="https://github.com/${slug}/commits/state">Histórico completo de cada ciclo (commits)</a></li><li><a href="https://github.com/${slug}/actions">Execuções e erros (Actions)</a></li>` : ''}</ul>
    <small>Versão ${esc(D.version)} · esquema ${D.schema} · modo ${esc(D.labels.modo)}</small></div>`;
  $('#view').innerHTML = h;
  document.querySelectorAll('a[data-confirm]').forEach(a => a.addEventListener('click', e => { const m = a.dataset.confirm; if (m && !confirm(m)) e.preventDefault(); }));
}

const VIEWS = { resumo: vResumo, carteiras: vCarteiras, operacoes: vOperacoes, risco: vRisco, alertas: vAlertas, estudo: vEstudo, controle: vControle };
function go(t) {
  tab = t; safe(() => localStorage.setItem('inv.tab', t));
  document.querySelectorAll('#tabs button').forEach(b => b.setAttribute('aria-selected', b.dataset.t === t));
  window.scrollTo(0, 0);
  try { VIEWS[t](); } catch (e) { $('#view').innerHTML = `<div class="banner crit">Erro ao desenhar a seção: ${esc(e.message)}</div>`; console.error(e); }
}
function boot() {
  $('#tabs').innerHTML = TABS.map(([k, l]) => `<button role="tab" data-t="${k}" aria-selected="false">${l}</button>`).join('');
  $('#tabs').onclick = e => { const b = e.target.closest('button[data-t]'); if (b) go(b.dataset.t); };
  const saved = safe(() => localStorage.getItem('inv.theme')); if (saved) document.documentElement.dataset.theme = saved;
  $('#theme').onclick = () => { const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); const n = cur === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = n; safe(() => localStorage.setItem('inv.theme', n)); go(tab); };
  fetch('data/dashboard.json?t=' + Date.now(), { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(d => {
    D = d; $('#sub').textContent = `${d.labels.modo} · dados até ${d.as_of}`;
    const want = location.hash.slice(1) || safe(() => localStorage.getItem('inv.tab')) || 'resumo';
    go(VIEWS[want] ? want : 'resumo');
  }).catch(e => { $('#view').innerHTML = `<div class="banner warn"><b>Ainda não há dados.</b> O primeiro ciclo ainda não rodou ou o painel não foi publicado. (${esc(e.message)})</div>`; });
}
boot();
})();
