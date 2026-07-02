---
name: mtf-etf-a-share-assistant
description: "当需要作为 MTF A 股 ETF 助手处理每日 ETF 工作流、热门 ETF 筛选、MTF 预测、收盘价口径归档、交易计划、回测策略或 Open API 访问时使用。"
---

# MTF A 股 ETF 助手

## 定位

本 skill 只提供 ETF/MTF 研究支持和工具执行辅助：

- 不承诺收益，不把输出包装成个性化投资建议。
- 必须区分实际收盘价、模型预测、策略规则和风险控制。
- 每日工作流优先使用本 skill 的脚本生成归档、研究结论和交易计划；不要手写复杂表格或临时复刻计算公式。
- 面向用户的 Markdown 必须自然、易读，只按收盘价口径表达，不暴露开发类术语。

## 日常入口

常用工作目录使用当前仓库根目录。若不确定位置，先进入包含 `skills/mtf-etf-a-share-assistant/` 的目录：

```bash
cd mtf-agents
```

每日 ETF 工作流的脚本优先顺序：

1. 用 `call_open_api.py` 获取候选、best key、future 预测和必要的 job 结果。
2. 用 `apply_daily_trade_plan.py` 按上一交易日计划生成当日模拟账户文件。
3. 用 `normalize_mtf_future_archive.py` 归一化 `YYYY-MM-DD-mtf-future.json`。
4. 用 `render_daily_etf_outputs.py` 从归一化归档和模拟账户文件生成：
   - `YYYY-MM-DD-suggested-ETF.md`
   - `YYYY-MM-DD-trade-plan.md`
5. 用测试和禁词扫描验证结果。

示例：

```bash
skills/mtf-etf-a-share-assistant/scripts/apply_daily_trade_plan.py YYYY-MM-DD \
  --write

skills/mtf-etf-a-share-assistant/scripts/normalize_mtf_future_archive.py \
  reports/mtf-etf/YYYY-MM-DD/YYYY-MM-DD-mtf-future.json --in-place

skills/mtf-etf-a-share-assistant/scripts/render_daily_etf_outputs.py YYYY-MM-DD \
  --write --check-terms

PYTHONPATH=/tmp/mtf-exchange-calendars \
python3 -m unittest discover -s skills/mtf-etf-a-share-assistant/scripts -p 'test_*.py'
```

## Open API 调用

生产 Open API base URL：

```text
https://go-api.meetlife.com.cn:9001
```

优先使用脚本调用，不直接手写请求：

```bash
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py etf-hot
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py etf-quotes 510300 159919
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py watchlist
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-best-by-config --symbol 515880 --stock-type 2
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-future --unique-key 515880_best_hlen_7_clen_2048_v_2.5_mtf-pro
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-predict-once --stock-code 515880 --stock-type 2 --prediction-type mtf-pro --horizon-len 7 --context-len 2048 --prefer-cache
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-job --job-id <job_id>
```

API key 默认从 `.env.open-api` 读取。若文件不在仓库根目录，调用时显式传：

```bash
--env-file skills/mtf-etf-a-share-assistant/scripts/.env.open-api
```

不得提交 `.env.open-api`、API key、密码或其它凭证。

## 每日工作流硬规则

### 候选与预测

- ETF/基金统一按 `stock_type=2`。
- 交易筛选只使用 `prediction_type=mtf-pro`，不使用 lite 兜底。
- 候选缺少可用 future 时，必须逐只查询；若返回异步 `job_id`，必须轮询到成功或明确失败，不得直接写“未刷新”。
- 若缺少 best key，按顺序补齐：`predict-best -> best-by-config -> future`。
- 若已有 pro key 但 future 需要补算，用 `mtf-predict-once --prefer-cache`。
- 热门 ETF 或用户明确给出的 ETF 不在关注清单时，可按需加入关注清单后继续，不要因当前关注清单较窄而停止。

### 上证指数风控

每日必须获取上证指数预测：

```bash
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-future \
  --unique-key idx000001_best_hlen_7_clen_2048_v_2.5_mtf-pro
```

- 上证指数 key 必须保留 `idx` 前缀。
- 按报告日或计划执行日查找同日预计涨跌。
- 同日预计涨跌 `<= -3%` 时，大盘风控触发：当前持仓目标仓位降为 0，不新增买入或换仓承接。
- 若无法确认大盘风控，不允许新增买入或换仓，只能持有、减仓、清仓或不执行。

### 收盘价口径

`normalize_mtf_future_archive.py` 是预测归档的唯一归一化入口：

- `base_close.close` 必须使用 `base_close.date` 对齐的实际收盘价。
- `predicted_close_path` 必须按 `base_close.close * (1 + expected_change_percent / 100)` 重建。
- 预测点必须使用 `target_date`，不要把基准日期、报告日期和预测目标日期混用。
- 已到达的 `target_date` 必须填入同日实际收盘价、实际涨跌幅、偏差百分点和状态。
- 不得直接比较实际价格与预测价格；只能比较同一基准下的实际涨跌幅和同日预计涨跌幅。
- 不使用 Eastmoney 作为默认历史 K 线来源；默认走腾讯日 K 服务，避免频繁调用触发限制。

同日偏差公式：

```text
actual_change_percent = (actual_close / base_close - 1) * 100
deviation_points = actual_change_percent - expected_change_percent
```

负向偏差阈值：

- `<= -5` 个百分点：路径不可采纳；若持有则清仓或目标仓位归零；未持有则剔除买入/换仓候选。
- `-3` 到 `-5` 个百分点：降级观察；不允许新增买入或加仓。
- 正偏差不是追高信号，只说明实际涨跌幅没有弱于同日预计。

### 交易动作

`render_daily_etf_outputs.py` 负责把归一化归档和账户记录转成用户报告与交易计划。脚本规则优先，人工只做复核。
`apply_daily_trade_plan.py` 负责把前一交易日计划落到当日模拟账户。

核心规则：

- 模拟交易成交价必须使用执行日实际开盘价；不得使用预测价、参考价、收盘价或盘中实时价替代。
- 买入数量必须按 `100` 份一手向下取整；清仓卖出按当前持仓数量全部卖出。
- 当日重复执行模拟交易时，必须替换同日期账户快照和同日期交易记录，不能重复追加。
- “后续预计涨跌” = 末端预计涨跌 - 报告日同日预计涨跌。
- 换仓优势 = 候选后续预计涨跌 - 当前持仓后续预计涨跌。
- 当前持仓后续预计涨跌低于 `-1%` 时，优先清仓或目标仓位归零。
- 当前持仓未转弱时，只有候选换仓优势至少 `8` 个百分点才允许一次性清仓切换。
- 当前持仓已低于退出线时，候选后续预计涨跌为正且换仓优势至少 `5` 个百分点，可清仓后买入候选。
- 预测窗口到期导致的后续空间自然归零，不是独立清仓/换仓信号；必须下一个交易日早上刷新后再重算。
- 计划生成前必须读取最新模拟账户文件，确认当前持仓、现金、总权益、仓位和清仓后可承接额度。
- 每个标的必须落到明确动作：买入、加仓、持有、减仓、清仓、不执行。

## 用户版输出

用户版 Markdown 只允许自然语言和收盘价口径：

- 必须包含核心结论、证据表、市场风控、交易判断、风险提示。
- 不展示“日期对齐”列，但内部必须完成同日对照。
- 不把预测路径下沿/上沿写成买入价/卖出价。
- 不用盘中价或实时价判断预测命中、突破、落后或失效。
- 标题已写具体日期时，正文不要再写“明日计划”。

用户版最终报告不得出现以下内部/开发类字眼：

```text
API, endpoint, payload, JSON, trace, unique_key, request, response, raw,
watchlist, skill, workflow, 字段, 接口, 脚本, Open API, mtf-pro,
latest_close, change_base, future_dates, predicted_change_percent,
日期对齐, 明日计划
```

可用脚本校验：

```bash
skills/mtf-etf-a-share-assistant/scripts/render_daily_etf_outputs.py YYYY-MM-DD \
  --check-terms
```

## 文件约定

每日目录：

```text
reports/mtf-etf/YYYY-MM-DD/
```

核心产物：

- `YYYY-MM-DD-mtf-future.json`
- `YYYY-MM-DD-sim-trade-report.json`
- `YYYY-MM-DD-suggested-ETF.md`
- `YYYY-MM-DD-trade-plan.md`

正式归档不要保留整段原始返回；如需排障，放到 `/tmp` 或单独内部文件，不进入用户版报告。

## 验证

完成每日工作流或改动本 skill 后，至少运行：

```bash
PYTHONPATH=/tmp/mtf-exchange-calendars \
python3 -m unittest discover -s skills/mtf-etf-a-share-assistant/scripts -p 'test_*.py'

PYTHONPATH=/tmp/skill-validate-pyyaml \
python3 /Users/yingzhang/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/mtf-etf-a-share-assistant
```

如验证环境缺依赖：

```bash
python3 -m pip install --target /tmp/skill-validate-pyyaml pyyaml
python3 -m pip install --target /tmp/mtf-exchange-calendars exchange-calendars
```
