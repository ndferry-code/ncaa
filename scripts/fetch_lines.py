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
use short school names (e.g. "Ohio State"). This resolves that using CFBD's
own /teams list (school + mascot, covering every division) as the source of
truth: "Ohio State Buckeyes" exact-matches CFBD's own "Ohio State" + "Buckeyes"
and resolves to "Ohio State" precisely.

This used to be done by prefix-matching against only the teams in your
seeded games, which had a real bug: "Idaho" (seeded, ranked) and "Idaho
State" (unseeded, unranked) are different schools, but since "Idaho State"
wasn't in the candidate pool, "Idaho State Bengals" incorrectly matched the
shorter "Idaho" -- silently overwriting the real Idaho @ Utah line with the
wrong game's spread. Using CFBD's full team list instead of a partial one
avoids that: "Idaho State Bengals" now resolves to "Idaho State", which
correctly doesn't match anything in your (ranked-only) seeded games, so
it's skipped instead of corrupting an unrelated game.

The old prefix-matching against seeded games is kept as a fallback only,
for the rare case a team isn't found in CFBD's team list at all.

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
CFBD_TEAMS_URL = "https://api.collegefootballdata.com/teams"

# Reference book for value comparison -- pick whichever major book you want
# Hard Rock's number compared against. Falls back to the first non-Hard-Rock
# book in the response if this key isn't present for a given game.
REFERENCE_BOOK_KEY = "draftkings"

# Add entries here only if CFBD's team list still doesn't resolve a specific
# team correctly (e.g. Odds API uses a genuinely different name). Key is the
# Odds API's exact team string.
TEAM_ALIASES = {
    # "Ole Miss Rebels": "Ole Miss",
}


def fetch_cfbd_team_map(cfbd_api_key):
    """
    Builds {"school mascot" (lowercase): "school"} from CFBD's full team
    list -- the authoritative source for turning an Odds-API-style full name
    ("Idaho State Bengals") back into CFBD's short school name ("Idaho
    State"), covering every division so it can't be confused with a
    similarly-prefixed but different school.
    """
    resp = requests.get(
        CFBD_TEAMS_URL, headers={"Authorization": f"Bearer {cfbd_api_key}"}, timeout=30
    )
    resp.raise_for_status()
    team_map = {}
    for t in resp.json():
        school = t.get("school")
        mascot = t.get("mascot")
        if not school:
            continue
        team_map[school.strip().lower()] = school
        if mascot:
            team_map[f"{school} {mascot}".strip().lower()] = school
    return team_map


def build_team_resolver(known_games, cfbd_team_map):
    """
    Returns resolve(odds_team_name) -> short_name or None. Tries, in order:
      1. TEAM_ALIASES exact override.
      2. Exact match against CFBD's full team list (school+mascot) -- the
         precise, authoritative path.
      3. Longest-prefix match against your seeded games' team names, as a
         fallback for the rare team CFBD's list doesn't cover cleanly.
    """
    candidates = set()
    for g in known_games:
        candidates.add(g["away"])
        candidates.add(g["home"])
    candidates = sorted(candidates, key=len, reverse=True)

    def resolve(odds_name):
        if odds_name in TEAM_ALIASES:
            return TEAM_ALIASES[odds_name]

        name_lower = odds_name.strip().lower()

        if name_lower in cfbd_team_map:
            return cfbd_team_map[name_lower]

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


def check_response(resp):
    """Like resp.raise_for_status(), but prints the response body first --
    our own API functions return {"error": "...", "stack": "..."} on failure,
    which is far more useful in the Action log than a bare status line."""
    if not resp.ok:
        print(f"Request to {resp.url} failed ({resp.status_code}): {resp.text}")
    resp.raise_for_status()


def main():
    odds_api_key = os.environ["ODDS_API_KEY"]
    cfbd_api_key = os.environ["CFBD_API_KEY"]
    app_url = os.environ["APP_URL"].rstrip("/")
    ingest_token = os.environ.get("INGEST_TOKEN", "")

    games_resp = requests.get(f"{app_url}/api/games", timeout=30)
    check_response(games_resp)
    known_games = games_resp.json().get("games", [])
    cfbd_team_map = fetch_cfbd_team_map(cfbd_api_key)
    resolve_team = build_team_resolver(known_games, cfbd_team_map)
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
        check_response(resp)
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
        check_response(resp)
        print(f"Pushed {len(reference_snapshots)} reference lines: {resp.json()}")

    if unmatched:
        print(f"Unmatched games ({len(unmatched)}) -- check TEAM_ALIASES: {unmatched}")


if __name__ == "__main__":
    main()
