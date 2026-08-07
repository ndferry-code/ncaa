"""
For every currently-seeded (ranked Top 25) game, searches the web for
general news/storylines and for picks from three named handicappers, then
uses Claude to produce a short, grounded summary -- paraphrased, sourced,
and explicit about when no clear pick was found rather than guessing.

Two new services beyond what the rest of this app uses:

1. Google Custom Search JSON API (the actual web search) -- free tier is
   100 queries/day. Get a key + create a Programmable Search Engine at
   https://programmablesearchengine.google.com (when creating it, set it to
   search the entire web, not specific sites). You need both:
     - GOOGLE_CSE_API_KEY
     - GOOGLE_CSE_ID (this is the "cx" value from the search engine's setup page)

2. The Claude API (the summarization step) -- get a key at
   https://console.anthropic.com. This is a paid API; at the game/query
   volumes here (roughly 25 games/week, one Haiku call each) cost is small,
   but it is real ongoing spend, unlike everything else in this project.
     - ANTHROPIC_API_KEY

Run manually:
    GOOGLE_CSE_API_KEY=xxx GOOGLE_CSE_ID=xxx ANTHROPIC_API_KEY=xxx \
    APP_URL=https://your-site.netlify.app INGEST_TOKEN=xxx \
    python scripts/fetch_expert_content.py

Grounding, not guessing: Claude is given only the actual search snippets
retrieved for that game and instructed to state a pick ONLY if it's clearly
evidenced there, citing the source URL, and to say so explicitly when it
isn't -- rather than inferring or fabricating a lean. Treat this as a
starting point to skim with the source links, not a guaranteed-accurate
transcript of what these people actually said -- web search snippets are an
imperfect window into a full article, video, or podcast.
"""

import json
import os
import sys
from datetime import datetime, timezone
import requests

GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

EXPERTS = ["Chris Fallica", "Sam Panayotovich", "Joel Klatt"]


def check_response(resp):
    if not resp.ok:
        print(f"Request to {resp.url} failed ({resp.status_code}): {resp.text}")
    resp.raise_for_status()


def google_search(query, api_key, cx, num=5):
    resp = requests.get(
        GOOGLE_CSE_URL,
        params={"key": api_key, "cx": cx, "q": query, "num": num},
        timeout=30,
    )
    if not resp.ok:
        print(f"Search failed for {query!r}: {resp.status_code} {resp.text}")
        return []
    items = resp.json().get("items", [])
    return [{"title": it.get("title"), "snippet": it.get("snippet"), "url": it.get("link")} for it in items]


def gather_snippets(game, google_key, google_cx):
    away, home = game["away"], game["home"]
    matchup = f"{away} vs {home}"

    news = google_search(f"{away} {home} college football preview injury report", google_key, google_cx)

    expert_results = {}
    for expert in EXPERTS:
        expert_results[expert] = google_search(
            f'"{expert}" pick {away} {home} college football', google_key, google_cx, num=4
        )

    return {"matchup": matchup, "news": news, "experts": expert_results}


def summarize_with_claude(game, snippets, anthropic_key):
    prompt = f"""You are helping summarize public betting/news content for a personal college football tracker. \
Game: {snippets['matchup']}.

Here are web search snippets about general news/storylines for this game:
{json.dumps(snippets['news'], indent=2)}

Here are web search snippets for each named expert's potential pick on this game:
{json.dumps(snippets['experts'], indent=2)}

Produce ONLY a JSON object (no markdown fences, no preamble) with this exact shape:
{{
  "newsSummary": "2-3 sentence paraphrased summary of the current storylines/injuries/context for this game, in your own words. If the snippets have nothing substantive, use an empty string.",
  "picks": [
    {{"expert": "Chris Fallica", "leaning": "<team name>" or null, "note": "<short paraphrased reason, one sentence>" or null, "sourceUrl": "<url>" or null}},
    {{"expert": "Sam Panayotovich", "leaning": ..., "note": ..., "sourceUrl": ...}},
    {{"expert": "Joel Klatt", "leaning": ..., "note": ..., "sourceUrl": ...}}
  ]
}}

Critical rules:
- Only state a "leaning" if it is CLEARLY evidenced in the snippets above for that specific expert and this specific game. If the snippets don't clearly show a pick for an expert, set leaning, note, and sourceUrl to null for them -- do not guess or infer from general team quality.
- Paraphrase everything in your own words. Do not copy sentences verbatim from the snippets.
- "leaning" should be the team name they favor (matching "{away}" or "{home}" as spelled), not a spread number.
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
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    check_response(resp)
    text = resp.json()["content"][0]["text"].strip()
    # Strip accidental markdown fences just in case.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"Could not parse Claude's response as JSON for {snippets['matchup']}: {text[:300]}")
        return {"newsSummary": "", "picks": [{"expert": e, "leaning": None, "note": None, "sourceUrl": None} for e in EXPERTS]}


def main():
    google_key = os.environ["GOOGLE_CSE_API_KEY"]
    google_cx = os.environ["GOOGLE_CSE_ID"]
    anthropic_key = os.environ["ANTHROPIC_API_KEY"]
    app_url = os.environ["APP_URL"].rstrip("/")
    ingest_token = os.environ.get("INGEST_TOKEN", "")

    games_resp = requests.get(f"{app_url}/api/games", timeout=30)
    check_response(games_resp)
    all_games = games_resp.json().get("games", [])
    if not all_games:
        print("No games seeded yet -- nothing to search for.")
        sys.exit(0)

    # Current week = whichever week has the most games right now (mirrors
    # what the dashboard defaults to). Pass a specific week via a small
    # edit here if you ever need to backfill a different one.
    weeks_present = sorted(set(g["week"] for g in all_games))
    week = weeks_present[-1]
    games = [g for g in all_games if g["week"] == week]
    print(f"Fetching expert content for week {week} ({len(games)} games)")

    items = []
    for g in games:
        print(f"  {g['away']} @ {g['home']}...")
        snippets = gather_snippets(g, google_key, google_cx)
        summary = summarize_with_claude(g, snippets, anthropic_key)
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
