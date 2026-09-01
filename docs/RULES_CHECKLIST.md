# Competition Rules Checklist

Verified for the Alpaca AI Trading Agents Hackathon as of 2026-09-01.

## Hard requirements

- [x] Build an autonomous AI trading agent.
- [x] Use Alpaca Trading API.
- [x] Use the official Alpaca MCP Server or Alpaca CLI; this project uses the CLI.
- [x] Every strategy incorporates options.
- [x] Paper trading only.
- [ ] Participant creates a brand-new, competition-dedicated Alpaca paper account.
- [ ] Account starts at exactly `$100,000`.
- [ ] Participant adds the exact Alpaca account ID to `.env` and the submission.
- [x] MIT License and open-source-ready repository.

## Schedule

- Start: 2026-08-28 15:00 UTC.
- Submission closes: 2026-09-04 15:00 UTC.
- China Standard Time deadline: 2026-09-04 23:00.
- US Eastern Daylight Time deadline: 2026-09-04 11:00.
- Review is asynchronous; there is no scheduled live demo or pitch session.

Sources: [event page](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon), [live dashboard](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon/live).

## Submission package

- [x] Title, short and long descriptions.
- [x] Technology/category tags.
- [x] 1200×630 cover image.
- [x] Under-five-minute video script.
- [x] Slide outline.
- [x] Interactive replay source.
- [x] Generate final narrated video (`output/submission/GlassBox-Alpha-Video-Presentation.mp4`).
- [x] Export final slides (`output/submission/GlassBox-Alpha-Slides.pdf`).
- [ ] Upload the final video and slide PDF to the submission form.
- [ ] Publish public GitHub repository and paste URL.
- [ ] Deploy the interactive replay and paste its URL if the form requests one.
- [ ] Paste fresh Alpaca paper account ID.
- [x] One-page AI logic / risk gates / Alpaca implementation write-up.

General submission guidance: [lablab hackathon guidelines](https://lablab.ai/ai-articles/hackathon-guidelines).

## Alpaca facts implemented

- Paper base URL and credentials are distinct from live.
- New paper accounts default to `$100,000`.
- Options are paper-enabled; Level 3 supports atomic multi-leg orders.
- Basic options data may be Indicative; full OPRA requires the applicable plan.
- Paper fills do not model all live execution effects.

Sources: [paper trading](https://docs.alpaca.markets/us/docs/paper-trading), [options trading](https://docs.alpaca.markets/us/docs/options-trading), [Level 3 multi-leg options](https://docs.alpaca.markets/us/docs/options-level-3-trading), [market-data plans](https://docs.alpaca.markets/us/docs/about-market-data-api), [Alpaca CLI](https://docs.alpaca.markets/us/docs/alpacas-cli).

## Items to confirm in the event Discord

- Exact P&L calculation and whether all positions must be flat at deadline.
- Weight of P&L, technology, originality and presentation criteria.
- Exact value of each Social Engagement Award.
- Whether account creation must occur strictly after kickoff; this project enforces that conservative interpretation for paper execution.
