"""`deploy/ask.php` — the endpoint, read as source because there is no PHP here.

The host runs PHP 5.5.9 and this machine has no PHP at all, so the file is
linted on the server before it ships (`php -l` over ssh) and its PROPERTIES
are asserted here. The properties are the point: this is a public endpoint in
front of a paid API key, and it now runs a tool loop, so the two things that
could go wrong are a reader reaching a file and a question costing more than
it should.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = (REPO / "deploy" / "ask.php").read_text()


def test_the_key_is_read_from_outside_the_web_root_and_never_echoed():
    assert "/etc/picksix/anthropic.key" in SRC
    # The key goes into one header and nowhere else.
    assert SRC.count("$key") <= 6, "the key is referenced more than expected"
    for leak in ("echo $key", "print $key", "error_log($key",
                 "'key' => $key", '"key" => $key'):
        assert leak not in SRC


def test_the_game_id_is_validated_by_shape_before_it_builds_a_path():
    """A traversal has to be impossible rather than caught."""
    i = SRC.index("preg_match('/^[A-Z]{2,4}_[A-Z]{2,4}$/', $game)")
    j = SRC.index("$ctx_file = $CTX_DIR")
    assert i < j, "the id is used in a path before it is validated"


def test_nothing_a_reader_sends_is_interpolated_into_a_path():
    """The ONE property that keeps this from being a file server.

    Every path is `$CTX_DIR` plus a literal from `$SLICE_FILES` plus either
    the validated `$game` or a `$team` checked by identity against the two
    teams this game's own core names.
    """
    # THE CONTEXT DIRECTORY, specifically. `bump()` also builds a path —
    # under `$STATE_DIR`, from a caller-supplied literal — and a check wide
    # enough to catch that one is a check that gets relaxed.
    ctx = re.findall(r"\$CTX_DIR\s*\.\s*'([^']*)'\s*\.\s*\$(\w+)", SRC)
    assert ctx, "no context path found; has the file been rewritten?"
    for _literal, var in ctx:
        assert var == "game", (
            f"${var} is interpolated into a context path; only the "
            f"shape-validated game id may be")

    # And inside `slice_body`, where the model's own argument arrives.
    body = SRC[SRC.index("function slice_body("):SRC.index("function api_call(")]
    joins = re.findall(r"\$dir\s*\.\s*'([^']*)'\s*\.\s*\$(\w+)", body)
    assert joins, "slice_body no longer builds a path"
    for _literal, var in joins:
        assert var == "path", f"${var} reaches a path unchecked"
    # `$path` only ever comes from the literal map, and the only two things
    # substituted into it are the validated id and the checked team.
    assert "$path = $files[$name];" in body
    subs = set(re.findall(r"str_replace\('(\{\w+\})'", body))
    assert subs == {"{gid}", "{team}"}, subs

    # And the reader's question never touches a path anywhere in the file.
    for m in re.finditer(r"^[^\n]*\$(?:CTX_DIR|dir)[^\n]*$", SRC, re.M):
        assert "$q" not in m.group(0), m.group(0)


def test_the_rate_limiters_filename_is_hashed_not_the_address():
    """`bump()` builds a path from its `$name`, and one caller passes the
    reader's IP. Hashed, so a header that is not an address cannot be one."""
    assert "'ip-' . md5($ip) . '.json'" in SRC
    assert "'ip-' . $ip" not in SRC


def test_the_slice_name_is_an_enum_resolved_against_a_literal_map():
    """The model picks a NAME, not a file. An unknown name is a sentence back
    to the model rather than a read that fails."""
    assert "$SLICE_FILES = array(" in SRC
    block = SRC[SRC.index("$SLICE_FILES = array("):]
    block = block[:block.index(");")]
    names = set(re.findall(r"'(\w+)'\s*=>", block))
    from src.export.askctx import SLICES

    assert names == set(SLICES), (
        f"the proxy serves {sorted(names)} and askctx builds {sorted(SLICES)}")
    # The tool's enum is generated from the same map, so the two cannot drift.
    assert "'enum' => array_keys($SLICE_FILES)" in SRC
    assert "There is no slice called" in SRC, (
        "an unknown name must come back as an explanation")


def test_the_team_argument_is_checked_against_this_games_own_teams():
    """`team` is the only slice argument a reader can influence through the
    model, so it is checked by identity rather than by shape."""
    assert "in_array($team, $teams, true)" in SRC
    # And `$teams` comes from the core file, not from the game id's spelling.
    i = SRC.index("$core_json = json_decode($ctx, true);")
    j = SRC.index("function slice_body(")
    assert i < j
    assert "$core_json[$k]" in SRC


def test_the_loop_has_a_round_cap_a_byte_cap_and_a_deadline():
    """Three budgets, because they fail differently.

    Rounds stop a model that keeps asking. Bytes stop one question pulling
    the whole site. The DEADLINE is the one that actually binds: the page
    gives up at 60 seconds and four calls at the 45-second per-call timeout
    is three minutes against a reader who left after one.
    """
    for name in ("$MAX_ROUNDS", "$SLICE_BYTES", "$DEADLINE"):
        assert name in SRC, name
    assert "(time() - $started) > $DEADLINE" in SRC
    assert "$slice_got >= $SLICE_BYTES" in SRC
    # The page's own ceiling, so the two are read together.
    js = (REPO / "src" / "export" / "v3js.py").read_text()
    assert "60000)" in js, "the page's ask timeout moved; re-read $DEADLINE"
    dl = int(re.search(r"\$DEADLINE\s*=\s*(\d+)", SRC).group(1))
    assert dl < 60, f"the deadline ({dl}s) is past the page's 60s give-up"


def test_the_tool_is_taken_away_on_the_last_round_rather_than_the_loop_stopping():
    """A model mid-way through gathering, handed no tools and no instruction
    to stop, has the budget run out underneath it and returns nothing."""
    assert "$tools = $last ? array($web_search)" in SRC
    assert "array($get_data, $web_search)" in SRC
    i = SRC.index("$last = ($round === $MAX_ROUNDS)")
    j = SRC.index("$tools = $last ?")
    assert i < j


def test_only_this_rounds_text_is_returned():
    """A turn that ends in a tool call may carry a line of preamble, and
    concatenating those across rounds reads as the model narrating its own
    plumbing to a reader who asked about a spread."""
    assert "$text = '';\n    $wants = array();" in SRC, (
        "the text has to be reset each round")


def test_the_assistant_turn_goes_back_verbatim():
    """The API requires the tool_use blocks it sent, with their ids. A
    reconstructed copy is a different message and the call is rejected."""
    assert "'content' => $out['content']" in SRC


def test_the_system_block_is_cached_because_the_loop_resends_it():
    assert "'cache_control' => array('type' => 'ephemeral')" in SRC
    # As a block list, which is what carries cache_control.
    assert "'system' => array(array(" in SRC


def test_the_model_is_told_to_fetch_before_it_says_it_cannot_answer():
    """THE OLD FAILURE WORE THE FACE OF HONESTY. Handed a thin summary, the
    model reported that the data did not include a number that was printed on
    the screen the reader was looking at."""
    assert "FETCH WHAT YOU NEED BEFORE YOU ANSWER" in SRC
    assert "do not tell the reader data is unavailable" in SRC
    assert "you_can_fetch" in SRC


def test_the_vocabulary_matches_the_screen():
    """A reader who has just read Model / Book / Adjusted off the card is
    owed the same three words back, and the gap between a positive edge and
    a losing bet is the thing here most often misread."""
    for word in ("Model is our number", "Book is the price",
                 "Adjusted is the two blended",
                 "a small positive edge can still"):
        assert word in SRC, word


def test_the_model_is_current():
    """Pinned rather than aliased, so an upgrade is a commit."""
    m = re.search(r"\$MODEL\s*=\s*'([^']+)'", SRC)
    assert m, "no model pinned"
    assert m.group(1) == "claude-opus-5", m.group(1)


def test_the_upstream_body_is_never_returned_to_the_caller():
    """It can echo request details, and this endpoint is public."""
    assert "fail(502, 'the model returned ' . $code)" in SRC
    assert "fail(502, $resp" not in SRC and "echo $resp" not in SRC


def test_the_rate_caps_still_run_before_the_key_is_read():
    i_day = SRC.index("$PER_DAY)")
    i_key = SRC.index("$KEY_FILE)")
    assert i_day < i_key, "a refused question must not read the key"


def test_the_answer_says_which_slices_it_looked_at():
    """An answer that reads thin is either a thin question or a slice that was
    never fetched, and from the outside those are indistinguishable."""
    assert "'used' => array_keys($fetched)" in SRC


def test_php_55_only():
    """The host is PHP 5.5.9. Three constructs that parse everywhere else and
    are a syntax error there, so the file never loads and every question 500s.
    """
    body = re.sub(r"/\*(?:.|\n)*?\*/", "", SRC)
    body = re.sub(r"^\s*//.*$", "", body, flags=re.M)
    for bad, why in ((r"\?\?", "null coalescing is PHP 7"),
                     (r"=>\s*\w+\s*=>", "nested arrow is not PHP"),
                     (r"\bfn\s*\(", "arrow functions are PHP 7.4"),
                     (r"function\s+\w+\s*\([^)]*\b(?:int|string|bool|float)\s+\$",
                      "scalar type hints are PHP 7")):
        assert not re.search(bad, body), why
