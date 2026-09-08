"""
Automatically settles pending bets once their games are final, using CFBD's
final scores. Grades each bet against the spread you actually took, and
stores the last known Hard Rock line at settlement time as the closing line
(for CLV tracking) if one isn't already set.

Run manually:
    CFBD_API_KEY=xxx APP_URL=https://your-site.netlify.app INGEST_TOKEN=xxx \
    python scripts/settle_bets.py --year 2026

What this can't do: it matches a bet to a team by checking whether
bet["side"] starts with that team's name. This works automatically for
anything logged via the site's quick-pick buttons (the normal path). If you
ever typed a fully custom "side" by hand that doesn't start with either
team's name as CFBD spells it, this skips that bet rather than guessing --
settle it manually from the site instead. The script prints which bets (if
any) it skipped for this reason.
"""

import argparse
import os
import sys
import requests

CFBD_BASE = "https://api.collegefootballdata.com"


def cfbd_get(path, params, api_key):
    resp = requests.get(
        f"{CFBD_BASE}{path}", params=params, headers={"Authorization": f"Bearer {api_key}"}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def check_response(resp):
    if not resp.ok:
        print(f"Request to {resp.url} failed ({resp.status_code}): {resp.text}")
    resp.raise_for_status()


def grade_bet(bet, game, final_scores):
    """Returns "win" | "loss" | "push" | None (None = couldn't confidently
    match the bet's side to a team -- leave for manual settle)."""
    away, home = game["away"], game["home"]
    side = (bet.get("side") or "").strip()

    if side.startswith(away):
        team_score, opp_score = final_scores["away"], final_scores["home"]
    elif side.startswith(home):
        team_score, opp_score = final_scores["home"], final_scores["away"]
    else:
        return None

    result_margin = (team_score - opp_score) + bet["spread"]
    if result_margin > 0:
        return "win"
    if result_margin < 0:
        return "loss"
    return "push"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()

    cfbd_key = os.environ["CFBD_API_KEY"]
    app_url = os.environ["APP_URL"].rstrip("/")
    ingest_token = os.environ.get("INGEST_TOKEN", "")

    bets_resp = requests.get(f"{app_url}/api/bets", timeout=30)
    check_response(bets_resp)
    pending = [b for b in bets_resp.json().get("bets", []) if not b.get("result")]
    if not pending:
        print("No pending bets to settle.")
        sys.exit(0)

    games_resp = requests.get(f"{app_url}/api/games", timeout=30)
    check_response(games_resp)
    games_by_id = {g["gameId"]: g for g in games_resp.json().get("games", [])}

    dashboard_resp = requests.get(f"{app_url}/api/dashboard", timeout=30)
    check_response(dashboard_resp)
    line_movement_by_id = {m["gameId"]: m for m in dashboard_resp.json().get("lineMovement", [])}

    # Group by week so CFBD only gets called once per week actually needed.
    weeks_needed = sorted({games_by_id[b["gameId"]]["week"] for b in pending if b["gameId"] in games_by_id})
    scores_by_week = {}
    for w in weeks_needed:
        cfbd_games = cfbd_get(
            "/games", {"year": args.year, "week": w, "seasonType": "regular", "division": "fbs"}, cfbd_key
        )
        for g in cfbd_games:
            away = g.get("awayTeam") or g.get("away_team")
            home = g.get("homeTeam") or g.get("home_team")
            completed = g.get("completed")
            away_pts = g.get("awayPoints", g.get("away_points"))
            home_pts = g.get("homePoints", g.get("home_points"))
            if completed and away_pts is not None and home_pts is not None:
                scores_by_week.setdefault(w, {})[(away, home)] = {"away": away_pts, "home": home_pts}

    settled, skipped_not_final, skipped_no_match = 0, 0, 0

    for bet in pending:
        game = games_by_id.get(bet["gameId"])
        if not game:
            continue
        final = scores_by_week.get(game["week"], {}).get((game["away"], game["home"]))
        if not final:
            skipped_not_final += 1
            continue

        result = grade_bet(bet, game, final)
        if result is None:
            skipped_no_match += 1
            print(f"  Couldn't match side {bet.get('side')!r} to a team for {game['away']} @ {game['home']} -- settle manually.")
            continue

        lm = line_movement_by_id.get(bet["gameId"])
        closing_line = bet.get("closingLine")
        if closing_line is None and lm and lm["hardrock"]["current"] is not None:
            closing_line = lm["hardrock"]["current"]

        resp = requests.post(
            f"{app_url}/api/bets",
            json={"gameId": bet["gameId"], "result": result, "closingLine": closing_line},
            headers={"x-ingest-token": ingest_token, "Content-Type": "application/json"},
            timeout=30,
        )
        check_response(resp)
        print(f"  Settled {game['away']} @ {game['home']}: {bet.get('side')} -> {result.upper()}")
        settled += 1

    print(f"Settled {settled} bet(s). {skipped_not_final} not final yet, {skipped_no_match} couldn't be auto-matched.")


if __name__ == "__main__":
    main()
