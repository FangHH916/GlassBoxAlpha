'use client';

import { useMemo, useState } from 'react';

type Scenario = 'clean' | 'stale' | 'wide';

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

const sleep = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export default function Home() {
  const [scenario, setScenario] = useState<Scenario>('clean');
  const [step, setStep] = useState(0);
  const [running, setRunning] = useState(false);
  const [hasRun, setHasRun] = useState(false);

  const failedGate = scenario === 'stale' ? 'Quote freshness' : scenario === 'wide' ? 'Liquidity' : null;
  const approved = hasRun && !failedGate;
  const rejected = hasRun && Boolean(failedGate);

  const gates = useMemo(() => baseGates.map((gate) => {
    const item = [...gate];
    if (gate[0] === 'Quote freshness' && scenario === 'stale') item[2] = '94 sec';
    if (gate[0] === 'Liquidity' && scenario === 'wide') item[2] = '18.4%';
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
            <span>{running ? 'RUNNING 29 RISK GATES' : 'RUN DECISION REPLAY'}</span><b>{running ? '···' : '→'}</b>
          </button>
          <span className="runHint">No credentials. No orders.<br />Deterministic judge demo.</span>
        </div>
      </section>

      <section className="ticker" aria-label="System summary">
        <div><span>MODE</span><b>REPLAY / PAPER-LOCKED</b></div>
        <div><span>ACCOUNT BASELINE</span><b>$100,000.00</b></div>
        <div><span>OPTION LEVEL</span><b>LEVEL 3 · MLEG</b></div>
        <div><span>DATA FEED</span><b>INDICATIVE · DISCLOSED</b></div>
        <div><span>OPEN RISK</span><b>$0 · 0.00%</b></div>
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
            ['04', 'RISK KERNEL', '29 hard gates'],
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
            <div className="panelTitle"><span>03 · AI CRITIC</span><b className="allow">ALLOW</b></div>
            <blockquote>“Trend and momentum agree. The candidate is defined-risk and its invalidation is explicit. I found no evidence-based reason to veto.”</blockquote>
            <dl>
              <div><dt>AUTHORITY</dt><dd>Veto only</dd></div>
              <div><dt>CAN CHANGE CONTRACT?</dt><dd>No</dd></div>
              <div><dt>CAN CHANGE SIZE?</dt><dd>No</dd></div>
              <div><dt>FAILURE MODE</dt><dd>VETO</dd></div>
            </dl>
            <p>Invalidated if the completed-bar signal enters neutral or reverses direction.</p>
          </article>
        </div>

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
          <div><b>{rejected ? '11 / 12' : '12 / 12'}</b><span>KEY GATES PASSED<br />29 CHECKS IN ENGINE</span></div>
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
          <div><span>AUDIT CHAIN</span><b>VALID · 7 RECORDS</b></div>
          <div><span>RECORD HASH</span><code>8d7a9f…c41e</code></div>
          <div><span>PREVIOUS HASH</span><code>0fa291…d73b</code></div>
          <div><span>EXECUTION</span><b>NO ORDER IN REPLAY</b></div>
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
