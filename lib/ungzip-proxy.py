#!/usr/bin/env python3
"""Local reverse proxy that gunzips Codex request bodies before 9router.

Codex CLI gzip-compresses large request bodies (this happens whenever you
*resume* a conversation, because the whole history is replayed into `input`).
9router's Next.js API does not decompress `Content-Encoding: gzip` request
bodies — it JSON.parses the raw gzip bytes and returns:

  {"error":{"message":"Invalid JSON body","type":"invalid_request_error",
            "code":"bad_request"}}

This shim sits between Codex and 9router: it accepts the (possibly
compressed) request, decompresses it, forwards clean JSON upstream, and
streams the response back unbuffered so SSE token streaming still works.

It is deliberately dependency-free (stdlib only) and binds to loopback.
"""
from __future__ import annotations

import argparse
import gzip
import http.client
import sys
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

# Headers we must not blindly forward (hop-by-hop or recomputed by us).
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

UPSTREAM_HOST = ""
UPSTREAM_PORT = 0
UPSTREAM_SCHEME = "http"


def decompress(body: bytes, encoding: str) -> bytes:
    enc = (encoding or "").strip().lower()
    if not body or enc in ("", "identity"):
        return body
    if enc == "gzip":
        return gzip.decompress(body)
    if enc == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    # br/zstd: we don't ship a decoder; pass through untouched so the
    # upstream error (if any) is the real one, not a masked crash.
    return body


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "cxsw-ungzip/1"

    def log_message(self, *_args):  # silence default access log
        pass

    def _relay(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""

        try:
            body = decompress(raw, self.headers.get("Content-Encoding", ""))
        except Exception as exc:  # corrupt gzip -> report, don't 500 silently
            self._fail(502, f"ungzip-proxy: cannot decode request body: {exc}")
            return

        out_headers = []
        for key, value in self.headers.items():
            low = key.lower()
            if low in HOP_BY_HOP or low in ("host", "content-length", "content-encoding"):
                continue
            out_headers.append((key, value))
        out_headers.append(("Host", f"{UPSTREAM_HOST}:{UPSTREAM_PORT}"))
        out_headers.append(("Content-Length", str(len(body))))

        try:
            conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=900)
            conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            for key, value in out_headers:
                conn.putheader(key, value)
            conn.endheaders()
            if body:
                conn.send(body)
            resp = conn.getresponse()
        except OSError as exc:
            self._fail(502, f"ungzip-proxy: upstream connect failed: {exc}")
            return

        # Stream the response straight through. Use connection-close framing
        # (no Content-Length / chunked re-encoding) so SSE arrives token by
        # token instead of being buffered until completion.
        self.send_response_only(resp.status, resp.reason)
        for key, value in resp.getheaders():
            if key.lower() in HOP_BY_HOP or key.lower() == "content-length":
                continue
            self.send_header(key, value)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()

    def _fail(self, code: int, message: str):
        payload = (
            '{"error":{"message":"%s","type":"proxy_error","code":"bad_gateway"}}'
            % message.replace('"', "'")
        ).encode()
        try:
            self.send_response_only(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True

    do_GET = _relay
    do_POST = _relay
    do_PUT = _relay
    do_DELETE = _relay
    do_PATCH = _relay
    do_HEAD = _relay


def main() -> int:
    global UPSTREAM_HOST, UPSTREAM_PORT, UPSTREAM_SCHEME
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--listen", default="127.0.0.1:20127", help="host:port to bind")
    ap.add_argument(
        "--upstream",
        default="http://127.0.0.1:20128/v1",
        help="real 9router base URL (only scheme/host/port are used)",
    )
    args = ap.parse_args()

    up = urlsplit(args.upstream)
    UPSTREAM_SCHEME = up.scheme or "http"
    UPSTREAM_HOST = up.hostname or "127.0.0.1"
    UPSTREAM_PORT = up.port or (443 if UPSTREAM_SCHEME == "https" else 80)
    if UPSTREAM_SCHEME == "https":
        sys.exit("ungzip-proxy: https upstream not supported (9router is local http)")

    host, _, port = args.listen.rpartition(":")
    httpd = ThreadingHTTPServer((host or "127.0.0.1", int(port)), Proxy)
    httpd.daemon_threads = True
    print(
        f"ungzip-proxy listening on {host or '127.0.0.1'}:{port} "
        f"-> {UPSTREAM_HOST}:{UPSTREAM_PORT}",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
