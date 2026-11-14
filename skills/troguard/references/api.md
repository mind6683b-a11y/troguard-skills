# TroGuard 公开检测 API

Base URL：`https://app.troguard.com`

所有请求使用 API Key：

```http
X-API-Key: trk_...
```

或：

```http
Authorization: Bearer trk_...
```

API Key 在 <https://app.troguard.com/team/api-keys> 创建；完整 Key 只显示一次。调用按团队盾石计费，1 盾石/张，失败任务退还。

402 按次支付通道已停用：没有 API Key 调用单图接口会返回 410 `aipay_deprecated`，不会创建账单。

## 批量检测（推荐）

```http
POST /api/public/tro-check/batch
Content-Type: application/json
X-API-Key: trk_...
Idempotency-Key: optional-8-64-chars
```

```json
{
  "name": "上新自查",
  "images": [
    { "filename": "a.png", "image_base64": "..." },
    { "filename": "b.jpg", "image_base64": "..." }
  ]
}
```

- 一次 1–200 张；每张解码后 ≤10MB；请求体 ≤82MB。
- `name` 可选，≤120 字符。
- `Idempotency-Key` 可选，8–64 位字母、数字或 `-_.:`；同一团队 + 用户 + Key 重复请求返回同一批次，不重复扣盾石。
- 成功 200：

```json
{
  "code": "ok",
  "message": "success",
  "data": { "id": "...", "total": 2, "jobs": [] },
  "billing": "credits",
  "credit_balance": 198,
  "already_submitted": false
}
```

`data.id` 就是 `batch_id`。检测是异步的，需要轮询。

## 批量检测（multipart）

```http
POST /api/public/tro-check/batch/upload
Content-Type: multipart/form-data
X-API-Key: trk_...
```

- 文件字段名 `images`，可重复；`name` 可选。
- 适合大图或不想做 Base64 的客户端。
- 其余限制与 JSON 批量接口一致。

## 单图检测

```http
POST /api/public/tro-check
Content-Type: application/json
X-API-Key: trk_...
```

```json
{
  "image_base64": "...",
  "filename": "pattern.png",
  "name": "可选批次名"
}
```

- 请求体 ≤16MB；单张解码后 ≤10MB。
- 成功 200，返回 `billing: "credits"` 和 `credit_balance`。
- 无 API Key 返回 410 `aipay_deprecated`。
- 盾石不足返回 402 `insufficient_credits`。

## 轮询批次

```http
GET /api/public/tro-check/{batch_id}
X-API-Key: trk_...
```

返回 `BatchView`：

```json
{
  "code": "ok",
  "data": {
    "id": "...",
    "total": 2,
    "created_at": "2026-11-14T12:00:00",
    "jobs": [
      {
        "id": "...",
        "filename": "a.png",
        "status": "succeeded",
        "result": {
          "risk_level": "critical",
          "verdict": "likely_infringing",
          "summary": "...",
          "confidence": 0.92,
          "evidence": [
            {
              "title": "...",
              "url": "...",
              "domain": "...",
              "source_type": "tro_case",
              "relation": "same_image",
              "relation_confidence": 0.95
            }
          ],
          "advice": ["..."]
        }
      }
    ]
  }
}
```

任务状态：`pending` / `dispatching` / `queued` / `running` / `succeeded` / `failed` / `canceled`。全部进入 `succeeded` / `failed` / `canceled` 后停止轮询。

风险等级：`critical` / `high` / `medium` / `low` / `unknown`。同图命中 TRO 案件库时通常为 `critical`。

## 限流

- 单图：每分钟 60 次、120 张（按 Key）。
- 批量：每分钟 20 次、1000 张（按 Key）。
- 超出返回 429 `too_many_requests`。

## 错误

| HTTP / code | 含义 | 处理 |
|---|---|---|
| 401 `unauthorized` | Key 无效、已吊销、用户或团队不可用 | 重新创建 Key |
| 402 `insufficient_credits` | 盾石不足 | 充值后重试 |
| 410 `aipay_deprecated` | 没有 API Key；402 按次支付已停用 | 改用 API Key |
| 400 `invalid_input` | 图片格式/大小不对、参数非法 | 修正请求 |
| 429 `too_many_requests` | 触发限流 | 降低并发或稍后重试 |
| 502 / 503 | 检测服务暂不可用 | 稍后重试；不要重复扣费 |

## 网络

- 始终使用 `https://app.troguard.com`，不要用 `http://`。80 端口在备案完成前可能被拦截并返回 403。
- 部分 macOS 自带 curl（SecureTransport）或中间网络可能重置 TLS 握手，表现为 `curl: (35) Recv failure`。优先使用 `scripts/tro-check.py`（Python/OpenSSL）或支持 TLS 1.3 的客户端。
- 沙箱代理报 `CONNECT tunnel failed, response 502` 时，加 `--no-proxy` 或在沙箱外运行。
