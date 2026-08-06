"""
Pulls current NCAAF spreads from The Odds API (multi-book consensus) and
pushes them to the tracker as the "reference" line for value comparison
against your Hard Rock number.

Get a free key at https://the-odds-api.com (500 free credits/month; this
script uses 1 credit per run since it's a single market/single sport call --
run it every few hours during game week, not more).

Run manually:
    ODDS_API_KEY=xxx APP_URL=https://your-site.netlify.app INGEST_TOKEN=xxx \
    python scripts/fetch_reference_odds.py

Team-name matching: The Odds API and CFBD spell team names slightly
differently sometimes (e.g. "Ohio State Buckeyes" vs "Ohio State"). This
script does a loose match; check the printed "unmatched" list after each run
and extend TEAM_ALIASES below if a game isn't lining up.
"""

import os
import requests

ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"

# Preferred book to use as "the reference" -- pick whichever sharp/major book
# you want Hard Rock compared against. DraftKings and Pinnacle (via us_ex or
# similar regions) are common choices. Falls back to the first book returned
# if your preferred key isn't present for a given game.
PREFERRED_BOOK = "draftkings"

# Add entries here if team names don't match between The Odds API and CFBD.
TEAM_ALIASES = {
    # "Ohio State Buckeyes": "Ohio State",
}


def normalize(name):
    return TEAM_ALIASES.get(name, name).strip().lower()


def slugify(s):
    return "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")


def fetch_odds_api_games(api_key):
    resp = requests.get(
        ODDS_API_BASE,
        params={
            "regions": "us",
            "markets": "spreads",
            "oddsFormat": "american",
            "apiKey": api_key,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def pick_book(bookmakers):
    for bm in bookmakers:
        if bm.get("key") == PREFERRED_BOOK:
            return bm
    return bookmakers[0] if bookmakers else None


def main():
    odds_api_key = os.environ["ODDS_API_KEY"]
    app_url = os.environ["APP_URL"].rstrip("/")
    ingest_token = os.environ.get("INGEST_TOKEN", "")

    # Pull the current game list from the app so we can map Odds API events
    # to your existing gameId scheme by team names.
    games_resp = requests.get(f"{app_url}/api/games", timeout=30)
    games_resp.raise_for_status()
    known_games = games_resp.json().get("games", [])
    lookup = {(normalize(g["away"]), normalize(g["home"])): g["gameId"] for g in known_games}

    events = fetch_odds_api_games(odds_api_key)
    snapshots = []
    unmatched = []

    for ev in events:
        away, home = ev.get("away_team"), ev.get("home_team")
        game_id = lookup.get((normalize(away), normalize(home)))
        if not game_id:
            unmatched.append(f"{away} @ {home}")
            continue

        book = pick_book(ev.get("bookmakers", []))
        if not book:
            continue
        spreads_market = next((m for m in book.get("markets", []) if m["key"] == "spreads"), None)
        if not spreads_market:
            continue
        home_outcome = next((o for o in spreads_market["outcomes"] if o["name"] == home), None)
        if not home_outcome:
            continue

        snapshots.append(
            {
                "gameId": game_id,
                "spread": home_outcome["point"],
                "odds": home_outcome.get("price"),
                "ts": ev.get("commence_time"),
            }
        )

    if snapshots:
        resp = requests.post(
            f"{app_url}/api/lines-ingest",
            json={"source": "reference", "book": PREFERRED_BOOK, "snapshots": snapshots},
            headers={"x-ingest-token": ingest_token, "Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"Pushed {len(snapshots)} reference lines: {resp.json()}")

    if unmatched:
        print(f"Unmatched games ({len(unmatched)}) -- check TEAM_ALIASES: {unmatched}")


if __name__ == "__main__":
    main()
