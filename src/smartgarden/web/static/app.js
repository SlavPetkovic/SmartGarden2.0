/* SmartGarden dashboard: makes docs/dashboard.html real against the live
   API. Every value on screen names its provenance (a role in a zone) and
   nothing here names a driver except the Health view (DATA-3, SCOPE-3). */
"use strict";

(function () {
  const API = "/api";
  const REFRESH_MS = 15000;
  const RECENT_HOURS = 2;
  const FALLBACK_DAYS = 30;

  let unit = "C";
  let rangeHours = 24;
  let model = null; // { channels, plants, zones, health }

  // ---------------------------------------------------------------------
  // fetch helpers
  // ---------------------------------------------------------------------

  async function api(path, opts) {
    const resp = await fetch(API + path, opts);
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      throw new Error(detail.detail || (resp.status + " " + resp.statusText));
    }
    return resp.status === 204 ? null : resp.json();
  }

  function isoRange(hoursBack, hoursForward) {
    const now = new Date();
    const start = new Date(now.getTime() - hoursBack * 3600 * 1000);
    const end = new Date(now.getTime() + (hoursForward || 0) * 3600 * 1000);
    return { start: start.toISOString(), end: end.toISOString() };
  }

  /* Last known value for a channel, and its age -- widening the window
     before giving up, so a quiet sensor still shows its last reading
     rather than nothing (UI-2). */
  async function latestFor(channelId) {
    for (const hours of [RECENT_HOURS, FALLBACK_DAYS * 24]) {
      const { start, end } = isoRange(hours, 0.01);
      const series = await api(
        `/channels/${channelId}/timeseries?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`
      ).catch(() => null);
      if (series && series.raw && series.raw.length) {
        const last = series.raw[series.raw.length - 1];
        return { value: last.value, quality: last.quality, at: new Date(last.ts) };
      }
      if (series && series.rollup && series.rollup.length) {
        const last = series.rollup[series.rollup.length - 1];
        return { value: last.mean, quality: "ok", at: new Date(last.ts) };
      }
    }
    return null;
  }

  function ageSeconds(at) {
    return Math.max(0, (Date.now() - at.getTime()) / 1000);
  }

  function fmtAge(seconds) {
    if (seconds < 90) return Math.round(seconds) + "s ago";
    if (seconds < 5400) return Math.round(seconds / 60) + " min ago";
    if (seconds < 86400 * 2) return Math.round(seconds / 3600) + "h ago";
    return Math.round(seconds / 86400) + "d ago";
  }

  function fmtClock(d) {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  function cToDisplay(c) {
    return unit === "C" ? c : (c * 9) / 5 + 32;
  }

  // ---------------------------------------------------------------------
  // model
  // ---------------------------------------------------------------------

  async function loadModel() {
    const [channels, plants, zones, health] = await Promise.all([
      api("/channels"),
      api("/plants"),
      api("/zones"),
      api("/health"),
    ]);
    model = { channels, plants, zones, health };
    return model;
  }

  function channelsFor(predicate) {
    return model.channels.filter(predicate);
  }

  function channelForPlantRole(plantSlug, role) {
    return channelsFor((c) => c.plant === plantSlug && c.role === role)[0] || null;
  }

  function channelForZoneRole(zoneSlug, role) {
    return channelsFor((c) => c.zone === zoneSlug && c.plant === null && c.role === role)[0] || null;
  }

  // ---------------------------------------------------------------------
  // hero
  // ---------------------------------------------------------------------

  async function renderHero() {
    const zone = model.zones[0];
    document.getElementById("greeting").textContent = zone ? zone.name : "SmartGarden";
    document.getElementById("subgreet").textContent = zone
      ? `${model.plants.length} plant${model.plants.length === 1 ? "" : "s"}`
      : "No zones configured yet";

    const tileDefs = zone
      ? [
          ["air_temp", "Air temp", "temp"],
          ["humidity", "Humidity", "pct"],
          ["vpd", "VPD", "kpa"],
          ["light", "Light", "lux"],
        ]
      : [];

    const tiles = document.getElementById("hero-tiles");
    tiles.innerHTML = "";
    for (const [role, label, kind] of tileDefs) {
      const channel = channelForZoneRole(zone.slug, role);
      const tile = document.createElement("div");
      tile.className = "tile";
      if (!channel) {
        tile.innerHTML = `<div><div class="k">${label}</div><div class="v">&ndash;</div></div>`;
        tiles.appendChild(tile);
        continue;
      }
      const latest = await latestFor(channel.id);
      tile.innerHTML = `<div><div class="k">${label}</div><div class="v">&hellip;</div></div>`;
      tiles.appendChild(tile);
      const v = tile.querySelector(".v");
      if (!latest) {
        v.textContent = "no data";
      } else if (kind === "temp") {
        v.innerHTML = `${cToDisplay(latest.value).toFixed(1)}<span class="u">&deg;${unit}</span>`;
      } else if (kind === "pct") {
        v.innerHTML = `${latest.value.toFixed(0)}<span class="u">%</span>`;
      } else if (kind === "kpa") {
        v.innerHTML = `${latest.value.toFixed(2)}<span class="u">kPa</span>`;
      } else {
        v.innerHTML = `${Math.round(latest.value).toLocaleString()}<span class="u">lux</span>`;
      }
    }
  }

  // ---------------------------------------------------------------------
  // plants panel
  // ---------------------------------------------------------------------

  function moistureStatusPill(value, low, high, staleSeconds) {
    if (staleSeconds > 300) return { cls: "warn", label: "Sensor stale" };
    if (low == null || high == null) return { cls: "info", label: "No band set" };
    if (value < low || value > high) return { cls: "crit", label: "Out of band" };
    return { cls: "good", label: "Healthy" };
  }

  async function renderPlantCard(plant) {
    const moistureCh = channelForPlantRole(plant.slug, "soil_moisture");
    const tempCh = channelForPlantRole(plant.slug, "soil_temp");
    const moisture = moistureCh ? await latestFor(moistureCh.id) : null;
    const soilTemp = tempCh ? await latestFor(tempCh.id) : null;

    const staleSeconds = moisture ? ageSeconds(moisture.at) : Infinity;
    const low = plant.moisture_low, high = plant.moisture_high;
    const status = moisture
      ? moistureStatusPill(moisture.value, low, high, staleSeconds)
      : { cls: "info", label: "No data" };

    const card = document.createElement("article");
    card.className = "card lift";

    // The meter's axis is the sensor's own plausible range (what the
    // hardware can actually report, e.g. a Seesaw's ~200-2000 counts) --
    // never a percentage, and never just the plant's own target band,
    // which is drawn as an overlay on that same axis (DATA-3's "every
    // value names its provenance" applies to the meter too).
    const axisMin = moistureCh && moistureCh.plausible_min != null ? moistureCh.plausible_min : (low != null ? low : 0);
    const axisMax = moistureCh && moistureCh.plausible_max != null ? moistureCh.plausible_max : (high != null ? high : 100);
    const axisSpan = Math.max(1, axisMax - axisMin);
    const pct = (v) => Math.min(100, Math.max(0, ((v - axisMin) / axisSpan) * 100));
    const trackFill = moisture ? pct(moisture.value) : 0;
    const bandStyle = low != null && high != null
      ? `left:${pct(low).toFixed(1)}%; right:${(100 - pct(high)).toFixed(1)}%`
      : null;

    card.innerHTML = `
      <div class="cardhead">
        <div><h3>${escapeHtml(plant.name)}</h3>
        <div class="sub">${escapeHtml(plant.species || plant.zone)}${plant.location ? " &middot; " + escapeHtml(plant.location) : ""}</div></div>
        <span class="spacer"></span>
        <span class="pill ${status.cls}"><span class="dot"></span>${status.label}</span>
      </div>
      <div class="meter">
        <div class="meterrow">
          <span class="bignum ${staleSeconds > 300 ? "stale" : ""}">${moisture ? Math.round(moisture.value) : "&ndash;"}</span>
          <span class="unit">${moisture ? "counts" + (staleSeconds > 300 ? " &middot; " + fmtAge(staleSeconds) : "") : "no reading yet"}</span>
        </div>
        <div class="track">
          ${bandStyle ? `<div class="band" style="${bandStyle}"></div>` : ""}
          <div class="fill ${staleSeconds > 300 ? "stale" : ""}" style="width:${trackFill}%"></div>
        </div>
        <div class="ticks"><span>${Math.round(axisMin)}</span><span>${low != null ? low + " · " + high : ""}</span><span>${Math.round(axisMax)}</span></div>
      </div>
      <div class="kvs">
        <div class="kv"><div class="k">Soil temp</div><div class="v">${soilTemp ? cToDisplay(soilTemp.value).toFixed(1) + " °" + unit : "&ndash;"}</div></div>
        <div class="kv"><div class="k">Reading age</div><div class="v">${moisture ? fmtAge(ageSeconds(moisture.at)) : "never"}</div></div>
      </div>
      <div class="actions">
        <button class="btn primary" data-water="${escapeHtml(plant.zone)}">Water zone now</button>
        <button class="btn" data-history="${escapeHtml(plant.slug)}">History</button>
      </div>
      <div class="guardnote">Manual actions pass the same guards as automatic ones.</div>
      <details class="settings">
        <summary>Edit thresholds</summary>
        <form class="settingsform" data-plant="${escapeHtml(plant.slug)}">
          <label>Moisture low<input type="number" name="moisture_low" value="${low != null ? low : ""}" step="any"></label>
          <label>Moisture high<input type="number" name="moisture_high" value="${high != null ? high : ""}" step="any"></label>
          <label>DLI target (mol)<input type="number" name="dli_target_moles" value="${plant.dli_target_moles != null ? plant.dli_target_moles : ""}" step="any"></label>
          <span></span>
          <div class="full"><button type="submit" class="btn primary" style="flex:none">Save</button></div>
        </form>
      </details>
    `;
    return card;
  }

  async function renderPlants() {
    const container = document.getElementById("plant-cards");
    container.innerHTML = "";
    if (!model.plants.length) {
      container.innerHTML = `<div class="empty">No plants configured yet. Add one to config/plants.toml.</div>`;
      return;
    }
    for (const plant of model.plants) {
      container.appendChild(await renderPlantCard(plant));
    }

    // stale-sensor banner: any plant whose soil reading is >5min old
    let staleName = null;
    for (const plant of model.plants) {
      const ch = channelForPlantRole(plant.slug, "soil_moisture");
      if (!ch) continue;
      const latest = await latestFor(ch.id);
      if (!latest || ageSeconds(latest.at) > 300) {
        staleName = plant.name;
        break;
      }
    }
    const banner = document.getElementById("stale-banner");
    if (staleName) {
      document.getElementById("stale-banner-text").innerHTML =
        `<b>${escapeHtml(staleName)}'s soil sensor has gone quiet.</b> Its moisture value is being ignored rather than trusted.`;
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }

    renderZoneCards();
  }

  function renderZoneCards() {
    const container = document.getElementById("zone-cards");
    container.innerHTML = "";
    for (const zone of model.zones) {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <div class="meterrow" style="margin-bottom:9px">
          <span class="bignum">${escapeHtml(zone.name)}</span>
          <span class="unit">budget ${zone.daily_budget_seconds}s/day &middot; window ${String(zone.watering_start_hour).padStart(2, "0")}:00&ndash;${String(zone.watering_end_hour).padStart(2, "0")}:00</span>
        </div>
        <div class="footnote">The budget is a ceiling, not a target. A guard may shorten a pulse
        or refuse it; nothing can lengthen one.</div>
        <details class="settings">
          <summary>Edit zone settings</summary>
          <form class="settingsform" data-zone="${escapeHtml(zone.slug)}">
            <label>Daily budget (s)<input type="number" name="daily_budget_seconds" value="${zone.daily_budget_seconds}" step="any"></label>
            <label>Max pulses/hour<input type="number" name="max_pulses_per_hour" value="${zone.max_pulses_per_hour}" step="1"></label>
            <label>Window start (hr)<input type="number" name="watering_start_hour" value="${zone.watering_start_hour}" min="0" max="23"></label>
            <label>Window end (hr)<input type="number" name="watering_end_hour" value="${zone.watering_end_hour}" min="0" max="23"></label>
            <div class="full"><button type="submit" class="btn primary" style="flex:none">Save</button></div>
          </form>
        </details>
      `;
      container.appendChild(card);
    }
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  // ---------------------------------------------------------------------
  // settings forms (UI-3)
  // ---------------------------------------------------------------------

  function numOrNull(form, name) {
    const raw = form.elements[name].value;
    return raw === "" ? null : Number(raw);
  }

  document.addEventListener("submit", async (ev) => {
    const form = ev.target;
    if (form.dataset.plant) {
      ev.preventDefault();
      const slug = form.dataset.plant;
      const body = {
        moisture_low: numOrNull(form, "moisture_low"),
        moisture_high: numOrNull(form, "moisture_high"),
        dli_target_moles: numOrNull(form, "dli_target_moles"),
      };
      try {
        await api(`/plants/${encodeURIComponent(slug)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        toast("Saved");
        renderPlants();
      } catch (err) {
        toast("Could not save: " + err.message);
      }
    } else if (form.dataset.zone) {
      ev.preventDefault();
      const slug = form.dataset.zone;
      const body = {
        daily_budget_seconds: numOrNull(form, "daily_budget_seconds"),
        max_pulses_per_hour: numOrNull(form, "max_pulses_per_hour"),
        watering_start_hour: numOrNull(form, "watering_start_hour"),
        watering_end_hour: numOrNull(form, "watering_end_hour"),
      };
      try {
        await api(`/zones/${encodeURIComponent(slug)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        toast("Saved");
        loadModel().then(() => renderZoneCards());
      } catch (err) {
        toast("Could not save: " + err.message);
      }
    }
  });

  // ---------------------------------------------------------------------
  // manual actions (ARCH-3)
  // ---------------------------------------------------------------------

  document.addEventListener("click", async (ev) => {
    const waterBtn = ev.target.closest("[data-water]");
    if (waterBtn) {
      const zone = waterBtn.dataset.water;
      waterBtn.disabled = true;
      try {
        await api(`/zones/${encodeURIComponent(zone)}/commands`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "water_now" }),
        });
        toast("Queued — the control loop will run it on the next tick, guards permitting");
      } catch (err) {
        toast("Could not queue: " + err.message);
      } finally {
        waterBtn.disabled = false;
      }
      return;
    }
    const historyBtn = ev.target.closest("[data-history]");
    if (historyBtn) {
      selectTab("history");
    }
  });

  // ---------------------------------------------------------------------
  // history (UI-6)
  // ---------------------------------------------------------------------

  async function fetchSeries(channelId, hours) {
    const { start, end } = isoRange(hours, 0);
    return api(`/channels/${channelId}/timeseries?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
  }

  async function fetchEvents(zoneSlug, hours) {
    const { start, end } = isoRange(hours, 0);
    const rows = await api(
      `/zones/${encodeURIComponent(zoneSlug)}/actuations?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`
    ).catch(() => []);
    return rows.map((r) => new Date(r.at));
  }

  function pointsOf(series) {
    if (series.tier === "raw") return series.raw.map((p) => ({ t: new Date(p.ts), v: p.value }));
    return series.rollup.map((p) => ({ t: new Date(p.ts), v: p.mean }));
  }

  async function renderHistory() {
    const container = document.getElementById("history-charts");
    container.innerHTML = "";
    const tierPill = document.getElementById("range-tier-pill");

    const targets = [];
    for (const plant of model.plants) {
      const ch = channelForPlantRole(plant.slug, "soil_moisture");
      if (ch) targets.push({ title: `${plant.name} soil moisture`, sub: `Capacitance counts${plant.moisture_low != null ? ` · target band ${plant.moisture_low}–${plant.moisture_high}` : ""}`, channel: ch, band: plant.moisture_low != null && plant.moisture_high != null ? [plant.moisture_low, plant.moisture_high] : null, zone: plant.zone });
    }
    for (const zone of model.zones) {
      const light = channelForZoneRole(zone.slug, "light");
      if (light) targets.push({ title: "Light", sub: "Measured illuminance", channel: light, band: null, zone: zone.slug });
      const vpd = channelForZoneRole(zone.slug, "vpd");
      if (vpd) targets.push({ title: "Vapour pressure deficit", sub: "Derived from air temperature and humidity", channel: vpd, band: null, zone: zone.slug });
    }

    if (!targets.length) {
      container.innerHTML = `<div class="empty">No channels reporting yet.</div>`;
      return;
    }

    let firstTier = null;
    for (const t of targets) {
      const card = document.createElement("div");
      card.className = "card lift";
      card.style.marginTop = "12px";
      const chartId = "chart-" + Math.random().toString(36).slice(2);
      const tipId = "tip-" + chartId;
      card.innerHTML = `
        <div class="cardhead"><div><h3>${escapeHtml(t.title)}</h3><div class="sub">${t.sub}</div></div></div>
        <div class="chartbox">
          <div class="chartwrap"><svg class="chart" id="${chartId}" viewBox="0 0 660 210"></svg></div>
          <div class="tip" id="${tipId}"></div>
        </div>
      `;
      container.appendChild(card);

      const series = await fetchSeries(t.channel.id, rangeHours);
      if (!firstTier) firstTier = series.tier;
      const points = pointsOf(series);
      const events = await fetchEvents(t.zone, rangeHours);
      drawChart(document.getElementById(chartId), {
        points, band: t.band, events, tipEl: document.getElementById(tipId),
      });
    }
    if (firstTier) tierPill.textContent = firstTier.replace("_", " ") + " resolution";
  }

  // ---------------------------------------------------------------------
  // chart drawing -- adapted from docs/dashboard.html, fed real points
  // ---------------------------------------------------------------------

  const W = 660, H = 210, PAD = { t: 14, r: 46, b: 26, l: 46 };
  const plotW = W - PAD.l - PAD.r, plotH = H - PAD.t - PAD.b;

  function niceTicks(lo, hi, count) {
    const span = hi - lo, raw = span / count || 1;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
    return out;
  }

  function svgEl(tag, attrs, text) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (text != null) el.textContent = text;
    return el;
  }

  function drawChart(svg, opts) {
    svg.textContent = "";
    const { points, band, events, tipEl } = opts;
    if (!points.length) {
      svg.appendChild(svgEl("text", { class: "tick", x: W / 2, y: H / 2, "text-anchor": "middle" }, "No data in this range"));
      return;
    }
    const t0 = points[0].t.getTime(), t1 = points[points.length - 1].t.getTime() || t0 + 1;
    const values = points.map((p) => p.v);
    let lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
    if (band) { lo = Math.min(lo, band[0]); hi = Math.max(hi, band[1]); }
    const pad = (hi - lo) * 0.12 || 1;
    lo -= pad; hi += pad;

    const x = (t) => PAD.l + ((t - t0) / Math.max(1, t1 - t0)) * plotW;
    const y = (v) => PAD.t + plotH - ((v - lo) / (hi - lo)) * plotH;

    if (band) {
      svg.appendChild(svgEl("rect", { class: "bandfill", x: PAD.l, y: y(band[1]), width: plotW, height: Math.max(0, y(band[0]) - y(band[1])) }));
      [band[0], band[1]].forEach((v) => svg.appendChild(svgEl("line", { class: "bandedge", x1: PAD.l, x2: PAD.l + plotW, y1: y(v), y2: y(v) })));
    }

    niceTicks(lo, hi, 4).forEach((v) => {
      svg.appendChild(svgEl("line", { class: "gridline", x1: PAD.l, x2: PAD.l + plotW, y1: y(v), y2: y(v) }));
      svg.appendChild(svgEl("text", { class: "tick", x: PAD.l - 8, y: y(v) + 3.5, "text-anchor": "end" }, v >= 1000 ? (v / 1000).toFixed(1) + "k" : Math.round(v)));
    });
    svg.appendChild(svgEl("line", { class: "axis", x1: PAD.l, x2: PAD.l + plotW, y1: PAD.t + plotH, y2: PAD.t + plotH }));

    const labelEvery = Math.max(1, Math.floor(points.length / 6));
    points.forEach((p, i) => {
      if (i % labelEvery === 0) {
        svg.appendChild(svgEl("text", { class: "tick", x: x(p.t.getTime()), y: H - 9, "text-anchor": "middle" }, fmtClock(p.t)));
      }
    });

    (events || []).forEach((evTime) => {
      const cx = x(evTime.getTime());
      svg.appendChild(svgEl("line", { class: "evtline", x1: cx, x2: cx, y1: PAD.t, y2: PAD.t + plotH }));
      const cy = PAD.t + plotH;
      svg.appendChild(svgEl("polygon", { class: "evt", points: `${cx},${cy - 8} ${cx - 5},${cy} ${cx + 5},${cy}` }));
    });

    let d = "";
    points.forEach((p) => { d += (d ? "L" : "M") + x(p.t.getTime()).toFixed(1) + " " + y(p.v).toFixed(1); });
    const last = points[points.length - 1];
    const area = d + `L${x(last.t.getTime()).toFixed(1)} ${PAD.t + plotH}L${PAD.l} ${PAD.t + plotH}Z`;
    svg.appendChild(svgEl("path", { class: "areafill", d: area }));
    svg.appendChild(svgEl("path", { class: "series", d }));
    svg.appendChild(svgEl("circle", { class: "cursordot", cx: x(last.t.getTime()), cy: y(last.v), r: 4 }));

    const cross = svgEl("line", { class: "crosshair", x1: 0, x2: 0, y1: PAD.t, y2: PAD.t + plotH, opacity: 0 });
    const dot = svgEl("circle", { class: "cursordot", r: 4, opacity: 0 });
    svg.appendChild(cross); svg.appendChild(dot);

    function move(ev) {
      const box = svg.getBoundingClientRect();
      const px = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - box.left) / box.width * W;
      const targetT = t0 + ((px - PAD.l) / plotW) * (t1 - t0);
      let nearest = points[0], nearestDist = Infinity;
      for (const p of points) {
        const dist = Math.abs(p.t.getTime() - targetT);
        if (dist < nearestDist) { nearest = p; nearestDist = dist; }
      }
      const cx = x(nearest.t.getTime()), cy = y(nearest.v);
      cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("opacity", 1);
      dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.setAttribute("opacity", 1);
      tipEl.innerHTML = `<div class="t">${fmtClock(nearest.t)}</div><div class="v">${nearest.v.toFixed(1)}</div>`;
      tipEl.style.opacity = 1;
      const left = (cx / W) * box.width;
      tipEl.style.left = Math.max(4, Math.min(box.width - 96, left - 40)) + "px";
      tipEl.style.top = ((cy / H) * box.height - 52) + "px";
    }
    function leave() { cross.setAttribute("opacity", 0); dot.setAttribute("opacity", 0); tipEl.style.opacity = 0; }
    svg.addEventListener("mousemove", move);
    svg.addEventListener("touchmove", move, { passive: true });
    svg.addEventListener("mouseleave", leave);
    svg.addEventListener("touchend", leave);
  }

  document.getElementById("range-chips").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-hours]");
    if (!btn) return;
    document.querySelectorAll("#range-chips button").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    rangeHours = Number(btn.dataset.hours);
    renderHistory();
  });

  // ---------------------------------------------------------------------
  // health (SENS-8, DATA-4 -- the one view that names hardware)
  // ---------------------------------------------------------------------

  function renderHealth() {
    const nodesEl = document.getElementById("health-nodes");
    nodesEl.innerHTML = model.health.nodes.map((n) => `
      <div class="row">
        <div><div class="name">${escapeHtml(n.slug)}</div><div class="meta">${escapeHtml(n.kind)}${n.description ? " · " + escapeHtml(n.description) : ""}</div></div>
        <span class="spacer"></span>
        <span class="pill ${n.online ? "good" : "warn"}"><span class="dot"></span>${n.online ? "Online" : "Offline"}${n.last_seen_at ? " · " + fmtAge(ageSeconds(new Date(n.last_seen_at))) : ""}</span>
      </div>
    `).join("") || `<div class="empty">No nodes configured.</div>`;

    const sensorsEl = document.getElementById("health-sensors");
    sensorsEl.innerHTML = model.health.sensors.map((s) => {
      const addr = s.address != null ? "0x" + s.address.toString(16) : "—";
      const mux = s.mux_address != null ? ` · mux 0x${s.mux_address.toString(16)} ch${s.mux_channel}` : "";
      return `
      <div class="row">
        <div><div class="name">${escapeHtml(s.slug)}</div><div class="meta">${escapeHtml(s.driver)} · ${addr}${mux} · every ${s.interval_seconds}s</div></div>
        <span class="spacer"></span>
        <span class="pill ${s.enabled ? "good" : "warn"}"><span class="dot"></span>${s.enabled ? "Enabled" : "Disabled"}</span>
      </div>`;
    }).join("") || `<div class="empty">No sensors configured.</div>`;

    const offlineCount = model.health.nodes.filter((n) => !n.online).length;
    for (const id of ["health-badge-side", "health-badge-tab"]) {
      const badge = document.getElementById(id);
      badge.textContent = String(offlineCount);
      badge.hidden = offlineCount === 0;
    }

    const livePill = document.getElementById("live-pill");
    const liveDetail = document.getElementById("live-detail");
    const anyOnline = model.health.nodes.some((n) => n.online);
    livePill.className = "pill " + (anyOnline ? "good" : "warn");
    liveDetail.textContent = model.health.nodes.length
      ? model.health.nodes.map((n) => n.slug + (n.last_seen_at ? " · " + fmtAge(ageSeconds(new Date(n.last_seen_at))) : " · never seen")).join(", ")
      : "no nodes yet";
  }

  // ---------------------------------------------------------------------
  // decision log (CTRL-8)
  // ---------------------------------------------------------------------

  async function renderLog() {
    const feed = document.getElementById("log-feed");
    feed.innerHTML = "";
    let all = [];
    for (const zone of model.zones) {
      const decisions = await api(`/zones/${encodeURIComponent(zone.slug)}/decisions?limit=30`).catch(() => []);
      all = all.concat(decisions.map((d) => ({ ...d, zoneName: zone.name })));
    }
    all.sort((a, b) => new Date(b.at) - new Date(a.at));
    if (!all.length) {
      feed.innerHTML = `<div class="empty">No decisions logged yet.</div>`;
      return;
    }
    const kindPill = { act: "good", no_action: "info", blocked: "crit", insufficient_data: "warn" };
    feed.innerHTML = all.slice(0, 40).map((d) => `
      <div class="entry">
        <div class="when">${fmtClock(new Date(d.at))}</div>
        <div class="what">
          <div class="head"><span class="pill ${kindPill[d.kind] || "info"}">${d.kind.replace("_", " ")}</span><span class="who">${escapeHtml(d.zoneName)}</span></div>
          <div class="reason">${escapeHtml(d.reason)}</div>
        </div>
      </div>
    `).join("");
  }

  // ---------------------------------------------------------------------
  // navigation
  // ---------------------------------------------------------------------

  function selectTab(tab) {
    document.querySelectorAll('[role="tab"][data-tab]').forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === tab));
    if (tab === "history" && model) renderHistory();
  }
  document.querySelectorAll('[role="tab"][data-tab]').forEach((btn) => {
    btn.addEventListener("click", () => selectTab(btn.dataset.tab));
  });

  document.getElementById("unit").addEventListener("click", () => {
    unit = unit === "C" ? "F" : "C";
    document.getElementById("unit").textContent = "°" + unit;
    renderHero();
    renderPlants();
  });

  let toastTimer;
  function toast(msg) {
    const t = document.getElementById("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 3200);
  }

  // ---------------------------------------------------------------------
  // boot + refresh
  // ---------------------------------------------------------------------

  async function refresh() {
    try {
      await loadModel();
      await renderHero();
      await renderPlants();
      await renderHealth();
      await renderLog();
      if (document.querySelector('.panel[data-panel="history"]').classList.contains("active")) {
        await renderHistory();
      }
    } catch (err) {
      const detail = document.getElementById("live-detail");
      if (detail) detail.textContent = "offline — showing last known state";
      const pill = document.getElementById("live-pill");
      if (pill) pill.className = "pill warn";
    }
  }

  refresh();
  setInterval(refresh, REFRESH_MS);

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }
})();
