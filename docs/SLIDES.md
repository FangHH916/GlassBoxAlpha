# Slide Deck Outline

## 1. GlassBox Alpha

An AI options agent you can audit before it trades.

Visual: generated cover card.

## 2. The authority problem

- LLMs are probabilistic.
- Orders are irreversible financial actions.
- A prompt is not a risk control.

## 3. Our inversion

Code constructs and freezes the trade. AI may only `ALLOW` or `VETO`. Deterministic risk code retains final authority.

## 4. Decision pipeline

Alpaca Data → Completed Bars → Candidate Factory → AI Critic → 29 Risk Gates → Alpaca CLI → Reconciliation → Exit Supervisor.

## 5. Defined-risk strategy

- SPY / QQQ only.
- Bull call or bear put debit spread.
- 7–21 DTE.
- 0.50% equity maximum loss.
- Atomic MLeg entry and exit.

## 6. The risk wall

Show a clean Trade Passport and the stale-quote failure beside it.

## 7. Alpaca-native implementation

- Trading API and paper clock/account.
- Options contracts, chain, Greeks and positions.
- Official CLI for MLeg orders.
- Feed disclosure: Indicative vs OPRA.

## 8. Auditability

Each decision records evidence, immutable candidate, AI verdict, observed/limit/pass for every gate, payload, result, and previous hash.

## 9. Live demo

Run Clean Market, then Stale Quote. Emphasize `NO ORDER SENT`.

## 10. What comes next

- WebSocket fill reconciliation and latency metrics.
- Conservative shadow P&L beside broker P&L.
- More replay fixtures and adversarial critic evals.
- Maintain the same rule: AI can reduce authority, never expand it.
