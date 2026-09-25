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


def _prune(s: "Session", root: str, keep: set, dry: bool) -> None:
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
        print(f"  (would list {root}/data and remove any h-*.json not in the "
              f"{len(keep)} just uploaded)")
        return
    got = s.run(f"ls {root}/data 2>/dev/null")
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
        s.run(f"rm -f {root}/data/{name}")


def next_version(s: Session, root: str, archive: str, stamp: str) -> str:
    """`YYYYMMDD.vN`, counting up from what is already on the server.

    Asked rather than assumed: deploying twice in a day is normal and
    overwriting this morning's archive copy would remove the thing that makes
    a rollback one command.
    """
    got = s.run(f"ls {root}/{archive}/{stamp}.v*.html 2>/dev/null | wc -l")
    n = 1
    if got and got.returncode == 0:
        try:
            n = int((got.stdout or "0").strip()) + 1
        except ValueError:
            n = 1
    return f"{stamp}.v{n}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print every command and change nothing")
    ap.add_argument("--no-build", action="store_true",
                    help="upload what is in site/v3 already")
    ap.add_argument("--out", default="site/v3")
    ap.add_argument("--setup-keys", action="store_true",
                    help="print how to stop being asked for a password")
    a = ap.parse_args()

    host, user = env("DEPLOY_HOST"), env("DEPLOY_USER")
    root, archive = env("DEPLOY_ROOT"), env("DEPLOY_ARCHIVE")
    target = f"{user}@{host}"

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
                            "--out", a.out])
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
        ver = next_version(s, root, archive, stamp)
        print(f"\ndeploying as {ver}\n", file=sys.stderr)
        s.run(f"mkdir -p {root}/{archive} {root}/data")

        # The archive copy first, so a failure part-way leaves the live page
        # untouched rather than half-replaced.
        if not s.copy(str(out / "index.html"),
                      f"{root}/{archive}/{ver}.html"):
            print("upload of index.html failed; live page untouched",
                  file=sys.stderr)
            return 1
        for f in ("manifest.webmanifest", "sw.js"):
            if not s.copy(str(out / f), f"{root}/{f}"):
                print(f"upload of {f} failed", file=sys.stderr)
                return 1
        if week_files:
            print(f"  {len(week_files)} week files "
                  f"({sum(f.stat().st_size for f in week_files) / 1024:,.0f} KB)",
                  file=sys.stderr)
            for f in week_files:
                if not s.copy(str(f), f"{root}/data/{f.name}"):
                    print(f"upload of {f.name} failed", file=sys.stderr)
                    return 1
            _prune(s, root, {f.name for f in week_files}, a.dry_run)

        # Promote last. Everything the new page needs is already in place.
        s.run(f"cp {root}/{archive}/{ver}.html {root}/index.html")

        if not a.dry_run:
            check = s.run(f"ls -l {root}/index.html {root}/sw.js "
                          f"{root}/manifest.webmanifest && "
                          f"ls {root}/data | wc -l")
            print((check.stdout or "") + (check.stderr or ""), file=sys.stderr)
            print(f"live: https://{host}/\n"
                  f"rollback: ssh {target} "
                  f"'cp {root}/{archive}/<older>.html {root}/index.html'",
                  file=sys.stderr)
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
