# Publishing the board

How the web board is built, how it reaches squarespro.com, and what the Ask
box costs. Read [OVERVIEW.md](OVERVIEW.md) first for what the models are and
[DATA_SOURCES.md](DATA_SOURCES.md) for where the numbers come from.

The published board is a single-page app with no server behind it, except for
one PHP proxy that answers questions. Everything else is static files.

---

## The two boards

| Board | Source | Built by | Audience |
|---|---|---|---|
| `site/v2` | `src/export/pwa.py` | `scripts/51_export_app.py` | The original installable PWA |
| `site/v3` | `src/export/v3.py`, `v3js.py`, `v3css.py` | `scripts/52_export_v3.py` | What squarespro.com serves |

v3 is the one that ships. It shares every calculation with v1 and v2 — the
payload builder is the same, so the board and the backtest cannot disagree
about a player — and owns only the shell and the wording.

## Build

```bash
python scripts/52_export_v3.py             # writes site/v3/
python scripts/52_export_v3.py --no-ai     # template sentences; no API call
python scripts/52_export_v3.py --week 3    # build a specific week
```

`--no-ai` is the one to use when you are iterating on layout: the notes ship
in their written phrasing and the build makes no request.

That produces:

```
site/v3/
  index.html              the whole app, payload inlined
  manifest.webmanifest    install metadata
  sw.js                   network-first service worker
  data/h-<market>-<week>.json    one graded week per market
  data/ask/<GAME>.json           one brief per game, for the Ask box
```

The page inlines its payload but **not** its history. A full season across six
markets measures about 20MB inlined, so `_split_history` lifts each week into
its own file and leaves an index behind. The index keeps two things the game
screen needs without fetching anything:

- `has` — which weeks exist.
- `by_game` — how many priced rows each game holds, per week.

`by_game` exists because six markets for one week is roughly 900KB, and the
game screen has to know which markets hold players for the game you opened
without downloading them to find out. Before it existed, the Players tab
opened on whichever market the board was left on, and fourteen of week 2's
sixteen games opened on a market holding nothing.

Important: a market whose prediction file has no `has_market_price` column
counts as priced, not unpriced. The first-TD board has never carried the
column, and reading a missing field as `false` emptied the market on every
past week while printing the message a genuinely empty week prints.

## Deploy

```bash
python scripts/58_deploy.py           # build, upload, promote
python scripts/58_deploy.py --dry-run # say what it would do, change nothing
python scripts/58_deploy.py --no-build  # ship what is already in site/v3
```

The script opens **one** SSH connection (ControlMaster) and reuses it for
every copy, so you authenticate once and the whole deploy runs over that
socket. It uploads in this order and promotes last, so the live page never
points at files that have not landed yet:

1. `index.html` into the versioned archive as `bets/YYYYMMDD.vN.html`
2. `manifest.webmanifest` and `sw.js`
3. the week files, then prune any the build no longer produces
4. the per-game Ask briefs
5. `ask.php` and `.htaccess`
6. `cp bets/YYYYMMDD.vN.html index.html` — the promotion

Rolling back is copying an older archive file over `index.html`. The script
prints the exact command when it finishes.

### Settings

Override any of these in `.env`. None of them is a credential.

| Key | Default |
|---|---|
| `DEPLOY_HOST` | `squarespro.com` |
| `DEPLOY_USER` | `root` |
| `DEPLOY_ROOT` | `/var/www/html` |
| `DEPLOY_ARCHIVE` | `bets` |

`DEPLOY_ARCHIVE` is the subdirectory holding versioned copies, not the path
the site is served from. The board is served from the site root.

### Authentication

The script reads no password and accepts none. It authenticates with an SSH
key at `~/.ssh/id_ed25519_squarespro`, passing `IdentitiesOnly=yes` so ssh
uses that key rather than offering every key on the machine.

```bash
python scripts/58_deploy.py --setup-keys   # prints the ssh-keygen/ssh-copy-id pair
```

A test asserts the absence of `sshpass`, `DEPLOY_PASS`, `--password`,
`getpass` and `PasswordAuthentication=yes` anywhere in the script. Putting a
password in `.env` would put it in every process listing on the machine.

### Cache headers

Apache served `index.html` with an ETag, a `Last-Modified` and no
`Cache-Control`, so browsers cached it heuristically: a deploy landed, the
file changed, and readers kept seeing the previous build with no way to know.
Every deploy now ships `deploy/htaccess` as `.htaccess`:

- `no-cache, must-revalidate` on html, json, webmanifest and `sw.js`. This
  means "ask before reusing", not "do not store" — an unchanged page still
  costs a 304 and nothing more.
- `no-store` on `ask.php`.
- `Options -Indexes`, so `data/ask/` stops serving a listing of every brief.

Note: this needs `mod_headers` enabled and `AllowOverride All` on the
directory. The service worker is network-first and was never the cause of a
stale page; this is the layer underneath it.

---

## The Ask box

Each game page carries a question box backed by `deploy/ask.php`, a proxy to
the Anthropic API. The browser never holds the key and never chooses the
context.

### How a question is answered

1. The page posts `{game, q}` to `ask.php`.
2. The proxy validates the game id against `^[A-Z]{2,4}_[A-Z]{2,4}$` **before**
   building any path from it.
3. It loads `data/ask/<GAME>.json`, the brief this repo published for that
   game — roughly 14KB of lines, projections, matchup edges and notes.
4. It checks the rate limits, then reads the key.
5. It calls the Messages API with the brief as context and the
   `web_search_20250305` server tool available, so a question about late
   injury news or weather can be answered from outside the brief.

Context comes from files on the server chosen by a validated id. Nothing in
the request body becomes a path, and nothing the caller sends becomes context.

### Limits

| Setting | Value | Why |
|---|---|---|
| `$PER_IP_HR` | 15 | One reader cannot spend the budget |
| `$PER_DAY` | 300 | The cap that actually protects the bill |
| `$MAX_Q` | 400 characters | A question, not a document |
| `$MAX_TOKENS` | 900 | A paragraph or two |
| `$TIMEOUT` | 45s | |

Both counters are checked **before** the key is read, so a refused request
costs nothing. Per-IP state is keyed by `md5(REMOTE_ADDR)`; the raw address is
never written to disk.

### Installing the key

The proxy reads `/etc/picksix/anthropic.key`, outside the web root. Without
it the endpoint answers `the question service is not configured` and the page
says asking is unavailable — the board works in full, minus the box.

```bash
grep '^ANTHROPIC_API_KEY=' .env | cut -d= -f2- | tr -d '\r\n' \
  | ssh <user>@<host> 'umask 077; cat > /etc/picksix/anthropic.key
      && chgrp www-data /etc/picksix/anthropic.key
      && chmod 640 /etc/picksix/anthropic.key'
```

Piping it never prints the key, never puts it in shell history, and never
writes it to a temporary file.

| Path | Owner | Mode |
|---|---|---|
| `/etc/picksix/anthropic.key` | `root:www-data` | `640` |
| `/var/lib/picksix` | `www-data:www-data` | `700` |

Caution: the host runs Ubuntu 14.04 and PHP 5.5, both end-of-life since 2019.
A compromise of that box takes the key with it. Use a key scoped to this use,
watch the spend, and rotate it by rewriting the file — no redeploy is needed.

Note: `ask.php` targets PHP 5.5. No null-coalescing operator, no scalar type
hints, no short array syntax in places 5.5 rejects.

### Verifying a deploy

```bash
curl -sI https://<host>/ | grep -i cache-control
curl -s -X POST https://<host>/ask.php -H 'Content-Type: application/json' \
     -d '{"game":"../../etc/passwd","q":"hi"}'      # -> unknown game
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/data/ask/     # -> 403
```

---

## The server

A single host serving static files and one PHP script.

Caution: it has 489MB of RAM and **no swap**. It has gone unresponsive under
memory pressure while still accepting TCP connections, which looks like a
hang rather than an outage. Adding a swap file is the standing recommendation:

```bash
fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
```
