"""Render the run as one self-contained HTML file (no server, no build step).

Open out/dashboard.html in any browser, or publish it with GitHub Pages. The
data is embedded as JSON; above `dashboard_max_accounts` rows only the highest
priority accounts are embedded so the file stays light at 30k+ accounts.
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd

from .pipeline import RunResult
from .segment import SEGMENT_LABELS
from .state import Store

SEGMENT_ORDER = ["broker_reliant", "broker_hybrid", "am_self_serving", "am_light_touch", "self_serve"]


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records")) if not df.empty else []


def render_dashboard(store: Store, queue: pd.DataFrame, accounts: pd.DataFrame, res: RunResult,
                     as_of: date, rules: dict, dispatched: int) -> str:
    cap = rules.get("dashboard", {}).get("max_accounts", 2000)
    outbox_cap = rules.get("dashboard", {}).get("max_outbox_rows", 300)
    counts = queue["bucket"].value_counts().to_dict() if not queue.empty else {}
    queue = pd.concat([queue[queue["bucket"] != "outbox"], queue[queue["bucket"] == "outbox"].head(outbox_cap)])
    acts = pd.read_sql_query(
        "SELECT a.* FROM actions a JOIN (SELECT account_id, MAX(action_id) m FROM actions GROUP BY account_id) l "
        "ON a.action_id = l.m", store.conn)
    acc = accounts.copy()
    if not acc.empty:
        acc = acc.sort_values(["priority", "gmv_total_6m"], ascending=False)
        truncated = len(acc) > cap
        acc_embed = acc.head(cap)
        acc_embed = acc_embed.merge(
            acts[["account_id", "status", "title", "owner", "channel", "why", "goal", "subject", "message",
                  "call_note", "due_date", "note"]].add_prefix("act_").rename(columns={"act_account_id": "account_id"}),
            on="account_id", how="left")
        seg = (acc.groupby("segment")
               .agg(n=("account_id", "count"), gmv=("gmv_total_6m", "sum"), app=("app_active_days_6m", "median"),
                    broker=("broker_reliance_pct", "median"), manual=("manual_orders", "sum"))
               .reindex(SEGMENT_ORDER).dropna(how="all").reset_index())
        seg["label"] = seg["segment"].map(SEGMENT_LABELS)
        totals = {
            "accounts": int(len(acc)),
            "gmv": float(acc["gmv_total_6m"].sum()),
            "broker_gmv": float(acc.loc[acc["segment"].isin(["broker_reliant", "broker_hybrid"]), "gmv_total_6m"].sum()),
            "broker_n": int(acc["segment"].isin(["broker_reliant", "broker_hybrid"]).sum()),
            "manual_orders": int(acc["manual_orders"].sum()),
            "am_label_self_serving": int(acc["label_mismatch"].eq("AM label, buys for themselves").sum()),
            "am_label": int(acc["ownership"].eq("Account Managed").sum()),
            "truncated": bool(truncated),
        }
    else:
        acc_embed, seg, totals = acc, pd.DataFrame(), {"accounts": 0}

    hist = store.history()
    hist = hist[hist["account_id"].isin(acc_embed["account_id"])] if not acc_embed.empty else hist.head(0)
    dq_all = store.dq()
    dq_counts = (dq_all.groupby(["field", "issue", "action", "severity"]).size().reset_index(name="n")
                 .sort_values("n", ascending=False)) if not dq_all.empty else dq_all
    dq_by_acc = dq_all.groupby("account_id")["issue"].apply(lambda s: sorted(set(s))).to_dict() if not dq_all.empty else {}

    payload = {
        "as_of": as_of.isoformat(),
        "run": {"id": res.run_id, "source": res.source, "rows_in": res.rows_in, "new": len(res.new),
                "updated": len(res.updated), "unchanged": len(res.unchanged), "dq": res.dq_issues,
                "created": res.actions_created, "refreshed": res.actions_refreshed,
                "superseded": res.actions_superseded, "seconds": res.seconds, "dispatched": dispatched,
                "seen_before": res.input_seen_before, "changes": res.changes},
        "runs": _records(store.runs()),
        "totals": totals,
        "segments": _records(seg),
        "accounts": _records(acc_embed),
        "queue": _records(queue.drop(columns=["message", "call_note", "subject"], errors="ignore")),
        "history": _records(hist[["account_id", "run_id", "change_type", "segment", "play", "detail"]]) if not hist.empty else [],
        "dq_counts": _records(dq_counts),
        "dq_by_acc": dq_by_acc,
        "human_capacity": rules["routing"]["daily_human_capacity"],
        "counts": {k: int(v) for k, v in counts.items()},
    }
    data = json.dumps(payload, default=str).replace("</", "<\\/")
    return TEMPLATE.replace("/*__DATA__*/", data)


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AM Autopilot</title>
<style>
:root{color-scheme:light;
 --page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
 --ring:rgba(11,11,11,.10);--wash:rgba(11,11,11,.04);
 --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;
 --good:#0ca30c;--warn:#fab219;--serious:#ec835a;--critical:#d03b3b;--goodtext:#006300}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;
 --page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
 --ring:rgba(255,255,255,.10);--wash:rgba(255,255,255,.05);
 --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--goodtext:#0ca30c}}
:root[data-theme="dark"]{color-scheme:dark;
 --page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
 --ring:rgba(255,255,255,.10);--wash:rgba(255,255,255,.05);
 --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--goodtext:#0ca30c}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:20px 24px 8px;display:flex;flex-wrap:wrap;gap:8px 24px;align-items:baseline;justify-content:space-between}
h1{font-size:20px;margin:0}h2{font-size:15px;margin:0 0 10px}h3{font-size:13px;margin:16px 0 6px;color:var(--ink2);text-transform:uppercase;letter-spacing:.04em}
.sub{color:var(--ink2)}
main{padding:0 24px 40px;max-width:1400px;margin:0 auto}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:16px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:12px 0}
@media (max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}}
section.block{margin-bottom:20px}
.kpi .v{font-size:24px;font-weight:650}.kpi .l{color:var(--ink2);font-size:12px}
.runline{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 0}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;background:var(--wash);border:1px solid var(--ring);font-size:12px;white-space:nowrap}
.pill.strong{font-weight:600}
.segbar{display:flex;gap:2px;height:28px;margin:8px 0 6px}
.segbar div{border-radius:4px;min-width:3px;position:relative}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--ink2)}
.sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
nav{display:flex;gap:4px;margin:18px 0 10px;flex-wrap:wrap;border-bottom:1px solid var(--grid)}
nav button{background:none;border:0;padding:8px 12px;font:inherit;color:var(--ink2);cursor:pointer;border-bottom:2px solid transparent}
nav button.on{color:var(--ink);border-bottom-color:var(--ink);font-weight:600}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
input,select{font:inherit;padding:6px 8px;border-radius:6px;border:1px solid var(--axis);background:var(--surface);color:var(--ink)}
.tablewrap{overflow-x:auto;border:1px solid var(--ring);border-radius:10px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:7px 10px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}
th{color:var(--ink2);font-weight:600;cursor:pointer;white-space:nowrap;position:sticky;top:0;background:var(--surface)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tbody tr{cursor:pointer}tbody tr:hover{background:var(--wash)}
.why{color:var(--ink2);max-width:520px}
.own{font-size:11px;padding:1px 6px;border-radius:4px;border:1px solid var(--ring);white-space:nowrap}
.own.human{background:var(--wash);font-weight:600}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media (max-width:900px){.grid2{grid-template-columns:1fr}}
.empty{color:var(--muted);padding:12px}
#drawer{position:fixed;top:0;right:0;height:100%;width:min(620px,100%);background:var(--surface);border-left:1px solid var(--ring);
 box-shadow:-8px 0 30px rgba(0,0,0,.12);transform:translateX(105%);transition:transform .2s;overflow-y:auto;z-index:10;padding:20px}
#drawer.open{transform:none}
#drawer .close{float:right;background:none;border:1px solid var(--ring);border-radius:6px;padding:4px 10px;cursor:pointer;color:var(--ink);font:inherit}
.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.facts div{background:var(--wash);border-radius:8px;padding:8px}.facts b{display:block;font-size:15px}.facts span{font-size:11px;color:var(--ink2)}
pre{white-space:pre-wrap;font:13px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--wash);border-radius:8px;padding:12px;margin:6px 0}
.copy{font:inherit;font-size:12px;padding:3px 10px;border-radius:6px;border:1px solid var(--axis);background:var(--surface);color:var(--ink);cursor:pointer}
.tl{border-left:2px solid var(--grid);margin-left:4px;padding-left:12px}
.tl div{margin-bottom:8px}
.flag{color:var(--critical);font-weight:600}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--surface);padding:4px 8px;border-radius:6px;font-size:12px;display:none;z-index:20}
.howto li{margin-bottom:6px}
</style>
</head>
<body>
<header>
  <div><h1>AM Autopilot</h1><div class="sub" id="asof"></div></div>
  <div class="runline" id="runline"></div>
</header>
<main>
  <section class="kpis" id="kpis"></section>
  <section class="card">
    <h2>Where the book's spend sits, by behaviour</h2>
    <div class="segbar" id="segbar" role="img" aria-label="Share of 6-month GMV by behavioural segment"></div>
    <div class="legend" id="legend"></div>
    <div class="tablewrap" style="margin-top:12px"><table id="segtable"></table></div>
  </section>
  <nav id="tabs"></nav>
  <section id="view"></section>
</main>
<aside id="drawer" aria-label="Account detail"></aside>
<div id="tip"></div>
<script id="data" type="application/json">/*__DATA__*/</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
// Categorical slots assigned in fixed order along the bar (validated adjacent pairs)
const SEGCOL = {broker_reliant:'var(--s1)', broker_hybrid:'var(--s2)', am_self_serving:'var(--s3)', am_light_touch:'var(--s4)', self_serve:'var(--s5)'};
const MONTHS = ['gmv_sep','gmv_oct','gmv_nov','gmv_dec','gmv_jan','gmv_feb'], MLAB = ['Sep','Oct','Nov','Dec','Jan','Feb'];
const gbp = v => '£' + Math.round(v || 0).toLocaleString('en-GB');
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const byId = Object.fromEntries(D.accounts.map(a => [a.account_id, a]));
const OWN = {human:'AM calls', review:'AM approves', auto:'Agent sends', none:'No action'};
const tip = document.getElementById('tip');
function showTip(e, html){ tip.innerHTML = html; tip.style.display = 'block'; tip.style.left = (e.clientX + 12) + 'px'; tip.style.top = (e.clientY + 12) + 'px'; }
function hideTip(){ tip.style.display = 'none'; }

// ---------- header ----------
const R = D.run, T = D.totals;
document.getElementById('asof').textContent = `Run ${R.id} · ${R.source} · as of ${D.as_of}`;
document.getElementById('runline').innerHTML = R.seen_before && !R.new && !R.updated
  ? `<span class="pill strong">File already processed: nothing to do</span>`
  : [`<span class="pill strong">${R.new} new</span>`, `<span class="pill strong">${R.updated} updated</span>`,
     `<span class="pill">${R.unchanged} skipped (no change)</span>`, `<span class="pill">${R.created} actions created</span>`,
     `<span class="pill">${R.refreshed} refreshed</span>`, `<span class="pill">${R.superseded} superseded</span>`,
     `<span class="pill">${R.dq} data fixes</span>`, `<span class="pill">${R.seconds}s</span>`].join('');

const q = D.queue, today = q.filter(r => r.bucket === 'today'), appr = q.filter(r => r.bucket === 'approval'),
      outbox = q.filter(r => r.bucket === 'outbox'), next = q.filter(r => r.bucket === 'next');
const kpis = [
  [T.accounts?.toLocaleString('en-GB'), 'accounts in the book'],
  [gbp(T.gmv), '6-month GMV'],
  [Math.round(100 * T.broker_gmv / T.gmv) + '%', `of GMV in ${T.broker_n} broker-reliant accounts`],
  [T.manual_orders?.toLocaleString('en-GB'), 'orders AMs placed by hand (6m)'],
  [`${T.am_label_self_serving} of ${T.am_label}`, 'AM accounts that already buy for themselves'],
  [D.counts.today || 0, `AM calls today (capacity ${D.human_capacity})`],
  [D.counts.approval || 0, 'drafts awaiting AM approval'],
  [R.dispatched || D.counts.outbox || 0, R.dispatched ? 'automated messages sent' : 'automated messages ready'],
];
document.getElementById('kpis').innerHTML = kpis.map(([v, l]) => `<div class="card kpi"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join('');

// ---------- segment bar + table ----------
const segs = D.segments;
document.getElementById('segbar').innerHTML = segs.map(s => {
  const pct = 100 * s.gmv / T.gmv;
  return `<div style="flex:${Math.max(pct, 0.6)};background:${SEGCOL[s.segment]}" data-tip="${esc(s.label)}: ${gbp(s.gmv)} (${pct.toFixed(0)}%), ${s.n} accounts"></div>`;
}).join('');
document.getElementById('legend').innerHTML = segs.map(s => `<span><span class="sw" style="background:${SEGCOL[s.segment]}"></span>${esc(s.label)} ${(100 * s.gmv / T.gmv).toFixed(0)}%</span>`).join('');
document.querySelectorAll('#segbar div').forEach(el => { el.onmousemove = e => showTip(e, el.dataset.tip); el.onmouseleave = hideTip; });
document.getElementById('segtable').innerHTML = `<thead><tr><th>Segment (from behaviour)</th><th class="num">Accounts</th><th class="num">6m GMV</th><th class="num">Share</th><th class="num">Median broker %</th><th class="num">Median app days</th><th class="num">AM-placed orders</th></tr></thead><tbody>` +
  segs.map(s => `<tr data-seg="${s.segment}"><td><span class="sw" style="background:${SEGCOL[s.segment]}"></span>${esc(s.label)}</td><td class="num">${s.n}</td><td class="num">${gbp(s.gmv)}</td><td class="num">${(100 * s.gmv / T.gmv).toFixed(1)}%</td><td class="num">${Math.round(s.broker)}%</td><td class="num">${Math.round(s.app)}</td><td class="num">${(s.manual || 0).toLocaleString('en-GB')}</td></tr>`).join('') + '</tbody>';
document.querySelectorAll('#segtable tbody tr').forEach(tr => tr.onclick = () => { state.seg = tr.dataset.seg; setTab('accounts'); });

// ---------- tables ----------
const state = {tab: 'today', seg: '', owner: '', play: '', search: '', sort: null};
function table(rows, cols, opts = {}) {
  if (!rows.length) return `<div class="tablewrap"><div class="empty">${opts.empty || 'Nothing here.'}</div></div>`;
  const head = cols.map((c, i) => `<th class="${c.num ? 'num' : ''}" data-i="${i}">${c.h}</th>`).join('');
  const body = rows.map(r => `<tr data-id="${esc(r.account_id)}">` + cols.map(c => `<td class="${c.num ? 'num' : ''} ${c.cls || ''}">${c.f(r)}</td>`).join('') + '</tr>').join('');
  return `<div class="tablewrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}
const own = r => `<span class="own ${r.owner}">${OWN[r.owner] || r.owner}</span>`;
const segcell = r => { const a = byId[r.account_id] || r; return `<span class="sw" style="background:${SEGCOL[a.segment]}"></span>${esc(a.segment_label)}`; };
const QCOLS = [
  {h: 'Priority', num: true, f: r => r.priority, k: 'priority'},
  {h: 'Account', f: r => `<b>${esc(r.account_id)}</b>${r.overdue ? ' <span class="flag">overdue</span>' : ''}`, k: 'account_id'},
  {h: 'Segment', f: segcell, k: 'segment_label'},
  {h: 'Next action', f: r => esc(r.title), k: 'title'},
  {h: 'Who', f: own, k: 'owner'},
  {h: '6m GMV', num: true, f: r => gbp(r.gmv_total_6m), k: 'gmv_total_6m'},
  {h: 'Why now', cls: 'why', f: r => esc(r.why), k: 'why'},
];
const ACOLS = [
  {h: 'Account', f: r => `<b>${esc(r.account_id)}</b>`, k: 'account_id'},
  {h: 'Label', f: r => esc(r.ownership), k: 'ownership'},
  {h: 'Behaviour', f: segcell, k: 'segment_label'},
  {h: '6m GMV', num: true, f: r => gbp(r.gmv_total_6m), k: 'gmv_total_6m'},
  {h: 'Broker %', num: true, f: r => r.broker_reliance_pct + '%', k: 'broker_reliance_pct'},
  {h: 'App days', num: true, f: r => r.app_active_days_6m, k: 'app_active_days_6m'},
  {h: 'Recency', f: r => esc(r.recency_state), k: 'recency_state'},
  {h: 'Health', num: true, f: r => r.health_score, k: 'health_score'},
  {h: 'Next action', f: r => esc(r.action_title), k: 'action_title'},
  {h: 'Who', f: own, k: 'owner'},
  {h: 'Priority', num: true, f: r => r.priority, k: 'priority'},
];
function sortRows(rows, cols) {
  if (!state.sort) return rows;
  const {i, dir} = state.sort, k = cols[i].k;
  return [...rows].sort((a, b) => { const x = a[k] ?? byId[a.account_id]?.[k], y = b[k] ?? byId[b.account_id]?.[k]; return (x > y ? 1 : x < y ? -1 : 0) * dir; });
}
function wire(cols) {
  document.querySelectorAll('#view tbody tr').forEach(tr => tr.onclick = () => openAcc(tr.dataset.id));
  document.querySelectorAll('#view th').forEach(th => th.onclick = () => {
    const i = +th.dataset.i; state.sort = state.sort && state.sort.i === i ? {i, dir: -state.sort.dir} : {i, dir: -1}; render();
  });
}
function filters(withOwner = true) {
  const segOpts = ['', ...D.segments.map(s => s.segment)].map(s => `<option value="${s}" ${state.seg === s ? 'selected' : ''}>${s ? esc(D.segments.find(x => x.segment === s).label) : 'All segments'}</option>`).join('');
  const ownOpts = ['', 'human', 'review', 'auto', 'none'].map(o => `<option value="${o}" ${state.owner === o ? 'selected' : ''}>${o ? OWN[o] : 'Anyone'}</option>`).join('');
  return `<div class="controls"><input id="f-search" placeholder="Search account, action, reason" value="${esc(state.search)}"><select id="f-seg">${segOpts}</select>${withOwner ? `<select id="f-own">${ownOpts}</select>` : ''}</div>`;
}
function wireFilters() {
  const s = document.getElementById('f-search'); if (s) s.oninput = e => { state.search = e.target.value; render(true); };
  const g = document.getElementById('f-seg'); if (g) g.onchange = e => { state.seg = e.target.value; render(); };
  const o = document.getElementById('f-own'); if (o) o.onchange = e => { state.owner = e.target.value; render(); };
}
function match(r) {
  const a = byId[r.account_id] || r;
  if (state.seg && a.segment !== state.seg) return false;
  if (state.owner && r.owner !== state.owner) return false;
  if (state.search) { const t = state.search.toLowerCase(); return [r.account_id, r.title, r.action_title, r.why, a.segment_label].some(x => String(x || '').toLowerCase().includes(t)); }
  return true;
}

const TABS = {
  today: ['Today', () => `<section class="block"><h2>AM calls today (${today.length})</h2>${table(sortRows(today, QCOLS), QCOLS, {empty: 'No calls due today.'})}
      ${next.length ? `<h3>Next up, over today's capacity (${next.length})</h3>${table(next, QCOLS)}` : ''}</section>
      <section class="block"><h2>Drafts for AM approval (${appr.length})</h2>${table(sortRows(appr, QCOLS).slice(0, 15), QCOLS, {empty: 'Nothing to approve.'})}
      ${appr.length > 15 ? `<div class="sub" style="margin-top:6px">Top 15 of ${appr.length} shown; filter all of them in the "All open actions" tab.</div>` : ''}</section>
      <h2 style="margin-top:18px">Automated by the agent (${D.counts.outbox || 0}${R.dispatched ? ', sent' : ''})</h2>${table(sortRows(outbox, QCOLS).slice(0, 25), QCOLS, {empty: 'Nothing automated today.'})}
      ${(D.counts.outbox || 0) > 25 ? `<div class="sub" style="margin-top:6px">Top 25 shown; the full list is in out/outbox.jsonl.</div>` : ''}`],
  actions: ['All open actions', () => filters() + table(sortRows(q.filter(match), QCOLS), QCOLS)],
  accounts: ['Accounts', () => filters() + (T.truncated ? `<div class="sub">Showing the top ${D.accounts.length.toLocaleString()} accounts by priority.</div>` : '') + table(sortRows(D.accounts.filter(match), ACOLS), ACOLS)],
  changes: ['What changed', () => {
    const ch = Object.entries(R.changes || {});
    const runs = D.runs.map(r => `<tr><td>${r.run_id}</td><td>${esc(r.source)}</td><td>${esc(r.as_of)}</td><td class="num">${r.rows_in ?? ''}</td><td class="num">${r.new ?? ''}</td><td class="num">${r.updated ?? ''}</td><td class="num">${r.unchanged ?? ''}</td><td class="num">${r.actions_created ?? ''}</td><td class="num">${r.actions_superseded ?? ''}</td></tr>`).join('');
    return `<h2>This run: ${R.new} new, ${R.updated} updated, ${R.unchanged} skipped</h2>` +
      (ch.length ? table(ch.map(([id, d]) => ({account_id: id, d})), [{h: 'Account', f: r => `<b>${esc(r.account_id)}</b>`}, {h: 'Segment now', f: segcell}, {h: 'What changed', cls: 'why', f: r => esc(r.d)}]) : '<div class="card empty">No existing accounts changed in this run.</div>') +
      `<h3>Run history</h3><div class="tablewrap"><table><thead><tr><th>Run</th><th>Source</th><th>As of</th><th class="num">Rows</th><th class="num">New</th><th class="num">Updated</th><th class="num">Skipped</th><th class="num">Actions created</th><th class="num">Superseded</th></tr></thead><tbody>${runs}</tbody></table></div>`;
  }],
  dq: ['Data quality', () => `<h2>What the cleaner fixed (all runs)</h2>` + table(D.dq_counts, [
      {h: 'Field', f: r => esc(r.field)}, {h: 'Issue', f: r => esc(r.issue)}, {h: 'What the tool did', cls: 'why', f: r => esc(r.action)},
      {h: 'Severity', f: r => esc(r.severity)}, {h: 'Rows', num: true, f: r => r.n}], {empty: 'No issues found.'})],
  how: ['How it works', () => `<div class="card howto"><h2>Every morning</h2><ol>
      <li><b>Data in.</b> The portfolio export lands in <code>data/inbox/</code> (or is passed to <code>autopilot run</code>).</li>
      <li><b>Automatic.</b> Clean and log every fix, fingerprint each account, skip anything unchanged, re-score what is new or changed, pick one next action per account, draft it, route it.</li>
      <li><b>Agent steps in.</b> Sends the automated nudges (outbox) and records them as sent, so cooldowns apply and nothing goes twice.</li>
      <li><b>AM steps in.</b> Approves drafts in the review queue and makes the calls in today's list (capped at ${D.human_capacity} a day), then logs outcomes with <code>autopilot mark</code>.</li>
      <li><b>Next run</b> sees the outcomes and any new data, refreshes or supersedes actions, and never duplicates them.</li></ol></div>`],
};
function setTab(t) { state.tab = t; state.sort = null; render(); }
function render(keepFocus) {
  document.getElementById('tabs').innerHTML = Object.entries(TABS).map(([k, [l]]) => `<button class="${state.tab === k ? 'on' : ''}" data-t="${k}">${l}</button>`).join('');
  document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => setTab(b.dataset.t));
  const pos = keepFocus ? document.getElementById('f-search')?.selectionStart : null;
  document.getElementById('view').innerHTML = TABS[state.tab][1]();
  wire(state.tab === 'accounts' ? ACOLS : QCOLS); wireFilters();
  if (keepFocus) { const s = document.getElementById('f-search'); s.focus(); s.setSelectionRange(pos, pos); }
}

// ---------- account drawer ----------
function spendChart(a) {
  const vals = MONTHS.map(m => a[m] || 0), max = Math.max(...vals, 1), W = 560, H = 150, pad = 26, bw = (W - 2 * pad) / 6;
  const firstOnBook = 6 - a.months_on_book;
  let s = `<svg viewBox="0 0 ${W} ${H + 24}" width="100%" role="img" aria-label="Monthly GMV">`;
  s += `<line x1="${pad}" x2="${W - pad}" y1="${H}" y2="${H}" stroke="var(--axis)"/>`;
  vals.forEach((v, i) => {
    const h = Math.max((v / max) * (H - 20), v > 0 ? 2 : 0), x = pad + i * bw + 6, w = bw - 12;
    const pre = i < firstOnBook;
    if (pre) s += `<rect x="${x}" y="${H - 18}" width="${w}" height="18" rx="4" fill="none" stroke="var(--grid)" stroke-dasharray="3 3"/>`;
    else s += `<rect class="bar" x="${x}" y="${H - h}" width="${w}" height="${h}" rx="4" fill="var(--s1)" data-tip="${MLAB[i]}: ${gbp(v)}"/>`;
    s += `<rect class="bar" x="${x - 4}" y="0" width="${w + 8}" height="${H}" fill="transparent" data-tip="${MLAB[i]}: ${pre ? 'not yet a customer' : gbp(v)}"/>`;
    s += `<text x="${x + w / 2}" y="${H + 16}" text-anchor="middle" font-size="11" fill="var(--muted)">${MLAB[i]}</text>`;
  });
  return s + '</svg>';
}
function openAcc(id) {
  const a = byId[id]; if (!a) return;
  const dr = document.getElementById('drawer');
  const hist = D.history.filter(h => h.account_id === id);
  const dq = (D.dq_by_acc[id] || []);
  const isHuman = a.act_owner === 'human';
  dr.innerHTML = `<button class="close" onclick="document.getElementById('drawer').classList.remove('open')">Close</button>
    <h2 style="font-size:18px">${esc(id)}</h2>
    <div class="sub">${esc(a.buyer_persona)} · ${esc(a.country)} · ${esc(a.ownership)} label · ${a.tenure_months} months tenure · status ${esc(a.account_status)}</div>
    <p><span class="sw" style="background:${SEGCOL[a.segment]}"></span><b>${esc(a.segment_label)}</b> · ${esc(a.segment_reason)}</p>
    ${a.label_mismatch ? `<p class="sub">Label vs behaviour: <b>${esc(a.label_mismatch)}</b>. Coverage: ${esc(a.coverage)}.</p>` : `<p class="sub">Coverage: ${esc(a.coverage)}.</p>`}
    <div class="facts">
      <div><b>${gbp(a.gmv_total_6m)}</b><span>6m GMV · ${gbp(a.gmv_runrate)}/month on book</span></div>
      <div><b>${a.orders_6m}</b><span>orders · ${a.manual_orders} placed by AM</span></div>
      <div><b>${a.broker_reliance_pct}%</b><span>broker reliance</span></div>
      <div><b>${a.app_active_days_6m} / ${a.pdp_views_6m.toLocaleString('en-GB')}</b><span>app days / product views</span></div>
      <div><b>${a.make_an_offer_6m} / ${a.chat_threads} / ${a.video_call_requests}</b><span>offers / chats / video calls</span></div>
      <div><b>${a.bundle_gmv_share_pct}%</b><span>of spend on bundles · ${a.handpick_orders} handpick orders</span></div>
      <div><b>${esc(a.recency_state)}</b><span>${a.months_since_last_spend ?? '?'} months since last spend</span></div>
      <div><b>${esc(a.momentum_label)}</b><span>momentum ${a.momentum ?? 'n/a'}</span></div>
      <div><b>${a.health_score}</b><span>health score / 100</span></div>
    </div>
    <h3>Monthly GMV</h3>${spendChart(a)}
    <h3>Next best action</h3>
    <p><b>${esc(a.act_title || a.action_title)}</b> · <span class="own ${a.act_owner || a.owner}">${OWN[a.act_owner || a.owner] || ''}</span> · ${esc(a.act_channel || '')} · priority ${a.priority} · status <b>${esc(a.act_status || 'none')}</b></p>
    <p class="why">${esc(a.act_why || a.why)}</p>
    ${a.act_goal ? `<p class="sub">Goal: ${esc(a.act_goal)}</p>` : ''}
    ${a.act_call_note ? `<h3>Call note</h3><pre>${esc(a.act_call_note)}</pre>` : ''}
    ${a.act_message ? `<h3>${isHuman ? 'Follow-up message (after the call)' : 'Draft message'}</h3><div class="sub">Subject: ${esc(a.act_subject)}</div><pre id="msg">${esc(a.act_message)}</pre><button class="copy" onclick="navigator.clipboard.writeText(document.getElementById('msg').innerText);this.textContent='Copied'">Copy message</button>` : ''}
    ${dq.length ? `<h3>Data notes</h3><ul>${dq.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    <h3>History</h3><div class="tl">${hist.map(h => `<div><b>Run ${h.run_id}</b> · ${esc(h.change_type)} · ${esc(h.segment)} → ${esc(h.play)}<br><span class="sub">${esc(h.detail)}</span></div>`).join('') || '<div class="sub">No history.</div>'}</div>`;
  dr.classList.add('open');
  dr.querySelectorAll('.bar').forEach(el => { el.onmousemove = e => showTip(e, el.dataset.tip); el.onmouseleave = hideTip; });
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') document.getElementById('drawer').classList.remove('open'); });
render();
</script>
</body>
</html>
"""
