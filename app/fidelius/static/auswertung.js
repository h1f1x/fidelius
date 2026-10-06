// Auswertung des Request-Logs als Kennzahlen-Cockpit, Spec: docs/specs/request-log-auswertung.md.
// Rechnet nichts selbst, sondern zeichnet die Antwort von /api/auswertung (Form im Docstring von
// app/fidelius/auswertung.py). Alles aus dem Log und aus der URL geht escaped ins HTML.
"use strict";
(() => {
  const ZEITRAEUME = [["24h", "24 h"], ["7t", "7 Tage"], ["30t", "30 Tage"], ["alles", "alles"]];
  const STANDARD = "30t";
  const FARBEN = 7; // --c1 … --c7 in style.css
  const PHASEN = [["gate", "Gate"], ["erkennung", "Erkennung"], ["laya", "Laya"], ["gesamt", "Gesamt"]];

  // Nur Werte aus der festen Liste; alles andere fällt auf 30 Tage zurück.
  const ausUrl = new URLSearchParams(location.search).get("zeitraum");
  let zeitraum = ZEITRAEUME.some(([k]) => k === ausUrl) ? ausUrl : STANDARD;

  // ---------- Formatierung ----------
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const istZahl = (v) => typeof v === "number" && Number.isFinite(v);
  const nf = new Intl.NumberFormat("de-DE");
  const n0 = (v) => istZahl(v) ? nf.format(Math.round(v)) : "–";
  const ms = (v) => !istZahl(v) ? "–" : v < 1000 ? `${Math.round(v)} ms`
    : `${(v / 1000).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`;
  const proz = (v) => istZahl(v) ? `${(v * 100).toLocaleString("de-DE", { maximumFractionDigits: 1 })} %` : "–";
  // Zeiten kommen schon in Berliner Zeit als ISO 8601, deshalb reicht Zerlegen statt Umrechnen.
  const tagKurz = (iso) => `${String(iso).slice(8, 10)}.${String(iso).slice(5, 7)}.`;
  const zeitDe = (iso) => `${tagKurz(iso)} ${String(iso).slice(11, 16)} Uhr`;
  const farbe = (i) => `var(--c${(i % FARBEN) + 1})`;
  const leer = (text = "Keine Daten im Zeitraum.") => `<p class="hint">${text}</p>`;

  // ---------- Trend zur Vorperiode ----------
  // richtung: 1 = höher ist schlechter, -1 = höher ist besser, 0 = weder noch.
  // Anteile vergleicht der Trend in Prozentpunkten, alles andere relativ.
  function trend(akt, vor, richtung, anteil = false) {
    if (!istZahl(akt) || !istZahl(vor) || (!anteil && vor === 0)) return `<span class="muted">kein Vergleich</span>`;
    const d = anteil ? akt - vor : (akt - vor) / vor;
    const text = anteil
      ? `${(Math.abs(d) * 100).toLocaleString("de-DE", { maximumFractionDigits: 1 })} Pp.`
      : proz(Math.abs(d));
    if (Math.abs(d) < (anteil ? 0.001 : 0.02)) return `<span class="muted">± 0 ${anteil ? "Pp." : "%"} zur Vorperiode</span>`;
    const klasse = richtung === 0 ? "muted" : (d > 0) === (richtung > 0) ? "worse" : "better";
    return `<span class="${klasse}">${d > 0 ? "▲" : "▼"} ${text}</span> <span class="muted">zur Vorperiode</span>`;
  }

  // ---------- SVG-Diagramme ----------
  const W = 600;

  function balken(items, { h = 140, every = 1 } = {}) {
    if (!items.length) return leer();
    const pad = 22, max = Math.max(1, ...items.map((i) => i.wert)), bw = (W - pad) / items.length;
    const teile = items.map((it, i) => {
      const bh = (h - 30) * it.wert / max, x = pad + i * bw;
      const marke = i % every === 0 && it.kurz !== "" ? `<text x="${x + bw / 2}" y="${h - 4}" text-anchor="middle">${esc(it.kurz ?? it.label)}</text>` : "";
      return `<g><title>${esc(it.label)}: ${n0(it.wert)}</title>
        <rect class="bar" x="${x + 1}" y="${h - 18 - bh}" width="${Math.max(1, bw - 2)}" height="${bh}" rx="2"/>
        <rect x="${x}" y="0" width="${bw}" height="${h}" fill="transparent"/>${marke}</g>`;
    }).join("");
    return `<svg class="chart" viewBox="0 0 ${W} ${h}" role="img">
      <line class="axis" x1="${pad}" x2="${W}" y1="${h - 18}" y2="${h - 18}"/>
      <text x="${pad - 4}" y="10" text-anchor="end">${n0(max)}</text>${teile}</svg>`;
  }

  function histogramm(hg, marken, h = 140) {
    const anzahl = hg.anzahl || [];
    if (!anzahl.length) return leer();
    if (!istZahl(hg.breite_ms)) return leer(`Alle ${n0(anzahl[0])} Anfragen mit 0 ms.`);
    const pad = 22, bw = (W - pad) / anzahl.length, top = Math.max(1, ...anzahl), bis = hg.bis_ms;
    const rects = anzahl.map((c, i) => {
      const bh = (h - 30) * c / top;
      const bereich = i === anzahl.length - 1 ? `ab ${ms(i * hg.breite_ms)}` : `${ms(i * hg.breite_ms)}–${ms((i + 1) * hg.breite_ms)}`;
      return `<rect class="bar" x="${pad + i * bw + 1}" y="${h - 18 - bh}" width="${bw - 2}" height="${bh}" rx="2"><title>${bereich}: ${n0(c)}</title></rect>`;
    }).join("");
    const achse = [0, 0.25, 0.5, 0.75, 1].map((f) =>
      `<text x="${pad + f * (W - pad)}" y="${h - 4}" text-anchor="${f === 1 ? "end" : "middle"}">${ms(f * bis)}</text>`).join("");
    const refs = marken.filter(([v]) => istZahl(v)).map(([v, label], i) => {
      const x = pad + Math.min(v, bis) / bis * (W - pad);
      return `<line class="ref" x1="${x}" x2="${x}" y1="${i * 11}" y2="${h - 18}"><title>${label}: ${ms(v)}</title></line>
        <text class="mark" x="${x + 3}" y="${10 + i * 11}">${label}</text>`;
    }).join("");
    return `<svg class="chart" viewBox="0 0 ${W} ${h}" role="img">${rects}
      <line class="axis" x1="${pad}" x2="${W}" y1="${h - 18}" y2="${h - 18}"/>${achse}${refs}</svg>
      <p class="hint">Abgeschnitten bei p99 (${ms(bis)}), längere Anfragen zählen im letzten Balken.</p>`;
  }

  function phasenBalken(phasen) {
    const teile = PHASEN.filter(([k]) => k !== "gesamt").map(([k, label], i) => ({ label, i, median: phasen[k]?.median_ms }));
    const summe = teile.reduce((s, p) => s + (istZahl(p.median) ? p.median : 0), 0);
    if (!summe) return leer();
    let x = 0;
    const rects = teile.map((p) => {
      const w = W * (istZahl(p.median) ? p.median : 0) / summe;
      const s = `<rect x="${x}" y="0" width="${w}" height="22" style="fill:${farbe(p.i)}"><title>${p.label}: ${ms(p.median)}</title></rect>`
        + (w > 110 ? `<text x="${x + 4}" y="34">${p.label} ${ms(p.median)}</text>` : "");
      x += w;
      return s;
    }).join("");
    return `<svg class="chart" viewBox="0 0 ${W} 38" role="img">${rects}</svg>
      <div class="legendrow">${teile.map((p) => `<span><i style="background:${farbe(p.i)}"></i>${p.label}</span>`).join("")}</div>`;
  }

  // Nearest-Rank wie im Backend; nur für die Achsen, damit Ausreißer die Skala nicht stauchen.
  const p99 = (werte) => { const s = [...werte].sort((a, b) => a - b); return s[Math.max(0, Math.ceil(0.99 * s.length) - 1)]; };

  function streuung(punkte, builds, h = 260) {
    const ok = punkte.filter((p) => istZahl(p[0]) && istZahl(p[1]));
    if (!ok.length) return leer();
    const pl = 44, pb = 20, xm = p99(ok.map((p) => p[0])) || 1, ym = p99(ok.map((p) => p[1])) || 1;
    const index = new Map(builds.map((b, i) => [b.name, i]));
    const kreise = ok.map(([z, t, b]) => {
      const cx = pl + Math.min(1, z / xm) * (W - pl), cy = h - pb - Math.min(1, t / ym) * (h - pb - 6);
      return `<circle cx="${cx}" cy="${cy}" r="2.4" style="fill:${farbe(index.get(b) ?? FARBEN - 1)}" fill-opacity=".6"><title>${n0(z)} Zeichen, ${ms(t)}, ${esc(b)}</title></circle>`;
    }).join("");
    const f = [0, 0.25, 0.5, 0.75, 1];
    const sichtbar = builds.filter((b) => ok.some((p) => p[2] === b.name));
    return `<svg class="chart" viewBox="0 0 ${W} ${h}" role="img">
      <line class="axis" x1="${pl}" x2="${W}" y1="${h - pb}" y2="${h - pb}"/><line class="axis" x1="${pl}" x2="${pl}" y1="0" y2="${h - pb}"/>
      ${f.map((v) => `<text x="${pl + v * (W - pl)}" y="${h - 6}" text-anchor="${v === 1 ? "end" : "middle"}">${n0(v * xm)}</text>`).join("")}
      ${f.map((v) => `<text x="${pl - 4}" y="${h - pb - v * (h - pb - 6) + 3}" text-anchor="end">${ms(v * ym)}</text>`).join("")}
      <text x="${W}" y="${h - pb - 4}" text-anchor="end">Zeichen →</text>${kreise}</svg>
      <div class="legendrow">${sichtbar.map((b) => `<span><i style="background:${farbe(index.get(b.name))}"></i>${esc(b.name)}</span>`).join("")}</div>`;
  }

  // ---------- Tabellen ----------
  const zahl = (v) => `<td class="num">${v}</td>`;

  const tPhasen = (phasen) => `<table><thead><tr><th>Phase</th><th class="num">Anfragen</th><th class="num">Median</th><th class="num">p90</th><th class="num">p99</th></tr></thead><tbody>
    ${PHASEN.map(([k, label]) => { const p = phasen[k] || {}; return `<tr><td>${label}</td>${zahl(n0(p.anzahl))}${zahl(ms(p.median_ms))}${zahl(ms(p.p90_ms))}${zahl(ms(p.p99_ms))}</tr>`; }).join("")}
    </tbody></table>`;

  const tKlassen = (klassen) => `<table><thead><tr><th>Textlänge</th><th class="num">Anfragen</th><th class="num">Median</th><th class="num">p90</th></tr></thead><tbody>
    ${klassen.map((k) => `<tr><td>${esc(k.label)}</td>${zahl(n0(k.anzahl))}${zahl(ms(k.median_ms))}${zahl(ms(k.p90_ms))}</tr>`).join("")}
    </tbody></table><p class="hint">Eine Seite sind 3.300 Zeichen.</p>`;

  function abweichung(d) {
    if (!istZahl(d)) return "";
    const klasse = d > 0.02 ? "worse" : d < -0.02 ? "better" : "muted";
    return `<span class="${klasse}">${d > 0 ? "+" : d < 0 ? "−" : ""}${proz(Math.abs(d))}</span>`;
  }

  function tBuilds(builds) {
    if (!builds.length) return leer();
    const zeilen = builds.map((b, i) => `<tr><td><i class="punkt" style="background:${farbe(i)}"></i>${esc(b.name)}</td>
      <td>${esc(tagKurz(b.erste))}–${esc(tagKurz(b.letzte))}</td>
      ${zahl(n0(b.anfragen))}${zahl(ms(b.median_ms))}${zahl(ms(b.p90_ms))}${zahl(ms(b.je_1000_median_ms))}${zahl(abweichung(b.abweichung_vorgaenger))}</tr>`).join("");
    return `<table><thead><tr><th>Build</th><th>im Log</th><th class="num">Anfragen</th><th class="num">Median</th><th class="num">p90</th><th class="num">je 1.000 Z.</th><th class="num">zum Vorgänger</th></tr></thead>
      <tbody>${zeilen}</tbody></table>
      <p class="hint">„*“ = Build mit lokalen Änderungen. Verglichen wird der Median je 1.000 Zeichen, weil die Texte unterschiedlich lang sind.</p>`;
  }

  function tKalibrierung(k) {
    if (!k.zeilen?.length) return leer("Keine Kalibrierläufe im Zeitraum.");
    return `<table><thead><tr><th>Build</th>${k.texte.map((z) => `<th class="num">${n0(z)} Z.</th>`).join("")}<th class="num">Läufe</th></tr></thead><tbody>
      ${k.zeilen.map((z) => `<tr><td>${esc(z.build)}</td>${z.median_ms.map((v) => zahl(ms(v))).join("")}${zahl(n0(z.laeufe))}</tr>`).join("")}
      </tbody></table><p class="hint">Median der Gesamtzeit je Kalibriertext. Gleicher Text, also direkt zwischen Builds vergleichbar.</p>`;
  }

  const tFehler = (fehler) => fehler.length
    ? `<table><thead><tr><th>Fehler</th><th class="num">Anzahl</th><th>zuletzt</th></tr></thead><tbody>
      ${fehler.map((f) => `<tr><td>${esc(f.text)}</td>${zahl(n0(f.anzahl))}<td>${esc(zeitDe(f.zuletzt))}</td></tr>`).join("")}</tbody></table>`
    : leer("Keine Fehler im Zeitraum.");

  // ---------- Seite ----------
  const zeitraumWahl = () => `<span class="seg">${ZEITRAEUME.map(([k, l]) =>
    `<button data-zeitraum="${k}" class="${k === zeitraum ? "on" : ""}">${l}</button>`).join("")}</span>`;

  function kopf(log) {
    const teile = [`${n0(log.zeilen)} Zeilen`];
    if (log.kaputt) teile.push(`<span class="worse">${n0(log.kaputt)} kaputte Zeilen übersprungen</span>`);
    teile.push(`<a href="/api/request-log" download="requests.jsonl">Rohlog laden</a>`);
    return teile.join(" · ");
  }

  const kachel = (titel, inhalt, breit = false) => `<div class="tile${breit ? " wide" : ""}"><h2>${titel}</h2>${inhalt}</div>`;
  const kpi = (k, v, t) => `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div><div class="t">${t}</div></div>`;

  function seite(a) {
    const titel = `<div><h1>Auswertung Request-Log</h1>`;
    if (!a.log.vorhanden) {
      return `<div class="top">${titel}</div>${zeitraumWahl()}</div>
        <div class="tile leer"><h2>Kein Request-Log vorhanden</h2><p class="hint">Erwartet unter <code>${esc(a.log.pfad)}</code>. Die Datei fehlt oder ist leer.</p></div>`;
    }
    const k = a.kennzahlen, v = a.vorperiode || {};
    const kalibLaeufe = (a.kalibrierung.zeilen || []).reduce((s, z) => s + (istZahl(z.laeufe) ? z.laeufe : 0), 0);
    const tage = a.nutzung.tage || [];
    return `<div class="top">${titel}<span class="hint">${kopf(a.log)}</span></div>${zeitraumWahl()}</div>
      <div class="kpis">
        ${kpi("Anfragen", n0(k.anfragen), trend(k.anfragen, v.anfragen, -1))}
        ${kpi("Median Gesamtzeit", ms(k.gesamt_median_ms), trend(k.gesamt_median_ms, v.gesamt_median_ms, 1))}
        ${kpi("p90 Gesamtzeit", ms(k.gesamt_p90_ms), trend(k.gesamt_p90_ms, v.gesamt_p90_ms, 1))}
        ${kpi("je 1.000 Zeichen (Median)", ms(k.je_1000_median_ms), trend(k.je_1000_median_ms, v.je_1000_median_ms, 1))}
        ${kpi("Fehlerquote", proz(k.fehlerquote), `${n0(k.fehler)} Fehler · ${trend(k.fehlerquote, v.fehlerquote, 1, true)}`)}
        ${kpi("als sensibel erkannt", proz(k.sensibel_anteil), trend(k.sensibel_anteil, v.sensibel_anteil, 0, true))}
      </div>
      <div class="grid">
        ${kachel("Anfragen pro Tag", balken(tage.map((t) => ({ label: tagKurz(t.tag), wert: t.anzahl })), { every: Math.ceil(tage.length / 15) }))}
        ${kachel("Anfragen nach Uhrzeit", balken(a.nutzung.stunden.map((n, i) => ({ label: `${i} Uhr`, kurz: i % 3 ? "" : String(i), wert: n }))))}
        ${kachel("Verteilung Gesamtzeit", histogramm(a.histogramm, [[k.gesamt_median_ms, "Median"], [k.gesamt_p90_ms, "p90"]]))}
        ${kachel("Wohin die Zeit geht (Median)", phasenBalken(a.phasen) + tPhasen(a.phasen))}
        ${kachel("Textlänge und Gesamtzeit", streuung(a.streuung, a.builds))}
        ${kachel("Nach Textlänge", tKlassen(a.laengenklassen))}
        ${kachel("Builds", tBuilds(a.builds), true)}
        ${kachel(`Kalibrierung <span class="muted">· ${n0(kalibLaeufe)} Läufe</span>`, tKalibrierung(a.kalibrierung))}
        ${kachel("Fehler", tFehler(a.fehler))}
      </div>`;
  }

  const root = document.getElementById("root");

  async function laden() {
    const url = new URL(location.href);
    url.searchParams.set("zeitraum", zeitraum);
    history.replaceState(null, "", url);
    try {
      const r = await fetch(`/api/auswertung?zeitraum=${encodeURIComponent(zeitraum)}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      root.innerHTML = seite(await r.json());
    } catch (e) {
      root.innerHTML = `<div class="top"><div><h1>Auswertung Request-Log</h1></div>${zeitraumWahl()}</div>
        <div class="errorbox">Auswertung nicht abrufbar: ${esc(e.message)}</div>`;
    }
  }

  root.addEventListener("click", (e) => {
    const b = e.target.closest("[data-zeitraum]");
    if (!b || !ZEITRAEUME.some(([k]) => k === b.dataset.zeitraum)) return;
    zeitraum = b.dataset.zeitraum;
    laden();
  });

  laden();
})();
