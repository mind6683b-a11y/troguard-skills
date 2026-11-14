#!/usr/bin/env python3
"""TroGuard batch detection helper. Python 3.8+ standard library only."""

import argparse
import base64
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://app.troguard.com"
DEFAULT_ENV_FILE = Path.home() / ".config" / "troguard.env"
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

GET_KEY_HELP = """未设置 TROGUARD_API_KEY。

新用户：打开 https://app.troguard.com/ 注册并验证邮箱，送 200 盾石
（约 200 次深度检测），不需要信用卡。
已有账号：登录 → 左侧「Agent → Agent Skill」→ 创建 API Key。

安全保存（不会回显，写入 ~/.config/troguard.env）：
  mkdir -p ~/.config
  read -rsp "TroGuard API Key: " TROGUARD_API_KEY && echo
  (umask 077 && printf "TROGUARD_API_KEY='%s'\\n" "$TROGUARD_API_KEY" > ~/.config/troguard.env)
  unset TROGUARD_API_KEY

不会用终端？把 Key 发给 Agent，让 Agent 帮你写入配置。
脚本会自动读取 ~/.config/troguard.env。
直达：https://app.troguard.com/team/api-keys
1 盾石/张；失败任务退还。"""


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
    api_key: str,
    body: dict | None = None,
    extra_headers: dict | None = None,
    timeout: int = 60,
) -> tuple[int, dict]:
    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "troguard-skill/1.0",
    }
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
        return (
            "API Key 无效或已吊销，请到 "
            "https://app.troguard.com/team/api-keys 重新创建。"
        )
    if status == 402 and code == "insufficient_credits":
        return "盾石不足，请到 https://app.troguard.com/ 充值后重试。"
    if status == 410 or code == "aipay_deprecated":
        return "402 按次支付已停用，请使用 API Key 调用。"
    if status == 429:
        return "触发限流，请降低并发或稍后重试。"
    if message:
        return f"HTTP {status} {code}: {message}".strip()
    return f"HTTP {status}"


def encode_images(paths: list[str], name: str) -> tuple[list[dict], str]:
    images: list[dict] = []
    digest = hashlib.sha256()
    total = 0
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.is_file():
            raise ValueError(f"图片不存在: {path}")
        data = path.read_bytes()
        if not data:
            raise ValueError(f"图片为空: {path}")
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError(
                f"{path.name} 超过 10MB（{len(data) / 1024 / 1024:.1f}MB）"
            )
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
    api_key: str,
    batch_id: str,
    timeout: int,
) -> dict:
    deadline = time.time() + timeout
    while True:
        status, payload = request_json(
            opener,
            "GET",
            f"{base}/api/public/tro-check/{batch_id}",
            api_key,
            timeout=60,
        )
        if status != 200 or payload.get("code") != "ok":
            raise ApiError(http_error_message(status, payload))
        batch = payload.get("data") or {}
        jobs = batch.get("jobs") or []
        total = int(batch.get("total") or 0)
        complete = bool(jobs) and (total == 0 or len(jobs) >= total)
        if complete and all(job.get("status") in TERMINAL for job in jobs):
            return batch
        if time.time() >= deadline:
            raise TimeoutError(
                f"等待批次超时（{timeout}s），batch_id={batch_id}；"
                f"可继续查询 GET /api/public/tro-check/{batch_id}"
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="用 TroGuard API Key 批量检测图片的版权/TRO 风险。",
        epilog="示例: python3 tro-check.py ./pattern.png --name 上新自查",
    )
    parser.add_argument("images", nargs="+", help="图片路径，1-200 张")
    parser.add_argument("--name", default="", help="批次名，可选")
    parser.add_argument("--json", action="store_true", help="输出完整批次 JSON")
    parser.add_argument("--env-file", default="", help="从文件读取 TROGUARD_* 环境变量")
    parser.add_argument("--timeout", type=int, default=600, help="等待批次的秒数")
    parser.add_argument("--no-proxy", action="store_true", help="不走系统代理")
    parser.add_argument("--base", default="", help="API 地址，默认 https://app.troguard.com")
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    api_key = os.environ.get("TROGUARD_API_KEY", "").strip()
    if not api_key and not args.env_file and DEFAULT_ENV_FILE.is_file():
        load_env_file(str(DEFAULT_ENV_FILE))
        api_key = os.environ.get("TROGUARD_API_KEY", "").strip()
    if not api_key:
        print(GET_KEY_HELP, file=sys.stderr)
        return 1

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

    try:
        images, idempotency = encode_images(args.images, args.name)
        opener = make_opener(args.no_proxy)
        batch = submit_batch(
            opener, base, api_key, images, args.name, idempotency
        )
        batch = poll_batch(opener, base, api_key, str(batch["id"]), args.timeout)
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
        print(json.dumps(batch, ensure_ascii=False, indent=2))
    else:
        print(summarize(batch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
