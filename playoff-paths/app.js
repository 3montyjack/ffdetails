const WEEKS = [11, 12, 13, 14];

function pctColor(p) {
  if (p >= 85) return "var(--locked)";
  if (p >= 40) return "var(--bubble)";
  if (p >= 8) return "var(--longshot)";
  return "var(--dead)";
}

function formatMask(mask) {
  return [...mask].map((ch) => `<span class="${ch}">${ch}</span>`).join("");
}

function remWinsLine(dist) {
  if (!dist || !Object.keys(dist).length) return "No make-paths in these sims.";
  const parts = Object.entries(dist)
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .map(([wins, share]) => `${wins} wins: ${share}% of makes`);
  return parts.join(" · ");
}

function renderField(data, selectedId) {
  const field = document.getElementById("field");
  field.innerHTML = "";
  data.standings.forEach((team, idx) => {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "team-row";
    if (team.roster_id === selectedId) btn.classList.add("active");
    if (team.seed === data.playoff_teams) btn.classList.add("cut-line");
    btn.style.animationDelay = `${idx * 35}ms`;
    btn.dataset.rosterId = String(team.roster_id);
    btn.setAttribute("aria-pressed", team.roster_id === selectedId ? "true" : "false");
    btn.innerHTML = `
      <span class="seed">${team.seed}</span>
      <span class="who">
        <strong>${escapeHtml(team.name)}</strong>
        <span>${escapeHtml(team.owner)} · ${team.wins}–${team.losses} · ${team.pf.toFixed(1)} PF</span>
      </span>
      <span class="bar-wrap">
        <span class="pct" style="color:${pctColor(team.playoff_pct)}">${team.playoff_pct.toFixed(1)}%</span>
        <span class="bar" aria-hidden="true"><i style="width:${Math.min(team.playoff_pct, 100)}%"></i></span>
      </span>
    `;
    btn.addEventListener("click", () => selectTeam(data, team.roster_id));
    li.appendChild(btn);
    field.appendChild(li);
  });
}

function selectTeam(data, rosterId) {
  const team = data.standings.find((t) => t.roster_id === rosterId);
  if (!team) return;
  const rid = String(rosterId);
  const path = data.paths[rid] || {};
  const slate = data.team_schedules[rid] || [];
  const blurb = data.path_blurbs[rid] || "";

  document.getElementById("pathHint").textContent =
    "Click another manager in the field to swap paths.";
  document.getElementById("selSeed").textContent = `Seed ${team.seed} · cut is 7`;
  document.getElementById("selName").textContent = team.name;
  document.getElementById("selOwner").textContent = team.owner;
  document.getElementById("selRecord").textContent =
    `${team.wins}–${team.losses} · ${team.pf.toFixed(1)} PF · μ ${team.mu}/wk`;
  document.getElementById("selPct").textContent = `${team.playoff_pct.toFixed(1)}%`;
  document.getElementById("selPct").style.color = pctColor(team.playoff_pct);
  document.getElementById("selBlurb").textContent = blurb;

  const slateEl = document.getElementById("selSlate");
  slateEl.innerHTML = slate
    .map(
      (g) => `
      <li>
        <span class="wk">W${g.week}</span>
        <span>vs ${escapeHtml(g.opponent)} <small>(${escapeHtml(g.opponent_owner)} · ${g.opponent_record})</small></span>
        <span>${(g.p_win * 100).toFixed(0)}% win</span>
      </li>`
    )
    .join("");

  const masksEl = document.getElementById("selMasks");
  const tops = path.top_paths || [];
  if (!tops.length) {
    masksEl.innerHTML = `<li><span class="mask">—</span><span>No playoff finishes in the sim sample.</span><span></span></li>`;
  } else {
    masksEl.innerHTML = tops
      .map(
        (m) => `
      <li>
        <span class="mask"><span class="mask-dots">${formatMask(m.mask)}</span></span>
        <span>W${WEEKS.join(" / W")} pattern among make sims</span>
        <span>${m.pct_of_makes}%</span>
      </li>`
      )
      .join("");
  }

  document.getElementById("selWinNeed").textContent = remWinsLine(path.rem_wins_dist);

  const weekNeed = path.week_win_given_make || {};
  const weekEl = document.getElementById("selWeekNeed");
  if (!Object.keys(weekNeed).length) {
    weekEl.innerHTML = "";
  } else {
    weekEl.innerHTML = `<h4>Win rate in sims where they make it</h4>` +
      WEEKS.map((w) => {
        const rate = weekNeed[String(w)] ?? 0;
        const game = slate.find((g) => g.week === w);
        const opp = game ? game.opponent : "—";
        return `
          <div class="need-row">
            <span>W${w}</span>
            <span class="track" title="vs ${escapeHtml(opp)}"><i style="width:${rate}%"></i></span>
            <span>${rate}%</span>
          </div>`;
      }).join("");
  }

  renderField(data, rosterId);
  history.replaceState(null, "", `#team-${rosterId}`);
}

function renderElim(data) {
  const elim = data.focus?.elimination;
  if (!elim) return;
  const rows = (elim.checkpoints || [])
    .map(
      (c) =>
        `<tr><th scope="row">${escapeHtml(c.when)}</th><td>${escapeHtml(c.signal)}</td><td>${escapeHtml(c.status)}</td></tr>`
    )
    .join("");
  document.getElementById("elimCopy").innerHTML = `
    <p><strong>3montyjack / WhenPurdyGivesYouVikings</strong> — ${escapeHtml(elim.practical_answer)}</p>
    ${
      rows
        ? `<div class="elim-table-wrap"><table class="elim-table"><thead><tr><th>When (CST)</th><th>Signal</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div>`
        : ""
    }
    <p style="margin-top:0.9rem">Conditionals (same engine): win W11 → ~${elim.p_make_if_win_w11}% · lose W11 → ~${elim.p_make_if_lose_w11}%.</p>
  `;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function main() {
  const res = await fetch("./data.json", { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load data.json (${res.status})`);
  const data = await res.json();

  document.getElementById("asOf").textContent =
    `As of ${data.as_of} · ${data.sims.toLocaleString()} Monte Carlo sims · scored through week ${data.scored_through}`;
  document.getElementById("leagueId").textContent = data.league_id;
  document.getElementById("methodCopy").textContent =
    `${data.method.note} Weekly scores ~ Normal(μ, σ) from weeks ${data.method.scoring_weeks} (σ floor ${data.method.sigma_floor}). ` +
    `Real Sleeper schedule for weeks ${data.remaining_weeks.join("–")}. Rank by ${data.method.seed_rule}. ` +
    `Playoffs start week ${data.playoff_week_start}.`;

  const hashId = Number((location.hash.match(/team-(\d+)/) || [])[1]);
  const initial =
    data.standings.some((t) => t.roster_id === hashId)
      ? hashId
      : data.ui?.default_roster_id || data.standings[0].roster_id;

  selectTeam(data, initial);
  renderElim(data);
}

main().catch((err) => {
  document.getElementById("asOf").textContent = String(err);
  console.error(err);
});
