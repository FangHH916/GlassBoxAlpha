# Architecture and Safety Invariants

## Runtime flow

```text
BOOT
  ├─ load immutable startup mode
  ├─ open local audit ledger
  └─ authenticate paper-only broker
       ↓
RECONCILE
  ├─ account + clock
  ├─ orders + option positions
  └─ deterministic exit policy
       ↓
SCAN
  ├─ completed 5-minute bars
  ├─ feature score
  └─ deterministic candidate
       ↓
CRITIQUE
  └─ structured ALLOW/VETO; no tools
       ↓
RISK
  └─ all checks must pass
       ↓
PREVIEW or PAPER SUBMIT
  └─ one idempotent atomic limit order
       ↓
TRADE PASSPORT
  └─ append to hash chain
```

## Safety invariants

1. No code path creates a live Alpaca client or live endpoint.
2. Preview never calls `submit`.
3. Paper entry requires Alpaca mode, paper execution mode, opt-in boolean, exact confirmation phrase, and matching configured account ID.
4. Any failed risk check sets approved quantity to zero.
5. The AI candidate ID must exactly match the immutable code-generated ID.
6. AI errors and schema failures are vetoes.
7. A submitted entry uses a stable client order ID derived from the candidate.
8. A debit vertical opens and closes as one MLeg; it is never intentionally legged.
9. A close may reduce risk even while the new-entry kill switch is engaged, but it still requires the paper execution interlock.
10. The broker is the source of truth for positions after every restart.
11. Stored account baselines and high-water marks are namespaced by the masked account identity.
12. Exit automation requires exact contract symbols, directions, and quantities.
13. Maximum loss and spread payoff are recomputed independently before approval.
14. An ambiguous entry or exit response engages the kill switch and requires broker reconciliation.
15. The local control API cannot start while paper-order execution is unlocked.

## Components

- `broker.py`: Alpaca Data/Trading clients, official CLI execution, replay broker.
- `indicators.py`: completed-bar features.
- `strategy.py`: deterministic thesis, contract selection and bounded sizing.
- `critic.py`: deterministic replay critic and strict OpenAI veto critic.
- `risk.py`: independent hard gates.
- `engine.py`: orchestration, reconciliation and exit policy.
- `audit.py`: SQLite Trade Passports and SHA-256 chain.
- `server.py`: local API with immutable execution mode.
- `site/`: credential-free public replay experience.

## Threat model

- **Prompt injection:** no untrusted news is currently passed; candidate fields are serialized as data and model authority is schema-limited.
- **Model mutation:** exact candidate ID and evidence allowlist are revalidated.
- **Duplicate submission:** proposal hash becomes `client_order_id`; prior paper submission blocks reuse.
- **Wrong account:** authenticated account ID and account creation timestamp are checked.
- **Secret disclosure:** public site is replay-only; local API masks account ID; `.env` and databases are ignored.
- **Partial/external position changes:** supervisor refuses to manufacture a closing vertical when only part of the expected structure is present.
- **Audit tampering:** each record hash commits to the prior hash and canonical JSON payload.
