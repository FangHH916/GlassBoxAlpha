'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';

type Scenario = 'clean' | 'ai_veto' | 'stale' | 'wide';
type ChatMessage = { role: 'agent' | 'user'; content: string; model?: string };
type RuntimeAccount = {
  equity: number; last_equity: number; buying_power: number; options_buying_power: number;
  option_market_value: number; daily_pnl: number; high_watermark: number;
  open_option_positions: number; trades_today: number; options_trading_level: number;
  is_paper: boolean; market_open: boolean; minutes_to_close?: number | null; account_id_masked?: string | null;
  error?: string;
};
type RuntimeReport = {
  run_id: string; created_at: string; status: string; symbol: string; mode: string; execution_mode: string;
  features?: { spot: number; signal_score: number; baseline_stance: string; rsi_14: number; timestamp: string } | null;
  proposal?: { proposal_id: string; structure: string; max_loss: number; max_profit?: number | null; quantity: number } | null;
  critic?: { verdict: string; thesis: string; source: string; model?: string | null } | null;
  risk?: { approved: boolean; summary: string; checks: Array<{ label: string; passed: boolean; observed: unknown; limit: unknown }> } | null;
  audit?: { record_hash: string; previous_hash: string; sequence: number };
};
type RuntimeState = {
  connected: true;
  fetched_at: string;
  settings: { mode: string; execution_mode: string; underlyings: string[]; ai_provider: string; ai_model?: string | null; option_feed: string; paper_execution_unlocked: boolean };
  health: Record<string, unknown>;
  account: RuntimeAccount;
  kill_switch: boolean;
  stats: { total_cycles: number; by_status: Record<string, number>; audit_chain_valid: boolean; audit_records: number };
  recent: RuntimeReport[];
  charts: Record<string, Array<{ timestamp: string; close: number }>>;
};

const passportPayload = JSON.stringify({
  candidate_id: 'GBA-7D90A3F1', symbol: 'SPY', structure: 'bull_call_debit_spread',
  quantity: 2, limit_debit: 2.5, max_loss: 500, critic: 'ALLOW',
  risk_checks: 32, execution: 'REPLAY_ONLY',
});
const storedPassportHash = '02d61a36fe9850156149a1c90eb2064ef4fcbd8777b7540dc4a4bca01e6eac21';

const baseGates = [
  ['Paper environment', 'Paper endpoint', 'paper', 'paper'],
  ['Dedicated account', 'Fresh competition account', 'matched', 'matched'],
  ['Market session', 'Minutes to close', '180 min', '≥ 45 min'],
  ['Candidate identity', 'Immutable hash', 'matched', 'matched'],
  ['AI critic', 'Veto-only verdict', 'ALLOW', 'ALLOW'],
  ['Signal strength', 'Completed-bar score', '0.52', '≥ 0.45'],
  ['Maximum loss', 'Worst-case debit', '$500', '≤ $500'],
  ['Portfolio risk', 'Open risk after trade', '0.50%', '≤ 1.00%'],
  ['Defined risk', 'No naked short leg', 'vertical', 'vertical'],
  ['Expiration', 'Days to expiry', '12 DTE', '7–21 DTE'],
  ['Quote freshness', 'Newest leg quote age', '2 sec', '≤ 30 sec'],
  ['Liquidity', 'Widest bid/ask', '5.1%', '≤ 12.0%'],
];

const priceBars = [42, 47, 45, 51, 55, 53, 58, 61, 59, 64, 68, 66, 72, 75, 73, 79, 82, 80, 85, 89, 87, 92, 94, 97];

const money = (value: number | undefined) => value === undefined ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value);
const signedMoney = (value: number | undefined) => value === undefined ? '—' : `${value >= 0 ? '+' : '−'}${money(Math.abs(value))}`;

const sleep = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export default function Home() {
  const [scenario, setScenario] = useState<Scenario>('clean');
  const [step, setStep] = useState(0);
  const [running, setRunning] = useState(false);
  const [hasRun, setHasRun] = useState(false);
  const [hashStatus, setHashStatus] = useState<'idle' | 'checking' | 'valid' | 'invalid'>('idle');
  const [chatInput, setChatInput] = useState('');
  const [chatBusy, setChatBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [runtime, setRuntime] = useState<RuntimeState | null>(null);
  const [runtimeError, setRuntimeError] = useState('Connecting to the Python agent…');
  const [runtimeLoading, setRuntimeLoading] = useState(true);
  const [cycleBusy, setCycleBusy] = useState(false);

  const failedGate = scenario === 'ai_veto' ? 'AI critic' : scenario === 'stale' ? 'Quote freshness' : scenario === 'wide' ? 'Liquidity' : null;
  const approved = hasRun && !failedGate;
  const rejected = hasRun && Boolean(failedGate);
  const latest = runtime?.recent?.[0];
  const account = runtime?.account && !runtime.account.error ? runtime.account : null;
  const aiOnline = runtime?.settings.ai_provider === 'DeepSeek' && Boolean(runtime.settings.ai_model);
  const chartSymbol = latest?.symbol ?? runtime?.settings.underlyings?.[0];
  const liveBars = useMemo(() => chartSymbol ? runtime?.charts?.[chartSymbol] ?? [] : [], [chartSymbol, runtime?.charts]);
  const chartPath = useMemo(() => {
    if (liveBars.length < 2) return '';
    const closes = liveBars.map((bar) => bar.close);
    const low = Math.min(...closes);
    const high = Math.max(...closes);
    const range = Math.max(high - low, 0.01);
    return closes.map((close, index) => `${index * (690 / Math.max(closes.length - 1, 1))},${175 - ((close - low) / range) * 145}`).join(' L ');
  }, [liveBars]);

  useEffect(() => {
    let active = true;
    async function refreshRuntime() {
      try {
        const response = await fetch('/api/runtime', { cache: 'no-store' });
        const payload = await response.json() as RuntimeState & { error?: string; detail?: string };
        if (!response.ok) throw new Error(payload.detail || payload.error || 'Python agent is unavailable');
        if (active) {
          setRuntime(payload);
          setRuntimeError('');
        }
      } catch (error) {
        if (active) {
          setRuntime(null);
          setRuntimeError(error instanceof Error ? error.message : 'Python agent is unavailable');
        }
      } finally {
        if (active) setRuntimeLoading(false);
      }
    }
    void refreshRuntime();
    const timer = window.setInterval(refreshRuntime, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const gates = useMemo(() => baseGates.map((gate) => {
    const item = [...gate];
    if (gate[0] === 'Quote freshness' && scenario === 'stale') item[2] = '94 sec';
    if (gate[0] === 'Liquidity' && scenario === 'wide') item[2] = '18.4%';
    if (gate[0] === 'AI critic' && scenario === 'ai_veto') item[2] = 'VETO';
    return item;
  }), [scenario]);

  async function runReplay() {
    if (running) return;
    setRunning(true);
    setHasRun(false);
    setStep(1);
    for (let next = 2; next <= 5; next += 1) {
      await sleep(420);
      setStep(next);
    }
    await sleep(250);
    setHasRun(true);
    setRunning(false);
    document.getElementById('passport')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function changeScenario(value: Scenario) {
    setScenario(value);
    setStep(0);
    setHasRun(false);
    setHashStatus('idle');
  }

  async function verifyReplayPassport() {
    setHashStatus('checking');
    const digest = await window.crypto.subtle.digest(
      'SHA-256', new TextEncoder().encode(`GENESIS${passportPayload}`),
    );
    const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
    setHashStatus(actual === storedPassportHash ? 'valid' : 'invalid');
  }

  async function askAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = chatInput.trim();
    if (!question || chatBusy) return;
    setMessages((current) => [...current, { role: 'user', content: question }]);
    setChatInput('');
    setChatBusy(true);
    try {
      const response = await fetch('/api/agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      const payload = await response.json() as { answer?: string; model?: string; error?: string };
      if (!response.ok || !payload.answer) throw new Error(payload.error || 'Agent unavailable');
      setMessages((current) => [...current, { role: 'agent', content: payload.answer!, model: payload.model }]);
    } catch (error) {
      setMessages((current) => [...current, {
        role: 'agent',
        content: error instanceof Error ? error.message : 'The model endpoint is unavailable.',
      }]);
    } finally {
      setChatBusy(false);
    }
  }

  function presetPrompt(prompt: string) {
    setChatInput(prompt);
  }

  async function runLiveCycle(symbol: string) {
    if (!runtime || cycleBusy) return;
    setCycleBusy(true);
    try {
      const response = await fetch('/api/runtime', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol }),
      });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || 'Agent cycle failed');
      const refreshed = await fetch('/api/runtime', { cache: 'no-store' });
      if (refreshed.ok) setRuntime(await refreshed.json() as RuntimeState);
    } catch (error) {
      setRuntimeError(error instanceof Error ? error.message : 'Agent cycle failed');
    } finally {
      setCycleBusy(false);
    }
  }

  const verdict = running ? 'ANALYZING' : approved ? 'APPROVED' : rejected ? 'ABSTAIN' : 'READY';

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="GlassBox Alpha home">
          <span className="mark" aria-hidden="true">G</span>
          <span>GLASSBOX <b>ALPHA</b></span>
        </a>
        <div className="status"><i /> PAPER ONLY · REPLAY</div>
        <a className="source" href="#architecture">HOW IT WORKS</a>
      </header>

      <section className="hero" id="top">
        <div className="eyebrow">OPTIONS ALPHA AGENTS · 2026</div>
        <h1>An AI options agent<br />you can audit <em>before</em> it trades.</h1>
        <p className="lede">AI may approve or veto. It can never invent a ticker, change a strike, increase size, or bypass the deterministic risk kernel.</p>
        <div className="heroActions">
          <button className="runButton" type="button" onClick={runReplay} disabled={running}>
            <span>{running ? 'RUNNING 32 RISK GATES' : 'RUN DECISION REPLAY'}</span><b>{running ? '···' : '→'}</b>
          </button>
          <span className="runHint">No credentials. No orders.<br />Credential-free replay.</span>
        </div>
      </section>

      <section className="authorityStrip" aria-label="Core differentiators">
        <div><span>01 · FREEZE</span><b>Code fixes the trade before AI sees it.</b><small>Symbol · strikes · quantity · price · max loss</small></div>
        <div><span>02 · DOUBLE VETO</span><b>AI or any hard gate can stop execution.</b><small>Neither layer can overrule the other</small></div>
        <div><span>03 · PROVE</span><b>Every decision links into a SHA-256 chain.</b><small>Inputs · verdict · limits · payload · result</small></div>
      </section>

      <section className="ticker" aria-label="System summary">
        <div><span>MODE</span><b>REPLAY / PAPER-LOCKED</b></div>
        <div><span>ACCOUNT BASELINE</span><b>$100,000.00</b></div>
        <div><span>OPTION LEVEL</span><b>LEVEL 3 · MLEG</b></div>
        <div><span>DATA FEED</span><b>INDICATIVE · DISCLOSED</b></div>
        <div><span>OPEN RISK</span><b>$0 · 0.00%</b></div>
      </section>

      <section className="commandCenter" aria-label="Agent command center">
        <div className="commandHead">
          <div><span className="label">LIVE AGENT COMMAND CENTER</span><h2>Only broker and agent data. No fabricated metrics.</h2></div>
          <div className={`liveBadge ${runtime ? '' : 'offline'}`}><i /> {runtimeLoading ? 'CONNECTING' : runtime ? `CONNECTED · ${runtime.settings.mode.toUpperCase()} · 5S` : 'DISCONNECTED'}</div>
        </div>

        <div className="dashboardGrid">
          <section className="metricBoard" aria-label="Portfolio metrics">
            {!runtime ? <div className="connectionEmpty"><span>PYTHON AGENT OFFLINE</span><h3>No account or market data is being displayed.</h3><p>{runtimeError}</p><code>BROKER_MODE=alpaca · USE_DEEPSEEK=true · python -m glassbox_alpha serve</code><small>Add credentials locally in `.env`; never commit them to GitHub.</small></div> : <div className="metricCards">
              <article><span>ALPACA EQUITY</span><b>{money(account?.equity)}</b><small>{account ? `Account ${account.account_id_masked ?? 'masked'}` : runtime.account.error}</small></article>
              <article><span>DAILY P&amp;L</span><b className={(account?.daily_pnl ?? 0) >= 0 ? 'positive' : 'negative'}>{signedMoney(account?.daily_pnl)}</b><small>Broker account state</small></article>
              <article><span>OPTION EXPOSURE</span><b>{money(account?.option_market_value)}</b><small>{account ? `${account.open_option_positions} open option positions` : 'Unavailable'}</small></article>
              <article><span>RECORDED CYCLES</span><b>{runtime.stats.total_cycles}</b><small>{runtime.stats.audit_chain_valid ? `${runtime.stats.audit_records} verified audit records` : 'AUDIT CHAIN INVALID'}</small></article>
            </div>}

            <article className="performancePanel">
              <div className="panelTitle"><span>{chartSymbol ?? 'MARKET'} · COMPLETED BARS</span><b>{latest?.features ? money(latest.features.spot) : 'NO REAL RUN'}</b></div>
              {runtime && chartPath ? <div className="lineChart" aria-label="Completed market bars from the Python agent">
                <svg viewBox="0 0 690 190" role="img" aria-label={`${chartSymbol} completed bar prices`}>
                  <path className="gridLine" d="M0 25H690M0 80H690M0 135H690M0 189H690" />
                  <path className="trend" d={`M ${chartPath}`} />
                </svg>
                <div className="chartAxis"><span>{liveBars[0]?.timestamp.slice(11, 16)}</span><span>PYTHON AGENT FEED</span><span>{liveBars.at(-1)?.timestamp.slice(11, 16)}</span></div>
              </div> : <div className="chartEmpty">{runtime ? 'Run a real preview cycle to load completed Alpaca bars.' : 'Waiting for a connected Python Agent.'}</div>}
              <div className="performanceFoot"><span>MODE <b>{runtime?.settings.mode.toUpperCase() ?? '—'}</b></span><span>FEED <b>{runtime?.settings.option_feed.toUpperCase() ?? '—'}</b></span><span>MARKET <b>{account ? (account.market_open ? 'OPEN' : 'CLOSED') : '—'}</b></span><span>KILL SWITCH <b>{runtime ? (runtime.kill_switch ? 'ENGAGED' : 'CLEAR') : '—'}</b></span></div>
            </article>

            <div className="watchAndActivity">
              <article className="watchlist">
                <div className="panelTitle"><span>AGENT WATCHLIST</span><b>{runtime ? `${runtime.settings.underlyings.length} SYMBOLS` : 'OFFLINE'}</b></div>
                {runtime?.settings.underlyings.map((symbol) => {
                  const report = runtime.recent.find((item) => item.symbol === symbol && item.features);
                  return <div className="watchRow" key={symbol}><b>{symbol}</b><span>{money(report?.features?.spot)}</span><span>{report?.features?.signal_score === undefined ? '—' : report.features.signal_score.toFixed(2)}</span><small>{report?.features?.baseline_stance?.toUpperCase() ?? 'NOT SCANNED'}</small></div>;
                })}
                {runtime && <button className="liveCycle" type="button" disabled={cycleBusy || !runtime.settings.underlyings[0]} onClick={() => void runLiveCycle(runtime.settings.underlyings[0])}>{cycleBusy ? 'RUNNING AGENT…' : `RUN ${runtime.settings.underlyings[0]} PREVIEW →`}</button>}
              </article>
              <article className="activityFeed">
                <div className="panelTitle"><span>DECISION STREAM</span><b>PYTHON LEDGER</b></div>
                {runtime?.recent.length ? runtime.recent.slice(0, 3).map((report) => <div className={`activity ${report.risk?.approved ? 'pass' : 'block'}`} key={report.run_id}><time>{report.created_at.slice(11, 19)}</time><i /><div><b>{report.symbol} · {report.status.replaceAll('_', ' ')}</b><small>{report.critic ? `${report.critic.verdict} · ${report.critic.source}${report.critic.model ? ` · ${report.critic.model}` : ''}` : report.risk?.summary ?? 'No candidate created'}</small></div></div>) : <div className="activityEmpty">No real Agent cycles have been recorded.</div>}
              </article>
            </div>
          </section>

          <aside className="agentChat" aria-label="Chat with the trading agent">
            <div className="chatHead">
              <div className="agentAvatar">AI</div>
              <div><b>GLASSBOX ANALYST</b><span><i /> {aiOnline ? `${runtime?.settings.ai_model} · REAL MODEL` : 'MODEL NOT CONNECTED'}</span></div>
              <em>VETO ONLY</em>
            </div>
            <div className="agentBoundary"><b>RUNTIME EVIDENCE</b><span>{latest ? `${latest.symbol} · ${latest.run_id.slice(0, 8)} · ${latest.status}` : 'A completed Agent cycle is required'}</span></div>
            <div className="messages" aria-live="polite">
              {!aiOnline && <div className="message system"><span>CONNECTION REQUIRED</span><p>Chat is disabled until the Python runtime reports a DeepSeek model and at least one real Agent cycle. No canned response will be substituted.</p></div>}
              {messages.map((message, index) => (
                <div className={`message ${message.role}`} key={`${message.role}-${index}`}>
                  <span>{message.role === 'agent' ? 'AGENT' : 'YOU'}</span>
                  <p>{message.content}</p>
                  {message.role === 'agent' && message.model && <small>DEEPSEEK · {message.model} · RUNTIME EVIDENCE</small>}
                </div>
              ))}
              {chatBusy && <div className="message agent thinking"><span>AGENT</span><p>Checking the frozen candidate and risk evidence…</p></div>}
            </div>
            <div className="quickPrompts">
              <button type="button" onClick={() => presetPrompt('Why did you make this decision?')}>WHY THIS DECISION?</button>
              <button type="button" onClick={() => presetPrompt('What is the worst-case loss?')}>EXPLAIN RISK</button>
              <button type="button" onClick={() => presetPrompt('What would make you veto this trade?')}>VETO CONDITIONS</button>
            </div>
            <form className="chatForm" onSubmit={askAgent}>
              <label htmlFor="agent-question">ASK ABOUT THE LATEST REAL DECISION</label>
              <div><input id="agent-question" value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder={aiOnline && latest ? 'Why was this candidate allowed?' : 'Connect Alpaca and DeepSeek first'} disabled={!aiOnline || !latest} maxLength={500} /><button type="submit" disabled={!chatInput.trim() || chatBusy || !aiOnline || !latest}>→</button></div>
            </form>
            <p className="chatDisclosure">Server-side model call · grounded in the latest audit record · no order tool.</p>
          </aside>
        </div>
      </section>

      <section className="decision" id="passport" aria-label="Trade decision passport">
        <div className="decisionHead">
          <div>
            <span className="label">TRADE PASSPORT · GBA-7D90A3F1</span>
            <h2>SPY · Bull call debit spread</h2>
          </div>
          <div className={`verdict ${rejected ? 'bad' : ''} ${running ? 'pending' : ''}`}>
            <span>{verdict}</span><b>{hasRun ? (approved ? 'PREVIEW ONLY' : 'NO ORDER SENT') : 'SELECT A SCENARIO'}</b>
          </div>
        </div>

        <div className="scenarioBar">
          <span>STRESS THE AGENT</span>
          <div role="group" aria-label="Replay scenario">
            <button className={scenario === 'clean' ? 'selected' : ''} onClick={() => changeScenario('clean')}>CLEAN MARKET</button>
            <button className={scenario === 'ai_veto' ? 'selected' : ''} onClick={() => changeScenario('ai_veto')}>AI VETO</button>
            <button className={scenario === 'stale' ? 'selected' : ''} onClick={() => changeScenario('stale')}>STALE QUOTE</button>
            <button className={scenario === 'wide' ? 'selected' : ''} onClick={() => changeScenario('wide')}>WIDE SPREAD</button>
          </div>
          <button className="miniRun" onClick={runReplay} disabled={running}>RUN →</button>
        </div>

        <div className="flow" id="architecture">
          {[
            ['01', 'MARKET', 'Completed 5m bars'],
            ['02', 'CANDIDATE', 'Defined-risk vertical'],
            ['03', 'AI CRITIC', 'ALLOW / VETO only'],
            ['04', 'RISK KERNEL', '32 hard gates'],
            ['05', 'ALPACA CLI', 'Paper execution'],
          ].map(([number, title, note], index) => (
            <div className="flowItem" key={number}>
              <div className={`node ${index === 2 ? 'accent' : ''} ${step > index ? 'active' : ''}`}>
                <span>{number}</span><b>{title}</b><small>{note}</small>
              </div>
              {index < 4 && <i>→</i>}
            </div>
          ))}
        </div>

        <div className="passportBody">
          <article className="marketPanel">
            <div className="panelTitle"><span>01 · MARKET EVIDENCE</span><b>SPY $667.69</b></div>
            <div className="priceChart" aria-label="Synthetic completed-bar replay chart">
              {priceBars.map((height, index) => <i key={index} style={{ height: `${height}%` }} />)}
              <span className="chartLabel">COMPLETED 5-MINUTE BARS</span>
            </div>
            <div className="featureGrid">
              <div><span>EMA 20 / 50</span><b>666.16 / 662.75</b><small>+0.52% spread</small></div>
              <div><span>RSI · 14</span><b>73.6</b><small>Momentum confirmed</small></div>
              <div><span>SIGNAL</span><b>+0.52</b><small>Threshold +0.45</small></div>
              <div><span>DATA AGE</span><b>8 sec</b><small>Completed bar only</small></div>
            </div>
          </article>

          <article className="criticPanel">
            <div className="panelTitle"><span>03 · AI CRITIC</span><b className={scenario === 'ai_veto' ? 'deny' : 'allow'}>{scenario === 'ai_veto' ? 'VETO' : 'ALLOW'}</b></div>
            <blockquote>{scenario === 'ai_veto'
              ? '“The signal is positive, but RSI is stretched and the evidence does not justify opening risk. Veto.”'
              : '“Trend and momentum agree. The candidate is defined-risk and its invalidation is explicit. I found no evidence-based reason to veto.”'}</blockquote>
            <dl>
              <div><dt>AUTHORITY</dt><dd>Veto only</dd></div>
              <div><dt>CAN CHANGE CONTRACT?</dt><dd>No</dd></div>
              <div><dt>CAN CHANGE SIZE?</dt><dd>No</dd></div>
              <div><dt>FAILURE MODE</dt><dd>VETO</dd></div>
            </dl>
            <p>Invalidated if the completed-bar signal enters neutral or reverses direction.</p>
          </article>
        </div>

        <section className="executionProof" aria-label="Bounded execution lifecycle">
          <div className="proofTitle">
            <div><span className="label">05 · BOUNDED EXECUTION</span><h3>One frozen candidate. One atomic order. One whole-spread exit.</h3></div>
            <b>REPLAY · EXPECTED PAPER PATH</b>
          </div>
          <div className="lifecycle">
            {[
              ['CANDIDATE FROZEN', '7d90a3f1…', true],
              ['AI VERDICT', scenario === 'ai_veto' ? 'VETO' : 'ALLOW', scenario !== 'ai_veto'],
              ['RISK KERNEL', failedGate ? `BLOCK · ${failedGate}` : '32 / 32 PASS', !failedGate],
              ['ATOMIC MLEG', failedGate ? 'NOT CALLED' : 'PREVIEW PAYLOAD', !failedGate],
              ['EXIT SUPERVISOR', failedGate ? 'NO POSITION' : '+35% · −25% · TIME', !failedGate],
            ].map(([title, value, passed]) => (
              <div className={`lifeStep ${hasRun && !passed ? 'blocked' : ''}`} key={String(title)}>
                <i>{hasRun ? (passed ? '✓' : '×') : '·'}</i><span>{title}</span><b>{hasRun ? value : 'WAITING'}</b>
              </div>
            ))}
          </div>
          <p>No broker receipt is fabricated in replay. In armed Paper mode, the passport records the Alpaca order ID, client order ID, status and timestamps.</p>
        </section>

        <div className="tradeStrip">
          <div><span>BUY TO OPEN</span><b>SPY 18 SEP 666 CALL</b><small>Δ +0.55 · OI 1,260</small></div>
          <i>+</i>
          <div><span>SELL TO OPEN</span><b>SPY 18 SEP 671 CALL</b><small>Δ +0.47 · OI 1,410</small></div>
          <div className="tradeMetric"><span>LIMIT DEBIT</span><b>$2.50</b></div>
          <div className="tradeMetric"><span>QUANTITY</span><b>2×</b></div>
          <div className="tradeMetric risk"><span>MAX LOSS</span><b>$500</b></div>
          <div className="tradeMetric reward"><span>MAX PROFIT</span><b>$500</b></div>
        </div>

        <div className="riskHeader">
          <div><span className="label">04 · DETERMINISTIC RISK WALL</span><h3>{rejected ? `Blocked by ${failedGate}` : 'Every failed gate forces ABSTAIN.'}</h3></div>
          <div><b>{rejected ? '11 / 12' : '12 / 12'}</b><span>KEY GATES PASSED<br />32 CHECKS IN ENGINE</span></div>
        </div>
        <div className="gateGrid">
          {gates.map(([name, note, observed, limit], index) => {
            const failed = name === failedGate;
            return (
              <article className={`gate ${failed ? 'failed' : ''}`} key={name}>
                <span>{String(index + 1).padStart(2, '0')}</span><i>{failed ? '×' : '✓'}</i>
                <h3>{name}</h3><p>{note}</p>
                <b>{observed}</b><small>{limit}</small>
              </article>
            );
          })}
        </div>

        <div className="auditBar">
          <div><span>AUDIT RECORD</span><b>REPLAY FIXTURE</b></div>
          <div><span>RECORD HASH</span><code>02d61a…e6eac21</code></div>
          <div><span>PREVIOUS HASH</span><code>GENESIS</code></div>
          <div><span>EXECUTION</span><b>NO ORDER IN REPLAY</b></div>
        </div>
        <div className="verifyBar">
          <div><span>REPLAY FIXTURE INTEGRITY</span><code>SHA256(previous_hash + canonical_payload)</code></div>
          <button type="button" onClick={verifyReplayPassport} disabled={hashStatus === 'checking'}>
            {hashStatus === 'idle' ? 'VERIFY IN BROWSER →' : hashStatus === 'checking' ? 'CHECKING…' : hashStatus === 'valid' ? '✓ HASH MATCHES' : '× TAMPER DETECTED'}
          </button>
        </div>
      </section>

      <section className="evidenceSection">
        <div className="evidenceIntro">
          <span className="eyebrow">DESIGN BOUNDARY</span>
          <h2>A decision record, not a forecast.</h2>
          <p>The model reviews a fixed candidate. It cannot change the order or bypass a failed check.</p>
        </div>
        <div className="evidenceGrid">
          <article><span>AI AUTHORITY</span><b>VETO ONLY</b><p>No order tool. No mutable quantity, contract or price.</p></article>
          <article><span>FAILURE POLICY</span><b>FAIL CLOSED</b><p>Timeout, invalid JSON or changed candidate ID becomes VETO.</p></article>
          <article><span>EXECUTION</span><b>ATOMIC MLEG</b><p>Defined-risk entry and whole-spread exit. No legging.</p></article>
          <article><span>PROOF</span><b>HASH CHAIN</b><p>Recompute integrity from the canonical decision payload.</p></article>
          <article><span>TESTS</span><b>24 / 24</b><p>Safety, audit, payload and failure-path tests passing.</p></article>
          <article><span>DISCLOSURE</span><b>HONEST DEMO</b><p>Replay and Paper evidence are explicitly separated.</p></article>
        </div>
      </section>

      <section className="principles">
        <div className="principleIntro">
          <span className="eyebrow">WHY GLASSBOX</span>
          <h2>The interesting trade is often<br />the one the agent <em>refuses.</em></h2>
        </div>
        <div className="principleGrid">
          <article><span>01</span><h3>Bounded intelligence</h3><p>The model reviews an immutable candidate. It has no execution tool and cannot negotiate with failed gates.</p></article>
          <article><span>02</span><h3>Provable downside</h3><p>Only long options or atomic debit verticals. No naked shorts, 0DTE, market orders, or leg-by-leg spreads.</p></article>
          <article><span>03</span><h3>Honest evidence</h3><p>Every quote carries feed and age. Paper P&amp;L and indicative-data limitations stay visible instead of becoming footnotes.</p></article>
          <article><span>04</span><h3>Replayable decisions</h3><p>Inputs, candidate, critic output, every gate, and order payload are linked in a tamper-evident hash chain.</p></article>
        </div>
      </section>

      <section className="disclosure">
        <b>PAPER-TRADING DISCLOSURE</b>
        <p>This demonstration does not provide investment advice. Paper fills do not model market impact, queue position, latency, slippage, fees, or live liquidity. Basic-plan options data may be indicative rather than OPRA. Short-window P&amp;L does not establish statistical edge.</p>
      </section>

      <footer>
        <div className="brand"><span className="mark">G</span><span>GLASSBOX <b>ALPHA</b></span></div>
        <span>BUILT FOR ALPACA AI TRADING AGENTS HACKATHON · 2026</span>
        <div><a href="https://docs.alpaca.markets/us/docs/options-level-3-trading">ALPACA DOCS</a><a href="https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon">EVENT</a></div>
      </footer>
    </main>
  );
}
