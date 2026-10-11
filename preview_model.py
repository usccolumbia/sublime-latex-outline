"""Pure helpers for the hover previews (image lookup, table text grid, popup HTML), testable without Sublime."""
import html
import os

IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".eps")
RASTER = (".png", ".jpg", ".jpeg", ".gif")


def resolve_image(name, base_dir, graphicspath=(), isfile=os.path.isfile):
    """Find the file behind an \\includegraphics argument: relative to the source file and to each \\graphicspath directory."""
    name = name.strip()
    dirs = [os.path.normpath(os.path.join(base_dir, g)) for g in graphicspath] + [base_dir]
    exts = [""] if os.path.splitext(name)[1].lower() in IMG_EXTS else [""] + list(IMG_EXTS)
    for d in dirs:
        for e in exts:
            p = os.path.normpath(os.path.join(d, name + e))
            if isfile(p):
                return p
    return None


def table_text(rows, width=44, max_rows=14, max_cols=8):
    """Monospace grid of a table's cells, shrunk to roughly `width` characters; long tables and wide rows are cut with an ellipsis."""
    if not rows:
        return ""
    ncols = min(max(len(r) for r in rows), max_cols)
    cap = max(5, (width - (ncols - 1) * 2) // ncols)
    cells = [[(c if len(c) <= cap else c[: cap - 1] + "…") for c in (r + [""] * ncols)[:ncols]] for r in rows[:max_rows]]
    w = [max(len(r[j]) for r in cells) for j in range(ncols)]
    lines = ["  ".join(c.ljust(w[j]) for j, c in enumerate(r)).rstrip() for r in cells]
    if len(rows) > max_rows:
        lines.append("… %d more rows" % (len(rows) - max_rows))
    if max(len(r) for r in rows) > max_cols:
        lines.append("… %d more columns" % (max(len(r) for r in rows) - max_cols))
    return "\n".join(lines)


def popup_html(entry, images=(), note=""):
    """images: list of (data_uri, label) already prepared; note: extra line such as 'rendering preview...'."""
    d = entry.data or {}
    title = html.escape(entry.title.split(":", 1)[0])
    cap = html.escape(d.get("caption") or entry.title.split(":", 1)[-1].strip())
    body = ['<body id="outline-preview" style="padding:4px"><b>%s</b><br>%s' % (title, cap)]
    for uri, label in images:
        body.append('<br><br><img src="%s">%s' % (uri, ("<br><i>%s</i>" % html.escape(label)) if label else ""))
    if entry.kind == "table":
        txt = table_text(d.get("rows") or [])
        body.append("<br><br><pre style=\"font-size:0.85em\">%s</pre>" % html.escape(txt) if txt else "<br><i>(no table body found)</i>")
    if note:
        body.append("<br><i>%s</i>" % html.escape(note))
    body.append("</body>")
    return "".join(body)
