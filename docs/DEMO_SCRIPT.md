# 2-Minute Demo Script

## 0:00–0:15 — Problem

“Most AI trading demos give the model authority to invent the trade. GlassBox Alpha gives AI only one power: the power to say no.”

Show the hero and `PAPER ONLY · REPLAY` lock.

## 0:15–0:35 — Immutable candidate

Run **Clean Market**. Follow the pipeline from completed bars to a code-generated SPY bull call debit spread. Point out that symbol, expiry, strikes, quantity, limit debit and maximum loss are already fixed before the AI sees it.

## 0:35–0:50 — Veto-only AI

Show the critic panel:

- authority: veto only;
- cannot change contract;
- cannot change size;
- failure mode: veto.

“The model has no order tool. A timeout or malformed response becomes VETO.”

## 0:50–1:15 — Risk wall

Show the exact `$500` maximum loss and 12 visible key gates. Explain that the Python engine evaluates 29 checks, including account identity, market time, daily loss, drawdown, DTE, liquidity and quote age.

## 1:15–1:35 — Prove refusal

Switch to **Stale Quote**, run again, and show `ABSTAIN · NO ORDER SENT` plus the red Quote Freshness gate. Repeat quickly with **Wide Spread** if time permits.

“Risk is not a paragraph in our README. It is the main interaction.”

## 1:35–1:50 — Alpaca execution

Show the terminal running:

```text
glassbox-alpha check
glassbox-alpha run --symbol SPY --compact
```

Explain that approved paper entries use the official Alpaca CLI as one atomic MLeg limit order, with `alpaca-py` for data and reconciliation. Do not expose credentials or a full account ID.

## 1:50–2:00 — Audit and close

Show the audit hash bar and run `glassbox-alpha verify-audit`. End with:

“GlassBox Alpha does not ask you to trust an agent. It shows you exactly why the agent was allowed to act.”

## Recording checklist

- Keep the final video below five minutes and 300 MB.
- Record at 1080p with browser zoom set so the full passport is readable.
- Hide `.env`, keys, full account ID and personal notifications.
- Use a paper account only.
- Include the public demo and GitHub URLs in the video description.
