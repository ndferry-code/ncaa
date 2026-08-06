const API = "/api";

let state = { games: [], bets: [], lineMovement: [], valueComparison: [], record: {}, week: null };

async function loadWeeks() {
  const res = await fetch(`${API}/games`);
  const { games } = await res.json();
  const weeks = [...new Set(games.map((g) => g.week))].sort((a, b) => a - b);
  const select = document.getElementById("weekSelect");
  select.innerHTML = weeks.map((w) => `<option value="${w}">Week ${w}</option>`).join("");
  if (weeks.length) {
    const current = weeks[weeks.length - 1];
    select.value = current;
    state.week = current;
  }
  select.addEventListener("change", () => {
    state.week = Number(select.value);
    loadDashboard();
  });
}

async function loadDashboard() {
  // state.week can legitimately be 0 (Week 0), which is falsy in JS -- use
  // an explicit null/undefined check rather than truthiness everywhere below.
  const url = state.week != null ? `${API}/dashboard?week=${state.week}` : `${API}/dashboard`;
  const res = await fetch(url);
  const data = await res.json();
  state = { ...state, ...data };
  renderTicker();
  renderRecordCards();
  renderGamesTable();
  renderMovementTable();
  renderInsights();
}

function fmtSpread(n) {
  if (n == null) return "—";
  return n > 0 ? `+${n}` : `${n}`;
}

function gameLabel(g, hrSpread) {
  const awayRank = g.apRankAway ? `#${g.apRankAway} ` : "";
  const homeRank = g.apRankHome ? `#${g.apRankHome} ` : "";
  let awayName = `${awayRank}${g.away}`;
  let homeName = `${homeRank}${g.home}`;
  // hrSpread is always the HOME team's number (see fetch_lines.py's
  // spread_for_home) -- negative means home is favored, positive means away
  // is favored, 0 is a pick'em. Bold whichever team is favored.
  if (typeof hrSpread === "number") {
    if (hrSpread < 0) homeName = `<span class="favorite">${homeName}</span>`;
    else if (hrSpread > 0) awayName = `<span class="favorite">${awayName}</span>`;
  }
  return `${awayName} @ ${homeName}`;
}

function renderTicker() {
  const movers = state.lineMovement.filter((m) => m.biggestMover && m.hardrock.deltaPts != null);
  const track = document.getElementById("tickerTrack");
  if (!movers.length) {
    track.textContent = "No significant line movement yet this week.";
    return;
  }
  track.innerHTML = movers
    .map((m) => {
      const g = state.games.find((x) => x.gameId === m.gameId);
      const dir = m.hardrock.deltaPts > 0 ? "up" : "down";
      const arrow = m.hardrock.deltaPts > 0 ? "▲" : "▼";
      return `<span class="item">${g ? gameLabel(g, m.hardrock.current) : m.gameId}: ${fmtSpread(m.hardrock.open)} → ${fmtSpread(
        m.hardrock.current
      )} <span class="${dir}">${arrow} ${Math.abs(m.hardrock.deltaPts)} pts</span></span>`;
    })
    .join("");
}

function renderRecordCards() {
  const r = state.record || {};
  const winPct = r.winPct != null ? `${(r.winPct * 100).toFixed(1)}%` : "—";
  const units = r.units != null ? r.units : 0;
  const cards = [
    { label: "Record", value: `${r.wins || 0}-${r.losses || 0}-${r.pushes || 0}` },
    { label: "Win %", value: winPct },
    { label: "Units", value: units > 0 ? `+${units}` : `${units}`, cls: units > 0 ? "positive" : units < 0 ? "negative" : "" },
    { label: "Avg CLV (pts)", value: r.avgClv != null ? r.avgClv.toFixed(2) : "—", cls: r.avgClv > 0 ? "positive" : r.avgClv < 0 ? "negative" : "" },
  ];
  document.getElementById("recordCards").innerHTML = cards
    .map((c) => `<div class="score-card"><div class="label">${c.label}</div><div class="value ${c.cls || ""}">${c.value}</div></div>`)
    .join("");
}

function renderGamesTable() {
  const body = document.getElementById("gamesBody");
  if (!state.games.length) {
    body.innerHTML = `<tr><td colspan="7" class="mono" style="color:var(--muted)">No games loaded for this week yet.</td></tr>`;
    return;
  }
  body.innerHTML = state.games
    .sort((a, b) => new Date(a.kickoff) - new Date(b.kickoff))
    .map((g) => {
      const bet = state.bets.find((b) => b.gameId === g.gameId);
      const vc = state.valueComparison.find((v) => v.gameId === g.gameId);
      const lm = state.lineMovement.find((m) => m.gameId === g.gameId);
      const kickoff = g.kickoff
        ? new Date(g.kickoff).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
        : "—";
      // Show the Hard Rock / reference spread independently whenever either
      // exists -- don't require both just because "edge" needs both. A game
      // with only a Hard Rock line (reference not posted yet, or vice versa)
      // should still show whichever number is actually available.
      const hrCurrent = lm ? lm.hardrock.current : null;
      const refCurrent = lm ? lm.reference.current : null;
      const hrSpread = fmtSpread(hrCurrent);
      const refSpread = refCurrent != null ? `${fmtSpread(refCurrent)} (${lm.reference.book || "ref"})` : "—";
      let edgeHtml = "—";
      if (vc) {
        const cls = vc.edgePts > 0 ? "edge-favor" : vc.edgePts < 0 ? "edge-against" : "edge-neutral";
        edgeHtml = `<span class="${cls} mono">${vc.edgePts > 0 ? "+" : ""}${vc.edgePts} pts</span>`;
      }
      const betCell = bet
        ? `<span class="mono">${bet.side} @ ${bet.odds}</span>`
        : `<button class="btn-log" data-gameid="${g.gameId}">Log bet</button>`;
      const resultCell = bet && bet.result
        ? `<span class="pill ${bet.result}">${bet.result.toUpperCase()}</span>`
        : bet
        ? `<span class="pill pending">PENDING</span>`
        : "—";
      return `<tr>
        <td class="mono">${kickoff}</td>
        <td>${gameLabel(g, hrCurrent)}</td>
        <td class="mono">${hrSpread}</td>
        <td class="mono">${refSpread}</td>
        <td>${edgeHtml}</td>
        <td>${betCell}</td>
        <td>${resultCell}</td>
      </tr>`;
    })
    .join("");

  body.querySelectorAll(".btn-log").forEach((btn) => {
    btn.addEventListener("click", () => openBetDialog(btn.dataset.gameid));
  });
}

function renderMovementTable() {
  const body = document.getElementById("movementBody");
  const rows = [...state.lineMovement]
    // Only real movers: must have an actual delta, and 0.0 pts doesn't
    // count as movement even if it technically has open/current values.
    .filter((m) => m.hardrock.deltaPts != null && m.hardrock.deltaPts !== 0)
    .sort((a, b) => Math.abs(b.hardrock.deltaPts) - Math.abs(a.hardrock.deltaPts))
    .slice(0, 10);
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="mono" style="color:var(--muted)">No line movement yet.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((m) => {
      const g = state.games.find((x) => x.gameId === m.gameId);
      const delta = m.hardrock.deltaPts;
      const cls = delta > 0 ? "edge-favor" : delta < 0 ? "edge-against" : "edge-neutral";
      const trend = m.hardrock.history
        .map((h) => h.spread)
        .slice(-8)
        .join(" → ");
      return `<tr>
        <td>${g ? gameLabel(g, m.hardrock.current) : m.gameId}${m.biggestMover ? ' <span class="pill pending">MOVER</span>' : ""}</td>
        <td class="mono">${fmtSpread(m.hardrock.open)}</td>
        <td class="mono">${fmtSpread(m.hardrock.current)}</td>
        <td class="mono ${cls}">${delta != null ? (delta > 0 ? "+" : "") + delta : "—"}</td>
        <td class="mono" style="color:var(--muted)">${trend || "—"}</td>
      </tr>`;
    })
    .join("");
}

function renderInsights() {
  const grid = document.getElementById("insightsGrid");
  const settled = state.bets.filter((b) => b.result === "win" || b.result === "loss");
  const insights = [];

  if (settled.length >= 3) {
    // Favorite vs underdog split
    const favBets = settled.filter((b) => b.spread < 0);
    const dogBets = settled.filter((b) => b.spread > 0);
    const favWinPct = favBets.length ? (favBets.filter((b) => b.result === "win").length / favBets.length) * 100 : null;
    const dogWinPct = dogBets.length ? (dogBets.filter((b) => b.result === "win").length / dogBets.length) * 100 : null;
    if (favWinPct != null) insights.push({ title: "Betting Favorites", body: `${favBets.length} bets, ${favWinPct.toFixed(0)}% win rate ATS.` });
    if (dogWinPct != null) insights.push({ title: "Betting Underdogs", body: `${dogBets.length} bets, ${dogWinPct.toFixed(0)}% win rate ATS.` });

    // CLV correlation
    const clvBets = settled.filter((b) => typeof b.lineAtPlacement === "number" && typeof b.closingLine === "number");
    if (clvBets.length >= 3) {
      const beatClose = clvBets.filter((b) => Math.sign(b.closingLine - b.lineAtPlacement) === Math.sign(b.spread));
      const winPctWhenBeatClose = beatClose.length
        ? (beatClose.filter((b) => b.result === "win").length / beatClose.length) * 100
        : null;
      if (winPctWhenBeatClose != null) {
        insights.push({
          title: "Closing Line Value",
          body: `When you beat the closing number, you won ${winPctWhenBeatClose.toFixed(0)}% of the time (${beatClose.length} bets). Early value is showing up in results.`,
        });
      }
    }
  } else {
    insights.push({ title: "Not enough data yet", body: "Log and settle a few more bets and trends will start showing up here automatically." });
  }

  grid.innerHTML = insights
    .map((i) => `<div class="insight-card"><div class="insight-title">${i.title}</div>${i.body}</div>`)
    .join("");
}

function openBetDialog(gameId) {
  const dialog = document.getElementById("betDialog");
  document.getElementById("betGameId").value = gameId;
  document.getElementById("betSide").value = "";
  document.getElementById("betSpread").value = "";
  document.getElementById("betOdds").value = -110;
  document.getElementById("betStake").value = 100;
  document.getElementById("betNotes").value = "";
  dialog.showModal();
}

document.getElementById("betCancel").addEventListener("click", () => {
  document.getElementById("betDialog").close();
});

document.getElementById("betForm").addEventListener("submit", async (e) => {
  const gameId = document.getElementById("betGameId").value;
  const g = state.games.find((x) => x.gameId === gameId);
  const bet = {
    gameId,
    week: g ? g.week : state.week,
    side: document.getElementById("betSide").value,
    spread: parseFloat(document.getElementById("betSpread").value),
    odds: parseInt(document.getElementById("betOdds").value, 10),
    stake: parseFloat(document.getElementById("betStake").value),
    notes: document.getElementById("betNotes").value,
    placedAt: new Date().toISOString(),
    lineAtPlacement: state.lineMovement.find((m) => m.gameId === gameId)?.hardrock.current ?? null,
    closingLine: null,
    result: null,
  };
  await fetch(`${API}/bets`, { method: "POST", body: JSON.stringify(bet) });
  await loadDashboard();
});

(async function init() {
  await loadWeeks();
  await loadDashboard();
})();
