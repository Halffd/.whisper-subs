#!/usr/bin/env python3
"""Rendering of the model/adapter catalog for the CLI.

Kept apart from model.py so both `--help` and `--model-list` print exactly
the same grouped view, and so argparse can build the help epilog lazily
without importing the runtime when it is not needed.
"""

from __future__ import annotations

from typing import List, Optional

MAX_HELP_MODELS_PER_GROUP = 6


def format_catalog(
    groups: Optional[List[dict]] = None,
    width: int = 100,
    limit_per_group: Optional[int] = None,
) -> str:
    """Render adapters and their models as an aligned, grouped listing.

    `groups` comes from TranscriptionContext.list_available_adapters(). When
    it is omitted the catalog is built from the registry directly.
    """
    if groups is None:
        from model import get_context

        groups = get_context().list_available_adapters()

    lines: List[str] = []
    for group in sorted(groups, key=lambda g: str(g["prefix"])):
        mark = "+" if group["available"] else "-"
        prefix = group["prefix"]
        name = group.get("name", "")
        # "prefix  name" heading; unavailable groups stay visible but marked.
        heading = f"  {mark} {prefix}"
        if name and name != prefix:
            heading = f"  {mark} {prefix:<12} {name}"

        models = list(group.get("models") or [])
        shown = models if limit_per_group is None else models[:limit_per_group]
        hidden = len(models) - len(shown)

        if not shown:
            lines.append(f"{heading}")
            lines.append("      (no models)")
            lines.append("")
            continue

        # Model names sit in one column so they stay scannable.
        joined = "  ".join(shown)
        lines.append(heading)
        lines.append(f"      {joined}")
        if hidden > 0:
            lines.append(f"      ... and {hidden} more (see --model-list)")
        lines.append("")

    lines.append("  + available    - missing dependency or API key")
    lines.append("  Use <prefix>:<model> to select one, e.g. groq:whisper-large-v3")
    return "\n".join(lines).rstrip() + "\n"


def build_help_epilog() -> str:
    """Catalog block appended to --help."""
    try:
        catalog = format_catalog(limit_per_group=MAX_HELP_MODELS_PER_GROUP)
    except Exception as exc:  # import/runtime failure must not break --help
        return f"Models:\n\n  (catalog unavailable: {exc})\n"

    return "Models:\n" + catalog
