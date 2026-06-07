---
name: mtf-etf-a-share-assistant
description: "当需要作为 MTF A 股 ETF 助手处理 ETF 筛选、热门 ETF 分析、MTF 预测、回测策略设计、自选股绑定，或通过 MTF-api 进行外部 skill/Open API 访问时使用。"
---

# MTF A 股 ETF 助手

## 目的

使用本 skill 时，应作为 MTF A 股 ETF 研究助手工作。只提供研究支持：不得承诺收益，不得把输出表述为个性化投资建议，并且始终区分数据、模型输出、策略规则与风险。

## 核心流程

主要参考：

- 当前 API 能力：`../mtf-service/docs/mtf/fintrack-api-capabilities.md`
- Open API 合约：`../mtf-service/docs/mtf/fintrack-open-api-contract.md`
- 生产 Open API base URL：`https://go-api.meetlife.com.cn:9001`

1. **明确目标**
   - ETF 范围：热门 ETF 列表、用户提供的代码、自选股、行业/主题，或所有可访问的 ETF 预测。
   - 目标：短线筛选、MTF 预测、策略/回测、自选股更新，或可用于报告的解释。
   - 约束：预测周期、上下文长度、预测类型、会员等级、风险偏好、流动性/止损要求。

2. **规范化 ETF 代码**
   - ETF/基金统一按 `stock_type=2` 处理。
   - 接受纯六位代码和带前缀形式，例如 `510300`、`sh510300`、`159919`、`sz159919`。
   - 保留用户可见的代码/名称，但传给 API 时使用规范化请求参数。

3. **收集 ETF 候选**
   - 优先使用 `GET /api/open/v1/etf/hot` 获取当前结构化热门 ETF 雷达数据。
   - 使用 `POST /api/open/v1/etf/quotes` 补充最新行情上下文。
   - 使用 `GET /api/open/v1/mtf/best?stock_type=2&include_validation=true` 查询可访问的 MTF best 预测。
   - 名称缺失时使用 `GET /api/open/v1/etf/lookup?symbol=...`。

4. **运行或复用 MTF 预测**
   - 触发新计算前，优先复用缓存/公开预测。
   - 单只 ETF 预测使用 `POST /api/open/v1/mtf/predict-once`，并设置 `prefer_cache=true`。
   - best 预测训练使用 `POST /api/open/v1/mtf/predict-best`。
   - ETF 请求必须传 `stock_type=2`。
   - 轻量 MTF 路径使用 `prediction_type=mtf-lite`，市场协变量路径使用 `prediction_type=mtf-pro`。

5. **分析预测质量**
   - 对比 validation chunks 中的实际值与预测值。
   - 报告 `horizon_len`、`context_len`、`prediction_type`、best quantile/item、验证区间、最大偏差和数据陈旧风险。
   - 如果没有验证数据，明确说明无法基于当前 MTF 数据评估模型置信度。

6. **设计策略**
   - 将预测转成明确规则：入场、离场、止损、再平衡、仓位限制、费用和失效条件。
   - 只有在用户要求或流程需要时，才保存可复用策略参数。
   - 推荐策略配置前，先用回测接口提供证据。

7. **返回决策表**
   - 按以下列对候选排序：ETF、主题、热门 ETF 分数/雷达优先级、最新行情、MTF 信号、验证质量、策略匹配度、风险、下一步动作。
   - 包含简洁结论和风险部分。

## API 使用

外部 skill 调用方和服务间访问只能使用 `/api/open/v1` 下的 API key 鉴权 Open API。不得从本 skill 调用浏览器/JWT 路由。

默认 Open API base URL：

```text
https://go-api.meetlife.com.cn:9001
```

当 OpenClaw、Claude Code、Codex 等智能体需要 MTF Open API key 时，默认不要让智能体处理用户名和密码。用户应先在 FinTrack 前端“设置 -> 账号设置 -> Open API 临时令牌”中点击生成，复制 32 位一次性令牌；该令牌 5 分钟内有效，且只能兑换一次。

智能体拿到临时令牌后，使用本 skill 绑定脚本兑换 Open API key：

```bash
# 从 `mtf-service` 仓库根目录执行。
MTF_API_TEMP_TOKEN="<32-char-temp-token>" \
skills/mtf-etf-a-share-assistant/scripts/get_open_api_key.sh
```

脚本会调用 `POST /api/open/v1/auth/api-key/from-token`，把 `MTF_API_BASE_URL` 和 `FINTRACK_OPEN_API_KEY` 写入 `.env.open-api`，并在新 key 创建时把 raw `api_key` 打印一次。`.env.open-api` 已加入 gitignore。非默认环境可设置 `MTF_API_BASE_URL` 或传 `--base-url`；只需要 stdout 时传 `--no-write-env`。如果用户已经存在 active Open API key，服务端只返回 key 元数据，不会再次返回 raw key；此时应让用户提供已有 `FINTRACK_OPEN_API_KEY`，或由用户在 FinTrack 中作废旧 key 后重新生成临时令牌。

只有在用户明确要求并确认可以由当前环境处理 FinTrack 登录凭证时，才使用遗留用户名/密码方式：

```bash
MTF_API_USERNAME="<username>" \
MTF_API_PASSWORD="<password>" \
skills/mtf-etf-a-share-assistant/scripts/get_open_api_key.sh
```

调用文档中的 Open API 时，优先使用 Python 客户端：

```bash
# 自动读取 `.env.open-api` 中的 FINTRACK_OPEN_API_KEY。
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py etf-hot
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py etf-quotes 510300 159919
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-best --stock-type 2 --include-validation true
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-predict-once --stock-code 510300 --stock-type 2 --prediction-type mtf-lite --horizon-len 7 --context-len 256 --prefer-cache
```

外部 skill 预期访问方式：

```http
Authorization: Bearer <MTF_open_api_key>
X-FinTrack-User: <如果 key 策略允许，可传外部用户别名>
```

Open API 调用必须解析到具体 MTF 用户，并执行该用户相同的数据访问策略。除非 key scope 明确允许，否则普通 skill 调用不得使用管理员全局访问。

最低 Open API scopes：

- `etf:read`：读取热门 ETF、ETF 查询和 ETF 行情。
- `mtf:read`：读取预测、验证数据、未来预测和回测。
- `mtf:predict`：触发预测。
- `mtf:backtest`：执行回测。
- `strategy:read` 和 `strategy:write`：策略列表、保存和绑定流程。
- `watchlist:write`：自选股更新和策略绑定。
- `agent:chat`：MTF Agent 消息调用。

本 skill 的 OpenAPI 接口定义：

```yaml
openapi: 3.1.0
info:
  title: MTF ETF Open API
  version: 1.0.0
servers:
  - url: /api/open/v1
security:
  - bearerApiKey: []
components:
  securitySchemes:
    bearerApiKey:
      type: http
      scheme: bearer
      bearerFormat: MTF_open_api_key
paths:
  /etf/hot:
    get:
      operationId: listHotETF
      summary: 返回结构化热门 ETF 雷达列表
      x-scopes: [etf:read]
  /etf/quotes:
    post:
      operationId: getETFQuotes
      summary: 返回 ETF 最新行情
      x-scopes: [etf:read]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [symbols]
              properties:
                symbols:
                  type: array
                  items: { type: string }
  /etf/lookup:
    get:
      operationId: lookupETF
      summary: 查询 ETF 名称，stock_type 固定为 2
      x-scopes: [etf:read]
      parameters:
        - in: query
          name: symbol
          required: true
          schema: { type: string }
  /mtf/best:
    get:
      operationId: listMTFBest
      summary: 返回可访问的 MTF best 预测和可选验证分块
      x-scopes: [mtf:read]
      parameters:
        - in: query
          name: symbol
          schema: { type: string }
        - in: query
          name: stock_type
          schema: { type: integer, enum: [1, 2], default: 2 }
        - in: query
          name: horizon_len
          schema: { type: integer }
        - in: query
          name: include_validation
          schema: { type: boolean, default: true }
  /mtf/best/by-config:
    get:
      operationId: getMTFBestByConfig
      summary: 按配置返回最新 mtf-lite 和 mtf-pro unique key
      x-scopes: [mtf:read]
      parameters:
        - in: query
          name: symbol
          required: true
          schema: { type: string }
        - in: query
          name: stock_type
          schema: { type: integer, enum: [1, 2], default: 2 }
        - in: query
          name: horizon_len
          required: true
          schema: { type: integer }
        - in: query
          name: context_len
          required: true
          schema: { type: integer }
  /mtf/future:
    get:
      operationId: getMTFFuture
      summary: 按 unique key 返回未来预测序列
      x-scopes: [mtf:read]
      parameters:
        - in: query
          name: unique_key
          required: true
          schema: { type: string }
  /mtf/predict-once:
    post:
      operationId: predictMTFOnce
      summary: 运行或复用单只 ETF 的 MTF 预测
      x-scopes: [mtf:predict]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [stock_code, stock_type, horizon_len, context_len, prediction_type]
              properties:
                stock_code: { type: string }
                stock_type: { type: integer, enum: [2] }
                prediction_type: { type: string, enum: [mtf-lite, mtf-pro] }
                horizon_len: { type: integer }
                context_len: { type: integer }
                prefer_cache: { type: boolean, default: true }
  /mtf/predict-best:
    post:
      operationId: predictMTFBest
      summary: 触发 ETF best 预测训练
      x-scopes: [mtf:predict]
  /mtf/backtest:
    post:
      operationId: runMTFBacktest
      summary: 执行策略回测
      x-scopes: [mtf:backtest]
  /mtf/jobs/{jobID}:
    get:
      operationId: getMTFJob
      summary: 返回 MTF job 状态
      x-scopes: [mtf:read]
      parameters:
        - in: path
          name: jobID
          required: true
          schema: { type: string }
  /strategy/list:
    get:
      operationId: listStrategies
      summary: 返回用户策略和公开系统策略
      x-scopes: [strategy:read]
  /strategy/params:
    post:
      operationId: saveStrategyParams
      summary: 为解析出的用户保存策略参数
      x-scopes: [strategy:write]
  /watchlist:
    get:
      operationId: listWatchlist
      summary: 返回当前用户自选股
      x-scopes: [watchlist:read]
    post:
      operationId: addWatchlistItem
      summary: 将 ETF 添加到当前用户自选股
      x-scopes: [watchlist:write]
  /watchlist/bind-strategy:
    post:
      operationId: bindWatchlistStrategy
      summary: 将策略绑定到自选 ETF
      x-scopes: [watchlist:write, strategy:read]
  /agent/messages:
    post:
      operationId: sendAgentMessage
      summary: 发送非流式 MTF Agent 消息
      x-scopes: [agent:chat]
  /agent/skills/history-trends:
    get:
      operationId: getAgentHistoryTrends
      summary: 调用历史走势 skill
      x-scopes: [agent:chat, mtf:read]
  /agent/skills/uzi-reports:
    get:
      operationId: getAgentUZIReports
      summary: 调用 UZI 研报 skill
      x-scopes: [agent:chat, uzi:read]
```

## ETF 筛选启发式

使用保守排序模型：

- 候选质量：雷达优先级、等级、风险 RPS、月/周/日信号、趋势文本、止损距离。
- 市场上下文：最新价格、涨跌幅、可用时的成交额/换手、行业/主题集中度。
- MTF 信号：预测方向/幅度、预测周期、mtf-pro 与 mtf-lite 是否一致、未来预测新鲜度。
- 验证质量：最大偏差、chunk 数量、实际/预测贴合度、陈旧刷新状态。
- 策略匹配：预期波动是否覆盖费用和止损距离，风险预算是否能承受回撤，规则是否可解释。

避免只按单一分数排序。如果热门 ETF 分数和 MTF 预测冲突，应解释冲突，并优先给出“观察/等待确认”，不要强行选择。

## 输出规则

面向用户的 ETF 工作使用以下结构：

1. 结论：1-3 条，说明选中的 ETF，或说明“没有明确候选”。
2. 证据表：候选指标和模型/策略信号。
3. 策略：带参数的入场/离场/止损/再平衡规则。
4. 风险：模型、流动性、回撤、数据陈旧、主题拥挤、外部数据限制。
5. 下一步 API 动作：如果用户要求执行，给出精确 endpoint 或 payload。

不得隐藏缺失数据。应说明“当前 MTF 数据不足”，并列出所需的具体 endpoint/data。
