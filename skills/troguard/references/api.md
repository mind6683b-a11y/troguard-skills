# TroGuard 公开检测 API

Base URL：`https://app.troguard.com`

## 免费单图（不需要 API Key）

```http
POST /api/public/skill/check
Content-Type: application/json

{"image_base64":"...","filename":"pattern.png","source":"skill"}
```

- 只接收 1 张图；单张解码后 ≤10MB；请求体 ≤16MB；不接受批量
- 同一 IP 同时只能有 1 个检测在跑；每 IP 每日免费次数有限（默认 3 次）；全局每日也有上限
- 成功 200：

```json
{
  "code": "ok",
  "data": {
    "batch_id": "...",
    "token": "...",
    "expires_at": "2026-11-17T12:00:00",
    "signup_url": "https://app.troguard.com/?utm_source=skill&utm_medium=agent&utm_campaign=free_single&src=free_skill"
  }
}
```

轮询（无需 API Key，token 绑定 batch_id + IP + 过期时间）：

```http
GET /api/public/skill/check/{batch_id}?token=...
```

返回完整 `BatchView` + CTA：

```json
{
  "code": "ok",
  "data": {
    "batch": { "id": "...", "total": 1, "jobs": [{ "status": "succeeded", "result": { "...": "完整结果" } }] },
    "cta": {
      "text": "注册送 200 盾石，查看历史、批量检测和团队协作",
      "signup_url": "...",
      "free_credits": 200,
      "api_key_url": "https://app.troguard.com/team/api-keys"
    }
  }
}
```

免费限制：

- 单图、无批量、单张 ≤10MB
- 同一 IP 同时 1 个检测；每 IP 每日默认 3 次；每分钟默认 3 次
- 全局每日默认 200 次；超过后返回 503
- `SKILL_FREE_ENABLED=false` 时返回 503，API Key 批量不受影响

## 批量检测（API Key，推荐注册后使用）

所有批量请求使用 API Key：

```http
X-API-Key: trk_...
```

或：

```http
Authorization: Bearer trk_...
```

API Key 在 <https://app.troguard.com/team/api-keys> 创建；完整 Key 只显示一次。批量按团队盾石计费，1 盾石/张，失败任务退还；注册送 200 盾石。

### JSON 批量

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

- 一次 1–200 张；每张解码后 ≤10MB；请求体 ≤82MB
- `Idempotency-Key` 可选，8–64 位字母、数字或 `-_.:`；同一团队 + 用户 + Key 重复请求返回同一批次，不重复扣盾石
- 成功 200：

```json
{
  "code": "ok",
  "data": { "id": "...", "total": 2, "jobs": [] },
  "billing": "credits",
  "credit_balance": 198,
  "already_submitted": false
}
```

### multipart 批量

```http
POST /api/public/tro-check/batch/upload
Content-Type: multipart/form-data
X-API-Key: trk_...
```

- 文件字段名 `images`，可重复；`name` 可选
- 适合大图或不想做 Base64 的客户端
- 其余限制与 JSON 批量接口一致

### 单图（API Key）

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

- 请求体 ≤16MB；单张解码后 ≤10MB
- 成功 200，返回 `billing: "credits"` 和 `credit_balance`
- 无 API Key 返回 410 `aipay_deprecated`；免费单图请用 `/api/public/skill/check`
- 盾石不足返回 402 `insufficient_credits`

## 轮询（API Key 批量）

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

- 免费单图：同一 IP 同时 1 个；每 IP 每日默认 3 次；每分钟默认 3 次；全局每日默认 200 次。
- API Key 单图：每分钟 60 次、120 张（按 Key）。
- API Key 批量：每分钟 20 次、1000 张（按 Key）。
- 超出返回 429；免费全局额度/通道关闭返回 503。

## 错误

| HTTP / code | 含义 | 处理 |
|---|---|---|
| 429 `skill_free_active` | 当前 IP 已有检测在跑 | 等当前检测完成后重试 |
| 429 `skill_free_daily_limit` | 今日免费次数用完 | 展示注册 CTA；注册后继续 |
| 503 `skill_free_global_limit` | 今日全局免费额度用完 | 稍后再试 |
| 503 `skill_free_unavailable` | 免费通道暂未开放 | 稍后再试；批量用 API Key |
| 401 `unauthorized` | 免费 token 无效/过期，或 API Key 无效 | 免费重跑；批量重新创建 Key |
| 402 `insufficient_credits` | 批量盾石不足 | 充值后重试 |
| 410 `aipay_deprecated` | 没有 API Key 调用旧单图接口 | 免费用 skill；批量创建 API Key |
| 400 `invalid_input` | 图片格式/大小不对、参数非法 | 修正请求 |
| 429 `too_many_requests` | 触发限流 | 降低并发或稍后重试 |
| 502 / 503 | 检测服务暂不可用 | 稍后重试；不要重复扣费 |

## 网络

- 始终使用 `https://app.troguard.com`，不要用 `http://`。80 端口在备案完成前可能被拦截并返回 403。
- 部分 macOS 自带 curl（SecureTransport）或中间网络可能重置 TLS 握手，表现为 `curl: (35) Recv failure`。优先使用 `scripts/tro-check.py`（Python/OpenSSL）或支持 TLS 1.3 的客户端。
- 沙箱代理报 `CONNECT tunnel failed, response 502` 时，加 `--no-proxy` 或在沙箱外运行。
