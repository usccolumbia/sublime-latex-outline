"""Sublime Text 3/4 plugin: an Overleaf-style "File outline" side panel for LaTeX files.

Command palette: "LaTeX Outline: Toggle".  Click an entry (or press Enter) to jump to it, click the triangle to fold or unfold,
the entry of the section you are editing is highlighted, and the outline refreshes as you type and when you switch .tex files.
"""
import base64
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback

import sublime
import sublime_plugin

from .outline_model import build_rows, current_row, marker_width, key
from .outline_parser import parse_outline, document_stats, extract_macros, extract_packages
from .preview_model import popup_html, resolve_image, RASTER, equation_tex, png_size

OUTLINE_NAME = "File outline"
STATE = {}  # window id -> dict(view=outline view id, src=source view id, rows=[Row], collapsed=set(), layout=original layout)


def log(msg):
    """Append to the file named by the debug_log setting (off by default); used to report errors without the console."""
    path = settings().get("debug_log", "")
    if path:
        try:
            with open(os.path.expanduser(path), "a") as fh:
                fh.write(msg + "\n")
        except OSError:
            pass


def guarded(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except Exception:
            log("ERROR in %s:\n%s" % (fn.__name__, traceback.format_exc()))
            raise
    return wrapper


def settings():
    return sublime.load_settings("LaTeXOutline.sublime-settings")


def is_tex(view):
    name = view.file_name() or ""
    return name.endswith((".tex", ".ltx", ".sty", ".cls")) or view.match_selector(0, "text.tex.latex")


def resolver_for(root_path):
    base = os.path.dirname(root_path) if root_path else ""

    def resolve(name, from_path):
        folder = os.path.dirname(from_path) if from_path and os.path.isabs(from_path) else base
        for cand in (name, name + ".tex"):
            for d in (folder, base):
                p = os.path.normpath(os.path.join(d, cand))
                if os.path.isfile(p):
                    try:
                        with open(p, encoding="utf-8", errors="replace") as fh:
                            return p, fh.read()
                    except OSError:
                        pass
        return None
    return resolve


def outline_view(window):
    st = STATE.get(window.id())
    if not st:
        return None
    for v in window.views():
        if v.id() == st["view"]:
            return v
    return None


def default_options():
    s = settings()
    legacy = bool(s.get("show_floats", False))
    return {"figures": bool(s.get("show_figures", True)) or legacy, "tables": bool(s.get("show_tables", True)) or legacy, "todos": bool(s.get("show_todos", False)),
            "equations": bool(s.get("show_equations", True))}


def compute_rows(window, src):
    s = settings()
    st = STATE[window.id()]
    opts = st.setdefault("opts", default_options())
    text = src.substr(sublime.Region(0, src.size()))
    path = src.file_name() or ""
    resolver = resolver_for(path) if (s.get("follow_inputs", False) and path) else None
    entries = parse_outline(text, path, figures=opts["figures"], tables=opts["tables"], todos=opts["todos"], resolver=resolver,
                            equations=opts["equations"], unnumbered=bool(s.get("show_unnumbered_equations", False)))
    markers = (str(s.get("expanded_marker", "⌄ "))[:2].ljust(2), str(s.get("collapsed_marker", "› "))[:2].ljust(2))
    return entries, build_rows(entries, st["collapsed"], markers)


FLOAT_SCOPE = "meta.latex-outline.float"
FLOAT_CURRENT_SCOPE = "meta.latex-outline.float.current"
EQ_SCOPE = "meta.latex-outline.equation"
EQ_CURRENT_SCOPE = "meta.latex-outline.equation.current"
SCHEME_FILE = "LaTeXOutline-floats.sublime-color-scheme"


def ensure_scheme(ov, src):
    """Give the outline view a color scheme that extends the source view's scheme with a background for figure/table rows."""
    s = settings()
    bg = str(s.get("float_background", "#E9DCC9"))
    if not bg:
        return False
    base = src.settings().get("color_scheme") or ov.settings().get("color_scheme")
    if base and base.startswith("Packages/User/" + SCHEME_FILE.replace(".sublime-color-scheme", "")):
        base = None
    if base and not base.startswith("Packages/"):   # the setting may hold a bare file name: "extends" needs the resource path
        found = sublime.find_resources(os.path.basename(base))
        base = found[0] if found else None
    fg = str(s.get("float_foreground", "#4A3728"))
    rules = [{"scope": FLOAT_SCOPE, "background": bg, "foreground": fg},
             {"scope": FLOAT_CURRENT_SCOPE, "background": str(s.get("float_current_background", "#C9AE86")), "foreground": "#2E1F12"},
             {"scope": EQ_SCOPE, "background": str(s.get("equation_background", "#DCE4F0")), "foreground": str(s.get("equation_foreground", "#2B3A55"))},
             {"scope": EQ_CURRENT_SCOPE, "background": str(s.get("equation_current_background", "#B8C7E0")), "foreground": "#16213A"}]
    body = {"extends": base, "rules": rules} if base else {"rules": rules}
    path = os.path.join(sublime.packages_path(), "User", SCHEME_FILE)
    text = json.dumps(body, indent=2)
    try:
        old = open(path).read() if os.path.exists(path) else None
        if old != text:
            with open(path, "w") as fh:
                fh.write(text)
    except OSError:
        return False
    resource = "Packages/User/" + SCHEME_FILE
    if resource not in sublime.find_resources(SCHEME_FILE):
        return None   # Sublime has not indexed the new file yet: setting it now would raise "Unable to find ..."; the caller retries
    if ov.settings().get("color_scheme") != resource:
        ov.settings().set("color_scheme", resource)
    return True


def draw_floats(ov, rows):
    """Colour the figure/table rows (milk brown) and the equation rows (pale blue)."""
    groups = {"float": [], "eq": []}
    for i, r in enumerate(rows):
        k = "float" if r.entry.kind in ("figure", "table") else "eq" if r.entry.kind == "equation" else None
        if k:
            line = ov.line(ov.text_point(i, 0))
            groups[k].append(sublime.Region(line.begin(), min(line.end() + 1, ov.size())))
    ov.add_regions("outline_floats", groups["float"], FLOAT_SCOPE, flags=sublime.DRAW_NO_OUTLINE)
    ov.add_regions("outline_equations", groups["eq"], EQ_SCOPE, flags=sublime.DRAW_NO_OUTLINE)
    return len(groups["float"]) + len(groups["eq"])


@guarded
def render(window, src=None):
    st = STATE.get(window.id())
    ov = outline_view(window)
    if not st or not ov:
        return
    src = src or next((v for v in window.views() if v.id() == st["src"]), None)
    if src is None or not is_tex(src):
        return
    st["src"] = src.id()
    entries, rows = compute_rows(window, src)
    st["entries"], st["rows"] = entries, rows
    if opts_equations_render():
        text_all = src.substr(sublime.Region(0, src.size()))
        st["preamble"] = (extract_macros(text_all), extract_packages(text_all))
    body = "\n".join(r.text for r in rows) if rows else "  (no sections found)"
    s = settings()
    stats = None
    if s.get("show_stats", True) or s.get("stats_in_status_bar", True):
        stats = document_stats(src.substr(sublime.Region(0, src.size())), bool(s.get("stats_exclude_abstract", False)))
        short = "Words %s | Sections %d | Figures %d | Tables %d | Equations %d" % (format(stats["words"], ","), stats["sections"], stats["figures"], stats["tables"], stats["equations"])
        log("STATS " + short)
        if s.get("stats_in_status_bar", True):
            src.set_status("latex_outline_stats", short)
            ov.set_status("latex_outline_stats", short)
        if s.get("show_stats", True):
            left = ["Words %s" % format(stats["words"], ","), "Sections %d (+%d)" % (stats["sections"], stats["subsections"]), "Equations %d" % stats["equations"]]
            right = ["Figures %d" % stats["figures"], "Tables %d" % stats["tables"]]
            right += [""] * (len(left) - len(right))
            pad = max(len(x) for x in left) + 3
            body += "\n\n" + "-" * (pad + max(len(x) for x in right)) + "\n" + "\n".join(l.ljust(pad) + r for l, r in zip(left, right))
    ov.run_command("latex_outline_set_text", {"text": body})
    log("RENDERED %d rows for %s" % (len(rows), os.path.basename(src.file_name() or "")))
    ov.set_name(OUTLINE_NAME)
    ok = ensure_scheme(ov, src)
    if ok is None:
        tries = STATE[window.id()].get("scheme_tries", 0) + 1
        STATE[window.id()]["scheme_tries"] = tries
        if tries <= 15:
            sublime.set_timeout_async(lambda: render(window), 300)
    else:
        STATE[window.id()]["scheme_tries"] = 0
    n = draw_floats(ov, rows)
    log("FLOATS scheme=%s rows=%d colored; style=%s" % (ok, n, {k: v for k, v in ov.style_for_scope(FLOAT_SCOPE).items() if k in ("background", "foreground")}))
    highlight(window, src)


@guarded
def highlight(window, src):
    st, ov = STATE.get(window.id()), outline_view(window)
    if not st or not ov or not st.get("rows"):
        return
    row = src.rowcol(src.sel()[0].begin())[0] if len(src.sel()) else 0
    idx = current_row(st["rows"], src.file_name() or "", row)
    st["current_idx"] = idx
    if idx is None:
        ov.erase_regions("current")
        return
    region = ov.line(ov.text_point(idx, 0))
    kind = st["rows"][idx].entry.kind
    scope = FLOAT_CURRENT_SCOPE if kind in ("figure", "table") and settings().get("float_background", "#E9DCC9") else \
        EQ_CURRENT_SCOPE if kind == "equation" and settings().get("equation_background", "#DCE4F0") else "region.bluish"
    ov.add_regions("current", [region], scope, flags=sublime.DRAW_NO_OUTLINE)
    log("HIGHLIGHT cursor_row=%d -> outline_row=%d %r" % (row, idx, st["rows"][idx].text))
    ov.show(region, False)


THUMB_DIR = None


def thumb_dir():
    global THUMB_DIR
    if THUMB_DIR is None:
        THUMB_DIR = os.path.join(sublime.cache_path(), "LaTeXOutline")
        os.makedirs(THUMB_DIR, exist_ok=True)
    return THUMB_DIR


def make_thumbnail(path, max_dim=520):
    """PNG thumbnail of an image file as a data URI, or None. Raster images are shrunk and PDF/EPS are rendered to PNG with macOS `sips`
    (when available); other systems fall back to the raster file itself."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = hashlib.sha1(("%s|%s|%s" % (path, st.st_mtime, max_dim)).encode()).hexdigest()
    out = os.path.join(thumb_dir(), key + ".png")
    if not os.path.exists(out):
        sips = shutil.which("sips")
        ext = os.path.splitext(path)[1].lower()
        if sips:
            try:
                subprocess.run([sips, "-s", "format", "png", "-Z", str(max_dim), path, "--out", out], check=True, capture_output=True, timeout=30)
            except Exception as e:
                log("THUMB sips failed for %s: %s" % (path, e))
        elif ext in RASTER and st.st_size < 1500000:
            shutil.copyfile(path, out)
    if not os.path.exists(out):
        return None
    with open(out, "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode("ascii")


def preview_images(entry, limit):
    d = entry.data or {}
    base = os.path.dirname(entry.path) if entry.path else ""
    found = []
    for name in d.get("images", [])[:limit]:
        p = resolve_image(name, base, d.get("graphicspath", ()))
        found.append((name, p))
    return found


def open_in_viewer(paths):
    """Open files with the system viewer (or the program named by the image_viewer setting)."""
    viewer = str(settings().get("image_viewer", "")).strip()
    for p in paths:
        if viewer:
            cmd = [viewer, p]
        elif sys.platform == "darwin":
            cmd = ["open", p]
        elif sys.platform.startswith("win"):
            os.startfile(p)  # noqa
            continue
        else:
            cmd = ["xdg-open", p]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("OPEN %s" % " ".join(cmd))


def open_entry_images(window, row):
    """Open the full-size image(s) of the figure on outline row `row`. Returns the number of files opened."""
    st = STATE.get(window.id())
    if not st or row >= len(st["rows"]):
        return 0
    entry = st["rows"][row].entry
    if entry.kind != "figure":
        sublime.status_message("LaTeX Outline: the row is not a figure")
        return 0
    found = [p for _, p in preview_images(entry, 20) if p]
    if not found:
        sublime.status_message("LaTeX Outline: no image file found for this figure")
        return 0
    open_in_viewer(found)
    sublime.status_message("LaTeX Outline: opened %d image file(s)" % len(found))
    return len(found)


def opts_equations_render():
    return bool(settings().get("equation_render", True))


TEX_DIRS = ("/Library/TeX/texbin", "/usr/local/bin", "/opt/homebrew/bin", "/usr/texbin", "/usr/bin", "/bin")


def tex_env():
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(list(TEX_DIRS) + [env.get("PATH", "")])
    return env


def render_equation(tex, dpi=200, timeout=30):
    """Typeset a standalone LaTeX document to a PNG with latex + dvipng (or pdflatex + pdftoppm). Returns (png path, "") or (None, reason)."""
    key = hashlib.sha1((tex + "|%d" % dpi).encode()).hexdigest()
    out = os.path.join(thumb_dir(), "eq-" + key + ".png")
    if os.path.exists(out):
        return out, ""
    work = os.path.join(thumb_dir(), "tmp-" + key)
    os.makedirs(work, exist_ok=True)
    env = tex_env()
    try:
        with open(os.path.join(work, "eq.tex"), "w") as fh:
            fh.write(tex)
        if shutil.which("latex", path=env["PATH"]) and shutil.which("dvipng", path=env["PATH"]):
            cmds = [["latex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "eq.tex"],
                    ["dvipng", "-D", str(dpi), "-T", "tight", "-bg", "White", "-fg", "Black", "-o", "eq.png", "eq.dvi"]]
        elif shutil.which("pdflatex", path=env["PATH"]) and shutil.which("pdftoppm", path=env["PATH"]):
            cmds = [["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "eq.tex"],
                    ["pdftoppm", "-r", str(dpi), "-png", "-singlefile", "eq.pdf", "eq"]]
        else:
            return None, "no LaTeX found (install TeX Live or MacTeX: latex + dvipng)"
        for cmd in cmds:
            r = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                msg = ""
                logp = os.path.join(work, "eq.log")
                if os.path.exists(logp):
                    lines = open(logp, errors="replace").read().splitlines()
                    bad = [i for i, l in enumerate(lines) if l.startswith("!")]
                    if bad:
                        msg = " ".join(x.strip() for x in lines[bad[0]: bad[0] + 2])[:160]
                return None, msg or "LaTeX failed"
        shutil.copyfile(os.path.join(work, "eq.png"), out)
        return out, ""
    except subprocess.TimeoutExpired:
        return None, "LaTeX timed out"
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)
    finally:
        shutil.rmtree(work, ignore_errors=True)


@guarded
def show_preview(window, row, point=None):
    st = STATE.get(window.id())
    ov = outline_view(window)
    if not st or not ov or row >= len(st["rows"]):
        return False
    entry = st["rows"][row].entry
    if entry.kind not in ("figure", "table", "equation") or not settings().get("hover_preview", True):
        return False
    st["last_row"] = row
    pkey = (entry.path, entry.line)
    if ov.is_popup_visible() and st.get("preview_key") == pkey:   # the mouse is still on the same entry: keep the popup, avoid flicker
        return True
    st["preview_key"] = pkey
    point = ov.text_point(row, 0) if point is None else point
    width = max(200, int(ov.viewport_extent()[0]) - 24)
    st["preview_token"] = st.get("preview_token", 0) + 1
    token = st["preview_token"]
    limit = int(settings().get("preview_max_images", 3))
    files = preview_images(entry, limit) if entry.kind == "figure" else []
    ready = []
    note = ""
    for name, p in files:
        if p is None:
            note = "image not found: %s" % name
    pending = [(n, p) for n, p in files if p]

    def popup(note_text, imgs):
        html_ = popup_html(entry, imgs, note_text)
        if any(p for _, p in files):
            html_ = html_.replace('</body>', '<br><a href="open">Open full image</a></body>')
        if ov.is_popup_visible() and st.get("preview_token") == token:
            ov.update_popup(html_)
        else:
            ov.show_popup(html_, flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY, location=point, on_hide=lambda: st.pop("preview_key", None), on_navigate=lambda href: open_entry_images(window, row) if href == "open" else None, max_width=width, max_height=int(settings().get("preview_max_height", 520)))
        log("PREVIEW row=%d kind=%s images=%d note=%r html=%d chars" % (row, entry.kind, len(imgs), note_text, len(html_)))

    eq_job = None
    if entry.kind == "equation" and opts_equations_render() and st.get("preamble"):
        macros, packages = st["preamble"]
        tex = equation_tex(entry, macros, packages, int(settings().get("equation_width_pt", 420)))
        if tex:
            eq_job = tex
    popup(note or ("rendering preview…" if (pending or eq_job) else ""), [])
    if eq_job:
        def work_eq():
            png, err = render_equation(eq_job, int(settings().get("equation_dpi", 200)), int(settings().get("latex_timeout", 30)))
            imgs, nt = [], ""
            if png:
                with open(png, "rb") as fh:
                    uri = "data:image/png;base64," + base64.b64encode(fh.read()).decode("ascii")
                size = png_size(png)
                w = min(width - 16, int(size[0] * 0.55)) if size else width - 16
                imgs.append((uri, "", w))
            else:
                nt = "could not typeset: " + err
                log("EQRENDER failed: " + err)
            if st.get("preview_token") == token:
                sublime.set_timeout(lambda: popup(nt, imgs), 0)
        threading.Thread(target=work_eq, daemon=True).start()
    if pending:
        def work():
            imgs, nt = [], note
            for name, p in pending:
                uri = make_thumbnail(p)
                if uri:
                    imgs.append((uri, os.path.basename(p), width - 16))
                else:
                    nt = "could not render %s" % os.path.basename(p)
            if st.get("preview_token") == token:
                sublime.set_timeout(lambda: popup(nt, imgs), 0)
        threading.Thread(target=work, daemon=True).start()
    return True


class LatexOutlineSetTextCommand(sublime_plugin.TextCommand):
    @guarded
    def run(self, edit, text=""):
        was = self.view.is_read_only()
        self.view.set_read_only(False)
        sel = self.view.viewport_position()
        self.view.replace(edit, sublime.Region(0, self.view.size()), text)
        self.view.set_read_only(True)
        self.view.set_viewport_position(sel, False)
        self.view.sel().clear()


class LatexOutlineToggleCommand(sublime_plugin.WindowCommand):
    @guarded
    def run(self):
        w = self.window
        ov = outline_view(w)
        log('TOGGLE window=%s active=%s file=%s groups=%d existing_outline=%s' % (w.id(), w.active_view().id() if w.active_view() else None, w.active_view().file_name() if w.active_view() else None, w.num_groups(), bool(ov)))
        if not ov:
            orphans = [v for v in w.views() if v.settings().get("latex_outline_view")]
            if orphans:   # left over from a plugin reload: treat the toggle as "close"
                for v in orphans:
                    v.close()
                if w.num_groups() == 2:
                    w.set_layout({"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]})
                log("TOGGLE closed %d orphan outline view(s)" % len(orphans))
                return
        if ov:
            st = STATE.pop(w.id())
            ov.close()
            if st.get("layout") and w.num_groups() == 2:
                w.set_layout(st["layout"])
            return
        src = w.active_view()
        if src is None or not is_tex(src):   # e.g. focus is in an empty group: use the .tex view shown in another group
            for g in range(w.num_groups()):
                v = w.active_view_in_group(g)
                if v is not None and is_tex(v):
                    src = v
                    break
        if src is None or not is_tex(src):
            log("TOGGLE aborted: active view is not a tex file")
            sublime.status_message("LaTeX Outline: open a .tex file first")
            return
        layout = w.layout()
        saved = None
        if w.num_groups() == 1:
            saved = layout
            width = float(settings().get("width", 0.22))
            w.set_layout({"cols": [0.0, width, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]})
            src_group = 1
            w.set_view_index(src, 1, 0)
        else:
            src_group = w.active_group()
        ov = w.new_file()
        STATE[w.id()] = dict(view=ov.id(), src=src.id(), rows=[], entries=[], collapsed=set(), layout=saved)
        w.set_view_index(ov, 0, 0)
        ov.set_scratch(True)
        ov.set_name(OUTLINE_NAME)
        ov.assign_syntax("scope:text.plain") if hasattr(ov, "assign_syntax") else ov.set_syntax_file("Packages/Text/Plain text.tmLanguage")
        for k, v in (("line_numbers", False), ("gutter", False), ("word_wrap", False), ("draw_white_space", "none"), ("scroll_past_end", False),
                     ("highlight_line", False), ("margin", 0), ("fold_buttons", False), ("draw_indent_guides", False), ("latex_outline_view", True),
                     ("font_size", float(settings().get("font_size", 11)))):
            ov.settings().set(k, v)
        w.focus_group(src_group)
        w.focus_view(src)
        render(w, src)
        log("LAYOUT groups=%d outline_group=%s src_group=%s outline_size=%d outline_first_lines=%r" % (w.num_groups(), w.get_view_index(ov)[0], w.get_view_index(src)[0], ov.size(), ov.substr(sublime.Region(0, min(ov.size(), 160)))))


class LatexOutlineToggleOptionCommand(sublime_plugin.WindowCommand):
    """Show or hide figures, tables or TODO markers in the outline of this window (the settings give the defaults)."""

    @guarded
    def run(self, option="figures"):
        st = STATE.get(self.window.id())
        if not st:
            sublime.status_message("LaTeX Outline: open the outline first")
            return
        opts = st.setdefault("opts", default_options())
        opts[option] = not opts.get(option, False)
        sublime.status_message("LaTeX Outline: %s %s" % (option, "shown" if opts[option] else "hidden"))
        render(self.window)

    def is_enabled(self):
        return self.window.id() in STATE


class LatexOutlineGotoCommand(sublime_plugin.TextCommand):
    """Enter in the outline: jump to the entry on the cursor line."""

    @guarded
    def run(self, edit, toggle=False):
        w = self.view.window()
        st = STATE.get(w.id()) if w else None
        if not st:
            return
        row = self.view.rowcol(self.view.sel()[0].begin() if len(self.view.sel()) else 0)[0]
        activate(w, row, toggle_only=toggle)


@guarded
def activate(window, row, col=None, toggle_only=False):
    st = STATE.get(window.id())
    if not st or row >= len(st["rows"]):
        return
    r = st["rows"][row]
    e = r.entry
    st["last_row"] = row
    if r.has_children and (toggle_only or (col is not None and col < marker_width(r, st["entries"]))):
        k = key(e)
        st["collapsed"].symmetric_difference_update({k})
        render(window)
        return
    src = next((v for v in window.views() if v.id() == st["src"]), None)
    if src is not None and (src.file_name() or "") == e.path:
        window.focus_view(src)
        pt = src.text_point(e.line, 0)
        src.sel().clear()
        src.sel().add(sublime.Region(pt))
        src.show_at_center(pt)
    elif e.path:
        window.open_file("%s:%d" % (e.path, e.line + 1), sublime.ENCODED_POSITION)


class LatexOutlineListener(sublime_plugin.EventListener):
    _pending = {}

    @guarded
    def on_post_text_command(self, view, command_name, args):
        if command_name == "drag_select" and view.settings().get("latex_outline_view"):
            w = view.window()
            if w and len(view.sel()):
                row, col = view.rowcol(view.sel()[0].begin())
                activate(w, row, col)

    @guarded
    def _refresh(self, view):
        w = view.window()
        if not w or w.id() not in STATE or view.settings().get("latex_outline_view") or not is_tex(view):
            return
        token = self._pending.get(w.id(), 0) + 1
        self._pending[w.id()] = token

        def go():
            if self._pending.get(w.id()) == token:
                render(w, view)
        sublime.set_timeout_async(go, int(settings().get("refresh_delay_ms", 400)))

    @guarded
    def on_hover(self, view, point, hover_zone):
        if hover_zone != sublime.HOVER_TEXT or not view.settings().get("latex_outline_view"):
            return
        w = view.window()
        if w and w.id() in STATE:
            show_preview(w, view.rowcol(point)[0], point)

    @guarded
    def on_modified_async(self, view):
        w = view.window()
        if w and w.id() in STATE and STATE[w.id()]["src"] == view.id():
            self._refresh(view)

    @guarded
    def on_post_save_async(self, view):
        self._refresh(view)

    @guarded
    def on_activated_async(self, view):
        w = view.window()
        if w and w.id() in STATE and not view.settings().get("latex_outline_view") and is_tex(view) and STATE[w.id()]["src"] != view.id():
            STATE[w.id()]["src"] = view.id()
            render(w, view)

    @guarded
    def on_selection_modified_async(self, view):
        w = view.window()
        if w and w.id() in STATE and STATE[w.id()]["src"] == view.id():
            highlight(w, view)

    @guarded
    def on_pre_close(self, view):
        w = view.window()
        if w and w.id() in STATE and STATE[w.id()]["view"] == view.id():
            st = STATE.pop(w.id())
            if st.get("layout") and w.num_groups() == 2:
                sublime.set_timeout(lambda: w.set_layout(st["layout"]), 0)


class LatexOutlineDebugClickCommand(sublime_plugin.WindowCommand):
    """Test hook: simulate a click (or Enter) on an outline row and log what happened."""

    @guarded
    def run(self, row=0, col=None, toggle=False):
        w = self.window
        st = STATE.get(w.id())
        if not st:
            log("DEBUGCLICK no outline")
            return
        before = len(st["rows"])
        activate(w, row, col, toggle_only=toggle)
        src = next((v for v in w.views() if v.id() == st["src"]), None)
        line = src.rowcol(src.sel()[0].begin())[0] + 1 if src is not None and len(src.sel()) else None
        log("DEBUGCLICK row=%s col=%s toggle=%s rows %d->%d source_cursor_line=%s row_text=%r" % (row, col, toggle, before, len(st["rows"]), line, st["rows"][row].text if row < len(st["rows"]) else None))


def plugin_loaded():
    """After a plugin reload STATE is empty: close outline views left over from the previous session so toggling stays consistent."""
    for w in sublime.windows():
        for v in w.views():
            if v.settings().get("latex_outline_view"):
                v.close()


class LatexOutlineDebugHoverCommand(sublime_plugin.WindowCommand):
    """Test hook: show the hover preview of outline row N."""

    @guarded
    def run(self, row=0):
        log("DEBUGHOVER row=%s shown=%s" % (row, show_preview(self.window, row)))


class LatexOutlineOpenImageCommand(sublime_plugin.TextCommand):
    """In the outline: open the full-size image(s) of the figure on the cursor line with the system viewer (key: o)."""

    @guarded
    def run(self, edit):
        w = self.view.window()
        if w and len(self.view.sel()):
            open_entry_images(w, self.view.rowcol(self.view.sel()[0].begin())[0])


class LatexOutlineOpenImageRowCommand(sublime_plugin.WindowCommand):
    """Test hook: open the image(s) of outline row N."""

    @guarded
    def run(self, row=0):
        log("DEBUGOPEN row=%s opened=%s" % (row, open_entry_images(self.window, row)))


class LatexOutlineDebugKeyCommand(sublime_plugin.WindowCommand):
    """Test hook: put the caret on outline row N and run the command bound to `o` through the view, as the key would."""

    @guarded
    def run(self, row=0, command="latex_outline_open_image"):
        ov = outline_view(self.window)
        if ov is None:
            log("DEBUGKEY no outline")
            return
        ov.sel().clear()
        ov.sel().add(sublime.Region(ov.text_point(row, 0)))
        self.window.focus_view(ov)
        log("DEBUGKEY focused=%s outline_setting=%s row=%d" % (self.window.active_view().id() == ov.id(), ov.settings().get("latex_outline_view"), row))
        ov.run_command(command)


class LatexOutlineOpenFigureCommand(sublime_plugin.WindowCommand):
    """Open the full-size image(s) of a figure from anywhere (the editor keeps focus after you click an outline entry).
    Uses the figure row you last hovered or clicked in the outline, else the figure the cursor is in."""

    @guarded
    def run(self):
        st = STATE.get(self.window.id())
        if not st or not st.get("rows"):
            sublime.status_message("LaTeX Outline: open the outline first")
            return
        rows = st["rows"]
        cands = [st.get("last_row"), st.get("current_idx")]
        for r in cands:
            if r is not None and r < len(rows) and rows[r].entry.kind == "figure":
                open_entry_images(self.window, r)
                return
        sublime.status_message("LaTeX Outline: hover or click a figure in the outline first")

    def is_enabled(self):
        return self.window.id() in STATE
