const { getRedis, json, requireAuth } = require("./_redis");

// GET  /api/expert-picks?week=3    -> list of {gameId, newsSummary, picks, generatedAt} for that week
// POST /api/expert-picks           -> upsert. Body: { week, items: [...], replace: true }
//
// Item shape:
// {
//   gameId: "2026-wk3-osu-uw",
//   newsSummary: "2-3 sentence paraphrased summary of current storylines/injuries",
//   picks: [
//     { expert: "Chris Fallica", leaning: "Ohio State" | null, note: "short reason or null", sourceUrl: "..." | null },
//     { expert: "Sam Panayotovich", ... },
//     { expert: "Joel Klatt", ... }
//   ],
//   generatedAt: "2026-09-18T14:00:00Z"
// }
//
// `replace: true` fully replaces that week's set of picks (used by the
// weekly fetch script) rather than only ever adding to it.

exports.handler = async (event) => {
  const redis = getRedis();

  try {
    if (event.httpMethod === "GET") {
      const week = event.queryStringParameters && event.queryStringParameters.week;
      if (week === undefined || week === null) return json(400, { error: "week query param required" });
      const gameIds = await redis.smembers(`week:${week}:experts`);
      if (gameIds.length === 0) return json(200, { picks: [] });
      const items = await redis.mget(...gameIds.map((id) => `experts:${week}:${id}`));
      return json(200, { picks: items.filter(Boolean) });
    }

    if (event.httpMethod === "POST") {
      if (!requireAuth(event)) return json(401, { error: "unauthorized" });
      const body = JSON.parse(event.body || "{}");
      const week = body.week;
      if (week === undefined || week === null) return json(400, { error: "week required" });
      const items = Array.isArray(body.items) ? body.items : [];
      const valid = items.filter((it) => it.gameId);

      if (body.replace) {
        const newIds = valid.map((it) => it.gameId);
        const existingIds = await redis.smembers(`week:${week}:experts`);
        const staleIds = existingIds.filter((id) => !newIds.includes(id));
        if (staleIds.length) {
          await redis.srem(`week:${week}:experts`, ...staleIds);
          await redis.del(...staleIds.map((id) => `experts:${week}:${id}`));
        }
      }

      for (const it of valid) {
        await redis.set(`experts:${week}:${it.gameId}`, it);
        await redis.sadd(`week:${week}:experts`, it.gameId);
      }
      return json(200, { saved: valid.length });
    }

    return json(405, { error: "method not allowed" });
  } catch (err) {
    return json(500, { error: err.message, stack: err.stack });
  }
};
