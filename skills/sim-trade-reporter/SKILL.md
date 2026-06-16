---
name: sim-trade-reporter
description: "Use when adding or writing simulated-trading/backtest strategy code that records initial cash, daily trades, profit, return rate, actual total equity, and generates a JSON trace plus an HTML table and equity/return curve report."
---

# Sim Trade Reporter

## Purpose

Use this skill when a FinTrack/MTF workflow needs simulated-trading or backtest code that records account performance, writes JSON trace files, and produces a portable HTML report. Keep the output as research and operational evidence, not investment advice.

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
2. Fix the simulation initial cash to `10000` unless the caller explicitly overrides it; the reporter must treat `10000` as the default starting capital for every new simulation run.
3. Call `record_daily_report(context)` from `after_trading_end(context)`.
4. Keep only serializable plain dict/list/string/number values in global state. Do not persist JoinQuant order, trade, position, or context objects.
5. After every simulated trade / daily settlement, append the latest position and account snapshot into a JSON file for traceability. The JSON trace must keep the full evolution of cash, position value, total equity, and trade details so later runs can be replayed and compared.
6. Generate both:
   - a JSON source file for traceability;
   - an HTML report with summary cards, daily table, trade detail table, and SVG curves.
7. Report these metrics for each trading day:
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
   - trade details from `get_trades()`;
   - current position snapshot.
8. If the simulation is restarted or resumed, keep the JSON trace append-only by date: replace the same date snapshot instead of duplicating it, but preserve the full historical sequence across runs.

## Implementation Template

For the complete copyable simulated-trading strategy helper, read:

- `references/joinquant-sim-trade-report-template.md`

Use the template directly unless the caller needs a different file name, fields, chart series, or report style.

## Output Rules

When generating strategy code:

- Include `set_option('use_real_price', True)` unless the existing strategy intentionally uses adjusted prices.
- Keep `after_trading_end(context)` idempotent for a single day: replace the existing date row rather than append duplicates.
- Escape HTML content before writing it into tables.
- Use plain SVG for curves so the report works without external JavaScript/CDN access.
- Append every simulated trade / daily settlement result to a JSON file so the position and cash evolution can be replayed later.
- The JSON trace must always treat `10000` as the default initial capital unless the caller overrides it explicitly.
- State clearly that simulated trading and backtest results may differ because different backtest/simulation engines can have matching, volume, replacement-code, pause/restart, and runtime differences.
