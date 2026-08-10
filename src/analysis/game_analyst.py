"""AI-powered game analysis using Claude API."""
import os
from datetime import date
from pathlib import Path

import anthropic


def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("\"'")
                    break
    return key


def _get_client() -> anthropic.Anthropic | None:
    key = _get_api_key()
    if not key:
        return None
    return anthropic.Anthropic(api_key=key)


def _date_context(season: int, week: int) -> str:
    """Build explicit date context for Claude prompts."""
    today = date.today().isoformat()
    return (
        f"Today is {today}. You are analyzing the {season} NFL season, Week {week}. "
        f"IMPORTANT: Do NOT rely on your training data for current NFL facts. "
        f"Only use the structured data provided below."
    )


def analyze_edges(
    edges: list[dict],
    target_type: str,
    season: int = 0,
    week: int = 0,
) -> str:
    """Analyze model vs Vegas disagreements with structured data only. Returns markdown.

    Each edge dict should have:
        player_name, team, game_label,
        model_prob, vegas_prob, edge_pct,
        situational (optional): dict of situational flags
    """
    client = _get_client()
    if client is None:
        return "No ANTHROPIC_API_KEY found. Add it to .env to enable AI analysis."

    if not edges:
        return "No significant edges found between model and Vegas this week."

    target_label = "First TD Scorer" if target_type == "first_td" else "Anytime TD Scorer"

    # Split into value picks (model > vegas) and fades (vegas > model)
    value_picks = sorted([e for e in edges if e["edge_pct"] > 0],
                         key=lambda x: x["edge_pct"], reverse=True)
    fades = sorted([e for e in edges if e["edge_pct"] < 0],
                   key=lambda x: x["edge_pct"])

    lines = []
    if value_picks:
        lines.append("VALUE PICKS (Model > Vegas):")
        for e in value_picks[:10]:
            sit = _format_situational(e.get("situational", {}))
            lines.append(
                f"  {e['player_name']} ({e['team']}) — {e['game_label']} — "
                f"Model: {e['model_prob']*100:.1f}% vs Vegas: {e['vegas_prob']*100:.1f}% "
                f"(+{e['edge_pct']:.1f}pp edge){sit}"
            )

    if fades:
        lines.append("\nFADES (Vegas > Model):")
        for e in fades[:10]:
            sit = _format_situational(e.get("situational", {}))
            lines.append(
                f"  {e['player_name']} ({e['team']}) — {e['game_label']} — "
                f"Model: {e['model_prob']*100:.1f}% vs Vegas: {e['vegas_prob']*100:.1f}% "
                f"({e['edge_pct']:.1f}pp){sit}"
            )

    date_ctx = _date_context(season, week) if season else ""

    prompt = f"""{date_ctx}

You are an expert NFL betting analyst. Our {target_label} prediction model disagrees with Vegas on these players.
ALL data below comes from our model and structured datasets — use ONLY this data for your analysis.

{chr(10).join(lines)}

For the top 3-5 most interesting disagreements, explain:
1. **Why might the model be right?** — What statistical signals (from the data above) could drive this?
2. **Why might Vegas be right?** — What qualitative factors might Vegas price in that a statistical model misses?
3. **Verdict** — Is this a genuine edge worth betting, or trust Vegas?

Be specific. Reference the actual numbers and situational flags provided. Do NOT speculate about current injuries, depth chart changes, or team news unless flagged in the data above."""

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _format_situational(sit: dict) -> str:
    """Format situational flags as a compact string."""
    if not sit:
        return ""
    flags = []
    if sit.get("is_new_team"):
        flags.append("NEW TEAM")
    if sit.get("is_revenge_game"):
        flags.append("REVENGE GAME")
    if sit.get("is_role_change"):
        flags.append("ROLE CHANGE")
    if sit.get("is_post_bye"):
        flags.append("POST-BYE")
    if sit.get("is_season_opener"):
        flags.append("SEASON OPENER")
    if sit.get("weeks_since_last_game") and sit["weeks_since_last_game"] > 3:
        flags.append(f"RETURN (out {sit['weeks_since_last_game']} weeks)")
    if sit.get("rest_advantage") and abs(sit["rest_advantage"]) >= 3:
        flags.append(f"REST {'+'if sit['rest_advantage']>0 else ''}{sit['rest_advantage']}d")
    if not flags:
        return ""
    return f" [{', '.join(flags)}]"
