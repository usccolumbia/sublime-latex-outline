"""Rendering and navigation logic of the outline panel, independent of Sublime (testable)."""
from collections import namedtuple

LEVEL_KINDS = ("part", "chapter", "section", "subsection", "subsubsection", "paragraph", "subparagraph")

Row = namedtuple("Row", "text entry index has_children collapsed")


def indent_ranks(entries):
    """Indent level of every entry: its section rank minus the shallowest rank present (floats and TODOs sit under the section they follow)."""
    ranks = [e.rank for e in entries if e.kind in LEVEL_KINDS]
    base = min(ranks) if ranks else 0
    out, last = [], 0
    for e in entries:
        if e.kind not in LEVEL_KINDS:
            out.append(last + 1)
        else:
            sorted_ranks = sorted(set(ranks))
            last = sorted_ranks.index(e.rank)   # compact: skipped levels (section -> paragraph) do not leave holes
            out.append(last)
    return out


def key(e):
    return (e.path, e.line)


def build_rows(entries, collapsed=frozenset(), markers=("⌄ ", "› ")):
    """markers = (expanded, collapsed) strings, both 2 characters wide so the tree stays aligned."""
    ind = indent_ranks(entries)
    rows, skip_until = [], None
    for i, e in enumerate(entries):
        if skip_until is not None:
            if ind[i] > skip_until:
                continue
            skip_until = None
        has_children = i + 1 < len(entries) and ind[i + 1] > ind[i]
        is_collapsed = has_children and key(e) in collapsed
        marker = (markers[1] if is_collapsed else markers[0]) if has_children else "  "
        icon = ""
        rows.append(Row("  " * ind[i] + marker + e.title, e, i, has_children, is_collapsed))
        if is_collapsed:
            skip_until = ind[i]
    return rows


def marker_width(row, entries):
    ind = indent_ranks(entries)[row.index]
    return ind * 2 + 2


def current_row(rows, path, line):
    """Index in rows of the last entry (in this file) at or before `line`, or None. Collapsed parents stand in for hidden children."""
    best = None
    for r, row in enumerate(rows):
        if row.entry.path == path and row.entry.line <= line:
            best = r
    return best
