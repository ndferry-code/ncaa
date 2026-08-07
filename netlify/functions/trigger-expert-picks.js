const { getRedis, json, requireAuth } = require("./_redis");

// POST /api/trigger-expert-picks -> dispatches the "Fetch expert picks"
// GitHub Actions workflow (expert-picks.yml) via GitHub's REST API. This is
// what the "Refresh Now" button on the Experts & News tab calls.
//
// This is fire-and-forget: GitHub queues the workflow run and this returns
// immediately (usually a few seconds) -- it does NOT wait for the run to
// finish (that takes a few minutes, since it's one Claude API call with web
// search per game, done sequentially). The frontend shows a "triggered"
// message rather than pretending it can show live progress or auto-refresh
// with new data the moment you click.
//
// COST NOTE: every trigger costs real money (the Anthropic web search calls
// in fetch_expert_content.py). Two safety nets against runaway triggering:
//   1. requireAuth -- same shared secret as every other write endpoint here.
//   2. A server-side cooldown (below) independent of #1, since this token
//      lives in the frontend's JS source and is visible to anyone who views
//      page source -- the cooldown caps worst-case cost even if it leaks.

const COOLDOWN_MINUTES = 15;

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") return json(405, { error: "method not allowed" });
  if (!requireAuth(event)) return json(401, { error: "unauthorized" });

  try {
    const redis = getRedis();
    const lastTriggered = await redis.get("expert-picks:last-triggered");
    if (lastTriggered) {
      const elapsedMs = Date.now() - new Date(lastTriggered).getTime();
      const remainingMs = COOLDOWN_MINUTES * 60 * 1000 - elapsedMs;
      if (remainingMs > 0) {
        return json(429, {
          error: `Triggered too recently -- wait ${Math.ceil(remainingMs / 60000)} more minute(s).`,
          lastTriggered,
        });
      }
    }

    const githubToken = process.env.GITHUB_PAT;
    const repo = process.env.GITHUB_REPO; // e.g. "yourusername/cfb-betting-tracker"
    if (!githubToken || !repo) {
      return json(500, { error: "GITHUB_PAT / GITHUB_REPO not configured in Netlify env vars" });
    }

    const resp = await fetch(
      `https://api.github.com/repos/${repo}/actions/workflows/expert-picks.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${githubToken}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "main" }),
      }
    );

    if (!resp.ok) {
      const text = await resp.text();
      return json(resp.status, { error: `GitHub API error: ${text}` });
    }

    await redis.set("expert-picks:last-triggered", new Date().toISOString());
    return json(200, { triggered: true });
  } catch (err) {
    return json(500, { error: err.message, stack: err.stack });
  }
};
