# Build-in-Public Drafts

Replace bracketed links before posting. Attach screenshots that do not show credentials or the full account ID. Tag the official current accounts shown in the event instructions.

## Post 1 — Design thesis

Most AI trading demos ask: “Can the model find a trade?”

For the Alpaca AI Trading Agents Hackathon, we started with a different question: “What authority should a probabilistic model never have?”

GlassBox Alpha freezes the symbol, contracts, size, limit and max loss in deterministic code. AI gets one power: ALLOW or VETO. It has no order tool and cannot negotiate with a failed risk gate.

Build log: [PUBLIC REPO]

#AlpacaHackathon #AIagents #OptionsTrading #BuildInPublic

## Post 2 — Failure is the feature

Today we deliberately fed GlassBox Alpha a stale option quote.

Result: ABSTAIN. No order sent. The Trade Passport shows the exact observed quote age, allowed limit, failed gate and audit hash.

Risk is not a paragraph in our README—it is the product's main interaction.

Try the replay: [PUBLIC DEMO]

#AlpacaHackathon #RiskManagement #FinTech #BuildInPublic

## Post 3 — Alpaca integration

GlassBox Alpha now constructs and closes defined-risk option spreads as atomic Alpaca MLeg limit orders.

- `alpaca-py` for account, clock, completed bars, option chain and positions
- official Alpaca CLI for paper execution
- stable client order IDs
- whole-spread exits only
- Indicative vs OPRA feed shown in the UI

No live endpoint exists in the project.

[PUBLIC REPO]

#AlpacaHackathon #AlgorithmicTrading #AIagents

