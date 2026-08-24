# ============================================================================
# 网页配置编辑器（config web-edit / 主菜单 [7] 置顶入口）
# ============================================================================
def find_free_port() -> int:
    """获取一个 127.0.0.1 上当前无占用的端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def generate_editor_password() -> str:
    """临时密码：前四位大写字母，后四位数字，例如 PAHE-0123。"""
    letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    digits = "".join(secrets.choice(string.digits) for _ in range(4))
    return f"{letters}-{digits}"


def editor_value_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    return "string"


def serialize_editor_value(change: Json) -> str:
    """把网页端提交的 JSON 值序列化为 TOML 字面量。"""
    kind = change.get("type")
    value = change.get("value")

    if kind == "boolean":
        return "true" if value else "false"
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ManageError(f"数值类型非法: {value!r}")
        return str(value)
    if kind == "array":
        items = value if isinstance(value, list) else []
        parts = [
            str(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else toml_str(str(x))
            for x in items
        ]
        return f"[{', '.join(parts)}]"
    return toml_str("" if value is None else str(value))


def strip_multiline_value(text: str, marker: str, key: str) -> str:
    """替换多行字符串（''' / \"\"\"）前，先移除其续行，避免残留导致 TOML 非法。"""
    try:
        start, end = _toml_section_span(text, marker)
    except ValueError:
        return text

    block = text[start:end]
    lines = block.splitlines(keepends=True)
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(?P<rhs>.*)$")

    for index, line in enumerate(lines):
        match = key_re.match(line)
        if not match:
            continue
        rhs = match.group("rhs")
        opener = re.match(r"^('''|\"\"\")", rhs)
        if not opener or opener.group(1) in rhs[3:]:
            return text  # 单行值，无需处理
        quote = opener.group(1)
        for tail in range(index + 1, len(lines)):
            if quote in lines[tail]:
                del lines[index + 1 : tail + 1]
                break
        return text[:start] + "".join(lines) + text[end:]

    return text


class ConfigEditorServer(ThreadingHTTPServer):
    """仅监听 127.0.0.1 的一次性配置编辑器服务。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int, password: str) -> None:
        self.password = password
        self.token = secrets.token_hex(16)
        super().__init__(("127.0.0.1", port), ConfigEditorHandler)


class ConfigEditorHandler(BaseHTTPRequestHandler):
    server: ConfigEditorServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    # ---- 基础工具 ----
    def _send_json(self, payload: Json, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Json:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1 << 20:
            raise ManageError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManageError(f"请求不是合法 JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ManageError("请求体必须是 JSON 对象")
        return data

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self.server.token}"

    # ---- 路由 ----
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            body = CONFIG_EDITOR_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/config":
            if not self._authorized():
                self._send_json({"error": "未授权"}, 401)
                return
            try:
                self._send_json(self._config_payload())
            except ManageError as exc:
                self._send_json({"error": str(exc)}, 500)
            return

        self._send_json({"error": "Not Found"}, 404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]

        try:
            data = self._read_json()
        except ManageError as exc:
            self._send_json({"error": str(exc)}, 400)
            return

        if path == "/api/auth":
            if secrets.compare_digest(str(data.get("password", "")), self.server.password):
                self._send_json({"token": self.server.token})
            else:
                time.sleep(0.5)  # 减缓口令爆破
                self._send_json({"error": "临时密码错误"}, 401)
            return

        if path == "/api/save":
            if not self._authorized():
                self._send_json({"error": "未授权"}, 401)
                return
            try:
                preview = self._apply_changes(data.get("changes"))
            except ManageError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"ok": True, "preview": preview})
            return

        self._send_json({"error": "Not Found"}, 404)

    # ---- 业务 ----
    def _config_payload(self) -> Json:
        if not CONFIG_FILE.is_file():
            raise ManageError("配置文件不存在")

        text = CONFIG_FILE.read_text(encoding="utf-8")
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"配置解析失败: {exc}") from exc

        sections: list[Json] = []

        def visit(path: str, table: Json) -> None:
            entries = []
            for key, value in table.items():
                if isinstance(value, dict):
                    continue
                entries.append({
                    "key": key,
                    "type": editor_value_kind(value),
                    "value": value,
                    "secret": bool(re.search(r"Password|Secret|ConnectionString", key, re.IGNORECASE)),
                })
            if entries:
                sections.append({"name": path, "entries": entries})
            for key, value in table.items():
                if isinstance(value, dict):
                    visit(f"{path}.{key}" if path else key, value)

        for key, value in parsed.items():
            if isinstance(value, dict):
                visit(key, value)

        return {
            "path": str(CONFIG_FILE),
            "sections": sections,
            "preview": mask_config_text(text),
        }

    def _apply_changes(self, changes: Any) -> str:
        if not CONFIG_FILE.is_file():
            raise ManageError("配置文件不存在")
        if not isinstance(changes, list) or not changes:
            raise ManageError("没有需要提交的变更")
        if len(changes) > 500:
            raise ManageError("单次变更过多")

        text = CONFIG_FILE.read_text(encoding="utf-8")
        t = TomlText(text)

        for change in changes:
            if not isinstance(change, dict):
                raise ManageError("变更格式非法")
            section = str(change.get("section", ""))
            key = str(change.get("key", ""))
            if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*", section):
                raise ManageError(f"非法的配置段落: {section!r}")
            if not re.fullmatch(r"[A-Za-z0-9_]+", key):
                raise ManageError(f"非法的配置键: {key!r}")

            marker = f"[{section}]"
            t.text = strip_multiline_value(t.text, marker, key)
            t.set(marker, key, serialize_editor_value(change), required=True)

        new_text = str(t)
        try:
            tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"变更后配置不是合法 TOML，已放弃写入: {exc}") from exc

        atomic_write(CONFIG_FILE, new_text)
        return mask_config_text(new_text)


