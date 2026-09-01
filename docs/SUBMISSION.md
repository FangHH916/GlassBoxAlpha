# Submission Copy

## Title

GlassBox Alpha — An AI Options Agent You Can Audit Before It Trades

## Short description

A paper-only autonomous options agent where AI can veto, but never change, a defined-risk trade.

## Team recruitment description

Building an autonomous AI options trading agent with explainable decisions and strict risk controls using Alpaca. Looking for teammates skilled in quantitative trading, Python, AI agents, or frontend development.

## Tags

`Alpaca` · `Options` · `AI Agents` · `Algorithmic Trading` · `Risk Management` · `OpenAI` · `Python` · `TypeScript` · `FinTech`

## Long description

Most trading agents give an LLM too much authority: the model can invent a ticker, change position size, or talk its way around a guardrail. GlassBox Alpha inverts that design.

Deterministic code reads completed five-minute Alpaca bars, constructs one exact SPY or QQQ defined-risk option candidate, fixes its contracts, size, price and maximum loss, and hashes it. An AI critic then receives only veto authority: `ALLOW` or `VETO`. It cannot change the candidate and it has no order tool. Invalid output, unavailable models, invented evidence or a changed candidate ID all fail closed.

An independent 29-check risk kernel then validates paper environment, dedicated competition account, market time, candidate identity, signal strength, option level, daily loss, peak drawdown, total exposure, maximum loss, defined-risk structure, DTE, quote freshness, liquidity and idempotency. Any failure becomes an explainable `ABSTAIN` and no order is sent.

Approved entries use the official Alpaca CLI to submit one atomic MLeg limit order to the paper endpoint. A deterministic supervisor reconciles positions and closes the whole spread at profit target, loss limit, signal invalidation, maximum holding time or the closing-time buffer. Every event becomes a hash-chained Trade Passport containing evidence, AI verdict, all observed limits, order payload and result.

The public judge demo requires no credentials. It includes clean, stale-quote and wide-spread replays so judges can see the agent refuse unsafe trades instead of merely reading about risk controls.

## One-page write-up

### AI logic

GlassBox Alpha separates candidate generation from AI judgment. Completed five-minute bars produce a bounded signal from EMA 20/50 alignment, five-bar momentum and RSI. Code—not AI—chooses SPY/QQQ, option type, same-expiry contracts, quantity and limit debit. The AI critic receives an immutable candidate plus enumerated evidence IDs through strict structured output. It may only return `ALLOW` or `VETO`, risk flags, a short thesis and an invalidation condition. It cannot call execution tools. Model timeout, invalid JSON, candidate mutation or fabricated evidence produces `VETO`.

### Risk gates

The deterministic risk kernel is evaluated after the AI and immediately before execution. Default limits are 0.50% equity maximum loss per entry, 1.00% total option exposure, 1.25% daily loss, 3.00% peak drawdown, one open structure, three contracts and three entries per day. Only long options or atomic call/put debit verticals are accepted. Contracts must be 7–21 DTE, active, tradable and liquid, with two-sided fresh quotes, open interest at least 500 and spread no wider than 12%. The system blocks 0DTE, naked shorts, market orders, credit trades, extended hours and leg-by-leg spreads. A persistent kill switch and candidate-hash idempotency provide operational safety.

### Alpaca infrastructure

`alpaca-py` reads the paper account, market clock, completed IEX bars, option contract metadata, chain snapshots, Greeks and current positions. The authenticated account ID must match the configured fresh competition account and its creation time must follow the event start. The default execution backend is the official Alpaca CLI, called without a shell using `alpaca api POST /v2/orders`. It receives paper credentials only in the child process; live mode is removed and is not implemented elsewhere. Level 3 entries and exits are single atomic MLeg limit orders with explicit position intents and stable client order IDs. The UI discloses whether data is Indicative or OPRA and warns that paper P&L is not live fill evidence.

### Originality and practical value

The product's primary output is not a prediction—it is a verifiable decision boundary. Trade Passports expose exactly why a trade was allowed or refused, while their SHA-256 chain makes silent history edits detectable. The approach is useful wherever probabilistic AI proposes financial action but deterministic controls must retain authority.

## Submission assets

- Cover/social image: `site/public/og.png` (1200×630)
- Demo video script: `docs/DEMO_SCRIPT.md`
- Slide outline: `docs/SLIDES.md`
- Architecture: `docs/ARCHITECTURE.md`
- Public repository URL: **add after publishing**
- Public demo URL: **add after deployment**
- Alpaca paper account ID: **add from the fresh competition account**
