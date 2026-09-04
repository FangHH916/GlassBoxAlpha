# Signal validation report

Run date: 2026-09-03

## Result

The original SPY/QQQ-only validation selected the `trend_pullback` signal with a minimum absolute score of `0.30`. The expanded-universe production update is documented below.

| Segment | Period | Trades | Win rate | Avg. return | Compounded proxy return | Max drawdown | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Training | 2026-05-05 to 2026-07-29 | 45 | 51.11% | +0.0933% | +4.096% | 3.658% | 1.348 |
| Out of sample | 2026-07-29 to 2026-09-02 | 11 | 72.73% | +0.1279% | +1.413% | 0.234% | 4.608 |

The previous production signal (`current_trend`, threshold `0.45`) produced only 11 training trades and one out-of-sample trade. Its training proxy return was -2.057%, so it was rejected.

## Method

- Source: Alpaca IEX adjusted 5-minute regular-session bars.
- Universe: SPY and QQQ, 6,474 bars each.
- Candidate models were defined before inspecting the out-of-sample scores: current trend, slow trend, trend-with-pullback, and mean reversion.
- Thresholds tested: 0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35, 0.40, and 0.45.
- The first 70% of timestamps selected the model and threshold. The last 30% was not used for selection.
- Entry uses the next bar's open, avoiding same-bar look-ahead.
- Each signal is held for 24 bars (120 minutes), with one portfolio position and at most three entries per day.
- Returns are directional returns of the underlying after four basis points of round-trip cost.

Reproduce with:

```powershell
.\.venv\Scripts\python.exe tools\backtest_signal.py --days 120
```

## Expanded liquid-ETF validation

On 2026-09-04, the same walk-forward selector was rerun over SPY, QQQ, IWM, DIA, GLD, TLT, XLF, and SMH. The training segment selected `trend_pullback` with a `0.20` threshold. It produced 172 training signals with a 12.059% compounded underlying proxy return and 4.779% maximum drawdown. The untouched out-of-sample segment produced 75 signals, a 38.67% win rate, a 1.258% compounded proxy return, and a 4.720% maximum drawdown.

Production therefore uses `0.20` and a smaller liquid subset—SPY, QQQ, GLD, and IWM—while preserving the same option liquidity, defined-risk, exposure, loss, drawdown, and daily-trade gates. The lower win rate is reported explicitly; selection was based on the training segment, not the out-of-sample result.

## Important limitation

This is signal validation, not an options-P&L backtest. It does not model option premiums, implied volatility, Greeks, bid/ask spreads, multi-leg fill quality, DeepSeek vetoes, or the live option-chain gates. The free Indicative options feed is derived rather than actual OPRA quotes, so converting these underlying returns into claimed option returns would be misleading. Paper fills also do not establish live execution quality or future profitability.

## Multi-strategy admission

The public Strategy Lab exposes trend-pullback, volatility-expansion, momentum-breakout, and mean-reversion for read-only previews. A strategy does not enter the production `auto` router merely because it exists. On the eight-ETF, 120-day walk-forward rerun, volatility-expansion was rejected: its best training candidates remained negative and the 0.20 threshold produced -8.574% training and -5.595% out-of-sample compounded underlying proxy returns. Production `auto` therefore remains trend-pullback until another strategy passes the same isolated validation rule.
