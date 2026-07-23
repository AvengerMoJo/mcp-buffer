"""Minimal local HTTP file server for LocalFileBackend.

Stdlib-only (no aiohttp/fastapi dependency) -- serves buffered files by
buffer_id with HTTP Range support so large PDFs can be streamed/seeked by
a downstream consumer instead of loaded whole. Runs in a background daemon
thread, started lazily on first upload and shared process-wide.

One process may hold multiple LocalFileBackend instances (different
store_dirs -- e.g. per-test, or per-folder configs), all sharing this one
server. buffer_id -> (path, mime_type) lookups therefore go through a
single process-wide registry (register/unregister below) rather than a
resolver bound to whichever backend instance happened to start the server
first -- binding per-instance would silently 404 every backend after the
first one.
"""

from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")

_registry_lock = threading.Lock()
_registry: Dict[str, Tuple[str, str]] = {}


def register(buffer_id: str, path: str, mime_type: str) -> None:
    with _registry_lock:
        _registry[buffer_id] = (path, mime_type)


def unregister(buffer_id: str) -> None:
    with _registry_lock:
        _registry.pop(buffer_id, None)


def _resolve(buffer_id: str) -> Optional[Tuple[str, str]]:
    with _registry_lock:
        return _registry.get(buffer_id)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
        pass  # silence default stderr access logging

    def do_GET(self):  # noqa: N802 - stdlib method name
        buffer_id = self.path.strip("/").split("/")[0]
        resolved = _resolve(buffer_id)
        if resolved is None:
            self.send_error(404, "Unknown or expired buffer_id")
            return
        path, mime_type = resolved
        file_path = Path(path)
        if not file_path.is_file():
            self.send_error(404, "File no longer on disk")
            return

        size = file_path.stat().st_size
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range")
        if range_header:
            m = _RANGE_RE.match(range_header)
            if m:
                status = 206
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
                end = min(end, size - 1)

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = length
            chunk_size = 1024 * 256
            while remaining > 0:
                chunk = f.read(min(chunk_size, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


class BufferHTTPServer:
    """Lazily-started singleton HTTP server for one process."""

    _instance: Optional["BufferHTTPServer"] = None
    _lock = threading.Lock()

    def __init__(self, host: str = "127.0.0.1"):
        self._host = host
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._port = 0

    @classmethod
    def shared(cls) -> "BufferHTTPServer":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                cls._instance.start()
            return cls._instance

    def start(self, port: int = 0) -> int:
        if self._httpd is not None:
            return self._port
        self._httpd = ThreadingHTTPServer((self._host, port), _Handler)
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self._port

    def base_url(self) -> str:
        if self._httpd is None:
            self.start()
        return f"http://{self._host}:{self._port}"

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
