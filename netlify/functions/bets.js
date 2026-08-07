const { getRedis, json, requireAuth } = require("./_redis");

// GET   /api/bets                 -> all bets
// POST  /api/bets                 -> create or update a bet. Body: partial or full bet object (see shape below).
//                                     Merges onto any existing bet with the same gameId -- so settling a bet
//                                     (e.g. { gameId, result: "win", closingLine: -5.5 }) doesn't clobber the
//                                     side/spread/odds/stake you originally logged.
// DELETE /api/bets?gameId=xxx     -> remove a bet
//
// Bet shape:
// {
//   gameId: "2026-wk3-osu-uw",
//   side: "Ohio State -6.5",     // human readable side you took
//   spread: -6.5,
//   odds: -110,
//   stake: 100,                  // units or $, your call - just be consistent
//   placedAt: "2026-09-17T14:00:00Z",
//   lineAtPlacement: -6.5,       // hard rock line when you bet, for CLV tracking
//   closingLine: null,           // filled in later once you know the closing number
//   result: null,                // "win" | "loss" | "push" | null (pending)
//   notes: ""
// }

exports.handler = async (event) => {
  const redis = getRedis();

  try {
    if (event.httpMethod === "GET") {
      const ids = await redis.smembers("bets:all");
      if (ids.length === 0) return json(200, { bets: [] });
      const bets = await redis.mget(...ids.map((id) => `bet:${id}`));
      return json(200, { bets: bets.filter(Boolean) });
    }

    if (event.httpMethod === "POST") {
      if (!requireAuth(event)) return json(401, { error: "unauthorized" });
      const incoming = JSON.parse(event.body || "{}");
      if (!incoming.gameId) return json(400, { error: "gameId required" });
      const existing = await redis.get(`bet:${incoming.gameId}`);
      const merged = existing ? { ...existing, ...incoming } : incoming;
      await redis.set(`bet:${incoming.gameId}`, merged);
      await redis.sadd("bets:all", incoming.gameId);
      return json(200, { saved: incoming.gameId });
    }

    if (event.httpMethod === "DELETE") {
      if (!requireAuth(event)) return json(401, { error: "unauthorized" });
      const gameId = event.queryStringParameters && event.queryStringParameters.gameId;
      if (!gameId) return json(400, { error: "gameId required" });
      await redis.del(`bet:${gameId}`);
      await redis.srem("bets:all", gameId);
      return json(200, { deleted: gameId });
    }

    return json(405, { error: "method not allowed" });
  } catch (err) {
    return json(500, { error: err.message, stack: err.stack });
  }
};
