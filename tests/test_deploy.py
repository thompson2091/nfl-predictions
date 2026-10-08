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
    # `web`, not `root`: v3 owns the web root and v4 sits under `/v4/`, so
    # the app's own files and its data/ go to the app's directory while the
    # rollback archive, ask.php and .htaccess stay at the root. A worker
    # scoped to `/v4/` cannot intercept a request to `/data/`, so sharing one
    # data directory would ship a page that works online and has no offline
    # week files.
    assert "{web}/data/{f.name}" in src


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
    assert src.index("{web}/data/{f.name}") < src.index(
        "cp {root}/{archive}/{ver}.html")


def test_v3_keeps_the_web_root_and_v4_gets_a_subdirectory():
    """THE ONE LINE THAT COULD OVERWRITE THE LIVE SITE.

    `--app v4` must land in `/var/www/html/v4`, not in `/var/www/html`. If the
    prefix were ever derived the other way round, a v4 deploy would replace
    v3's index.html with a page whose data/ is one directory down — a live
    site serving a shell whose every fetch 404s.
    """
    src = (REPO / "scripts/58_deploy.py").read_text()
    assert 'web = root if a.app == "v3" else f"{root}/{a.app}"' in src
    # And the three the app owns go to `web`, not to `root`.
    for frag in ('mkdir -p {root}/{archive} {web} {web}/data {web}/data/ask',
                 'f"{web}/{f}"', 'f"{web}/data/{f.name}"',
                 'f"{web}/data/ask/{f.name}"',
                 'cp {root}/{archive}/{ver}.html {web}/index.html'):
        assert frag in src, frag


def test_the_server_config_stays_at_the_root_for_both_apps():
    """`ask.php` and `.htaccess` are the SERVER's, not an app's.

    One proxy and one set of cache rules serve both. Copying them under
    `/v4/` would leave the root pair unmaintained and give the two apps
    different caching, which is exactly how one of them starts serving a
    stale page that nobody can reproduce.
    """
    src = (REPO / "scripts/58_deploy.py").read_text()
    assert 'f"{root}/ask.php"' in src
    assert 'f"{root}/.htaccess"' in src


def test_the_archive_name_carries_the_app_for_everything_but_v3(dep):
    """Both apps archive into one `bets/`, so the name has to separate them.

    Shared, v4's build would count v3's copies, pick the same `vN` and
    overwrite one — and a rollback would restore whichever app happened to
    win. v3 keeps the bare name so every build already on the server stays
    addressable and the rollback line in anyone's notes still works.
    """
    class S:
        def run(self, cmd):
            class R:
                returncode = 0
                stdout = "0"
                stderr = ""
            return R()

    s = S()
    assert dep.next_version(s, "/r", "bets", "20261008") == "20261008.v1"
    assert dep.next_version(s, "/r", "bets", "20261008", "v3") == "20261008.v1"
    assert (dep.next_version(s, "/r", "bets", "20261008", "v4")
            == "20261008-v4.v1")


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
