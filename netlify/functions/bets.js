const { getRedis, json, requireAuth } = require("./_redis");

// GET    /api/bets                -> all bets
// GET    /api/bets?gameId=xxx     -> all bets logged against one game (can be more than one -- a spread bet AND a total, say)
// POST   /api/bets                -> create or update a bet. Body: partial or full bet object (see shape below).
//                                     Pass "id" to update/settle an existing bet (merges onto it, so you don't have
//                                     to resend every field). Omit "id" to create a new one -- the server assigns one.
// DELETE /api/bets?id=xxx         -> remove a bet
//
// Bet shape:
// {
//   id: "bet-1758923-ab12",       // server-assigned, stable for the life of the bet
//   gameId: "2026-wk3-osu-uw",    // OPTIONAL -- omit for an ad hoc / prop / parlay bet not tied to a tracked game
//   week: 3,                      // OPTIONAL -- lets it roll into a weekly record even without a gameId
//   betType: "spread",            // "spread" | "total" | "moneyline" | "other"
//   label: "Ohio State -6.5",     // human readable description of the bet -- what you'd read back to yourself
//   odds: -110,                   // American odds
//   stake: 100,                   // units or $, your call - just be consistent
//   placedAt: "2026-09-17T14:00:00Z",
//   spread: -6.5,                 // OPTIONAL, only meaningful for spread/total bets
//   lineAtPlacement: -6.5,        // OPTIONAL, hard rock line when you bet, for CLV tracking (spread bets only)
//   closingLine: null,            // OPTIONAL, filled in later once you know the closing number
//   result: null,                 // "win" | "loss" | "push" | null (pending)
//   notes: ""
// }

function makeId() {
  return `bet-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

exports.handler = async (event) => {
  const redis = getRedis();

  try {
    if (event.httpMethod === "GET") {
      const gameId = event.queryStringParameters && event.queryStringParameters.gameId;
      let ids;
      if (gameId) {
        ids = await redis.smembers(`game:${gameId}:bets`);
      } else {
        ids = await redis.smembers("bets:all");
      }
      if (ids.length === 0) return json(200, { bets: [] });
      const bets = await redis.mget(...ids.map((id) => `bet:${id}`));
      return json(200, { bets: bets.filter(Boolean) });
    }

    if (event.httpMethod === "POST") {
      if (!requireAuth(event)) return json(401, { error: "unauthorized" });
      const incoming = JSON.parse(event.body || "{}");

      const id = incoming.id || makeId();
      const existing = incoming.id ? await redis.get(`bet:${id}`) : null;
      const merged = existing ? { ...existing, ...incoming, id } : { ...incoming, id };

      await redis.set(`bet:${id}`, merged);
      await redis.sadd("bets:all", id);
      if (merged.week !== undefined && merged.week !== null) {
        await redis.sadd(`week:${merged.week}:bets`, id);
      }
      if (merged.gameId) {
        await redis.sadd(`game:${merged.gameId}:bets`, id);
      }
      return json(200, { saved: id, bet: merged });
    }

    if (event.httpMethod === "DELETE") {
      if (!requireAuth(event)) return json(401, { error: "unauthorized" });
      const id = event.queryStringParameters && event.queryStringParameters.id;
      if (!id) return json(400, { error: "id required" });
      const existing = await redis.get(`bet:${id}`);
      await redis.del(`bet:${id}`);
      await redis.srem("bets:all", id);
      if (existing) {
        if (existing.week !== undefined && existing.week !== null) {
          await redis.srem(`week:${existing.week}:bets`, id);
        }
        if (existing.gameId) {
          await redis.srem(`game:${existing.gameId}:bets`, id);
        }
      }
      return json(200, { deleted: id });
    }

    return json(405, { error: "method not allowed" });
  } catch (err) {
    return json(500, { error: err.message, stack: err.stack });
  }
};
