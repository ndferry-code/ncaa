# CFB ATS Tracker

Tracks your college football bets against the spread for Top 25 + notable
matchups, logs Hard Rock Bet (FL) line movement through the week, compares
Hard Rock's number against the wider market, and surfaces trends from your
settled bets as the season goes on.

Same stack pattern as your other pool apps: **Netlify Functions + Upstash
Redis** for the app, **GitHub Actions** for scheduled updates.

**Lines come from The Odds API, not from scraping Hard Rock directly.** The
Odds API already lists Hard Rock Bet as a bookmaker, so one API call gets you
both Hard Rock's actual line and a reference market line (DraftKings by
default) for value comparison — fully automated, no login, no geofencing
issues. Regulated sportsbooks use location-verification services that block
cloud servers outside their licensed state, so scraping the app/site directly
from GitHub Actions would likely have been unreliable at best.

## What's here

```
public/                  Frontend (plain HTML/JS, no build step)
netlify/functions/       Serverless API (games, bets, line ingest, dashboard)
scripts/                 Python: seed weekly games, fetch lines
.github/workflows/       Scheduled updater + seeder
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
     the update script uses to write data (keeps randos off the internet from
     posting fake lines to your public API endpoints).
4. Deploy. Your site URL (e.g. `https://cfb-tracker-nick.netlify.app`) is
   what you'll use as `APP_URL` everywhere below.

## 3. Get your two free API keys

- **CollegeFootballData.com** — free key at collegefootballdata.com/key.
  Used once a week to pull the AP Top 25 and that week's schedule.
- **The Odds API** — free key at the-odds-api.com (500 credits/month free
  tier; this app uses ~2 credits per scheduled run, since it queries both the
  `us` and `us2` regions to cover Hard Rock and the reference book together).
  Used for both the Hard Rock line and the reference line.

## 4. Wire up GitHub Actions

In your repo's Settings → Secrets and variables → Actions:

**Secrets:**
- `APP_URL` — your Netlify site URL
- `INGEST_TOKEN` — same value you set in Netlify
- `CFBD_API_KEY`
- `ODDS_API_KEY`

**Variables:**
- `SEASON_YEAR` — e.g. `2026`

The workflow (`.github/workflows/update-lines.yml`) fetches lines every 3
hours Mon–Sat, and reseeds the week's Top 25 + notable games every Monday.
The current week is auto-detected from CFBD's `/calendar` endpoint — nothing
to update by hand. Adjust the cron schedules to match how often you actually
want snapshots — more often near kickoff if you want tighter CLV tracking.

## 5. Sanity-check the Hard Rock match

The first time `fetch_lines.py` runs, it prints which bookmaker it matched as
"Hard Rock" (e.g. `key='hardrockbet' title='Hard Rock Bet (FL)'`). Check that
log line once — The Odds API lists Hard Rock separately per state, and the
script picks whichever entry has "FL" in the title, preferring that over a
generic "Hard Rock Bet" entry if both appear. If it ever matches the wrong
one, adjust `find_hardrock_book()` in `scripts/fetch_lines.py`.

Trigger a manual run from the Actions tab (`workflow_dispatch`) to see this
without waiting for the next scheduled run.

## 6. Seed your first week of games

Once secrets are set:

```
CFBD_API_KEY=xxx APP_URL=https://your-site.netlify.app INGEST_TOKEN=xxx \
python scripts/seed_games.py --year 2026
```

(Omitting `--week` auto-detects the current week; pass `--week 1` explicitly
if you're backfilling before the season's underway and the calendar hasn't
got a "current" week yet.)

Add any unranked-but-notable games by hand in `NOTABLE_GAMES` at the top of
`seed_games.py` before running — that's your weekly editorial call on what
counts as "notable."

Then pull lines for those games:

```
ODDS_API_KEY=xxx CFBD_API_KEY=xxx APP_URL=https://your-site.netlify.app INGEST_TOKEN=xxx \
python scripts/fetch_lines.py
```

### Early-season note

CFBD sometimes hasn't split "Week 0" from "Week 1" apart in their own data
yet this early in the season — both get tagged under the same week number,
which is fine: the ranked/notable filter applies to the combined batch as
one week either way, so you don't need to think about it. If you ever want
a specific week to include every game regardless of rank (e.g. because the
AP poll isn't out yet and you still want a small early slate fully
tracked), pass `--all-games` for that one run — just know it'll pull in
every FBS game CFBD has for that week number, which can be a big batch once
Week 0 and Week 1 are lumped together.

If you seed before the AP preseason poll is out, expect zero games back
(nothing qualifies as ranked yet) unless you've listed specific games in
`NOTABLE_GAMES`. Re-run the seed once the poll drops and ranks fill in
normally.

### One-time cleanup if you tried the earlier Week 0/Week 1 split

An earlier version of this script split Week 0 out from Week 1 as separate
weeks. That's been removed — they're combined again. If your app still shows
a leftover "Week 0" in the dropdown from that earlier version, clear it out
once:

```
curl -X DELETE "https://your-site.netlify.app/api/games?week=0" \
  -H "x-ingest-token: YOUR_INGEST_TOKEN"
```

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
  settle a bet — could automate by having the update script flag the last
  pre-kickoff snapshot per game.
- **Redis history is capped at 200 snapshots/game** to keep storage in
  check — plenty for a single game week at a few-hour cadence.
- **If Hard Rock ever disappears from The Odds API response** (bookmakers do
  briefly drop out during maintenance, per their docs), that run's Hard Rock
  push is just skipped — you won't get a bad snapshot, just a gap in that
  game's history until the next run picks it back up.
