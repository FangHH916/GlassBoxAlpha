# Submission Copy

## Title

GlassBox Alpha: Verifiable AI Options Agent

## Short description

GlassBox Alpha is a paper-only autonomous options agent that lets AI veto a defined-risk SPY or QQQ trade, while deterministic code controls construction, risk, execution, and the audit trail.

## Team recruitment description

Building an autonomous AI options trading agent with explainable decisions and strict risk controls using Alpaca. Looking for teammates skilled in quantitative trading, Python, AI agents, or frontend development.

## Tags

`Alpaca` · `Options` · `AI Agents` · `Algorithmic Trading` · `Risk Management` · `OpenAI` · `Python` · `TypeScript` · `FinTech`

## Long description

GlassBox Alpha is a paper-only autonomous options trading agent built on Alpaca. It solves a specific problem in agentic trading: an AI model should contribute judgment without having unrestricted control over financial actions.

Completed five-minute Alpaca bars feed a deterministic strategy engine that constructs one exact SPY or QQQ trade. The code fixes the contracts, expiry, quantity, limit price, and maximum loss before the AI sees the proposal. A structured AI critic may only return ALLOW or VETO. It cannot change the trade or submit an order, and any timeout, invalid response, altered candidate ID, or unsupported evidence fails closed.

Before execution, an independent 32-check risk kernel recomputes the trade economics and verifies account identity, paper mode, market time, option structure, exposure, DTE, quote freshness, liquidity, position limits, drawdown, and idempotency. A failed check produces ABSTAIN. Approved orders can be submitted as atomic multi-leg limit orders through the official Alpaca CLI, while a deterministic supervisor manages whole-position exits.

Every decision creates a hash-chained Trade Passport containing the market evidence, AI verdict, risk observations, order payload, and result. Judges can inspect credential-free replay scenarios for approval, AI veto, stale quotes, and excessive spreads. The result is not another prediction bot, but a verifiable decision system in which probabilistic AI advises and deterministic controls retain authority.

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
