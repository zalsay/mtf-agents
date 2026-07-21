#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据 sim-trade-report.json 生成一张可交互的模拟交易资产曲线图 (HTML+ECharts)。

用法:
    python3 scripts/gen_asset_curve_html.py [report_json] [output_html] \
        [--date YYYY-MM-DD] [--no-benchmark] [--force-benchmark]

默认读取 reports/mtf-etf/YYYY-MM-DD/YYYY-MM-DD-sim-trade-report.json
(取最新日期目录) 并输出同目录下的 asset-curve.html。
传 --date YYYY-MM-DD 可指定生成某一天(与 apply/render 参数对齐)。

脚本会自动把 echarts.min.js 放到输出目录(优先从 scripts/vendor 或其它
日期目录复制, 否则从 CDN 下载), 使 HTML 离线也能渲染。

上证指数对比曲线: 用 easy-tdx 拉取 000001 真实日线收盘, 归一化为
"¥等价"(首日=初始本金), 与策略曲线共享主图坐标轴, 直观对比
"买指数躺平 vs 策略"。首次拉取后会缓存到 sh-index-benchmark.json,
之后离线可用。
"""
import json
import os
import sys
import shutil
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_latest_report():
    base = os.path.join(ROOT, "reports", "mtf-etf")
    if not os.path.isdir(base):
        return None
    dates = sorted(
        (d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))),
        reverse=True,
    )
    for d in dates:
        p = os.path.join(base, d, f"{d}-sim-trade-report.json")
        if os.path.exists(p):
            return p
    return None


def fetch_sh_index_closes():
    """用 easy-tdx 拉取上证指数(000001)真实日线收盘, 返回 {date: close}。失败返回 None。"""
    try:
        from easy_tdx.cli.conn import get_mac_client
        from easy_tdx.cli.parsers import parse_adjust, parse_market, parse_period
    except Exception as e:
        print("WARN: 缺少 easy-tdx, 跳过上证指数对比:", e)
        return None
    try:
        with get_mac_client() as client:
            frame = client.get_stock_kline(
                parse_market("SH"), "000001",
                period=parse_period("DAILY"), start=0, count=80,
                adjust=parse_adjust("QFQ"),
            )
        recs = frame.to_dict("records")
    except Exception as e:
        print("WARN: easy-tdx 获取上证指数失败, 跳过对比曲线:", e)
        return None
    closes = {}
    for r in recs:
        dt = str(r.get("datetime"))
        c = r.get("close")
        if c is not None:
            closes[dt[:10]] = float(c)
    return closes or None


def load_or_fetch_benchmark(dates, out_dir, force=False):
    """返回归一化到 initial 的上证指数序列(同长度, 缺失为 None), 或 None。"""
    cache = os.path.join(out_dir, "sh-index-benchmark.json")
    if not force and os.path.exists(cache):
        try:
            c = json.load(open(cache, encoding="utf-8"))
            if c.get("dates") == dates and c.get("norm") is not None:
                return c["norm"], c.get("period_ret")
        except Exception:
            pass
    raw = fetch_sh_index_closes()
    if not raw:
        return None, None
    closes = [raw.get(d) for d in dates]
    first = next((c for c in closes if c is not None), None)
    if first is None:
        return None, None
    norm = [(c / first * 10000.0) if c is not None else None for c in closes]
    last = next((c for c in reversed(closes) if c is not None), None)
    period_ret = (last / first - 1) * 100 if last else None
    try:
        json.dump(
            {"dates": dates, "norm": norm, "period_ret": period_ret},
            open(cache, "w", encoding="utf-8"),
            ensure_ascii=False, indent=2,
        )
    except Exception:
        pass
    return norm, period_ret


def ensure_echarts(out_dir):
    """确保 out_dir 下有 echarts.min.js(本地化, 离线可渲染)。
    优先从 scripts/vendor 或其它日期目录复制, 否则从 CDN 下载。"""
    local = os.path.join(out_dir, "echarts.min.js")
    if os.path.exists(local) and os.path.getsize(local) > 100000:
        return local
    candidates = [os.path.join(ROOT, "scripts", "vendor", "echarts.min.js")]
    base = os.path.join(ROOT, "reports", "mtf-etf")
    if os.path.isdir(base):
        for d in sorted(os.listdir(base), reverse=True):
            c = os.path.join(base, d, "echarts.min.js")
            if os.path.exists(c):
                candidates.append(c)
                break
    for src in candidates:
        if os.path.exists(src) and os.path.getsize(src) > 100000:
            shutil.copy(src, local)
            print(f"copied echarts.min.js <- {src}")
            return local
    url = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"
    try:
        print("downloading echarts.min.js ...")
        urllib.request.urlretrieve(url, local)
        return local
    except Exception as e:
        print("WARN: 无法获取 echarts.min.js (HTML 将依赖在线 CDN):", e)
        return None


def main():
    args = sys.argv[1:]
    report_path = None
    out_path = None
    date_arg = None
    no_benchmark = False
    force_benchmark = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--no-benchmark":
            no_benchmark = True
        elif a == "--force-benchmark":
            force_benchmark = True
        elif a == "--date":
            i += 1
            date_arg = args[i] if i < len(args) else None
        elif a.startswith("--date="):
            date_arg = a.split("=", 1)[1]
        elif report_path is None:
            report_path = a
        elif out_path is None:
            out_path = a
        i += 1

    if report_path is None:
        if date_arg:
            cand = os.path.join(
                ROOT, "reports", "mtf-etf", date_arg,
                f"{date_arg}-sim-trade-report.json",
            )
            if os.path.exists(cand):
                report_path = cand
            else:
                raise SystemExit(f"找不到 {date_arg} 的报告: {cand}")
        else:
            report_path = find_latest_report()
    if not report_path or not os.path.exists(report_path):
        raise SystemExit(f"找不到报告文件: {report_path}")
    out_dir = os.path.dirname(report_path)
    if out_path is None:
        out_path = os.path.join(out_dir, "asset-curve.html")
    ensure_echarts(out_dir)

    d = json.load(open(report_path, encoding="utf-8"))
    rows = d["rows"]
    trades = d.get("trades", []) or []

    dates = [r["date"] for r in rows]
    total = [round(r["total_value"], 2) for r in rows]
    positions = [round(r["positions_value"], 2) for r in rows]
    cash = [round(r["available_cash"], 2) for r in rows]
    daily_pnl = [round(r["daily_profit"], 2) for r in rows]
    cumulative = [round(r["cumulative_return_rate"] * 100, 2) for r in rows]

    initial = rows[0]["initial_cash"]
    final_value = rows[-1]["total_value"]
    cum_profit = rows[-1]["cumulative_profit"]
    cum_ret = rows[-1]["cumulative_return_rate"] * 100
    last_pos = rows[-1].get("current_position_snapshot") or []
    last_pos_str = "、".join(
        f"{p['name']}({p['symbol']}) {p['amount']}份" for p in last_pos
    ) or "无"

    # 最大回撤（基于总资产峰值-谷值）
    cur_peak = total[0]
    cur_peak_i = 0
    max_dd = 0.0
    dd_peak_i = 0
    dd_trough_i = 0
    for i, v in enumerate(total):
        if v > cur_peak:
            cur_peak = v
            cur_peak_i = i
        dd = (v - cur_peak) / cur_peak
        if dd < max_dd:
            max_dd = dd
            dd_peak_i = cur_peak_i
            dd_trough_i = i
    max_dd_pct = round(max_dd * 100, 2)
    dd_peak_date = dates[dd_peak_i]
    dd_trough_date = dates[dd_trough_i]

    # 买卖标记
    markers = []
    for t in trades:
        dt = t["date"]
        side = t["side"]
        sym = t["security"]
        if dt in dates:
            idx = dates.index(dt)
            yv = total[idx]
        else:
            yv = None
        is_buy = side == "buy"
        markers.append(
            {
                "name": ("买入 " + sym) if is_buy else "卖出 " + sym,
                "value": sym,
                "xAxis": dt,
                "yAxis": yv,
                "symbol": "triangle",
                "symbolSize": 16,
                "symbolRotate": 0 if is_buy else 180,
                "itemStyle": {"color": "#ffd166" if is_buy else "#b388ff"},
                "label": {
                    "show": True,
                    "formatter": "B" if is_buy else "S",
                    "color": "#0f1419",
                    "fontWeight": "bold",
                    "fontSize": 10,
                },
            }
        )

    # 上证指数对比
    benchmark = None
    index_period_ret = None
    excess = None
    if not no_benchmark:
        benchmark, index_period_ret = load_or_fetch_benchmark(
            dates, out_dir, force=force_benchmark
        )
        if benchmark is not None and index_period_ret is not None:
            excess = cum_ret - index_period_ret

    pos_pct = [round(p / t * 100, 2) if t else 0 for p, t in zip(positions, total)]
    cash_pct = [round(100 - x, 2) for x in pos_pct]  # 保证堆叠正好到 100%
    payload = {
        "dates": dates,
        "total": total,
        "positions": positions,
        "cash": cash,
        "pos_pct": pos_pct,
        "cash_pct": cash_pct,
        "daily_pnl": daily_pnl,
        "cumulative": cumulative,
        "initial": initial,
        "final_value": final_value,
        "cum_profit": round(cum_profit, 2),
        "cum_ret": round(cum_ret, 2),
        "max_dd_pct": max_dd_pct,
        "dd_peak_date": dd_peak_date,
        "dd_trough_date": dd_trough_date,
        "markers": markers,
        "last_pos_str": last_pos_str,
        "trade_count": len(trades),
        "report_date": d.get("report_date"),
        "valuation_source": d.get("valuation_source"),
        "benchmark": benchmark,
        "index_period_ret": (round(index_period_ret, 2) if index_period_ret is not None else None),
        "excess": (round(excess, 2) if excess is not None else None),
    }

    html = build_html(payload)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"written: {out_path}")
    print(
        f"期末总资产={final_value} 累计收益={cum_profit} 累计收益率={cum_ret:.2f}% "
        f"最大回撤={max_dd_pct}% 交易次数={len(trades)}"
        + (f" 上证区间收益={index_period_ret:.2f}% 超额={excess:.2f}%" if excess is not None else " (无上证对比)")
    )


def build_html(p):
    data_json = json.dumps(p, ensure_ascii=False)
    sign = "+" if p["cum_profit"] >= 0 else ""
    ret_sign = "+" if p["cum_ret"] >= 0 else ""
    has_bench = p["benchmark"] is not None
    bench_legend = "'上证指数(¥等价)', " if has_bench else ""
    bench_series = ""
    if has_bench:
        bench_series = """
    {
      name: '上证指数(¥等价)', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
      data: D.benchmark, smooth: true, symbol: 'none', z: 1,
      lineStyle: { width: 1.8, color: '#f0883e' },
      itemStyle: { color: '#f0883e' },
      connectNulls: false
    },"""
    # tooltip 中是否包含上证
    bench_tip = ""
    if has_bench:
        bench_tip = """
      const b = D.benchmark[i];
      if (b != null) s += '上证指数(¥等价)：' + fmtY(b) + '<br/>';"""
    # 超额收益 KPI
    excess_kpi = ""
    if p["excess"] is not None:
        ec = "up" if p["excess"] >= 0 else "down"
        es = "+" if p["excess"] >= 0 else ""
        excess_kpi = f"""
    <div class="kpi">
      <div class="label">超额收益 (vs 上证)</div>
      <div class="value {ec}">{es}{p['excess']:.2f}%</div>
    </div>"""
    kpi_cols = "repeat(6, 1fr)" if p["excess"] is not None else "repeat(5, 1fr)"
    bench_note = ""
    if has_bench:
        bench_note = " <span style='color:#f0883e'>橙线=上证指数(¥等价, 首日对齐初始本金)</span>，与蓝线(策略)、灰虚线(持币)对比；"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>模拟交易资产曲线 · {p['report_date']}</title>
<script src="./echarts.min.js"></script>
<style>
  :root {{
    --bg: #0d1117;
    --panel: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #8b949e;
    --red: #ef4444;
    --green: #16c784;
    --gold: #ffd166;
    --purple: #b388ff;
    --blue: #58a6ff;
    --orange: #f0883e;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
      "Microsoft YaHei", Roboto, Helvetica, Arial, sans-serif;
    padding: 24px;
  }}
  .wrap {{ max-width: 1180px; margin: 0 auto; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; font-weight: 600; }}
  .sub {{ color: var(--muted); font-size: 13px; margin-bottom: 18px; }}
  .kpis {{
    display: grid; grid-template-columns: {kpi_cols}; gap: 12px; margin-bottom: 18px;
  }}
  .kpi {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 16px;
  }}
  .kpi .label {{ color: var(--muted); font-size: 12px; margin-bottom: 6px; }}
  .kpi .value {{ font-size: 20px; font-weight: 700; }}
  .up {{ color: var(--red); }}
  .down {{ color: var(--green); }}
  .chart {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 8px 8px 4px; position: relative; }}
  .zoom-label {{ position: absolute; left: 12px; bottom: 16px; color: var(--muted); font-size: 12px; line-height: 18px; pointer-events: none; user-select: none; }}
  #main {{ width: 100%; height: 680px; }}
  .legend-note {{ color: var(--muted); font-size: 12px; margin-top: 10px; line-height: 1.6; }}
  .tag {{ display:inline-block; padding: 1px 7px; border-radius: 6px; font-size: 12px; margin-right: 6px; }}
  .tag.buy {{ background: rgba(255,209,102,.15); color: var(--gold); border:1px solid rgba(255,209,102,.4); }}
  .tag.sell {{ background: rgba(179,136,255,.15); color: var(--purple); border:1px solid rgba(179,136,255,.4); }}
  @media (max-width: 860px) {{ .kpis {{ grid-template-columns: repeat(2,1fr); }} }}
</style>
</head>
<body>
<div class="wrap">
  <h1>模拟交易资产曲线</h1>
  <div class="sub">
    报告日期 {p['report_date']} · 数据区间 {p['dates'][0]} ~ {p['dates'][-1]}（{len(p['dates'])} 个交易日）·
    持仓估值来源：{p['valuation_source'] or '未知'}
  </div>

  <div class="kpis">
    <div class="kpi">
      <div class="label">期末总资产</div>
      <div class="value">¥{p['final_value']:,.2f}</div>
    </div>
    <div class="kpi">
      <div class="label">累计收益</div>
      <div class="value {('up' if p['cum_profit']>=0 else 'down')}">{sign}¥{p['cum_profit']:,.2f}</div>
    </div>
    <div class="kpi">
      <div class="label">累计收益率</div>
      <div class="value {('up' if p['cum_ret']>=0 else 'down')}">{ret_sign}{p['cum_ret']:.2f}%</div>
    </div>
    <div class="kpi">
      <div class="label">最大回撤</div>
      <div class="value down">{p['max_dd_pct']}%</div>
    </div>
    <div class="kpi">
      <div class="label">交易笔数</div>
      <div class="value">{p['trade_count']}</div>
    </div>{excess_kpi}
  </div>

  <div class="chart">
    <div class="zoom-label">区间</div>
    <div id="main"></div>
  </div>

  <div class="legend-note">
    当前持仓：{p['last_pos_str']}。<br/>
    <span class="tag buy">B</span> 买入标记（金色▲）&nbsp;&nbsp;
    <span class="tag sell">S</span> 卖出标记（紫色▼）&nbsp;&nbsp;
    日盈亏柱：<span class="up">红=涨</span>
    <span class="down">绿=跌</span>（A股惯例）。
    虚线为初始本金 ¥{p['initial']:,.0f}；阴影区为最大回撤（{p['dd_peak_date']} → {p['dd_trough_date']}）。
    {bench_note}
    中间图为资产配置 <b>100% 堆叠占比</b>：蓝=持仓占比、金=现金占比（两者之和恒为 100%）。
    可拖动下方缩放条查看局部区间，悬浮查看每日明细。
  </div>
</div>

<script>
const D = {data_json};

const fmtY = (v) => '¥' + Number(v).toLocaleString('zh-CN', {{maximumFractionDigits: 2}});
const fmtPct = (v) => (v >= 0 ? '+' : '') + v.toFixed(2) + '%';

const option = {{
  backgroundColor: 'transparent',
  textStyle: {{ color: '#e6edf3' }},
  animationDuration: 700,
  tooltip: {{
    trigger: 'axis',
    backgroundColor: 'rgba(22,27,34,0.96)',
    borderColor: '#30363d',
    textStyle: {{ color: '#e6edf3' }},
    axisPointer: {{ type: 'cross', label: {{ backgroundColor: '#30363d' }} }},
    formatter: function (ps) {{
      const i = ps[0].dataIndex;
      const tv = D.total[i], pos = D.positions[i], cs = D.cash[i];
      const dp = D.daily_pnl[i], cr = D.cumulative[i];
      const dpCls = dp >= 0 ? 'color:#ef4444' : 'color:#16c784';
      let s = '<b>' + D.dates[i] + '</b><br/>';
      s += '总资产：' + fmtY(tv) + '<br/>';
      s += '持仓市值：' + fmtY(pos) + '（' + (tv? (pos/tv*100).toFixed(1):0) + '%）<br/>';
      s += '可用现金：' + fmtY(cs) + '（' + (tv? (cs/tv*100).toFixed(1):0) + '%）<br/>';
      s += '当日盈亏：<span style="' + dpCls + '">' + (dp>=0?'+':'') + dp.toFixed(2) + '</span><br/>';
      s += '累计收益率：' + fmtPct(cr);{bench_tip}
      return s;
    }}
  }},
  axisPointer: {{ link: [{{ xAxisIndex: 'all' }}] }},
  legend: {{
    data: ['总资产', '初始本金', {bench_legend}'持仓占比', '现金占比', '当日盈亏'],
    top: 6, textStyle: {{ color: '#8b949e' }}, inactiveColor: '#444'
  }},
  grid: [
    {{ left: 64, right: 24, top: 48, height: '38%' }},
    {{ left: 64, right: 24, top: '52%', height: '19%' }},
    {{ left: 64, right: 24, top: '76%', height: '14%' }}
  ],
  xAxis: [
    {{ type: 'category', data: D.dates, gridIndex: 0, boundaryGap: false,
       axisLine: {{ lineStyle: {{ color: '#30363d' }} }},
       axisLabel: {{ color: '#8b949e' }} }},
    {{ type: 'category', data: D.dates, gridIndex: 1, boundaryGap: false,
       axisLine: {{ lineStyle: {{ color: '#30363d' }} }},
       axisLabel: {{ show: false }} }},
    {{ type: 'category', data: D.dates, gridIndex: 2, boundaryGap: true,
       axisLine: {{ lineStyle: {{ color: '#30363d' }} }},
       axisLabel: {{ color: '#8b949e', fontSize: 10 }} }}
  ],
  yAxis: [
    {{ type: 'value', gridIndex: 0, scale: true,
       axisLabel: {{ color: '#8b949e', formatter: (v)=> '¥'+v }},
       splitLine: {{ lineStyle: {{ color: 'rgba(48,54,61,0.6)' }} }} }},
    {{ type: 'value', gridIndex: 1, min: 0, max: 100,
       axisLabel: {{ color: '#8b949e', formatter: (v)=> v + '%' }},
       splitLine: {{ lineStyle: {{ color: 'rgba(48,54,61,0.6)' }} }} }},
    {{ type: 'value', gridIndex: 2,
       axisLabel: {{ color: '#8b949e', formatter: (v)=> v }},
       splitLine: {{ lineStyle: {{ color: 'rgba(48,54,61,0.6)' }} }} }}
  ],
  dataZoom: [
    {{ type: 'inside', xAxisIndex: [0,1,2] }},
    {{ type: 'slider', xAxisIndex: [0,1,2], bottom: 10, height: 18,
       borderColor: '#30363d', fillerColor: 'rgba(88,166,255,0.15)',
       textStyle: {{ color: '#8b949e' }}, dataBackground: {{ lineStyle:{{color:'#30363d'}}, areaStyle:{{color:'#21262d'}} }} }}
  ],
  series: [
    {{
      name: '总资产', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
      data: D.total, smooth: true, symbol: 'circle', symbolSize: 5, z: 3,
      lineStyle: {{ width: 2.6, color: '#58a6ff' }},
      itemStyle: {{ color: '#58a6ff' }},
      areaStyle: {{ color: new echarts.graphic.LinearGradient(0,0,0,1, [
        {{ offset: 0, color: 'rgba(88,166,255,0.30)' }},
        {{ offset: 1, color: 'rgba(88,166,255,0.02)' }}
      ]) }},
      markLine: {{
        symbol: 'none', silent: true,
        lineStyle: {{ color: '#8b949e', type: 'dashed', width: 1.3 }},
        label: {{ color: '#8b949e', formatter: '初始本金 ¥' + D.initial }},
        data: [{{ yAxis: D.initial }}]
      }},
      markArea: {{
        itemStyle: {{ color: 'rgba(239,68,68,0.10)' }},
        label: {{ show: true, position: 'insideTop', color: '#ef4444',
                  formatter: '最大回撤 ' + D.max_dd_pct + '%', fontSize: 11 }},
        data: [[{{ xAxis: D.dd_peak_date }}, {{ xAxis: D.dd_trough_date }}]]
      }},
      markPoint: {{
        symbolSize: 16, data: D.markers,
        label: {{ show: true, position: 'top' }}
      }}
    }},{bench_series}
    {{
      name: '初始本金', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
      data: D.dates.map(()=> D.initial), symbol: 'none', z: 1,
      lineStyle: {{ color: '#6e7681', type: 'dashed', width: 1.2 }},
      tooltip: {{ show: false }}
    }},
    {{
      name: '持仓占比', type: 'line', xAxisIndex: 1, yAxisIndex: 1,
      data: D.pos_pct, stack: 'alloc', smooth: true, symbol: 'none',
      lineStyle: {{ width: 0 }},
      areaStyle: {{ color: '#58a6ff' }}
    }},
    {{
      name: '现金占比', type: 'line', xAxisIndex: 1, yAxisIndex: 1,
      data: D.cash_pct, stack: 'alloc', smooth: true, symbol: 'none',
      lineStyle: {{ width: 0 }},
      areaStyle: {{ color: '#ffd166' }}
    }},
    {{
      name: '当日盈亏', type: 'bar', xAxisIndex: 2, yAxisIndex: 2,
      data: D.daily_pnl.map(v => ({{
        value: v,
        itemStyle: {{ color: v >= 0 ? '#ef4444' : '#16c784' }}
      }})),
      barWidth: '55%'
    }}
  ]
}};

const chart = echarts.init(document.getElementById('main'), null, {{ renderer: 'canvas' }});
chart.setOption(option);
window.addEventListener('resize', () => chart.resize());
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
