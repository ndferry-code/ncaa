"""
Seeds this week's game list into the tracker: every Top 25 matchup, plus a
hand-maintained list of "notable" unranked games you want to include.

Data source: collegefootballdata.com (free tier, 1000 calls/month, plenty for
weekly use). Get a key at https://collegefootballdata.com/key and set it as
the CFBD_API_KEY secret in your GitHub repo.

Run manually:
    CFBD_API_KEY=xxx APP_URL=https://your-site.netlify.app INGEST_TOKEN=xxx \
    python scripts/seed_games.py --year 2026 --week 3

--week is optional. If you omit it, the script derives each week's date
window from actual game kickoff times (see get_season_weeks()) and picks
whichever week we're currently inside (falling back to the most recently
*started* week once ranges end, e.g. during a Sunday/Monday gap between
weeks). That's what the GitHub Actions workflow does every Monday -- no
CURRENT_WEEK variable to maintain.

Week 0 (the season's opening week) is handled specially: instead of
filtering to ranked/notable games, it includes EVERY FBS game that week,
since the Week 0 slate is small enough to track in full. This kicks in
automatically whenever the resolved week is the earliest one with any
scheduled games -- no flag needed. Pass --all-games explicitly if you ever
want that same "everything" behavior for a week that wouldn't otherwise
qualify.

NOTABLE_GAMES below is yours to edit each week for the non-ranked matchups you
want tracked (rivalry games, primetime games, whatever catches your eye) --
it only matters for weeks that aren't running in "all games" mode.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
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


def get_season_weeks(year, api_key):
    """
    Derives each week's date window directly from actual game kickoff times,
    rather than CFBD's /calendar endpoint. /calendar's aggregate per-week
    dates can be null this far ahead of the season for weeks whose kickoff
    times aren't finalized yet (Week 0 is the common case) -- which caused
    Week 0 to get silently dropped and Week 1 to look like the season's
    earliest week. Reading dates off individual games instead avoids that.

    Returns [{week, start, end}, ...] sorted by week number.
    """
    games = cfbd_get(
        "/games", {"year": year, "seasonType": "regular", "division": "fbs"}, api_key
    )
    by_week = {}
    for g in games:
        week_num = g.get("week")
        start_raw = g.get("startDate") or g.get("start_date")
        if week_num is None or not start_raw:
            continue
        dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        w = by_week.setdefault(week_num, {"week": week_num, "start": dt, "end": dt})
        if dt < w["start"]:
            w["start"] = dt
        if dt > w["end"]:
            w["end"] = dt
    return sorted(by_week.values(), key=lambda w: w["week"])


def get_current_week(weeks):
    """
    Given get_season_weeks() output, picks whichever week "now" falls
    into (or the most recently started one, or the earliest if the season
    hasn't started yet).
    """
    now = datetime.now(timezone.utc)

    if not weeks:
        raise ValueError("CFBD returned no games with kickoff times for this year yet")

    # Currently inside a week's game window
    for w in weeks:
        if w["start"] <= now <= (w["end"] or w["start"]):
            return w["week"]

    # Between weeks (e.g. Sun/Mon) -- use the most recent week that's started
    started = [w for w in weeks if w["start"] <= now]
    if started:
        return started[-1]["week"]

    # Season hasn't started yet -- default to the earliest week number that
    # actually has games scheduled, whatever CFBD numbers it (0 or 1).
    return weeks[0]["week"]


def get_ap_ranks(year, week, api_key):
    """
    Returns {school: rank} for the AP Top 25 in the given week. Handles two
    CFBD quirks that matter most for Week 0:
      1. Poll name matching is case-insensitive substring match, not exact,
         since preseason polls are sometimes labeled slightly differently.
      2. If the requested week has no AP poll yet (common for Week 0 -- the
         preseason poll is often filed under week 1 instead), this falls
         back to week 1's poll. If even that's empty, it just returns {} --
         meaning ranked games won't show up until the poll is actually out,
         so lean on NOTABLE_GAMES for anything you want tracked before then.
    """
    def ranks_for(w):
        rankings = cfbd_get("/rankings", {"year": year, "week": w, "seasonType": "regular"}, api_key)
        ranks = {}
        for poll_week in rankings:
            for poll in poll_week.get("polls", []):
                if "ap top 25" in poll.get("poll", "").lower():
                    for rank in poll.get("ranks", []):
                        ranks[rank["school"]] = rank["rank"]
        return ranks

    ranks = ranks_for(week)
    if not ranks and week != 1:
        ranks = ranks_for(1)  # preseason poll is often filed under week 1
    return ranks


def build_games(year, week, api_key, include_all=False):
    ap_ranks = get_ap_ranks(year, week, api_key)
    games = cfbd_get(
        "/games",
        {"year": year, "week": week, "seasonType": "regular", "division": "fbs"},
        api_key,
    )

    out = []
    for g in games:
        away, home = g.get("awayTeam") or g.get("away_team"), g.get("homeTeam") or g.get("home_team")
        if not away or not home:
            continue
        away_rank = ap_ranks.get(away)
        home_rank = ap_ranks.get(home)
        is_notable = (away, home) in NOTABLE_GAMES or (home, away) in NOTABLE_GAMES
        if not include_all and not (away_rank or home_rank or is_notable):
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


def split_opening_batch(games, resolved_week, year, gap_hours=48, max_split_days=14):
    """
    CFBD sometimes hasn't split Week 0 from Week 1 yet this early in the
    season -- both get tagged with the same week number, which is why the
    "opening week" batch can come back way oversized (200+ games instead of
    the ~65-70 a normal week has). This detects that: if there's a clear gap
    of `gap_hours`+ between two clusters of kickoff times within the first
    `max_split_days` days, the earlier cluster gets relabeled as Week 0
    (kept in full) and the later cluster reverts to `resolved_week` with the
    normal ranked/notable filter re-applied (since it's not really the
    opening week once split out).

    If no such gap is found, returns games unchanged -- this is a no-op for
    a normal, already-correctly-split week.
    """
    dated = [g for g in games if g.get("kickoff")]
    if len(dated) < 2:
        return games

    dated.sort(key=lambda g: g["kickoff"])
    parsed = [datetime.fromisoformat(g["kickoff"].replace("Z", "+00:00")) for g in dated]

    biggest_gap = timedelta(0)
    split_idx = None
    for i in range(len(parsed) - 1):
        gap = parsed[i + 1] - parsed[i]
        if gap > biggest_gap:
            biggest_gap = gap
            split_idx = i

    if split_idx is None or biggest_gap < timedelta(hours=gap_hours):
        return games  # no clear two-cluster split -- leave as-is
    if parsed[split_idx] - parsed[0] > timedelta(days=max_split_days):
        return games  # gap happens too late to plausibly be a week0/week1 seam

    early_ids = {g["gameId"] for g in dated[: split_idx + 1]}
    print(
        f"Detected an unsplit opening batch: {len(early_ids)} games before a "
        f"{biggest_gap} gap, {len(dated) - len(early_ids)} after. Splitting "
        f"the earlier cluster into Week 0."
    )

    out = []
    for g in games:
        if g["gameId"] in early_ids:
            g["week"] = 0
            g["gameId"] = g["gameId"].replace(f"-wk{resolved_week}-", "-wk0-", 1)
            out.append(g)
        else:
            g["week"] = resolved_week
            # Re-apply the normal ranked/notable filter to the later cluster
            # -- it's genuinely resolved_week now, not the opening week.
            if g["apRankAway"] or g["apRankHome"] or g["notable"]:
                out.append(g)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--week", type=int, default=None, help="Omit to auto-detect from CFBD's calendar")
    parser.add_argument(
        "--all-games",
        action="store_true",
        help="Include every FBS game that week, not just ranked/notable. "
        "Applied automatically for the season's opening week regardless of this flag.",
    )
    args = parser.parse_args()

    cfbd_key = os.environ["CFBD_API_KEY"]
    app_url = os.environ["APP_URL"].rstrip("/")
    ingest_token = os.environ.get("INGEST_TOKEN", "")

    calendar_weeks = get_season_weeks(args.year, cfbd_key)

    week = args.week
    if week is None:
        week = get_current_week(calendar_weeks)
        print(f"Auto-detected current week: {week}")

    is_opening_week = bool(calendar_weeks) and week == calendar_weeks[0]["week"]
    include_all = args.all_games or is_opening_week
    if is_opening_week and not args.all_games:
        print(f"Week {week} is the season's opening week -- including all FBS games, not just ranked/notable.")

    games = build_games(args.year, week, cfbd_key, include_all=include_all)
    if is_opening_week and not args.all_games:
        games = split_opening_batch(games, week, args.year)

    if not games:
        print(f"No games found for {args.year} week {week}.")
        sys.exit(0)

    resp = requests.post(
        f"{app_url}/api/games",
        json={"games": games, "replace": True},
        headers={"x-ingest-token": ingest_token, "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Seeded {len(games)} games for week {week}: {resp.json()}")


if __name__ == "__main__":
    main()
