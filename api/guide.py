#!/usr/bin/env python3
"""A detailed, self-contained HTML reference page for the WhisperSubs API.

The page is built from the running FastAPI application rather than written
out by hand: every endpoint, its method, path, summary and parameters are
read from the route table. With 60+ routes a hand-maintained page would be
stale within a week, and a stale reference is worse than none.

Everything is inlined — no CDN, no external font — so the page works on a
machine with no internet, which is the normal state of the box serving it.

Served at /guide by api/server.py and linked from the JSON root.
"""

from __future__ import annotations

import html
import inspect
import typing
from typing import Any, Dict, List, Optional, Tuple

# Routes FastAPI adds itself; they are linked from the header instead.
_BUILTIN_PATHS = {
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}

# Friendly headings for the first path segment.
_GROUPS = {
    "auth": "Authentication",
    "transcribe": "Transcription",
    "jobs": "Jobs",
    "media": "Media",
    "subtitles": "Subtitle library",
    "library": "Subtitle library",
    "channels": "Channels",
    "search": "Search",
    "downloads": "Downloads",
    "streams": "Streams",
    "model": "Models",
    "models": "Models",
    "system": "System",
    "health": "System",
    "status": "System",
    "screens": "Screens",
    "players": "Players",
}

_METHOD_ORDER = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def _describe_endpoint(endpoint: Any) -> str:
    """First paragraph of an endpoint's docstring, or ''."""
    doc = inspect.getdoc(endpoint) or ""
    if not doc:
        return ""
    return doc.strip().split("\n\n")[0].replace("\n", " ").strip()


def _annotation_name(annotation: Any) -> str:
    if annotation is inspect.Parameter.empty:
        return ""
    if isinstance(annotation, str):
        return annotation
    name = getattr(annotation, "__name__", None)
    if name:
        return name
    text = str(annotation)
    return text.replace("typing.", "")


def _parameters(endpoint: Any) -> List[Tuple[str, str, str]]:
    """(name, annotation, default) for each parameter worth showing."""
    rows: List[Tuple[str, str, str]] = []
    try:
        signature = inspect.signature(endpoint)
    except (TypeError, ValueError):
        return rows

    for name, param in signature.parameters.items():
        if name in {"self", "request", "background_tasks", "credentials"}:
            continue
        annotation = _annotation_name(param.annotation)
        if param.default is inspect.Parameter.empty:
            default = "required"
        elif param.default is None:
            default = "null"
        else:
            default = repr(param.default)
            if len(default) > 24:
                default = default[:21] + "..."
        rows.append((name, annotation or "any", default))
    return rows


def _collect_routes(app: Any) -> List[Dict[str, Any]]:
    routes: List[Dict[str, Any]] = []
    for route in getattr(app, "routes", []):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        endpoint = getattr(route, "endpoint", None)
        if not path or not methods or endpoint is None or path in _BUILTIN_PATHS:
            continue

        for method in sorted(m for m in methods if m in _METHOD_ORDER):
            routes.append(
                {
                    "method": method,
                    "path": path,
                    "name": getattr(route, "name", ""),
                    "summary": (getattr(route, "summary", "") or "").strip(),
                    "description": _describe_endpoint(endpoint),
                    "params": _parameters(endpoint),
                }
            )
    return routes


def _group_of(path: str) -> str:
    segment = path.strip("/").split("/")[0] if path.strip("/") else "root"
    segment = segment.split("{")[0].strip("/") or "root"
    return _GROUPS.get(segment, segment.replace("-", " ").replace("_", " ").title())


def _render_route(route: Dict[str, Any]) -> str:
    method = route["method"]
    path = html.escape(route["path"])
    summary = html.escape(route["summary"] or route["description"] or "")
    if len(summary) > 220:
        summary = summary[:217] + "..."

    rows = ""
    if route["params"]:
        cells = "".join(
            f'<tr><td class="p-name">{html.escape(n)}</td>'
            f'<td class="p-type">{html.escape(t)}</td>'
            f'<td class="p-def">{html.escape(d)}</td></tr>'
            for n, t, d in route["params"]
        )
        rows = (
            '<details class="params"><summary>'
            f"{len(route['params'])} parameter"
            f"{'s' if len(route['params']) != 1 else ''}</summary>"
            '<table class="ptable"><thead><tr><th>name</th><th>type</th>'
            f"<th>default</th></tr></thead><tbody>{cells}</tbody></table>"
            "</details>"
        )

    return (
        f'<li class="ep" data-search="{html.escape((route["method"] + " " + route["path"] + " " + summary).lower())}">'
        f'<div class="sig"><span class="m {method.lower()}">{method}</span>'
        f'<code class="path">{path}</code></div>'
        f'<div class="sum">{summary or "<em>no description</em>"}</div>'
        f"{rows}</li>"
    )


def build_guide_page(app: Any) -> str:
    """Render the full reference page for `app`."""
    routes = _collect_routes(app)

    try:
        import app_meta

        build: Dict[str, Any] = dict(app_meta.get_build_info() or {})
    except Exception:
        build = {}

    title = getattr(app, "title", "API")
    version = getattr(app, "version", "") or build.get("version", "")
    description = (getattr(app, "description", "") or "").strip()

    # Group, preserving first-seen order so related endpoints stay adjacent.
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for route in routes:
        grouped.setdefault(_group_of(route["path"]), []).append(route)

    sections = []
    for group, items in grouped.items():
        items.sort(key=lambda r: (r["path"], _METHOD_ORDER.index(r["method"])))
        body = "\n".join(_render_route(r) for r in items)
        sections.append(
            f'<section class="group"><h2>{html.escape(group)}'
            f'<span class="count">{len(items)}</span></h2>'
            f'<ul class="eps">{body}</ul></section>'
        )

    meta_rows = "".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
        for k, v in sorted(build.items())
    )

    from api.pages import render_shell

    # Chrome (nav, base CSS, footer) lives in api.pages so every page matches.
    body = (
        f'<div class="links" style="margin-bottom:6px">'
        f'<a href="/docs">interactive docs (Swagger)</a>'
        f'<a href="/redoc">ReDoc</a>'
        f'<a href="/openapi.json">OpenAPI schema</a></div>'
        + '<div class="searchwrap"><input id="q" type="search" '
        'placeholder="filter endpoints by path, method or description…" '
        'autocomplete="off" /></div>'
        + ("".join(sections) if sections else '<p class="empty">No endpoints registered.</p>')
        + '<p class="empty" id="noresults" style="display:none">'
        'No endpoints match that filter.</p>'
        + '<section class="meta"><h2>Build</h2><table>'
        + (meta_rows or "<tr><td>(unavailable)</td></tr>")
        + "</table></section>"
        + GUIDE_SCRIPT
    )

    return render_shell(
        f"{title} reference",
        f"{len(routes)} endpoints across {len(grouped)} groups. Generated from "
        "the running route table, so it cannot drift from the code.",
        "/guide",
        body,
        extra_css=GUIDE_CSS,
    )


GUIDE_CSS = """
  ul.eps { list-style: none; margin: 0; padding: 0; }
  li.ep {
    border: 1px solid #262b36; border-radius: 10px; padding: 12px 14px;
    margin-bottom: 8px; background: #171a21;
  }
  .sig { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .m {
    font-size: 11px; font-weight: 700; letter-spacing: .06em;
    padding: 2px 7px; border-radius: 5px; color: #0f1116;
    background: #9aa4b2; min-width: 52px; text-align: center;
  }
  .m.get { background: #4fc08d; }
  .m.post { background: #e0af68; }
  .m.delete { background: #f07178; }
  .m.put { background: #bb9af7; }
  .m.patch { background: #7dcfff; }
  .path { color: #e6e9ef; word-break: break-all; }
  .sum { color: #9aa4b2; margin-top: 6px; }
  details.params { margin-top: 8px; }
  details.params summary { cursor: pointer; color: #7aa2f7; font-size: 13px; }
  table.ptable { border-collapse: collapse; margin-top: 8px; font-size: 13px; }
  .ptable th, .ptable td {
    text-align: left; padding: 3px 12px 3px 0; border-bottom: 1px solid #262b36;
  }
  .ptable th { color: #9aa4b2; font-weight: 500; }
  .p-name { color: #e6e9ef; }
  .p-type { color: #bb9af7; }
  .p-def { color: #9aa4b2; }
  .meta table { border-collapse: collapse; font-size: 13px; }
  .meta th { text-align: left; color: #9aa4b2; font-weight: 500;
    padding: 3px 16px 3px 0; }
  .links a { color: #7aa2f7; text-decoration: none; margin-right: 14px;
    border-bottom: 1px dotted #7aa2f7; }
  .links a:hover { border-bottom-style: solid; }
  .searchwrap { margin-top: 14px; }
"""

GUIDE_SCRIPT = """
<script>
(function () {
  var q = document.getElementById("q");
  var eps = Array.prototype.slice.call(document.querySelectorAll("li.ep"));
  var groups = Array.prototype.slice.call(document.querySelectorAll("section.group"));
  var none = document.getElementById("noresults");
  function apply() {
    var needle = q.value.trim().toLowerCase(), visible = 0;
    eps.forEach(function (el) {
      var hit = !needle ||
        (el.getAttribute("data-search") || "").indexOf(needle) !== -1;
      el.style.display = hit ? "" : "none";
      if (hit) visible++;
    });
    groups.forEach(function (g) {
      var any = g.querySelectorAll("li.ep:not([style*='display: none'])").length > 0;
      g.style.display = any ? "" : "none";
    });
    none.style.display = visible ? "none" : "";
  }
  q.addEventListener("input", apply);
})();
</script>"""




if __name__ == "__main__":
    from api.server import app

    print(build_guide_page(app))
