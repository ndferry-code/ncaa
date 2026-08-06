const { getRedis, json, requireAuth } = require("./_redis");

// GET  /api/games?week=3          -> list games for a week
// GET  /api/games                 -> list all games across all weeks
// POST /api/games                 -> upsert one or many games. Body: { games: [...], replace: true } or a single game object
// DELETE /api/games?week=0        -> remove an entire week's games (e.g. cleaning up after a schema/behavior change)
// `replace: true` fully replaces that week's game list with exactly what's
// sent (used by the weekly reseed script). Omit it for a one-off addition --
// then games are just added/updated, nothing existing gets removed.
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

  try {
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

      // Week 0 is a valid week number, but `0` is falsy in JS -- a naive
      // `!g.week` check silently drops every single Week 0 game. Check for
      // presence explicitly instead.
      const valid = games.filter((g) => g.gameId && g.week !== undefined && g.week !== null);

      if (body.replace) {
        // Full replace per week: re-seeding a week should make Redis match
        // exactly what was just sent, not accumulate stale entries forever
        // (e.g. a game that no longer qualifies once rankings update).
        const weeksInPayload = [...new Set(valid.map((g) => g.week))];
        for (const w of weeksInPayload) {
          const newIdsForWeek = valid.filter((g) => g.week === w).map((g) => g.gameId);
          const existingIds = await redis.smembers(`week:${w}:games`);
          const staleIds = existingIds.filter((id) => !newIdsForWeek.includes(id));
          if (staleIds.length) {
            await redis.srem(`week:${w}:games`, ...staleIds);
            await redis.del(...staleIds.map((id) => `game:${id}`));
          }
        }
      }

      for (const g of valid) {
        await redis.set(`game:${g.gameId}`, g);
        await redis.sadd(`week:${g.week}:games`, g.gameId);
        await redis.sadd("season:weeks", String(g.week));
      }
      return json(200, { saved: valid.length, removed: games.length - valid.length });
    }

    if (event.httpMethod === "DELETE") {
      if (!requireAuth(event)) return json(401, { error: "unauthorized" });
      const week = event.queryStringParameters && event.queryStringParameters.week;
      if (week === undefined || week === null) return json(400, { error: "week query param required" });
      const ids = await redis.smembers(`week:${week}:games`);
      if (ids.length) {
        await redis.del(...ids.map((id) => `game:${id}`));
        await redis.del(`week:${week}:games`);
      }
      await redis.srem("season:weeks", String(week));
      return json(200, { deletedWeek: week, removedGames: ids.length });
    }

    return json(405, { error: "method not allowed" });
  } catch (err) {
    // Surface the real error instead of a bare 500 -- callers (curl, the
    // Python scripts) print the response body on failure, so this shows up
    // directly instead of requiring a trip to the Netlify function logs.
    return json(500, { error: err.message, stack: err.stack });
  }
};
