# TroGuard 免费单图接口

Base：`https://app.troguard.com`

免费通道只接收 **1 张图**，返回完整单图检测报告；批量、历史、团队协作在 app 内。

## 提交检测

```http
POST /api/public/skill/check
Content-Type: application/json
```

```json
{
  "image_base64": "iVBORw0KGgo...",
  "filename": "pattern.png",
  "source": "skill"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `image_base64` | string | 是 | 图片 base64；解码后 ≤10MB，请求体 ≤16MB |
| `filename` | string | 否 | 文件名，默认 `image` |
| `source` | string | 否 | 来源标记，默认 `skill` |

成功：

```json
{
  "code": "ok",
  "message": "",
  "data": {
    "batch_id": "a1b2c3d4e5f6...",
    "token": "long-random-token",
    "expires_at": "2026-11-15T10:00:00Z",
    "signup_url": "https://app.troguard.com/?utm_source=skill&utm_medium=agent&utm_campaign=free_check"
  }
}
```

- 免费检测不扣盾石。
- 同一 IP 同时只能有 1 个检测在跑；每 IP 每日 50 次，全局每日 500 次，每分钟 3 次。
- 结果只在本次 `token` 有效期内可查；不返回历史。

## 查询结果

```http
GET /api/public/skill/check/{batch_id}?token={token}
```

```json
{
  "code": "ok",
  "data": {
    "batch": {
      "id": "a1b2c3d4e5f6...",
      "status": "succeeded",
      "jobs": [
        {
          "id": "job-1",
          "filename": "pattern.png",
          "status": "succeeded",
          "image_url": "https://...",
          "result": {
            "risk_level": "high",
            "verdict": "likely_infringing",
            "confidence": 0.82,
            "compliance": {
              "violation": false,
              "risk_level": "low",
              "categories": [],
              "matched_terms": [],
              "reason": "未发现平台合规风险"
            },
            "summary": "命中案件库同图，疑似侵犯他人印花版权。",
            "evidence": [
              {
                "title": "TATIANA ... / 26-cv-2438",
                "url": "https://...",
                "domain": "cases.troguard.com",
                "source_type": "tro_case",
                "relation": "same_image",
                "relation_confidence": 0.91,
                "thumbnail": "https://..."
              }
            ],
            "advice": ["核对权利人授权", "上架前下架或替换"],
            "requires_verification": true
          }
        }
      ]
    },
    "cta": {
      "text": "注册送 200 盾石，可看历史、批量检测和团队协作",
      "signup_url": "https://app.troguard.com/?utm_source=skill&utm_medium=agent&utm_campaign=free_check"
    }
  }
}
```

`data.batch` 是完整 `BatchView`；`data.cta` 用于引导注册。批量/历史入口在 app 内。

## 字段

| 字段 | 说明 |
|---|---|
| `batch.status` | `pending` / `running` / `completed` / `failed` / `canceled` |
| `jobs[].status` | `pending` / `dispatching` / `queued` / `running` / `succeeded` / `failed` / `canceled` |
| `result.risk_level` | 综合风险（版权 + 平台合规）：`critical` / `high` / `medium` / `low` / `unknown` |
| `result.verdict` | 版权/IP 判定：`likely_infringing` / `possible_infringing` / `unlikely_infringing` / `inconclusive` |
| `result.confidence` | 0–1 |
| `result.compliance.violation` | 是否命中平台合规违禁；true 时不要上架 |
| `result.compliance.risk_level` | 合规风险：`high` / `medium` / `low` |
| `result.compliance.categories[]` | 规则类别，目前为 `violence_gore_crime_weapons_suicide` |
| `result.compliance.visible_text` | 上传图中逐字转写的可见文字 |
| `result.compliance.matched_terms[]` | 命中的违禁词，如 `MURDER`、`自杀` |
| `result.compliance.reason` | 合规原因 |
| `result.summary` | 一句话结论 |
| `result.evidence[]` | 来源标题、URL、域名、类型、匹配关系、缩略图 |
| `result.advice[]` | 处理建议 |
| `result.requires_verification` | 是否建议人工复核 |
| `jobs[].image_url` | 原图签名 URL |
| `evidence[].thumbnail` | 案件库/证据缩略图签名 URL |

## 错误

| 状态 | code | 说明 |
|---|---|---|
| 400 | `invalid_input` | 图片格式/大小不对，或参数非法 |
| 401 | `unauthorized` | 免费 `token` 无效/过期 |
| 429 | `skill_free_active` | 当前 IP 已有检测在跑 |
| 429 | `skill_free_daily_limit` | 当前 IP 今日免费次数用完 |
| 429 | `too_many_requests` | 请求过于频繁 |
| 503 | `skill_free_global_limit` | 今日全局免费额度用完 |
| 503 | `skill_free_unavailable` | 免费通道暂未开放 |

## 网络

- 只支持 `https://app.troguard.com`；不要用 `http://`。
- 大陆网络下 `curl` / 部分 TLS 客户端可能握手重置；优先用 `scripts/tro-check.py`，或换 TLS 1.3 客户端。
- 公司代理环境可加 `--no-proxy`。
