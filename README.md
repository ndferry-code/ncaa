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

## 3. Get your API keys

- **CollegeFootballData.com** — free key at collegefootballdata.com/key.
  Used once a week to pull the AP Top 25 and that week's schedule.
- **The Odds API** — free key at the-odds-api.com (500 credits/month free
  tier; this app uses ~2 credits per scheduled run, since it queries both the
  `us` and `us2` regions to cover Hard Rock and the reference book together).
  Used for both the Hard Rock line and the reference line.
- **Anthropic API key** (for the Experts & News tab) — console.anthropic.com.
  Unlike everything else in this project, **this one costs real money** —
  it's a paid API, and web search specifically is billed at $10 per 1,000
  searches plus normal token costs. At the volumes here (~25 games/week,
  capped at 6 searches each) that's modest but real ongoing spend. Skip
  this if you don't want the Experts & News tab; the rest of the app works
  fine without it, just with a "no expert content generated yet" state on
  that tab. This is the only extra service needed for that tab — search
  itself runs through Claude's own built-in web search tool, not a
  separate search API.
- **GitHub fine-grained Personal Access Token** (only if you want the
  "Refresh Now" button on the Experts & News tab — the schedule works fine
  without it). GitHub → Settings → Developer settings → Personal access
  tokens → Fine-grained tokens → Generate new token. Restrict it to just
  this repo ("Only select repositories"), and under Repository permissions
  set **Actions: Read and write** (this specific permission — Contents
  alone isn't enough). Copy the token — you won't see it again.

## 4. Wire up GitHub Actions

In your repo's Settings → Secrets and variables → Actions:

**Secrets:**
- `APP_URL` — your Netlify site URL
- `INGEST_TOKEN` — same value you set in Netlify
- `CFBD_API_KEY`
- `ODDS_API_KEY`
- `ANTHROPIC_API_KEY` — only needed for Experts & News

**Variables:**
- `SEASON_YEAR` — e.g. `2026`

Two workflow files:
- `.github/workflows/update-lines.yml` — fetches lines every 3 hours
  Mon–Sat, reseeds the week's Top 25 games every Monday. The current week
  is auto-detected from actual game kickoff times — nothing to update by
  hand. Adjust the cron schedules to match how often you actually want
  snapshots — more often near kickoff if you want tighter CLV tracking.
- `.github/workflows/expert-picks.yml` — pulls expert picks/news every
  Wednesday. Kept as its own workflow (rather than a job in the one above)
  specifically so the site's "Refresh Now" button (next section) can
  trigger just this, without also re-running the lines/games jobs.

## 5. Set up the "Refresh Now" button (optional)

This lets you manually re-trigger the Experts & News research from the site
itself, instead of waiting for Wednesday or going into GitHub's Actions tab.
Skip this section if the weekly schedule is enough for you.

In **Netlify** (Site settings → Environment variables), add:
- `GITHUB_PAT` — the fine-grained personal access token from step 3 (Actions:
  Read and write, scoped to just this repo)
- `GITHUB_REPO` — `yourusername/your-repo-name`

Then open `public/app.js` and replace the placeholder:
```js
const INGEST_TOKEN = "REPLACE_WITH_YOUR_INGEST_TOKEN";
```
with your actual `INGEST_TOKEN` value (same one everywhere else). This is
what lets the button (and bet logging — see the note below) authenticate
its requests. **Be aware this puts the token in your site's public JS
source** — anyone who views page source can see it. For a personal tool
that's a reasonable tradeoff (worst case: someone messes with your bet log,
or triggers an extra expert-picks run, which is separately rate-limited to
once per 15 minutes server-side regardless of the token). Just don't share
this site's URL publicly.

(This same token/header was actually missing from bet logging before now —
if you've been wondering why "Save Bet" didn't seem to do anything, that
was it. Fixed as part of adding this.)

## 6. Sanity-check the Hard Rock match

The first time `fetch_lines.py` runs, it prints which bookmaker it matched as
"Hard Rock" (e.g. `key='hardrockbet' title='Hard Rock Bet (FL)'`). Check that
log line once — The Odds API lists Hard Rock separately per state, and the
script picks whichever entry has "FL" in the title, preferring that over a
generic "Hard Rock Bet" entry if both appear. If it ever matches the wrong
one, adjust `find_hardrock_book()` in `scripts/fetch_lines.py`.

Trigger a manual run from the Actions tab (`workflow_dispatch`) to see this
without waiting for the next scheduled run.

## 7. Seed your first week of games

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

## 8. Use it

Open your Netlify URL. Pick the week, click "Log bet" on any game to record
your side/spread/odds/stake. The dashboard fills in line movement, Hard
Rock-vs-market value, and your record/CLV/trends as data comes in.

To settle a bet after a game, `POST` to `/api/bets` with the same `gameId`
and add `result: "win" | "loss" | "push"` and `closingLine` — worth wiring a
tiny settle form into the UI later if logging results by hand gets old; the
API already supports it.

## Experts & News tab — how it actually works, and its limits

There's no API anywhere that hands you "here's what Chris Fallica, Sam
Panayotovich, and Joel Klatt picked this week." This tab is built by giving
Claude an actual research task per game — genuinely agentic, not a fixed
pipeline: Claude decides what to search for, runs its own built-in web
search tool as many times as it judges useful (capped at 6 per game), and
only then produces a short paraphrased summary, citing a source link and
explicitly saying "no clear pick found" rather than guessing when it
doesn't find one. There's no separate search API in the loop — search runs
server-side as part of the same Claude API call.

**What this means in practice:**
- It's only as good as what's publicly indexed and discoverable by search.
  Podcast-only or video-only picks without a written recap may not surface.
- Search results are a partial window into a full article/video — treat
  the summary as a starting point to click through and verify, not a
  guaranteed-accurate transcript.
- It updates once a week (Wednesday), or on demand via the "Refresh Now"
  button on the site if you've set that up (see step 5). If an expert
  changes their pick later in the week, this won't catch that until the
  next run.
- Cost: this is the one part of the whole project that costs real money per
  run — both the web search tool itself ($10/1,000 searches) and normal
  token costs. Small at this volume, but not free. This is also why
  "Refresh Now" is rate-limited to once per 15 minutes server-side — it's
  a real cost every time it runs, triggered manually or not.

If you ever want to adjust which experts it looks for, or how many searches
it's allowed per game, edit `EXPERTS` / `MAX_SEARCHES_PER_GAME` at the top
of `scripts/fetch_expert_content.py`.

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
