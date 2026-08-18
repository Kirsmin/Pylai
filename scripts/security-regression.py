#!/usr/bin/env python3
"""Pylai 注册并发安全回归脚本。

真实发起 100 个并发 /api/auth/register/create 请求，验收：
  1 个成功，99 个 HTTP 409 duplicate；
  所有失败响应体不得包含成功者 UID。
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


def post(base: str, path: str, payload: dict) -> tuple[int, dict | None, str]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode()), ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = None
        return exc.code, parsed, body


def read_docker_code(container: str) -> str | None:
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", "2000", container],
            capture_output=True,
            text=True,
            timeout=10,
        )
        logs = (result.stdout or "") + (result.stderr or "")
    except Exception:
        logs = ""
    matches = re.findall(r"验证码:(\d{6})", logs)
    return matches[-1] if matches else None


def read_log_code(path: str) -> str | None:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    matches = re.findall(r"验证码:(\d{6})", text)
    return matches[-1] if matches else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="后端 API 或 Nginx 基地址")
    parser.add_argument("--email-code", default=None, help="邮箱验证码；TestMode 下可省略并从 docker logs 自动读取")
    parser.add_argument("--container", default="pylai-dev", help="读取验证码的开发容器名")
    parser.add_argument("--log-file", default=None, help="读取验证码的后端日志文件")
    parser.add_argument("--workers", type=int, default=100, help="并发注册请求数（默认 100）")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    workers = max(1, args.workers)
    stamp = int(time.time())
    email = f"race-{stamp}@pylaios.local"
    username = f"raceuser{stamp}"
    password = f"Race!{secrets.token_urlsafe(18)}A1"

    _, init_data, init_body = post(base, "/api/auth/register/init", {})
    if not init_data or not init_data.get("sessionToken"):
        print(json.dumps({"success": False, "stage": "init", "status": None, "body": init_body[:300]}, ensure_ascii=False))
        return 1
    token = init_data["sessionToken"]

    status, data, body = post(base, "/api/auth/register/send-email-code", {"sessionToken": token, "email": email})
    if status != 200 or not data or not data.get("success"):
        print(json.dumps({"success": False, "stage": "send-email-code", "status": status, "body": body[:300]}, ensure_ascii=False))
        return 1

    code = args.email_code or read_log_code(args.log_file or "") or read_docker_code(args.container)
    if not code or not re.fullmatch(r"\d{6}", code):
        print(json.dumps({"success": False, "stage": "email-code", "error": "未提供 --email-code 且无法从容器日志读取验证码"}, ensure_ascii=False))
        return 1

    status, data, body = post(base, "/api/auth/register/verify-email", {"sessionToken": token, "code": code})
    if status != 200 or not data or not data.get("success"):
        print(json.dumps({"success": False, "stage": "verify-email", "status": status, "body": body[:300]}, ensure_ascii=False))
        return 1

    status, data, body = post(base, "/api/auth/register/check-username", {"sessionToken": token, "username": username})
    if status != 200 or not data or not data.get("success"):
        print(json.dumps({"success": False, "stage": "check-username", "status": status, "body": body[:300]}, ensure_ascii=False))
        return 1

    payload = {"sessionToken": token, "password": password}

    def create() -> tuple[int, dict | None, str]:
        return post(base, "/api/auth/register/create", payload)

    results: list[tuple[int, dict | None, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(create) for _ in range(workers)]
        for future in as_completed(futures):
            results.append(future.result())

    success = [r for r in results if r[0] == 200 and r[1] and r[1].get("success")]
    conflicts = [r for r in results if r[0] == 409]
    others = [r for r in results if r[0] not in (200, 409)]

    winner_uid = success[0][1].get("uid") if success else None
    leaked = bool(winner_uid) and any(winner_uid in r[2] for r in conflicts)

    ok = len(success) == 1 and len(conflicts) == workers - 1 and not others and not leaked

    print(json.dumps({
        "success": ok,
        "workers": workers,
        "successCount": len(success),
        "conflictCount": len(conflicts),
        "otherStatuses": sorted({r[0] for r in others}),
        "failures": [{"status": r[0], "body": r[2][:300]} for r in others],
        "winnerUidLeakedInFailure": leaked,
        "stage": "create-race",
    }, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
