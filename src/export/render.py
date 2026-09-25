"""Turn a captured node tree into one self-contained HTML page.

This is not a Streamlit look-alike. The capture gives us the app's numbers and
its prose; the layout here is chosen for a reader who arrives cold with no
sidebar, no reruns and no tooltips they know how to find — so the track record
leads as stat tiles, every explanation the app hid behind a `help=` becomes a
visible affordance, and the board's filters are rebuilt as real controls that
run in the browser.

Everything is inlined. The page makes no network requests, which is what lets it
be published by copying one file.
"""
from __future__ import annotations

import html
import json
import re
from typing import Any

# ── Board filters ──────────────────────────────────────────────────────────
#
# The app's filter widgets, mapped to the client-side behavior that reproduces
# them. Keyed by the widget's label, so a control the app renames simply stops
# appearing rather than silently filtering on the wrong thing.
#
# `Only where we differ` and `Longshot standouts` are deliberately absent: both
# threshold on constants fitted elsewhere in the pipeline (min_edge_pp, the
# longshot band) which the capture does not carry, and a filter that guesses its
# own cut-off would be a different filter wearing the app's label.
BOARD_FILTERS = {
    "Game": {"mode": "equals", "column": "Game", "all": "All games"},
    "Search player": {"mode": "contains", "column": "Player"},
    "Show per game": {"mode": "top_n", "column": "#", "all": "Everyone"},
}

# ── Combination controls ───────────────────────────────────────────────────
#
# Unlike the board's filters, these do not hide rows — they change which
# combinations exist, which means recomputing them. The page can do that: a
# slip's numbers are products of its legs', every leg is a row of the board
# table above, and every cell there carries its exact value in `data-v`
# alongside the rounded one it displays. So the export rebuilds these as real
# controls driven by the page's own board, rather than publishing a screenshot
# of a control that does nothing.
#
# Keyed by the app's label, like BOARD_FILTERS, so a renamed control stops
# appearing instead of quietly driving the wrong parameter.
COMBO_CONTROLS = {
    "Legs": "legs",
    "From each game's top": "perGame",
    "Rank by": "metric",
    "Show": "show",
}

#: Board columns the engine needs, by the label app.py gives them. `Bet edge`
#: is optional: a market that is not blended has no pre-blend column, and there
#: the published number is already the one a bet is judged on.
COMBO_INPUTS = {
    "player": "Player", "game": "Game", "odds": "Odds", "rank": "#",
    "ours": "Our estimate", "book": "Bookmaker says", "betEdge": "Bet edge",
    "read": "Our read", "tier": "Worth backing",
}

#: Streamlit's `icon=":material/x:"`, reduced to the four states a callout can
#: be in. The glyphs are drawn in CSS; this only picks the tone.
ICON_TONE = {
    "trending_up": "good", "insights": "good", "check_circle": "good",
    "warning": "warn", "error": "bad", "block": "bad",
    "info": "info", "payments": "info", "functions": "info",
}


# ── Text ───────────────────────────────────────────────────────────────────


def esc(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _unstreamlit(text: str) -> str:
    """Undo the two things app.py does purely to appease Streamlit's renderer."""
    # Dollar signs are escaped in the app because a matched pair reads as LaTeX.
    text = text.replace("\\$", "$")
    # Material icon directives; the tone they carried is read separately.
    text = re.sub(r":material/[a-z_]+:\s*", "", text)
    return text


def _inline(text: str) -> str:
    """Bold, italic and code, on already-escaped text."""
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text, flags=re.S)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    return text


def md(text: str) -> str:
    """The markdown subset app.py actually writes.

    Headings, bullets, bold/italic/code, paragraphs and rules. Deliberately not
    a general markdown implementation — anything outside this set would render
    as literal text, which is visible and fixable, rather than as broken HTML.
    """
    text = _unstreamlit(str(text))
    out: list[str] = []
    bullets: list[str] = []

    def flush():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    # A blockquote is one wrapped paragraph in the source; joining its lines
    # first means the continuation's "> " does not survive into the middle of
    # the sentence, which is how it read before.
    def quote(block: str) -> str:
        body = " ".join(re.sub(r"^>\s?", "", ln).strip() for ln in block.split("\n"))
        return f"<blockquote>{_inline(esc(body))}</blockquote>"

    for block in re.split(r"\n\s*\n", text.strip()):
        block = block.strip()
        if not block:
            continue
        if re.fullmatch(r"-{3,}", block):
            flush()
            out.append("<hr>")
            continue
        if block.startswith(">"):
            flush()
            out.append(quote(block))
            continue
        lines = block.split("\n")
        # A block can mix a heading, some bullets and a paragraph.
        para: list[str] = []

        def flush_para():
            if para:
                flush()
                out.append(f"<p>{_inline(' '.join(para))}</p>")
                para.clear()

        for line in lines:
            line = line.strip()
            head = re.match(r"^(#{1,6})\s+(.*)$", line)
            bullet = re.match(r"^[-*]\s+(.*)$", line)
            if head:
                flush_para()
                flush()
                # The app's #### and ##### are section labels inside a tab, not
                # page-level headings, so they land as h3/h4.
                level = min(6, len(head.group(1)) + 1)
                out.append(f"<h{level}>{_inline(esc(head.group(2)))}</h{level}>")
            elif bullet:
                flush_para()
                bullets.append(_inline(esc(bullet.group(1))))
            else:
                flush()
                para.append(esc(line))
        flush_para()
    flush()
    return "".join(out)


def plain(text: str) -> str:
    """Escaped one-liner — for tooltips and labels, where block tags cannot go."""
    return _inline(esc(_unstreamlit(str(text))))


# ── Numbers ────────────────────────────────────────────────────────────────


def fmt_cell(value: Any, spec: str | None) -> str:
    """Apply a column_config format the way Streamlit would.

    Text cells additionally get inline markdown, which Streamlit's TextColumn
    does not: the tier legend's rules are written with emphasis in them, and
    left raw they publish as a literal `*below*`.
    """
    if value is None or value == "":
        return ""
    if spec is None:
        return plain(value)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return plain(value)
    try:
        if spec == "percent":
            return esc(f"{value * 100:.1f}%")
        if spec == "dollar":
            return esc(f"${value:,.2f}")
        if spec in ("plain", "localized"):
            return esc(f"{value:,g}")
        return esc(_unstreamlit(spec) % value)
    except (TypeError, ValueError):
        return esc(value)


# ── Components ─────────────────────────────────────────────────────────────


def help_button(text: str | None) -> str:
    """The app's `help=` tooltips, made visible.

    They carry most of the app's explanation of what a number means, and in
    Streamlit they hide behind a hover target a first-time reader never finds.
    Here they are a marked control with the text in a popover.
    """
    if not text:
        return ""
    return (f'<button class="help" type="button" aria-label="What this means">'
            f'<span class="tip" role="tooltip">{md(text)}</span></button>')


def tiles(nodes: list[dict], tid: str | None = None) -> str:
    """A strip of stat tiles, in rows that come out even.

    The column count is chosen to divide the number of tiles rather than left
    to auto-fit, because auto-fit strands the last one or two in a part-empty
    row — and this strip is the first thing on the page.
    """
    n = len(nodes)
    cols = next((c for c in (5, 4, 3) if c <= n and n % c == 0), min(n, 4))
    ident = f' id="{tid}"' if tid else ""
    return (f'<div class="tiles"{ident} style="--cols:{cols}">'
            + "".join(tile(t) for t in nodes) + "</div>")


def tile(node: dict) -> str:
    delta = (f'<div class="tile-delta">{esc(_unstreamlit(node["delta"]))}</div>'
             if node.get("delta") else "")
    return (
        '<div class="tile">'
        f'<div class="tile-label">{esc(node["label"])}{help_button(node.get("help"))}</div>'
        f'<div class="tile-value">{esc(_unstreamlit(node["value"]))}</div>'
        f'{delta}</div>'
    )


def callout(node: dict) -> str:
    tone = ICON_TONE.get((node.get("icon") or "").replace(":material/", "").strip(":"),
                         {"success": "good", "warning": "warn",
                          "error": "bad"}.get(node["kind"], "info"))
    return f'<div class="callout {tone}">{md(node["body"])}</div>'


def table(node: dict, tid: str, controls: list[dict]) -> str:
    """A sortable, filterable table.

    Streamlit ships sorting for free and the export has to earn it, but the
    trade is worth it: the board is 75 rows of a dozen numeric columns, and
    without a way to reorder it the reader can only take the app's sort on
    trust.
    """
    cols = node["columns"]

    head = []
    for c in cols:
        numeric = c["type"] in ("number", "bool")
        head.append(
            f'<th class="{"num" if numeric else ""}" data-type='
            f'"{"number" if numeric else "text"}" tabindex="0" role="button" '
            f'aria-sort="none"><span>{esc(_unstreamlit(c["label"]))}'
            f'{help_button(c.get("help"))}</span></th>'
        )

    keys = [c["label"] for c in cols]
    body = []
    for row in node["rows"]:
        cells = []
        for c, v in zip(cols, row):
            numeric = c["type"] in ("number", "bool")
            sort = "" if v is None else esc(v)
            cells.append(f'<td class="{"num" if numeric else ""}" '
                         f'data-v="{sort}">{fmt_cell(v, c["format"])}</td>')
        body.append(f"<tr>{''.join(cells)}</tr>")

    bar = _control_bar(tid, controls, keys, node["rows"], cols)
    count = (f'<p class="rowcount" data-for="{tid}"></p>' if bar else "")

    # A long table scrolls inside itself rather than pushing the page's prose
    # far below the fold; the header is sticky either way.
    tall = " tall" if len(node["rows"]) > 20 else ""
    return (
        f'{bar}'
        f'<div class="tablewrap{tall}"><table id="{tid}" class="grid">'
        f'<thead><tr>{"".join(head)}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>{count}'
    )


def _control_bar(tid: str, controls: list[dict], keys: list[str],
                 rows: list[list], cols: list[dict]) -> str:
    """Rebuild the app's filter widgets as controls that work in the browser."""
    if not controls:
        return ""
    bits = []
    for w in controls:
        spec = BOARD_FILTERS.get(w["label"])
        if not spec or spec["column"] not in keys:
            continue
        col = keys.index(spec["column"])
        common = (f'data-table="{tid}" data-col="{col}" '
                  f'data-mode="{spec["mode"]}" data-all="{esc(spec.get("all", ""))}"')
        if w["kind"] == "text_input":
            bits.append(
                f'<label class="ctl"><span>{esc(w["label"])}'
                f'{help_button(w.get("help"))}</span>'
                f'<input type="search" class="filter" {common} '
                f'placeholder="e.g. Barkley"></label>')
        else:
            opts = "".join(f'<option>{esc(_unstreamlit(o))}</option>'
                           for o in (w.get("options") or []))
            bits.append(
                f'<label class="ctl"><span>{esc(w["label"])}'
                f'{help_button(w.get("help"))}</span>'
                f'<select class="filter" {common}>{opts}</select></label>')
    if not bits:
        return ""
    return f'<div class="controls">{"".join(bits)}</div>'


def combo_controls(widgets: list[dict], spec: dict) -> str:
    """The section's own controls, rebuilt against the page's engine.

    Ranges come from the capture rather than from here, so the page can only
    offer settings the app offers.
    """
    bits = []
    for w in widgets:
        param = COMBO_CONTROLS.get(w["label"])
        if param is None:
            continue
        common = f'class="combo-input" data-param="{param}"'
        if w["kind"] == "slider":
            lo, hi = w.get("min_value"), w.get("max_value")
            step = w.get("step") or 1
            opts = "".join(
                f'<option{" selected" if v == w["value"] else ""}>{v}</option>'
                for v in range(int(lo), int(hi) + 1, int(step)))
            field = f'<select {common}>{opts}</select>'
        else:
            opts = "".join(
                f'<option value="{esc(o)}"'
                f'{" selected" if o == w["value"] else ""}>{esc(o)}</option>'
                for o in (w.get("options") or []))
            field = f'<select {common}>{opts}</select>'
        bits.append(f'<label class="ctl"><span>{esc(w["label"])}</span>'
                    f'{field}</label>')
    if not bits:
        return ""
    # The graded grid rides in a script block rather than an attribute: it is a
    # few hundred rows, and HTML-escaping every quote of it tripled the size of
    # the page for no benefit.
    record = spec.pop("record", None) or []
    blob = ""
    if record:
        spec["recordId"] = f'{spec["table"]}-record'
        blob = (f'<script type="application/json" id="{spec["recordId"]}">'
                f'{json.dumps(record, separators=(",", ":"))}</script>')
    return (f'<div class="controls combo-controls" '
            f"data-combo='{esc(json.dumps(spec))}'>{''.join(bits)}</div>{blob}")


# ── Chart ──────────────────────────────────────────────────────────────────
#
# One ordinal blue ramp rather than three categorical hues: Top-1, Top-3 and
# Top-5 are the same measurement at increasing depth — each set contains the one
# before it — so a single hue getting lighter as the net widens encodes the
# nesting that three unrelated colors would hide. Steps validated against both
# surfaces (light end 2.06:1 light, 2.63:1 dark).
RAMP = ["--ramp-1", "--ramp-2", "--ramp-3"]


def chart(node: dict, fid: str) -> str:
    series = [s for s in node["series"] if s["x"] and s["y"]]
    if not series:
        return ""

    W, H = 720, 340
    pad = {"l": 46, "r": 58, "t": 14, "b": 34}
    xs = sorted({x for s in series for x in s["x"]})
    lo_y, hi_y = 0.0, 100.0
    if max(v for s in series for v in s["y"]) > 100:
        hi_y = max(v for s in series for v in s["y"])

    def px(x):
        span = (len(xs) - 1) or 1
        return pad["l"] + (xs.index(x) / span) * (W - pad["l"] - pad["r"])

    def py(y):
        return pad["t"] + (1 - (y - lo_y) / (hi_y - lo_y)) * (H - pad["t"] - pad["b"])

    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
             f'aria-label="{esc(node.get("title") or "chart")}">']

    # Gridlines and y ticks — hairline, solid, recessive.
    for t in range(0, 101, 25):
        y = py(t)
        parts.append(f'<line class="grid" x1="{pad["l"]}" y1="{y:.1f}" '
                     f'x2="{W - pad["r"]}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{pad["l"] - 10}" y="{y + 4:.1f}" '
                     f'text-anchor="end">{t}%</text>')

    step = max(1, round(len(xs) / 9))
    for i, x in enumerate(xs):
        if i % step and i != len(xs) - 1:
            continue
        parts.append(f'<text class="tick" x="{px(x):.1f}" y="{H - pad["b"] + 20}" '
                     f'text-anchor="middle">{esc(x)}</text>')

    # Direct end-labels, but only where they do not land on top of each other.
    # Nudging collided labels apart detaches them from their lines; the legend
    # and the hover tooltip already carry identity, so a dropped label costs
    # nothing and a stacked one costs legibility.
    placed: list[float] = []
    for i, s in enumerate(series):
        var = f"var({RAMP[i % len(RAMP)]})"
        pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(s["x"], s["y"]))
        parts.append(f'<polyline class="line" points="{pts}" stroke="{var}"/>')
        ex, ey = s["x"][-1], s["y"][-1]
        cy = py(ey)
        parts.append(f'<circle class="end" cx="{px(ex):.1f}" cy="{cy:.1f}" '
                     f'r="4" fill="{var}"/>')
        if all(abs(cy - p) >= 14 for p in placed):
            placed.append(cy)
            parts.append(f'<text class="endlabel" x="{px(ex) + 10:.1f}" '
                         f'y="{cy + 4:.1f}">{esc(s["name"])}</text>')

    parts.append(f'<line class="crosshair" y1="{pad["t"]}" y2="{H - pad["b"]}" '
                 f'x1="0" x2="0" style="opacity:0"/>')
    parts.append("</svg>")

    legend = "".join(
        f'<span class="key"><i style="background:var({RAMP[i % len(RAMP)]})"></i>'
        f'{esc(s["name"])}</span>' for i, s in enumerate(series))

    data = json.dumps({
        "xs": xs, "pad": pad, "w": W, "h": H,
        "series": [{"name": s["name"], "x": s["x"], "y": s["y"]} for s in series],
    })
    axis = ""
    if node.get("x_title"):
        axis = f'<p class="axis-note">{esc(node["x_title"])} →</p>'
    return (
        f'<figure class="figure" id="{fid}" data-chart=\'{esc(data)}\'>'
        f'<figcaption>{esc(node.get("title") or "")}</figcaption>'
        f'<div class="legend">{legend}</div>'
        f'{"".join(parts)}<div class="tip chart-tip" hidden></div>{axis}</figure>'
    )


# ── Tree walk ──────────────────────────────────────────────────────────────


class Renderer:
    """Walks one pane's nodes.

    `prefix` scopes the element ids it mints. Every market and every pane gets
    its own Renderer, so without it each one restarted at 1 and the page ended
    up with several `tbl1`s — at which point a filter in one market drove the
    other market's table, since getElementById returns whichever came first.
    """

    def __init__(self, prefix: str = "t", market: str = "",
                 record: dict | None = None):
        self.prefix = prefix
        self.n = 0
        #: Which market this pane is, and how it has been graded. Both only
        #: matter to the combinations engine: one game cannot supply two legs
        #: on a single-winner market, and the strip above the table reports the
        #: measured row for whatever the controls currently say.
        self.market = market
        self.record = record or {}
        #: The table a recomputed slip draws its legs from, and the strip that
        #: describes it — both are simply the last of each drawn before it.
        self.last_table = None
        self.last_tiles = None
        self.pending_combo: list[dict] = []

    def nodes(self, children: list[dict]) -> str:
        out: list[str] = []
        pending: list[dict] = []   # widgets waiting for the table they filter
        run: list[dict] = []       # consecutive metrics, grouped into one strip

        def flush_tiles():
            if run:
                self.n += 1
                self.last_tiles = f"{self.prefix}-s{self.n}"
                out.append(tiles(run, self.last_tiles))
                run.clear()

        for node in children:
            if node["t"] == "metric":
                run.append(node)
                continue
            flush_tiles()

            if node["t"] == "widget":
                if node["label"] in BOARD_FILTERS:
                    pending.append(node)
                elif node["label"] in COMBO_CONTROLS:
                    self.pending_combo.append(node)
                continue

            if node["t"] == "table":
                self.n += 1
                tid = f"{self.prefix}-t{self.n}"
                if self.pending_combo:
                    out.append(self.combos(tid))
                out.append(table(node, tid, pending))
                self.last_table = tid
                pending = []
            elif node["t"] == "chart":
                self.n += 1
                out.append(chart(node, f"{self.prefix}-f{self.n}"))
            elif node["t"] == "callout":
                out.append(callout(node))
            elif node["t"] == "divider":
                out.append("<hr>")
            elif node["t"] == "text":
                out.append(self.text(node))
            elif node["t"] == "group":
                # Not cleared here: only a table consumes pending controls, and
                # app.py puts a callout between the filter bar and the board
                # whenever the longshot filter is on.
                out.append(self.group(node, pending))

        flush_tiles()
        return "".join(out)

    def combos(self, tid: str) -> str:
        """Controls for the combinations table about to be drawn.

        Degrades to nothing rather than to a control that does not work: with
        no board table on the page there is nothing to build legs from, and a
        select that reorders no rows is worse than no select.
        """
        widgets, self.pending_combo = self.pending_combo, []
        if not self.last_table:
            return ""
        spec = {
            "board": self.last_table,
            "table": tid,
            "strip": self.last_tiles,
            "singleWinner": self.market == "first_td",
            "columns": COMBO_INPUTS,
            "record": self.record,
        }
        return combo_controls(widgets, spec)

    def text(self, node: dict) -> str:
        kind, body = node["kind"], node["body"]
        if not str(body).strip():
            return ""
        if kind in ("title", "header"):
            return f"<h2>{plain(body)}</h2>"
        if kind == "subheader":
            return f"<h3>{plain(body)}</h3>"
        if kind == "caption":
            return f'<p class="caption">{plain(body)}</p>'
        if kind == "code":
            return f"<pre><code>{esc(body)}</code></pre>"
        return md(body)

    def group(self, node: dict, pending: list[dict]) -> str:
        kids = node["children"]
        # A container holding only widgets is a filter bar; its controls belong
        # to the table that follows, so hand them upward rather than render here.
        if node["kind"] == "container" and kids and all(k["t"] == "widget" for k in kids):
            pending.extend(k for k in kids if k["label"] in BOARD_FILTERS)
            self.pending_combo.extend(k for k in kids
                                      if k["label"] in COMBO_CONTROLS)
            return ""
        if node["kind"] == "expander":
            return (f'<details class="disclosure"><summary>'
                    f'{plain(node["label"])}</summary>'
                    f'<div class="disclosure-body">{self.nodes(kids)}</div></details>')
        if node["kind"] == "columns":
            # Columns of nothing but metrics are a stat strip that happened to
            # be built with columns instead of a horizontal container.
            flat = [g for c in kids for g in c["children"]]
            if flat and all(g["t"] == "metric" for g in flat):
                return tiles(flat)
            inner = "".join(f'<div class="col" style="flex:{c.get("weight", 1)}">'
                            f'{self.nodes(c["children"])}</div>' for c in kids)
            return f'<div class="cols">{inner}</div>'
        if node["kind"] == "container" and node.get("border"):
            return f'<div class="panel">{self.nodes(kids)}</div>'
        body = self.nodes(kids)
        return body
