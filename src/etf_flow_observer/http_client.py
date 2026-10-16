"""带限速、磁盘缓存和失败重试的 HTTP 客户端。只使用 IPv4。

这个环境里到部分站点的 IPv6 不可达。强制 IPv4 是为了能连上公开网页，
不是为了隐藏来源。每次真实往返和每次缓存复用都会留下原始响应记录。
"""

from __future__ import annotations

import hashlib
import http.client
import json
import socket
import ssl
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from email.message import Message

from etf_flow_observer.errors import ObserverError
from etf_flow_observer.storage import Store
from etf_flow_observer.timing import SHANGHAI


class IPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        infos = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
        if not infos:
            raise OSError(f"没有 IPv4 地址: {self.host}")
        last: Exception | None = None
        for family, socktype, proto, _, sockaddr in infos:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(self.timeout)
            try:
                sock.connect(sockaddr)
                context = self._context or ssl.create_default_context()
                self.sock = context.wrap_socket(sock, server_hostname=self.host)
                return
            except Exception as exc:  # 换下一个 A 记录
                last = exc
                sock.close()
        raise last or OSError(f"连接失败: {self.host}")


@dataclass
class FetchResult:
    url: str
    method: str
    status: int | None
    body: bytes
    text: str
    fetched_at: datetime
    from_cache: bool
    raw_id: int
    error: str | None
    network_fetched_at: datetime
    cache_accessed_at: datetime | None = None
    request_started_at: datetime | None = None

    def json(self) -> object:
        return json.loads(self.text, parse_float=Decimal, parse_int=Decimal)


class HttpClient:
    def __init__(
        self,
        store: Store,
        *,
        user_agent: str,
        min_interval_seconds: float,
        timeout_seconds: float,
        max_retries: int,
        cache_ttl_seconds: int,
        max_http_requests: int,
        sleeper=time.sleep,
        clock=None,
        transport=None,
    ):
        self.store = store
        self.user_agent = user_agent
        self.min_interval_seconds = min_interval_seconds
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_http_requests = max_http_requests
        self.sleeper = sleeper
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.transport = transport
        self.http_calls = 0

    def send(
        self,
        method: str,
        url: str,
        *,
        source_name: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        use_cache: bool = True,
    ) -> FetchResult:
        method = method.upper()
        fingerprint = hashlib.sha256(
            b"\n".join([method.encode(), url.encode(), body or b""])
        ).hexdigest()
        now = self.clock()
        if use_cache:
            cached = self.store.latest_success(fingerprint)
            if cached is not None:
                fetched = datetime.fromisoformat(cached["network_fetched_at"] or cached["fetched_at"])
                age = (now - fetched).total_seconds()
                path = cached["body_path"]
                if age <= self.cache_ttl_seconds and path:
                    payload = open(path, "rb").read()
                    self.store.save_raw(
                        source_name=source_name,
                        fingerprint=fingerprint,
                        method=method,
                        url=url,
                        request_body=_body_text(body),
                        http_status=200,
                        body=None,
                        fetched_at=fetched,
                        from_cache=True,
                        error=None,
                        existing_body_path=path,
                        content_sha256=cached["content_sha256"],
                        network_fetched_at=fetched,
                        cache_accessed_at=now,
                        attempt_no=0,
                    )
                    return FetchResult(
                        url=url,
                        method=method,
                        status=200,
                        body=payload,
                        text=_decode(payload, Message()),
                        fetched_at=fetched,
                        from_cache=True,
                        raw_id=int(cached["id"]),
                        error=None,
                        network_fetched_at=fetched,
                        cache_accessed_at=now,
                    )

        host = urllib.parse.urlsplit(url).hostname or ""
        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Connection": "close",
        }
        if headers:
            request_headers.update(headers)

        last_error = "没有发出请求"
        status: int | None = None
        payload = b""
        response_headers = Message()
        raw_id = 0
        request_started_at = now
        network_at = now
        for attempt in range(1, self.max_retries + 1):
            if self.http_calls >= self.max_http_requests:
                raise ObserverError(
                    f"这一轮 HTTP 请求已到上限 {self.max_http_requests}，停止以免连续打接口"
                )
            delay = self._attempt_delay(host, attempt)
            if delay > 0:
                self.sleeper(delay)
            # 请求开始 ≠ 响应完整到达。transport 里推进时钟时必须能测出这两点不同。
            request_started_at = self.clock()
            self.store.mark_host(host, request_started_at)
            self.http_calls += 1
            try:
                status, response_headers, payload = self._once(
                    method, url, request_headers, body
                )
                if status in {429, 500, 502, 503, 504}:
                    last_error = f"HTTP {status}"
                else:
                    last_error = ""
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                status = None
                payload = b""
            network_at = self.clock()
            error = _attempt_error(last_error, status, response_headers)
            raw_id = self.store.save_raw(
                source_name=source_name,
                fingerprint=fingerprint,
                method=method,
                url=url,
                request_body=_body_text(body),
                http_status=status,
                body=payload,
                fetched_at=network_at,
                from_cache=False,
                error=error,
                network_fetched_at=network_at,
                cache_accessed_at=None,
                attempt_no=attempt,
                request_started_at=request_started_at,
            )
            retryable = status in {429, 500, 502, 503, 504} or status is None
            if error is None or not retryable or attempt >= self.max_retries:
                break

        text = _decode(payload, response_headers)
        final_error = None if status == 200 and last_error == "" else _attempt_error(last_error, status, response_headers)
        return FetchResult(
            url=url,
            method=method,
            status=status,
            body=payload,
            text=text,
            fetched_at=network_at,
            from_cache=False,
            raw_id=raw_id,
            error=final_error,
            network_fetched_at=network_at,
            cache_accessed_at=None,
            request_started_at=request_started_at,
        )

    def _attempt_delay(self, host: str, attempt: int) -> float:
        """两次真实请求至少间隔配置的最小间隔，重试不能比这个更短。"""
        wait = self.store.reserve_host(host, self.min_interval_seconds, self.clock())
        if attempt == 1:
            return wait
        return max(wait, float(self.min_interval_seconds))

    def _once(self, method: str, url: str, headers: dict[str, str], body: bytes | None):
        if self.transport is not None:
            return self.transport(method, url, headers, body)
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https":
            raise ObserverError(f"只访问 https: {url}")
        port = parts.port or 443
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        connection = IPv4HTTPSConnection(parts.hostname, port, timeout=self.timeout_seconds)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            return response.status, response.headers, payload
        finally:
            connection.close()


def _attempt_error(last_error: str, status: int | None, headers: Message) -> str | None:
    if status in {301, 302, 303, 307, 308}:
        location = headers.get("Location", "") if headers else ""
        return f"重定向到 {location or '未知地址'}，不把跳转页当成数据"
    if last_error:
        return last_error
    if status is not None and status >= 400:
        return f"HTTP {status}"
    if status is None:
        return last_error or "没有发出请求"
    return None


def _decode(payload: bytes, headers: Message) -> str:
    charset = "utf-8"
    content_type = headers.get("Content-Type", "") if headers else ""
    if "charset=" in content_type.lower():
        charset = content_type.lower().split("charset=")[-1].split(";")[0].strip() or "utf-8"
    return payload.decode(charset, errors="replace")


def _body_text(body: bytes | None) -> str | None:
    if body is None:
        return None
    return body.decode("utf-8", errors="replace")
