// Auswertung des Request-Logs als Kennzahlen-Cockpit, Spec: docs/specs/request-log-auswertung.md.
// Rechnet nichts selbst, sondern zeichnet die Antwort von /api/report (Form im Docstring von
// app/fidelius/log_report.py). Alles aus dem Log und aus der URL geht escaped ins HTML.
"use strict";
(() => {
  const PERIODS = [["24h", "24 h"], ["7d", "7 Tage"], ["30d", "30 Tage"], ["all", "alles"]];
  const DEFAULT_PERIOD = "30d";
  const COLORS = 7; // --c1 … --c7 in style.css
  const PHASES = [["gate", "Gate"], ["detection", "Erkennung"], ["laya", "Laya"], ["total", "Gesamt"]];

  // Nur Werte aus der festen Liste; alles andere fällt auf 30 Tage zurück.
  const fromUrl = new URLSearchParams(location.search).get("period");
  let period = PERIODS.some(([key]) => key === fromUrl) ? fromUrl : DEFAULT_PERIOD;

  // ---------- Formatierung ----------
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const isNumber = (v) => typeof v === "number" && Number.isFinite(v);
  const numberFormat = new Intl.NumberFormat("de-DE");
  const integer = (v) => isNumber(v) ? numberFormat.format(Math.round(v)) : "–";
  const ms = (v) => !isNumber(v) ? "–" : v < 1000 ? `${Math.round(v)} ms`
    : `${(v / 1000).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`;
  const percent = (v) => isNumber(v) ? `${(v * 100).toLocaleString("de-DE", { maximumFractionDigits: 1 })} %` : "–";
  // Zeiten kommen schon in Berliner Zeit als ISO 8601, deshalb reicht Zerlegen statt Umrechnen.
  const shortDay = (iso) => `${String(iso).slice(8, 10)}.${String(iso).slice(5, 7)}.`;
  const dateTime = (iso) => `${shortDay(iso)} ${String(iso).slice(11, 16)} Uhr`;
  const color = (i) => `var(--c${(i % COLORS) + 1})`;
  const empty = (text = "Keine Daten im Zeitraum.") => `<p class="hint">${text}</p>`;

  // ---------- Trend zur Vorperiode ----------
  // direction: 1 = höher ist schlechter, -1 = höher ist besser, 0 = weder noch.
  // Anteile vergleicht der Trend in Prozentpunkten, alles andere relativ.
  function trend(current, previous, direction, share = false) {
    if (!isNumber(current) || !isNumber(previous) || (!share && previous === 0)) return `<span class="muted">kein Vergleich</span>`;
    const delta = share ? current - previous : (current - previous) / previous;
    const text = share
      ? `${(Math.abs(delta) * 100).toLocaleString("de-DE", { maximumFractionDigits: 1 })} Pp.`
      : percent(Math.abs(delta));
    if (Math.abs(delta) < (share ? 0.001 : 0.02)) return `<span class="muted">± 0 ${share ? "Pp." : "%"} zur Vorperiode</span>`;
    const cls = direction === 0 ? "muted" : (delta > 0) === (direction > 0) ? "worse" : "better";
    return `<span class="${cls}">${delta > 0 ? "▲" : "▼"} ${text}</span> <span class="muted">zur Vorperiode</span>`;
  }

  // ---------- SVG-Diagramme ----------
  const W = 600;

  function bars(items, { height = 140, every = 1 } = {}) {
    if (!items.length) return empty();
    const padLeft = 22, max = Math.max(1, ...items.map((item) => item.value)), barWidth = (W - padLeft) / items.length;
    const parts = items.map((item, i) => {
      const barHeight = (height - 30) * item.value / max, x = padLeft + i * barWidth;
      const tick = i % every === 0 && item.short !== "" ? `<text x="${x + barWidth / 2}" y="${height - 4}" text-anchor="middle">${esc(item.short ?? item.label)}</text>` : "";
      return `<g><title>${esc(item.label)}: ${integer(item.value)}</title>
        <rect class="bar" x="${x + 1}" y="${height - 18 - barHeight}" width="${Math.max(1, barWidth - 2)}" height="${barHeight}" rx="2"/>
        <rect x="${x}" y="0" width="${barWidth}" height="${height}" fill="transparent"/>${tick}</g>`;
    }).join("");
    return `<svg class="chart" viewBox="0 0 ${W} ${height}" role="img">
      <line class="axis" x1="${padLeft}" x2="${W}" y1="${height - 18}" y2="${height - 18}"/>
      <text x="${padLeft - 4}" y="10" text-anchor="end">${integer(max)}</text>${parts}</svg>`;
  }

  function histogram(hist, markers, height = 140) {
    const counts = hist.counts || [];
    if (!counts.length) return empty();
    if (!isNumber(hist.width_ms)) return empty(`Alle ${integer(counts[0])} Anfragen mit 0 ms.`);
    const padLeft = 22, barWidth = (W - padLeft) / counts.length, top = Math.max(1, ...counts), upper = hist.max_ms;
    const rects = counts.map((count, i) => {
      const barHeight = (height - 30) * count / top;
      const range = i === counts.length - 1 ? `ab ${ms(i * hist.width_ms)}` : `${ms(i * hist.width_ms)}–${ms((i + 1) * hist.width_ms)}`;
      return `<rect class="bar" x="${padLeft + i * barWidth + 1}" y="${height - 18 - barHeight}" width="${barWidth - 2}" height="${barHeight}" rx="2"><title>${range}: ${integer(count)}</title></rect>`;
    }).join("");
    const axis = [0, 0.25, 0.5, 0.75, 1].map((f) =>
      `<text x="${padLeft + f * (W - padLeft)}" y="${height - 4}" text-anchor="${f === 1 ? "end" : "middle"}">${ms(f * upper)}</text>`).join("");
    const refs = markers.filter(([v]) => isNumber(v)).map(([v, label], i) => {
      const x = padLeft + Math.min(v, upper) / upper * (W - padLeft);
      return `<line class="ref" x1="${x}" x2="${x}" y1="${i * 11}" y2="${height - 18}"><title>${label}: ${ms(v)}</title></line>
        <text class="mark" x="${x + 3}" y="${10 + i * 11}">${label}</text>`;
    }).join("");
    return `<svg class="chart" viewBox="0 0 ${W} ${height}" role="img">${rects}
      <line class="axis" x1="${padLeft}" x2="${W}" y1="${height - 18}" y2="${height - 18}"/>${axis}${refs}</svg>
      <p class="hint">Abgeschnitten bei p99 (${ms(upper)}), längere Anfragen zählen im letzten Balken.</p>`;
  }

  // Anteile kommen fertig aus phase_bar: bezogen auf den Gesamtmedian, Rest als „übrige“.
  const BAR_PHASES = { gate: ["Gate", 0], detection: ["Erkennung", 1], laya: ["Laya", 2], other: ["übrige", COLORS - 1] };

  function phaseBar(parts) {
    const known = (parts || []).filter((p) => BAR_PHASES[p.phase] && isNumber(p.share));
    if (!known.some((p) => p.share > 0)) return empty();
    let x = 0;
    const rects = known.map((p) => {
      const [label, colorIndex] = BAR_PHASES[p.phase], width = W * p.share;
      const rect = `<rect x="${x}" y="0" width="${width}" height="22" style="fill:${color(colorIndex)}"><title>${label}: ${ms(p.median_ms)}</title></rect>`
        + (width > 110 ? `<text x="${x + 4}" y="34">${label} ${ms(p.median_ms)}</text>` : "");
      x += width;
      return rect;
    }).join("");
    return `<svg class="chart" viewBox="0 0 ${W} 38" role="img">${rects}</svg>
      <div class="legendrow">${known.map((p) => `<span><i style="background:${color(BAR_PHASES[p.phase][1])}"></i>${BAR_PHASES[p.phase][0]}</span>`).join("")}</div>
      <p class="hint">Anteile am Median der Gesamtzeit. Die Phasen-Mediane stammen aus verschieden vielen Anfragen; „übrige“ ist der Rest bis zum Gesamtmedian.</p>`;
  }

  // Nearest-Rank wie im Backend; nur für die Achsen, damit Ausreißer die Skala nicht stauchen.
  const p99 = (values) => { const s = [...values].sort((a, b) => a - b); return s[Math.max(0, Math.ceil(0.99 * s.length) - 1)]; };

  function scatter(points, builds, height = 260) {
    const valid = points.filter((p) => isNumber(p[0]) && isNumber(p[1]));
    if (!valid.length) return empty();
    const padLeft = 44, padBottom = 20;
    const xMax = p99(valid.map((p) => p[0])) || 1, yMax = p99(valid.map((p) => p[1])) || 1;
    const index = new Map(builds.map((b, i) => [b.name, i]));
    const circles = valid.map(([chars, total, build]) => {
      const cx = padLeft + Math.min(1, chars / xMax) * (W - padLeft), cy = height - padBottom - Math.min(1, total / yMax) * (height - padBottom - 6);
      return `<circle cx="${cx}" cy="${cy}" r="2.4" style="fill:${color(index.get(build) ?? COLORS - 1)}" fill-opacity=".6"><title>${integer(chars)} Zeichen, ${ms(total)}, ${esc(build)}</title></circle>`;
    }).join("");
    const ticks = [0, 0.25, 0.5, 0.75, 1];
    const visible = builds.filter((b) => valid.some((p) => p[2] === b.name));
    return `<svg class="chart" viewBox="0 0 ${W} ${height}" role="img">
      <line class="axis" x1="${padLeft}" x2="${W}" y1="${height - padBottom}" y2="${height - padBottom}"/><line class="axis" x1="${padLeft}" x2="${padLeft}" y1="0" y2="${height - padBottom}"/>
      ${ticks.map((v) => `<text x="${padLeft + v * (W - padLeft)}" y="${height - 6}" text-anchor="${v === 1 ? "end" : "middle"}">${integer(v * xMax)}</text>`).join("")}
      ${ticks.map((v) => `<text x="${padLeft - 4}" y="${height - padBottom - v * (height - padBottom - 6) + 3}" text-anchor="end">${ms(v * yMax)}</text>`).join("")}
      <text x="${W}" y="${height - padBottom - 4}" text-anchor="end">Zeichen →</text>${circles}</svg>
      <div class="legendrow">${visible.map((b) => `<span><i style="background:${color(index.get(b.name))}"></i>${esc(b.name)}</span>`).join("")}</div>`;
  }

  // ---------- Tabellen ----------
  const numCell = (v) => `<td class="num">${v}</td>`;

  const phaseTable = (phases) => `<table><thead><tr><th>Phase</th><th class="num">Anfragen</th><th class="num">Median</th><th class="num">p90</th><th class="num">p99</th></tr></thead><tbody>
    ${PHASES.map(([key, label]) => { const p = phases[key] || {}; return `<tr><td>${label}</td>${numCell(integer(p.count))}${numCell(ms(p.median_ms))}${numCell(ms(p.p90_ms))}${numCell(ms(p.p99_ms))}</tr>`; }).join("")}
    </tbody></table>`;

  const lengthTable = (classes, pageChars) => `<table><thead><tr><th>Textlänge</th><th class="num">Anfragen</th><th class="num">Median</th><th class="num">p90</th></tr></thead><tbody>
    ${classes.map((c) => `<tr><td>${esc(c.label)}</td>${numCell(integer(c.count))}${numCell(ms(c.median_ms))}${numCell(ms(c.p90_ms))}</tr>`).join("")}
    </tbody></table><p class="hint">Eine Seite sind ${integer(pageChars)} Zeichen.</p>`;

  function change(delta) {
    if (!isNumber(delta)) return "";
    const cls = delta > 0.02 ? "worse" : delta < -0.02 ? "better" : "muted";
    return `<span class="${cls}">${delta > 0 ? "+" : delta < 0 ? "−" : ""}${percent(Math.abs(delta))}</span>`;
  }

  function buildTable(builds) {
    if (!builds.length) return empty();
    const rows = builds.map((b, i) => `<tr><td><i class="punkt" style="background:${color(i)}"></i>${esc(b.name)}</td>
      <td>${esc(shortDay(b.first))}–${esc(shortDay(b.last))}</td>
      ${numCell(integer(b.requests))}${numCell(ms(b.median_ms))}${numCell(ms(b.p90_ms))}${numCell(ms(b.per_1000_median_ms))}${numCell(change(b.change_vs_previous))}</tr>`).join("");
    return `<table><thead><tr><th>Build</th><th>im Log</th><th class="num">Anfragen</th><th class="num">Median</th><th class="num">p90</th><th class="num">je 1.000 Z.</th><th class="num">zum Vorgänger</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <p class="hint">„*“ = Build mit lokalen Änderungen. Verglichen wird der Median je 1.000 Zeichen, weil die Texte unterschiedlich lang sind.</p>`;
  }

  function calibrationTable(calibration) {
    if (!calibration.rows?.length) return empty("Keine Kalibrierläufe im Zeitraum.");
    return `<table><thead><tr><th>Build</th>${calibration.texts.map((chars) => `<th class="num">${integer(chars)} Z.</th>`).join("")}<th class="num">Läufe</th></tr></thead><tbody>
      ${calibration.rows.map((row) => `<tr><td>${esc(row.build)}</td>${row.median_ms.map((v) => numCell(ms(v))).join("")}${numCell(integer(row.runs))}</tr>`).join("")}
      </tbody></table><p class="hint">Median der Gesamtzeit je Kalibriertext. Gleicher Text, also direkt zwischen Builds vergleichbar.</p>`;
  }

  const errorTable = (errors) => errors.length
    ? `<table><thead><tr><th>Fehler</th><th class="num">Anzahl</th><th>zuletzt</th></tr></thead><tbody>
      ${errors.map((e) => `<tr><td>${esc(e.text)}</td>${numCell(integer(e.count))}<td>${esc(dateTime(e.last))}</td></tr>`).join("")}</tbody></table>`
    : empty("Keine Fehler im Zeitraum.");

  // ---------- Seite ----------
  const periodPicker = () => `<span class="seg">${PERIODS.map(([key, label]) =>
    `<button data-period="${key}" class="${key === period ? "on" : ""}">${label}</button>`).join("")}</span>`;

  // Titel links, darunter optional die Zeile zum Log; rechts die Zeitraumwahl.
  const header = (info = "") => `<div class="top">
      <div><h1>Auswertung Request-Log</h1>${info}</div>
      ${periodPicker()}
    </div>`;

  function logLine(log) {
    const parts = [`${integer(log.lines)} Zeilen`];
    if (log.broken) parts.push(`<span class="worse">${integer(log.broken)} kaputte Zeilen übersprungen</span>`);
    parts.push(`<a href="/api/request-log" download="requests.jsonl">Rohlog laden</a>`);
    return parts.join(" · ");
  }

  const tile = (title, content, wide = false) => `<div class="tile${wide ? " wide" : ""}"><h2>${title}</h2>${content}</div>`;
  const kpi = (label, value, trendHtml) => `<div class="kpi"><div class="k">${label}</div><div class="v">${value}</div><div class="t">${trendHtml}</div></div>`;

  function page(data) {
    if (!data.log.present) {
      return `${header()}
        <div class="tile leer"><h2>Kein Request-Log vorhanden</h2><p class="hint">Erwartet unter <code>${esc(data.log.path)}</code>. Die Datei fehlt oder ist leer.</p></div>`;
    }
    const metrics = data.metrics, previous = data.previous || {};
    const calibrationRuns = (data.calibration.rows || []).reduce((s, row) => s + (isNumber(row.runs) ? row.runs : 0), 0);
    const days = data.usage.days || [];
    return `${header(`<span class="hint">${logLine(data.log)}</span>`)}
      <div class="kpis">
        ${kpi("Anfragen", integer(metrics.requests), trend(metrics.requests, previous.requests, -1))}
        ${kpi("Median Gesamtzeit", ms(metrics.total_median_ms), trend(metrics.total_median_ms, previous.total_median_ms, 1))}
        ${kpi("p90 Gesamtzeit", ms(metrics.total_p90_ms), trend(metrics.total_p90_ms, previous.total_p90_ms, 1))}
        ${kpi("je 1.000 Zeichen (Median)", ms(metrics.per_1000_median_ms), trend(metrics.per_1000_median_ms, previous.per_1000_median_ms, 1))}
        ${kpi("Fehlerquote", percent(metrics.error_rate), `${integer(metrics.error_count)} Fehler · ${trend(metrics.error_rate, previous.error_rate, 1, true)}`)}
        ${kpi("als sensibel erkannt", percent(metrics.sensitive_share), trend(metrics.sensitive_share, previous.sensitive_share, 0, true))}
      </div>
      <div class="grid">
        ${tile("Anfragen pro Tag", bars(days.map((d) => ({ label: shortDay(d.day), value: d.count })), { every: Math.ceil(days.length / 15) }))}
        ${tile("Anfragen nach Uhrzeit", bars(data.usage.hours.map((n, i) => ({ label: `${i} Uhr`, short: i % 3 ? "" : String(i), value: n }))))}
        ${tile("Verteilung Gesamtzeit", histogram(data.histogram, [[metrics.total_median_ms, "Median"], [metrics.total_p90_ms, "p90"]]))}
        ${tile("Wohin die Zeit geht (Median)", phaseBar(data.phase_bar) + phaseTable(data.phases))}
        ${tile("Textlänge und Gesamtzeit", scatter(data.scatter, data.builds))}
        ${tile("Nach Textlänge", lengthTable(data.length_classes, data.page_chars))}
        ${tile("Builds", buildTable(data.builds), true)}
        ${tile(`Kalibrierung <span class="muted">· ${integer(calibrationRuns)} Läufe</span>`, calibrationTable(data.calibration))}
        ${tile("Fehler", errorTable(data.errors))}
      </div>`;
  }

  const root = document.getElementById("root");

  async function load() {
    const url = new URL(location.href);
    url.searchParams.set("period", period);
    history.replaceState(null, "", url);
    try {
      const response = await fetch(`/api/report?period=${encodeURIComponent(period)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      root.innerHTML = page(await response.json());
    } catch (e) {
      root.innerHTML = `${header()}
        <div class="errorbox">Auswertung nicht abrufbar: ${esc(e.message)}</div>`;
    }
  }

  root.addEventListener("click", (e) => {
    const button = e.target.closest("[data-period]");
    if (!button || !PERIODS.some(([key]) => key === button.dataset.period)) return;
    period = button.dataset.period;
    load();
  });

  load();
})();
