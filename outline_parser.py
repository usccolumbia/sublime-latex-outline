"""Pure-Python LaTeX outline extraction (no Sublime dependency, so it can be unit-tested).

parse_outline(text, path, ...) -> list of Entry for \\part ... \\subparagraph, optionally floats (figure/table captions) and \\TODO{...}
markers, in document order. \\input / \\include / \\subfile are followed (relative to the root file) when a resolver is given.
Comments (%...), verbatim-like environments and \\iffalse ... \\fi blocks are ignored.
"""
import os
import re
from collections import namedtuple

Entry = namedtuple("Entry", "kind level rank title path line data", defaults=(None,))  # line is 0-based; data: figure/table details (dict) or None

LEVELS = {"part": 0, "chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4, "paragraph": 5, "subparagraph": 6}
SECTION_RE = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)(\*?)\s*(?:\[[^\]]*\])?\s*\{")
FLOAT_RE = re.compile(r"\\begin\{(figure\*?|table\*?)\}")
CAPTION_RE = re.compile(r"\\caption\s*(?:\[[^\]]*\])?\s*\{")
TODO_RE = re.compile(r"\\TODO\s*\{")
INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
SKIP_ENVS = ("verbatim", "lstlisting", "minted", "comment", "Verbatim")
STRIP_CMDS = ("textbf", "textit", "emph", "texttt", "textsc", "textrm", "textsf", "mathrm", "mathbf", "mathit", "text", "underline", "textsuperscript", "textsubscript")


def mask_comments(text):
    """Blank out comments, skipped environments and \\iffalse blocks, keeping offsets and newlines intact."""
    out = []
    for line in text.split("\n"):
        m = re.search(r"(?<!\\)%", line)
        out.append(line[: m.start()] + " " * (len(line) - m.start()) if m else line)
    t = "\n".join(out)

    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    for env in SKIP_ENVS:
        t = re.sub(r"\\begin\{%s\*?\}.*?\\end\{%s\*?\}" % (env, env), blank, t, flags=re.S)
    t = re.sub(r"\\iffalse\b.*?\\fi\b", blank, t, flags=re.S)
    return t


def read_group(text, pos):
    """text[pos] == '{'. Return (content, index after the matching '}') or (None, pos) if unbalanced."""
    depth = 0
    i = pos
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[pos + 1: i], i + 1
        i += 1
    return None, pos


def clean_title(s):
    s = re.sub(r"\\label\{[^}]*\}", "", s)
    s = re.sub(r"\\texorpdfstring\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}\{([^{}]*)\}", r"\1", s)
    for _ in range(4):   # peel nested formatting commands
        s2 = re.sub(r"\\(?:%s)\*?\s*\{([^{}]*)\}" % "|".join(STRIP_CMDS), r"\1", s)
        s2 = re.sub(r"\\[a-zA-Z]+\*?\s*(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", s2)
        if s2 == s:
            break
        s = s2
    s = re.sub(r"\\(?:\\|newline|,|;|:|!|quad|qquad|ensuremath)", " ", s)
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    s = s.replace("~", " ").replace("{", "").replace("}", "").replace("\\", "")
    return re.sub(r"\s+", " ", s).strip()


def line_starts(text):
    starts = [0]
    for m in re.finditer("\n", text):
        starts.append(m.end())
    return starts


def line_of(starts, pos):
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo


def parse_outline(text, path="", figures=False, tables=False, todos=False, resolver=None, _seen=None, floats=None, equations=False, unnumbered=False):
    """resolver(name, from_path) -> (resolved_path, text) or None; enables \\input recursion. floats=True is shorthand for figures+tables."""
    if floats is not None:
        figures = tables = bool(floats)
    top = _seen is None
    masked = mask_comments(text)
    starts = line_starts(masked)
    items = []   # (pos, Entry)
    for m in SECTION_RE.finditer(masked):
        title, _ = read_group(masked, m.end() - 1)
        if title is None:
            continue
        kind = m.group(1)
        t = clean_title(title)
        if not t:
            continue
        items.append((m.start(), Entry(kind, LEVELS[kind], LEVELS[kind], t + ("" if not m.group(2) else ""), path, line_of(starts, m.start()))))
    if figures or tables:
        for fm in FLOAT_RE.finditer(masked):
            env = fm.group(1)
            is_fig = env.startswith("figure")
            if (is_fig and not figures) or (not is_fig and not tables):
                continue
            end = masked.find("\\end{" + env + "}", fm.end())
            seg_end = end if end >= 0 else len(masked)
            seg = masked[fm.end():seg_end]
            # ignore sub-floats: blank out subfigure/subtable bodies so the caption found is the outer one
            seg_main = re.sub(r"\\begin\{(subfigure|subtable)\}.*?\\end\{\1\}", lambda m: re.sub(r"[^\n]", " ", m.group(0)), seg, flags=re.S)
            cm = CAPTION_RE.search(seg_main)
            title = ""
            pos = fm.start()
            if cm:
                cap, _ = read_group(seg_main, cm.end() - 1)
                title = clean_title(cap or "")
                pos = fm.end() + cm.start()
            if not title:
                im = re.search(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", seg_main)
                lm = re.search(r"\\label\{([^}]*)\}", seg_main)
                title = (os.path.basename(im.group(1)) if im else (lm.group(1) if lm else "(no caption)"))
            kind = "figure" if is_fig else "table"
            full_caption = clean_title(cap or "") if cm else ""
            if is_fig:
                imgs = [g.strip() for g in INCLUDEGRAPHICS_RE.findall(seg_main)]
                data = dict(images=imgs, caption=full_caption, graphicspath=find_graphicspath(masked))
            else:
                data = dict(rows=parse_tabular(seg_main), caption=full_caption)
            items.append((pos, Entry(kind, 99, 99, title[:90], path, line_of(starts, pos), data)))
    if equations:
        for pos, ent in find_equations(masked, starts, path, unnumbered):
            items.append((pos, ent))
    if todos:
        for tm in TODO_RE.finditer(masked):
            body, _ = read_group(masked, tm.end() - 1)
            if body is not None:
                items.append((tm.start(), Entry("todo", 99, 99, "TODO: " + clean_title(body)[:60], path, line_of(starts, tm.start()))))
    items.sort(key=lambda x: x[0])
    entries = [e for _, e in items]
    if resolver:
        seen = set(_seen or ())
        seen.add(path)
        merged = []
        # splice the outline of \input files at the position of the \input command
        inputs = [(m.start(), m.group(1).strip()) for m in INPUT_RE.finditer(masked)]
        pos_list = [p for p, _ in items]
        for p, name in inputs:
            got = resolver(name, path)
            if not got or got[0] in seen:
                continue
            sub = parse_outline(got[1], got[0], figures, tables, todos, resolver, seen, None, equations, unnumbered)
            merged.append((p, sub))
        if merged:
            result, mi = [], 0
            merged.sort(key=lambda x: x[0])
            for (p, e) in items:
                while mi < len(merged) and merged[mi][0] < p:
                    result.extend(merged[mi][1]); mi += 1
                result.append(e)
            while mi < len(merged):
                result.extend(merged[mi][1]); mi += 1
            entries = result
    if top:   # number figures, tables and equations in document order, across \\input files
        nf = nt = ne = 0
        out = []
        for e in entries:
            if e.kind == "equation":
                d = dict(e.data or {})
                n = d.get("count", 0)
                if d.get("tag"):
                    label = "(%s)" % d["tag"]
                elif n:
                    label = "%d" % (ne + 1) if n == 1 else "%d\u2013%d" % (ne + 1, ne + n)
                    ne += n
                else:
                    label = "unnumbered"
                d["number"] = label
                out.append(e._replace(title="Eq. %s: %s" % (label, e.title), data=d))
                continue
            if e.kind == "figure":
                nf += 1; e = e._replace(title="Fig. %d: %s" % (nf, e.title))
            elif e.kind == "table":
                nt += 1; e = e._replace(title="Table %d: %s" % (nt, e.title))
            out.append(e)
        entries = out
    return entries


GRAPHICSPATH_RE = re.compile(r"\\graphicspath\s*\{((?:\s*\{[^{}]*\}\s*)+)\}")
INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics\*?\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
TABULAR_RE = re.compile(r"\\begin\{(tabularx|tabular\*|tabular|longtable|tabulary|longtabu)\}")
RULE_CMDS = re.compile(r"\\(?:hline|toprule|midrule|bottomrule|endhead|endfirsthead|endfoot|endlastfoot|noalign\{[^}]*\}|cline\{[^}]*\}|cmidrule(?:\([^)]*\))?\{[^}]*\}|rowcolor(?:\[[^\]]*\])?\{[^}]*\}|cellcolor(?:\[[^\]]*\])?\{[^}]*\}|arraybackslash|centering|small|footnotesize|scriptsize|tiny|bfseries|itshape)\b")


def find_graphicspath(masked):
    m = GRAPHICSPATH_RE.search(masked)
    return re.findall(r"\{([^{}]*)\}", m.group(1)) if m else []


def split_top(s, sep):
    """Split on `sep` ('&' or '\\\\') outside braces, ignoring an escaped \\&."""
    parts, depth, cur, i = [], 0, [], 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            if sep == "\\\\" and s.startswith("\\\\", i) and depth == 0:
                parts.append("".join(cur)); cur = []
                i += 2
                m = re.match(r"\s*\[[^\]]*\]", s[i:])
                if m: i += m.end()
                continue
            cur.append(s[i:i + 2]); i += 2
            continue
        if c == "{": depth += 1
        elif c == "}": depth -= 1
        if sep == "&" and c == "&" and depth == 0:
            parts.append("".join(cur)); cur = []; i += 1
            continue
        cur.append(c); i += 1
    parts.append("".join(cur))
    return parts


def parse_tabular(seg):
    """First tabular-like environment inside a float -> list of rows of cleaned cell strings (or [])."""
    m = TABULAR_RE.search(seg)
    if not m:
        return []
    env = m.group(1)
    end = seg.find("\\end{" + env + "}", m.end())
    body_start = m.end()
    ngroups = 2 if env in ("tabularx", "tabular*", "tabulary") else 1
    pos = body_start
    for _ in range(ngroups):
        while pos < len(seg) and seg[pos] in " \n\t":
            pos += 1
        if pos < len(seg) and seg[pos] == "[":
            pos = seg.find("]", pos) + 1
            while pos < len(seg) and seg[pos] in " \n\t": pos += 1
        if pos < len(seg) and seg[pos] == "{":
            _, pos = read_group(seg, pos)
    body = seg[pos: end if end >= 0 else len(seg)]
    body = re.sub(r"\\(?:makecell|thead|shortstack)(?:\[[^\]]*\])?\{((?:[^{}]|\{[^{}]*\})*)\}", lambda mm: mm.group(1).replace("\\\\", " "), body)
    body = RULE_CMDS.sub("", body)
    rows = []
    for r in split_top(body, "\\\\"):
        if not r.strip():
            continue
        cells = []
        for c in split_top(r, "&"):
            mc = re.match(r"\s*\\multicolumn\s*\{(\d+)\}\s*\{[^{}]*\}\s*\{(.*)\}\s*$", c, flags=re.S)
            if mc:
                cells.append(clean_title(mc.group(2)))
                cells.extend([""] * (int(mc.group(1)) - 1))
            else:
                cells.append(clean_title(c))
        if any(cells):
            rows.append(cells)
    return rows


MATH_ENVS = ("equation", "align", "alignat", "gather", "multline", "flalign", "eqnarray", "displaymath", "math", "split", "cases")
DROP_ENVS = ("figure", "table", "thebibliography", "tabular", "tabularx", "longtable", "tikzpicture", "lstlisting", "minted", "verbatim", "comment")
DROP_CMDS_ARG = ("cite", "citep", "citet", "citealp", "citeauthor", "nocite", "ref", "eqref", "autoref", "cref", "Cref", "pageref", "label", "url", "href",
                 "includegraphics", "input", "include", "bibliography", "bibliographystyle", "usepackage", "documentclass", "graphicspath", "hypersetup",
                 "newcommand", "renewcommand", "providecommand", "DeclareMathOperator", "setlength", "vspace", "hspace", "footnotemark", "texorpdfstring")


def count_words(text, exclude_abstract=False):
    """Words in the running text, the way journals count a main-text limit: math, figures/tables (incl. captions), bibliography,
    citations, references and the preamble are left out; section titles and footnotes are counted."""
    t = mask_comments(text)
    m = re.search(r"\\begin\{document\}", t)
    if m:
        t = t[m.end():]
    e = re.search(r"\\end\{document\}", t)
    if e:
        t = t[: e.start()]
    for env in DROP_ENVS + MATH_ENVS + (("abstract",) if exclude_abstract else ()):
        t = re.sub(r"\\begin\{%s\*?\}.*?\\end\{%s\*?\}" % (env, env), " ", t, flags=re.S)
    t = re.sub(r"\\\[.*?\\\]", " ", t, flags=re.S)
    t = re.sub(r"\$\$.*?\$\$", " ", t, flags=re.S)
    t = re.sub(r"(?<!\\)\$.*?(?<!\\)\$", " ", t, flags=re.S)
    t = re.sub(r"\\(?:%s)\*?\s*(?:\[[^\]]*\])?\s*(?:\{[^{}]*\})+" % "|".join(DROP_CMDS_ARG), " ", t)
    t = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}", " ", t)
    t = re.sub(r"\\[a-zA-Z]+\*?", " ", t)          # remaining commands: keep their text arguments
    t = re.sub(r"\\.", " ", t)                       # escaped symbols and spacing commands
    words = re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", t)
    return len(words)   # numbers count as words, as in a word processor and in texcount


def document_stats(text, exclude_abstract=False):
    e = parse_outline(text, "", figures=True, tables=True, equations=True)
    count = lambda k: sum(1 for x in e if x.kind == k)
    return dict(words=count_words(text, exclude_abstract), sections=count("section"), subsections=count("subsection"),
                figures=count("figure"), tables=count("table"), equations=sum((x.data or {}).get("count", 0) for x in e if x.kind == "equation"))


EQ_ENV_RE = re.compile(r"\\begin\{(equation|align|alignat|gather|multline|eqnarray|flalign|displaymath)(\*?)\}")
ROW_ENVS = ("align", "alignat", "gather", "eqnarray", "flalign")


def equation_snippet(body):
    s = re.sub(r"\\(?:label|tag)\*?\s*\{[^{}]*\}", " ", body)
    s = re.sub(r"\\(?:nonumber|notag)\b", " ", s)
    s = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}(?:\{[^{}]*\})?", " ", s)
    first = [r for r in split_top(s, "\\\\") if r.strip()]
    one = first[0] if first else s
    one = re.sub(r"(?<!\\)&", " ", one)
    one = re.sub(r"\s+", " ", one).strip()
    more = len(first) > 1
    one = one[:70] + ("\u2026" if len(one) > 70 else "")
    return one + (" \u2026" if more else "") if one else "(empty)"


def equation_entry(kind_env, starred, body, pos, starts, path, unnumbered, display_only=False):
    label = re.search(r"\\label\s*\{([^{}]*)\}", body)
    tag = re.search(r"\\tag\*?\s*\{([^{}]*)\}", body)
    rows = [r for r in split_top(body, "\\\\") if r.strip()]
    if display_only or starred:
        count = 0
    elif kind_env in ROW_ENVS:
        count = sum(1 for r in rows if not re.search(r"\\(?:nonumber|notag|tag)\b", r))
    else:
        count = 0 if re.search(r"\\(?:nonumber|notag)\b", body) else 1
    if tag and not display_only:
        count = 0
    if count == 0 and not tag and not unnumbered:
        return None
    src = re.sub(r"[ \t]+", " ", body.strip())
    data = dict(count=count, tag=tag.group(1) if tag else None, label=label.group(1) if label else None, source=src, env=kind_env + ("*" if starred else ""))
    return Entry("equation", 99, 99, equation_snippet(body), path, line_of(starts, pos), data)


def find_equations(masked, starts, path, unnumbered=False):
    """(position, Entry) for numbered display equations (and, with unnumbered=True, unnumbered ones: starred environments, \\[ \\], $$ $$)."""
    out = []
    for m in EQ_ENV_RE.finditer(masked):
        env, star = m.group(1), m.group(2)
        end = masked.find("\\end{%s%s}" % (env, star), m.end())
        if end < 0:
            continue
        body = masked[m.end(): end]
        if env in ("alignat", "flalign") or env == "alignat":
            body = re.sub(r"^\s*\{\d+\}", "", body)
        ent = equation_entry(env, bool(star) or env == "displaymath", body, m.start(), starts, path, unnumbered)
        if ent is not None:
            out.append((m.start(), ent))
    if unnumbered:
        for m in re.finditer(r"\\\[(.*?)\\\]", masked, flags=re.S):
            ent = equation_entry("\\[", True, m.group(1), m.start(), starts, path, True, True)
            if ent is not None:
                out.append((m.start(), ent))
        for m in re.finditer(r"\$\$(.*?)\$\$", masked, flags=re.S):
            ent = equation_entry("$$", True, m.group(1), m.start(), starts, path, True, True)
            if ent is not None:
                out.append((m.start(), ent))
    return out


MACRO_RE = re.compile(r"\\(newcommand|renewcommand|providecommand|DeclareRobustCommand|DeclareMathOperator|def|let)(\*?)\s*")
PKG_WHITELIST = ("amsmath", "amssymb", "amsfonts", "amsthm", "mathtools", "bm", "braket", "physics", "siunitx", "upgreek", "mathrsfs", "dsfont", "nicefrac",
                 "cancel", "xcolor", "mathdots", "stmaryrd", "yhmath", "txfonts", "newtxmath", "mathrsfs", "bbm", "isomath", "empheq", "cases", "esint")


def extract_macros(text):
    """Macro definitions of the document (name -> (kind, full definition text)), \\newcommand / \\renewcommand / \\providecommand /
    \\DeclareMathOperator / \\def; used to typeset equations that rely on the author's own macros."""
    masked = mask_comments(text)
    out = {}
    for m in MACRO_RE.finditer(masked):
        kind = m.group(1)
        pos = m.end()
        name = None
        if kind == "def" or kind == "let":
            nm = re.match(r"\\([a-zA-Z@]+)", masked[pos:])
            if not nm:
                continue
            name = nm.group(1)
            q = pos + nm.end()
            if kind == "let":
                continue   # \let is rarely math-relevant and often points at package internals
            j = masked.find("{", q)
            if j < 0 or "\n\n" in masked[q:j]:
                continue
            _, end = read_group(masked, j)
            if end == j:
                continue
        else:
            if pos < len(masked) and masked[pos] == "{":
                g, q = read_group(masked, pos)
                nm = re.match(r"\s*\\([a-zA-Z@]+)\s*$", g or "")
                if not nm:
                    continue
                name = nm.group(1)
            else:
                nm = re.match(r"\\([a-zA-Z@]+)", masked[pos:])
                if not nm:
                    continue
                name = nm.group(1)
                q = pos + nm.end()
            ngroups = 1   # the name is already consumed; one body group follows (after optional [n] and [default])
            end = q
            for _ in range(ngroups):
                while end < len(masked) and masked[end] in " \n\t":
                    end += 1
                while masked.startswith("[", end):          # [nargs] and [default]
                    end = masked.find("]", end) + 1
                if end <= 0 or end >= len(masked) or masked[end] != "{":
                    end = -1
                    break
                _, end = read_group(masked, end)
            if end < 0:
                continue
        out[name] = (kind, masked[m.start(): end])
    return out


def extract_packages(text):
    """Math-related \\usepackage lines of the preamble (whitelist), as 'pkg' or 'opts|pkg' tuples."""
    masked = mask_comments(text)
    pre = masked.split("\\begin{document}")[0]
    out = []
    for m in re.finditer(r"\\usepackage\s*(?:\[([^\]]*)\])?\s*\{([^{}]*)\}", pre):
        for pkg in [x.strip() for x in m.group(2).split(",")]:
            if pkg in PKG_WHITELIST:
                out.append((m.group(1) or "", pkg))
    return out


def macro_closure(body, macros):
    """Names of the macros used by `body`, directly or through other macros."""
    need, todo = set(), [body]
    while todo:
        s = todo.pop()
        for name in re.findall(r"\\([a-zA-Z@]+)", s):
            if name in macros and name not in need:
                need.add(name)
                todo.append(macros[name][1])
    return need
