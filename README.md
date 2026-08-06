# CFB ATS Tracker

Tracks your college football bets against the spread for Top 25 + notable
matchups, logs Hard Rock Bet (FL) line movement through the week, compares
Hard Rock's number against the wider market, and surfaces trends from your
settled bets as the season goes on.

Same stack pattern as your other pool apps: **Netlify Functions + Upstash
Redis** for the app, **GitHub Actions** for the scheduled scraping.

## What's here

```
public/                  Frontend (plain HTML/JS, no build step)
netlify/functions/       Serverless API (games, bets, line ingest, dashboard)
scripts/                 Python: seed weekly games, scrape Hard Rock, pull reference odds
.github/workflows/       Scheduled scraper + seeder
```

## 1. Set up Upstash Redis

Reuse your existing Upstash account. Create a new Redis database (free tier
is plenty for a season of CFB data), grab the REST URL and REST token.

## 2. Deploy to Netlify

1. Push this folder to a new GitHub repo.
2. In Netlify: "Add new site" → "Import from Git" → pick the repo. Build
   settings are already in `netlify.toml`, nothing to change.
3. In Site settings → Environment variables, add:
   - `UPSTASH_REDIS_REST_URL`
   - `UPSTASH_REDIS_REST_TOKEN`
   - `INGEST_TOKEN` — make up any random string, this is the shared secret
     your scrapers use to write data (keeps randos off the internet from
     posting fake lines to your public API endpoints).
4. Deploy. Your site URL (e.g. `https://cfb-tracker-nick.netlify.app`) is
   what you'll use as `APP_URL` everywhere below.

## 3. Get your two free API keys

- **CollegeFootballData.com** — free key at collegefootballdata.com/key.
  Used once a week to pull the AP Top 25 and that week's schedule.
- **The Odds API** — free key at the-odds-api.com (500 credits/month free
  tier; this app uses ~1 credit per scheduled run). Used for the "reference"
  line you're comparing Hard Rock against.

## 4. Wire up GitHub Actions

In your repo's Settings → Secrets and variables → Actions:

**Secrets:**
- `APP_URL` — your Netlify site URL
- `INGEST_TOKEN` — same value you set in Netlify
- `CFBD_API_KEY`
- `ODDS_API_KEY`

**Variables:**
- `SEASON_YEAR` — e.g. `2026`
- `CURRENT_WEEK` — bump this by hand each week (simplest option), or wire up
  a date-based calculation later if you want it fully hands-off

The workflow (`.github/workflows/scrape-lines.yml`) scrapes lines every 3
hours Mon–Sat. Adjust the cron schedule to match how often you actually want
snapshots — more often near kickoff if you want tighter CLV tracking.

## 5. Finish the Hard Rock scraper — the one manual step

I couldn't reach hardrockbet.com from where this was built, so
`scripts/scrape_hardrock.py` ships with a **network-capture scraper
skeleton**, not verified selectors. It's set up to do this the reliable way
(read the JSON their app already fetches, rather than scrape brittle HTML),
but you need to point it at the real endpoint once:

1. Run locally: `HEADLESS=false python scripts/scrape_hardrock.py`
   (opens a real browser window) — or just open Hard Rock Bet's CFB page in
   Chrome yourself with DevTools → Network → Fetch/XHR open.
2. Find the request that returns spread data as JSON.
3. Update `ODDS_JSON_URL_PATTERN` and `parse_odds_payload()` in that file to
   match what you see.
4. If there's no clean JSON endpoint, fall back to DOM scraping — there's a
   `scrape_via_dom()` function with a `SELECTORS` dict ready for you to fill
   in from the real page markup.

Full instructions are in the docstring at the top of that file.

## 6. Seed your first week of games

Once secrets are set:

```
CFBD_API_KEY=xxx APP_URL=https://your-site.netlify.app INGEST_TOKEN=xxx \
python scripts/seed_games.py --year 2026 --week 1
```

Add any unranked-but-notable games by hand in `NOTABLE_GAMES` at the top of
`seed_games.py` before running — that's your weekly editorial call on what
counts as "notable."

## 7. Use it

Open your Netlify URL. Pick the week, click "Log bet" on any game to record
your side/spread/odds/stake. The dashboard fills in line movement, Hard
Rock-vs-market value, and your record/CLV/trends as data comes in.

To settle a bet after a game, `POST` to `/api/bets` with the same `gameId`
and add `result: "win" | "loss" | "push"` and `closingLine` — worth wiring a
tiny settle form into the UI later if logging results by hand gets old; the
API already supports it.

## Notes / things to revisit once the season's rolling

- **Insights are intentionally simple to start** (favorite vs. underdog
  split, CLV correlation). Once you've got a few weeks of settled bets, the
  natural next additions are by-conference and by-rank-tier splits — the
  `computeRecord()` function in `netlify/functions/dashboard.js` is the
  place to extend.
- **CLV requires a closing line.** Right now that means noting the last
  Hard Rock snapshot before kickoff and setting it as `closingLine` when you
  settle a bet — could automate by having the scraper flag the last
  pre-kickoff snapshot per game.
- **Redis history is capped at 200 snapshots/game** to keep storage in
  check — plenty for a single game week at a few-hour cadence.
