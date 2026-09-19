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
import os
import re
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response, StreamingResponse

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_CHUNK_SIZE = 1024 * 256
_UPLOAD_TOKEN_ENV_VAR = "MCP_BUFFER_UPLOAD_TOKEN"

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

    # Browsers/chats default to Latin-1 for any text/* without an explicit
    # charset, which mojibakes UTF-8 markdown/text/JSON. Append charset only
    # for text-ish types; binary stays as-is so image/PDF viewers pick their
    # own handling.
    def _content_type(mt: str) -> str:
        if mt.startswith("text/") and "charset=" not in mt:
            return f"{mt}; charset=utf-8"
        return mt

    headers = {
        "Content-Type": _content_type(mime_type),
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


def _check_upload_token(request: Request) -> Optional[Response]:
    """Return a 401 Response if MCP_BUFFER_UPLOAD_TOKEN is set and the
    request doesn't present a matching token; None if the request may
    proceed (either no token configured, or it matched).

    Checked on every /buffer/upload call (web page and raw PUT/POST alike)
    so setting the token actually closes the public write path, not just
    the page's own prompt -- a token gate on the page alone would be
    cosmetic if the route behind it stayed wide open.
    """
    required = os.environ.get(_UPLOAD_TOKEN_ENV_VAR)
    if not required:
        return None
    supplied = request.headers.get("x-upload-token") or request.query_params.get("token")
    if supplied != required:
        return Response("Invalid or missing upload token", status_code=401)
    return None


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
        denied = _check_upload_token(request)
        if denied is not None:
            return denied
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


_UPLOAD_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mcp-buffer</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 640px; margin: 3rem auto; padding: 0 1.5rem;
    background: Canvas; color: CanvasText;
  }
  h1 { font-size: 1.25rem; margin-bottom: 0.25rem; }
  p.sub { color: GrayText; margin-top: 0; font-size: 0.9rem; }
  #drop {
    border: 2px dashed color-mix(in srgb, CanvasText 30%, transparent);
    border-radius: 10px; padding: 2.5rem 1rem; text-align: center;
    cursor: pointer; transition: border-color 0.15s, background 0.15s;
  }
  #drop.hover { border-color: #4a90d9; background: color-mix(in srgb, #4a90d9 8%, transparent); }
  #file { display: none; }
  .row { display: flex; gap: 0.5rem; margin-top: 1rem; }
  input[type=text], input[type=number], input[type=password] {
    flex: 1; padding: 0.5rem; border-radius: 6px;
    border: 1px solid color-mix(in srgb, CanvasText 30%, transparent);
    background: Canvas; color: CanvasText; font-size: 0.9rem;
  }
  label.field { font-size: 0.8rem; color: GrayText; display: block; margin-top: 0.75rem; }
  button {
    padding: 0.5rem 1rem; border-radius: 6px; border: none;
    background: #4a90d9; color: white; font-size: 0.9rem; cursor: pointer;
  }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  #bar { height: 6px; border-radius: 3px; background: color-mix(in srgb, CanvasText 12%, transparent);
    margin-top: 1rem; overflow: hidden; display: none; }
  #bar > div { height: 100%; width: 0%; background: #4a90d9; transition: width 0.1s; }
  #result { margin-top: 1.25rem; padding: 0.75rem 1rem; border-radius: 8px;
    background: color-mix(in srgb, CanvasText 6%, transparent); display: none; font-size: 0.9rem; }
  #result a { word-break: break-all; }
  #error { margin-top: 1rem; color: #d9534f; font-size: 0.9rem; display: none; }
  #copy { margin-left: 0.5rem; }
</style>
</head>
<body>
<h1>mcp-buffer</h1>
<p class="sub">Drop a file, get a link back.</p>

<div id="drop">Click or drag a file here</div>
<input type="file" id="file">

<div id="tokenRow" style="display:none">
  <label class="field" for="token">Upload token</label>
  <div class="row">
    <input type="text" id="token" placeholder="required to upload"
      autocapitalize="off" autocorrect="off" autocomplete="off" spellcheck="false">
  </div>
</div>

<label class="field" for="filename">Filename (optional override)</label>
<div class="row">
  <input type="text" id="filename" placeholder="defaults to the file's own name">
</div>

<label class="field" for="ttl">Expire after (seconds, optional)</label>
<div class="row">
  <input type="number" id="ttl" min="1" placeholder="never expires if left blank">
  <button id="go" disabled>Upload</button>
</div>

<div id="bar"><div></div></div>
<div id="error"></div>
<div id="result"></div>

<script>
(function () {
  var fileInput = document.getElementById('file');
  var drop = document.getElementById('drop');
  var go = document.getElementById('go');
  var bar = document.getElementById('bar');
  var barInner = bar.querySelector('div');
  var result = document.getElementById('result');
  var error = document.getElementById('error');
  var tokenInput = document.getElementById('token');
  var tokenRow = document.getElementById('tokenRow');
  var filenameInput = document.getElementById('filename');
  var ttlInput = document.getElementById('ttl');
  var selected = null;

  // A token can arrive once via ?token=... in the URL (e.g. a bookmarked
  // link) so it never has to be typed on a phone keyboard -- save it and
  // scrub it from the visible address bar/history immediately.
  var urlToken = new URLSearchParams(window.location.search).get('token');
  if (urlToken) {
    localStorage.setItem('mcp_buffer_token', urlToken);
    history.replaceState(null, '', window.location.pathname);
  }

  var savedToken = urlToken || localStorage.getItem('mcp_buffer_token');
  if (savedToken) {
    tokenInput.value = savedToken;
    tokenRow.style.display = 'block';
  }
  // Otherwise the token field stays hidden until the first 401 so an
  // unconfigured (open) server stays a one-click upload.

  function pick(f) {
    selected = f;
    drop.textContent = f ? (f.name + ' (' + f.size.toLocaleString() + ' bytes)') : 'Click or drag a file here';
    go.disabled = !f;
  }

  drop.addEventListener('click', function () { fileInput.click(); });
  fileInput.addEventListener('change', function () { pick(fileInput.files[0] || null); });
  ['dragenter', 'dragover'].forEach(function (evt) {
    drop.addEventListener(evt, function (e) { e.preventDefault(); drop.classList.add('hover'); });
  });
  ['dragleave', 'drop'].forEach(function (evt) {
    drop.addEventListener(evt, function (e) { e.preventDefault(); drop.classList.remove('hover'); });
  });
  drop.addEventListener('drop', function (e) {
    var f = e.dataTransfer.files[0];
    if (f) pick(f);
  });

  go.addEventListener('click', function () {
    if (!selected) return;
    error.style.display = 'none';
    result.style.display = 'none';
    go.disabled = true;

    var filename = filenameInput.value.trim() || selected.name;
    var params = new URLSearchParams({ filename: filename });
    if (ttlInput.value) params.set('ttl_seconds', ttlInput.value);

    var xhr = new XMLHttpRequest();
    xhr.open('PUT', '/buffer/upload?' + params.toString());
    xhr.setRequestHeader('Content-Type', selected.type || 'application/octet-stream');
    var token = tokenInput.value.trim();
    if (token) xhr.setRequestHeader('X-Upload-Token', token);

    bar.style.display = 'block';
    xhr.upload.addEventListener('progress', function (e) {
      if (e.lengthComputable) barInner.style.width = Math.round(100 * e.loaded / e.total) + '%';
    });

    xhr.onload = function () {
      bar.style.display = 'none';
      barInner.style.width = '0%';
      go.disabled = false;
      if (xhr.status === 401) {
        tokenRow.style.display = 'block';
        error.textContent = 'Upload token missing or incorrect.';
        error.style.display = 'block';
        return;
      }
      if (xhr.status !== 201) {
        error.textContent = 'Upload failed (' + xhr.status + '): ' + xhr.responseText;
        error.style.display = 'block';
        return;
      }
      if (token) localStorage.setItem('mcp_buffer_token', token);
      var data = JSON.parse(xhr.responseText);
      result.innerHTML = '<div><a href="' + data.link + '" target="_blank" rel="noopener">' +
        data.link + '</a><button id="copy">Copy</button></div>' +
        '<div style="color:GrayText;margin-top:0.4rem">' + data.filename + ' · ' +
        data.size_bytes.toLocaleString() + ' bytes' +
        (data.expires_at ? (' · expires ' + data.expires_at) : '') + '</div>';
      result.style.display = 'block';
      document.getElementById('copy').addEventListener('click', function () {
        navigator.clipboard.writeText(data.link);
        this.textContent = 'Copied!';
      });
      pick(null);
      fileInput.value = '';
    };
    xhr.onerror = function () {
      bar.style.display = 'none';
      go.disabled = false;
      error.textContent = 'Network error during upload.';
      error.style.display = 'block';
    };
    xhr.send(selected);
  });
})();
</script>
</body>
</html>
"""


def register_web_upload_route(mcp) -> None:
    """Mount GET /buffer/web -- a dependency-free pastebin-style upload
    page (drag/drop or click-to-pick) that PUTs to /buffer/upload, the
    same route curl/API callers use. If MCP_BUFFER_UPLOAD_TOKEN is set,
    the page prompts for it and sends it as X-Upload-Token; the token is
    enforced by _check_upload_token on the upload route itself, not by
    anything client-side, so this page can't be bypassed by skipping the
    prompt.
    """

    @mcp.custom_route("/buffer/web", methods=["GET"], include_in_schema=False)
    async def _buffer_web_route(request: Request) -> Response:
        return HTMLResponse(_UPLOAD_PAGE_HTML)
