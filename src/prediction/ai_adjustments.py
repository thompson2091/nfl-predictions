"""AI-powered prediction adjustments using Claude API.

Applies bounded probability adjustments based on situational context.
Works for both predict season (forward-looking) and historical seasons (backtesting).
For historical seasons, Claude is given only the context that was available at that point.
"""
import hashlib
import json
import os
from datetime import date
from pathlib import Path

import anthropic
import polars as pl

from src.utils.config import get_config
from src.utils.paths import get_path


def _get_client() -> anthropic.Anthropic | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("\"'")
                    break
    if not key:
        return None
    return anthropic.Anthropic(api_key=key)


def _cache_dir() -> Path:
    d = Path("data/raw/ai_context_cache")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(season: int, week: int, game_id: str, target_type: str) -> str:
    raw = f"{season}_{week}_{game_id}_{target_type}"
    return hashlib.md5(raw.encode()).hexdigest()


def _load_cached(season: int, week: int, game_id: str, target_type: str) -> dict | None:
    path = _cache_dir() / f"{_cache_key(season, week, game_id, target_type)}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _save_cache(season: int, week: int, game_id: str, target_type: str, data: dict):
    path = _cache_dir() / f"{_cache_key(season, week, game_id, target_type)}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_ai_adjustments(
    game_id: str,
    game_label: str,
    players: list[dict],
    season: int,
    week: int,
    target_type: str,
    force_refresh: bool = False,
) -> dict:
    """Get AI adjustments for a single game.

    Args:
        game_id: Game identifier
        game_label: Human-readable game label (e.g. "BAL @ IND")
        players: List of dicts with player_name, team, probability, and
                 optional situational flags (is_new_team, is_revenge_game, etc.)
        season: NFL season year
        week: Week number
        target_type: "first_td" or "anytime_td"
        force_refresh: Bypass cache

    Returns:
        Dict of player_name -> {adjustment: float, reason: str}
    """
    cfg = get_config()
    ai_cfg = cfg.get("ai_context", {})
    if not ai_cfg.get("enabled", False):
        return {}

    max_adj = ai_cfg.get("max_adjustment", 0.1)

    # Check cache
    if not force_refresh:
        cached = _load_cached(season, week, game_id, target_type)
        if cached is not None:
            return cached

    client = _get_client()
    if client is None:
        return {}

    target_label = "First TD Scorer" if target_type == "first_td" else "Anytime TD Scorer"

    # Build player context
    player_lines = []
    for p in players[:15]:  # top 15 per game
        line = f"  {p['player_name']} ({p['team']}) — Model: {p['probability']*100:.1f}%"

        # Add situational flags
        flags = []
        if p.get("is_new_team"):
            flags.append("NEW TEAM")
        if p.get("is_revenge_game"):
            flags.append("REVENGE GAME")
        if p.get("is_role_change"):
            flags.append("ROLE CHANGE")
        if p.get("is_post_bye"):
            flags.append("POST-BYE")
        if p.get("is_season_opener"):
            flags.append("SEASON OPENER")
        if p.get("weeks_since_last_game") and p["weeks_since_last_game"] > 3:
            flags.append(f"RETURNING (missed {p['weeks_since_last_game']} weeks)")
        if p.get("rest_advantage") and abs(p["rest_advantage"]) >= 3:
            flags.append(f"REST ADV {'+'if p['rest_advantage']>0 else ''}{p['rest_advantage']}d")
        if p.get("career_seasons") and p["career_seasons"] >= 8:
            flags.append(f"VET ({p['career_seasons']} seasons)")
        if p.get("vegas_odds") is not None:
            vo = p["vegas_odds"]
            vegas_str = f"+{vo}" if vo > 0 else str(vo)
            flags.append(f"Vegas: {vegas_str} ({p.get('vegas_implied', 0)*100:.0f}%)")

        if flags:
            line += f" [{', '.join(flags)}]"
        player_lines.append(line)

    # Date context: for historical seasons, tell Claude the date as if we're in that season
    predict_season = cfg["seasons"].get("predict_season", 0)
    if season < predict_season:
        # Historical: set context as if it's that season
        date_ctx = (
            f"You are analyzing {season} NFL Week {week} — treat this as if the current date "
            f"is during the {season} NFL season. Do NOT use knowledge of events after this week."
        )
    else:
        today = date.today().isoformat()
        date_ctx = (
            f"Today is {today}. You are analyzing the upcoming {season} NFL season, Week {week}."
        )

    prompt = f"""{date_ctx}

You are an expert NFL analyst. Review these {target_label} predictions for {game_label} and suggest probability adjustments based on situational context.

ALL data comes from our structured datasets. Use ONLY this data — do NOT speculate about information not provided.

PLAYERS:
{chr(10).join(player_lines)}

For any players where the situational flags suggest the model might be over- or under-valuing them, return a JSON object mapping player names to adjustments.

Rules:
- Adjustments are MULTIPLICATIVE factors between -{max_adj} and +{max_adj}
- Example: {{"Player Name": {{"adjustment": 0.05, "reason": "Revenge game motivation + post-bye rest advantage"}}}}
- Only adjust players where you see a clear situational signal — most players should NOT be adjusted
- Return an empty object {{}} if no adjustments are warranted
- Be conservative — these adjustments modify a well-calibrated statistical model

Return ONLY valid JSON. No markdown, no code blocks, no explanation outside the JSON."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown code blocks if Claude included them
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        adjustments = json.loads(raw)

        # Validate and clamp adjustments
        validated = {}
        for name, data in adjustments.items():
            if isinstance(data, dict) and "adjustment" in data:
                adj = float(data["adjustment"])
                adj = max(-max_adj, min(max_adj, adj))
                validated[name] = {
                    "adjustment": adj,
                    "reason": data.get("reason", ""),
                }

        _save_cache(season, week, game_id, target_type, validated)
        return validated

    except (json.JSONDecodeError, Exception):
        return {}


def apply_adjustments(
    result: pl.DataFrame,
    adjustments_by_game: dict[str, dict],
) -> pl.DataFrame:
    """Apply AI adjustments to prediction results.

    Args:
        result: Predictions DataFrame with game_id, player_name, probability columns
        adjustments_by_game: Dict of game_id -> {player_name: {adjustment, reason}}

    Returns:
        DataFrame with ai_adjusted_prob and ai_reason columns added
    """
    adj_list = []
    reason_list = []

    for row in result.iter_rows(named=True):
        game_adjs = adjustments_by_game.get(row["game_id"], {})
        player_adj = game_adjs.get(row["player_name"], {})

        if player_adj:
            adj_factor = player_adj["adjustment"]
            # Multiplicative: new_prob = prob * (1 + adjustment)
            adjusted = row["probability"] * (1 + adj_factor)
            adjusted = max(0.001, min(0.999, adjusted))
            adj_list.append(adjusted)
            reason_list.append(player_adj.get("reason", ""))
        else:
            adj_list.append(row["probability"])
            reason_list.append("")

    result = result.with_columns([
        pl.Series("ai_adjusted_prob", adj_list),
        pl.Series("ai_reason", reason_list),
    ])

    return result
