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
    cap = "" if entry.kind == "equation" else html.escape(d.get("caption") or entry.title.split(":", 1)[-1].strip())
    body = ['<body id="outline-preview" style="padding:4px"><b>%s</b><br>%s' % (title, cap)]
    for img in images:
        uri, label = img[0], img[1]
        width = img[2] if len(img) > 2 else None
        body.append('<br><br><img %ssrc="%s">%s' % ('width="%d" ' % width if width else "", uri, ("<br><i>%s</i>" % html.escape(label)) if label else ""))
    if entry.kind == "equation":
        src = (d.get("source") or "").strip()
        if len(src) > 700:
            src = src[:700] + " …"
        lab = ("<br><i>label: %s</i>" % html.escape(d["label"])) if d.get("label") else ""
        body.append("%s<br><br><pre style=\"font-size:0.85em\">%s</pre>" % (lab, html.escape(src)))
    if entry.kind == "table":
        txt = table_text(d.get("rows") or [])
        body.append("<br><br><pre style=\"font-size:0.85em\">%s</pre>" % html.escape(txt) if txt else "<br><i>(no table body found)</i>")
    if note:
        body.append("<br><i>%s</i>" % html.escape(note))
    body.append("</body>")
    return "".join(body)


ENV_MAP = {"equation": "equation*", "align": "align*", "alignat": "align*", "flalign": "flalign*", "gather": "gather*", "multline": "multline*",
           "eqnarray": "eqnarray*", "displaymath": "equation*", "\\[": "equation*", "$$": "equation*"}


def equation_tex(entry, macros, packages, width_pt=420):
    """Complete LaTeX document (standalone class) that typesets one equation entry, or None. macros: dict from extract_macros;
    packages: list of (options, name) from extract_packages."""
    import re
    try:
        from .outline_parser import macro_closure
    except ImportError:   # run as a top-level module (tests)
        from outline_parser import macro_closure
    d = entry.data or {}
    body = d.get("source") or ""
    if not body.strip():
        return None
    env = ENV_MAP.get((d.get("env") or "equation").rstrip("*"), "equation*")
    body = re.sub(r"\\label\s*\{[^{}]*\}", "", body)
    body = re.sub(r"\\(?:nonumber|notag)\b", "", body)
    tag = d.get("tag")
    number = d.get("number") or ""
    if not tag and re.fullmatch(r"\d+", number) and env == "equation*":
        body = body + " \\tag{%s}" % number
    lines = ["\\documentclass[border=6pt,varwidth=%dpt]{standalone}" % width_pt,
             "\\usepackage{amsmath,amssymb,amsfonts,bm,mathtools}"]
    seen = set(["amsmath", "amssymb", "amsfonts", "bm", "mathtools"])
    for opts, pkg in packages:
        if pkg not in seen:
            seen.add(pkg)
            lines.append("\\usepackage%s{%s}" % ("[%s]" % opts if opts else "", pkg))
    for name in sorted(macro_closure(body, macros)):
        kind, text = macros[name]
        lines.append("\\let\\%s\\relax" % name)
        if kind in ("newcommand", "renewcommand", "providecommand", "DeclareRobustCommand"):
            text = re.sub(r"^\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)", r"\\newcommand", text)
        lines.append(text)
    lines += ["\\begin{document}", "\\begin{%s}" % env, body, "\\end{%s}" % env, "\\end{document}"]
    return "\n".join(lines) + "\n"


def png_size(path):
    """(width, height) of a PNG file, or None."""
    import struct
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
    except OSError:
        pass
    return None
