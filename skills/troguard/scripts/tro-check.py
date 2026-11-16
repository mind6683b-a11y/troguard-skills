#!/usr/bin/env python3
"""TroGuard free single-image helper. Python 3.8+ standard library only.

Default: anonymous free check for exactly one image (no API key).
With TROGUARD_API_KEY: existing API-key batch path (1-200 images).
"""

import argparse
import base64
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://app.troguard.com"
DEFAULT_ENV_FILE = Path.home() / ".config" / "troguard.env"
FREE_MAX_IMAGES = 1
MAX_IMAGES = 200
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 60 * 1024 * 1024
POLL_INTERVAL = 2.0
TERMINAL = {"succeeded", "failed", "canceled"}
RISK_ORDER = ("critical", "high", "medium", "low", "unknown")
RISK_LABEL = {
    "critical": "极高风险",
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
    "unknown": "待确认",
}
VERDICT_LABEL = {
    "likely_infringing": "高度疑似侵权",
    "possible_infringing": "疑似侵权",
    "unlikely_infringing": "未发现明显风险",
    "inconclusive": "无法判断",
}
SOURCE_LABEL = {
    "tro_case": "涉诉案件",
    "case_library": "案件库",
    "licensing_agency": "授权机构",
    "stock": "图库素材",
    "portfolio": "作品集",
    "marketplace": "电商在售",
    "brand_official": "品牌官方",
    "social": "社交平台",
    "own": "自有站点",
    "news": "其他来源",
}
RELATION_LABEL = {
    "same_image": "同一张图",
    "same_product_other_shot": "同款商品",
    "similar_style": "风格相似",
    "unrelated": "无关",
    "unknown": "未判定",
}

GET_KEY_HELP = """批量检测需要 TROGUARD_API_KEY。

免费单图不需要 Key：直接运行
  python3 scripts/tro-check.py ./pattern.png

需要批量/历史/团队时：
1. 打开 https://app.troguard.com/ 注册并验证邮箱，送 200 盾石
   （约 200 次深度检测），不需要信用卡。
2. 登录 → 左侧「Agent → Agent Skill」→ 创建 API Key。
3. 安全保存（不会回显，写入 ~/.config/troguard.env，权限 600）：

  mkdir -p ~/.config
  read -rsp "TroGuard API Key: " TROGUARD_API_KEY && echo
  (umask 077 && printf "TROGUARD_API_KEY='%s'\\n" "$TROGUARD_API_KEY" > ~/.config/troguard.env)
  unset TROGUARD_API_KEY

不会用终端？把 Key 发给 Agent，让 Agent 帮你写入配置。
脚本会自动读取 ~/.config/troguard.env；也可以 export TROGUARD_API_KEY。
直达：https://app.troguard.com/team/api-keys
批量 1 盾石/张；失败任务退还。"""


class ApiError(Exception):
    """The API returned a non-200 response."""


class NetworkError(Exception):
    """The request could not reach the API."""


def load_env_file(path: str) -> None:
    for raw in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def make_opener(no_proxy: bool) -> urllib.request.OpenerDirector:
    handlers = []
    if no_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    return urllib.request.build_opener(*handlers)


def request_json(
    opener: urllib.request.OpenerDirector,
    method: str,
    url: str,
    api_key: str = "",
    body: dict | None = None,
    extra_headers: dict | None = None,
    timeout: int = 60,
) -> tuple[int, dict]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "troguard-skill/1.1",
    }
    if api_key:
        headers["X-API-Key"] = api_key
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"message": raw[:500]}
        return error.code, payload
    except (urllib.error.URLError, ConnectionResetError, TimeoutError, ssl.SSLError) as error:
        raise NetworkError(str(error)) from error


def http_error_message(status: int, payload: dict) -> str:
    code = str(payload.get("code") or "")
    message = str(payload.get("message") or "").strip()
    if status == 401:
        return "免费检测凭证无效或已过期；批量请检查 API Key。"
    if status == 402 and code == "insufficient_credits":
        return "盾石不足，请到 https://app.troguard.com/ 充值后重试。"
    if status == 410 or code == "aipay_deprecated":
        return "402 按次支付已停用；免费单图请使用本脚本，批量请创建 API Key。"
    if code == "skill_free_active":
        return "当前 IP 已有检测在运行，请等待完成后再试。"
    if code == "skill_free_daily_limit":
        return "今日免费检测次数已用完；注册后可继续检测。"
    if code == "skill_free_global_limit":
        return "今日免费检测额度已用完，请稍后再试。"
    if status == 503:
        return message or "免费检测暂不可用，请稍后再试。"
    if status == 429:
        return message or "请求过于频繁，请稍后再试。"
    if message:
        return f"HTTP {status} {code}: {message}".strip()
    return f"HTTP {status}"


def read_image(path: str) -> tuple[Path, bytes]:
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise ValueError(f"图片不存在: {file_path}")
    data = file_path.read_bytes()
    if not data:
        raise ValueError(f"图片为空: {file_path}")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"{file_path.name} 超过 10MB（{len(data) / 1024 / 1024:.1f}MB）")
    return file_path, data


def encode_images(paths: list[str], name: str) -> tuple[list[dict], str]:
    images: list[dict] = []
    digest = hashlib.sha256()
    total = 0
    for raw in paths:
        path, data = read_image(raw)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("图片总量超过 60MB，请分批提交")
        digest.update(data)
        digest.update(b"\0")
        images.append(
            {
                "filename": path.name,
                "image_base64": base64.b64encode(data).decode("ascii"),
            }
        )
    if not 1 <= len(images) <= MAX_IMAGES:
        raise ValueError(f"一次提交 1-{MAX_IMAGES} 张图片")
    digest.update(name.encode("utf-8"))
    idempotency = "troguard-" + digest.hexdigest()[:32]
    return images, idempotency


def submit_free(
    opener: urllib.request.OpenerDirector,
    base: str,
    image: dict,
    source: str,
) -> dict:
    status, payload = request_json(
        opener,
        "POST",
        f"{base}/api/public/skill/check",
        body={
            "image_base64": image["image_base64"],
            "filename": image["filename"],
            "source": source,
        },
        timeout=180,
    )
    if status != 200 or payload.get("code") != "ok":
        raise ApiError(http_error_message(status, payload))
    data = payload.get("data") or {}
    if not data.get("batch_id") or not data.get("token"):
        raise ApiError("接口没有返回 batch_id 或 token")
    return data


def submit_batch(
    opener: urllib.request.OpenerDirector,
    base: str,
    api_key: str,
    images: list[dict],
    name: str,
    idempotency: str,
) -> dict:
    status, payload = request_json(
        opener,
        "POST",
        f"{base}/api/public/tro-check/batch",
        api_key,
        body={"name": name, "images": images},
        extra_headers={"Idempotency-Key": idempotency},
        timeout=180,
    )
    if status != 200 or payload.get("code") != "ok":
        raise ApiError(http_error_message(status, payload))
    batch = payload.get("data") or {}
    if not batch.get("id"):
        raise ApiError("接口没有返回 batch_id")
    return batch


def poll_batch(
    opener: urllib.request.OpenerDirector,
    base: str,
    batch_id: str,
    token: str,
    api_key: str,
    timeout: int,
) -> tuple[dict, dict]:
    url = f"{base}/api/public/skill/check/{batch_id}"
    if token:
        url += "?" + urllib.parse.urlencode({"token": token})
    deadline = time.time() + timeout
    while True:
        status, payload = request_json(
            opener,
            "GET",
            url,
            api_key,
            timeout=60,
        )
        if status != 200 or payload.get("code") != "ok":
            raise ApiError(http_error_message(status, payload))
        data = payload.get("data") or {}
        if token:
            batch = data.get("batch") or {}
            cta = data.get("cta") or {}
        else:
            batch = data
            cta = {}
        jobs = batch.get("jobs") or []
        complete = bool(jobs) and all(job.get("status") in TERMINAL for job in jobs)
        if complete:
            return batch, cta
        if time.time() >= deadline:
            raise TimeoutError(
                f"等待检测超时（{timeout}s），batch_id={batch_id}；可继续查询同一接口"
            )
        time.sleep(POLL_INTERVAL)


def summarize(batch: dict) -> str:
    jobs = batch.get("jobs") or []
    status = {"succeeded": 0, "failed": 0, "canceled": 0, "running": 0}
    counts = {level: 0 for level in RISK_ORDER}
    risks: list[tuple[str, str, str, str]] = []
    for job in jobs:
        job_status = job.get("status") or "unknown"
        if job_status in status:
            status[job_status] += 1
        else:
            status["running"] += 1
        result = job.get("result") or {}
        level = result.get("risk_level") or "unknown"
        if job_status == "succeeded" and level in counts:
            counts[level] += 1
            if level in {"critical", "high"}:
                evidence = result.get("evidence") or []
                title = ""
                if evidence:
                    title = str(
                        evidence[0].get("title")
                        or evidence[0].get("url")
                        or evidence[0].get("domain")
                        or ""
                    )
                risks.append(
                    (
                        str(job.get("filename") or job.get("id") or "?"),
                        level,
                        str(result.get("summary") or ""),
                        title,
                    )
                )
    lines = [
        f"batch: {batch.get('id') or '-'}",
        "任务: "
        + " · ".join(
            [
                f"成功 {status['succeeded']}",
                f"失败 {status['failed']}",
                f"取消 {status['canceled']}",
                f"进行中 {status['running']}",
            ]
        ),
        "风险: "
        + " · ".join(f"{RISK_LABEL[level]} {counts[level]}" for level in RISK_ORDER),
    ]
    if risks:
        lines.append("高风险图片:")
        for filename, level, summary, title in risks:
            lines.append(f"  - {filename} [{RISK_LABEL[level]}] {summary}")
            if title:
                lines.append(f"    证据: {title}")
    else:
        lines.append("未发现极高/高风险图片；未命中不代表没有风险，仍建议核对来源。")
    return "\n".join(lines)


def summarize_free(batch: dict, cta: dict) -> str:
    jobs = batch.get("jobs") or []
    lines = [
        f"批次: {batch.get('id') or '-'}",
        "模式: 免费单图",
        f"任务: {len(jobs)} 张",
    ]
    for job in jobs:
        status = job.get("status") or "unknown"
        lines.append("")
        lines.append(f"文件: {job.get('filename') or '-'}")
        lines.append(f"状态: {status}")
        if status != "succeeded":
            if job.get("error"):
                lines.append(f"错误: {job.get('error')}")
            continue
        result = job.get("result") or {}
        risk = result.get("risk_level") or "unknown"
        verdict = result.get("verdict") or "inconclusive"
        lines.append(f"风险: {RISK_LABEL.get(risk, risk)}")
        lines.append(f"判定: {VERDICT_LABEL.get(verdict, verdict)}")
        if isinstance(result.get("confidence"), (int, float)):
            lines.append(f"置信度: {float(result['confidence']):.2f}")
        if result.get("summary"):
            lines.append(f"结论: {result['summary']}")
        if result.get("requires_verification"):
            lines.append("需要人工复核: 是")
        evidence = result.get("evidence") or []
        if evidence:
            lines.append("证据:")
            for item in evidence:
                title = item.get("title") or item.get("url") or item.get("domain") or "来源"
                source_type = SOURCE_LABEL.get(str(item.get("source_type") or ""), "")
                relation = RELATION_LABEL.get(str(item.get("relation") or ""), "")
                meta = " · ".join(value for value in (source_type, relation) if value)
                lines.append(f"  - {title}" + (f"（{meta}）" if meta else ""))
                if item.get("url"):
                    lines.append(f"    {item['url']}")
        advice = result.get("advice") or []
        if advice:
            lines.append("建议:")
            for item in advice:
                lines.append(f"  - {item}")
    if cta:
        lines.append("")
        lines.append("——")
        lines.append(cta.get("text") or "注册后可继续检测")
        if cta.get("signup_url"):
            lines.append(f"注册: {cta['signup_url']}")
        if cta.get("api_key_url"):
            lines.append(f"API Key: {cta['api_key_url']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TroGuard：默认免费检测 1 张图；设置 API Key 后可批量。",
        epilog="示例: python3 tro-check.py ./pattern.png",
    )
    parser.add_argument("images", nargs="+", help="图片路径；免费 1 张，API Key 最多 200 张")
    parser.add_argument("--free", action="store_true", help="强制使用免费单图接口")
    parser.add_argument("--name", default="", help="批次名（API Key 批量时可选）")
    parser.add_argument("--source", default="skill", help="来源标记，默认 skill")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--env-file", default="", help="从文件读取 TROGUARD_* 环境变量")
    parser.add_argument("--timeout", type=int, default=600, help="等待检测的秒数")
    parser.add_argument("--no-proxy", action="store_true", help="不走系统代理")
    parser.add_argument("--base", default="", help="API 地址，默认 https://app.troguard.com")
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    api_key = os.environ.get("TROGUARD_API_KEY", "").strip()
    if not api_key and not args.env_file and DEFAULT_ENV_FILE.is_file():
        load_env_file(str(DEFAULT_ENV_FILE))
        api_key = os.environ.get("TROGUARD_API_KEY", "").strip()

    base = (
        args.base
        or os.environ.get("TROGUARD_API_BASE", "")
        or DEFAULT_BASE
    ).rstrip("/")
    if base.startswith("http://") and not any(
        host in base for host in ("localhost", "127.0.0.1")
    ):
        print("必须使用 https://，不要用 http://", file=sys.stderr)
        return 1

    use_free = args.free or not api_key
    if use_free and len(args.images) != FREE_MAX_IMAGES:
        print(
            f"免费检测一次只接收 {FREE_MAX_IMAGES} 张图片；批量检测请先注册并设置 API Key。",
            file=sys.stderr,
        )
        print(GET_KEY_HELP, file=sys.stderr)
        return 1
    if not use_free and not api_key:
        print(GET_KEY_HELP, file=sys.stderr)
        return 1

    try:
        images, idempotency = encode_images(args.images, args.name)
        opener = make_opener(args.no_proxy)
        if use_free:
            submitted = submit_free(opener, base, images[0], args.source)
            batch, cta = poll_batch(
                opener,
                base,
                str(submitted["batch_id"]),
                str(submitted["token"]),
                "",
                args.timeout,
            )
        else:
            batch = submit_batch(
                opener, base, api_key, images, args.name, idempotency
            )
            batch, cta = poll_batch(
                opener,
                base,
                str(batch["id"]),
                "",
                api_key,
                args.timeout,
            )
    except ValueError as error:
        print(f"参数错误：{error}", file=sys.stderr)
        return 1
    except ApiError as error:
        print(f"检测失败：{error}", file=sys.stderr)
        return 1
    except NetworkError as error:
        print(f"无法连接 TroGuard API：{error}", file=sys.stderr)
        print(
            "检查网络或代理；可加 --no-proxy；优先用本脚本而不是系统 curl。",
            file=sys.stderr,
        )
        return 1
    except TimeoutError as error:
        print(str(error), file=sys.stderr)
        return 1

    if args.json:
        if use_free:
            print(json.dumps({"batch": batch, "cta": cta}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(batch, ensure_ascii=False, indent=2))
    elif use_free:
        print(summarize_free(batch, cta))
    else:
        print(summarize(batch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
