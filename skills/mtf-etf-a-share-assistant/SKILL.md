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
   - 使用 `GET /api/open/v1/watchlist` 确认当前 API key 用户关注清单；该清单只作为当前 MTF 读取权限状态，不作为 ETF 候选范围硬限制。
   - 热门 ETF 或用户明确给出的 ETF 若不在关注清单，但需要读取 MTF 预测，可调用 `POST /api/open/v1/watchlist` 自动加入关注清单后继续查询；不要批量加入全部热门 ETF，只加入已通过行情初筛、需要进入 MTF 阶段的少量候选。
   - 使用 `GET /api/open/v1/mtf/best?stock_type=2&include_validation=true` 查询已在关注清单内且可访问的 MTF best 预测。
   - 名称缺失时使用 `GET /api/open/v1/etf/lookup?symbol=...`。

4. **运行或复用 MTF 预测**
   - 触发新计算前，优先复用缓存/公开预测。
   - 查询 `mtf/best`、`mtf/best/by-config`、`mtf/future` 前，必须确认 `symbol` 或 `unique_key` 对应标的在当前用户关注清单内；不在关注清单时，若该标的来自热门 ETF 初筛或用户明确指定，可直接调用 `watchlist-add` 自动添加后继续，不要因原 watchlist 较窄而停止筛选。
   - 先调用 `GET /api/open/v1/mtf/best/by-config?symbol=<code>&stock_type=2`，不传 `horizon_len` 和 `context_len`，读取该标的所有可用配置的聚合 key 列表。
   - 如果 `mtf/best/by-config` 返回 `not_found` 或聚合列表为空，说明该标的当前没有 best unique key；此时不要直接跳到 `predict-once`。应先调用 `POST /api/open/v1/mtf/predict-best` 发起 best 模型训练，读取响应中的 `estimated_inference_time_sec`，等待预计时间后再查询 `mtf-job` 状态；job 成功后再次查询 `mtf/best/by-config` 获取 unique key。
   - 任何返回 `job_id` 的异步请求都遵循预计时间等待规则：优先使用响应中的 `estimated_inference_time_sec`，若该字段为空则使用 `queue_status` 和默认短等待；到预计时间前不要频繁查询 `mtf-job`。到点后若仍为 `queued`/`running`，再按低频间隔继续查询。
   - 从聚合 key 列表中只选择 `mtf_pro_unique_key`；缺少 pro key、pro 训练失败或 pro future 不可用时，剔除该候选，不再请求或使用 `mtf_lite_unique_key`。
   - 用户明确指定 `horizon_len` 或 `context_len` 时，可把任一参数单独传给 `mtf-best-by-config` 做过滤；两个参数都传时查询更精确的单配置/配置子集。
   - best 预测训练使用 `POST /api/open/v1/mtf/predict-best`；适用于无 best unique key、best 过期或需要重新训练配置的场景。
   - 单只 ETF 续跑或复用 future 前的补算使用 `POST /api/open/v1/mtf/predict-once`，并设置 `prefer_cache=true`；适用于已有 best unique key 后，从 best 验证末端续跑到当前可用 chunk 的场景。
   - ETF 请求必须传 `stock_type=2`。
   - ETF 交易筛选只使用市场协变量路径 `prediction_type=mtf-pro`；不要为了交易决策请求 `mtf-lite`。

5. **分析预测质量**
   - `GET /api/open/v1/mtf/future?unique_key=...` 返回后，优先读取 `predicted_change_percent`。这是 MTF 交易研究里的核心预测涨跌幅字段，用于衡量未来 `horizon_len` 序列的方向和幅度。
   - `predicted_change_percent` 是数组时，末值代表预测周期末相对 `change_base_value` 的涨跌幅；同时观察数组路径是否连续走强、走弱或震荡。若接口返回单值，按周期末预测涨跌幅处理。
   - 同一标的同时有 `mtf_pro_unique_key` 和 `mtf_lite_unique_key` 时，只使用 `mtf_pro_unique_key` 调用 `mtf-future`，不再做 lite/pro 对比；缺少 pro key 或 pro future 不可用时，剔除该候选。
   - 对比 validation chunks 中的实际值与预测值。
   - 报告 `horizon_len`、`context_len`、`prediction_type`、best quantile/item、验证区间、最大偏差和数据陈旧风险。
   - 如果没有验证数据，明确说明无法基于当前 MTF 数据评估模型置信度。

6. **设计策略**
   - 将预测转成明确规则：入场、离场、止损、再平衡、仓位限制、费用和失效条件。
   - 默认把 `predicted_change_percent` 作为交易动作分层依据：末值明显为正且路径改善时可列为“候选/确认”，接近 0 或路径震荡时列为“观察”，为负且走弱时列为“回避/减仓观察”。具体阈值需结合 ETF 波动、费用、止损距离和用户风险约束。
   - 只有在用户要求或流程需要时，才保存可复用策略参数。
   - 推荐策略配置前，先用回测接口提供证据。

7. **返回决策表**
   - 按以下列对候选排序：ETF、主题、热门 ETF 分数/雷达优先级、最新行情、实际采用的预测类型、`predicted_change_percent` 周期末值和路径、验证质量、策略匹配度、风险、下一步动作。
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

脚本会调用 `POST /api/open/v1/auth/api-key/from-token`，把 `MTF_API_BASE_URL` 和 `FINTRACK_OPEN_API_KEY` 写入 `.env.open-api`，并把 raw `api_key` 打印一次。`.env.open-api` 已加入 gitignore。非默认环境可设置 `MTF_API_BASE_URL` 或传 `--base-url`；只需要 stdout 时传 `--no-write-env`。临时令牌一次性、5 分钟有效；服务端会为兑换请求新建 active key 并返回 raw key。

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
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py mtf-predict-once --stock-code 510300 --stock-type 2 --prediction-type mtf-pro --horizon-len 7 --context-len 2048 --prefer-cache
skills/mtf-etf-a-share-assistant/scripts/call_open_api.py strategy-save --json @strategy.json
```

外部 skill 预期访问方式：

```http
Authorization: Bearer <MTF_open_api_key>
X-FinTrack-User: <如果 key 策略允许，可传外部用户别名>
X-Request-Id: <可选调用方请求 ID>
```

Open API 调用必须解析到具体 MTF 用户，并执行该用户相同的数据访问策略。除非 key scope 明确允许，否则普通 skill 调用不得使用管理员全局访问。

最低 Open API scopes：

- `etf:read`：读取热门 ETF、ETF 查询和 ETF 行情。
- `mtf:read`：读取预测、验证数据、未来预测和回测。
- `mtf:predict`：触发预测。
- `mtf:backtest`：执行回测。
- `strategy:read` 和 `strategy:write`：策略列表、保存和绑定流程。
- `watchlist:write`：自选股更新和策略绑定。
- `watchlist:read`：读取自选股。
- `uzi:read`：查询 UZI 报告索引和摘要；当前 ETF skill 没有专门 UZI 子命令，需要时使用 `call_open_api.py raw` 或后续扩展脚本。

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
      summary: 返回关注清单内可访问的 MTF best 预测和可选验证分块
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
      summary: 返回关注清单内聚合配置 key 列表，或按指定配置返回最新 mtf-lite 和 mtf-pro unique key
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
          required: false
          schema: { type: integer }
        - in: query
          name: context_len
          required: false
          schema: { type: integer }
      x-parameter-rules:
        - horizon_len 和 context_len 都不传：按 symbol + stock_type 返回所有可用配置的聚合 key 列表。
        - 只传 horizon_len：返回该 horizon 下的可用配置 key。
        - 只传 context_len：返回该 context 下的可用配置 key。
        - 两者都传：返回更精确的单配置/配置子集查询。
  /mtf/future:
    get:
      operationId: getMTFFuture
      summary: 按 unique key 反查并校验关注清单后返回未来预测序列
      x-scopes: [mtf:read]
      parameters:
        - in: query
          name: unique_key
          required: true
          schema: { type: string }
      x-signal-fields:
        predicted_change_percent: 预测涨跌幅，交易研究的核心方向/幅度字段；数组末值代表预测周期末涨跌幅。
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
      requestBody:
        description: 复用 SaveStrategyParamsRequest；服务端覆盖 user_id。
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
```

推荐编排：

1. `GET /etf/hot` 获取热门 ETF 候选池。
2. `POST /etf/quotes` 补充行情。
3. `GET /watchlist` 确认当前用户关注清单；若候选不在关注清单，先让用户确认是否 `POST /watchlist` 添加。
4. `GET /mtf/best/by-config?symbol=<code>&stock_type=2` 不传 horizon/context，获取该标的所有可用配置的聚合 key 列表。
5. 只选择可用 `mtf_pro_unique_key`；缺少 pro 或 pro future 不可用时剔除该候选。如果用户指定周期/上下文，则只查询并使用对应单配置的 pro key。
6. `GET /mtf/future?unique_key=...` 读取所选 key 的 `predicted_change_percent`。
7. 必要时 `GET /mtf/best?stock_type=2&include_validation=true` 查询关注清单内已有 best 与 validation，用于质量说明。
8. 对缺失 best unique key 的标的，先调用 `POST /mtf/predict-best`；若响应返回 `job_id`，读取 `estimated_inference_time_sec` 并等待预计时间后再调用 `GET /mtf/jobs/{job_id}`。job `succeeded` 后重新查询 `/mtf/best/by-config` 获取 unique key；若 best 训练失败，记录失败原因并剔除该候选。
9. 拿到 unique key 后调用 `GET /mtf/future?unique_key=...`；若 future 返回异步 `job_id`，同样按 `estimated_inference_time_sec` 等待后再查 job。若 future 不可用但 best key 已存在，可调用 `POST /mtf/predict-once` 并设置 `prefer_cache=true` 从 best `val_end_date` 续跑到当前可用 chunk。
10. `POST /mtf/backtest` 验证策略参数。
11. `POST /strategy/params` 保存策略。
12. `POST /watchlist/bind-strategy` 更新用户工作台策略绑定。

## ETF 筛选启发式

使用保守排序模型：

- 候选质量：雷达优先级、等级、风险 RPS、月/周/日信号、趋势文本、止损距离。
- 市场上下文：最新价格、涨跌幅、可用时的成交额/换手、行业/主题集中度。
- MTF 信号：预测方向/幅度、预测周期、pro 预测类型、未来预测新鲜度；只使用 pro，不要求与 lite 对比。
- 交易指导信号：优先读取 `predicted_change_percent`，使用周期末值判断预期方向和幅度，使用数组路径判断趋势质量；不得只看 `predicted_latest` 或单一价格点。
- 验证质量：最大偏差、chunk 数量、实际/预测贴合度、陈旧刷新状态。
- 策略匹配：预期波动是否覆盖费用和止损距离，风险预算是否能承受回撤，规则是否可解释。

避免只按单一分数排序。如果热门 ETF 分数和 MTF 预测冲突，应解释冲突，并优先给出“观察/等待确认”，不要强行选择。

## 输出规则

面向用户的 ETF 工作使用以下结构：

1. 结论：1-3 条，说明选中的 ETF，或说明“没有明确候选”。
2. 证据表：候选指标和模型/策略信号。
3. 策略：带参数的入场/离场/止损/再平衡规则，必须说明采用 pro，并给出 `predicted_change_percent` 周期末值和路径特征。
4. 风险：模型、流动性、回撤、数据陈旧、主题拥挤、外部数据限制。
5. 下一步 API 动作：如果用户要求执行，给出精确 endpoint 或 payload。

不得隐藏缺失数据。应说明“当前 MTF 数据不足”，并列出所需的具体 endpoint/data。
