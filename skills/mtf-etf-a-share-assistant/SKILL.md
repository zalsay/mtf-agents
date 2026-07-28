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

## 运行依赖

- 正式运行每日工作流前必须确认 Python 环境已安装 `easy-tdx`。
- 实际日 K 查询统一通过 `easy-tdx` 获取，日线复权口径必须显式使用前复权 `QFQ`。
- 若运行环境缺少依赖，先执行 `python3 -m pip install easy-tdx`，再运行 `apply_daily_trade_plan.py` 或 `normalize_mtf_future_archive.py`。

## 日常入口

常用工作目录使用当前仓库根目录。若不确定位置，先进入包含 `skills/mtf-etf-a-share-assistant/` 的目录：

```bash
cd mtf-agents
```

每日 ETF 工作流的脚本优先顺序：

1. 用 `scripts/build_daily_archive.py --date YYYY-MM-DD` 一键构建当日 `YYYY-MM-DD-mtf-future.json`（内部先通过 v2 `etf-hot` 拉取并落盘 `YYYY-MM-DD-etf-hot.json`，直接以 `data.items` 中的热门 ETF 作为目标，再通过 v2 规则选择 mtf-pro best key、按归档日期读取已有 future 缓存；默认 cache miss 只跳过，明确需要补算时才增加 `--allow-predict`；最后用 easy-tdx(QFQ) 回填当日收盘；`close_observation.source` 固定为 `easy_tdx_qfq_daily_kline` 避免拆分因子双计；单只预测/行情失败自动跳过继续）。
2. 用 `apply_daily_trade_plan.py` 按上一交易日计划生成当日模拟账户文件。
3. 用 `normalize_mtf_future_archive.py` 归一化 `YYYY-MM-DD-mtf-future.json`。
4. 用 `render_daily_etf_outputs.py` 从归一化归档和模拟账户文件生成：
   - `YYYY-MM-DD-suggested-ETF.md`
   - `YYYY-MM-DD-trade-plan.md`
5. 用 `gen_asset_curve_html.py` 从 `YYYY-MM-DD-sim-trade-report.json` 生成
   可交互资产曲线图 `asset-curve.html`（含上证指数对比、100% 堆叠配置占比、
   买卖标记、最大回撤阴影）。脚本会自动把 `echarts.min.js` 放到当日目录, 离线可渲染。
6. 用测试和禁词扫描验证结果。

示例：

```bash
# 1) 一键构建当日预测归档 (v2 etf-hot -> v2 mtf-future + easy-tdx 回填)
python3 scripts/build_daily_archive.py --date YYYY-MM-DD

# 可选预测配置；context 缺省时按 2048 -> 1024 -> 512 选择 pro best key
python3 scripts/build_daily_archive.py --date YYYY-MM-DD \
  --horizon-len 8 --context-len 1024

skills/mtf-etf-a-share-assistant/scripts/apply_daily_trade_plan.py YYYY-MM-DD \
  --write

skills/mtf-etf-a-share-assistant/scripts/normalize_mtf_future_archive.py \
  reports/mtf-etf/YYYY-MM-DD/YYYY-MM-DD-mtf-future.json --in-place

skills/mtf-etf-a-share-assistant/scripts/render_daily_etf_outputs.py YYYY-MM-DD \
  --write --check-terms

# 生成当日可交互资产曲线图(自动放置 echarts.min.js 到当日目录)
python3 scripts/gen_asset_curve_html.py --date YYYY-MM-DD

PYTHONPATH=/tmp/mtf-exchange-calendars \
python3 -m unittest discover -s skills/mtf-etf-a-share-assistant/scripts -p 'test_*.py'
```

## Open API 调用

生产 Open API base URL：

```text
https://go-api.meetlife.com.cn/mtf-service
```

优先使用脚本调用，不直接手写请求：

```bash
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-v2-etf-hot
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py etf-quotes 510300 159919
skills/mtf-etf-a-share-assistant/scripts/get_open_api_key.sh \
  --v2 --server-name mtf-agents --user-id external-user-id
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-v2-best \
  --symbol 515880 --stock-type 2 --horizon-len 8 --context-len 2048
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-v2-future \
  --symbol 515880 --stock-type 2 --horizon-len 8 \
  --predict-date YYYY-MM-DD
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-v2-public-key
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-best-by-config --symbol 515880 --stock-type 2
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-future \
  --unique-key 515880_best_hlen_7_clen_2048_v_2.5_mtf-pro \
  --predict-date YYYY-MM-DD
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-predict-once \
  --stock-code 515880 --stock-type 2 --prediction-type mtf-pro \
  --horizon-len 7 --context-len 2048 --predict-date YYYY-MM-DD --prefer-cache
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-v2-predict-once \
  --stock-code 515880 --stock-type 2 --horizon-len 8 --context-len 2048 \
  --predict-date YYYY-MM-DD --prefer-cache
# v2 补算后轮询上面的 mtf-v2-future，不使用 v1 mtf-job 查询
```

API key 默认从 `.env.open-api` 读取。若文件不在仓库根目录，调用时显式传：

```bash
--env-file skills/mtf-etf-a-share-assistant/scripts/.env.open-api
```

不得提交 `.env.open-api`、API key、密码或其它凭证。v2 热门 ETF、best、future 和 predict 使用 `MTF_OPEN_API_V2_KEY`；v1 数据接口继续使用 `FINTRACK_OPEN_API_KEY`。
v2 key 申请使用 `GET /api/open/v2/auth/public-key` 和 RSA-OAEP-SHA256；申请密文只在请求期间存在，后续使用服务端返回的短 key。
公钥每次申请时动态获取，不在 skill 中硬编码；当前服务返回 `ciphertext_bytes=256`，短 key 长度为 50 个字符。

## 每日工作流硬规则

### 候选与预测

- ETF/基金统一按 `stock_type=2`。
- 交易筛选只使用 `prediction_type=mtf-pro`，不使用 lite 兜底。
- 每日工作流的候选直接来自 v2 `etf-hot` 返回的 `data.items`，逐个使用其 `code` 查询 v2 best 与指定日期 future；不再使用 watchlist 作为候选源。
- v2 只允许 `context_len=512/1024/2048`、`horizon_len=8/16/32/64`，默认使用 `8`；先调用 `mtf-best-by-config` 聚合并只选 `mtf_pro_unique_key`。
- 候选缺少指定日期的 future 时，使用 `mtf-v2-future` 只查缓存；cache miss 不会自动推理。
- 需要补算时必须由调用方显式执行 `mtf-v2-predict-once --prediction-type mtf-pro --predict-date YYYY-MM-DD --prefer-cache`，然后轮询相同日期的 `mtf-v2-future` 直到缓存出现；v2 没有可供客户端调用的 job 查询路由，不得改用 v1 `mtf-job`。
- v2 客户端不接收、不判断会员等级；权限由服务端 API key 统一处理。
- `watchlist` 仅用于用户明确要求的自选清单和 v1 用户级操作；每日热门 ETF 工作流不因 watchlist 内容或限制而缩小候选范围。

### 上证指数风控

每日必须获取上证指数预测：

```bash
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-v2-future \
  --symbol 000001 --stock-type 3 --horizon-len 8 --context-len 2048 \
  --predict-date YYYY-MM-DD
```

- 上证指数按 `symbol=000001`、`stock_type=3` 处理；通过 v2 best 聚合选择实际落库的 `000001_best_..._mtf-pro`，不添加 `idx` 前缀。
- 按报告日或计划执行日查找同日预计涨跌。
- 同日预计涨跌 `<= -3%` 时，大盘风控触发：当前持仓目标仓位降为 0，不新增买入或换仓承接。
- 若无法确认大盘风控，不允许新增买入或换仓，只能持有、减仓、清仓或不执行。

### 收盘价口径

`normalize_mtf_future_archive.py` 是预测归档的唯一归一化入口：

- `base_close.close` 必须使用 `base_close.date` 对齐的实际收盘价。
- 若 `base_close.date` 到预测 `target_date` 之间发生份额拆分或折算，模型原始预计涨跌必须先换成前复权可比口径：`adjusted_expected_change_percent = ((1 + raw_expected_change_percent / 100) * share_factor - 1) * 100`。
- 拆分调整后的预计涨跌路径必须保存原始路径、逐点拆分因子和已调整口径标记；重复归一化时不得再次调整。
- `predicted_close_path` 必须按 `base_close.close * (1 + expected_change_percent / 100)` 重建。
- 预测点必须使用 `target_date`，不要把基准日期、报告日期和预测目标日期混用。
- 已到达的 `target_date` 必须填入同日实际收盘价、实际涨跌幅、偏差百分点和状态。
- 不得直接比较实际价格与预测价格；只能比较同一基准下的实际涨跌幅和同日预计涨跌幅。
- 不使用 Eastmoney 作为默认历史 K 线来源；实际日 K 查询默认走 `easy-tdx`，并显式使用前复权 `QFQ`。

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
- 模拟账户日终权益和持仓市值必须使用执行日实际收盘价重估，不得用开盘成交价代替收盘估值。
- 若 ETF 发生份额拆分或折算，必须先按 `split_adjustments.json` 调整持仓份额；模型预计涨跌与实际涨跌都必须转换到同一前复权基准，不能只修正实际价格，也不能把拆分后的低价当作真实暴跌。
- 当日重复执行模拟交易时，必须替换同日期账户快照和同日期交易记录，不能重复追加。
- `YYYY-MM-DD-sim-trade-report.json` 顶层第一个字段必须是 `current_fund_performance`，直接展示最新资金、收益和当前持仓。
- “后续预计涨跌” = 末端预计涨跌 - 报告日同日预计涨跌。
- 若刷新后的下一批预测路径从报告日之后开始，只能用于后续空间估算；报告日同日偏差仍必须使用包含报告日 `target_date` 的路径或标记为待确认。
- 换仓优势 = 候选后续预计涨跌 - 当前持仓后续预计涨跌。
- 当前持仓后续预计涨跌低于 `-1%` 时，优先清仓或目标仓位归零。
- 当前持仓未转弱时，只有候选换仓优势至少 `8` 个百分点才允许一次性清仓切换。
- 当前持仓已低于退出线时，候选后续预计涨跌为正且换仓优势至少 `5` 个百分点，可清仓后买入候选。
- 预测窗口到期导致的后续空间自然归零，不是独立清仓/换仓信号；必须下一个交易日早上刷新后再重算。
- 计划生成前必须读取最新模拟账户文件，确认当前持仓、现金、总权益、仓位和清仓后可承接额度。
- 交易计划标题日期必须使用下一交易日，不得用下一自然日替代。
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
- `YYYY-MM-DD-asset-curve.html`（可交互资产曲线图）
- `echarts.min.js`（随图放置, 离线渲染依赖）

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
python3 -m pip install easy-tdx
```
