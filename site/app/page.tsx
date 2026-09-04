'use client';

import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';

type ChatMessage = { role: 'agent' | 'user'; content: string; model?: string };
type RiskCheck = { label: string; passed: boolean; observed: unknown; limit: unknown };
type RuntimeAccount = {
  equity: number; last_equity: number; buying_power: number; options_buying_power: number;
  option_market_value: number; daily_pnl: number; high_watermark: number;
  open_option_positions: number; trades_today: number; options_trading_level: number;
  is_paper: boolean; market_open: boolean; minutes_to_close?: number | null; account_id_masked?: string | null;
  error?: string;
};
type RuntimeReport = {
  run_id: string; created_at: string; status: string; symbol: string; mode: string; execution_mode: string;
  features?: { spot: number; signal_score: number; baseline_stance: string; rsi_14: number; timestamp: string; strategy?: string; volatility_ratio?: number; breakout_20bar?: number } | null;
  proposal?: { proposal_id: string; structure: string; max_loss: number; max_profit?: number | null; quantity: number } | null;
  critic?: { verdict: string; thesis: string; source: string; model?: string | null } | null;
  risk?: { approved: boolean; summary: string; checks: RiskCheck[] } | null;
  thesis?: { summary: string; source: string; stance: string; confidence: number } | null;
  audit?: { record_hash: string; previous_hash: string; sequence: number };
};
type RuntimeControl = {
  enabled: boolean; strategy: string; underlyings: string[]; min_signal_score: number;
  risk_per_trade_pct: number; max_option_exposure_pct: number; max_trades_per_day: number;
  max_positions: number; max_hold_minutes: number; profit_target_pct: number;
  stop_loss_pct: number; scan_interval_seconds: number; version: number; updated_at: string;
};
type StrategyReview = {
  completed_structures: number; win_rate?: number | null; average_return?: number | null;
  verdict: string; reason: string; proposed_changes: Partial<RuntimeControl>;
  auto_applied: false; owner_approval_required: true;
};
type RuntimeState = {
  connected: true; fetched_at: string;
  settings: { mode: string; execution_mode: string; underlyings: string[]; available_underlyings?: string[]; strategies?: string[]; ai_provider: string; ai_model?: string | null; signal_model: string; min_signal_score: number; option_feed: string; paper_execution_unlocked: boolean };
  health: Record<string, unknown>; account: RuntimeAccount; kill_switch: boolean;
  stats: { total_cycles: number; by_status: Record<string, number>; audit_chain_valid: boolean; audit_records: number };
  control: RuntimeControl; review: StrategyReview;
  recent: RuntimeReport[]; charts: Record<string, Array<{ timestamp: string; close: number }>>;
};
type ConnectionPhase = 'connecting' | 'waking' | 'online' | 'offline';

const RUNTIME_CACHE_KEY = 'glassbox:last-runtime';
const WAKE_WINDOW_MS = 90_000;
const POLL_INTERVAL_MS = 5_000;

const money = (value: number | undefined) => value === undefined ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value);
const signedMoney = (value: number | undefined) => value === undefined ? '—' : `${value >= 0 ? '+' : '−'}${money(Math.abs(value))}`;
const shortId = (value: string | undefined, size = 9) => value ? `${value.slice(0, size)}…` : '—';
const readable = (value: string | undefined) => value ? value.replaceAll('_', ' ').toUpperCase() : '—';
const displayValue = (value: unknown) => value === null || value === undefined ? '—' : typeof value === 'boolean' ? (value ? 'YES' : 'NO') : typeof value === 'object' ? JSON.stringify(value) : String(value);

export default function Home() {
  const [runtime, setRuntime] = useState<RuntimeState | null>(null);
  const [runtimeError, setRuntimeError] = useState('Connecting to the Python agent…');
  const [runtimeLoading, setRuntimeLoading] = useState(true);
  const [connectionPhase, setConnectionPhase] = useState<ConnectionPhase>('connecting');
  const [retryCount, setRetryCount] = useState(0);
  const [cachedAt, setCachedAt] = useState('');
  const wakeStartedAt = useRef<number | null>(null);
  const [cycleBusy, setCycleBusy] = useState('');
  const [cycleNotice, setCycleNotice] = useState('');
  const [selectedStrategy, setSelectedStrategy] = useState('auto');
  const [selectedRunId, setSelectedRunId] = useState('');
  const [chatInput, setChatInput] = useState('');
  const [chatBusy, setChatBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [ownerToken, setOwnerToken] = useState('');
  const [ownerUnlocked, setOwnerUnlocked] = useState(false);
  const [controlDraft, setControlDraft] = useState<RuntimeControl | null>(null);
  const [controlNotice, setControlNotice] = useState('');
  const [controlBusy, setControlBusy] = useState(false);

  async function refreshRuntime() {
    try {
      const response = await fetch('/api/runtime', { cache: 'no-store' });
      const payload = await response.json() as RuntimeState & { error?: string; detail?: string };
      if (!response.ok) throw new Error(payload.detail || payload.error || 'Python agent is unavailable');
      setRuntime(payload);
      setRuntimeError('');
      setConnectionPhase('online');
      setRetryCount(0);
      setCachedAt('');
      wakeStartedAt.current = null;
      try { window.localStorage.setItem(RUNTIME_CACHE_KEY, JSON.stringify({ runtime: payload, savedAt: payload.fetched_at })); } catch { /* storage is optional */ }
      setSelectedRunId((current) => current || payload.recent?.[0]?.run_id || '');
    } catch (error) {
      const now = Date.now();
      wakeStartedAt.current ??= now;
      setConnectionPhase(now - wakeStartedAt.current < WAKE_WINDOW_MS ? 'waking' : 'offline');
      setRetryCount((current) => current + 1);
      setRuntimeError(error instanceof Error ? error.message : 'Python agent is unavailable');
    } finally { setRuntimeLoading(false); }
  }

  useEffect(() => {
    let active = true;
    let timer = 0;
    try {
      const cached = JSON.parse(window.localStorage.getItem(RUNTIME_CACHE_KEY) ?? 'null') as { runtime?: RuntimeState; savedAt?: string } | null;
      if (cached?.runtime) { setRuntime(cached.runtime); setCachedAt(cached.savedAt ?? cached.runtime.fetched_at); }
    } catch { /* a damaged cache should never block live data */ }
    async function poll() {
      if (!active) return;
      await refreshRuntime();
      if (active) timer = window.setTimeout(poll, POLL_INTERVAL_MS);
    }
    void poll();
    return () => { active = false; window.clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (runtime?.control && !ownerUnlocked) setControlDraft(runtime.control);
  }, [runtime?.control, ownerUnlocked]);

  const runtimeOnline = connectionPhase === 'online';
  const runtimeWaking = connectionPhase === 'waking' || connectionPhase === 'connecting';
  const account = runtime?.account && !runtime.account.error ? runtime.account : null;
  const latest = runtime?.recent?.[0];
  const selected = runtime?.recent.find((item) => item.run_id === selectedRunId) ?? latest;
  const aiOnline = runtimeOnline && runtime?.settings.ai_provider === 'DeepSeek' && Boolean(runtime.settings.ai_model);
  const chartSymbol = latest?.symbol ?? runtime?.settings.underlyings?.[0];
  const bars = useMemo(() => chartSymbol ? runtime?.charts?.[chartSymbol] ?? [] : [], [chartSymbol, runtime?.charts]);
  const chartPath = useMemo(() => {
    if (bars.length < 2) return '';
    const values = bars.map((bar) => bar.close); const low = Math.min(...values); const span = Math.max(Math.max(...values) - low, 0.01);
    return values.map((value, index) => `${index * (640 / Math.max(values.length - 1, 1))},${126 - ((value - low) / span) * 100}`).join(' L ');
  }, [bars]);

  async function runLiveCycle(symbol: string) {
    if (!runtime || !runtimeOnline || cycleBusy) return;
    setCycleBusy(symbol); setCycleNotice('');
    try {
      const response = await fetch('/api/runtime', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, strategy: selectedStrategy }) });
      const payload = await response.json() as RuntimeReport & { error?: string };
      if (!response.ok) throw new Error(payload.error || 'Agent cycle failed');
      setCycleNotice(`${symbol} ${readable(selectedStrategy)} preview: ${readable(payload.status)}. Public previews never submit orders.`);
      await refreshRuntime(); setSelectedRunId(payload.run_id);
    } catch (error) { setCycleNotice(error instanceof Error ? error.message : 'Agent cycle failed'); }
    finally { setCycleBusy(''); }
  }

  async function askAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const question = chatInput.trim();
    if (!question || chatBusy) return;
    setMessages((current) => [...current, { role: 'user', content: question }]); setChatInput(''); setChatBusy(true);
    try {
      const response = await fetch('/api/agent', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question, strategy: selectedStrategy }) });
      const payload = await response.json() as { answer?: string; model?: string; error?: string };
      if (!response.ok || !payload.answer) throw new Error(payload.error || 'Agent unavailable');
      setMessages((current) => [...current, { role: 'agent', content: payload.answer!, model: payload.model }]);
    } catch (error) { setMessages((current) => [...current, { role: 'agent', content: error instanceof Error ? error.message : 'Model endpoint unavailable.' }]); }
    finally { setChatBusy(false); }
  }

  async function unlockOwner(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ownerToken.trim() || controlBusy) return;
    setControlBusy(true); setControlNotice('');
    try {
      const response = await fetch('/api/control', { headers: { Authorization: `Bearer ${ownerToken.trim()}` }, cache: 'no-store' });
      const payload = await response.json() as RuntimeControl & { error?: string };
      if (!response.ok) throw new Error(payload.error || 'Owner authorization failed');
      setControlDraft(payload); setOwnerUnlocked(true); setControlNotice('Owner controls unlocked for this tab only.');
    } catch (error) { setOwnerUnlocked(false); setControlNotice(error instanceof Error ? error.message : 'Authorization failed'); }
    finally { setControlBusy(false); }
  }

  async function saveControl(next?: RuntimeControl) {
    const value = next ?? controlDraft;
    if (!value || !ownerUnlocked || controlBusy) return;
    setControlBusy(true); setControlNotice('');
    try {
      const { version: _version, updated_at: _updatedAt, ...editable } = value;
      const response = await fetch('/api/control', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ownerToken.trim()}` }, body: JSON.stringify(editable) });
      const payload = await response.json() as RuntimeControl & { error?: string };
      if (!response.ok) throw new Error(payload.error || 'Control update failed');
      setControlDraft(payload); setControlNotice(`Configuration v${payload.version} applied to the autonomous Paper agent.`);
      await refreshRuntime();
    } catch (error) { setControlNotice(error instanceof Error ? error.message : 'Control update failed'); }
    finally { setControlBusy(false); }
  }

  function setControl<K extends keyof RuntimeControl>(key: K, value: RuntimeControl[K]) {
    setControlDraft((current) => current ? { ...current, [key]: value } : current);
  }

  const decisionTone = selected?.risk?.approved ? 'pass' : selected?.status.includes('error') ? 'error' : 'abstain';
  const decisionLabel = selected?.risk?.approved ? 'APPROVED' : selected ? readable(selected.status) : 'NO RUN';

  return (
    <main className="appShell">
      <header className="appHeader">
        <a className="brand" href="#top"><span className="mark">G</span><span>GLASSBOX <b>ALPHA</b></span></a>
        <div className="headerStatus"><span className={`connectionDot ${runtimeOnline ? 'online' : runtimeWaking ? 'waking' : ''}`} /><b>{connectionPhase === 'online' ? 'ALPACA CONNECTED' : connectionPhase === 'offline' ? 'AGENT OFFLINE' : connectionPhase === 'waking' ? 'WAKING AGENT' : 'CONNECTING'}</b><span>PAPER ONLY</span></div>
      </header>

      <div className="workspace" id="top">
        <section className="intro">
          <div><span className="kicker">AUDITABLE OPTIONS AGENT</span><h1>AI can veto.<br />Code controls the trade.</h1><p>Run the live pipeline, inspect every hard risk gate, then ask DeepSeek to explain the immutable decision record.</p></div>
          <div className="systemSummary">
            <span>EXECUTION</span><b>{runtime?.settings.execution_mode?.toUpperCase() ?? '—'}</b>
            <span>MODEL</span><b>{runtime?.settings.ai_model ?? '—'}</b>
            <span>SIGNAL</span><b>{runtime ? `${runtime.settings.signal_model.toUpperCase()} ≥ ${runtime.settings.min_signal_score.toFixed(2)}` : '—'}</b>
            <span>AUDIT</span><b className={runtime?.stats.audit_chain_valid ? 'ok' : ''}>{runtime ? (runtime.stats.audit_chain_valid ? 'CHAIN VERIFIED' : 'CHAIN INVALID') : '—'}</b>
          </div>
        </section>

        {!runtimeOnline && <section className={`offlinePanel ${runtimeWaking ? 'wakingPanel' : ''}`}><div><span>RUNTIME CONNECTION</span><h2>{connectionPhase === 'offline' ? 'Agent could not be reached' : 'Waking the Paper Trading Agent…'}</h2><p>{connectionPhase === 'offline' ? runtimeError : `Render free instances can take up to a minute to start. Retrying automatically${retryCount ? ` · attempt ${retryCount}` : ''}.`}{cachedAt ? ` Showing the last verified snapshot from ${new Date(cachedAt).toLocaleString()}.` : ''}</p></div><div className="wakeStatus"><i /><b>{runtimeWaking ? 'AUTO RETRY ACTIVE' : 'RETRYING IN BACKGROUND'}</b><small>{runtimeLoading ? 'Connecting…' : 'Trading and chat remain locked until verified.'}</small></div></section>}

        <section className="metrics" aria-label="Live Alpaca account">
          <article><span>ACCOUNT EQUITY</span><b>{money(account?.equity)}</b><small>{account ? `Alpaca ${account.account_id_masked ?? 'masked'}` : 'Broker unavailable'}</small></article>
          <article><span>DAILY P&amp;L</span><b className={(account?.daily_pnl ?? 0) >= 0 ? 'positive' : 'negative'}>{signedMoney(account?.daily_pnl)}</b><small>Reported by broker</small></article>
          <article><span>OPTION EXPOSURE</span><b>{money(account?.option_market_value)}</b><small>{account ? `${account.open_option_positions} open positions` : '—'}</small></article>
          <article><span>PAPER TRADES TODAY</span><b>{account?.trades_today ?? '—'}</b><small>{runtime ? `${runtime.stats.audit_records} audit records total` : '—'}</small></article>
        </section>

        <section className="ownerConsole" aria-label="Autonomous agent strategy controls">
          <div className="panelHeader"><div><span className="kicker">AUTONOMOUS PAPER AGENT</span><h2>Strategy &amp; risk control</h2></div><div className={`agentMode ${runtime?.control?.enabled ? 'running' : ''}`}><i /><span>{runtime?.control?.enabled ? 'RUNNING' : 'PAUSED'}</span><small>CONFIG v{runtime?.control?.version ?? '—'}</small></div></div>
          <div className="controlOverview">
            <div><span>ACTIVE STRATEGY</span><b>{readable(runtime?.control?.strategy)}</b></div><div><span>SCAN</span><b>{runtime?.control ? `${runtime.control.scan_interval_seconds / 60} MIN` : '—'}</b></div><div><span>UNIVERSE</span><b>{runtime?.control?.underlyings?.join(' · ') || '—'}</b></div><div><span>ENTRY / EXPOSURE</span><b>{runtime?.control ? `${(runtime.control.risk_per_trade_pct * 100).toFixed(2)}% / ${(runtime.control.max_option_exposure_pct * 100).toFixed(2)}%` : '—'}</b></div>
          </div>
          {!ownerUnlocked ? <form className="ownerLogin" onSubmit={unlockOwner}><div><b>OWNER CONTROL</b><span>Public visitors can inspect and preview. Only the account owner can change strategy or route autonomous Paper orders.</span></div><input type="password" value={ownerToken} onChange={(event) => setOwnerToken(event.target.value)} placeholder="Owner control token" autoComplete="current-password" /><button type="submit" disabled={controlBusy || !ownerToken.trim()}>{controlBusy ? 'VERIFYING…' : 'UNLOCK'}</button></form> : controlDraft && <div className="ownerEditor">
            <div className="field"><label>STRATEGY</label><select value={controlDraft.strategy} onChange={(event) => setControl('strategy', event.target.value)}>{runtime?.settings.strategies?.map((strategy) => <option key={strategy} value={strategy}>{readable(strategy)}</option>)}</select></div>
            <div className="field"><label>MIN SIGNAL</label><input type="number" min="0.20" max="0.60" step="0.01" value={controlDraft.min_signal_score} onChange={(event) => setControl('min_signal_score', Number(event.target.value))} /></div>
            <div className="field"><label>RISK / TRADE</label><input type="number" min="0.0005" max="0.0025" step="0.0005" value={controlDraft.risk_per_trade_pct} onChange={(event) => setControl('risk_per_trade_pct', Number(event.target.value))} /></div>
            <div className="field"><label>TOTAL EXPOSURE</label><input type="number" min="0.0025" max="0.01" step="0.0025" value={controlDraft.max_option_exposure_pct} onChange={(event) => setControl('max_option_exposure_pct', Number(event.target.value))} /></div>
            <div className="field"><label>TRADES / DAY</label><input type="number" min="1" max="8" step="1" value={controlDraft.max_trades_per_day} onChange={(event) => setControl('max_trades_per_day', Number(event.target.value))} /></div>
            <div className="field"><label>MAX STRUCTURES</label><input type="number" min="1" max="3" step="1" value={controlDraft.max_positions} onChange={(event) => setControl('max_positions', Number(event.target.value))} /></div>
            <div className="field"><label>MAX HOLD (MIN)</label><input type="number" min="30" max="120" step="15" value={controlDraft.max_hold_minutes} onChange={(event) => setControl('max_hold_minutes', Number(event.target.value))} /></div>
            <div className="field"><label>TAKE PROFIT</label><input type="number" min="0.10" max="0.50" step="0.05" value={controlDraft.profit_target_pct} onChange={(event) => setControl('profit_target_pct', Number(event.target.value))} /></div>
            <div className="field"><label>STOP LOSS</label><input type="number" min="0.10" max="0.25" step="0.01" value={controlDraft.stop_loss_pct} onChange={(event) => setControl('stop_loss_pct', Number(event.target.value))} /></div>
            <div className="field"><label>SCAN INTERVAL</label><select value={controlDraft.scan_interval_seconds} onChange={(event) => setControl('scan_interval_seconds', Number(event.target.value))}><option value={300}>5 MIN</option><option value={600}>10 MIN</option><option value={900}>15 MIN</option><option value={1800}>30 MIN</option><option value={3600}>60 MIN</option></select></div>
            <div className="symbolField"><label>SYMBOLS</label><div>{(runtime?.settings.available_underlyings ?? runtime?.settings.underlyings ?? []).map((symbol) => <label key={symbol}><input type="checkbox" checked={controlDraft.underlyings.includes(symbol)} onChange={(event) => setControl('underlyings', event.target.checked ? [...controlDraft.underlyings, symbol] : controlDraft.underlyings.filter((item) => item !== symbol))} />{symbol}</label>)}</div></div>
            <div className="controlActions"><button type="button" onClick={() => void saveControl()} disabled={controlBusy || !controlDraft.underlyings.length}>{controlBusy ? 'APPLYING…' : 'APPLY CONFIG'}</button><button className={controlDraft.enabled ? 'pause' : 'start'} type="button" onClick={() => { const next = { ...controlDraft, enabled: !controlDraft.enabled }; setControlDraft(next); void saveControl(next); }} disabled={controlBusy}>{controlDraft.enabled ? 'PAUSE NEW ENTRIES' : 'START AUTONOMOUS'}</button></div>
          </div>}
          <div className="reviewStrip"><div><span>AGENT REVIEW</span><b>{readable(runtime?.review?.verdict)}</b><p>{runtime?.review?.reason ?? 'Waiting for runtime evidence.'}</p></div><div><span>COMPLETED / WIN RATE / AVG</span><b>{runtime?.review ? `${runtime.review.completed_structures} / ${runtime.review.win_rate == null ? '—' : `${(runtime.review.win_rate * 100).toFixed(0)}%`} / ${runtime.review.average_return == null ? '—' : `${(runtime.review.average_return * 100).toFixed(1)}%`}` : '—'}</b><small>Recommendations are never auto-applied. Owner approval is required.</small></div></div>
          {controlNotice && <p className="controlNotice">{controlNotice}</p>}
        </section>

        <section className="controlGrid">
          <div className="leftColumn">
            <article className="agentControl">
              <div className="panelHeader"><div><span className="kicker">STRATEGY LAB</span><h2>Preview a real-data decision</h2></div><span className="marketBadge">PREVIEW ONLY</span></div>
              <div className="pipeline" aria-label="Agent pipeline">
                {[[ '01', 'MARKET', 'Completed bars' ], [ '02', 'PROPOSE', 'Defined risk' ], [ '03', 'CRITIC', 'DeepSeek veto' ], [ '04', 'RISK', 'Hard gates' ], [ '05', 'EXECUTE', 'Alpaca Paper' ]].map(([number, title, note]) => <div key={number}><span>{number}</span><b>{title}</b><small>{note}</small></div>)}
              </div>
              <div className="strategyPicker"><label htmlFor="strategy">STRATEGY</label><select id="strategy" value={selectedStrategy} onChange={(event) => setSelectedStrategy(event.target.value)}>{(runtime?.settings.strategies ?? ['auto']).map((strategy) => <option key={strategy} value={strategy}>{readable(strategy)}</option>)}</select><span>Uses live Alpaca evidence · cannot submit orders</span></div>
              <div className="runRow"><div>{runtime?.settings.underlyings?.map((symbol) => <button key={symbol} type="button" onClick={() => void runLiveCycle(symbol)} disabled={!runtimeOnline || Boolean(cycleBusy)}>{cycleBusy === symbol ? 'RUNNING…' : `PREVIEW ${symbol}`}</button>)}</div><p>{cycleNotice || (!runtimeOnline ? 'Controls unlock automatically after the Agent connection is verified.' : 'Choose any strategy and symbol. This public workspace is always preview-only.')}</p></div>
            </article>

            <article className="decisionCard">
              <div className="panelHeader"><div><span className="kicker">SELECTED DECISION</span><h2>{selected ? `${selected.symbol} · ${readable(selected.features?.baseline_stance ?? selected.status)}` : 'No decision recorded'}</h2></div><div className={`decisionBadge ${decisionTone}`}><span>{decisionLabel}</span><small>{selected?.execution_mode ? readable(selected.execution_mode) : 'WAITING'}</small></div></div>
              <div className="decisionBody">
                <div className="marketEvidence">
                  <div className="evidenceValues"><div><span>STRATEGY</span><b>{readable(selected?.features?.strategy)}</b></div><div><span>SIGNAL</span><b>{selected?.features?.signal_score?.toFixed(3) ?? '—'}</b></div><div><span>VOL RATIO</span><b>{selected?.features?.volatility_ratio?.toFixed(2) ?? '—'}</b></div><div><span>BREAKOUT</span><b>{selected?.features?.breakout_20bar?.toFixed(2) ?? '—'}</b></div></div>
                  <div className="miniChart">{chartPath ? <svg viewBox="0 0 640 140" preserveAspectRatio="none" role="img" aria-label={`${chartSymbol} completed bars`}><path className="chartGrid" d="M0 20H640M0 70H640M0 120H640" /><path className="chartLine" d={`M ${chartPath}`} /></svg> : <span>Completed Alpaca bars appear after a cycle.</span>}</div>
                </div>
                <div className="decisionExplanation">
                  <span className="kicker">MODEL &amp; RISK VERDICT</span>
                  <blockquote>{selected?.critic?.thesis ?? selected?.risk?.summary ?? selected?.thesis?.summary ?? (selected ? 'No candidate reached the AI critic. The deterministic signal layer abstained.' : 'Run the Agent to create a real decision record.')}</blockquote>
                  <dl><div><dt>AI REVIEW</dt><dd>{selected?.critic ? `${readable(selected.critic.verdict)} · ${selected.critic.model ?? selected.critic.source}` : 'NOT INVOKED'}</dd></div><div><dt>PROPOSAL</dt><dd>{selected?.proposal ? `${readable(selected.proposal.structure)} · ${selected.proposal.quantity}×` : 'NONE'}</dd></div><div><dt>MAX LOSS</dt><dd>{money(selected?.proposal?.max_loss)}</dd></div><div><dt>ORDER</dt><dd>{selected?.risk?.approved ? 'ELIGIBLE FOR PAPER ROUTING' : 'NOT SENT'}</dd></div></dl>
                </div>
              </div>
            </article>
          </div>

          <aside className="agentChat" aria-label="Chat with the agent">
            <div className="chatHead"><div className="agentAvatar">AI</div><div><b>ASK GLASSBOX</b><span>{aiOnline ? `${runtime?.settings.ai_model} · GROUNDED` : 'MODEL OFFLINE'}</span></div><em>NO ORDER TOOL</em></div>
            <div className="grounding"><span>READING</span><b>{latest ? `${latest.symbol} · ${shortId(latest.run_id)}` : 'NO AUDIT RECORD'}</b></div>
            <div className="messages" aria-live="polite">
              {messages.length === 0 && <div className="welcomeMessage"><span>Ask about the latest real decision</span><p>Why did the Agent abstain? What was the maximum loss? Which gate blocked execution?</p></div>}
              {messages.map((message, index) => <div className={`message ${message.role}`} key={`${message.role}-${index}`}><span>{message.role === 'agent' ? 'DEEPSEEK' : 'YOU'}</span><p>{message.content}</p>{message.model && <small>{message.model} · runtime evidence</small>}</div>)}
              {chatBusy && <div className="message agent"><span>DEEPSEEK</span><p>Reading the audit record…</p></div>}
            </div>
            <div className="quickPrompts">{['Why did the Agent make this decision?', 'Which risk checks mattered most?', 'What would allow a paper order?'].map((prompt) => <button type="button" key={prompt} onClick={() => setChatInput(prompt)}>{prompt}</button>)}</div>
            <form className="chatForm" onSubmit={askAgent}><input aria-label="Ask the Agent" value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder={aiOnline && latest ? 'Ask about the latest decision…' : 'Connect DeepSeek and run the Agent first'} disabled={!aiOnline || !latest} maxLength={500} /><button type="submit" disabled={!chatInput.trim() || chatBusy || !aiOnline || !latest}>SEND</button></form>
          </aside>
        </section>

        <section className="auditSection" id="audit">
          <div className="panelHeader"><div><span className="kicker">TRADE PASSPORTS</span><h2>Every decision is independently auditable.</h2></div><div className={`chainBadge ${runtime?.stats.audit_chain_valid ? 'valid' : ''}`}>{runtime?.stats.audit_chain_valid ? '✓ SHA-256 CHAIN VALID' : 'CHAIN UNAVAILABLE'}</div></div>
          <div className="auditGrid">
            <div className="recordList"><div className="recordHeader"><span>TIME / SYMBOL</span><span>OUTCOME</span><span>HASH</span></div>{runtime?.recent?.length ? runtime.recent.slice(0, 8).map((report) => <button className={selected?.run_id === report.run_id ? 'selected' : ''} type="button" key={report.run_id} onClick={() => setSelectedRunId(report.run_id)}><span><b>{report.symbol}</b><small>{new Date(report.created_at).toLocaleString()}</small></span><strong>{readable(report.status)}</strong><code>{shortId(report.audit?.record_hash, 10)}</code></button>) : <div className="emptyRecords">No real Agent decisions recorded.</div>}</div>
            <div className="passportDetail">
              <div className="passportMeta"><span>RUN ID <code>{selected?.run_id ?? '—'}</code></span><span>SEQUENCE <b>{selected?.audit?.sequence ?? '—'}</b></span><span>PREVIOUS <code>{shortId(selected?.audit?.previous_hash, 14)}</code></span><span>RECORD HASH <code>{shortId(selected?.audit?.record_hash, 18)}</code></span></div>
              <h3>Deterministic risk checks</h3>
              <div className="riskChecks">{selected?.risk?.checks?.length ? selected.risk.checks.slice(0, 12).map((check) => <div className={check.passed ? 'passed' : 'failed'} key={check.label}><i>{check.passed ? '✓' : '×'}</i><span><b>{check.label}</b><small>{displayValue(check.observed)} / limit {displayValue(check.limit)}</small></span></div>) : <p>No proposal reached the risk kernel in this cycle.</p>}</div>
            </div>
          </div>
        </section>

        <section className="riskPolicy" aria-label="Risk policy"><span>NON-NEGOTIABLE POLICY</span><b>Defined-risk options only</b><b>AI has veto-only authority</b><b>Failed checks force abstention</b><b>Paper trading only</b></section>
      </div>

      <footer><span>GLASSBOX ALPHA · ALPACA AI TRADING AGENTS HACKATHON</span><p>Paper trading is not investment advice. Basic-plan options data may be indicative. Paper fills do not model live liquidity, latency, slippage, fees, or market impact.</p></footer>
    </main>
  );
}
