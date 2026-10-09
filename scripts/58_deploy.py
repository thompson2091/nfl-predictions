#!/usr/bin/env python3
"""Build site/v3 and put it on the server, in one command.

    python scripts/58_deploy.py --dry-run     # show exactly what would happen
    python scripts/58_deploy.py               # build, upload, promote, verify
    python scripts/58_deploy.py --no-build    # upload what is already in site/v3

**THE `data/` FOLDER GOES TOO, AND THAT IS THE POINT OF THIS SCRIPT.** The
manual routine it replaces copied `index.html`, `manifest.webmanifest` and
`sw.js` and stopped there, so every past week on the live site failed to load
— and because a blocked fetch used to render as "no priced picks recorded",
the site said the weeks were empty rather than missing. Three files uploaded
out of four is the most expensive kind of nearly-right.

**ONE SSH CONNECTION, SO ONE PASSWORD PROMPT.** `ControlMaster` opens a single
multiplexed connection up front; every copy and command rides on it and closes
when the script exits. The previous routine asked five times.

**NO PASSWORD IS STORED, READ OR ACCEPTED.** Not in `.env`, not on the command
line, not in an environment variable. A password in a dotfile ends up in shell
history, in a backup, in a crash report, and it is the credential for a root
account on a public web server. `ssh-copy-id root@host` once and this script
never prompts again — run `--setup-keys` for the exact command.

The versioned copy is kept: `bets/YYYYMMDD.vN.html`, numbered up from whatever
is already on the server, then promoted to `index.html`. So a bad build is one
`cp` away from being rolled back, from a shell you are already in.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, ".")

#: Overridable in `.env` — host and paths, never a credential.
DEFAULTS = {
    "DEPLOY_HOST": "squarespro.com",
    "DEPLOY_USER": "root",
    "DEPLOY_ROOT": "/var/www/html",
    "DEPLOY_ARCHIVE": "bets",
}

#: The three that must land beside each other. `sw.js` takes its scope from
#: the directory it is served from, so a manifest or worker one level off is
#: an app that loads, works, and never installs or goes offline.
TOP = ["index.html", "manifest.webmanifest", "sw.js"]

#: EVERY DATA FILE THE BUILD WRITES, AS THE PATTERNS THAT CARRY IT UP. This is
#: the contract between `52_export_v3.py`, which decides what to write, and
#: this script, which decides what to send — and it was broken for as long as
#: the full player history existed. The week files are `h-<market>-<week>.json`
#: and the glob that collected them was `h-*.json`; the history files are
#: `hist-<market>.json`, whose second character is an `i` and not a `-`, so
#: they matched nothing and six files totalling 1.6 MB stayed on the laptop.
#: Nothing failed: the page fetched one, got a 404, and quietly redrew the
#: button that had asked for it.
#:
#: `test_every_data_file_the_build_writes_is_one_the_deploy_uploads` reads this
#: tuple against the paths the exporter actually writes, so the next file added
#: there fails a test rather than going missing in production.
#:
#: **AND THE TUPLE MUST BE WHAT THE UPLOAD ACTUALLY GLOBS.** It was not. The
#: upload below reaches for its own `data.glob(...)` per group and never reads
#: this tuple, so adding `tlines.json` here satisfied the test while the
#: uploader ignored it — the file was built, every test passed, and the live
#: page 404'd on it on 2026-10-03. The same silent shape as the bug this
#: constant was introduced to prevent, one level further out.
#:
#: `test_the_upload_globs_what_this_tuple_names` now reads the source below and
#: requires every entry here to be globbed there. The groups stay separate on
#: purpose — week files are pruned, ask briefs go to a subdirectory — so the
#: fix is to keep the two in step, not to merge them.
#: `ask/*/*.json` is the Ask box's slices — `core/<gid>`, `players/<gid>`,
#: `angles/<gid>`, `team/<TEAM>` and `record/season`, one directory deeper
#: than the flat briefs beside them. A glob that stops at `ask/*.json` ships
#: the summary and none of the data the model asks for, which is the exact
#: shape of the `hist-*.json` bug this tuple was introduced to prevent: the
#: page works, every answer is thin, and nothing fails.
DATA_GLOBS = ("h-*.json", "hist-*.json", "tlines.json", "ask/*.json",
              "ask/*/*.json")


def env(key: str) -> str:
    v = os.environ.get(key)
    if v:
        return v
    p = Path(".env")
    if p.exists():
        for line in p.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return DEFAULTS[key]


class Session:
    """One multiplexed SSH connection for the whole deploy."""

    def __init__(self, target: str, dry: bool):
        self.target, self.dry = target, dry
        self.sock = str(Path(tempfile.mkdtemp()) / "cm")

    #: A key dedicated to this deploy, used when it exists. Named rather than
    #: left to ssh's defaults because this machine has two dozen keys for
    #: other things and offering all of them can exhaust the server's auth
    #: attempt limit before reaching the right one.
    KEY = Path.home() / ".ssh" / "id_ed25519_squarespro"

    def _base(self) -> list[str]:
        opts = ["-o", "ControlMaster=auto", "-o", f"ControlPath={self.sock}",
                "-o", "ControlPersist=120"]
        if self.KEY.exists():
            # `IdentitiesOnly` so ssh uses THIS key rather than adding it to
            # the pile it already offers.
            opts += ["-i", str(self.KEY), "-o", "IdentitiesOnly=yes"]
        return opts

    def open(self) -> bool:
        if self.dry:
            return True
        print(f"opening one connection to {self.target} "
              f"(you will be asked for the password once, if keys are not "
              f"set up)\n", file=sys.stderr)
        r = subprocess.run(["ssh", *self._base(), self.target, "true"])
        return r.returncode == 0

    def run(self, cmd: str) -> subprocess.CompletedProcess | None:
        if self.dry:
            print(f"  ssh {self.target} '{cmd}'")
            return None
        return subprocess.run(["ssh", *self._base(), self.target, cmd],
                              capture_output=True, text=True)

    def copy(self, src: str, dest: str, recursive: bool = False) -> bool:
        if self.dry:
            print(f"  scp {'-r ' if recursive else ''}{src} "
                  f"{self.target}:{dest}")
            return True
        cmd = ["scp", *self._base()]
        if recursive:
            cmd.append("-r")
        cmd += [src, f"{self.target}:{dest}"]
        return subprocess.run(cmd).returncode == 0

    def close(self) -> None:
        if not self.dry:
            subprocess.run(["ssh", "-o", f"ControlPath={self.sock}",
                            "-O", "exit", self.target],
                           capture_output=True)


#: Only files matching this are ever considered for deletion. Belt and
#: braces on top of the explicit list below: a bug that produced an empty
#: keep-set can then delete week files and nothing else.
PRUNABLE = "h-"


def _prune(s: "Session", web: str, keep: set, dry: bool) -> None:
    """Remove week files the build no longer produces — BY NAME, one at a time.

    The first version built a shell `for` loop with a `case` statement and
    interpolated the keep-list into it as a quoted string. The quotes collided
    with the quotes ssh needs around the whole command, so the pattern never
    matched what it was meant to and the loop it guarded was `rm -f`. On a
    live web server.

    So nothing is matched remotely. The directory is LISTED, the difference is
    computed here where it can be printed and tested, and each stale file is
    removed by its exact name. A file that does not start with `h-` is never
    a candidate however wrong the rest of this gets.
    """
    # `dry` is checked HERE rather than inferred from the session returning
    # None. A destructive step that decides whether it is a rehearsal by
    # looking at the shape of someone else's return value is a step that
    # deletes things the day that return value changes.
    if dry:
        print(f"  (would list {web}/data and remove any h-*.json not in the "
              f"{len(keep)} just uploaded)")
        return
    got = s.run(f"ls {web}/data 2>/dev/null")
    if got is None:
        return
    if got.returncode != 0:
        return
    remote = {ln.strip() for ln in (got.stdout or "").splitlines() if ln.strip()}
    stale = sorted(f for f in remote
                   if f.startswith(PRUNABLE) and f.endswith(".json")
                   and f not in keep)
    if not stale:
        return
    print(f"  removing {len(stale)} stale week file(s): "
          f"{', '.join(stale[:4])}{' ...' if len(stale) > 4 else ''}",
          file=sys.stderr)
    for name in stale:
        s.run(f"rm -f {web}/data/{name}")


def next_version(s: Session, root: str, archive: str, stamp: str,
                 app: str = "v3") -> str:
    """`YYYYMMDD.vN`, counting up from what is already on the server.

    Asked rather than assumed: deploying twice in a day is normal and
    overwriting this morning's archive copy would remove the thing that makes
    a rollback one command.

    **THE APP IS IN THE NAME FOR EVERYTHING BUT v3.** Both apps archive into
    one `bets/` directory, so a shared `YYYYMMDD.vN` would have v4's build
    counting v3's copies and then overwriting one of them — and a rollback
    would restore whichever app happened to win. v3 keeps the bare name it
    has always had, so every archived build already on the server stays
    addressable and the rollback line in anyone's notes still works.
    """
    pre = stamp if app == "v3" else f"{stamp}-{app}"
    got = s.run(f"ls {root}/{archive}/{pre}.v*.html 2>/dev/null | wc -l")
    n = 1
    if got and got.returncode == 0:
        try:
            n = int((got.stdout or "0").strip()) + 1
        except ValueError:
            n = 1
    return f"{pre}.v{n}"


def _canonical(host: str) -> str:
    """The rewrite that sends every other address to `https://<host>/`."""
    bare = host[4:] if host.startswith("www.") else host
    esc = bare.replace(".", "\\.")
    return (
        "# One address: http:// and www. go to https://" + bare + "/, so saved\n"
        "# picks live in one browser store. Written by 58_deploy.py.\n"
        "<IfModule mod_rewrite.c>\n"
        "  RewriteEngine On\n"
        "  RewriteCond %{HTTPS} off [OR]\n"
        "  RewriteCond %{HTTP_HOST} !^" + esc + "$ [NC]\n"
        "  RewriteRule ^ https://" + bare + "%{REQUEST_URI} [L,R=301]\n"
        "</IfModule>\n\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print every command and change nothing")
    ap.add_argument("--no-build", action="store_true",
                    help="upload what is in site/<app> already")
    # WHICH APP, AND WHERE ON THE SERVER IT LANDS.
    #
    # v3 owns the web root and v4 sits under `/v4/` so the two can be read
    # side by side on one week's data. The prefix is not cosmetic: a service
    # worker's scope is the directory it is served from, so a page at `/v4/`
    # needs its OWN `sw.js` and its OWN `data/` beside it. Sharing `/data/`
    # would give a page that works online and has no offline week files,
    # because a worker scoped to `/v4/` cannot intercept a request to
    # `/data/` — it would load, work, and silently stop working on a train.
    ap.add_argument("--app", default="v3", choices=["v3", "v4"])
    # ON BY DEFAULT since 2026-10-09, once both readers confirmed they use
    # https://squarespro.com. It has to be: `.htaccess` is uploaded whole on
    # every deploy, so an opt-in flag would be undone by the next unattended
    # one — the Tuesday rollover deploys without arguments.
    ap.add_argument("--no-canonical", dest="canonical", action="store_false",
                    help="do not send http:// and www. to https://<host>/. "
                         "Each address keeps its own saved picks")
    ap.set_defaults(canonical=True)
    ap.add_argument("--out", default=None,
                    help="local build directory (default: site/<app>)")
    ap.add_argument("--setup-keys", action="store_true",
                    help="print how to stop being asked for a password")
    a = ap.parse_args()

    host, user = env("DEPLOY_HOST"), env("DEPLOY_USER")
    root, archive = env("DEPLOY_ROOT"), env("DEPLOY_ARCHIVE")
    target = f"{user}@{host}"
    if a.out is None:
        a.out = f"site/{a.app}"
    # Where the app's three files and its data/ go. v3 keeps the web root it
    # has always had; v4 gets a subdirectory of its own. The archive stays at
    # the root for both, with the app in the version name, so one rollback
    # command works either way and the two cannot overwrite each other's
    # history.
    web = root if a.app == "v3" else f"{root}/{a.app}"

    if a.setup_keys:
        key = Session.KEY
        print(f"""
To stop typing the password, run this once:

    {'' if key.exists() else 'ssh-keygen -t ed25519 -N "" -f ' + str(key)}
    ssh-copy-id -i {key}.pub {target}

It will ask for the server password one final time. After that this script,
scp and ssh all find the key by themselves.

Key present: {'yes, at ' + str(key) if key.exists() else 'no'}

Do NOT put the password in .env. It is the root account of a public web
server, and a dotfile ends up in shell history, in backups and in crash
reports.
""")
        return 0

    if not a.no_build:
        print("building ...", file=sys.stderr)
        r = subprocess.run([sys.executable, "scripts/52_export_v3.py",
                            "--app", a.app, "--out", a.out])
        if r.returncode != 0:
            print("build failed; nothing uploaded", file=sys.stderr)
            return 1

    out = Path(a.out)
    missing = [f for f in TOP if not (out / f).exists()]
    if missing:
        print(f"missing {', '.join(missing)} in {out} — refusing to deploy "
              f"a partial site", file=sys.stderr)
        return 1
    data = out / "data"
    week_files = sorted(data.glob("h-*.json")) if data.exists() else []
    hist_files = sorted(data.glob("hist-*.json")) if data.exists() else []
    tline_files = sorted(data.glob("tlines.json")) if data.exists() else []
    ask_files = sorted((data / "ask").glob("*.json")) if data.exists() else []
    # One directory deeper, and listed separately because they are uploaded
    # to a path that includes their subdirectory. Globbed here rather than
    # merged into `ask_files` so the upload below cannot lose the prefix.
    slice_files = (sorted((data / "ask").glob("*/*.json"))
                   if data.exists() else [])
    if not week_files:
        # A warning, not a failure: a season before any week is played has
        # none, and that is legitimate.
        print("  note: no data/ week files to upload — the week picker will "
              "have nothing to fetch", file=sys.stderr)

    stamp = date.today().strftime("%Y%m%d")
    s = Session(target, a.dry_run)
    if not s.open():
        print("could not connect", file=sys.stderr)
        return 1
    try:
        ver = next_version(s, root, archive, stamp, a.app)
        print(f"\ndeploying as {ver}\n", file=sys.stderr)
        # AND A LOCAL COPY UNDER THE SAME NAME. The server's `bets/` was the
        # only record of what each deploy served, and git does not line up
        # with it — deploys come from the working tree. Gitignored: 6 MB a
        # build, and the server keeps its own.
        if not a.dry_run:
            hist = Path("deploy/history")
            hist.mkdir(parents=True, exist_ok=True)
            shutil.copy2(out / "index.html", hist / f"{ver}.html")
        subs = sorted({f.parent.name for f in slice_files})
        s.run(f"mkdir -p {root}/{archive} {web} {web}/data {web}/data/ask"
              + "".join(f" {web}/data/ask/{d}" for d in subs))

        # The archive copy first, so a failure part-way leaves the live page
        # untouched rather than half-replaced.
        if not s.copy(str(out / "index.html"),
                      f"{root}/{archive}/{ver}.html"):
            print("upload of index.html failed; live page untouched",
                  file=sys.stderr)
            return 1
        for f in ("manifest.webmanifest", "sw.js"):
            if not s.copy(str(out / f), f"{web}/{f}"):
                print(f"upload of {f} failed", file=sys.stderr)
                return 1
        if week_files:
            print(f"  {len(week_files)} week files "
                  f"({sum(f.stat().st_size for f in week_files) / 1024:,.0f} KB)",
                  file=sys.stderr)
            for f in week_files:
                if not s.copy(str(f), f"{web}/data/{f.name}"):
                    print(f"upload of {f.name} failed", file=sys.stderr)
                    return 1
            _prune(s, web, {f.name for f in week_files}, a.dry_run)
        # A SEPARATE STEP, NOT A WIDER GLOB. Loosening the week glob to `h*`
        # would also put these under `_prune`, which deletes anything matching
        # PRUNABLE that is not in its keep-set — a sweep they have no reason
        # to be inside. They are rewritten whole on every build.
        if hist_files:
            print(f"  {len(hist_files)} history files "
                  f"({sum(f.stat().st_size for f in hist_files) / 1024:,.0f} KB)",
                  file=sys.stderr)
            for f in hist_files:
                if not s.copy(str(f), f"{web}/data/{f.name}"):
                    print(f"upload of {f.name} failed", file=sys.stderr)
                    return 1
        else:
            # Said out loud: "Show every week" is the only thing that reads
            # them, and with none uploaded it is a button that does nothing.
            print("  note: no data/hist-*.json to upload — \"Show every week\" "
                  "will 404", file=sys.stderr)
        # THE TEAM LINE RECORD, on the same footing as the player history and
        # for the same reason: "Show every game" is the only thing that reads
        # it, and without it that button 404s in silence.
        if tline_files:
            print(f"  team line record "
                  f"({sum(f.stat().st_size for f in tline_files) / 1024:,.0f} KB)",
                  file=sys.stderr)
            for f in tline_files:
                if not s.copy(str(f), f"{web}/data/{f.name}"):
                    print(f"upload of {f.name} failed", file=sys.stderr)
                    return 1
        else:
            print("  note: no data/tlines.json to upload — \"Show every game\" "
                  "will 404", file=sys.stderr)
        if ask_files:
            print(f"  {len(ask_files)} ask briefs", file=sys.stderr)
            for f in ask_files:
                if not s.copy(str(f), f"{web}/data/ask/{f.name}"):
                    print(f"upload of {f.name} failed", file=sys.stderr)
                    return 1
        if slice_files:
            print(f"  {len(slice_files)} ask slices "
                  f"({sum(f.stat().st_size for f in slice_files) / 1024:,.0f} KB)",
                  file=sys.stderr)
            for f in slice_files:
                # The parent directory is part of the destination. Uploading
                # by `f.name` alone would flatten `core/TB_DAL.json` and
                # `players/TB_DAL.json` onto each other.
                rel = f"{f.parent.name}/{f.name}"
                if not s.copy(str(f), f"{web}/data/ask/{rel}"):
                    print(f"upload of {rel} failed", file=sys.stderr)
                    return 1
        # The proxy itself. Uploaded every time so a change to it ships with
        # the page that calls it; it reads its key from outside the web root
        # and holds no secret of its own.
        # BESIDE THE PAGE THAT CALLS IT, not at the root.
        #
        # `V3ASK_URL` is the relative string `ask.php`, so a page at `/v4/`
        # calls `/v4/ask.php` — and the proxy resolves its data directory
        # from `__DIR__`. One copy at the root would have v4's Ask reading
        # v3's briefs, which are the same numbers only for as long as both
        # apps are deployed in the same run.
        php = Path("deploy/ask.php")
        if php.exists():
            if not s.copy(str(php), f"{web}/ask.php"):
                print("upload of ask.php failed", file=sys.stderr)
                return 1
        # And the cache rules. Without them Apache serves the page with an
        # ETag and no Cache-Control, browsers cache it heuristically, and a
        # deploy lands while the reader keeps seeing the previous build.
        ht = Path("deploy/htaccess")
        if ht.exists() and a.canonical:
            # ONE ADDRESS. The site answered on http://, https:// and www.,
            # and browser storage belongs to an address — so saved picks made
            # on one were missing on the others, which looks exactly like a
            # deploy deleting them.
            tmp = Path(tempfile.mkdtemp()) / "htaccess"
            tmp.write_text(_canonical(host) + ht.read_text())
            ht = tmp
        if ht.exists():
            if not s.copy(str(ht), f"{root}/.htaccess"):
                print("upload of .htaccess failed", file=sys.stderr)
                return 1

        # Promote last. Everything the new page needs is already in place.
        s.run(f"cp {root}/{archive}/{ver}.html {web}/index.html")

        if not a.dry_run:
            check = s.run(f"ls -l {web}/index.html {web}/sw.js "
                          f"{web}/manifest.webmanifest && "
                          f"ls {web}/data | wc -l")
            print((check.stdout or "") + (check.stderr or ""), file=sys.stderr)
            at = "" if a.app == "v3" else a.app + "/"
            print(f"live: https://{host}/{at}\n"
                  f"rollback: ssh {target} "
                  f"'cp {root}/{archive}/<older>.html {web}/index.html'",
                  file=sys.stderr)
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
