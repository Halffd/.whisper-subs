#!/usr/bin/env python3
"""Server-rendered HTML pages for the WhisperSubs API: status, library, stats.

These pages read the same in-process state the JSON endpoints expose
(`task_status`, `batch_status`, `get_jobs()`, `_library_items()`,
`audio_cache.stats()`), so there is no second data path to keep in sync and
no client-side fetching to fail against auth.

Auth policy matches the JSON API: the endpoints these pages summarise use
`get_current_user_optional`, so the pages are readable without credentials
and expose nothing the unauthenticated JSON API would not.

A single shell provides the CSS and the nav bar so all four pages
(guide/status/library/stats) stay visually consistent. Everything is inlined:
no CDN, no external font, so the pages work on a box with no internet.
"""

from __future__ import annotations

import html
import os
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

NAV = [
    ("/guide", "Guide"),
    ("/status", "Status"),
    ("/library", "Library"),
    ("/stats", "Stats"),
]

CSS = """
  * { box-sizing: border-box; }
  body {
    margin: 0; background: #0f1116; color: #e6e9ef;
    font: 15px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  a { color: #7aa2f7; }
  nav {
    display: flex; gap: 4px; align-items: center; flex-wrap: wrap;
    padding: 10px 24px; background: #12151c; border-bottom: 1px solid #262b36;
    position: sticky; top: 0; z-index: 6;
  }
  nav .brand { color: #9aa4b2; margin-right: 14px; font-size: 13px; }
  nav a {
    text-decoration: none; color: #9aa4b2; padding: 4px 10px;
    border-radius: 6px; font-size: 13px;
  }
  nav a:hover { background: #1c212b; color: #e6e9ef; }
  nav a.active { background: #1c212b; color: #7aa2f7; }
  header { padding: 24px 24px 14px; border-bottom: 1px solid #262b36; }
  h1 { margin: 0 0 4px; font-size: 20px; }
  .lede { color: #9aa4b2; margin: 0 0 6px; max-width: 82ch; }
  main { padding: 8px 24px 60px; max-width: 1200px; }
  h2 {
    font-size: 14px; text-transform: uppercase; letter-spacing: .08em;
    color: #9aa4b2; margin: 26px 0 10px; display: flex; gap: 8px;
    align-items: center;
  }
  .count {
    background: #262b36; color: #9aa4b2; border-radius: 99px;
    padding: 1px 8px; font-size: 12px; letter-spacing: 0;
  }
  .cards { display: flex; flex-wrap: wrap; gap: 10px; }
  .card {
    background: #171a21; border: 1px solid #262b36; border-radius: 10px;
    padding: 12px 16px; min-width: 150px; flex: 0 1 auto;
  }
  .card .k { color: #9aa4b2; font-size: 12px; text-transform: uppercase;
    letter-spacing: .06em; }
  .card .v { font-size: 22px; margin-top: 4px; }
  .card .sub { color: #9aa4b2; font-size: 12px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { text-align: left; padding: 6px 12px 6px 0;
    border-bottom: 1px solid #262b36; vertical-align: top; }
  th { color: #9aa4b2; font-weight: 500; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .pill {
    font-size: 11px; padding: 1px 7px; border-radius: 99px;
    background: #262b36; color: #9aa4b2; margin-right: 4px;
  }
  .ok { color: #4fc08d; } .warn { color: #e0af68; } .bad { color: #f07178; }
  .bar { background: #262b36; border-radius: 4px; height: 8px; overflow: hidden;
    min-width: 90px; }
  .bar > span { display: block; height: 100%; background: #7aa2f7; }
  .empty { color: #9aa4b2; padding: 14px 0; }
  #q { width: 100%; max-width: 520px; padding: 9px 12px; border-radius: 8px;
    border: 1px solid #262b36; background: #0b0d12; color: #e6e9ef;
    font: inherit; }
  .searchwrap { margin-top: 10px; }
  footer { color: #9aa4b2; font-size: 12px; margin-top: 40px; }
  code.path { color: #e6e9ef; }
"""


def render_shell(
    title: str,
    subtitle: str,
    active: str,
    body: str,
    extra_css: str = "",
) -> str:
    """Wrap `body` in the shared chrome."""
    links = " ".join(
        f'<a href="{href}"{" class='active'" if href == active else ""}>'
        f"{html.escape(label)}</a>"
        for href, label in NAV
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{html.escape(title)}</title>
<style>{CSS}{extra_css}</style>
</head>
<body>
<nav><span class="brand">WhisperSubs</span>{links}</nav>
<header>
  <h1>{html.escape(title)}</h1>
  <p class="lede">{subtitle}</p>
</header>
<main>
{body}
<footer>WhisperSubs API &middot; <a href="/guide">Guide</a> &middot;
<a href="/docs">Swagger</a> &middot; <a href="/openapi.json">OpenAPI</a></footer>
</main>
</body>
</html>
"""


# --- helpers -------------------------------------------------------------


def _fmt_bytes(n: Any) -> str:
    try:
        value = float(n)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024
    return f"{value:,.1f} TB"


def _fmt_duration(seconds: Any) -> str:
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "-"
    if total <= 0:
        return "-"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _card(key: str, value: str, sub: str = "") -> str:
    extra = f'<div class="sub">{html.escape(sub)}</div>' if sub else ""
    return (
        f'<div class="card"><div class="k">{html.escape(key)}</div>'
        f'<div class="v">{html.escape(value)}</div>{extra}</div>'
    )


def _bar(pct: float) -> str:
    clamped = max(0.0, min(100.0, float(pct or 0)))
    return f'<div class="bar"><span style="width:{clamped:.0f}%"></span></div>'


def _library_items() -> List[Dict[str, Any]]:
    """Reuse the API's own scanner so the page cannot disagree with /api/v1/library."""
    try:
        from api import server

        return server._library_items()
    except Exception:
        return []


def _load_metadata(srt_path: str) -> Dict[str, Any]:
    """Sibling .metadata.json, or {} when absent/unreadable."""
    import json

    meta_path = os.path.splitext(srt_path)[0] + ".metadata.json"
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _model_from_meta(meta: Dict[str, Any], filename: str) -> str:
    """Model name from metadata, falling back to the filename suffix."""
    model = meta.get("model")
    if model:
        return str(model)
    stem = os.path.splitext(filename)[0]
    if "." in stem:
        return stem.rsplit(".", 1)[1]
    return "unknown"


# --- /status -------------------------------------------------------------


def status_page(app: Any) -> str:
    import datetime

    body: List[str] = []
    cards: List[str] = []

    # System figures, same source the /metrics endpoint uses.
    system: Dict[str, Any] = {}
    try:
        import psutil

        system = {
            "cpu": psutil.cpu_percent(interval=0.1),
            "mem": psutil.virtual_memory().percent,
            "disk": (
                psutil.disk_usage(os.environ.get("HOME", "/")).percent
                if os.path.exists(os.environ.get("HOME", "/"))
                else 0
            ),
            "boot": psutil.boot_time(),
        }
    except Exception:
        system = {}

    try:
        from api import server

        with server.task_lock:
            tasks = [dict(v) for v in server.task_status.values()]
        with server.batch_lock:
            batches = [dict(v) for v in server.batch_status.values()]
        build = server.app_meta.get_build_info()
    except Exception:
        tasks, batches, build = [], [], {}

    try:
        from whisper_subs import get_jobs

        jobs = get_jobs()
    except Exception:
        jobs = []

    by_status: Dict[str, int] = {}
    for t in tasks:
        key = str(t.get("status", "unknown"))
        by_status[key] = by_status.get(key, 0) + 1

    cards.append(_card("Tasks", str(len(tasks)), f"{len(by_status)} states"))
    cards.append(_card("Active", str(by_status.get("processing", 0)), "processing"))
    cards.append(_card("Queued", str(by_status.get("queued", 0))))
    cards.append(_card("Failed", str(by_status.get("failed", 0)), "needs attention"))
    cards.append(_card("Jobs", str(len(jobs))))
    cards.append(_card("Batches", str(len(batches))))
    body.append('<div class="cards">' + "".join(cards) + "</div>")

    # System panel with bars.
    if system:
        rows = [
            ("CPU", f"{system['cpu']:.0f}%", system["cpu"]),
            ("Memory", f"{system['mem']:.0f}%", system["mem"]),
            ("Disk (home)", f"{system['disk']:.0f}%", system["disk"]),
        ]
        table = "".join(
            f'<tr><td>{html.escape(name)}</td><td class="num">{html.escape(val)}</td>'
            f"<td>{_bar(pct)}</td></tr>"
            for name, val, pct in rows
        )
        uptime = ""
        if system.get("boot"):
            host_uptime = datetime.datetime.now().timestamp() - system["boot"]
            uptime = (
                f'<p class="lede">Host uptime: {html.escape(_fmt_duration(host_uptime))}'
                " (host, not this process).</p>"
            )
        body.append("<h2>System</h2>" + uptime + f"<table>{table}</table>")
    else:
        body.append(
            '<h2>System</h2><p class="empty">psutil unavailable; '
            "install it to see CPU, memory and disk usage.</p>"
        )

    # Build info.
    if build:
        rows = "".join(
            f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
            for k, v in sorted(build.items())
        )
        body.append(f"<h2>Build</h2><table>{rows}</table>")

    # Tasks table, newest first.
    if tasks:
        tasks.sort(key=lambda t: str(t.get("created_at", "")), reverse=True)
        rows = "".join(
            f"<tr><td>{html.escape(str(t.get('task_id', ''))[:28])}</td>"
            f"<td>{html.escape(str(t.get('status', '')))}</td>"
            f"<td>{html.escape(str(t.get('progress', '') or ''))}</td>"
            f"<td>{html.escape(str(t.get('created_at', ''))[:19])}</td>"
            f"<td>{html.escape(str(t.get('error', '') or '')[:70])}</td></tr>"
            for t in tasks[:40]
        )
        body.append(
            "<h2>Recent tasks<span class='count'>"
            f"{min(len(tasks), 40)} of {len(tasks)}</span></h2>"
            "<table><thead><tr><th>task</th><th>status</th><th>progress</th>"
            f"<th>created</th><th>error</th></tr></thead><tbody>{rows}</tbody></table>"
        )
    else:
        body.append('<h2>Tasks</h2><p class="empty">No tasks recorded.</p>')

    # Jobs by status.
    if jobs:
        counts: Dict[str, int] = {}
        for j in jobs:
            counts[str(j.get("status", "unknown"))] = (
                counts.get(str(j.get("status", "unknown")), 0) + 1
            )
        rows = "".join(
            f"<tr><td>{html.escape(k)}</td><td class='num'>{v}</td></tr>"
            for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
        )
        body.append(f"<h2>Jobs by status</h2><table>{rows}</table>")

    return render_shell(
        "Server status",
        "Live health, load and recent work. Figures come from the same "
        "in-process state the JSON endpoints expose.",
        "/status",
        "\n".join(body),
    )


# --- /library ------------------------------------------------------------


def library_page(limit: int = 500) -> str:
    items = _library_items()
    items.sort(key=lambda it: (str(it.get("channel", "")), str(it.get("title", ""))))

    channels: Dict[str, int] = {}
    total_bytes = 0
    with_video = 0
    with_audio = 0
    with_thumb = 0
    for it in items:
        channels[str(it.get("channel", ""))] = (
            channels.get(str(it.get("channel", "")), 0) + 1
        )
        total_bytes += int(it.get("size_bytes") or 0)
        with_video += 1 if it.get("has_video") else 0
        with_audio += 1 if it.get("has_audio") else 0
        with_thumb += 1 if it.get("has_thumbnail") else 0

    cards = [
        _card("Subtitles", str(len(items))),
        _card("Channels", str(len(channels))),
        _card("Subtitle size", _fmt_bytes(total_bytes)),
        _card("With video", str(with_video)),
        _card("With audio", str(with_audio)),
        _card("With thumbnail", str(with_thumb)),
    ]

    shown = items[:limit]
    rows = []
    for it in shown:
        badges = []
        if it.get("has_video"):
            badges.append('<span class="pill">video</span>')
        if it.get("has_audio"):
            badges.append('<span class="pill">audio</span>')
        if it.get("has_thumbnail"):
            badges.append('<span class="pill">thumb</span>')
        # Quote exactly as the JSON API does: a raw source_url containing &
        # would otherwise terminate the query string.
        play = (
            '<a href="/api/v1/play?source='
            + urllib.parse.quote(str(it["source_url"]), safe="")
            + "&srt="
            + urllib.parse.quote(str(it.get("path", "")), safe="")
            + '">play</a>'
            if it.get("source_url")
            else '<span class="pill">no url</span>'
        )
        srt_link = f"/api/v1/subs/file?path={html.escape(str(it.get('path', '')))}"
        rows.append(
            f'<tr data-search="{html.escape((str(it.get("title", "")) + " " + str(it.get("channel", ""))).lower())}">'
            f"<td>{html.escape(str(it.get('title', ''))[:64])}</td>"
            f"<td>{html.escape(str(it.get('channel', '')))}</td>"
            f"<td>{''.join(badges)}</td>"
            f'<td class="num">{_fmt_bytes(it.get("size_bytes"))}</td>'
            f'<td><a href="{srt_link}">srt</a> {play}</td></tr>'
        )

    table = (
        "<table><thead><tr><th>title</th><th>channel</th><th>media</th>"
        '<th class="num">size</th><th></th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table>"
        if rows
        else '<p class="empty">No subtitles in the library yet.</p>'
    )

    truncated = (
        f'<p class="empty">Showing the first {limit} of {len(items)} items.</p>'
        if len(items) > limit
        else ""
    )

    body = (
        '<div class="cards">'
        + "".join(cards)
        + "</div>"
        + '<div class="searchwrap"><input id="q" type="search" '
        'placeholder="filter by title or channel…" autocomplete="off" /></div>'
        + f"<h2>Library<span class='count'>{len(items)}</span></h2>"
        + table
        + truncated
        + '<p class="empty" id="noresults" style="display:none">'
        "No items match that filter.</p>"
    )

    script = """
<script>
(function () {
  var q = document.getElementById("q");
  var rows = Array.prototype.slice.call(document.querySelectorAll("tbody tr"));
  var none = document.getElementById("noresults");
  q.addEventListener("input", function () {
    var needle = q.value.trim().toLowerCase(), visible = 0;
    rows.forEach(function (r) {
      var hit = !needle || (r.getAttribute("data-search") || "").indexOf(needle) !== -1;
      r.style.display = hit ? "" : "none";
      if (hit) visible++;
    });
    none.style.display = visible ? "none" : "";
  });
})();
</script>"""

    return render_shell(
        "Subtitle library",
        "Everything transcribed on this machine, grouped by channel. "
        "Links open the subtitle or hand the source to the player.",
        "/library",
        body + script,
    )


# --- /stats --------------------------------------------------------------


def stats_page() -> str:
    items = _library_items()

    per_channel: Dict[str, Dict[str, int]] = {}
    per_model: Dict[str, Dict[str, int]] = {}
    media_format: Dict[str, int] = {}
    total_bytes = 0
    total_duration = 0.0
    with_duration = 0

    for it in items:
        srt_path = it.get("srt_path") or it.get("path") or ""
        if srt_path and not os.path.isabs(srt_path):
            try:
                from api import server

                srt_path = os.path.join(server.OUTPUT_DIR, srt_path)
            except Exception:
                pass
        meta = _load_metadata(srt_path)
        model = _model_from_meta(meta, os.path.basename(str(it.get("path", ""))))

        size = int(it.get("size_bytes") or 0)
        total_bytes += size

        channel = str(it.get("channel", ""))
        entry = per_channel.setdefault(channel, {"count": 0, "bytes": 0})
        entry["count"] += 1
        entry["bytes"] += size

        m = per_model.setdefault(model, {"count": 0, "bytes": 0, "duration": 0.0})
        m["count"] += 1
        m["bytes"] += size

        try:
            duration = float(meta.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0:
            total_duration += duration
            with_duration += 1
            m["duration"] += duration

        for media in it.get("media") or []:
            fmt = str(media.get("format", "?"))
            media_format[fmt] = media_format.get(fmt, 0) + 1

    cards = [
        _card("Subtitles", str(len(items))),
        _card("Channels", str(len(per_channel))),
        _card("Models used", str(len(per_model))),
        _card("Subtitle size", _fmt_bytes(total_bytes)),
        _card(
            "Transcribed audio",
            _fmt_duration(total_duration),
            f"{with_duration} of {len(items)} have duration",
        ),
    ]

    def table(counts: Dict[str, Dict[str, int]], label: str) -> str:
        if not counts:
            return f"<h2>{label}</h2><p class='empty'>Nothing recorded.</p>"
        rows = "".join(
            f"<tr><td>{html.escape(name or '(none)')}</td>"
            f"<td class='num'>{data['count']}</td>"
            f"<td class='num'>{_fmt_bytes(data['bytes'])}</td>"
            f"<td class='num'>{_fmt_duration(data.get('duration', 0)) if data.get('duration') else '-'}</td></tr>"
            for name, data in sorted(counts.items(), key=lambda kv: -kv[1]["count"])
        )
        return (
            f"<h2>{label}<span class='count'>{len(counts)}</span></h2>"
            "<table><thead><tr><th>name</th><th class='num'>subtitles</th>"
            f"<th class='num'>size</th><th class='num'>audio</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    # Job outcomes, from the jobs file the pipeline writes.
    try:
        from whisper_subs import get_jobs

        jobs = get_jobs()
    except Exception:
        jobs = []
    job_counts: Dict[str, int] = {}
    for j in jobs:
        job_counts[str(j.get("status", "unknown"))] = (
            job_counts.get(str(j.get("status", "unknown")), 0) + 1
        )

    media_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td class='num'>{v}</td></tr>"
        for k, v in sorted(media_format.items(), key=lambda kv: -kv[1])
    )
    media_block = (
        f"<h2>Media formats present</h2><table>{media_rows}</table>"
        if media_rows
        else ""
    )

    jobs_block = (
        "<h2>Transcription jobs</h2><table>"
        + "".join(
            f"<tr><td>{html.escape(k)}</td><td class='num'>{v}</td></tr>"
            for k, v in sorted(job_counts.items(), key=lambda kv: -kv[1])
        )
        + "</table>"
        if job_counts
        else ""
    )

    # Cache, straight from the module the JSON endpoint uses.
    cache_block = ""
    try:
        import audio_cache

        c = audio_cache.stats()
        cache_block = (
            "<h2>Audio cache</h2><div class='cards'>"
            + _card("Entries", str(c.get("total_entries", 0)))
            + _card("On disk", str(c.get("existing_files", 0)))
            + _card("Size", _fmt_bytes(c.get("total_size_bytes", 0)))
            + _card("Max files", str(c.get("max_files", "-")))
            + _card("Max age", f"{c.get('max_age_days', '-')}d")
            + "</div>"
        )
    except Exception:
        cache_block = ""

    body = (
        '<div class="cards">'
        + "".join(cards)
        + "</div>"
        + table(per_model, "By model")
        + table(per_channel, "By channel")
        + media_block
        + jobs_block
        + cache_block
        + '<p class="empty">Duration is only known for subtitles whose '
        ".metadata.json recorded it; older files may lack it.</p>"
    )

    return render_shell(
        "Statistics",
        "Aggregates across the whole library: what was transcribed, with which "
        "model, and how much audio that represents.",
        "/stats",
        body,
    )
