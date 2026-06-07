# JoinQuant Sim Trade Report Template

Use this helper inside JoinQuant strategy code. It records initial cash, each day's trade results, daily/cumulative profit, daily/cumulative return, actual account equity, and writes an HTML report with tables and SVG curves.

```python
# -*- coding: utf-8 -*-
import json


def initialize(context):
    set_option('use_real_price', True)
    g.report_rows = []
    g.report_trades = []
    g.initial_cash = float(context.portfolio.starting_cash)
    g.report_json_path = 'mtf_sim_trade_report.json'
    g.report_html_path = 'mtf_sim_trade_report.html'

    # 用户原有初始化逻辑放在这一行之后。


def after_trading_end(context):
    record_daily_report(context)

    # 用户原有盘后逻辑放在这一行之后。


def record_daily_report(context):
    today = context.current_dt.strftime('%Y-%m-%d')
    portfolio = context.portfolio
    total_value = float(portfolio.total_value)
    available_cash = float(portfolio.available_cash)
    positions_value = float(portfolio.positions_value)
    initial_cash = float(getattr(g, 'initial_cash', portfolio.starting_cash))

    previous_value = initial_cash
    if getattr(g, 'report_rows', None):
        previous_value = float(g.report_rows[-1]['total_value'])

    daily_profit = total_value - previous_value
    cumulative_profit = total_value - initial_cash
    daily_return_rate = daily_profit / previous_value if previous_value else 0.0
    cumulative_return_rate = cumulative_profit / initial_cash if initial_cash else 0.0

    trades = serialize_trades(get_trades(), today)
    replace_row_for_date({
        'date': today,
        'initial_cash': initial_cash,
        'total_value': total_value,
        'available_cash': available_cash,
        'positions_value': positions_value,
        'daily_profit': daily_profit,
        'cumulative_profit': cumulative_profit,
        'daily_return_rate': daily_return_rate,
        'cumulative_return_rate': cumulative_return_rate,
        'trade_count': len(trades),
    })
    replace_trades_for_date(today, trades)

    payload = {'rows': g.report_rows, 'trades': g.report_trades}
    write_file(g.report_json_path, json.dumps(payload, ensure_ascii=False, indent=2))
    write_file(g.report_html_path, render_report_html(g.report_rows, g.report_trades))
    log.info('MTF模拟交易报告已更新: {0}, {1}'.format(g.report_json_path, g.report_html_path))


def serialize_trades(trades, date_text):
    rows = []
    for trade_id, trade in trades.items():
        price = float(getattr(trade, 'price', 0) or 0)
        amount = float(getattr(trade, 'amount', 0) or 0)
        commission = float(getattr(trade, 'commission', 0) or 0)
        rows.append({
            'date': date_text,
            'trade_id': str(getattr(trade, 'trade_id', trade_id)),
            'order_id': str(getattr(trade, 'order_id', '')),
            'security': str(getattr(trade, 'security', '')),
            'amount': amount,
            'price': price,
            'value': amount * price,
            'commission': commission,
        })
    return rows


def replace_row_for_date(row):
    g.report_rows = [item for item in getattr(g, 'report_rows', []) if item['date'] != row['date']]
    g.report_rows.append(row)
    g.report_rows.sort(key=lambda item: item['date'])


def replace_trades_for_date(date_text, trades):
    g.report_trades = [item for item in getattr(g, 'report_trades', []) if item['date'] != date_text]
    g.report_trades.extend(trades)
    g.report_trades.sort(key=lambda item: (item['date'], item['trade_id']))


def render_report_html(rows, trades):
    latest = rows[-1] if rows else {}
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>MTF JoinQuant 模拟交易报告</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #172033; background: #f6f8fb; }
h1 { font-size: 24px; margin: 0 0 16px; }
h2 { font-size: 18px; margin: 24px 0 10px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 18px; }
.card { background: #fff; border: 1px solid #dfe5ef; border-radius: 8px; padding: 12px; }
.label { font-size: 12px; color: #64748b; }
.value { font-size: 20px; font-weight: 700; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dfe5ef; }
th, td { padding: 8px 10px; border-bottom: 1px solid #e6ebf2; text-align: right; font-size: 13px; }
th:first-child, td:first-child, .left { text-align: left; }
th { color: #475569; background: #f1f5f9; }
.chart { background: #fff; border: 1px solid #dfe5ef; border-radius: 8px; padding: 12px; }
.positive { color: #0f8a4b; }
.negative { color: #c2410c; }
</style>
</head>
<body>
<h1>MTF JoinQuant 模拟交易报告</h1>
<section class="cards">
{summary_cards}
</section>
<section class="chart">
{chart}
</section>
<h2>每日资金与收益</h2>
{daily_table}
<h2>每日成交明细</h2>
{trade_table}
</body>
</html>""".format(
        summary_cards=render_summary_cards(latest),
        chart=render_svg_chart(rows),
        daily_table=render_daily_table(rows),
        trade_table=render_trade_table(trades),
    )


def render_summary_cards(latest):
    cards = [
        ('初始资金', money(latest.get('initial_cash', 0))),
        ('实际资金', money(latest.get('total_value', 0))),
        ('累计收益', signed_money(latest.get('cumulative_profit', 0))),
        ('累计收益率', pct(latest.get('cumulative_return_rate', 0))),
    ]
    return ''.join('<div class="card"><div class="label">{0}</div><div class="value">{1}</div></div>'.format(
        esc(label), value
    ) for label, value in cards)


def render_daily_table(rows):
    body = ''.join(
        '<tr><td>{date}</td><td>{initial_cash}</td><td>{total_value}</td><td>{available_cash}</td>'
        '<td>{positions_value}</td><td>{daily_profit}</td><td>{cumulative_profit}</td>'
        '<td>{daily_return_rate}</td><td>{cumulative_return_rate}</td><td>{trade_count}</td></tr>'.format(
            date=esc(row['date']),
            initial_cash=money(row['initial_cash']),
            total_value=money(row['total_value']),
            available_cash=money(row['available_cash']),
            positions_value=money(row['positions_value']),
            daily_profit=signed_money(row['daily_profit']),
            cumulative_profit=signed_money(row['cumulative_profit']),
            daily_return_rate=pct(row['daily_return_rate']),
            cumulative_return_rate=pct(row['cumulative_return_rate']),
            trade_count=int(row['trade_count']),
        ) for row in rows
    )
    return '<table><thead><tr><th>日期</th><th>初始资金</th><th>实际资金</th><th>可用资金</th><th>持仓市值</th><th>当日收益</th><th>累计收益</th><th>当日收益率</th><th>累计收益率</th><th>成交数</th></tr></thead><tbody>{0}</tbody></table>'.format(body)


def render_trade_table(trades):
    body = ''.join(
        '<tr><td>{date}</td><td class="left">{security}</td><td>{amount}</td><td>{price}</td><td>{value}</td><td>{commission}</td><td class="left">{order_id}</td></tr>'.format(
            date=esc(row['date']),
            security=esc(row['security']),
            amount='{0:.0f}'.format(row['amount']),
            price=money(row['price']),
            value=money(row['value']),
            commission=money(row['commission']),
            order_id=esc(row['order_id']),
        ) for row in trades
    )
    return '<table><thead><tr><th>日期</th><th>标的</th><th>数量</th><th>成交价</th><th>成交额</th><th>费用</th><th>订单ID</th></tr></thead><tbody>{0}</tbody></table>'.format(body or '<tr><td colspan="7" class="left">暂无成交</td></tr>')


def render_svg_chart(rows):
    width, height, pad = 900, 280, 34
    if len(rows) < 2:
        return '<svg viewBox="0 0 {0} {1}" width="100%" height="{1}"><text x="24" y="48">数据不足，至少需要两个交易日绘制曲线。</text></svg>'.format(width, height)

    def points(series):
        min_value = min(series)
        max_value = max(series)
        span = max_value - min_value or 1
        result = []
        for index, value in enumerate(series):
            x = pad + index * ((width - pad * 2) / float(len(series) - 1))
            y = height - pad - ((value - min_value) / span) * (height - pad * 2)
            result.append('{0:.1f},{1:.1f}'.format(x, y))
        return ' '.join(result)

    values = [float(row['total_value']) for row in rows]
    profits = [float(row['cumulative_profit']) for row in rows]
    returns = [float(row['cumulative_return_rate']) for row in rows]

    x_labels = ''.join('<text x="{0:.1f}" y="{1}" font-size="11" text-anchor="middle">{2}</text>'.format(
        pad + index * ((width - pad * 2) / float(len(rows) - 1)),
        height - 8,
        esc(row['date'][5:]),
    ) for index, row in enumerate(rows))

    return '<svg viewBox="0 0 {0} {1}" width="100%" height="{1}" role="img"><line x1="{2}" y1="{3}" x2="{4}" y2="{3}" stroke="#cbd5e1"/><polyline points="{5}" fill="none" stroke="#2563eb" stroke-width="2.5"/><polyline points="{6}" fill="none" stroke="#9333ea" stroke-width="2.5"/><polyline points="{7}" fill="none" stroke="#16a34a" stroke-width="2.5"/><text x="24" y="22" font-size="12" fill="#2563eb">实际资金</text><text x="112" y="22" font-size="12" fill="#9333ea">累计收益</text><text x="196" y="22" font-size="12" fill="#16a34a">累计收益率</text>{8}</svg>'.format(
        width, height, pad, height - pad, width - pad, points(values), points(profits), points(returns), x_labels
    )


def money(value):
    return '{0:,.2f}'.format(float(value or 0))


def signed_money(value):
    value = float(value or 0)
    css = 'positive' if value >= 0 else 'negative'
    return '<span class="{0}">{1:+,.2f}</span>'.format(css, value)


def pct(value):
    value = float(value or 0)
    css = 'positive' if value >= 0 else 'negative'
    return '<span class="{0}">{1:+.2%}</span>'.format(css, value)


def esc(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#x27;')
```

Notes:

- `get_trades()` returns only the current day's trades, so call it from `after_trading_end(context)`.
- `write_file()` writes into JoinQuant research files. Open `mtf_sim_trade_report.html` in the research file area to inspect the report.
- The template stores only serializable values. JoinQuant warns against persisting mutable `context`, order, trade, or position objects.
- For simulated trading, keep `set_option('use_real_price', True)` unless the strategy has a documented reason to use adjusted-price behavior.
