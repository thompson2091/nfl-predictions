"""Run app.py with a fake Streamlit that records instead of renders.

The alternative was a second copy of the app's logic that emits HTML, and a
second copy drifts: the board's column set, the tier labels and every sentence
of prose are computed in app.py from measured artefacts, so a re-implementation
would be wrong the first time any of them changed. Instead the app runs exactly
as it does under `streamlit run`, against a `streamlit` module that appends
nodes to a tree rather than sending them to a browser.

That keeps app.py the single source of truth. What the export chooses is only
*which* captured nodes to show and how they look — see render.py.

Widgets return their default, which is what a visitor would see on first load,
except where `overrides` names one by label (the market selector, for instance).
"""
from __future__ import annotations

import functools
import runpy
import sys
import types
from typing import Any

import pandas as pd


# ── The node tree ──────────────────────────────────────────────────────────
#
# Nodes are plain dicts so the whole capture can be written to JSON and
# inspected when an export looks wrong. `t` is the node type; groups carry
# `children`.


class Node(dict):
    pass


def _node(t: str, **kw) -> Node:
    n = Node(t=t)
    n.update(kw)
    return n


class Block:
    """A container. Streamlit calls these DeltaGenerators.

    Two ways to write into one, both of which app.py uses: `with block:` makes
    it the target of bare `st.*` calls, and `block.metric(...)` writes into it
    directly whatever the `with` stack says. Both are supported here because
    changing app.py to suit the exporter would defeat the point of the exporter.
    """

    def __init__(self, capture: "Capture", node: Node):
        self._capture = capture
        self._node = node

    # -- container protocol ------------------------------------------------

    def __enter__(self):
        self._capture.stack.append(self)
        return self

    def __exit__(self, *exc):
        self._capture.stack.pop()
        return False

    def _append(self, node: Node) -> Node:
        self._node["children"].append(node)
        return node

    @property
    def open(self) -> bool:
        """Every tab is "selected" during an export.

        app.py gates each tab body on `tab.open` so that a live rerun only
        computes the tab on screen. The export has no screen and no reruns — it
        publishes several panes from one pass — so it needs all five bodies to
        execute. Returning True here is what keeps the lazy-tab optimisation
        from silently emptying every pane but the first.

        A real property rather than something `__getattr__` invents, because
        that fallback returns a bound method, and a bound method is truthy —
        the export would have appeared to work while the app-side gate did
        nothing.
        """
        return True

    # -- everything app.py calls on a container ----------------------------
    #
    # Delegated to the Capture, which holds the actual implementations, with
    # `self` as the destination. `st.foo(...)` is the same call with the
    # destination taken from the `with` stack instead.

    def __getattr__(self, name: str):
        fn = getattr(self._capture, f"_el_{name}", None)
        if fn is None:
            raise AttributeError(
                f"The export's fake Streamlit has no `{name}`. app.py started "
                f"using a Streamlit feature the exporter does not know about — "
                f"add an `_el_{name}` to src/export/capture.py."
            )
        return functools.partial(fn, self)


def _group(kind: str, **kw) -> Node:
    return _node("group", kind=kind, children=[], **kw)


# ── Value coercion ─────────────────────────────────────────────────────────


def _plain(v: Any) -> Any:
    """A JSON-safe version of a cell value, keeping numbers as numbers."""
    if v is None:
        return None
    if isinstance(v, (bool, str, int)):
        return v
    if isinstance(v, float):
        return None if pd.isna(v) else v
    if hasattr(v, "item"):  # numpy scalar
        try:
            return _plain(v.item())
        except Exception:
            pass
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return str(v)


def _as_table(data: Any) -> tuple[list[str], list[list[Any]]]:
    """(column names, rows) for anything app.py hands to st.dataframe."""
    if isinstance(data, pd.DataFrame):
        frame = data
    elif hasattr(data, "to_pandas"):  # polars
        frame = data.to_pandas()
    else:
        frame = pd.DataFrame(list(data))
    cols = [str(c) for c in frame.columns]
    rows = [[_plain(v) for v in row] for row in frame.itertuples(index=False)]
    return cols, rows


# ── Column config ──────────────────────────────────────────────────────────
#
# app.py builds these with st.column_config.*Column(...). They carry the label,
# the number format and — the reason this export exists at all — the help text,
# which is where most of the app's explanation of itself lives.


def _column(kind: str):
    def make(label: str | None = None, *, help: str | None = None,
             width: str | None = None, format: str | None = None, **_ignored):
        return {"kind": kind, "label": label, "help": help,
                "width": width, "format": format}
    return make


class _ColumnConfig(types.SimpleNamespace):
    pass


column_config = _ColumnConfig(
    TextColumn=_column("text"),
    NumberColumn=_column("number"),
    Column=_column("text"),
    CheckboxColumn=_column("bool"),
    ListColumn=_column("text"),
    LinkColumn=_column("text"),
    DateColumn=_column("text"),
    ProgressColumn=_column("number"),
)


# ── The capture ────────────────────────────────────────────────────────────


class Capture:
    def __init__(self, overrides: dict[str, Any] | None = None):
        self.root = _group("root")
        self.sidebar_node = _group("sidebar")
        self.main = Block(self, self.root)
        self.sidebar = Block(self, self.sidebar_node)
        self.stack: list[Block] = [self.main]
        self.overrides = overrides or {}
        #: Every widget the app drew, with the value the export resolved for
        #: it. The renderer needs these — the board's own filters are rebuilt
        #: client-side from the same options the app offered.
        self.widgets: list[Node] = []
        self._caches: list[dict] = []

    @property
    def _here(self) -> Block:
        return self.stack[-1]

    # -- text --------------------------------------------------------------

    def _text(self, dest: Block, kind: str, body: Any, **kw) -> None:
        dest._append(_node("text", kind=kind, body="" if body is None else str(body), **kw))

    def _el_title(self, dest, body, **kw):
        self._text(dest, "title", body)

    def _el_header(self, dest, body, **kw):
        self._text(dest, "header", body)

    def _el_subheader(self, dest, body, **kw):
        self._text(dest, "subheader", body)

    def _el_caption(self, dest, body, **kw):
        self._text(dest, "caption", body)

    def _el_markdown(self, dest, body, **kw):
        self._text(dest, "markdown", body)

    def _el_write(self, dest, *args, **kw):
        for a in args:
            if isinstance(a, (str, int, float)):
                self._text(dest, "markdown", a)
            else:
                self._el_dataframe(dest, a)

    def _el_code(self, dest, body, **kw):
        self._text(dest, "code", body)

    def _el_divider(self, dest, **kw):
        dest._append(_node("divider"))

    # -- callouts ----------------------------------------------------------

    def _callout(self, dest, kind, body, icon=None, **kw):
        dest._append(_node("callout", kind=kind, body=str(body), icon=icon))

    def _el_info(self, dest, body, icon=None, **kw):
        self._callout(dest, "info", body, icon)

    def _el_success(self, dest, body, icon=None, **kw):
        self._callout(dest, "success", body, icon)

    def _el_warning(self, dest, body, icon=None, **kw):
        self._callout(dest, "warning", body, icon)

    def _el_error(self, dest, body, icon=None, **kw):
        self._callout(dest, "error", body, icon)

    def _el_exception(self, dest, body, **kw):
        self._callout(dest, "error", body, None)

    # -- metric ------------------------------------------------------------

    def _el_metric(self, dest, label, value, delta=None, help=None, **kw):
        dest._append(_node("metric", label=str(label), value=str(value),
                           delta=None if delta is None else str(delta),
                           help=help))

    # -- tables ------------------------------------------------------------

    def _el_dataframe(self, dest, data, column_config=None, hide_index=True, **kw):
        cols, rows = _as_table(data)
        cfg = column_config or {}
        spec = []
        for c in cols:
            conf = cfg.get(c) or {}
            spec.append({
                "key": c,
                "label": conf.get("label") or c,
                "type": conf.get("kind", "text"),
                "format": conf.get("format"),
                "help": conf.get("help"),
                "width": conf.get("width"),
            })
        dest._append(_node("table", columns=spec, rows=rows))

    _el_table = _el_dataframe

    # -- charts ------------------------------------------------------------

    def _el_plotly_chart(self, dest, fig, **kw):
        """Keep the data and the axis titles; drop everything Plotly-specific.

        The export draws its own SVG, so a Plotly figure is only ever a carrier
        for a few series and their labels.
        """
        d = fig.to_dict()
        layout = d.get("layout", {})

        def _axis_title(axis):
            t = layout.get(axis, {}).get("title")
            return t.get("text") if isinstance(t, dict) else t

        title = layout.get("title")
        series = []
        for tr in d.get("data", []):
            series.append({
                "name": tr.get("name"),
                "x": [_plain(v) for v in (tr.get("x") or [])],
                "y": [_plain(v) for v in (tr.get("y") or [])],
                "dash": (tr.get("line") or {}).get("dash"),
                "color": (tr.get("line") or {}).get("color"),
            })
        dest._append(_node(
            "chart",
            title=(title.get("text") if isinstance(title, dict) else title),
            x_title=_axis_title("xaxis"), y_title=_axis_title("yaxis"),
            series=series,
        ))

    _el_line_chart = _el_plotly_chart

    # -- containers --------------------------------------------------------

    def _el_container(self, dest, *, border=False, horizontal=False, **kw):
        return Block(self, dest._append(
            _group("container", border=bool(border), horizontal=bool(horizontal))))

    def _el_expander(self, dest, label, expanded=False, **kw):
        return Block(self, dest._append(
            _group("expander", label=str(label), expanded=bool(expanded))))

    def _el_columns(self, dest, spec, **kw):
        n = spec if isinstance(spec, int) else len(spec)
        weights = [1] * n if isinstance(spec, int) else [float(w) for w in spec]
        group = dest._append(_group("columns", weights=weights))
        cols = []
        for w in weights:
            child = _group("column", weight=w)
            group["children"].append(child)
            cols.append(Block(self, child))
        return cols

    def _el_tabs(self, dest, labels, **kw):
        group = dest._append(_group("tabs"))
        out = []
        for label in labels:
            child = _group("tab", label=str(label))
            group["children"].append(child)
            out.append(Block(self, child))
        return out

    def _el_empty(self, dest, **kw):
        return Block(self, dest._append(_group("container")))

    def _el_form(self, dest, *a, **kw):
        return Block(self, dest._append(_group("container")))

    def _el_spinner(self, dest, *a, **kw):
        return _Null()

    def _el_status(self, dest, *a, **kw):
        return _Null()

    # -- widgets -----------------------------------------------------------
    #
    # Resolved to a value and recorded. The recording matters as much as the
    # value: the board's Game / Search / Show-per-game controls are real
    # controls on the exported page, rebuilt from the options captured here so
    # they cannot offer a filter the app does not have.

    def _widget(self, dest, kind, label, value, options=None, help=None, **extra):
        node = _node("widget", kind=kind, label=str(label), value=_plain(value),
                     options=None if options is None else [_plain(o) for o in options],
                     help=help, **extra)
        dest._append(node)
        self.widgets.append(node)
        return value

    def _el_selectbox(self, dest, label, options, index=0, help=None,
                      format_func=None, **kw):
        opts = list(options)
        value = self.overrides.get(str(label))
        if value is None or value not in opts:
            value = opts[index] if opts else None
        labels = [str(format_func(o)) if format_func else str(o) for o in opts]
        return self._widget(dest, "selectbox", label, value, opts, help,
                            option_labels=labels)

    def _el_radio(self, dest, label, options, index=0, help=None, **kw):
        return self._el_selectbox(dest, label, options, index, help, **kw)

    def _el_multiselect(self, dest, label, options, default=None, help=None, **kw):
        value = list(default or [])
        self._widget(dest, "multiselect", label, None, list(options), help)
        return value

    def _el_text_input(self, dest, label, value="", help=None, **kw):
        v = self.overrides.get(str(label), value) or ""
        return self._widget(dest, "text_input", label, v, None, help)

    def _el_checkbox(self, dest, label, value=False, help=None, disabled=False, **kw):
        v = bool(self.overrides.get(str(label), value))
        return self._widget(dest, "checkbox", label, v, None, help,
                            disabled=bool(disabled))

    def _el_toggle(self, dest, label, value=False, help=None, **kw):
        v = bool(self.overrides.get(str(label), value))
        return self._widget(dest, "toggle", label, v, None, help)

    def _el_number_input(self, dest, label, min_value=None, max_value=None,
                         value=None, help=None, **kw):
        v = self.overrides.get(str(label), value)
        v = float(v) if v is not None else (float(min_value) if min_value is not None else 0.0)
        return self._widget(dest, "number_input", label, v, None, help)

    def _el_slider(self, dest, label, min_value=None, max_value=None,
                   value=None, help=None, **kw):
        v = value if value is not None else min_value
        return self._widget(dest, "slider", label, v, None, help)

    def _el_button(self, dest, label, **kw):
        self._widget(dest, "button", label, False, None, kw.get("help"))
        return False

    _el_download_button = _el_button
    _el_form_submit_button = _el_button

    # -- no-ops ------------------------------------------------------------

    def _el_set_page_config(self, dest, **kw):
        pass

    def _el_stop(self, dest, *a, **kw):
        raise _Stop()

    def _el_rerun(self, dest, *a, **kw):
        raise _Stop()

    # -- caching -----------------------------------------------------------

    def cache_data(self, func=None, **_kw):
        """`@st.cache_data` and `@st.cache_data(show_spinner=...)`, both used.

        Memoising for real, not just passing through: the board, the
        walk-forward accuracy and the head-to-head are each read by several
        sections, and app.py leans on the cache to avoid recomputing them.
        """
        if func is None:
            return self.cache_data
        cache: dict = {}
        self._caches.append(cache)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                key = (args, tuple(sorted(kwargs.items())))
                hash(key)
            except TypeError:
                return func(*args, **kwargs)
            if key not in cache:
                cache[key] = func(*args, **kwargs)
            return cache[key]

        wrapper.clear = cache.clear
        return wrapper

    cache_resource = cache_data


class _Stop(Exception):
    """st.stop() — the app ending its own run, which is not an error."""


class _Null:
    """A context manager that swallows whatever is done to it (st.spinner)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, _name):
        return lambda *a, **kw: None


# ── The fake module ────────────────────────────────────────────────────────


def _install(capture: Capture) -> types.ModuleType:
    mod = types.ModuleType("streamlit")

    for name in dir(Capture):
        if not name.startswith("_el_"):
            continue
        el = name[4:]
        # Bare `st.foo(...)` writes wherever the `with` stack currently points.
        def make(el=el):
            fn = getattr(capture, f"_el_{el}")
            return lambda *a, **kw: fn(capture._here, *a, **kw)
        setattr(mod, el, make())

    mod.sidebar = capture.sidebar
    mod.column_config = column_config
    mod.cache_data = capture.cache_data
    mod.cache_resource = capture.cache_resource
    mod.session_state = {}
    mod.secrets = {}

    sys.modules["streamlit"] = mod
    sys.modules["streamlit.column_config"] = column_config
    return mod


def run_app(app_path: str, overrides: dict[str, Any] | None = None) -> Capture:
    """Execute app.py against the fake Streamlit and return what it drew."""
    capture = Capture(overrides)
    real = sys.modules.get("streamlit")
    _install(capture)
    try:
        runpy.run_path(app_path, run_name="__export__")
    except _Stop:
        pass
    finally:
        if real is not None:
            sys.modules["streamlit"] = real
        else:
            sys.modules.pop("streamlit", None)
        sys.modules.pop("streamlit.column_config", None)
    return capture
