#!/usr/bin/env python3
"""TroGuard free single-image report helper. Python 3.8+ standard library only."""

import argparse
import base64
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://app.troguard.com"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
POLL_INTERVAL = 2.0
TERMINAL = {"succeeded", "failed", "canceled"}
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
COMPLIANCE_CATEGORY_LABEL = {
    "violence_gore_crime_weapons_suicide": "暴力、血腥、犯罪、武器与自杀内容",
}


class ApiError(Exception):
    """The service returned a non-200 response."""


class NetworkError(Exception):
    """The request could not reach the service."""


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
    body: dict | None = None,
    timeout: int = 60,
) -> tuple[int, dict]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "troguard-skill/1.2.2",
    }
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


def error_message(status: int, payload: dict) -> str:
    code = str(payload.get("code") or "")
    message = str(payload.get("message") or "").strip()
    if status == 401:
        return "免费检测凭证无效或已过期，请重新检测。"
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


def submit_free(
    opener: urllib.request.OpenerDirector,
    base: str,
    filename: str,
    data: bytes,
    source: str,
) -> dict:
    status, payload = request_json(
        opener,
        "POST",
        f"{base}/api/public/skill/check",
        body={
            "image_base64": base64.b64encode(data).decode("ascii"),
            "filename": filename,
            "source": source,
        },
        timeout=180,
    )
    if status != 200 or payload.get("code") != "ok":
        raise ApiError(error_message(status, payload))
    result = payload.get("data") or {}
    if not result.get("batch_id") or not result.get("token"):
        raise ApiError("接口没有返回 batch_id 或 token")
    return result


def poll_free(
    opener: urllib.request.OpenerDirector,
    base: str,
    batch_id: str,
    token: str,
    timeout: int,
) -> tuple[dict, dict]:
    url = f"{base}/api/public/skill/check/{batch_id}?token={token}"
    deadline = time.time() + timeout
    while True:
        try:
            status, payload = request_json(opener, "GET", url, timeout=60)
        except NetworkError:
            if time.time() >= deadline:
                raise
            time.sleep(POLL_INTERVAL)
            continue
        if status in {500, 502, 503, 504}:
            if time.time() >= deadline:
                raise ApiError(
                    "服务暂时不可用；不要重新提交，保留 batch_id/token 继续轮询"
                )
            time.sleep(POLL_INTERVAL)
            continue
        if status != 200 or payload.get("code") != "ok":
            raise ApiError(error_message(status, payload))
        data = payload.get("data") or {}
        batch = data.get("batch") or {}
        cta = data.get("cta") or {}
        jobs = batch.get("jobs") or []
        if jobs and all(job.get("status") in TERMINAL for job in jobs):
            return batch, cta
        if time.time() >= deadline:
            raise TimeoutError(
                f"等待检测超时（{timeout}s），batch_id={batch_id}；可继续查询同一接口"
            )
        time.sleep(POLL_INTERVAL)


def image_lines(batch: dict) -> list[str]:
    """把相关图片放在报告最前面，便于直接内嵌。"""
    lines: list[str] = []
    for job in batch.get("jobs") or []:
        filename = str(job.get("filename") or job.get("id") or "图")
        result = job.get("result") or {}
        for item in result.get("evidence") or []:
            thumbnail = str(item.get("thumbnail") or "")
            if thumbnail:
                title = str(
                    item.get("title")
                    or item.get("url")
                    or item.get("domain")
                    or "证据"
                )
                lines.append(f"![{title}]({thumbnail})")
        image_url = str(job.get("image_url") or "")
        if image_url:
            lines.append(f"![原图：{filename}]({image_url})")
    return lines[:5]


def summarize(batch: dict, cta: dict) -> str:
    jobs = batch.get("jobs") or []
    media = image_lines(batch)
    lines = ["## TroGuard 检测报告", ""]
    if media:
        lines.extend(["### 相关图片", *media, ""])
    lines.extend(
        [
            f"批次: {batch.get('id') or '-'}",
            f"模式: 免费单图 · {len(jobs)} 张",
            "",
        ]
    )
    for job in jobs:
        status = job.get("status") or "unknown"
        lines.append(f"### 文件：{job.get('filename') or '-'}")
        lines.append(f"状态: {status}")
        if status != "succeeded":
            if job.get("error"):
                lines.append(f"错误: {job.get('error')}")
            lines.append("")
            continue
        result = job.get("result") or {}
        risk = result.get("risk_level") or "unknown"
        verdict = result.get("verdict") or "inconclusive"
        lines.append(f"风险等级: {RISK_LABEL.get(risk, risk)}")
        lines.append(f"判定: {VERDICT_LABEL.get(verdict, verdict)}")
        compliance = result.get("compliance")
        if isinstance(compliance, dict):
            if compliance.get("violation"):
                level = str(compliance.get("risk_level") or "")
                categories = "、".join(
                    COMPLIANCE_CATEGORY_LABEL.get(str(item), str(item))
                    for item in (compliance.get("categories") or [])
                    if item
                )
                terms = "、".join(
                    str(item) for item in (compliance.get("matched_terms") or []) if item
                )
                detail = " · ".join(
                    value
                    for value in (
                        RISK_LABEL.get(level, level),
                        categories,
                        f"命中 {terms}" if terms else "",
                    )
                    if value
                )
                lines.append(f"平台合规: {detail or '命中'}")
                if compliance.get("visible_text"):
                    lines.append(f"识别文字: {compliance['visible_text']}")
                if compliance.get("reason"):
                    lines.append(f"合规原因: {compliance['reason']}")
            else:
                lines.append("平台合规: 未发现明显违规")
        if isinstance(result.get("confidence"), (int, float)):
            lines.append(f"置信度: {float(result['confidence']):.2f}")
        if result.get("summary"):
            lines.append(f"结论: {result['summary']}")
        if result.get("requires_verification"):
            lines.append("人工复核: 建议人工复核")
        evidence = result.get("evidence") or []
        if evidence:
            lines.append("")
            lines.append("### 证据")
            for item in evidence:
                title = item.get("title") or item.get("url") or item.get("domain") or "来源"
                source_type = SOURCE_LABEL.get(str(item.get("source_type") or ""), "")
                relation = RELATION_LABEL.get(str(item.get("relation") or ""), "")
                meta = " · ".join(value for value in (source_type, relation) if value)
                lines.append(f"- {title}" + (f"（{meta}）" if meta else ""))
                if item.get("url"):
                    lines.append(f"  {item['url']}")
        advice = result.get("advice") or []
        if advice:
            lines.append("")
            lines.append("### 建议")
            for item in advice:
                lines.append(f"- {item}")
        lines.append("")
    if cta:
        lines.append("---")
        lines.append(cta.get("text") or "注册后可继续检测")
        if cta.get("signup_url"):
            lines.append(f"注册: {cta['signup_url']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TroGuard：免费检测 1 张图，输出检测报告和内嵌图片。",
        epilog="示例: python3 tro-check.py ./pattern.png",
    )
    parser.add_argument("images", nargs="+", help="图片路径；免费检测只接收 1 张")
    parser.add_argument("--source", default="skill", help="来源标记，默认 skill")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--timeout", type=int, default=600, help="等待检测的秒数")
    parser.add_argument("--no-proxy", action="store_true", help="不走系统代理")
    parser.add_argument("--base", default="", help="服务地址，默认 https://app.troguard.com")
    args = parser.parse_args()

    if len(args.images) != 1:
        print("免费检测一次只接收 1 张图片。", file=sys.stderr)
        return 1

    base = (args.base or DEFAULT_BASE).rstrip("/")
    if base.startswith("http://") and not any(
        host in base for host in ("localhost", "127.0.0.1")
    ):
        print("必须使用 https://，不要用 http://", file=sys.stderr)
        return 1

    try:
        path, data = read_image(args.images[0])
        opener = make_opener(args.no_proxy)
        submitted = submit_free(opener, base, path.name, data, args.source)
        batch, cta = poll_free(
            opener,
            base,
            str(submitted["batch_id"]),
            str(submitted["token"]),
            args.timeout,
        )
    except ValueError as error:
        print(f"参数错误：{error}", file=sys.stderr)
        return 1
    except ApiError as error:
        print(f"检测失败：{error}", file=sys.stderr)
        return 1
    except NetworkError as error:
        print(f"无法连接 TroGuard：{error}", file=sys.stderr)
        print(
            "检查网络或代理；可加 --no-proxy；优先用本脚本而不是系统 curl。",
            file=sys.stderr,
        )
        return 1
    except TimeoutError as error:
        print(str(error), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"batch": batch, "cta": cta}, ensure_ascii=False, indent=2))
    else:
        print(summarize(batch, cta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
