"""
Scrapes current NCAAF point spreads from Hard Rock Bet (Florida) and pushes
them to the tracker as line snapshots.

IMPORTANT -- READ BEFORE FIRST RUN
-----------------------------------
I can't reach hardrockbet.com from this environment, so the selectors and
the network-capture pattern below are starting points, not verified against
the live site. Sportsbook sites are single-page apps that render odds from
an internal JSON API, which is usually far more reliable to scrape than the
DOM (DOM scraping breaks the moment they ship a CSS change). This script
tries the network-capture approach first. To finish wiring it up:

  1. Run this once with HEADLESS=false to open a real browser window.
  2. Open Hard Rock Bet's NCAAF page yourself in that window, or better: open
     Chrome DevTools > Network > Fetch/XHR on hardrockbet.com's football page
     and find the request that returns spread data as JSON (look for a
     request name like "events", "offers", "markets", or similar).
  3. Copy that request's URL pattern into ODDS_JSON_URL_PATTERN below, and
     update parse_odds_payload() to match the actual JSON shape you see.
  4. If Hard Rock has no clean JSON endpoint, fall back to DOM scraping:
     update the SELECTORS dict with real selectors from the page and use
     scrape_via_dom() instead of scrape_via_network() in main().

Run manually:
    APP_URL=https://your-site.netlify.app INGEST_TOKEN=xxx HEADLESS=false \
    python scripts/scrape_hardrock.py
"""

import json
import os
import re
import requests
from playwright.sync_api import sync_playwright

HARDROCK_NCAAF_URL = "https://app.hardrock.bet/sport/american_football/college_football"  # TODO verify real URL
ODDS_JSON_URL_PATTERN = re.compile(r"(offers|events|markets)", re.IGNORECASE)  # TODO tighten once you find the real endpoint

# Fallback DOM selectors if there's no clean JSON endpoint. TODO: fill these
# in from the real page structure.
SELECTORS = {
    "event_row": "[data-testid='event-row']",
    "team_name": "[data-testid='team-name']",
    "spread_value": "[data-testid='spread-value']",
}


def slugify(s):
    return "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")


def parse_odds_payload(payload):
    """
    TODO: adapt this to Hard Rock's actual JSON shape once you've captured a
    real response. Expected output: list of dicts:
      { "away": "...", "home": "...", "spread": -6.5, "odds": -110 }
    The stub below assumes a generic {"events": [...]} shape as a starting
    guess -- replace with the real field names.
    """
    results = []
    for event in payload.get("events", []):
        try:
            away = event["awayTeam"]["name"]
            home = event["homeTeam"]["name"]
            spread_market = next(
                m for m in event.get("markets", []) if m.get("type", "").lower() == "spread"
            )
            home_outcome = next(
                o for o in spread_market["outcomes"] if o.get("team") == "home"
            )
            results.append(
                {
                    "away": away,
                    "home": home,
                    "spread": home_outcome["line"],
                    "odds": home_outcome.get("price"),
                }
            )
        except (KeyError, StopIteration):
            continue
    return results


def scrape_via_network(page):
    captured = []

    def handle_response(response):
        if ODDS_JSON_URL_PATTERN.search(response.url) and response.status == 200:
            try:
                data = response.json()
                captured.extend(parse_odds_payload(data))
            except Exception:
                pass

    page.on("response", handle_response)
    page.goto(HARDROCK_NCAAF_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(5000)  # let lazy-loaded odds requests fire
    return captured


def scrape_via_dom(page):
    page.goto(HARDROCK_NCAAF_URL, wait_until="networkidle", timeout=60000)
    rows = page.query_selector_all(SELECTORS["event_row"])
    results = []
    for row in rows:
        teams = row.query_selector_all(SELECTORS["team_name"])
        spreads = row.query_selector_all(SELECTORS["spread_value"])
        if len(teams) < 2 or len(spreads) < 1:
            continue
        results.append(
            {
                "away": teams[0].inner_text().strip(),
                "home": teams[1].inner_text().strip(),
                "spread": float(spreads[-1].inner_text().strip().replace("+", "")),
                "odds": None,
            }
        )
    return results


def match_to_known_games(scraped, known_games):
    lookup = {(g["away"].lower(), g["home"].lower()): g["gameId"] for g in known_games}
    snapshots = []
    unmatched = []
    for item in scraped:
        key = (item["away"].lower(), item["home"].lower())
        game_id = lookup.get(key)
        if not game_id:
            unmatched.append(f"{item['away']} @ {item['home']}")
            continue
        snapshots.append({"gameId": game_id, "spread": item["spread"], "odds": item.get("odds")})
    return snapshots, unmatched


def main():
    app_url = os.environ["APP_URL"].rstrip("/")
    ingest_token = os.environ.get("INGEST_TOKEN", "")
    headless = os.environ.get("HEADLESS", "true").lower() != "false"

    games_resp = requests.get(f"{app_url}/api/games", timeout=30)
    games_resp.raise_for_status()
    known_games = games_resp.json().get("games", [])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        scraped = scrape_via_network(page)
        if not scraped:
            print("Network capture found nothing -- falling back to DOM scrape (check selectors).")
            scraped = scrape_via_dom(page)
        browser.close()

    snapshots, unmatched = match_to_known_games(scraped, known_games)

    if snapshots:
        resp = requests.post(
            f"{app_url}/api/lines-ingest",
            json={"source": "hardrock", "book": "hardrock", "snapshots": snapshots},
            headers={"x-ingest-token": ingest_token, "Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        print(f"Pushed {len(snapshots)} Hard Rock lines: {resp.json()}")
    else:
        print("No lines scraped -- see instructions at the top of this file to finish wiring the scraper.")

    if unmatched:
        print(f"Scraped but unmatched to a known game ({len(unmatched)}): {unmatched}")


if __name__ == "__main__":
    main()
