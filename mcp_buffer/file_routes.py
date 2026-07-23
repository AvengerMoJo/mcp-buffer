"""Buffered-file HTTP route, mounted onto the same FastMCP app that serves
the MCP protocol -- one process, one port, one hostname for both the
MCP tool-calling endpoint and the file downloads it hands out links to.

(Earlier revision ran a second stdlib http.server on its own port for
file serving, separate from the MCP server's port -- that was an
accident of LocalFileBackend owning its own server, not a real
requirement. FastMCP.custom_route() lets us mount plain HTTP routes on
its own ASGI app instead, so there's no reason for a second port.)

buffer_id -> (path, mime_type) lookups go through a process-wide registry
(register/unregister below) rather than being owned by one particular
LocalFileBackend instance -- a process may hold multiple instances
(different store_dirs, e.g. per-folder configs), all served by this one
route.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_CHUNK_SIZE = 1024 * 256

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


def _parse_range(range_header: Optional[str], size: int) -> Tuple[int, int, bool]:
    """Returns (start, end, is_partial)."""
    if not range_header:
        return 0, size - 1, False
    m = _RANGE_RE.match(range_header)
    if not m:
        return 0, size - 1, False
    start = int(m.group(1)) if m.group(1) else 0
    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    return start, end, True


async def _serve(request: Request, send_body: bool) -> Response:
    buffer_id = request.path_params["buffer_id"]
    resolved = _resolve(buffer_id)
    if resolved is None:
        return Response("Unknown or expired buffer_id", status_code=404)
    path, mime_type = resolved
    file_path = Path(path)
    if not file_path.is_file():
        return Response("File no longer on disk", status_code=404)

    size = file_path.stat().st_size
    start, end, is_partial = _parse_range(request.headers.get("range"), size)
    length = end - start + 1

    headers = {
        "Content-Type": mime_type,
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
    }
    status_code = 200
    if is_partial:
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    if not send_body:
        return Response(status_code=status_code, headers=headers)

    def iter_chunks():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                yield chunk
                remaining -= len(chunk)

    return StreamingResponse(iter_chunks(), status_code=status_code, headers=headers)


def register_file_route(mcp) -> None:
    """Mount GET/HEAD /buffer/{buffer_id} onto a FastMCP server instance."""

    @mcp.custom_route("/buffer/{buffer_id}", methods=["GET", "HEAD"], include_in_schema=False)
    async def _buffer_file_route(request: Request) -> Response:
        return await _serve(request, send_body=request.method == "GET")
