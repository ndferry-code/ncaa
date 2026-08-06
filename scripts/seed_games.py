"""
Seeds this week's game list into the tracker: every Top 25 matchup, plus a
hand-maintained list of "notable" unranked games you want to include.

Data source: collegefootballdata.com (free tier, 1000 calls/month, plenty for
weekly use). Get a key at https://collegefootballdata.com/key and set it as
the CFBD_API_KEY secret in your GitHub repo.

Run manually:
    CFBD_API_KEY=xxx APP_URL=https://your-site.netlify.app INGEST_TOKEN=xxx \
    python scripts/seed_games.py --year 2026 --week 3

--week is optional. If you omit it, the script asks CFBD's /calendar endpoint
for the season's week date ranges and picks whichever week we're currently
inside (falling back to the most recently *started* week once ranges end,
e.g. during a Sunday/Monday gap between weeks). That's what the GitHub
Actions workflow does every Monday -- no CURRENT_WEEK variable to maintain.

NOTABLE_GAMES below is yours to edit each week for the non-ranked matchups you
want tracked (rivalry games, primetime games, whatever catches your eye).
"""

import argparse
import os
import sys
from datetime import datetime, timezone
import requests

CFBD_BASE = "https://api.collegefootballdata.com"

# Edit this list by hand each week for unranked-but-notable games you want in
# the tracker. Match on (away, home) team names as CFBD spells them.
NOTABLE_GAMES = [
    # ("Colorado", "Nebraska"),
]


def cfbd_get(path, params, api_key):
    resp = requests.get(
        f"{CFBD_BASE}{path}",
        params=params,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def slugify(s):
    return "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")


def get_current_week(year, api_key):
    """
    Figures out the current CFB week from CFBD's /calendar endpoint instead
    of a hand-maintained variable. Returns a regular-season week number, or
    raises if the calendar can't be parsed -- caller should fall back to
    requiring --week explicitly if that happens.
    """
    calendar = cfbd_get("/calendar", {"year": year}, api_key)
    now = datetime.now(timezone.utc)

    weeks = []
    for entry in calendar:
        if entry.get("seasonType") not in ("regular", None):
            continue
        start = entry.get("firstGameStart") or entry.get("first_game_start")
        end = entry.get("lastGameStart") or entry.get("last_game_start")
        week_num = entry.get("week")
        if not (start and week_num is not None):
            continue
        weeks.append(
            {
                "week": week_num,
                "start": datetime.fromisoformat(start.replace("Z", "+00:00")),
                "end": datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None,
            }
        )
    weeks.sort(key=lambda w: w["start"])

    if not weeks:
        raise ValueError("CFBD /calendar returned no usable regular-season weeks")

    # Currently inside a week's game window
    for w in weeks:
        if w["start"] <= now <= (w["end"] or w["start"]):
            return w["week"]

    # Between weeks (e.g. Sun/Mon) -- use the most recent week that's started
    started = [w for w in weeks if w["start"] <= now]
    if started:
        return started[-1]["week"]

    # Season hasn't started yet -- default to week 1
    return weeks[0]["week"]


def build_games(year, week, api_key):
    rankings = cfbd_get(
        "/rankings", {"year": year, "week": week, "seasonType": "regular"}, api_key
    )
    games = cfbd_get(
        "/games",
        {"year": year, "week": week, "seasonType": "regular", "division": "fbs"},
        api_key,
    )

    ap_ranks = {}
    for poll_week in rankings:
        for poll in poll_week.get("polls", []):
            if poll.get("poll") == "AP Top 25":
                for rank in poll.get("ranks", []):
                    ap_ranks[rank["school"]] = rank["rank"]

    out = []
    for g in games:
        away, home = g.get("awayTeam") or g.get("away_team"), g.get("homeTeam") or g.get("home_team")
        if not away or not home:
            continue
        away_rank = ap_ranks.get(away)
        home_rank = ap_ranks.get(home)
        is_notable = (away, home) in NOTABLE_GAMES or (home, away) in NOTABLE_GAMES
        if not (away_rank or home_rank or is_notable):
            continue
        game_id = f"{year}-wk{week}-{slugify(away)}-{slugify(home)}"
        out.append(
            {
                "gameId": game_id,
                "week": week,
                "kickoff": g.get("startDate") or g.get("start_date"),
                "away": away,
                "home": home,
                "apRankAway": away_rank,
                "apRankHome": home_rank,
                "notable": is_notable and not (away_rank or home_rank),
            }
        )
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--week", type=int, default=None, help="Omit to auto-detect from CFBD's calendar")
    args = parser.parse_args()

    cfbd_key = os.environ["CFBD_API_KEY"]
    app_url = os.environ["APP_URL"].rstrip("/")
    ingest_token = os.environ.get("INGEST_TOKEN", "")

    week = args.week
    if week is None:
        week = get_current_week(args.year, cfbd_key)
        print(f"Auto-detected current week: {week}")

    games = build_games(args.year, week, cfbd_key)
    if not games:
        print(f"No ranked/notable games found for {args.year} week {week}")
        sys.exit(0)

    resp = requests.post(
        f"{app_url}/api/games",
        json={"games": games},
        headers={"x-ingest-token": ingest_token, "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Seeded {len(games)} games for week {week}: {resp.json()}")


if __name__ == "__main__":
    main()
