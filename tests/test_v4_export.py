"""site/v4 — the Hashmark app: does every screen render, and is it v4's?

v4 is v3's bundle plus a block of duplicate declarations. That mechanism is
what keeps `render`, `v3Do`, the delegation and every screen builder shared
rather than forked — and it has a failure mode v3 does not have. If the
concatenation order flips, or a `const` collides, or a name is misspelled, the
page still parses and still renders. It renders v3, in Hashmark colors. A
blank screen announces itself; the wrong app wearing the right stylesheet does
not.

So the checks here are mostly of the form "this is a thing only v4 emits".
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def v4_js(tmp_path_factory):
    """The v4 bundle, assembled exactly as `v4.render` assembles it."""
    from src.export import site as v1
    from src.export import v4js

    js = "\n".join([v1.JS_CORE, v1.JS_SHARED, v1.JS_SLIPVIEW, v1.JS_WEEK,
                    v1.JS_COMBOS, v1.JS_SAVED, v1.JS_LADDER, v1.JS_MODEL,
                    v4js.js()])
    p = tmp_path_factory.mktemp("v4") / "app.js"
    p.write_text(js)
    return p


@pytest.fixture(scope="module")
def payload_v4():
    """v3's enriched fixture. Same payload, which is the point of v4."""
    import tests.test_v3_export as T

    return T.payload_v3.__wrapped__()


def test_the_bundle_puts_v4s_overrides_after_v3s(v4_js):
    """ORDER IS THE WHOLE MECHANISM, so it is asserted rather than assumed.

    A duplicate function declaration is last-wins, so v4's `v3Header` has to
    be instantiated after v3's. Reversed, the bundle parses, loads, and
    renders v3.
    """
    src = Path(v4_js).read_text()
    # v3's own header builder, and v4's replacement for it.
    v3_at = src.index("function v3Header() {\n  const weeks = v3Weeks();")
    v4_at = src.index("function v3Header() {\n  return V.game ?")
    assert v3_at < v4_at, "v4's overrides are concatenated before v3's"


def test_v4_declares_no_const_that_v3_already_declares():
    """A DUPLICATE `const` IS A SYNTAX ERROR AND TAKES THE WHOLE PAGE DOWN.

    The override block relies on `function` being redeclarable. `const` is
    not: one collision and the script throws before its first statement, so
    every screen is blank at once. Cheap to check, and the kind of thing a
    later phase adds by accident while reaching for a name that reads well.
    """
    import re

    from src.export import v3js, v4js

    def consts(src):
        return set(re.findall(r"^(?:const|let)\s+([A-Za-z_$][\w$]*)",
                              src, re.M))

    clash = consts(v3js.js()) & consts(v4js.OVERRIDES)
    assert not clash, f"v4 redeclares v3's const: {sorted(clash)}"


def test_the_override_block_declares_only_functions():
    """THE RULE THE FIRST RUN TAUGHT, and it is not a style preference.

    v3's bundle ENDS WITH `render()`, at module scope. v4's block is appended
    after it, so every v4 function is called once before v4's own module body
    has been evaluated. A hoisted `function` survives that; a `const` sits in
    the temporal dead zone and throws, and an uncaught throw at module scope
    abandons the rest of the script — so the page comes up blank with the
    stylesheet loaded, which is the loudest possible version of the quietest
    possible bug.

    It happened on the very first run: `ReferenceError: Cannot access
    'V4ICONS' before initialization`, from inside the boot render. Every
    table v4 needs is a function returning it instead.
    """
    import re

    from src.export import v4js

    top = re.findall(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)",
                     v4js.OVERRIDES, re.M)
    assert not top, (
        "declared at module scope in v4's override block, which runs after "
        f"v3's boot render: {top}. Make it a function.")


def test_v4_overrides_only_functions_v3_actually_declares():
    """A MISSPELLED OVERRIDE IS A FUNCTION NOBODY CALLS.

    `v3Screen` spelled `v3Screeen` would add a dead function and leave v3's
    router in place — the page renders, every tab works, and none of it is
    v4. So each name v4 means to shadow has to exist in v3.
    """
    import re

    from src.export import v3js, v4js

    v3_fns = set(re.findall(r"^function\s+([A-Za-z_$][\w$]*)",
                            v3js.js(), re.M))
    # The ones v4 redeclares on purpose. Anything else it defines is its own
    # and starts `v4`.
    shadowed = {n for n in re.findall(r"^function\s+(v3[\w$]*)",
                                      v4js.OVERRIDES, re.M)}
    assert shadowed, "v4 shadows nothing, so it is not overriding anything"
    missing = shadowed - v3_fns
    assert not missing, f"v4 shadows names v3 does not declare: {sorted(missing)}"
    assert {"v3Header", "v3Nav", "v3Screen"} <= shadowed, (
        "the three chrome builders are what v4 exists to replace")


def test_every_font_the_design_asks_for_is_on_disk():
    """A missing face falls back silently, and the fallback is not the design.

    `v4.font_faces` skips a file it cannot find so a fresh checkout renders a
    plainer page rather than no page. That is the right behavior and it is
    also why nothing would otherwise notice: Barlow Condensed missing means
    every heading comes out in Arial Narrow and the page still works.
    """
    from src.export.v4 import FONT_FACES, font_faces
    from src.export.site import FONT_DIR

    missing = [n for _, n, _ in FONT_FACES if not (FONT_DIR / n).exists()]
    assert not missing, f"not in design/fonts: {missing}"
    css = font_faces()
    for family, _, weight in FONT_FACES:
        assert f"font-family:'{family}'" in css
        assert f"font-weight:{weight}" in css
    assert css.count("@font-face") == len(FONT_FACES)


def test_the_stylesheet_is_v3s_components_under_hashmark_tokens():
    """The trade this whole version rests on, asserted both ways.

    If the component rules were ever copied instead of imported, v3's screens
    would keep rendering in v4 while slowly diverging from what v4's CSS
    describes — and nothing would fail.
    """
    from src.export import v3css, v4css

    out = v4css.css()
    assert v3css.COMPONENTS in out, "v4 no longer reuses v3's component rules"
    assert out.index(":root{") < out.index(v3css.COMPONENTS), (
        "the tokens have to precede the rules that read them")
    assert out.index(v3css.COMPONENTS) < out.index(v4css.CHROME), (
        "v4's chrome has to come last or v3's rules win")
    # The ground, the ink and the accent, which is what makes it Hashmark.
    assert "--bg:#F3F4F1" in out and "--ink:#10140F" in out
    assert "--action:#C6F24E" in out
    # And NOT v3's.
    assert "#F5F3EE" not in out.split(v3css.COMPONENTS)[0]


def test_nothing_in_v4_grades_in_green_or_red():
    """Blue and orange, from the design system, and the reason is not taste.

    About one man in twelve cannot separate v3's #1C6B42 from its #9E3624,
    and every number on this app that carries a verdict carries it in color.
    The Hashmark pair differs in lightness as well as hue.
    """
    from src.export.v4css import HASHMARK

    assert HASHMARK["good"] == "#0A4FA3"
    assert HASHMARK["bad"] == "#A2480A"
    for k in ("good", "bad", "gooddot", "baddot"):
        assert HASHMARK[k] not in ("#1C6B42", "#9E3624", "#1C7A4A", "#B3402F")


def test_the_service_worker_cache_is_not_v3s(payload_v4):
    """ONE ORIGIN, TWO SCOPES, AND `./index.html` MEANS BOTH.

    A worker's scope is the directory it is served from, so v3's `./` and
    v4's `./` are different URLs with the same relative spelling. Sharing a
    cache name would let v3's cached shell answer a v4 request.
    """
    from src.export.v4 import render

    files = render(dict(payload_v4))
    assert "picksix-v4-" in files["sw.js"]
    assert "picksix-v3-" not in files["sw.js"]


def test_render_produces_the_three_files_that_must_land_together(payload_v4):
    from src.export.v4 import render

    files = render(dict(payload_v4))
    for name in ("index.html", "manifest.webmanifest", "sw.js"):
        assert name in files and files[name]
    page = files["index.html"]
    # The shell's two deliberate differences from v3's.
    assert 'id="appbar"' in page and 'class="appbar" id="appbar"' not in page, (
        "the header element must carry no class: v4 supplies .appbar or .ghead")
    # The ELEMENT, not the string: v4 carries v3's `render`, which still
    # names `slipbarHost` in the existence check that now always fails.
    # Asserting on the bare name passed for the wrong reason and would have
    # kept passing if the host were put back.
    assert 'id="slipbarHost"' not in page, "the bet slip is gone"
    # The ground color reaches the browser chrome as well as the page.
    assert '<meta name="theme-color" content="#F3F4F1">' in page
    assert json.loads(files["manifest.webmanifest"])["theme_color"] == "#F3F4F1"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_every_v4_screen_renders(payload_v4, v4_js, tmp_path):
    """Every tab, every filter, every game section, against a stub DOM."""
    p = tmp_path / "payload.json"
    p.write_text(json.dumps(payload_v4))
    r = subprocess.run(["node", str(REPO / "tests" / "js" / "v4app.js"),
                        str(p), str(v4_js)],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    # And that the fixture actually reached the checks, rather than the
    # harness reporting "nothing to check" and exiting zero.
    for line in ("v4’s app bar replaced v3’s header",
                 "the third tab reads Starred, not Picks",
                 "storage is under v4’s own key, not v3’s",
                 "there is no slip bar",
                 "the games list exercised real cards",
                 "every game on the board is openable",
                 "games are grouped under the day the card names",
                 "the lean buckets account for every game",
                 "the away row reads the away side’s model chance",
                 "inside a game the header goes dark",
                 "every data key on screen is one the delegation handles"):
        assert f"ok    {line}" in r.stdout, (
            f"never exercised: {line}\n{r.stdout}")
