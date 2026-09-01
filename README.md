# GlassBox Alpha

> An AI options agent you can audit before it trades.

GlassBox Alpha is a paper-only autonomous options agent built for the **Alpaca AI Trading Agents Hackathon — Options Alpha Agents track**. It constructs defined-risk SPY/QQQ option candidates in deterministic code, gives an AI critic veto-only authority, reruns every hard risk gate, and executes approved orders through the official Alpaca CLI or `alpaca-py`.

The central idea is simple: **AI may say no, but it cannot change the trade.**

## Why it is different

Most trading-agent demos let a model invent a ticker, price, or position size. GlassBox Alpha separates intelligence from authority:

```text
Alpaca market data
        ↓
completed-bar feature engine
        ↓
deterministic candidate factory
        ↓
AI critic (ALLOW / VETO only)
        ↓
32-check deterministic risk kernel
        ↓
official Alpaca CLI → paper endpoint only
        ↓
fill reconciliation + whole-spread exit supervisor
        ↓
hash-chained Trade Passport
```

- The AI cannot create symbols, strikes, expiries, quantities, or prices.
- A model timeout, invalid schema, fabricated evidence ID, or changed candidate ID becomes `VETO`.
- Only long options and atomic call/put debit verticals are allowed.
- Live trading is intentionally absent from the codebase.
- Replay and preview cannot submit orders.
- An unknown broker response engages the kill switch and requires reconciliation before another entry.
- Every decision persists its inputs, critic result, risk checks, result, and previous-record hash.

## Competition compliance

| Requirement | Implementation |
| --- | --- |
| Autonomous AI trading agent | `watch` runs signal, critic, risk, entry and exit supervision cycles |
| Alpaca Trading API | `AlpacaBroker` reads account, clock, bars, options contracts, chain and positions |
| Official MCP or CLI | Official Alpaca CLI is the default order backend; SDK is an explicit fallback |
| Options in every strategy | Bull call / bear put debit spreads; Level 2 falls back to a long option |
| Paper-only | `TradingClient(..., paper=True)`; no live URL or live mode exists |
| Fresh $100k competition account | Account ID match, creation-time check and explicit setup checklist |
| Explainable risk gates | Every check exposes observed value, limit, pass/fail and detail |
| Public demo | `site/` contains a credential-free interactive decision replay |
| Open source | MIT License |

The submission deadline is **2026-09-04 15:00 UTC / 23:00 China Standard Time**. See [docs/RULES_CHECKLIST.md](docs/RULES_CHECKLIST.md).

## Safe quick start

Python 3.11+ is required. Replay needs no credentials and never connects to Alpaca.

```powershell
cd D:\Python\GlassBoxAlpha
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env

glassbox-alpha run --symbol SPY --compact
glassbox-alpha verify-audit
```

Expected replay result:

```json
{
  "status": "approved_preview",
  "symbol": "SPY",
  "risk": "All gates passed."
}
```

Run the credential-free decision replay:

```powershell
cd site
npm install
npm run dev
```

Open `http://localhost:3000`. Switch among Clean Market, Stale Quote, Wide Spread, and AI Veto to inspect approval and fail-closed outcomes.

## Connect read-only Alpaca paper data

1. During the competition, create a **new paper account dedicated only to this event**. Do not reuse the account used by another bot.
2. Confirm its starting balance is exactly `$100,000`.
3. Generate new paper API credentials.
4. Copy `.env.example` to `.env` and set:

```env
BROKER_MODE=alpaca
EXECUTION_MODE=preview
APCA_API_KEY_ID=your-paper-key
APCA_API_SECRET_KEY=your-paper-secret
COMPETITION_ACCOUNT_ID=the-exact-paper-account-id
```

5. Run the read-only safety check:

```powershell
glassbox-alpha check
```

Use `glassbox-alpha check --show-account-id` only when you explicitly need the full ID for the submission form. Normal output masks it.

## Install and verify the official Alpaca CLI

GlassBox Alpha uses the sponsor's official CLI for paper order submission. Install it from the [official Alpaca CLI repository](https://github.com/alpacahq/cli):

```powershell
go install github.com/alpacahq/cli/cmd/alpaca@latest
alpaca --help-all
```

The adapter calls `alpaca api POST /v2/orders` with a single atomic MLeg JSON payload. It sets paper credentials only for that child process, removes `ALPACA_LIVE_TRADE`, uses a unique `client_order_id`, and never invokes a shell.

## Optional OpenAI veto critic

Replay uses a deterministic critic so judges can run it without secrets. To use an OpenAI model as the veto-only critic:

```env
USE_OPENAI=true
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-5-mini
```

The integration uses the Responses API with strict JSON Schema. The only accepted fields are candidate ID, `ALLOW`/`VETO`, risk flags, supplied evidence IDs, thesis, and invalidation. The model has no order tool. Network or parsing failures return `VETO`.

## Unlock paper execution

Do this only after preview output, the account ID, option level and CLI have been checked. Four independent conditions are required:

```env
BROKER_MODE=alpaca
EXECUTION_MODE=paper
ALLOW_PAPER_ORDERS=true
PAPER_ORDER_CONFIRMATION=I_UNDERSTAND_PAPER_ONLY
COMPETITION_ACCOUNT_ID=the-exact-authenticated-account-id
```

Then run one cycle:

```powershell
glassbox-alpha run --symbol SPY --compact
```

Or run autonomous monitoring:

```powershell
glassbox-alpha watch --interval 300
```

Every watch iteration first reconciles open option positions and evaluates exit policy, then scans configured underlyings. Entry is limited to three trades per day and one open option structure.

## Entry policy

- Only completed five-minute bars are used.
- EMA 20/50, five-bar momentum and RSI create a bounded directional score.
- `abs(signal) >= 0.45` and deterministic confidence `>= 0.64` are required.
- SPY and QQQ only by default.
- 7–21 DTE; target long delta `0.55`, short delta `0.30`.
- Each leg needs bid/ask, open interest `>= 500`, spread `<= 12%`, and a fresh timestamp.
- Level 3 uses one atomic MLeg debit spread. Level 2 may only buy a single long option at half risk budget.

## Hard risk limits

- Maximum loss per entry: `0.50%` of equity.
- Total open option risk: `1.00%` of equity.
- Daily loss circuit: `1.25%`.
- Peak drawdown circuit: `3.00%`.
- Maximum open structures: `1`.
- Maximum contracts: `3`.
- Maximum new entries per day: `3`.
- Minimum 45 minutes before the regular close.
- No 0DTE, naked short, credit strategy, market order, extended-hours order, or leg-by-leg vertical.
- Persistent kill switch blocks every new candidate.

```powershell
glassbox-alpha kill
glassbox-alpha resume
```

`resume` only releases the kill switch. It cannot change the process's execution mode or unlock paper orders.

## Exit supervisor

Whole structures are closed atomically—never one leg at a time—when any of these occurs:

- spread return reaches `+35%`;
- spread return reaches `-25%`;
- holding time reaches 120 minutes;
- 35 minutes remain before close;
- deterministic signal becomes neutral or reverses.

For MLeg closes, the adapter reverses both position intents and expresses a net credit as a negative Alpaca MLeg limit price. `supervise` only reduces existing risk:

```powershell
glassbox-alpha supervise
```

## Trade Passports

Decisions are stored in SQLite using a SHA-256 hash chain. The broker remains the source of truth for positions; the local ledger is an audit record, not a substitute for reconciliation.

```powershell
glassbox-alpha verify-audit
glassbox-alpha passport <run-id>
glassbox-alpha serve --port 8787
```

Local API routes:

- `GET /health`
- `GET /api/dashboard`
- `GET /api/passports/{run_id}`
- `POST /api/cycle` with `{"symbol":"SPY"}`
- `POST /api/kill-switch` with `{"engaged":true}`

The local API binds to `127.0.0.1` by default and cannot alter execution mode.
It refuses to start while the paper-order interlock is unlocked.

## Tests

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
cd site
npm run build
```

Tests cover paper-only configuration, the execution interlock, candidate construction, Level 2 fallback, every clean risk gate, stale quotes, kill switch persistence, atomic entry and close payloads, OpenAI failure-to-veto behavior, preview non-execution, and Trade Passport tamper detection.

## Important limitations

- This project does not provide investment advice or promise profit.
- Alpaca paper trading does not model market impact, queue position, latency, realistic partial liquidity, all fees, or live slippage.
- Basic-plan options data may use Alpaca's Indicative Feed rather than OPRA. Paper matching and the strategy's observed feed can differ.
- A short hackathon P&L window cannot establish a statistically reliable edge.
- The participant must personally create and preserve the fresh competition paper account, supply its ID, verify tax/eligibility requirements, publish the repository, and submit the final links.

Official sources and known rule ambiguities are recorded in [docs/RULES_CHECKLIST.md](docs/RULES_CHECKLIST.md).

Before publishing, use [docs/JUDGE_SCORECARD.md](docs/JUDGE_SCORECARD.md) to separate implemented safeguards from evidence that still requires a real competition Paper account.
