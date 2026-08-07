const API = "/api";

let state = { games: [], bets: [], lineMovement: [], valueComparison: [], record: {}, week: null, expertPicks: [] };
let expertsLoadedForWeek = null;

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
    if (document.getElementById("tabExperts").style.display !== "none") loadExperts();
  });
}

function initTabs() {
  const buttons = document.querySelectorAll(".tab-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      document.getElementById("tabDashboard").style.display = tab === "dashboard" ? "" : "none";
      document.getElementById("tabExperts").style.display = tab === "experts" ? "" : "none";
      if (tab === "experts") loadExperts();
    });
  });
}

async function loadExperts() {
  // Cache per week within a session -- this data only refreshes weekly on
  // the backend anyway, no need to refetch every tab click.
  if (expertsLoadedForWeek === state.week && state.expertPicks.length) {
    renderExperts();
    return;
  }
  const grid = document.getElementById("expertsGrid");
  grid.innerHTML = `<div class="breakeven-empty-text" style="padding:20px">Loading…</div>`;
  const res = await fetch(`${API}/expert-picks?week=${state.week}`);
  const data = await res.json();
  state.expertPicks = data.picks || [];
  expertsLoadedForWeek = state.week;
  renderExperts();
}

function renderExperts() {
  const grid = document.getElementById("expertsGrid");
  if (!state.expertPicks.length) {
    grid.innerHTML = `<div class="breakeven-empty-text" style="padding:20px">No expert content generated for this week yet -- it's pulled in automatically each Thursday.</div>`;
    return;
  }
  grid.innerHTML = state.expertPicks
    .map((item) => {
      const g = state.games.find((x) => x.gameId === item.gameId);
      const header = g ? gameLabel(g) : item.gameId;
      const newsHtml = item.newsSummary
        ? `<div class="expert-news">${item.newsSummary}</div>`
        : `<div class="expert-news empty">No notable news found this week.</div>`;
      const picksHtml = (item.picks || [])
        .map((p) => {
          const lean = p.leaning
            ? `<span class="expert-lean">${p.leaning}</span>`
            : `<span class="expert-lean none">no clear pick found</span>`;
          const note = p.note ? `<span class="expert-note">${p.note}</span>` : "";
          const source = p.sourceUrl ? `<a class="expert-source" href="${p.sourceUrl}" target="_blank" rel="noopener">source</a>` : "";
          return `<div class="expert-pick-row">
            <span class="expert-name">${p.expert}</span>
            ${lean}
            ${note}
            ${source}
          </div>`;
        })
        .join("");
      const generated = item.generatedAt
        ? `<div class="expert-generated">Updated ${new Date(item.generatedAt).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</div>`
        : "";
      return `<div class="expert-card">
        <div class="expert-card-header">${header}</div>
        ${newsHtml}
        ${picksHtml}
        ${generated}
      </div>`;
    })
    .join("");
}

async function loadDashboard() {
  // state.week can legitimately be 0 (Week 0), which is falsy in JS -- use
  // an explicit null/undefined check rather than truthiness everywhere below.
  const url = state.week != null ? `${API}/dashboard?week=${state.week}` : `${API}/dashboard`;
  const res = await fetch(url);
  const data = await res.json();
  state = { ...state, ...data };
  renderTicker();
  renderBreakevenHero();
  renderRecordCards();
  renderGamesTable();
  renderMovementTable();
  renderWeeklyResults();
  renderInsights();
}

function renderBreakevenHero() {
  const el = document.getElementById("breakevenHero");
  const r = state.record || {};
  const breakevenPct = (r.breakevenPct != null ? r.breakevenPct : 110 / 210) * 100;

  if (r.winPct == null) {
    el.innerHTML = `<div class="breakeven-card empty">
      <div class="breakeven-empty-text">Log some bets to start tracking win % against your ${breakevenPct.toFixed(1)}% break-even target.</div>
    </div>`;
    return;
  }

  const winPct = r.winPct * 100;
  const delta = winPct - breakevenPct;
  const above = delta >= 0;

  // Gauge is zoomed to a 35-65% window rather than 0-100 -- season win
  // rates realistically live in that band, and the full range would make
  // any real difference look like a rounding error.
  const GAUGE_MIN = 35, GAUGE_MAX = 65;
  const clampPos = (v) => Math.max(0, Math.min(100, ((v - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)) * 100));
  const fillPos = clampPos(winPct);
  const markerPos = clampPos(breakevenPct);

  const grade =
    delta >= 10 ? "A+" : delta >= 5 ? "A" : delta >= 0 ? "B" : delta >= -5 ? "C" : "F";

  let streakHtml = "";
  if (r.streak && r.streak.count > 0) {
    const emoji = r.streak.type === "win" ? "🔥" : "🧊";
    const label = r.streak.type === "win" ? "W" : "L";
    streakHtml = `<div class="breakeven-streak">${emoji} ${r.streak.count}${label}</div>`;
  }

  el.innerHTML = `<div class="breakeven-card ${above ? "above" : "below"}">
    <div class="breakeven-top">
      <div class="breakeven-figure">
        <div class="breakeven-pct">${winPct.toFixed(1)}%</div>
        <div class="breakeven-label">WIN % ATS</div>
      </div>
      <div class="breakeven-grade">${grade}</div>
      ${streakHtml}
    </div>
    <div class="breakeven-gauge">
      <div class="breakeven-track">
        <div class="breakeven-fill" style="width:${fillPos}%"></div>
        <div class="breakeven-marker" style="left:${markerPos}%"></div>
      </div>
      <div class="breakeven-scale">
        <span>${GAUGE_MIN}%</span><span>break-even ${breakevenPct.toFixed(1)}%</span><span>${GAUGE_MAX}%</span>
      </div>
    </div>
    <div class="breakeven-delta">${above ? "+" : ""}${delta.toFixed(1)} pts ${above ? "above" : "below"} break-even</div>
  </div>`;
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
  const breakevenPct = (r.breakevenPct != null ? r.breakevenPct : 110 / 210) * 100;
  const units = r.units != null ? r.units : 0;
  // Win % has its own big hero above now -- these cards cover what that
  // doesn't: the exact record, the target itself, units, and CLV.
  const cards = [
    { label: "Record", value: `${r.wins || 0}-${r.losses || 0}-${r.pushes || 0}` },
    { label: "Break-even Target", value: `${breakevenPct.toFixed(1)}%` },
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
        ? `<button class="btn-log btn-logged" data-gameid="${g.gameId}">${bet.side} @ ${bet.odds}</button>`
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

  // Both "Log bet" (new) and the logged-bet button (edit/settle) open the
  // same dialog -- openBetDialog looks up whether a bet already exists for
  // this gameId and pre-fills accordingly.
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

function renderWeeklyResults() {
  const body = document.getElementById("weeklyResultsBody");
  const byWeek = (state.record && state.record.byWeek) || {};
  const weeks = Object.keys(byWeek)
    .filter((w) => w !== "unknown")
    .map(Number)
    .sort((a, b) => a - b);

  if (!weeks.length) {
    body.innerHTML = `<tr><td colspan="3" class="mono" style="color:var(--muted)">No settled bets yet.</td></tr>`;
    return;
  }

  body.innerHTML = weeks
    .map((w) => {
      const r = byWeek[w];
      const decided = r.wins + r.losses;
      const winPct = decided > 0 ? ((r.wins / decided) * 100).toFixed(1) + "%" : "—";
      const cls = decided > 0 ? (r.wins / decided >= 0.5 ? "edge-favor" : "edge-against") : "";
      return `<tr>
        <td class="mono">Week ${w}</td>
        <td class="mono">${r.wins}-${r.losses}-${r.pushes}</td>
        <td class="mono ${cls}">${winPct}</td>
      </tr>`;
    })
    .join("");
}

function openBetDialog(gameId) {
  const dialog = document.getElementById("betDialog");
  const g = state.games.find((x) => x.gameId === gameId);
  const lm = state.lineMovement.find((m) => m.gameId === gameId);
  const hrCurrent = lm ? lm.hardrock.current : null; // this is always the HOME team's spread
  const existing = state.bets.find((b) => b.gameId === gameId);

  document.getElementById("betDialogTitle").textContent = existing ? "Edit Bet" : "Log Bet";
  document.getElementById("betGameId").value = gameId;
  document.getElementById("betSide").value = existing ? existing.side : "";
  document.getElementById("betSpread").value = existing ? existing.spread : "";
  document.getElementById("betOdds").value = existing ? existing.odds : -110;
  document.getElementById("betStake").value = existing ? existing.stake : 100;
  document.getElementById("betNotes").value = existing ? existing.notes || "" : "";
  document.getElementById("betResult").value = existing && existing.result ? existing.result : "";
  document.getElementById("betClosingLine").value = existing && existing.closingLine != null ? existing.closingLine : "";
  document.getElementById("betDelete").style.display = existing ? "" : "none";

  const quickPickRow = document.getElementById("quickPickRow");
  quickPickRow.innerHTML = "";

  // One-tap buttons for the two teams at the current Hard Rock line, so the
  // common case (you bet one side of the number the app is already
  // tracking) needs no typing at all -- just tap the team, set stake, save.
  if (g && typeof hrCurrent === "number") {
    const awaySpread = Math.round(hrCurrent * -10) / 10;
    const picks = [
      { team: g.away, spread: awaySpread },
      { team: g.home, spread: hrCurrent },
    ];
    picks.forEach((p) => {
      const label = `${p.team} ${fmtSpread(p.spread)}`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "quick-pick-btn";
      btn.textContent = label;
      if (existing && existing.side === label) btn.classList.add("selected");
      btn.addEventListener("click", () => {
        document.getElementById("betSide").value = label;
        document.getElementById("betSpread").value = p.spread;
        quickPickRow.querySelectorAll(".quick-pick-btn").forEach((b) => b.classList.remove("selected"));
        btn.classList.add("selected");
      });
      quickPickRow.appendChild(btn);
    });
  }

  dialog.showModal();
}

document.getElementById("betCancel").addEventListener("click", () => {
  document.getElementById("betDialog").close();
});

document.getElementById("betDelete").addEventListener("click", async () => {
  const gameId = document.getElementById("betGameId").value;
  if (!confirm("Delete this bet? This can't be undone.")) return;
  await fetch(`${API}/bets?gameId=${encodeURIComponent(gameId)}`, { method: "DELETE" });
  document.getElementById("betDialog").close();
  await loadDashboard();
});

document.getElementById("betForm").addEventListener("submit", async (e) => {
  const gameId = document.getElementById("betGameId").value;
  const g = state.games.find((x) => x.gameId === gameId);
  const existing = state.bets.find((b) => b.gameId === gameId);
  const resultVal = document.getElementById("betResult").value;
  const closingLineVal = document.getElementById("betClosingLine").value;
  const bet = {
    gameId,
    week: g ? g.week : state.week,
    side: document.getElementById("betSide").value,
    spread: parseFloat(document.getElementById("betSpread").value),
    odds: parseInt(document.getElementById("betOdds").value, 10),
    stake: parseFloat(document.getElementById("betStake").value),
    notes: document.getElementById("betNotes").value,
    // Keep the original placedAt/lineAtPlacement when editing -- these
    // describe when/where you bet, not when you're settling the result.
    placedAt: existing ? existing.placedAt : new Date().toISOString(),
    lineAtPlacement: existing
      ? existing.lineAtPlacement
      : state.lineMovement.find((m) => m.gameId === gameId)?.hardrock.current ?? null,
    closingLine: closingLineVal !== "" ? parseFloat(closingLineVal) : null,
    result: resultVal || null,
  };
  await fetch(`${API}/bets`, { method: "POST", body: JSON.stringify(bet) });
  await loadDashboard();
});

(async function init() {
  initTabs();
  await loadWeeks();
  await loadDashboard();
})();
