"""
Pulls current NCAAF spreads from The Odds API and pushes TWO snapshots per
game to the tracker: Hard Rock Bet's actual line, and a reference market line
for value comparison. One API call, no browser, no login, no geofencing --
The Odds API carries Hard Rock Bet as a bookmaker directly.

This replaces the earlier scrape_hardrock.py approach. Scraping the Hard Rock
app/site directly turned out to be the wrong path for two reasons:
  1. It's a regulated real-money sportsbook -- these use location-verification
     services (GeoComply and similar) that specifically detect and block
     cloud servers / VPNs / anything not physically in-state. A GitHub
     Actions runner is never going to look like it's in Florida, so an
     automated scraper would likely get blocked regardless of app vs. web.
  2. Trying to spoof that verification would mean deliberately circumventing
     a regulated gambling platform's compliance system -- not something worth
     doing even if it were technically possible, given the risk to your
     account. Pulling the same number from a licensed odds aggregator instead
     sidesteps the problem entirely.

Get a free key at https://the-odds-api.com (500 free credits/month; this
script uses 1 credit per run since it's a single market/single sport call --
run it every few hours during game week, not more).

Run manually:
    ODDS_API_KEY=xxx APP_URL=https://your-site.netlify.app INGEST_TOKEN=xxx \
    python scripts/fetch_lines.py

Team-name matching: The Odds API returns full names with mascots (e.g.
"Ohio State Buckeyes"), while CFBD -- and therefore your seeded games --
use short school names (e.g. "Ohio State"). This script resolves that by
longest-prefix matching each Odds API name against every team name already
in your seeded games: "Ohio State Buckeyes" matches candidate "Ohio State"
at a word boundary, and if two candidates could both match (e.g. "Miami"
and "Miami (OH)" against "Miami (OH) RedHawks"), the longer/more specific
one wins. No hardcoded alias list needed for the general case -- it self-
resolves from whatever short names CFBD already gave your games. Add entries
to TEAM_ALIASES below only for the rare case where prefix matching still
doesn't line up.

Bookmaker key: The Odds API's widget lists Hard Rock Bet separately per
state ("Hard Rock Bet", "Hard Rock Bet (FL)", etc). Rather than hardcode a
key that might be wrong, this script scans every bookmaker on each event for
one whose title contains "Hard Rock" and prefers one with "FL" in the name
if more than one shows up. First run will print exactly which bookmaker
key/title it matched -- sanity check that against your app once and you're
done.
"""

import os
import requests

ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"

# Reference book for value comparison -- pick whichever major book you want
# Hard Rock's number compared against. Falls back to the first non-Hard-Rock
# book in the response if this key isn't present for a given game.
REFERENCE_BOOK_KEY = "draftkings"

# Add entries here only if longest-prefix matching still doesn't resolve a
# specific team correctly (e.g. Odds API uses a genuinely different school
# name, not just school+mascot). Key is the Odds API's exact team string.
TEAM_ALIASES = {
    # "Ole Miss Rebels": "Ole Miss",
}


def build_team_resolver(known_games):
    """
    Builds a resolver that maps an Odds API team name (school + mascot) back
    to whichever short school name CFBD used when the game was seeded, via
    longest-prefix matching at a word boundary. Returns a function
    resolve(odds_team_name) -> short_name or None.
    """
    candidates = set()
    for g in known_games:
        candidates.add(g["away"])
        candidates.add(g["home"])
    # Longest first, so "Miami (OH)" is tried before the shorter "Miami"
    # when matching "Miami (OH) RedHawks" -- prevents the more specific
    # school from being shadowed by a shorter, coincidentally-matching one.
    candidates = sorted(candidates, key=len, reverse=True)

    def resolve(odds_name):
        if odds_name in TEAM_ALIASES:
            return TEAM_ALIASES[odds_name]
        name_lower = odds_name.strip().lower()
        for cand in candidates:
            cand_lower = cand.strip().lower()
            if name_lower == cand_lower:
                return cand
            if name_lower.startswith(cand_lower + " ") or name_lower.startswith(cand_lower + "-"):
                return cand
        return None

    return resolve


def fetch_odds_api_games(api_key):
    resp = requests.get(
        ODDS_API_BASE,
        params={
            # us2 is where Hard Rock Bet lives; us covers DraftKings/FanDuel/etc
            # for the reference line. Costs 2 "regions" worth of credits.
            "regions": "us,us2",
            "markets": "spreads",
            "oddsFormat": "american",
            "apiKey": api_key,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def find_hardrock_book(bookmakers):
    candidates = [bm for bm in bookmakers if "hard rock" in bm.get("title", "").lower()]
    if not candidates:
        return None
    fl = [bm for bm in candidates if "fl" in bm.get("title", "").lower()]
    return (fl or candidates)[0]


def find_reference_book(bookmakers, hardrock_key):
    for bm in bookmakers:
        if bm.get("key") == REFERENCE_BOOK_KEY:
            return bm
    for bm in bookmakers:
        if bm.get("key") != hardrock_key:
            return bm
    return None


def spread_for_home(market, home_team):
    outcome = next((o for o in market.get("outcomes", []) if o["name"] == home_team), None)
    return outcome


def main():
    odds_api_key = os.environ["ODDS_API_KEY"]
    app_url = os.environ["APP_URL"].rstrip("/")
    ingest_token = os.environ.get("INGEST_TOKEN", "")

    games_resp = requests.get(f"{app_url}/api/games", timeout=30)
    games_resp.raise_for_status()
    known_games = games_resp.json().get("games", [])
    resolve_team = build_team_resolver(known_games)
    lookup = {(g["away"].lower(), g["home"].lower()): g["gameId"] for g in known_games}

    events = fetch_odds_api_games(odds_api_key)

    hardrock_snapshots = []
    reference_snapshots = []
    unmatched = []
    reference_book_seen = None
    printed_hardrock_match = False

    for ev in events:
        away_raw, home_raw = ev.get("away_team"), ev.get("home_team")
        away_short = resolve_team(away_raw) if away_raw else None
        home_short = resolve_team(home_raw) if home_raw else None
        home = home_raw  # outcome names in the odds payload use the full Odds API name
        game_id = lookup.get((away_short.lower(), home_short.lower())) if away_short and home_short else None
        if not game_id:
            unmatched.append(f"{away_raw} @ {home_raw}")
            continue

        bookmakers = ev.get("bookmakers", [])
        hr_book = find_hardrock_book(bookmakers)
        if hr_book and not printed_hardrock_match:
            print(f"Matched Hard Rock bookmaker: key='{hr_book['key']}' title='{hr_book['title']}'")
            printed_hardrock_match = True

        ref_book = find_reference_book(bookmakers, hr_book["key"] if hr_book else None)
        if ref_book:
            reference_book_seen = ref_book["key"]

        commence_time = ev.get("commence_time")

        if hr_book:
            spreads_market = next((m for m in hr_book.get("markets", []) if m["key"] == "spreads"), None)
            if spreads_market:
                outcome = spread_for_home(spreads_market, home)
                if outcome:
                    hardrock_snapshots.append(
                        {"gameId": game_id, "spread": outcome["point"], "odds": outcome.get("price"), "ts": commence_time}
                    )

        if ref_book:
            spreads_market = next((m for m in ref_book.get("markets", []) if m["key"] == "spreads"), None)
            if spreads_market:
                outcome = spread_for_home(spreads_market, home)
                if outcome:
                    reference_snapshots.append(
                        {"gameId": game_id, "spread": outcome["point"], "odds": outcome.get("price"), "ts": commence_time}
                    )

    if hardrock_snapshots:
        resp = requests.post(
            f"{app_url}/api/lines-ingest",
            json={"source": "hardrock", "book": "hardrockbet", "snapshots": hardrock_snapshots},
            headers={"x-ingest-token": ingest_token, "Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"Pushed {len(hardrock_snapshots)} Hard Rock lines: {resp.json()}")
    else:
        print("No Hard Rock lines found in this response -- Hard Rock may be temporarily unlisted, or check the bookmaker title match above.")

    if reference_snapshots:
        resp = requests.post(
            f"{app_url}/api/lines-ingest",
            json={"source": "reference", "book": reference_book_seen or REFERENCE_BOOK_KEY, "snapshots": reference_snapshots},
            headers={"x-ingest-token": ingest_token, "Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"Pushed {len(reference_snapshots)} reference lines: {resp.json()}")

    if unmatched:
        print(f"Unmatched games ({len(unmatched)}) -- check TEAM_ALIASES: {unmatched}")


if __name__ == "__main__":
    main()
