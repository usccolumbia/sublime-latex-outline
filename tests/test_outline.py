import os, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from outline_parser import parse_outline, clean_title, mask_comments
from outline_model import build_rows, current_row, indent_ranks

SAMPLE = r"""
\documentclass{article}
\begin{document}
% \section{Commented out}
\section{Introduction}\label{sec:intro}
text \section*{Unnumbered} more
\subsection[short]{Long \textbf{bold} and $x^2$ title~here}
\paragraph{CDVAE.} The text.
\begin{verbatim}
\section{Inside verbatim}
\end{verbatim}
\iffalse
\section{Dead}
\fi
\section{Results}
\begin{figure}\centering\caption{A figure with \emph{emph}.}\label{f}\end{figure}
\TODO{fix this, it has {nested} braces}
\subsection{Deep}
\paragraph{P1.}
\end{document}
"""


class Parser(unittest.TestCase):
    def test_basic(self):
        e = parse_outline(SAMPLE, "a.tex")
        self.assertEqual([x.title for x in e], ["Introduction", "Unnumbered", "Long bold and $x^2$ title here", "CDVAE.", "Results", "Deep", "P1."])
        self.assertEqual([x.kind for x in e], ["section", "section", "subsection", "paragraph", "section", "subsection", "paragraph"])
        self.assertEqual(e[0].line, 4)

    def test_floats_and_todos(self):
        e = parse_outline(SAMPLE, "a.tex", figures=True, tables=True, todos=True)
        titles = [x.title for x in e]
        self.assertIn("Fig. 1: A figure with emph.", titles)
        self.assertTrue(any(t.startswith("TODO: fix this") for t in titles))

    def test_figures_tables_separate_and_numbered(self):
        src = r"""\\section{A}
\\begin{table}\\caption{T one}\\end{table}
\\begin{figure}\\begin{subfigure}\\caption{sub}\\end{subfigure}\\caption{Main fig}\\label{f}\\end{figure}
\\begin{figure*}\\includegraphics{figs/plot.pdf}\\end{figure*}
\\section{B}\\begin{table*}\\caption[short]{T two}\\end{table*}"""
        figs = [x.title for x in parse_outline(src, "a", figures=True)]
        self.assertEqual(figs, ["A", "Fig. 1: Main fig", "Fig. 2: plot.pdf", "B"])
        tabs = [x.title for x in parse_outline(src, "a", tables=True)]
        self.assertEqual(tabs, ["A", "Table 1: T one", "B", "Table 2: T two"])

    def test_clean_title(self):
        self.assertEqual(clean_title(r"\texorpdfstring{Co$_3$}{Co3} \textit{x}\label{a}"), "Co3 x")

    def test_comment_mask_keeps_offsets(self):
        t = "a % \\section{x}\nb"
        self.assertEqual(len(mask_comments(t)), len(t))

    def test_input_recursion(self):
        files = {"b.tex": r"\section{From B}", "c.tex": r"\input{a}"}
        def res(name, frm):
            n = name if name.endswith(".tex") else name + ".tex"
            return (n, files[n]) if n in files else None
        root = r"\section{One}\input{b}\section{Two}\input{c}"
        e = parse_outline(root, "a.tex", resolver=res)
        self.assertEqual([x.title for x in e], ["One", "From B", "Two"])   # c.tex -> a.tex is a cycle and is skipped


class Equations(unittest.TestCase):
    SRC = r"""\section{A}
\begin{equation}\label{eq:one} E = mc^2 \end{equation}
\begin{align} a &= b \\ c &= d \nonumber \\ e &= f \label{x}\end{align}
\begin{equation*} unnum \end{equation*}
\[ x^2 \]
\begin{equation} y = 1 \tag{A1}\end{equation}
\begin{gather} p \\ q \end{gather}
"""

    def test_numbering(self):
        e = [x for x in parse_outline(self.SRC, "a.tex", equations=True) if x.kind == "equation"]
        self.assertEqual([x.title for x in e], ["Eq. 1: E = mc^2", "Eq. 2–3: a = b …", "Eq. (A1): y = 1", "Eq. 4–5: p …"])
        self.assertEqual(e[0].data["label"], "eq:one")
        self.assertEqual(e[1].data["count"], 2)

    def test_unnumbered_optional(self):
        e = [x.title for x in parse_outline(self.SRC, "a.tex", equations=True, unnumbered=True) if x.kind == "equation"]
        self.assertIn("Eq. unnumbered: unnum", e)
        self.assertIn("Eq. unnumbered: x^2", e)
        self.assertEqual(len(e), 6)

    def test_stats_and_popup(self):
        from outline_parser import document_stats
        from preview_model import popup_html
        self.assertEqual(document_stats(self.SRC)["equations"], 5)
        e = next(x for x in parse_outline(self.SRC, "a.tex", equations=True) if x.kind == "equation")
        h = popup_html(e)
        self.assertIn("eq:one", h)
        self.assertIn("E = mc^2", h)

    def test_hidden_by_default(self):
        self.assertFalse(any(x.kind == "equation" for x in parse_outline(self.SRC, "a.tex")))


class Stats(unittest.TestCase):
    def test_word_count(self):
        from outline_parser import count_words, document_stats
        src = r"""\documentclass{article}\usepackage{amsmath}
\begin{document}
\section{Intro words}
One two three. % comment words here
\begin{equation} a + b = c \end{equation} Inline $x^2 + y$ math and \textbf{bold text} plus \cite{key} and Fig.~\ref{f}.
\begin{figure}\includegraphics{a}\caption{Caption words not counted}\end{figure}
\begin{table}\begin{tabular}{ll}a & b\\\end{tabular}\caption{Skip}\end{table}
\subsection{Sub}
Don't count-twice, 3 numbers 42.
\end{document}"""
        # 2 (title) + 3 + 'Inline math and' 3 + 'bold text plus and Fig' 5 + 'Sub' 1 + "Don't count-twice" 2 + 'numbers' 1 = 17; numbers count as words (+2: 3 and 42); math, floats and comments are not counted
        self.assertEqual(count_words(src), 19)
        s = document_stats(src)
        self.assertEqual((s["sections"], s["subsections"], s["figures"], s["tables"]), (1, 1, 1, 1))


class Preview(unittest.TestCase):
    def test_table_and_figure_data(self):
        src = r"""\graphicspath{{figs/}}
\section{A}
\begin{table}\caption{Res}\begin{tabular}{lrr}\toprule Method & \makecell{Top-1\\(\%)} & Top-5 \\ \midrule TCSPv3 & 122 & 154 \\ \multicolumn{2}{c}{Mean} & 1 \\ \bottomrule\end{tabular}\end{table}
\begin{figure}\includegraphics[width=3cm]{plot}\caption{Panels}\end{figure}"""
        e = parse_outline(src, "a.tex", figures=True, tables=True)
        tab = next(x for x in e if x.kind == "table").data
        self.assertEqual(tab["rows"], [["Method", "Top-1 (%)", "Top-5"], ["TCSPv3", "122", "154"], ["Mean", "", "1"]])
        fig = next(x for x in e if x.kind == "figure").data
        self.assertEqual((fig["images"], fig["graphicspath"]), (["plot"], ["figs/"]))

    def test_helpers(self):
        from preview_model import resolve_image, table_text, popup_html
        files = {"/d/figs/plot.png", "/d/other.pdf"}
        isf = lambda p: p in files
        self.assertEqual(resolve_image("plot", "/d", ["figs/"], isf), "/d/figs/plot.png")
        self.assertEqual(resolve_image("other.pdf", "/d", [], isf), "/d/other.pdf")
        self.assertIsNone(resolve_image("missing", "/d", ["figs/"], isf))
        txt = table_text([["a", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "c"]] * 20, width=30)
        self.assertIn("more rows", txt)
        self.assertIn("…", txt)
        e = parse_outline(r"\begin{table}\caption{X}\begin{tabular}{l}a\\\end{tabular}\end{table}", "a", tables=True)[0]
        self.assertIn("<b>Table 1</b>", popup_html(e))


class Model(unittest.TestCase):
    def test_rows_collapse_and_current(self):
        e = parse_outline(SAMPLE, "a.tex")
        rows = build_rows(e)
        self.assertEqual(indent_ranks(e), [0, 0, 1, 2, 0, 1, 2])
        self.assertTrue(rows[0].has_children is False and rows[1].has_children)
        rows2 = build_rows(e, collapsed={("a.tex", e[1].line)})   # collapse "Unnumbered"
        self.assertEqual(len(rows2), len(rows) - 2)
        self.assertEqual(current_row(rows, "a.tex", 14), 4)       # line 14 is under "Results"


REAL = Path(os.environ.get("LATEX_OUTLINE_SAMPLE", Path(__file__).resolve().parent / "sample.tex"))


@unittest.skipUnless(REAL.exists(), "sample document not available")
class Real(unittest.TestCase):
    def test_sample_document(self):
        text = REAL.read_text()
        e = parse_outline(text, str(REAL), figures=True, tables=True, todos=True)
        titles = [x.title for x in e]
        self.assertEqual([x.title for x in e if x.kind == "section"], ["Introduction", "Methods", "Results", "Discussion"])
        self.assertIn("Fig. 1: A figure with a caption.", titles)
        self.assertTrue(any(t.startswith("Table 1: Match rates") for t in titles))
        self.assertTrue(any(x.kind == "todo" for x in e))
        self.assertNotIn("A commented-out section", titles)
        rows = build_rows(e)
        self.assertGreater(len(rows), 10)


if __name__ == "__main__":
    unittest.main()
