import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Evidence = {path: string; pointer?: string; line_start?: number; line_end?: number};
type Run = {
  run_id: string; mode: string; scenario_id: string | null; repository_path?:string; analysis_summary?:string; parent_run_id?:string; lifecycle: string; outcome: string | null;
  result: string; result_reason: string; termination_reason?: string | null;
  created_at: string; started_at?: string | null; finished_at?: string | null; development_verification: string;
  patch?: {edited_files?: string[]; empty?: boolean};
  changes: {kind:string; id:string; description:string; disposition:string; evidence:Evidence[]; affected_locations:Evidence[]}[];
  manual_actions: {change_id:string; required_work:string; unresolved_decision:string; blocking_effect:string}[];
  development_checks: {id:string; status:string; revision_hash:string; log_artifact_id:string}[];
  artifacts:string[]; warnings:string[]; evaluation:{verdict:string};
  budget:{used_requests:number; used_tools:number; used_patch_attempts:number; used_checks:number; active_seconds?:number; limits?:Record<string,number>};
};
type Scenario = {id:string; code:string; name:string; summary:string; before:string; after:string; expect:string};
type Progress = {seq:number; kind:string; message:string; at:number; stage?:string|null; status?:string|null; duration_ms?:number|null};
const label = (value:string) => value.replaceAll('_', ' ').replaceAll('-', ' ');
// Mirrors backend/src/api_maintainer/status.py so the UI and the CLI never disagree.
const RESULT_LABEL:Record<string,string> = {pass:'Passed', partial:'Partly done', review:'Needs your review', fail:'Failed', running:'Running'};
const MARK:Record<string,string> = {ok:'\u2713', error:'\u2717', warn:'!', info:'\u00b7'};
const LEGACY_STATUS:Record<string,string> = {tool_error:'error', provider_error:'error', provider_retry:'warn', response_truncated:'warn', submission_pending:'warn', awaiting_review:'warn'};
const eventStatus = (e:Progress) => (e.status && e.status !== 'info') ? e.status : (LEGACY_STATUS[e.kind] || 'info');
const clock = (at:number) => new Date(at*1000).toLocaleTimeString();
const took = (ms?:number|null) => ms ? ` \u00b7 ${(ms/1000).toFixed(1)}s` : '';
const mark = (status:string) => <span className={`status-mark status-mark-${status}`} aria-hidden="true">{MARK[status] || MARK.info}</span>;
const elapsed = (r:Run) => {
  if (r.finished_at && r.started_at) {
    const ms = Date.parse(r.finished_at) - Date.parse(r.started_at);
    if (ms >= 0) return ms/1000;
  }
  return r.budget?.active_seconds || null;
};
const duration = (seconds:number|null) => seconds === null ? '\u2014'
  : seconds < 60 ? `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
  : `${Math.floor(seconds/60)}m${String(Math.floor(seconds%60)).padStart(2,'0')}s`;
// One row per participant in the run: what it produced and whether that worked.
function stageRows(r:Run):[string,string,string][] {
  const rows:[string,string,string][] = [];
  const repairable = r.changes.filter(c => c.disposition === 'repair').length;
  if (r.changes.length || r.lifecycle !== 'created')
    rows.push(['Analysis agent', r.changes.length ? 'ok' : 'warn',
      r.changes.length ? `${r.changes.length} change(s): ${repairable} repairable, ${r.manual_actions.length} needing a person` : 'No changes recorded']);
  const files = r.patch?.edited_files?.length ?? 0;
  if (r.patch && Object.keys(r.patch).length)
    rows.push(['Repair agent', files ? 'ok' : 'warn',
      files ? `${files} file(s) patched in ${r.budget.used_patch_attempts} attempt(s)` : `No file changed (${r.budget.used_patch_attempts} patch attempt(s))`]);
  if (['finished','interrupted'].includes(r.lifecycle) || r.development_checks.length)
    rows.push(['Development checks', {passed:'ok', failed:'error'}[r.development_verification] || 'warn',
      `${label(r.development_verification)} (${r.development_checks.length} run)`]);
  rows.push(['Independent evaluation', {passed:'ok', failed:'error', not_run:'info'}[r.evaluation.verdict] || 'warn',
    label(r.evaluation.verdict)]);
  return rows;
}
const done = (r:Run) => ['finished','interrupted','awaiting_review'].includes(r.lifecycle);
const runUrl = (id:string) => `/api/runs/${encodeURIComponent(id)}`;
async function api<T>(url:string, init?:RequestInit):Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const error = await response.json().catch(() => ({detail:'The local service could not complete the request.'}));
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Please check the supplied inputs.');
  }
  return response.json();
}
function App() {
  const [view, setView] = useState(location.hash.slice(1) || 'new');
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [history, setHistory] = useState<Run[]>([]);
  const [run, setRun] = useState<Run|null>(null);
  const [health, setHealth] = useState<Record<string,boolean>|null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<Progress[]>([]);
  const [diff, setDiff] = useState('');
  const [demo, setDemo] = useState(false);
  const [scenarioId, setScenarioId] = useState('');
  const [reviewSummary, setReviewSummary] = useState('');
  const [reviewNotes, setReviewNotes] = useState('');
  useEffect(() => {
    const change = () => {setView(location.hash.slice(1) || 'new'); setError('');};
    window.addEventListener('hashchange', change);
    Promise.all([api<Scenario[]>('/api/scenarios'), api<Record<string,boolean>>('/api/health')])
      .then(([s,h]) => {setScenarios(s); setScenarioId(c => c || s[0]?.id || ''); setHealth(h);}).catch(e => setError(e.message));
    return () => window.removeEventListener('hashchange', change);
  }, []);
  // Health is a live prerequisite, not a one-time fact: a transient Docker blip must not
  // leave a stale "setup needed" banner for the rest of the session. Recheck on return to
  // the form and after every create attempt.
  useEffect(() => {
    if (view !== 'new') return;
    let stopped = false;
    api<Record<string,boolean>>('/api/health').then(h => {if (!stopped) setHealth(h);}).catch(() => {});
    return () => {stopped = true;};
  }, [view, busy]);
  useEffect(() => {
    let stopped = false;
    let timer:ReturnType<typeof setTimeout>;
    let cursor = 0;
    setRun(null); setEvents([]); setDiff('');
    async function load() {
      try {
        if (view === 'history') {
          const list = await api<Run[]>('/api/runs');
          if (!stopped) setHistory(list);
          return;
        }
        if (!view.startsWith('run/')) return;
        const id = view.slice(4);
        const [r, ev] = await Promise.all([api<Run>(runUrl(id)), api<Progress[]>(`${runUrl(id)}/events?after_seq=${cursor}`)]);
        if (stopped) return;
        setRun(r); if (r.lifecycle==='awaiting_review') {setReviewSummary(r.analysis_summary || ''); setReviewNotes('');} setEvents(prev => [...prev, ...ev].slice(-100));
        if (ev.length) cursor = ev[ev.length-1].seq;
        if (r.artifacts.includes('patch.diff')) {
          const response = await fetch(`${runUrl(id)}/artifacts/patch.diff`);
          if (!response.ok) throw new Error('Patch download is unavailable.');
          const text = await response.text();
          if (!stopped) setDiff(text);
        }
        if (!done(r) && !stopped) timer = setTimeout(load, 1000);
      } catch (e) {
        if (!stopped) {setError((e as Error).message); timer=setTimeout(load, 3000);}
      }
    }
    load();
    return () => {stopped=true; clearTimeout(timer);};
  }, [view, busy]);
  async function create(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = new FormData(event.currentTarget);
    for (const field of ['old_spec','new_spec']) {
      const file = form.get(field);
      if (file instanceof File && !file.size) form.delete(field);
    }
    if (!String(form.get('notes') || '').trim()) form.delete('notes');
    const pending = sessionStorage.getItem('creation-key') || crypto.randomUUID();
    sessionStorage.setItem('creation-key',pending);
    setBusy(true); setError('');
    try {
      const result = await api<Run>('/api/runs', {method:'POST', body:form, headers:{'Idempotency-Key':pending}});
      sessionStorage.removeItem('creation-key');
      location.hash = `run/${result.run_id}`;
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function repair() {
    if (!run || busy) return;
    setBusy(true); setError('');
    try {setRun(await api<Run>(`${runUrl(run.run_id)}/repair`, {method:'POST'}));}
    catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function revise() {
    if (!run || busy) return;
    setBusy(true); setError('');
    try {
      const result = await api<Run>(`${runUrl(run.run_id)}/revise`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({summary:reviewSummary,notes:reviewNotes})});
      location.hash = `run/${result.run_id}`;
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  const selectedScenario = scenarios.find(s => s.id === scenarioId);
  const reviewChanged = !!run && (reviewSummary !== (run.analysis_summary || '') || !!reviewNotes.trim());
  const evidence = (e:Evidence, i:number) => <li key={i}><code>{e.path}{e.pointer ? ` ${e.pointer}` : `:${e.line_start}${e.line_end ? '–'+e.line_end : ''}`}</code></li>;
  return <div className="shell">
    <aside><a href="#new" className="brand"><span className="mark">↗</span> API Maintainer</a><p className="eyebrow">LOCAL WORKSPACE</p>
      <nav aria-label="Main navigation"><a className={view==='new'?'selected':''} href="#new">＋ New migration</a><a className={view==='history'?'selected':''} href="#history">◷ Run history</a></nav>
      <div className="sidebar-note"><span className="dot"/> Original source preserved<p>Review every change before applying it to your application.</p></div>
    </aside>
    <main><header><span>API MIGRATIONS</span><span className="local">● Local execution</span></header>
      {error && <div role="alert" className="notice error">{error}<button aria-label="Dismiss error" onClick={()=>setError('')}>×</button></div>}
      {view==='new' && <><div className="intro"><p className="eyebrow">A SAFER WAY TO UPDATE</p><h1>Move your API forward.</h1><p>Understand what changed. Generate a focused repair.<br/>Keep the evidence and the final decision in your hands.</p></div>
        {health && !health.ready && <div className="notice">Setup needed: {Object.entries(health).filter(([k,v])=>k!=='ready'&&!v).map(([k])=>label(k)).join(', ')}. Run <code>api-maintainer doctor</code> after configuring the local prerequisites.</div>}
        <form className="migration-form" onSubmit={create} onChange={()=>sessionStorage.removeItem('creation-key')}>
          <section className="card"><div className="section-title"><span className="step">01</span><div><h2>Provide your client and API documents</h2><p>We identify the migration changes from your documents and client code.</p></div></div>
            <div className="input-mode" role="group" aria-label="Migration source">
              <button type="button" aria-pressed={!demo} onClick={()=>{setDemo(false);sessionStorage.removeItem('creation-key');}}>Your repository<span>Use your client code and API documents</span></button>
              <button type="button" aria-pressed={demo} onClick={()=>{setDemo(true);sessionStorage.removeItem('creation-key');}}>Try a demo<span>Explore with a sample bookstore</span></button>
            </div>
            <input type="hidden" name="sample_id" value={demo?'bookstore':'repository'}/>
            <input type="hidden" name="mode" value="review"/>
            {demo ? <>
              <p className="hint demo-about">The demo migrates a small sample bookstore client for you: <code>client.py</code> calls <code>GET /books/&#123;book_id&#125;</code> and <code>app.py</code> prints a price quote from the title and price it returns. Pick the API change below and we supply the matching before and after API documents. Nothing on your machine is read or changed.</p>
              <label>Demo scenario<select name="scenario_id" value={scenarioId} onChange={e=>setScenarioId(e.target.value)}>{scenarios.map(s=><option key={s.id} value={s.id}>{s.code} · {s.name}</option>)}</select></label>
              {selectedScenario && <div className="scenario-brief">
                <p className="document-tag">WHAT CHANGES IN THIS DEMO</p>
                <p className="scenario-summary">{selectedScenario.summary}</p>
                <div className="columns scenario-shift">
                  <div><span className="document-tag">BEFORE</span><code>{selectedScenario.before}</code></div>
                  <div><span className="document-tag">AFTER</span><code>{selectedScenario.after}</code></div>
                </div>
                <p className="scenario-expect"><strong>What a correct migration does</strong> {selectedScenario.expect}</p>
              </div>}
            </> : <>
              <label>Client repository path<input type="text" name="repository_path" required placeholder="/Users/you/projects/my-client"/></label>
              <p className="hint">An absolute directory on the machine running this app. A copy of supported source and text files is analyzed; your original files stay unchanged. Git metadata, dependencies, hidden files and common credential files are excluded. Choose a directory without embedded secrets.</p>
              <div className="columns upload"><label className="document-field"><span className="document-tag">BEFORE</span>Previous API document<span className="document-description">The API contract your client uses today</span><input type="file" name="old_spec" required accept=".json,.yaml,.yml"/></label><label className="document-field"><span className="document-tag">AFTER</span>New API document<span className="document-description">The API contract you’re migrating to</span><input type="file" name="new_spec" required accept=".json,.yaml,.yml"/></label></div>
              <p className="hint">OpenAPI 3.0.x in JSON or YAML · 1 MiB per document. Change types are detected automatically.</p>
            </>}
            <label>Migration notes <span className="optional">optional</span><textarea name="notes" rows={3} placeholder="Add context about renamed fields, units, or intended behavior…"/></label>
            {!demo&&<details className="test-settings" open><summary>Test settings <span className="optional">optional</span></summary><label>Test command<input name="test_command" placeholder="python -m unittest discover -s tests"/></label><label>Prebuilt Docker image<input name="test_image" defaultValue="api-maintainer-python:local"/></label><p className="hint">Use an image containing your test dependencies. Tests run in /source with no network and a read-only repository. Without a command, repairs remain unverified. The default image supports Python’s standard library.</p></details>}
          </section>
          <section className="card"><div className="section-title"><span className="step">02</span><div><h2>Analyze, then review</h2><p>Review detected change types, affected files and editable migration notes before approving a repair. Edited summaries and notes are reanalyzed for a fresh review.</p></div></div>
            <div className="form-footer"><span>Source and API documents are sent to the configured model.</span><button className="primary" disabled={busy}>{busy?'Starting…':'Identify changes →'}</button></div>
          </section>
        </form></>}
      {view==='history' && <><div className="intro"><p className="eyebrow">SAVED WORK</p><h1>Run history</h1><p>Your analyses, patches, and verification evidence.</p></div><section className="card">{history.length ? <div className="table-wrap"><table><thead><tr><th>Result</th><th>Target</th><th>Why</th><th>Time</th><th>Started</th></tr></thead><tbody>{history.map(r=><tr key={r.run_id}><td><span className={`badge result-${r.result}`}>{mark({pass:'ok',partial:'warn',review:'warn',fail:'error',running:'info'}[r.result] || 'info')} {RESULT_LABEL[r.result] || label(r.lifecycle)}</span></td><td><a href={`#run/${r.run_id}`}>{r.repository_path?.split('/').filter(Boolean).pop() || label(r.scenario_id || 'API migration')}</a></td><td className="why">{r.result_reason}</td><td>{duration(elapsed(r))}</td><td>{new Date(r.created_at).toLocaleString()}</td></tr>)}</tbody></table></div>:<div className="empty"><h2>No migrations yet</h2><p>Provide a client repository and two API documents to start.</p><a href="#new">New migration →</a></div>}</section></>}
      {view.startsWith('run/') && !run && <p role="status">Loading saved migration…</p>}
      {run && <><div className="intro"><p className="eyebrow">MIGRATION / {run.run_id.slice(0,8)}</p><h1>{run.repository_path?.split('/').filter(Boolean).pop() || label(run.scenario_id || 'API migration')}</h1><p><span className={`badge result-${run.result}`}>{mark({pass:'ok',partial:'warn',review:'warn',fail:'error',running:'info'}[run.result] || 'info')} {RESULT_LABEL[run.result] || label(run.lifecycle)}</span> {run.mode==='review'?'Review first':'Automatic'} · {duration(elapsed(run))}</p></div>
        <section className={`card verdict verdict-${run.result}`}>
          <h2>{RESULT_LABEL[run.result] || label(run.lifecycle)}</h2>
          <p className="reason">{run.result_reason}</p>
          <ol className="stage-list">{stageRows(run).map(([name, status, detail]) => <li key={name} className={`stage-${status}`}>{mark(status)}<strong>{name}</strong><span>{detail}</span></li>)}</ol>
        </section>
        {run.manual_actions.length>0&&<section className="notice manual"><h2>Manual work remains</h2>{run.manual_actions.map((a,i)=><div key={i}><p>{a.required_work}</p><p><strong>Decision needed:</strong> {a.unresolved_decision}</p><p>{a.blocking_effect}</p></div>)}</section>}
        {run.lifecycle==='awaiting_review'&&<section className="card"><h2>Review the migration</h2><p>Inspect the detected changes and evidence below. Edit the summary or add corrections, then reanalyze before approval.</p>
          <label>Migration summary<textarea rows={4} value={reviewSummary} onChange={e=>setReviewSummary(e.target.value)}/></label>
          <label>Review notes and corrections<textarea rows={3} value={reviewNotes} onChange={e=>setReviewNotes(e.target.value)} placeholder="Correct the scope or explain the intended behavior…"/></label>
          <div className="form-footer"><button disabled={busy||!reviewChanged} onClick={revise}>Reanalyze edits</button><button className="primary" disabled={busy||reviewChanged} onClick={repair}>{busy?'Starting…':'Approve and generate repair →'}</button></div>
          {reviewChanged&&<p className="hint">Reanalyze your edits before approving. A linked run preserves this analysis for comparison.</p>}
        </section>}
        {run.parent_run_id&&<p><a href={`#run/${run.parent_run_id}`}>View previous analysis</a></p>}
        <div className="stats"><div><span>Model requests</span><strong>{run.budget.used_requests} / {run.budget.limits?.requests ?? 12}</strong></div><div><span>Patch attempts</span><strong>{run.budget.used_patch_attempts} / {run.budget.limits?.patch_attempts ?? 6}</strong></div><div><span>Development</span><strong>{label(run.development_verification)}</strong></div><div><span>Independent evaluation</span><strong>{label(run.evaluation.verdict)}</strong></div></div>
        <section className="card"><h2>Changes & evidence</h2>{run.changes.length ? run.changes.map(c=><article className="change" key={c.id}><span className="badge">{label(c.disposition)}</span><h3>{label(c.kind)}</h3><p>{c.description}</p><ul>{c.evidence.map(evidence)}</ul>{c.affected_locations.length>0&&<><h4>Affected source</h4><ul>{c.affected_locations.map(evidence)}</ul></>}</article>):<p className="hint">Analysis has not produced changes yet.</p>}</section>
        <section className="card"><h2>Source patch</h2><pre className="diff">{diff || (done(run)?'No source edits delivered.':'The patch will appear after repair.')}</pre></section>
        <section className="card"><h2>Development checks</h2>{run.development_checks.map(c=><p key={c.id}><strong>{c.id} · {c.status}</strong><br/><code>{c.revision_hash.slice(0,16)}</code> · <a href={`${runUrl(run.run_id)}/artifacts/${c.log_artifact_id}`}>Download log</a></p>)}{!run.development_checks.length&&<p>No checks have run.</p>}<p className="hint">Development checks and independent evaluation are separate results.</p></section>
        <section className="card"><h2>Artifacts</h2><div className="downloads">{run.artifacts.map(a=><a key={a} href={`${runUrl(run.run_id)}/artifacts/${encodeURIComponent(a)}`}>↓ {a}</a>)}</div></section>
        {run.warnings.map((w,i)=><div className="notice" key={i}>{w}</div>)}
        <details className="card" open={['fail','partial','running'].includes(run.result)}><summary>Activity log <span className="optional">{events.length} step(s) across every agent</span></summary>
          <ol className="events">{events.map(e=>{const status=eventStatus(e); return <li key={e.seq} className={`event event-${status}`}>{mark(status)}<time>{clock(e.at)}</time><span className="stage-tag">{e.stage || label(e.kind)}</span><span className="event-message">{e.message}{took(e.duration_ms)}</span></li>;})}
          {!events.length&&<li className="hint">No activity recorded yet.</li>}</ol>
          <p className="hint">Every line names the agent or stage that produced it. Check logs and the full patch are under Artifacts.</p>
        </details>
      </>}
      <footer>API Maintainer <span>Evidence-backed migrations. Local by design.</span></footer>
    </main>
  </div>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
