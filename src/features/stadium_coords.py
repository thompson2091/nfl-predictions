"""Where each stadium is, so a weather forecast can be fetched for it.

Keyed on stadium **name**, not `stadium_id`. nflverse assigns the home team's
`stadium_id` even for neutral-site games, so JAX00 covers both Jacksonville and
Wembley — using the id would fetch Florida weather for a London kickoff. Names
change while the site does not (Heinz Field and Acrisure Stadium are one place),
so renames map to the same coordinates.

**These coordinates are asserted, then verified.** `scripts/28_weather.py
--validate` fetches the historical temperature at each site and correlates it
against the kickoff temperature nflverse already records in `schedules.parquet`.
A coordinate in the wrong city fails that check immediately, which is what makes
an asserted table safe to use: nothing here is trusted until it agrees with
independent data. Any site that fails is excluded rather than guessed at, and
its games carry null weather.

Retractable roofs (`roof == "closed"`) are handled by the caller, not here — the
venue has a location either way; whether the roof was shut is a per-game fact.
"""
from __future__ import annotations

#: name -> (latitude, longitude). Renames of one site share coordinates.
STADIUM_COORDS: dict[str, tuple[float, float]] = {
    # --- current outdoor venues -------------------------------------------
    "MetLife Stadium":                      (40.8135, -74.0745),
    "Lincoln Financial Field":              (39.9008, -75.1675),
    "Gillette Stadium":                     (42.0909, -71.2643),
    "M&T Bank Stadium":                     (39.2780, -76.6227),
    "Levi's Stadium":                       (37.4033, -121.9694),
    "Raymond James Stadium":                (27.9759, -82.5033),
    "Lambeau Field":                        (44.5013, -88.0622),
    "Bank of America Stadium":              (35.2258, -80.8528),
    "Soldier Field":                        (41.8623, -87.6167),
    "Nissan Stadium":                       (36.1665, -86.7713),
    "Hard Rock Stadium":                    (25.9580, -80.2389),
    "Sun Life Stadium":                     (25.9580, -80.2389),
    "Empower Field at Mile High":           (39.7439, -105.0201),
    "Sports Authority Field at Mile High":  (39.7439, -105.0201),
    "Lumen Field":                          (47.5952, -122.3316),
    "CenturyLink Field":                    (47.5952, -122.3316),
    "Acrisure Stadium":                     (40.4468, -80.0158),
    "Heinz Field":                          (40.4468, -80.0158),
    "Paycor Stadium":                       (39.0955, -84.5161),
    "Paul Brown Stadium":                   (39.0955, -84.5161),
    "GEHA Field at Arrowhead Stadium":      (39.0489, -94.4839),
    "Arrowhead Stadium":                    (39.0489, -94.4839),
    "Highmark Stadium":                     (42.7738, -78.7870),
    "New Era Field":                        (42.7738, -78.7870),
    "Ralph Wilson Stadium":                 (42.7738, -78.7870),
    "Huntington Bank Field":                (41.5061, -81.6995),
    "FirstEnergy Stadium":                  (41.5061, -81.6995),
    "Northwest Stadium":                    (38.9077, -76.8645),
    "FedExField":                           (38.9077, -76.8645),
    "EverBank Stadium":                     (30.3239, -81.6373),
    "EverBank Field":                       (30.3239, -81.6373),
    "TIAA Bank Stadium":                    (30.3239, -81.6373),

    # --- retractable / closed roofs, which still have a location ----------
    "Mercedes-Benz Stadium":                (33.7554, -84.4009),
    "Lucas Oil Stadium":                    (39.7601, -86.1639),
    "NRG Stadium":                          (29.6847, -95.4107),
    "AT&T Stadium":                         (32.7473, -97.0945),
    "State Farm Stadium":                   (33.5276, -112.2626),
    "University of Phoenix Stadium":        (33.5276, -112.2626),

    # --- former US venues --------------------------------------------------
    "Los Angeles Memorial Coliseum":        (34.0141, -118.2879),
    "StubHub Center":                       (33.8644, -118.2611),
    "Oakland-Alameda County Coliseum":      (37.7516, -122.2005),
    "O.co Coliseum":                        (37.7516, -122.2005),
    "Ring Central Coliseum":                (37.7516, -122.2005),
    "Qualcomm Stadium":                     (32.7831, -117.1196),
    "TCF Bank Stadium":                     (44.9764, -93.2247),

    # --- international ------------------------------------------------------
    "Wembley Stadium":                      (51.5560, -0.2795),
    "Tottenham Hotspur Stadium":            (51.6043, -0.0664),
    "Tottenham Stadium":                    (51.6043, -0.0664),
    "Twickenham Stadium":                   (51.4560, -0.3416),
    "Allianz Arena":                        (48.2188, 11.6247),
    "Deutsche Bank Park":                   (50.0686, 8.6455),
    "Azteca Stadium":                       (19.3029, -99.1505),
    "Estadio Banorte":                      (19.3029, -99.1505),
    "Arena Corinthians":                    (-23.5453, -46.4742),
}


def coordinates(stadium: str | None) -> tuple[float, float] | None:
    """Where this stadium is, or None if it is not in the table.

    None is a legitimate answer and must stay one: a venue nobody has mapped
    should yield null weather rather than a plausible guess. Silently
    substituting the home team's usual ground is exactly the failure the
    `stadium_id` key would have caused.
    """
    if not stadium:
        return None
    return STADIUM_COORDS.get(stadium.strip())
