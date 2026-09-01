# Judge Readiness Scorecard

Use this as the final submission gate. Do not claim evidence that is not visible to a judge.

## Must be visible in the first 30 seconds

- One-sentence authority thesis: AI can veto but cannot change or execute a trade.
- Candidate ID and hash exist before the AI verdict.
- Paper-only status is visible.
- Maximum loss is shown in dollars before any execution step.

## Technical proof

- Public repository opens without authentication.
- Public demo opens without credentials.
- Fifteen tests pass from a clean checkout.
- One sanitized Alpaca Paper order ID matches a Trade Passport.
- One complete position exit or a clearly labeled recorded exit fixture is shown.
- Browser hash verification and CLI chain verification both pass.
- A failed AI critic and a failed deterministic gate both produce no order.

## Honest evidence boundary

- Replay, preview and real Paper events use distinct labels.
- No simulated order ID is presented as a broker receipt.
- Account ID and API credentials are masked.
- Indicative versus OPRA data is disclosed.
- Paper performance is not described as expected live performance.

## Submission assets

- Public GitHub URL
- Public deployed demo URL
- Video under five minutes and 300 MB
- Slide deck
- Cover image
- One-page write-up
- Fresh dedicated `$100,000` competition account ID

## Final narrative test

A judge should be able to answer all four questions after two minutes:

1. What can the AI do? Veto only.
2. What can it never do? Mutate or execute the candidate.
3. What stops an unsafe order? Either independent veto layer.
4. How can I verify the claim? Recompute the Trade Passport hash chain.
