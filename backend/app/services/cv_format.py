"""Text normalisation for the CV template — pure functions, no I/O.

Per the layered-architecture rule this module lives in `app.services` and
MUST NOT import FastAPI. `cv_engine` calls it right before scoring and
rendering so every client (web form, API, future importers) gets the same
clean output.

Why it exists (bugs seen on a real CV sent to an employer, 2026-09-28):
- Skills were split on every "/" in the browser, so "(OpenAI / Anthropic)",
  "CI/CD" and "Agile/Scrum" broke into orphan fragments in the PDF.
- Bullets pasted from an LLM or a doc kept their "*" / "-" / "•" markers,
  which rendered as double bullets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_OPENERS = "([{"
_CLOSERS = ")]}"

# Group separators inside one line (a pasted one-liner). A bare "/" is
# deliberately NOT a separator: it lives inside real skill names ("CI/CD",
# "HTML5/CSS3"). Newlines always start a fresh group context.
_GROUP_SEPARATORS = (" / ", " | ", ";")

_MAX_LABEL_LENGTH = 40

# Leading list markers: symbols (*, -, •, ·, –, —, >) or "1." / "1)". A marker
# only counts when followed by whitespace, so "2.5M users" or "-10% latency"
# keep their numbers.
_MARKER_CHARS = "*\\-•●▪◦·–—>"
_BULLET_MARKER = re.compile(rf"^(?:[{_MARKER_CHARS}]+|\d{{1,2}}[.)])\s+")
_ONLY_MARKERS = re.compile(rf"[{_MARKER_CHARS}\s]*")
_MARKDOWN_BOLD = re.compile(r"\*\*(.+?)\*\*")


@dataclass
class SkillGroup:
    """A labelled skills line, e.g. "Frontend: React, TypeScript"."""

    label: str
    items: list[str] = field(default_factory=list)


@dataclass
class SkillsLayout:
    """Skills ready for the template: labelled groups plus unlabelled items."""

    groups: list[SkillGroup] = field(default_factory=list)
    ungrouped: list[str] = field(default_factory=list)

    @property
    def flat(self) -> list[str]:
        """Every skill in display order, labels dropped."""
        items: list[str] = []
        for group in self.groups:
            items.extend(group.items)
        items.extend(self.ungrouped)
        return items


def split_top_level(text: str, separators: tuple[str, ...]) -> list[str]:
    """Split `text` on any separator that sits outside (), [] and {}.

    Returns stripped, non-empty parts. Unbalanced closers are ignored, so a
    stray ")" never makes the rest of the string unsplittable.
    """
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    i = 0
    while i < len(text):
        char = text[i]
        if depth == 0:
            separator = next((s for s in separators if text.startswith(s, i)), None)
            if separator is not None:
                parts.append("".join(buffer))
                buffer = []
                i += len(separator)
                continue
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS and depth > 0:
            depth -= 1
        buffer.append(char)
        i += 1
    parts.append("".join(buffer))
    return [part.strip() for part in parts if part.strip()]


def _split_label(chunk: str) -> tuple[str | None, str]:
    """Return (label, rest) when the chunk looks like "Label: a, b"."""
    depth = 0
    for index, char in enumerate(chunk):
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS and depth > 0:
            depth -= 1
        elif char == ":" and depth == 0:
            label = chunk[:index].strip()
            rest = chunk[index + 1 :].strip()
            is_label = (
                0 < len(label) <= _MAX_LABEL_LENGTH
                and "," not in label
                and rest
                and not rest.startswith("//")  # a URL, not a label
            )
            return (label, rest) if is_label else (None, chunk)
    return None, chunk


def _split_items(text: str) -> list[str]:
    """Comma-split outside parentheses; drop a sentence-final period."""
    items: list[str] = []
    for raw in split_top_level(text, (",",)):
        item = raw.strip()
        if item.endswith(".") and not item.endswith(".."):
            item = item[:-1].rstrip()
        if item:
            items.append(item)
    return items


def _dedupe(items: list[str], seen: set[str]) -> list[str]:
    unique: list[str] = []
    for item in items:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def normalize_skills(chunks: list[str]) -> SkillsLayout:
    """Turn raw skill strings into labelled groups and loose items.

    Accepts one group per line ("Frontend: React, TypeScript"), plain comma
    lists, or a pasted one-liner with " / " between groups. Within one line,
    an unlabelled part that follows a labelled one continues that group, so
    "Frontend: React / Next.js" stays together; a new line never continues
    the previous line's group.
    """
    layout = SkillsLayout()
    seen: set[str] = set()

    for chunk in chunks:
        for line in chunk.splitlines():
            current: SkillGroup | None = None
            for part in split_top_level(line, _GROUP_SEPARATORS):
                label, rest = _split_label(part)
                items = _dedupe(_split_items(rest), seen)
                if label is not None:
                    current = next(
                        (g for g in layout.groups if g.label.casefold() == label.casefold()),
                        None,
                    )
                    if current is None:
                        current = SkillGroup(label=label)
                        layout.groups.append(current)
                    current.items.extend(items)
                elif current is not None:
                    current.items.extend(items)
                else:
                    layout.ungrouped.extend(items)

    layout.groups = [g for g in layout.groups if g.items]
    return layout


def clean_bullet(text: str) -> str:
    """Strip list markers and markdown bold from one achievement line.

    Returns "" for a line made only of markers, so callers can drop it.
    """
    cleaned = text.strip()
    if _ONLY_MARKERS.fullmatch(cleaned):
        return ""
    while True:
        stripped = _BULLET_MARKER.sub("", cleaned, count=1).strip()
        if stripped == cleaned:
            break
        cleaned = stripped
    return _MARKDOWN_BOLD.sub(r"\1", cleaned).strip()
