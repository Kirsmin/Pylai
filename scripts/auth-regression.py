#!/usr/bin/env python3
"""认证核心路径集成回归测试。

覆盖（CI 必过门禁，跑在 dev 冒烟容器上）：
  A. 登录错误处理与防枚举（不存在用户/错误密码同一错误码）
  B. 防暴力破解：连续失败触发账户锁定，锁定期内正确密码同样拒绝；
     IP 失败计数停在阈值内不触发 IP 封禁
  C. CSRF 双提交防护：用户侧写请求缺 X-CSRF-Token 必须 403 csrf_invalid，
     补签后放行；匿名/Bearer 豁免；MFA step-up 同受约束
  D. Session 撤销与改密后旧会话失效（多会话全部吊销 + 旧密码失效）
  E. AdminUI BFF CSRF 隔离（Pylaios.AdminCsrf ↔ X-CSRF-Token）
  F. OAuth PKCE 流程完整性：缺 challenge 拒绝、错误 verifier 拒绝、
     正向拿码换 token、Refresh Token 轮换后旧 token 重放拒绝
  G. MFA/WebAuthn 边界条件（Fido2 preview 专项回归）：
     TOTP enroll 强制 HTTPS、伪造 transactionId/attestation 拒绝；
     可直连后端时（--backend-url）额外覆盖 TOTP 正向注册 + 登录 step-up + 重放防护

输出单行 JSON 到 stdout（success/scenarios/failures），exit 0/1。
诊断信息走 stderr。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.cookiejar
import json
import re
import secrets as pysecrets
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler


# ══════════════════════════ HTTP 客户端 ══════════════════════════

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    """带 Cookie Jar 的最小 HTTP 客户端（自动附带用户侧 CSRF token）。"""

    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            HTTPCookieProcessor(self.jar), _NoRedirect())
        self._csrf: str | None = None

    def request(self, method: str, path: str, *, payload=None, form=None,
                headers: dict | None = None, csrf: bool = False,
                extra_headers: dict | None = None):
        url = path if path.startswith("http") else f"{self.base}{path}"
        data = None
        hdrs = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode()
            hdrs.setdefault("Content-Type", "application/json")
        elif form is not None:
            data = urllib.parse.urlencode(form).encode()
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        if csrf:
            if self._csrf is None:
                st, _, body, _ = self.request("GET", "/api/auth/csrf")
                if st != 200:
                    raise RuntimeError(f"CSRF 补签失败 status={st} body={body!r}")
                self._csrf = json.loads(body)["token"]
            hdrs["X-CSRF-Token"] = self._csrf
        if extra_headers:
            hdrs.update(extra_headers)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with self.opener.open(req, timeout=20) as resp:
                return resp.status, dict(resp.headers), resp.read().decode(errors="replace"), resp.geturl()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read().decode(errors="replace"), exc.url

    # 便捷封装：(status, parsed_json|None, raw_body)
    def get(self, path: str, **kw):
        st, _, body, _ = self.request("GET", path, **kw)
        return st, _json(body), body

    def post(self, path: str, **kw):
        kw.setdefault("payload", {})
        st, _, body, _ = self.request("POST", path, **kw)
        return st, _json(body), body

    def delete(self, path: str, **kw):
        st, _, body, _ = self.request("DELETE", path, **kw)
        return st, _json(body), body

    def raw(self, method: str, path: str, **kw):
        """返回 (status, headers, body)，供 authorize 302 Location 解析。"""
        return self.request(method, path, **kw)


def _json(body: str):
    try:
        return json.loads(body)
    except Exception:
        return None


# ══════════════════════════ 基础设施 ══════════════════════════

def read_secrets(container: str) -> dict:
    """优先读 dev 容器 .secrets（KEY='VALUE'）；拆分拓扑回退解析 /etc/pylai/pylai.toml [Seeds]。"""
    probe = subprocess.run(
        ["docker", "exec", container, "sh", "-c",
         "cat /var/lib/pylai/.secrets 2>/dev/null || true"],
        capture_output=True, text=True, timeout=15)
    out: dict[str, str] = {}
    for line in (probe.stdout or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'").strip('"')
    need = {"ADMIN_PASSWORD", "USER_PASSWORD", "MAX_PASSWORD"}
    if need <= out.keys():
        return out

    toml_raw = subprocess.run(
        ["docker", "exec", container, "cat", "/etc/pylai/pylai.toml"],
        capture_output=True, text=True, timeout=15)
    if toml_raw.returncode == 0:
        section: str | None = None
        group_map = {"DefaultAdmin": "ADMIN_PASSWORD",
                     "DefaultUser": "USER_PASSWORD",
                     "DefaultMax": "MAX_PASSWORD"}
        emails: dict[str, str] = {}
        for raw_line in toml_raw.stdout.splitlines():
            line = raw_line.strip()
            m = re.match(r"\[Seeds\.(\w+)\]", line)
            if m:
                section = m.group(1)
                continue
            if section is None:
                continue
            km = re.match(r'(Email|Password) = "(.*)"', line)
            if km:
                value = km.group(2).replace('\\"', '"').replace("\\\\", "\\")
                if km.group(1) == "Password":
                    out[group_map.get(section, f"SEED_{section}")] = value
                else:
                    emails[group_map.get(section, f"SEED_{section}")] = value
        for key, email in emails.items():
            if email:
                out[key.replace("_PASSWORD", "_USERNAME")] = email.split("@")[0].lower()
    return out


def _read_code_count(container: str) -> tuple[int, str]:
    result = subprocess.run(
        ["docker", "logs", "--tail", "3000", container],
        capture_output=True, text=True, timeout=15)
    logs = (result.stdout or "") + (result.stderr or "")
    matches = re.findall(r"验证码:(\d{6})", logs)
    return len(matches), (matches[-1] if matches else "")


def wait_new_code(container: str, before_count: int, timeout_s: float = 20) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        count, code = _read_code_count(container)
        if count > before_count and code:
            return code
        time.sleep(0.5)
    raise RuntimeError("等待邮箱验证码超时")


def register_user(client: Client, container: str) -> dict:
    """完整注册一个新 normal 用户并返回 {username,email,password,uid}。"""
    token = pysecrets.token_urlsafe(9).replace("-", "A").replace("_", "B")
    username = f"AuthRg{token}"
    email = f"{username.lower()}@regression.local"
    password = f"Rg!{pysecrets.token_urlsafe(15)}aA1"

    st, body, _ = client.post("/api/auth/register/init")
    assert st == 200 and body and body.get("sessionToken"), f"register.init 失败 {st} {body}"
    stoken = body["sessionToken"]

    before, _ = _read_code_count(container)
    st, _, raw, _ = client.request("POST", "/api/auth/register/send-email-code",
                                   payload={"sessionToken": stoken, "email": email})
    assert st == 200, f"send-email-code 失败 {st} {raw}"
    # 发码可能已同步写日志；未出现新码则轮询等待
    count_after, code = _read_code_count(container)
    if count_after <= before:
        code = wait_new_code(container, before)

    st, body, raw = client.post("/api/auth/register/verify-email",
                                payload={"sessionToken": stoken, "code": code})
    assert st == 200, f"verify-email 失败 {st} {raw}"

    st, body, raw = client.post("/api/auth/register/check-username",
                                payload={"sessionToken": stoken, "username": username})
    assert st == 200, f"check-username 失败 {st} {raw}"

    st, body, raw = client.post("/api/auth/register/create",
                                payload={"sessionToken": stoken, "password": password})
    assert st == 200 and body and body.get("uid"), f"register.create 失败 {st} {raw}"

    return {"username": username, "email": email, "password": password,
            "uid": body["uid"], "sessionToken": stoken}


def login_client(base: str, username: str, password: str) -> tuple[Client, int, dict | None]:
    c = Client(base)
    st, body, raw = c.post("/api/auth/login", payload={
        "usernameOrEmail": username, "password": password})
    return c, st, (body if isinstance(body, dict) else None)


def totp_code(secret_b32: str, step: int = 30, digits: int = 6,
              t: float | None = None, offset: int = 0) -> str:
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32.upper() + pad)
    counter = int((t or time.time()) // step) + offset
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    binary = ((digest[o] & 0x7F) << 24) | (digest[o + 1] << 16) \
        | (digest[o + 2] << 8) | digest[o + 3]
    return str(binary % (10 ** digits)).zfill(digits)


def pkce_pair() -> tuple[str, str]:
    verifier = pysecrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


# ══════════════════════════ 场景 ══════════════════════════

class Suite:
    def __init__(self, base: str, container: str,
                 secrets: dict | None = None,
                 existing: tuple[str, str] | None = None):
        self.base = base
        self.container = container
        self.secrets = secrets or {}
        self.existing = existing
        self.results: dict[str, bool] = {}
        self.failures: list[str] = []
        self.skipped: list[str] = []
        self._current = ""

    def _obtain_user(self) -> tuple[Client, str, str] | None:
        """现有账户模式直接登录；否则注册新用户。失败返回 None。"""
        c = Client(self.base)
        if self.existing:
            username, password = self.existing
            st, body, raw = c.post("/api/auth/login", payload={
                "usernameOrEmail": username, "password": password})
            if not self.check(st == 200, f"现有账户 {username} 登录应 200，实际 {st} {raw}"):
                return None
            return c, username, password
        u = register_user(c, self.container)
        st, _, raw = c.post("/api/auth/login", payload={
            "usernameOrEmail": u["username"], "password": u["password"]})
        if not self.check(st == 200, f"新用户 {u['username']} 登录应 200，实际 {st} {raw}"):
            return None
        return c, u["username"], u["password"]

    def check(self, cond: bool, msg: str) -> bool:
        if not cond:
            self.failures.append(f"[{self._current}] {msg}")
            print(f"    ✗ {msg}", file=sys.stderr)
        return cond

    def run(self, name: str, fn):
        self._current = name
        print(f"==> {name}", file=sys.stderr)
        try:
            fn()
            ok = not any(f.startswith(f"[{name}]") for f in self.failures)
        except Exception as exc:
            ok = False
            self.failures.append(f"[{name}] 异常: {exc}")
            traceback.print_exc(file=sys.stderr)
        self.results[name] = ok

    # ---- A. 登录错误处理与防枚举 ----
    def s_login_errors(self):
        c = Client(self.base)
        st, body, raw = c.post("/api/auth/login", payload={
            "usernameOrEmail": f"no-such-user-{pysecrets.token_hex(4)}@x.local",
            "password": "Whatever!123aA"})
        if not self.check(st == 401, f"不存在用户应 401，实际 {st}"):
            return
        self.check(body and body.get("errorCode") == "invalid_credentials",
                   f"不存在用户 errorCode 应为 invalid_credentials，实际 {body}")

        got = self._obtain_user()
        if got is None:
            return
        _, username, _ = got
        st, body, raw = c.post("/api/auth/login", payload={
            "usernameOrEmail": username, "password": "Wrong!Pass1aA"})
        self.check(st == 401 and body and body.get("errorCode") == "invalid_credentials",
                   f"错误密码应 401 invalid_credentials，实际 {st} {body}")
        self.check(body and "banId" in body, "invalid_credentials 应携带 banId 字段（防枚举同构响应）")

    # ---- B. 防暴力破解（账户锁定）----
    def s_brute_force_lockout(self):
        if self.existing:
            self.skipped.append("brute_force_lockout(existing)")
            return
        c = Client(self.base)
        u = register_user(c, self.container)
        # 前 4 次：invalid_credentials；第 5 次触发 LockoutEnd
        for i in range(1, 5):
            st, body, _ = c.post("/api/auth/login", payload={
                "usernameOrEmail": u["username"], "password": f"Brute!{i}aaaaA1"})
            self.check(st == 401 and body and body.get("errorCode") == "invalid_credentials",
                       f"第{i}次错误密码应 invalid_credentials，实际 {st} {body}")
        st, body, _ = c.post("/api/auth/login", payload={
            "usernameOrEmail": u["username"], "password": "Brute!5aaaaA1"})
        self.check(st == 401, f"第5次错误密码应 401，实际 {st}")
        # 锁定期内：正确密码也必须拒绝
        st, body, _ = c.post("/api/auth/login", payload={
            "usernameOrEmail": u["username"], "password": u["password"]})
        self.check(st == 401 and body and body.get("errorCode") == "locked_out",
                   f"锁定期间正确密码应 locked_out，实际 {st} {body}")
        self.check(bool(body and body.get("lockoutRemaining")),
                   "locked_out 响应应包含 lockoutRemaining")
        # 锁定期提前返回不再累计 IP 失败（IP 计数停在 5 < 10 封禁阈值）

    # ---- C. CSRF 双提交（用户侧 + MFA step-up）----
    def s_csrf(self):
        got = self._obtain_user()
        if got is None:
            return
        c, username, password = got
        self.u_csrfer = {"username": username, "password": password}

        st, body, raw = c.post("/api/auth/logout")
        self.check(st == 403 and body and body.get("errorCode") == "csrf_invalid",
                   f"无 CSRF token 的写请求应 403 csrf_invalid，实际 {st} {raw}")

        st, body, raw = c.post("/api/auth/mfa/step-up")
        self.check(st == 403 and body and body.get("errorCode") == "csrf_invalid",
                   f"MFA step-up 无 token 应 403 csrf_invalid，实际 {st} {raw}")

        st, body, raw = c.get("/api/auth/csrf")
        self.check(st == 200 and bool(body and body.get("token")),
                   f"CSRF 补签失败 {st} {raw}")
        if st != 200:
            return
        c._csrf = body["token"]

        st, body, raw = c.post("/api/auth/logout", csrf=True)  # 附带 X-CSRF-Token
        self.check(st == 200, f"带 CSRF token 的 logout 应 200，实际 {st} {raw}")
        st, body, _ = c.get("/api/auth/account")
        self.check(st == 401, f"登出后 account 应 401，实际 {st} {body}")

        # 匿名写请求豁免（login 本身无需 CSRF）
        anon = Client(self.base)
        st, _, _ = anon.post("/api/auth/login", payload={
            "usernameOrEmail": "nobody@x.local", "password": "X!1234abAB"})
        self.check(st == 401, "匿名请求应豁免 CSRF（直达认证层 401）")

    # ---- D. Session 撤销与改密后旧会话失效 ----
    def s_session_revoke_on_password_change(self):
        if self.existing:
            self.skipped.append("session_revoke_on_password_change(existing)")
            return
        c1 = Client(self.base)
        u = register_user(c1, self.container)
        new_password = f"Rp!{pysecrets.token_urlsafe(15)}bB2"
        st, _, _ = c1.post("/api/auth/login", payload={
            "usernameOrEmail": u["username"], "password": u["password"]})
        self.check(st == 200, "会话1登录失败")
        c2, st, _ = login_client(self.base, u["username"], u["password"])
        self.check(st == 200, "会话2登录失败")
        if st != 200:
            return

        st, body, _ = c1.get("/api/auth/account/sessions")
        self.check(st == 200 and isinstance(body, dict) and len(body.get("sessions", [])) >= 2,
                   f"应至少有 2 个活跃会话，实际 {st} {body}")

        st, body, raw = c1.post("/api/auth/account/change-password", csrf=True, payload={
            "currentPassword": u["password"], "newPassword": new_password})
        self.check(st == 200, f"改密应 200，实际 {st} {raw}")
        if st != 200:
            return

        st, body, raw = c1.get("/api/auth/account")
        self.check(st == 401 and body and body.get("errorCode") == "session_invalid",
                   f"改密后会话1应 401 session_invalid，实际 {st} {raw}")
        st, body, raw = c2.get("/api/auth/account")
        self.check(st == 401 and body and body.get("errorCode") == "session_invalid",
                   f"改密后会话2（并行会话）应 401 session_invalid，实际 {st} {raw}")

        _, st_old, _ = login_client(self.base, u["username"], u["password"])
        self.check(st_old == 401, "旧密码登录应 401")
        c3, st_new, body = login_client(self.base, u["username"], new_password)
        self.check(st_new == 200 and body and body.get("uid") == u["uid"],
                   f"新密码登录应 200 且 uid 一致，实际 {st_new} {body}")
        self.new_password_of_csrfer = new_password

    # ---- E. Admin BFF CSRF ----
    def s_admin_bff_csrf(self, candidates: list[tuple[str, str]]):
        if not candidates:
            self.skipped.append("admin_bff_csrf(no-credentials)")
            return
        admin = Client(self.base)
        st, body, raw = None, None, ""
        for username, password in candidates:
            st, body, raw = admin.post("/api/auth/login", payload={
                "usernameOrEmail": username, "password": password})
            if st == 200:
                break
        self.check(st == 200, f"管理账户登录失败（候选={len(candidates)}）last={st} {raw}")
        if st != 200:
            return

        st, _, _ = admin.get("/api/admin/users?skip=0&take=1")
        self.check(st == 200, f"admin 读请求应豁免 CSRF 得 200，实际 {st}")

        random_uid = (f"{pysecrets.token_hex(8)}-{pysecrets.token_hex(4)}-"
                      f"4{pysecrets.token_hex(3)}-8{pysecrets.token_hex(3)}-"
                      f"{pysecrets.token_hex(12)}")
        st, body, raw = admin.delete(f"/api/admin/users/{random_uid}")
        self.check(st == 403 and body and body.get("errorCode") == "csrf_invalid",
                   f"/api/admin 写请求无 token 应 403 csrf_invalid，实际 {st} {raw}")

        st, body, raw = admin.get("/api/admin/bff/csrf")
        self.check(st == 200 and bool(body and body.get("token")),
                   f"BFF CSRF 补签失败 {st} {raw}")
        if st != 200:
            return
        admin._csrf = body["token"]
        st, body, raw = admin.delete(f"/api/admin/users/{random_uid}", csrf=True)
        self.check(st != 403 or (body or {}).get("errorCode") != "csrf_invalid",
                   f"带 BFF token 后不应再报 csrf_invalid，实际 {st} {raw}")

    # ---- F1/F2. OAuth PKCE ----
    def _authorize(self, client: Client, challenge: str | None, state: str):
        params = {
            "response_type": "code",
            "client_id": "pylai-console",
            "redirect_uri": "https://oauthdebugger.com/debug",
            "scope": "openid profile:basic offline_access",
            "state": state,
            "nonce": pysecrets.token_hex(8),
        }
        if challenge is not None:
            params["code_challenge"] = challenge
            params["code_challenge_method"] = "S256"
        st, headers, body, url = client.raw(
            "GET", "/connect/authorize?" + urllib.parse.urlencode(params))
        return st, headers, body, url

    def s_oauth_pkce(self):
        if not self.client_secret:
            self.skipped.append("oauth_pkce(no-client-secret)")
            return
        c = Client(self.base)
        if self.existing:
            username, password = self.existing
            st, _, _ = c.post("/api/auth/login", payload={
                "usernameOrEmail": username, "password": password})
        elif getattr(self, "new_password_of_csrfer", None):
            st, _, _ = c.post("/api/auth/login", payload={
                "usernameOrEmail": self.u_csrfer["username"],
                "password": self.new_password_of_csrfer})
        else:
            u = register_user(c, self.container)
            self.u_csrfer = u
            st, _, _ = c.post("/api/auth/login", payload={
                "usernameOrEmail": u["username"], "password": u["password"]})
        self.check(st == 200, "OAuth 场景登录失败")
        if st != 200:
            return

        # 缺 PKCE → invalid_request
        st, headers, body, url = self._authorize(c, challenge=None, state="neg")
        err_txt = body if st == 400 else (headers.get("Location", "") if st in (301, 302) else "")
        self.check("invalid_request" in err_txt or (isinstance(_json(body), dict)
                   and (_json(body) or {}).get("error") == "invalid_request"),
                   f"缺 code_challenge 应 invalid_request，实际 status={st} body={body[:200]!r} loc={headers.get('Location', '')!r}")

        # 正向流程
        verifier, challenge = pkce_pair()
        state = "pkce-happy"
        st, headers, body, url = self._authorize(c, challenge, state)
        loc = headers.get("Location", "")
        self.check(st in (301, 302) and "requestId=" in loc,
                   f"首次 authorize 应 302 到 consent 页，实际 {st} {loc[:160]!r}")
        if st not in (301, 302):
            return
        request_id = urllib.parse.parse_qs(
            urllib.parse.urlparse(loc).query)["requestId"][0]

        st, body, raw = c.post("/api/auth/authorize-request/consent", csrf=True,
                               payload={"requestId": request_id, "approved": True})
        self.check(st == 200 and body and body.get("redirectUrl"),
                   f"consent 批准失败 {st} {raw}")
        if st != 200:
            return

        st, headers, body, url = c.raw("GET", body["redirectUrl"])
        loc = headers.get("Location", "")
        self.check(st in (301, 302) and "code=" in loc,
                   f"同意后应 302 携带 code，实际 {st} {loc[:160]!r}")
        if "code=" not in loc:
            return
        q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
        code = q["code"][0]
        self.check(q.get("state", [None])[0] == state, "state 应原样回传")

        # 错误 verifier → invalid_grant
        st, body, raw = c.raw("POST", "/connect/token", form={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": "https://oauthdebugger.com/debug",
            "client_id": "pylai-console", "client_secret": self.client_secret,
            "code_verifier": "wrong-verifier-" + "x" * 40})
        self.check(st in (400, 401) and isinstance(body, dict)
                   and body.get("error") == "invalid_grant",
                   f"错误 verifier 应 invalid_grant，实际 {st} {raw[:200]}")

        # 正确 verifier（重新授权拿新码：已有永久授权自动同意）
        verifier, challenge = pkce_pair()
        st, headers, _, _ = self._authorize(c, challenge, state="pkce-auto")
        loc = headers.get("Location", "")
        self.check(st in (301, 302) and "code=" in loc,
                   f"已有永久授权应跳过 consent 直接发码，实际 {st} {loc[:160]!r}")
        if "code=" not in loc:
            return
        code = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)["code"][0]
        st, body, raw = c.raw("POST", "/connect/token", form={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": "https://oauthdebugger.com/debug",
            "client_id": "pylai-console", "client_secret": self.client_secret,
            "code_verifier": verifier})
        self.check(st == 200 and isinstance(body, dict)
                   and body.get("access_token") and body.get("refresh_token"),
                   f"正确 PKCE 交换应得 access/refresh token，实际 {st} {raw[:200]}")
        if st != 200:
            return

        # Refresh 轮换：R1 → R2，R1 重放拒绝
        r1 = body["refresh_token"]
        st, body2, raw = c.raw("POST", "/connect/token", form={
            "grant_type": "refresh_token", "refresh_token": r1,
            "client_id": "pylai-console", "client_secret": self.client_secret})
        self.check(st == 200 and isinstance(body2, dict) and body2.get("refresh_token"),
                   f"refresh 应 200 换新 token，实际 {st} {raw[:200]}")
        if st != 200:
            return
        r2 = body2["refresh_token"]
        self.check(r2 != r1, "refresh token 应轮换（新旧不同）")
        st, body3, raw = c.raw("POST", "/connect/token", form={
            "grant_type": "refresh_token", "refresh_token": r1,
            "client_id": "pylai-console", "client_secret": self.client_secret})
        self.check(st in (400, 401) and isinstance(body3, dict)
                   and body3.get("error") == "invalid_grant",
                   f"旧 refresh token 重放应 invalid_grant，实际 {st} {raw[:200]}")

    # ---- G. MFA/WebAuthn 边界（Fido2 preview 专项）----
    def s_mfa_webauthn_edges(self, candidates: list[tuple[str, str]],
                             backend_url: str | None):
        m = Client(self.base)
        st = None
        max_username, max_password = candidates[0]
        for username, password in candidates:
            max_username, max_password = username, password
            st, body, raw = m.post("/api/auth/login", payload={
                "usernameOrEmail": username, "password": password})
            if st == 200:
                break
        self.check(st == 200, f"max 账户登录失败（候选={len(candidates)}）last={st} {raw}")
        if st != 200:
            return
        # MFA 端点属已认证写请求，受 Cookie-CSRF 双提交约束，先补签
        st, body, raw = m.get("/api/auth/csrf")
        if not self.check(st == 200 and bool(body and body.get("token")),
                          f"MFA 场景 CSRF 补签失败 {st} {raw}"):
            return
        m._csrf = body["token"]

        # HTTPS 强制：经 nginx(HTTP) enroll 必须 400 invalid_request
        st, body, raw = m.post("/api/auth/mfa/totp/enroll", csrf=True)
        self.check(st == 400 and body and body.get("errorCode") == "invalid_request",
                   f"HTTP 下 TOTP enroll 应 400 invalid_request（HTTPS 强制），实际 {st} {raw}")

        # WebAuthn 注册入口可达但伪造 attestation 必须拒绝
        st, body, raw = m.post("/api/auth/mfa/webauthn/registration-options", csrf=True)
        options_ok = st == 200 and body and body.get("registrationId")
        self.check(options_ok, f"WebAuthn registration-options 应 200，实际 {st} {raw[:160]}")
        if options_ok:
            st, body, raw = m.post("/api/auth/mfa/webauthn/registration", csrf=True, payload={
                "registrationId": body["registrationId"],
                "response": {"id": "forged", "rawId": "forged", "type": "public-key",
                             "response": {"attestationObject": "AAAA",
                                          "clientDataJson": "AAAA"}}})
            # 伪造 attestation 必须被拒：模型绑定失败(422)或 fido2 校验失败(400)均可
            self.check(st in (400, 422) and body and not body.get("success", True),
                       f"伪造 attestation 应被拒绝，实际 {st} {raw[:160]}")

        # 伪造事务 ID 的负路径
        st, body, raw = m.get("/api/auth/mfa/step-up/webauthn/options?transactionId=forged-tx")
        self.check(st in (400, 422) and body and body.get("errorCode") == "mfa_invalid",
                   f"伪造 step-up 事务应 mfa_invalid，实际 {st} {raw[:160]}")

        fake = Client(self.base)
        st, body, raw = fake.post("/api/auth/mfa/verify", payload={
            "transactionId": "forged-tx", "code": "123456"})
        self.check(st in (400, 401, 422) and body and body.get("errorCode") == "mfa_invalid",
                   f"伪造登录事务 verify 应 mfa_invalid，实际 {st} {raw[:160]}")

        # 直连后端时补齐 TOTP 正向流 + 重放防护（nginx 会覆写 X-Forwarded-Proto，无法经代理伪造 https）
        if not backend_url:
            print("    （未提供 --backend-url，跳过 TOTP 正向流/重放防护）", file=sys.stderr)
            return
        b = Client(backend_url)
        # 此时 max 尚未注册任何 MFA，可正常登录取得会话
        bst, bbody, raw = b.post("/api/auth/login", payload={
            "usernameOrEmail": max_username, "password": max_password})
        if not self.check(bst == 200, f"直连后端 max 登录应 200，实际 {bst} {raw[:160]}"):
            return
        st, body, raw = b.request("POST", "/api/auth/mfa/totp/enroll",
                                  extra_headers={"X-Forwarded-Proto": "https"})
        enrolled = st == 200 and body and body.get("enrollmentId")
        if not self.check(enrolled,
                          f"直连后端 + proto=https 的 enroll 应 200，实际 {st} {raw[:200]}"):
            return
        enrollment_id = body["enrollmentId"]
        secret_b32 = body["secret"]
        now = time.time()
        code_v = totp_code(secret_b32, t=now)
        st, body, raw = b.post("/api/auth/mfa/totp/confirm", csrf=True, payload={
            "enrollmentId": enrollment_id, "code": code_v})
        self.check(st == 200, f"TOTP confirm 应 200，实际 {st} {raw[:200]}")
        if st != 200:
            return

        # 启用 TOTP 后 max 登录必须 step-up
        m2, st, body = login_client(backend_url, max_username, max_password)
        self.check(st == 401 and body and body.get("errorCode") == "mfa_required"
                   and body.get("mfaTransactionId"),
                   f"启用 TOTP 后登录应 mfa_required，实际 {st} {body}")
        if st != 401:
            return
        tx = body["mfaTransactionId"]
        st, body, raw = m2.post("/api/auth/mfa/verify", csrf=True, payload={
            "transactionId": tx, "code": code_v})
        self.check(st == 200, f"首验 TOTP 码应 200 完成登录，实际 {st} {raw[:200]}")

        # 重放防护：新事务中同一时间窗的码必须被 LastTotpCounter 拒绝
        _, st2, body2 = login_client(backend_url, max_username, max_password)
        if not self.check(st2 == 401 and body2 and body2.get("mfaTransactionId"),
                          "第二次登录应再次要求 MFA"):
            return
        st, body, raw = m2.post("/api/auth/mfa/verify", csrf=True, payload={
            "transactionId": body2["mfaTransactionId"], "code": code_v})
        self.check(st in (400, 401) and body and body.get("errorCode") == "mfa_invalid",
                   f"重放同一 TOTP 码应 mfa_invalid，实际 {st} {raw[:200]}")


# ══════════════════════════ 入口 ══════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--backend-url", default=None,
                        help="直连后端地址（如 http://127.0.0.1:5000），提供时额外覆盖 TOTP 正向流与重放防护")
    parser.add_argument("--container", default="pylai-dev")
    parser.add_argument("--account", default=None,
                        help="现有账户凭据：'user:pass' 或种子别名 MAX/ADMIN/USER（提供后跳过需注册/改密的场景）")
    parser.add_argument("--only", default=None,
                        help="逗号分隔的场景名过滤（如 login_errors,csrf）；未列出的场景跳过")
    args = parser.parse_args()

    secrets = read_secrets(args.container)
    existing = None
    if args.account:
        if ":" in args.account:
            username, password = args.account.split(":", 1)
            existing = (username, password)
        else:
            prefix = args.account.upper()
            username = secrets.get(f"{prefix}_USERNAME") or {
                "MAX": "max@pylaios.local", "ADMIN": "admin@pylaios.local",
                "USER": "user@pylaios.local"}.get(prefix, "")
            password = secrets.get(f"{prefix}_PASSWORD", "")
            if not (username and password):
                print(f"--account {args.account}: 凭据缺失", file=sys.stderr)
                return 1
            existing = (username, password)

    suite = Suite(args.base_url, args.container, secrets, existing)
    suite.client_secret = secrets.get("CLIENT_SECRET", "")
    if not suite.client_secret:
        print("缺少 CLIENT_SECRET，OAuth 场景无法执行", file=sys.stderr)

    def candidates(prefix: str, default_username: str) -> list[tuple[str, str]]:
        password = secrets.get(f"{prefix}_PASSWORD", "")
        pairs: list[tuple[str, str]] = []
        custom = secrets.get(f"{prefix}_USERNAME")
        if custom and password:
            pairs.append((custom, password))
        if password:
            pairs.append((default_username, password))
        return pairs

    scenarios = [
        ("login_errors", suite.s_login_errors),
        ("brute_force_lockout", suite.s_brute_force_lockout),
        ("csrf", suite.s_csrf),
        ("session_revoke_on_password_change",
         suite.s_session_revoke_on_password_change),
        ("admin_bff_csrf", lambda: suite.s_admin_bff_csrf(
            candidates("ADMIN", "admin@pylaios.local"))),
        ("oauth_pkce", suite.s_oauth_pkce),
        ("mfa_webauthn_edges", lambda: suite.s_mfa_webauthn_edges(
            candidates("MAX", "max@pylaios.local"), args.backend_url)),
    ]
    only = {x.strip() for x in args.only.split(",")} if args.only else None
    for name, fn in scenarios:
        if only is not None and name not in only:
            suite.skipped.append(name)
            continue
        suite.run(name, fn)

    summary = {
        "success": not suite.failures,
        "scenarios": suite.results,
        "skipped": suite.skipped,
        "failures": suite.failures,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
