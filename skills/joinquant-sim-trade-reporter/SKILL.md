---
name: joinquant-sim-trade-reporter
description: "Use when adding or writing JoinQuant simulated-trading/backtest strategy code that records initial cash, daily trades, profit, return rate, actual total equity, and generates an HTML table plus an equity/return curve report."
---

# JoinQuant Sim Trade Reporter

## Purpose

Use this skill when a FinTrack/MTF workflow needs JoinQuant simulated-trading or backtest code that records account performance and produces a portable HTML report. Keep the output as research and operational evidence, not investment advice.

Primary JoinQuant API source:

- `https://www.joinquant.com/help/api/help#name:api`

Relevant JoinQuant primitives:

- `initialize(context)`: capture `context.portfolio.starting_cash` once.
- `after_trading_end(context)`: record daily snapshots after orders are matched.
- `get_trades()`: get all trade records for the current day.
- `context.portfolio.starting_cash`: initial cash.
- `context.portfolio.total_value`: actual account equity.
- `context.portfolio.available_cash`: available cash.
- `context.portfolio.positions_value`: position value.
- `context.portfolio.returns`: cumulative return.
- `write_file(path, content)`: write report files into JoinQuant research files.

## Workflow

1. Add the reporter bootstrap in `initialize(context)`.
2. Call `record_daily_report(context)` from `after_trading_end(context)`.
3. Keep only serializable plain dict/list/string/number values in global state. Do not persist JoinQuant order, trade, position, or context objects.
4. Generate both:
   - a JSON source file for traceability;
   - an HTML report with summary cards, daily table, trade detail table, and SVG curves.
5. Report these metrics for each trading day:
   - date;
   - initial cash;
   - actual total equity;
   - available cash;
   - position value;
   - daily profit;
   - cumulative profit;
   - daily return rate;
   - cumulative return rate;
   - trade count;
   - trade details from `get_trades()`.

## Implementation Template

For the complete copyable JoinQuant strategy helper, read:

- `references/joinquant-sim-trade-report-template.md`

Use the template directly unless the caller needs a different file name, fields, chart series, or report style.

## Output Rules

When generating strategy code:

- Include `set_option('use_real_price', True)` unless the existing strategy intentionally uses adjusted prices.
- Keep `after_trading_end(context)` idempotent for a single day: replace the existing date row rather than append duplicates.
- Escape HTML content before writing it into tables.
- Use plain SVG for curves so the report works without external JavaScript/CDN access.
- State clearly that simulated trading and backtest results may differ because JoinQuant documents matching, volume, replacement-code, pause/restart, and runtime differences between both modes.
