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

import json
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

    # ?format=text|html re-serves the body in a more consumer-friendly form
    # so tools like NotebookLM ingest it instead of treating raw markdown
    # bytes as a plain text dump.
    fmt = (request.query_params.get("format") or "").lower()
    if fmt and request.method == "GET":
        if fmt == "text":
            return Response(content=file_path.read_bytes(), media_type="text/plain; charset=utf-8")
        if fmt == "html":
            body = file_path.read_text(encoding="utf-8", errors="replace")
            page = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                f"<title>{buffer_id}</title></head>"
                f"<body><pre>{body}</pre></body></html>"
            )
            return Response(content=page, media_type="text/html; charset=utf-8")
        return Response("format must be 'text' or 'html'", status_code=400)

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


def register_upload_route(mcp, backend: "BufferBackend") -> None:
    """Mount PUT/POST /buffer/upload -- raw-body ingest, pastebin-style.

    The MCP tool surface (buffer_upload_file) takes a *path*, which only
    works when the caller shares a filesystem with this process. Remote
    callers (another machine, another agent) push bytes instead:

        curl -X PUT 'https://host/buffer/upload?filename=report.pdf' \\
             -H 'Content-Type: application/pdf' --data-binary @report.pdf

    and get back JSON {buffer_id, link, filename, mime_type, size_bytes,
    expires_at}. Must be registered BEFORE register_file_route so
    /buffer/upload isn't shadowed by the /buffer/{buffer_id} GET route.
    """

    @mcp.custom_route("/buffer/upload", methods=["PUT", "POST"], include_in_schema=False)
    async def _buffer_upload_route(request: Request) -> Response:
        body = await request.body()
        if not body:
            return Response("Empty request body", status_code=400)

        params = request.query_params
        filename = params.get("filename") or "upload.bin"
        mime_type = (
            params.get("mime_type")
            or request.headers.get("content-type", "").split(";")[0].strip()
            or None
        )
        ttl_seconds = None
        if params.get("ttl_seconds"):
            try:
                ttl_seconds = int(params["ttl_seconds"])
            except ValueError:
                return Response("ttl_seconds must be an integer", status_code=400)

        try:
            entry = await backend.buffer_upload(
                content=body,
                filename=filename,
                mime_type=mime_type,
                ttl_seconds=ttl_seconds,
                folder_id=params.get("folder_id"),
            )
        except Exception as e:
            return Response(f"Upload failed: {e}", status_code=500)

        return Response(
            content=json.dumps(
                {
                    "buffer_id": entry.buffer_id,
                    "link": entry.link,
                    "filename": entry.filename,
                    "mime_type": entry.mime_type,
                    "size_bytes": entry.size_bytes,
                    "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
                }
            ),
            status_code=201,
            media_type="application/json",
        )
