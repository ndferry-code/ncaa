const { getRedis, json } = require("./_redis");

// GET /api/dashboard?week=3   -> everything the frontend needs for a week (or all weeks if omitted)
//
// Returns:
// {
//   games: [...],
//   bets: [...],
//   lineMovement: [ { gameId, hardrock: {open, current, deltaPts, history}, reference: {...}, biggestMover: bool } ],
//   valueComparison: [ { gameId, hardrockSpread, referenceSpread, edgePts, favorsHardrock } ],
//   record: { wins, losses, pushes, winPct, units, byFavoriteUnderdog, byConference, byWeek }
// }

function americanToDecimalPayout(odds) {
  if (odds == null) return 1.909; // -110 default
  return odds > 0 ? odds / 100 : 100 / Math.abs(odds);
}

// Break-even win rate implied by a given American price -- e.g. -110 needs
// 110/210 = 52.38% winners just to break even (the vig).
function americanToBreakevenPct(odds) {
  const o = odds == null ? -110 : odds;
  return o > 0 ? 100 / (100 + o) : Math.abs(o) / (Math.abs(o) + 100);
}

function computeStreak(bets) {
  // Current consecutive win/loss streak, most recent bet first. Pushes are
  // excluded entirely (neither break nor extend a streak) since they're a
  // non-event for this purpose.
  const decided = bets
    .filter((b) => b.result === "win" || b.result === "loss")
    .slice()
    .sort((a, b) => new Date(a.placedAt) - new Date(b.placedAt));
  if (!decided.length) return { type: null, count: 0 };
  const last = decided[decided.length - 1].result;
  let count = 0;
  for (let i = decided.length - 1; i >= 0; i--) {
    if (decided[i].result === last) count++;
    else break;
  }
  return { type: last, count };
}

function computeRecord(bets) {
  const settled = bets.filter((b) => b.result === "win" || b.result === "loss" || b.result === "push");
  const wins = settled.filter((b) => b.result === "win").length;
  const losses = settled.filter((b) => b.result === "loss").length;
  const pushes = settled.filter((b) => b.result === "push").length;
  const decided = wins + losses;
  const winPct = decided > 0 ? wins / decided : null;

  let units = 0;
  for (const b of settled) {
    const stake = b.stake || 1;
    if (b.result === "win") units += stake * americanToDecimalPayout(b.odds);
    else if (b.result === "loss") units -= stake;
  }

  // CLV: did you beat the closing line on average?
  const clvSamples = bets.filter(
    (b) => typeof b.lineAtPlacement === "number" && typeof b.closingLine === "number"
  );
  const avgClv =
    clvSamples.length > 0
      ? clvSamples.reduce((sum, b) => sum + (b.closingLine - b.lineAtPlacement), 0) / clvSamples.length
      : null;

  const byWeek = {};
  for (const b of settled) {
    const wk = b.week != null ? b.week : "unknown"; // week 0 is valid and falsy -- don't let `||` swallow it
    byWeek[wk] = byWeek[wk] || { wins: 0, losses: 0, pushes: 0 };
    byWeek[wk][b.result === "win" ? "wins" : b.result === "loss" ? "losses" : "pushes"] += 1;
  }

  // Break-even target from your actual average price across ALL bets
  // (pending included) -- represents your typical juice, not skewed by
  // which particular bets happened to win. Defaults to -110's 52.38% when
  // there's no data yet.
  const oddsSource = bets.length ? bets : [{ odds: -110 }];
  const breakevenPct =
    oddsSource.reduce((sum, b) => sum + americanToBreakevenPct(b.odds), 0) / oddsSource.length;

  const streak = computeStreak(settled);

  return {
    wins,
    losses,
    pushes,
    winPct,
    units: Math.round(units * 100) / 100,
    avgClv,
    byWeek,
    breakevenPct,
    streak,
  };
}

exports.handler = async (event) => {
  const redis = getRedis();
  const week = event.queryStringParameters && event.queryStringParameters.week;

  try {
    let gameIds;
    if (week) {
      gameIds = await redis.smembers(`week:${week}:games`);
    } else {
      const weeks = await redis.smembers("season:weeks");
      const sets = await Promise.all(weeks.map((w) => redis.smembers(`week:${w}:games`)));
      gameIds = [...new Set(sets.flat())];
    }

    const games = gameIds.length ? (await redis.mget(...gameIds.map((id) => `game:${id}`))).filter(Boolean) : [];

    const allBetIds = await redis.smembers("bets:all");
    const allBets = allBetIds.length ? (await redis.mget(...allBetIds.map((id) => `bet:${id}`))).filter(Boolean) : [];
    const bets = week ? allBets.filter((b) => gameIds.includes(b.gameId)) : allBets;

    const lineMovement = [];
    const valueComparison = [];

    for (const g of games) {
      const [hrLatest, hrHistory, refLatest, refHistory] = await Promise.all([
        redis.get(`lines:hardrock:${g.gameId}:latest`),
        redis.lrange(`lines:hardrock:${g.gameId}:history`, 0, -1),
        redis.get(`lines:reference:${g.gameId}:latest`),
        redis.lrange(`lines:reference:${g.gameId}:history`, 0, -1),
      ]);

      const hrOpen = hrHistory && hrHistory.length ? hrHistory[0].spread : null;
      const hrCurrent = hrLatest ? hrLatest.spread : null;
      const hrDelta = hrOpen != null && hrCurrent != null ? Math.round((hrCurrent - hrOpen) * 10) / 10 : null;

      lineMovement.push({
        gameId: g.gameId,
        hardrock: { open: hrOpen, current: hrCurrent, deltaPts: hrDelta, history: hrHistory || [] },
        reference: {
          open: refHistory && refHistory.length ? refHistory[0].spread : null,
          current: refLatest ? refLatest.spread : null,
          book: refLatest ? refLatest.book : null,
          history: refHistory || [],
        },
      });

      if (hrCurrent != null && refLatest && typeof refLatest.spread === "number") {
        const edge = Math.round((hrCurrent - refLatest.spread) * 10) / 10;
        valueComparison.push({
          gameId: g.gameId,
          hardrockSpread: hrCurrent,
          referenceSpread: refLatest.spread,
          referenceBook: refLatest.book,
          edgePts: edge, // positive = hardrock number is higher (more points to the team getting points)
        });
      }
    }

    // Flag the biggest movers (top 3 by absolute point movement)
    const sortedByMovement = [...lineMovement]
      .filter((m) => m.hardrock.deltaPts != null)
      .sort((a, b) => Math.abs(b.hardrock.deltaPts) - Math.abs(a.hardrock.deltaPts));
    const biggestMoverIds = new Set(sortedByMovement.slice(0, 3).map((m) => m.gameId));
    lineMovement.forEach((m) => (m.biggestMover = biggestMoverIds.has(m.gameId)));

    const record = computeRecord(allBets);

    return json(200, { games, bets, lineMovement, valueComparison, record });
  } catch (err) {
    return json(500, { error: err.message, stack: err.stack });
  }
};
