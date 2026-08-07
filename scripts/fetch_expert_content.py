"""
For every currently-seeded (ranked Top 25) game, uses Claude's built-in
agentic web search tool to research news/storylines and picks from three
named handicappers, producing a short, grounded summary -- paraphrased,
sourced, and explicit about when no clear pick was found rather than
guessing.

This is genuinely agentic, not a fixed pipeline: Claude decides what to
search for, how many searches to run (up to the cap below), and when it's
found enough -- rather than this script handing it a rigid set of canned
queries. The web search itself runs server-side as part of the same API
call; there's no separate search API to wire up.

One service beyond what the rest of this app uses:

  Anthropic API key -- get one at https://console.anthropic.com. This is a
  paid API; web search specifically is billed at $10 per 1,000 searches
  plus normal token costs for what Claude reads. At the volumes here
  (~25 games/week, capped at MAX_SEARCHES_PER_GAME searches each) that's
  real but modest ongoing spend -- unlike everything else in this project,
  which is free.
    - ANTHROPIC_API_KEY

Run manually:
    ANTHROPIC_API_KEY=xxx APP_URL=https://your-site.netlify.app INGEST_TOKEN=xxx \
    python scripts/fetch_expert_content.py

Grounding, not guessing: Claude is instructed to state a pick ONLY if it's
clearly evidenced in what it actually found via search, citing the source
URL, and to say so explicitly when it isn't -- rather than inferring or
fabricating a lean from general team quality. Treat this as a starting
point to skim with the source links, not a guaranteed-accurate transcript
of what these people actually said -- web search results are an imperfect
window into a full article, video, or podcast.
"""

import json
import os
import sys
from datetime import datetime, timezone
import requests

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
MAX_SEARCHES_PER_GAME = 6

EXPERTS = ["Chris Fallica", "Sam Panayotovich", "Joel Klatt"]


def check_response(resp):
    if not resp.ok:
        print(f"Request to {resp.url} failed ({resp.status_code}): {resp.text}")
    resp.raise_for_status()


def research_game(game, anthropic_key):
    away, home = game["away"], game["home"]
    matchup = f"{away} vs {home}"

    prompt = f"""You're researching the college football game {matchup} for a personal betting tracker.

Use web search (you have up to {MAX_SEARCHES_PER_GAME} searches -- use as many or as few as you actually need) to find:
1. Current news, storylines, and injury reports for this specific matchup.
2. Whether these three specific people have stated a pick/lean for this specific game: {", ".join(EXPERTS)}. Search for each by name along with the two teams.

Once you've searched enough, respond with ONLY a JSON object (no markdown fences, no preamble, no text after it) in exactly this shape:
{{
  "newsSummary": "2-3 sentence paraphrased summary of current storylines/injuries/context for this game, in your own words. Empty string if you found nothing substantive.",
  "picks": [
    {{"expert": "Chris Fallica", "leaning": "<team name>" or null, "note": "<short paraphrased reason, one sentence>" or null, "sourceUrl": "<url>" or null}},
    {{"expert": "Sam Panayotovich", "leaning": ..., "note": ..., "sourceUrl": ...}},
    {{"expert": "Joel Klatt", "leaning": ..., "note": ..., "sourceUrl": ...}}
  ]
}}

Critical rules:
- Only state a "leaning" if you found it CLEARLY stated by that specific person for this specific game. If you didn't find a clear pick for someone, set their leaning, note, and sourceUrl to null -- do not guess or infer from general team quality or your own opinion.
- Paraphrase everything in your own words. Do not copy sentences verbatim from what you find.
- "leaning" should be the team name they favor (matching "{away}" or "{home}" as spelled), not a spread number.
- Your final message must be ONLY the JSON object -- no other text before or after it.
"""

    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": anthropic_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES_PER_GAME}],
        },
        timeout=120,
    )
    check_response(resp)
    body = resp.json()

    # The web_search tool runs server-side within this same response --
    # content can include search_result/tool_use blocks interspersed with
    # text blocks (e.g. reasoning between search rounds). Concatenate just
    # the text blocks in order to get Claude's actual final answer.
    text = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text").strip()

    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: sometimes a stray sentence sneaks in around the JSON
        # despite instructions -- try to pull out just the {...} block.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        print(f"Could not parse Claude's response as JSON for {matchup}: {text[:300]}")
        return {"newsSummary": "", "picks": [{"expert": e, "leaning": None, "note": None, "sourceUrl": None} for e in EXPERTS]}


def main():
    anthropic_key = os.environ["ANTHROPIC_API_KEY"]
    app_url = os.environ["APP_URL"].rstrip("/")
    ingest_token = os.environ.get("INGEST_TOKEN", "")

    games_resp = requests.get(f"{app_url}/api/games", timeout=30)
    check_response(games_resp)
    all_games = games_resp.json().get("games", [])
    if not all_games:
        print("No games seeded yet -- nothing to research.")
        sys.exit(0)

    # Current week = whichever week has the most games right now (mirrors
    # what the dashboard defaults to). Pass a specific week via a small
    # edit here if you ever need to backfill a different one.
    weeks_present = sorted(set(g["week"] for g in all_games))
    week = weeks_present[-1]
    games = [g for g in all_games if g["week"] == week]
    print(f"Researching expert picks for week {week} ({len(games)} games)")

    items = []
    for g in games:
        print(f"  {g['away']} @ {g['home']}...")
        summary = research_game(g, anthropic_key)
        items.append(
            {
                "gameId": g["gameId"],
                "newsSummary": summary.get("newsSummary", ""),
                "picks": summary.get("picks", []),
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

    resp = requests.post(
        f"{app_url}/api/expert-picks",
        json={"week": week, "items": items, "replace": True},
        headers={"x-ingest-token": ingest_token, "Content-Type": "application/json"},
        timeout=30,
    )
    check_response(resp)
    print(f"Saved expert content for {len(items)} games: {resp.json()}")


if __name__ == "__main__":
    main()
