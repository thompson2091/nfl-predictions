"""Keep the previous copy of a served file before it is overwritten.

`blend_weight.json`, `edge_threshold.json` and `market_blend_served.json` are
refit in place, and each had one git commit: the weight a board was served
with last week was simply gone once this week's fit landed, and the locked
manifest's artifact hashes stopped describing what was being served without
anything saying so. `write_kept` moves the old copy to `history/` beside it,
stamped, before writing the new one. A rewrite that changes nothing keeps
nothing.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def write_kept(path: Path | str, text: str) -> Path | None:
    """Write `text` to `path`, keeping the old file under `history/`.

    Returns where the old copy went, or None when there was nothing to keep.
    """
    p = Path(path)
    kept = None
    if p.exists():
        if p.read_text() == text:
            return None
        h = p.parent / "history"
        h.mkdir(parents=True, exist_ok=True)
        kept = h / f"{p.stem}.{datetime.now():%Y%m%dT%H%M%S}{p.suffix}"
        shutil.copy2(p, kept)
    p.write_text(text)
    return kept
