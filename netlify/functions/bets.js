const { getRedis, json, requireAuth } = require("./_redis");

// GET   /api/bets                 -> all bets
// POST  /api/bets                 -> create/update a bet. Body: bet object (see shape below)
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
      const bet = JSON.parse(event.body || "{}");
      if (!bet.gameId) return json(400, { error: "gameId required" });
      await redis.set(`bet:${bet.gameId}`, bet);
      await redis.sadd("bets:all", bet.gameId);
      return json(200, { saved: bet.gameId });
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
