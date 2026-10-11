# sublime-latex-outline

An Overleaf-style **File outline** side panel for LaTeX in Sublime Text 3/4, with figure and table previews and document totals. It is a standalone package: it works with or without [LaTeXTools](https://github.com/SublimeText/LaTeXTools) (MIT), which has a quick-panel table of contents but no persistent outline.

## Features

- **Outline tree** of `\part`, `\chapter`, `\section`, `\subsection`, `\subsubsection`, `\paragraph` and `\subparagraph` in a narrow left pane. Comments, verbatim blocks and `\iffalse` text are ignored; titles are cleaned (`\textbf`, `\label`, `\texorpdfstring`, `~`).
- **Navigation:** click an entry or press Enter to jump to it; click the `⌄`/`›` chevron or press Space to fold or unfold a branch. The entry of the section you are editing is highlighted, and the outline refreshes as you type and when you switch `.tex` tabs.
- **Figures and tables** are listed under their section, numbered in document order (`Fig. 1: caption`, `Table 2: caption`; `figure*`/`table*` included, sub-figures ignored; no caption falls back to the image file name or label) on a light milk-brown background.
- **Hover preview:** point at a figure row for its caption and an image thumbnail (PNG/JPG, and PDF/EPS rendered with macOS `sips`; up to three images per figure, found relative to the file and `\graphicspath`), or at a table row for its caption and a text grid of its cells (`\makecell`, `\multicolumn` and rules handled).
- **Open the full image:** press `Cmd+Alt+P` (`Ctrl+Alt+P` elsewhere; P for picture) to open the figure you last hovered or clicked (else the figure the cursor is in) in the system viewer, or click **Open full image** in the popup. `o` / `Shift+Enter` do the same while the outline pane itself has focus.
- **Totals:** words, sections (and subsections), figures and tables at the bottom of the outline and in the status bar (`Words 7,137 | Sections 10 | Figures 5 | Tables 6`). Words are the main text as a journal limit counts it: section titles and footnotes included, numbers count; math, figures/tables with their captions, the bibliography, citations/references and the preamble are left out. It agrees with `texcount` to within a few percent.
- Optional: `\TODO{...}` markers, and following `\input`/`\include`/`\subfile` into other files.

## Install

Clone into your Sublime `Packages` folder (Sublime Text 4 on macOS also uses the `Sublime Text 3` folder):

```bash
cd "$HOME/Library/Application Support/Sublime Text 3/Packages"     # Linux: ~/.config/sublime-text/Packages
git clone https://github.com/usccolumbia/sublime-latex-outline.git LaTeXOutline
```

Open a `.tex` file and run **LaTeX Outline: Toggle** from the Command Palette, or press `Cmd+Alt+O` (`Ctrl+Alt+O` on Linux/Windows). Toggle again to close it; the original layout is restored.

## Keys and commands

| Key (macOS / other) | Command |
|---|---|
| `Cmd+Alt+O` / `Ctrl+Alt+O` | LaTeX Outline: Toggle |
| `Cmd+Alt+F` / `Ctrl+Alt+F` | Show/Hide Figures |
| `Cmd+Alt+T` / `Ctrl+Alt+T` | Show/Hide Tables |
| `Cmd+Alt+P` / `Ctrl+Alt+P` | Open Figure Image |
| Enter / Space (outline focused) | jump / fold |
| `o` / `Shift+Enter` (outline focused) | open figure image |

`Cmd+Alt+P` replaces Sublime's default binding to Show Scope Name while this package is installed.

## Settings (`LaTeXOutline.sublime-settings`)

`width`, `show_figures`, `show_tables`, `show_todos`, `follow_inputs`, `refresh_delay_ms`, `expanded_marker` / `collapsed_marker` (2 characters; use `"- "`/`"+ "` if your font lacks the chevrons), `float_background`, `float_foreground`, `float_current_background` (colours of figure/table rows; `float_background: ""` turns them off), `hover_preview`, `preview_max_images`, `preview_max_height`, `image_viewer`, `show_stats`, `stats_in_status_bar`, `stats_exclude_abstract`, `debug_log`.

The package writes `Packages/User/LaTeXOutline-floats.sublime-color-scheme`, which extends your current color scheme, to colour the figure and table rows.

## Status

- The parser, rendering logic and word counter are plain Python with unit tests (`python -m unittest discover -s tests`).
- Exercised inside Sublime Text 4 (build 4215, macOS): toggle on/off with the layout restored, jumping, folding, cursor-following highlight, live refresh, hover previews with PDF figures, opening images, totals, recovery from leftover panels after a plugin reload.
- Not exercised: real mouse clicks on entries (handled through Sublime's `drag_select` command) and the key bindings on a physical keyboard; Linux and Windows. Thumbnails of PDF/EPS figures need macOS `sips`; elsewhere only PNG/JPG thumbnails are shown.
- The footer totals are the last lines of the outline, not pinned; the status bar line is always visible.

## Development

Set `"debug_log": "/tmp/latex_outline.log"` to log toggles, renders and errors. `latex_outline_debug_click`, `latex_outline_debug_hover`, `latex_outline_debug_key` and `latex_outline_open_image_row` are test hooks that simulate a click, a hover, a key press and an open on outline row N.

## License

MIT, see `LICENSE`.
