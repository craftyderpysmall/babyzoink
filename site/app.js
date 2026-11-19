import { remoteData } from "./config.js";

const modes = ["Cube", "Ship", "Ball", "UFO", "Wave", "Robot", "Spider", "Swing"];
const byId = (id) => document.getElementById(id);
const format = (value, digits = 1) => Number(value).toLocaleString("en-US", { maximumFractionDigits: digits });
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 4 });
const pacific = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short", timeZone: "America/Los_Angeles" });
let snapshot;
let mode = "cube";
let source = "Bundled snapshot";

function el(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  return node;
}

function renderRows(id, rows, empty, columns) {
  const body = byId(id);
  body.replaceChildren();
  if (!rows.length) {
    const row = el("tr");
    const cell = el("td", empty);
    cell.colSpan = columns;
    row.append(cell);
    body.append(row);
    return;
  }
  for (const line of rows) {
    const row = el("tr");
    for (const item of line) row.append(el("td", item));
    body.append(row);
  }
}

const runLabels = {
  "m5c-search": "search teacher", "m4-practice": "M4 practice", "m4-control": "M4 control",
};

function attempts() {
  const kind = byId("attempt-kind").value;
  const rows = (snapshot.levels || []).filter((level) => kind === "all" || level.level.startsWith(`${kind}:`));
  renderRows("attempt-rows", rows.map((level) => {
    const first = level.first_cleared_by;
    const by = first ? `${runLabels[first.run] || first.run}, attempt ${first.attempt}` : "not yet";
    return [
      level.name, format(level.normal_attempts, 0), format(level.practice_attempts, 0),
      format(level.normal_clears, 0), `${format(100 * level.best_progress)}%`, by,
    ];
  }), "No attempts recorded for this group yet.", 6);
}

function latestModeRow(name) {
  return (snapshot.performance?.zero_shot?.trend ?? []).reduce((latest, row) => {
    return row.mode === name && (!latest || row.generation > latest.generation) ? row : latest;
  }, null);
}

function overviewPerformance() {
  const official = snapshot.levels?.filter((row) => row.level?.startsWith("official:"));
  const cleared = official?.filter((row) => row.normal_clears > 0) ?? [];
  const searchClears = cleared.filter((row) =>
    ["m5c-search", "m5c-demo-replay"].includes(row.first_cleared_by?.run)).length;
  const clears = official?.length ? `${cleared.length} of 5` : "—";
  const attribution = searchClears ? ` · ${searchClears} first cleared by search teacher` : "";
  byId("official-clears").textContent = `Official levels cleared ${clears}${attribution}`;
  const best = (snapshot.progress.results ?? []).reduce((highest, row) => {
    if (!Number.isFinite(row.first_run_progress_pct) || row.agent === "Timing heuristic") return highest;
    return !highest || row.first_run_progress_pct > highest.first_run_progress_pct ? row : highest;
  }, null);
  byId("policy-best").textContent = best
    ? `Trained-policy best ${format(best.first_run_progress_pct)}% first run · ${best.study}`
    : "Trained-policy best —";
  byId("overview-modes").replaceChildren(...modes.map((name) => {
    const key = name.toLowerCase();
    const record = latestModeRow(key);
    const link = el("a", undefined, "mode");
    link.href = `#performance/${key}`;
    const rating = Number.isFinite(record?.rating)
      ? describe(record)
      : `Not rated yet · ${format(record?.seconds ?? 0)} s observed, ${format(record?.deaths ?? 0, 0)} deaths`;
    const rate = Number.isFinite(record?.deaths_per_minute) ? format(record.deaths_per_minute) : "—";
    const bestLevel = record?.best_level_cleared;
    const level = bestLevel ? snapshot.level_names?.[bestLevel] ?? bestLevel : "—";
    link.append(el("strong", name), el("small", rating),
      el("small", `Deaths/min ${rate}`), el("small", `Best level cleared ${level}`));
    return link;
  }));
}

function overview() {
  const { progress, energy } = snapshot;
  const completed = progress.milestones.filter((item) => item.status === "done").length;
  byId("done").textContent = `${completed} / ${progress.milestones.length}`;
  byId("next").textContent = progress.milestones.find((item) => item.status !== "done")?.name || "All milestones complete";
  byId("energy").textContent = energy.rows.length ? `${format(energy.kwh, 4)} kWh` : "—";
  byId("cost").textContent = energy.rows.length ? usd.format(energy.cost_usd) : "—";
  byId("tracking").textContent = energy.tracking_since ? `Tracking began ${pacific.format(new Date(energy.tracking_since))} PT` : "No samples yet";
  const price = progress.price;
  byId("price").textContent = `${price.region} ${price.sector.toLowerCase()} · ${format(price.cents_per_kwh, 2)}¢/kWh`;
  const items = progress.milestones.map((milestone) => {
    const li = el("li");
    const detail = el("div");
    detail.append(el("strong", milestone.name), el("p", milestone.detail));
    const status = milestone.status === "done" ? "Complete" : milestone.status.replaceAll("_", " ");
    li.append(el("span", milestone.id, "code"), detail, el("small", status, milestone.status));
    return li;
  });
  byId("milestones").replaceChildren(...items);
  renderRows("results", progress.results.map((row) => [
    row.study, row.agent, Number.isFinite(row.first_run_progress_pct) ? `${format(row.first_run_progress_pct)}%` : "—",
    Number.isFinite(row.clears_within_3) ? `${format(row.clears_within_3)} / ${row.drills}` : "—",
    Number.isFinite(row.first_try_clears) ? `${format(row.first_try_clears)} / ${row.drills}` : "—",
  ]), "No study results are available.", 5);
  overviewPerformance();
  attempts();
  renderRows("energy-rows", energy.rows.map((row) => [
    row.date, `${format(row.kwh, 4)} kWh`, usd.format(row.cost_usd),
  ]), "No power samples are available.", 3);
}

function chart(id, entries, { baseline = null, empty, digits = 1 }) {
  const canvas = byId(id);
  const { width, height } = canvas.getBoundingClientRect();
  if (!width || !height) return;
  const density = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * density);
  canvas.height = Math.round(height * density);
  const ctx = canvas.getContext("2d");
  ctx.scale(density, density);
  ctx.font = "13px system-ui";
  ctx.fillStyle = "#adbccc";
  const defined = entries.filter((item) => item.value !== null);
  if (!defined.length) {
    ctx.textAlign = "center";
    ctx.fillText(empty, width / 2, height / 2, width - 26);
    return;
  }
  const values = defined.flatMap((item) => item.interval ?? [item.value]);
  if (baseline !== null) values.push(baseline);
  let low = Math.min(...values);
  let high = Math.max(...values);
  if (low === high) high = low + 1;
  if (baseline === null) {
    const padding = (high - low) * .08;
    low -= padding;
    high += padding;
  }
  const left = 57, right = width - 22, top = 15, bottom = height - 32;
  const x = (index) => entries.length === 1 ? (left + right) / 2 : left + index * (right - left) / (entries.length - 1);
  const y = (value) => bottom - (value - low) / (high - low) * (bottom - top);
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) {
    const value = low + i * (high - low) / 4;
    const heightAt = y(value);
    ctx.strokeStyle = "#2b394d";
    ctx.beginPath();
    ctx.moveTo(left, heightAt);
    ctx.lineTo(right, heightAt);
    ctx.stroke();
    ctx.fillText(format(value, digits), left - 8, heightAt);
  }
  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.strokeStyle = "#a6edc6";
  ctx.lineWidth = 2;
  ctx.beginPath();
  let previous = false;
  const labelInterval = Math.max(1, Math.ceil(entries.length / Math.max(2, Math.floor((right - left) / 85))));
  entries.forEach((item, index) => {
    if (index % labelInterval === 0 || index === entries.length - 1) {
      ctx.fillText(item.label, x(index), height - 9);
    }
    if (item.value === null) {
      previous = false;
      return;
    }
    if (previous) ctx.lineTo(x(index), y(item.value));
    else ctx.moveTo(x(index), y(item.value));
    previous = true;
  });
  ctx.stroke();
  entries.forEach((item, index) => {
    if (item.value === null) return;
    if (item.interval) {
      ctx.strokeStyle = "#72a991";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x(index), y(item.interval[0]));
      ctx.lineTo(x(index), y(item.interval[1]));
      ctx.stroke();
    }
    ctx.fillStyle = "#a6edc6";
    ctx.beginPath();
    ctx.arc(x(index), y(item.value), 4, 0, Math.PI * 2);
    ctx.fill();
  });
}

function title(name) {
  return modes.find((item) => item.toLowerCase() === name) ?? name;
}

function scopeRows() {
  return snapshot.performance?.[byId("scope").value]?.trend ?? [];
}

function refreshGenerations() {
  const select = byId("generation");
  const generations = [...new Set(scopeRows().map((row) => row.generation))].sort((a, b) => a - b);
  const previous = select.value;
  select.replaceChildren(...generations.map((number) => {
    const option = el("option", `Generation ${number}`);
    option.value = number;
    return option;
  }));
  if (!generations.length) select.append(el("option", "No measured generations"));
  select.disabled = !generations.length;
  if (generations.length) select.value = generations.some((n) => String(n) === previous) ? previous : generations.at(-1);
}

function describe(record) {
  if (!record) return "No evidence";
  const observed = `${format(record.seconds)} s observed`;
  if (!Number.isFinite(record.rating)) return observed;
  const scale = record.calibration === "gddl" ? "GDDL" : "Pre-demon";
  const rating = `${scale} ${format(record.rating, 2)}`;
  return record.interval
    ? `${rating} · ${format(record.interval[0], 2)} to ${format(record.interval[1], 2)}` : rating;
}

function performance() {
  const generation = Number(byId("generation").value);
  const rows = scopeRows();
  const current = rows.find((row) => row.mode === mode && row.generation === generation);
  const selected = new Map(rows.filter((row) => row.generation === generation).map((row) => [row.mode, row]));
  for (const button of byId("modes").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(mode === button.dataset.mode));
    button.querySelector("small").textContent = describe(selected.get(button.dataset.mode));
  }
  const practice = current && byId("scope").value === "all"
    ? ` · ${current.checkpoint_entries} checkpoint and ${current.startpos_entries} start-position entries` : "";
  byId("trend-title").textContent = `${title(mode)} rating by generation`;
  byId("trend-summary").textContent = current
    ? `${format(current.seconds)} s observed in ${current.entries} entries · ${current.deaths} deaths${practice}${current.rating === null ? " · calibration pending" : ""}`
    : "No section telemetry for this mode and evidence scope.";
  const historical = new Map(rows.filter((row) => row.mode === mode).map((row) => [row.generation, row]));
  const numbers = [...new Set(rows.map((row) => row.generation))].sort((a, b) => a - b);
  chart("trend-chart", numbers.map((number) => {
    const point = historical.get(number);
    return { label: `Gen ${number}`, value: point?.rating ?? null, interval: point?.interval };
  }), { empty: "No calibrated ratings in this view." });
  const points = [...historical.values()].filter((row) => Number.isFinite(row.rating));
  byId("trend-chart").setAttribute("aria-label", points.length
    ? points.map((row) => `Generation ${row.generation}, rating ${describe(row)}`).join(". ")
    : `No calibrated ${title(mode)} ratings in this view`);
  renderRows("level-rows", (current?.levels ?? []).map((row) => [
    snapshot.level_names?.[row.level] ?? row.level, row.anchor ?? "Unrated",
    `${format(row.seconds)} s · ${row.entries} entries`, row.deaths_per_minute ?? "—",
    row.mean_attempts_to_first_section_clear === null ? "—" : format(row.mean_attempts_to_first_section_clear),
  ]), "No entered sections recorded for this view.", 5);
}

function route() {
  const [page, requestedMode] = location.hash.slice(1).split("/");
  const active = page === "performance" ? "performance" : "overview";
  if (active === "performance" && modes.some((name) => name.toLowerCase() === requestedMode)) {
    mode = requestedMode;
    if (snapshot) {
      byId("scope").value = "zero_shot";
      refreshGenerations();
      const record = latestModeRow(mode);
      if (record) byId("generation").value = record.generation;
    }
  }
  for (const name of ["overview", "performance"]) {
    byId(name).hidden = active !== name;
    if (name === active) byId(`nav-${name}`).setAttribute("aria-current", "page");
    else byId(`nav-${name}`).removeAttribute("aria-current");
  }
  draw();
}

function draw() {
  if (!snapshot) return;
  if (byId("overview").hidden) {
    performance();
  } else {
    const entries = snapshot.energy.rows.map((row) => ({ label: row.date.slice(5), value: row.cumulative_kwh }));
    chart("energy-chart", entries, { baseline: 0, digits: 3, empty: "No energy samples recorded." });
    byId("energy-chart").setAttribute("aria-label", entries.length
      ? `Cumulative estimated energy reached ${format(snapshot.energy.kwh, 4)} kWh`
      : "No energy samples recorded");
  }
}

async function fetchData(url, timeout = 10_000) {
  const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(timeout) });
  if (!response.ok) throw new Error(`Snapshot HTTP ${response.status}`);
  const data = await response.json();
  if (data.schema !== 1 || !Number.isFinite(Date.parse(data.updated_at)) ||
      !data.progress || !data.energy || !data.gddl) {
    throw new Error("Unsupported snapshot");
  }
  return data;
}

async function init() {
  byId("modes").append(...modes.map((name) => {
    const button = el("button", undefined, "mode");
    button.type = "button";
    button.dataset.mode = name.toLowerCase();
    button.append(el("strong", name), el("small", "No evidence"));
    button.addEventListener("click", () => { mode = button.dataset.mode; performance(); });
    return button;
  }));
  byId("scope").addEventListener("change", () => { refreshGenerations(); draw(); });
  byId("generation").addEventListener("change", draw);
  byId("attempt-kind").addEventListener("change", attempts);
  addEventListener("hashchange", route);
  addEventListener("resize", draw);
  route();
  if (remoteData) {
    const [remote, bundled] = await Promise.allSettled([
      fetchData(remoteData, 4500),
      fetchData("./data/dashboard.json"),
    ]);
    if (remote.status === "fulfilled" && (bundled.status !== "fulfilled" ||
      Date.parse(remote.value.updated_at) >= Date.parse(bundled.value.updated_at))) {
      snapshot = remote.value;
      source = "Nightly data feed";
    } else if (bundled.status === "fulfilled") {
      snapshot = bundled.value;
      source = remote.status === "fulfilled"
        ? "Bundled snapshot · newer than nightly data"
        : "Bundled fallback · live data feed unavailable";
    }
  }
  snapshot ??= await fetchData("./data/dashboard.json");
  byId("updated").textContent = `Updated ${pacific.format(new Date(snapshot.updated_at))} PT`;
  byId("data-source").textContent = source;
  const { version, checked_at: checkedAt } = snapshot.gddl;
  if (version) byId("gddl-source").textContent = `GD Demon Ladder · API ${version}${checkedAt ? ` · checked ${checkedAt.slice(0, 10)}` : ""}`;
  overview();
  refreshGenerations();
  route();
}

init().catch(() => {
  byId("error").textContent = "Dashboard data could not be loaded. Reload the page to try again.";
  byId("error").hidden = false;
});
