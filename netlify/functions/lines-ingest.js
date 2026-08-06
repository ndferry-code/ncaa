const { getRedis, json, requireAuth } = require("./_redis");

// POST /api/lines-ingest
// Called by the GitHub Actions scraper (or manually) to push a new line snapshot.
// Body:
// {
//   source: "hardrock" | "reference",
//   book: "hardrock" | "draftkings" | "fanduel" | ...,   // only meaningful for source=reference
//   snapshots: [
//     { gameId: "2026-wk3-osu-uw", spread: -6.5, odds: -110, ts: "2026-09-17T14:00:00Z" },
//     ...
//   ]
// }
//
// Stores each snapshot in the history list and overwrites the `latest` pointer.
// History lists are capped at 200 entries per game (roughly a week of hourly snapshots)
// so Redis storage doesn't grow unbounded across a season.

const MAX_HISTORY = 200;

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") return json(405, { error: "method not allowed" });
  if (!requireAuth(event)) return json(401, { error: "unauthorized" });

  try {
    const redis = getRedis();
    const body = JSON.parse(event.body || "{}");
    const source = body.source === "reference" ? "reference" : "hardrock";
    const book = body.book || (source === "hardrock" ? "hardrock" : "unknown");
    const snapshots = Array.isArray(body.snapshots) ? body.snapshots : [];

    let written = 0;
    for (const snap of snapshots) {
      if (!snap.gameId || typeof snap.spread !== "number") continue;
      const record = {
        spread: snap.spread,
        odds: snap.odds ?? null,
        book,
        ts: snap.ts || new Date().toISOString(),
      };
      const latestKey = `lines:${source}:${snap.gameId}:latest`;
      const historyKey = `lines:${source}:${snap.gameId}:history`;
      await redis.set(latestKey, record);
      await redis.rpush(historyKey, record);
      await redis.ltrim(historyKey, -MAX_HISTORY, -1);
      written += 1;
    }

    return json(200, { written, source, book });
  } catch (err) {
    return json(500, { error: err.message, stack: err.stack });
  }
};
