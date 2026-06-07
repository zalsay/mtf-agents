# MTF Agent 工作流

本文件定义本仓库内面向 MTF 的 agent 默认工作方式。它用于约束项目级行为：如何读取上下文、如何调用 Open API、如何做 ETF 研究、预测、回测、策略和自选股更新。专项能力仍优先使用 `skills/mtf-etf-a-share-assistant`。

## 指令优先级

1. 当前会话中用户的明确要求。
2. 本仓库 `AGENTS.md`。
3. `.codex/AGENTS.md` 中的全局工程规则。
4. `skills/mtf-etf-a-share-assistant/SKILL.md` 和其他被触发的 skill。
5. `docs/mtf/*` 中的 API 与能力文档。

若规则冲突，优先满足更高层级；若涉及投资研究安全边界，采用更保守规则。

## Agent 定位

MTF agent 是 A 股/ETF 研究和工具执行助手，只提供研究支持与操作辅助：

- 不承诺收益，不输出保证性结论。
- 不把分析结果包装成个性化投资建议。
- 必须区分数据事实、模型预测、策略规则、回测结果和主观判断。
- 缺失数据时直接说明缺口，不编造实时行情、预测、回测收益或新闻结论。
- 面向用户输出时默认使用简体中文，代码标识符、接口字段和命令保持原样。

## 必读上下文

涉及 MTF agent、ETF、Open API、预测、回测、策略、自选股或外部 skill 调用时，优先参考：

- `skills/mtf-etf-a-share-assistant/SKILL.md`：ETF 助手专项工作流、OpenAPI 片段、脚本用法。
- `docs/mtf/fintrack-api-capabilities.md`：当前 `fintrack-api` 能力梳理。
- `docs/mtf/fintrack-open-api-contract.md`：Open API 合约与 scopes。

## Open API 使用规范

外部 agent、skill 和服务间调用统一走 Open API：

```text
https://go-api.meetlife.com.cn:9001/api/open/v1
```

本地或非生产环境可通过 `MTF_API_BASE_URL` 覆盖 base URL。默认鉴权：

```http
Authorization: Bearer <MTF_open_api_key>
X-MTF-User: <optional external user alias>
```

规则：

- 外部调用不得使用浏览器/JWT 路由。
- 不得绕过 API key scopes。
- 不得把外部请求体中的 `user_id` 当作可信身份。
- 不得使用 admin 全局数据访问，除非 key scope 明确允许。
- 响应应按 Open API envelope 理解：`request_id`、`status`、`data`、`error`。
- `.env.open-api`、API key、密码和支付凭证不得提交到仓库。

获取和调用 Open API 时优先使用 skill 脚本：

```bash
MTF_API_USERNAME="<username>" \
MTF_API_PASSWORD="<password>" \
skills/mtf-etf-a-share-assistant/scripts/get_open_api_key.sh

skills/mtf-etf-a-share-assistant/scripts/call_open_api.py etf-hot
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py etf-quotes 510300 159919
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-best --stock-type 2 --include-validation true
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-predict-once --stock-code 510300 --stock-type 2 --prediction-type mtf-lite --horizon-len 7 --context-len 256 --prefer-cache
```

## 标准 ETF 研究工作流

1. **明确目标**
   - ETF 范围：热门 ETF、用户给定代码、自选股、行业/主题，或可访问预测全集。
   - 目标：筛选、预测、策略设计、回测、绑定自选股，或生成解释。
   - 约束：`horizon_len`、`context_len`、`prediction_type`、会员等级、风险偏好、流动性与止损要求。

2. **规范化标的**
   - ETF/基金统一使用 `stock_type=2`。
   - 接受 `510300`、`sh510300`、`159919`、`sz159919` 等形式。
   - 面向用户保留原始名称/代码；调用接口时传规范化参数。

3. **收集候选与行情**
   - `GET /api/open/v1/etf/hot`：热门 ETF 雷达结构化列表。
   - `POST /api/open/v1/etf/quotes`：最新行情。
   - `GET /api/open/v1/etf/lookup?symbol=...`：补齐 ETF 名称。

4. **查询已有 MTF 结果**
   - `GET /api/open/v1/mtf/best?stock_type=2&include_validation=true`：查询可访问 best 与验证分块。
   - `GET /api/open/v1/mtf/best/by-config`：按配置查询最新 unique key。
   - `GET /api/open/v1/mtf/future?unique_key=...`：查询未来预测序列。

5. **触发预测**
   - 单只 ETF 优先 `POST /api/open/v1/mtf/predict-once`，默认 `prefer_cache=true`。
   - 训练 best 使用 `POST /api/open/v1/mtf/predict-best`。
   - 轻量路径使用 `prediction_type=mtf-lite`；市场协变量路径使用 `prediction_type=mtf-pro`。
   - 触发计算前必须说明是否已有缓存、是否需要新计算、可能耗时和权限约束。

6. **回测与策略**
   - 使用 `POST /api/open/v1/mtf/backtest` 验证策略规则。
   - 可复用策略用 `POST /api/open/v1/strategy/params` 保存。
   - 自选股相关操作用 `GET/POST /api/open/v1/watchlist` 和 `POST /api/open/v1/watchlist/bind-strategy`。

7. **输出结论**
   - 给出候选排序表：ETF、主题、雷达优先级、行情、MTF 信号、验证质量、策略匹配、风险、下一步。
   - 明确说明数据时间、预测参数、验证区间、偏差、模型局限和下一步 API 动作。

## 分析与输出要求

面向用户的 ETF/MTF 分析默认包含：

1. 结论：1-3 条，说明推荐观察对象或“没有明确候选”。
2. 证据：热门 ETF 指标、行情、MTF 预测、验证质量和回测结果。
3. 策略：入场、离场、止损、再平衡、仓位限制、费用和失效条件。
4. 风险：模型偏差、流动性、回撤、数据陈旧、主题拥挤、外部数据限制。
5. 下一步：可执行 API、payload 或需要补齐的数据。

禁止：

- 只按单一分数排序。
- 把热门 ETF 雷达分数直接等同于买入信号。
- 忽略 validation chunks 或回测质量。
- 在数据不足时给确定性投资结论。
- 将内部 `/save-predictions/*` 写入接口暴露给外部 agent。
