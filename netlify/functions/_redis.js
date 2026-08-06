// Shared Upstash Redis client + key schema for the CFB betting tracker.
//
// KEY SCHEMA
// ----------
// game:{gameId}                      -> JSON: { gameId, week, kickoff, away, home, apRankAway, apRankHome, notable }
// week:{week}:games                  -> SET of gameId
// bet:{gameId}                       -> JSON: { gameId, side, spread, odds, stake, placedAt, result, notes }
// lines:hardrock:{gameId}:latest     -> JSON: { spread, odds, ts }
// lines:hardrock:{gameId}:history    -> LIST of JSON snapshots, oldest first (RPUSH)
// lines:reference:{gameId}:latest    -> JSON: { book, spread, odds, ts }  (best-of-market comparison line)
// lines:reference:{gameId}:history   -> LIST of JSON snapshots
// season:weeks                       -> SET of week numbers present in the system
//
// All writes go through helpers here so every function shares one consistent shape.

const { Redis } = require("@upstash/redis");

function getRedis() {
  const url = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) {
    throw new Error(
      "Missing UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN env vars"
    );
  }
  return new Redis({ url, token });
}

function json(statusCode, body) {
  return {
    statusCode,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
    body: JSON.stringify(body),
  };
}

function requireAuth(event) {
  // Simple shared-secret auth for write endpoints hit by GitHub Actions / you.
  // Set INGEST_TOKEN in Netlify env vars and pass it as `x-ingest-token` header.
  const expected = process.env.INGEST_TOKEN;
  if (!expected) return true; // no token configured = auth disabled (dev only)
  const provided = event.headers["x-ingest-token"] || event.headers["X-Ingest-Token"];
  return provided === expected;
}

module.exports = { getRedis, json, requireAuth };
