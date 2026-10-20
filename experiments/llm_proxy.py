#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM API 本地透明代理（域名接管模式）

配合 /etc/hosts 使用：
    127.0.0.1 llmapi.evolventapi.com

客户端继续访问 http://llmapi.evolventapi.com/...，流量实际进入本代理；
代理自动剥离上游不支持的参数（如 OpenAI 专有的 `store`，Anthropic 后端
不支持会报 UnsupportedParamsError），并注入 `drop_params: true`，然后
通过【真实 IP + Host 头】直连上游服务器（绕过 /etc/hosts，避免回环）。

真实 IP 通过 DoH（AliDNS/Cloudflare）定期解析，支持多 IP 故障切换，
也可用环境变量 UPSTREAM_IPS 硬编码兜底。

环境变量：
    HOST            监听地址（默认 127.0.0.1）
    PORT            监听端口（默认 80）
    UPSTREAM_HOST   上游域名（默认 llmapi.evolventapi.com）
    UPSTREAM_PORT   上游端口（默认 80）
    UPSTREAM_IPS    逗号分隔的兜底真实 IP（DoH 失败时使用）
    TIMEOUT         上游读写超时秒数（默认 600）
    REFRESH_SECS    DoH 刷新间隔（默认 300）
"""
import http.client
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "80"))
UPSTREAM_HOST = os.environ.get("UPSTREAM_HOST", "llmapi.evolventapi.com")
UPSTREAM_PORT = int(os.environ.get("UPSTREAM_PORT", "80"))
FALLBACK_IPS = [ip.strip() for ip in os.environ.get("UPSTREAM_IPS", "").split(",") if ip.strip()]
TIMEOUT = int(os.environ.get("TIMEOUT", "600"))
REFRESH_SECS = int(os.environ.get("REFRESH_SECS", "300"))

DOH_URLS = [
    "https://dns.alidns.com/resolve?name={h}&type=A",
    "https://cloudflare-dns.com/dns-query?name={h}&type=A",
]

# 转发前直接删除的参数（OpenAI 专有、Anthropic 后端已知不支持）
STRIP_PARAMS = {"store"}
# 注入到请求体的 LiteLLM 选项：自动丢弃上游不支持的任何参数
INJECT_PARAMS = {"drop_params": True}

# 请求方向不透传的头（Content-Length 由 http.client 按改写后的 body 重算）
REQ_DROP_HEADERS = {
    "connection", "keep-alive", "transfer-encoding", "te", "trailers",
    "proxy-authorization", "proxy-authenticate", "upgrade", "host",
    "content-length", "expect",
}
# 响应方向不透传的头（响应体按连接关闭分界；content-encoding 保留透传）
RESP_DROP_HEADERS = {
    "connection", "keep-alive", "transfer-encoding", "te", "trailers",
    "proxy-authorization", "proxy-authenticate", "upgrade", "content-length",
}

_lock = threading.Lock()
_current_ips = list(FALLBACK_IPS) or None


def _log(msg):
    print(f"[proxy] {msg}", flush=True)


def doh_resolve():
    """通过 DoH 解析上游真实 IP（绕过本机 /etc/hosts）"""
    for url in DOH_URLS:
        try:
            req = urllib.request.Request(
                url.format(h=UPSTREAM_HOST),
                headers={"Accept": "application/dns-json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode())
            ips = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
            if ips:
                return ips
        except Exception:
            continue
    return None


def refresh_ips(force_log=False):
    global _current_ips
    ips = doh_resolve()
    if ips:
        with _lock:
            if ips != _current_ips:
                _log(f"上游真实IP更新: {ips}")
            _current_ips = ips
        return ips
    if force_log:
        _log(f"DoH 解析失败，继续使用 {_current_ips or FALLBACK_IPS}")
    return None


def get_ips():
    with _lock:
        return list(_current_ips) if _current_ips else list(FALLBACK_IPS)


def upstream_request(method, path, headers, body):
    """按真实 IP + Host 头直连上游；全部失败时刷新 DNS 再试一轮"""
    attempts = []

    def _try(ips):
        for ip in ips:
            conn = http.client.HTTPConnection(ip, UPSTREAM_PORT, timeout=TIMEOUT)
            try:
                h = dict(headers)
                h["Host"] = UPSTREAM_HOST
                h["Connection"] = "close"
                conn.request(method, path, body=body, headers=h)
                resp = conn.getresponse()
                return resp, conn, ip
            except Exception as e:
                attempts.append(f"{ip}: {type(e).__name__}")
                try:
                    conn.close()
                except Exception:
                    pass
        return None

    result = _try(get_ips())
    if result:
        return result
    refresh_ips(force_log=True)
    result = _try(get_ips())
    if result:
        return result
    raise ConnectionError(f"上游全部不可达 [{'; '.join(attempts)}]")


def clean_body(body):
    """剥离不兼容参数、注入 drop_params；非 JSON 请求体原样返回"""
    try:
        data = json.loads(body)
    except Exception:
        return body, []
    if not isinstance(data, dict):
        return body, []
    removed = [p for p in STRIP_PARAMS if p in data]
    for p in removed:
        del data[p]
    injected = [k for k, v in INJECT_PARAMS.items() if data.get(k) != v]
    data.update(INJECT_PARAMS)
    if removed or injected:
        return json.dumps(data, ensure_ascii=False).encode(), removed
    return body, []


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self, method, body):
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in REQ_DROP_HEADERS}
        if body:
            body, removed = clean_body(body)
            if removed:
                _log(f"剥离参数 {removed} (model={self._model()})")
        try:
            resp, conn, ip = upstream_request(method, self.path, headers, body)
        except Exception as e:
            self._relay_exception(e)
            return
        _log(f"{method} {self.path} -> {resp.status} (上游 {ip})")
        try:
            self._relay(resp)
        except (BrokenPipeError, ConnectionResetError):
            _log("客户端提前断开")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _model(self):
        # 仅用于日志，失败忽略
        try:
            return json.loads(self._last_body).get("model", "?")
        except Exception:
            return "?"

    def _relay(self, resp):
        """把上游响应逐块转发给客户端（支持 SSE 流式）"""
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in RESP_DROP_HEADERS:
                self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()
        while True:
            chunk = resp.read1(65536)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()
        self.close_connection = True

    def _relay_exception(self, e):
        _log(f"上游连接失败: {type(e).__name__}: {e}")
        payload = json.dumps({
            "error": {"message": f"proxy: upstream unreachable ({type(e).__name__}: {e})",
                      "type": "proxy_error", "code": 502}
        }).encode()
        self.send_response(502)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def do_GET(self):
        self._last_body = b""
        self._forward("GET", None)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        self._last_body = self.rfile.read(length) if length else b""
        self._forward("POST", self._last_body or None)

    def log_message(self, fmt, *args):  # 静默默认访问日志
        pass


def main():
    refresh_ips(force_log=True)
    print(f"[proxy] LLM 透明代理已启动", flush=True)
    print(f"[proxy] 监听:   http://{HOST}:{PORT} （域名接管模式）", flush=True)
    print(f"[proxy] 上游:   http://{UPSTREAM_HOST}:{UPSTREAM_PORT} "
          f"(真实IP: {get_ips()})", flush=True)
    print(f"[proxy] 剥离:   {sorted(STRIP_PARAMS)}  注入: {INJECT_PARAMS}", flush=True)

    def _refresher():
        while True:
            time.sleep(REFRESH_SECS)
            refresh_ips()

    threading.Thread(target=_refresher, daemon=True).start()

    server = ThreadingHTTPServer((HOST, PORT), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[proxy] 已停止", flush=True)


if __name__ == "__main__":
    main()
