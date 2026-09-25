"""The deploy script: what it uploads, what it deletes, and what it never stores.

It replaces a hand-typed scp routine that copied three files out of four.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dep():
    spec = importlib.util.spec_from_file_location(
        "dep", REPO / "scripts/58_deploy.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeSession:
    """Records commands instead of running them."""

    def __init__(self, listing=""):
        self.listing, self.cmds = listing, []

    def run(self, cmd):
        self.cmds.append(cmd)

        class R:
            returncode = 0
            stdout = self.listing
            stderr = ""
        return R()


def test_the_data_folder_is_uploaded():
    """The routine this replaces copied index.html, the manifest and sw.js and
    stopped. Every past week on the live site then failed to load — and a
    blocked fetch used to render as "no priced picks recorded", so the site
    said the weeks were empty rather than missing."""
    src = (REPO / "scripts/58_deploy.py").read_text()
    assert 'glob("h-*.json")' in src
    assert "{root}/data/{f.name}" in src


def test_stale_week_files_are_deleted_by_name_and_never_by_pattern(dep):
    """The first version interpolated the keep-list into a remote shell `case`
    statement inside an ssh command. The quotes collided with the quotes ssh
    needs around the whole thing, so the pattern never matched what it was
    meant to — and the loop it guarded was `rm -f`, on a live web server.
    """
    s = FakeSession("h-old-1.json\nh-anytime_td-1.json\nnotes.txt\n")
    dep._prune(s, "/var/www/html", {"h-anytime_td-1.json"}, dry=False)
    removed = [c for c in s.cmds if c.startswith("rm ")]
    assert removed == ["rm -f /var/www/html/data/h-old-1.json"]
    # No shell globbing, no case statement, no loop.
    for c in s.cmds:
        assert "*" not in c and "case " not in c and "for f in" not in c


def test_a_file_that_is_not_a_week_file_is_never_a_candidate(dep):
    """Belt and braces: a bug producing an empty keep-set deletes week files
    and nothing else."""
    s = FakeSession("index.html\nsw.js\nrobots.txt\nh-x-1.json\n")
    dep._prune(s, "/var/www/html", set(), dry=False)
    removed = [c for c in s.cmds if c.startswith("rm ")]
    assert removed == ["rm -f /var/www/html/data/h-x-1.json"]


def test_a_dry_run_deletes_nothing(dep):
    s = FakeSession("h-old-1.json\n")
    dep._prune(s, "/var/www/html", {"h-new-1.json"}, dry=True)
    assert not [c for c in s.cmds if c.startswith("rm ")]


def test_no_password_is_read_or_accepted_anywhere():
    """It is the root account of a public web server. A dotfile ends up in
    shell history, in backups and in crash reports; `ssh-copy-id` does not."""
    src = (REPO / "scripts/58_deploy.py").read_text()
    # MECHANISMS, not the word. The first version of this test matched the
    # string "PASSWORD" and failed on the docstring explaining that none is
    # stored — a test that forbids describing the property it enforces.
    for bad in ("sshpass", "DEPLOY_PASS", "--password", "getpass",
                "PasswordAuthentication=yes"):
        assert bad not in src, f"{bad} has no business in a deploy script"
    # And what it DOES read from .env is host and paths, never a credential.
    block = src[src.index("DEFAULTS = {"):]
    block = block[:block.index("}")]
    for key in ("DEPLOY_HOST", "DEPLOY_USER", "DEPLOY_ROOT"):
        assert key in block
    assert "PASS" not in block.upper()


def test_the_live_page_is_promoted_last():
    """Everything the new page needs must already be on the server when it
    goes live. Promoting first would serve a page whose week files and worker
    are still uploading."""
    src = (REPO / "scripts/58_deploy.py").read_text()
    assert src.index("_prune(") < src.index("cp {root}/{archive}/{ver}.html")
    assert src.index("{root}/data/{f.name}") < src.index(
        "cp {root}/{archive}/{ver}.html")


def test_a_partial_build_is_refused_rather_than_half_uploaded():
    src = (REPO / "scripts/58_deploy.py").read_text()
    assert "refusing to deploy" in src
    for f in ("index.html", "manifest.webmanifest", "sw.js"):
        assert f in src


def test_the_archive_copy_is_versioned_so_a_rollback_is_one_command(dep):
    """Deploying twice in a day is normal, and overwriting the morning's
    archive removes the thing that makes a rollback trivial."""
    s = FakeSession("2\n")
    assert dep.next_version(s, "/var/www/html", "bets", "20260925") \
        == "20260925.v3"
    s2 = FakeSession("0\n")
    assert dep.next_version(s2, "/var/www/html", "bets", "20260925") \
        == "20260925.v1"
