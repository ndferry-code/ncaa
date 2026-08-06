const { getRedis, json, requireAuth } = require("./_redis");

// GET  /api/games?week=3          -> list games for a week
// GET  /api/games                 -> list all games across all weeks
// POST /api/games                 -> upsert one or many games. Body: { games: [...] } or a single game object
// Game shape:
// {
//   gameId: "2026-wk3-osu-uw",       // slugify away@home+week yourself, must be stable all season
//   week: 3,
//   kickoff: "2026-09-19T23:30:00Z",
//   away: "Washington", home: "Ohio State",
//   apRankAway: 14, apRankHome: 2,    // null if unranked
//   notable: false                    // true if you're including it despite being unranked
// }

exports.handler = async (event) => {
  const redis = getRedis();

  if (event.httpMethod === "GET") {
    const week = event.queryStringParameters && event.queryStringParameters.week;
    let gameIds;
    if (week) {
      gameIds = await redis.smembers(`week:${week}:games`);
    } else {
      const weeks = await redis.smembers("season:weeks");
      const sets = await Promise.all(weeks.map((w) => redis.smembers(`week:${w}:games`)));
      gameIds = [...new Set(sets.flat())];
    }
    if (gameIds.length === 0) return json(200, { games: [] });
    const games = await redis.mget(...gameIds.map((id) => `game:${id}`));
    return json(200, { games: games.filter(Boolean) });
  }

  if (event.httpMethod === "POST") {
    if (!requireAuth(event)) return json(401, { error: "unauthorized" });
    const body = JSON.parse(event.body || "{}");
    const games = Array.isArray(body.games) ? body.games : [body];
    for (const g of games) {
      if (!g.gameId || !g.week) continue;
      await redis.set(`game:${g.gameId}`, g);
      await redis.sadd(`week:${g.week}:games`, g.gameId);
      await redis.sadd("season:weeks", String(g.week));
    }
    return json(200, { saved: games.length });
  }

  return json(405, { error: "method not allowed" });
};
