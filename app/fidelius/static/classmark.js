/* Schutzstufe im Text: Markierung des auslösenden Abschnitts und Expertenansicht je Abschnitt
   (docs/specs/klassifikation.md, Abschnitt 7). Reine Funktionen ohne DOM; im Browser als
   window.ClassMark, unter Node per require für die Tests. */
(function (root) {
  // Treffer, die im anonymisierten Text durch ihren Platzhalter ersetzt sind, in derselben Auswahl wie
  // placeholders.anonymize auf dem Server: mit Platzhalter, nach Start, Überlappungen übersprungen.
  function replaced(ents) {
    const out = [];
    let pos = 0;
    for (const e of [...ents].filter((e) => e.placeholder).sort((a, b) => a.start - b.start)) {
      if (e.start < pos) continue;
      out.push(e); pos = e.end;
    }
    return out;
  }

  // Offset im anonymisierten Text → Offset im Original. Liegt er in einem Platzhalter, zählt der ganze
  // Treffer zum Abschnitt: ein Anfang rückt an den Trefferanfang, ein Ende an das Trefferende.
  function origAt(x, reps, isEnd) {
    let pos = 0, apos = 0;
    for (const e of reps) {
      const gap = e.start - pos;
      if (x < apos + gap || (isEnd && x === apos + gap)) return pos + (x - apos);
      apos += gap;
      const len = e.placeholder.length;
      if (x < apos + len || (isEnd && x === apos + len)) return isEnd ? e.end : e.start;
      apos += len; pos = e.end;
    }
    return pos + (x - apos);
  }

  // Die Abschnitte von `anonymized` beziehen sich auf den anonymisierten Text, die UI zeigt aber immer
  // das Original mit Platzhaltern. Deshalb wird zurückgerechnet.
  function toOriginal(start, end, ents) {
    const reps = replaced(ents);
    return { start: origAt(start, reps, false), end: origAt(end, reps, true) };
  }

  // Die Abschnitte, die die Stufe des Originals und des anonymisierten Texts bestimmt haben, beide in
  // Offsets des Originals. Wird bei jedem Rendern aus der aktuellen Bewertung neu berechnet, damit eine
  // ersetzte Bewertung des anonymisierten Texts („neu bewerten“) sofort an der richtigen Stelle sitzt.
  function triggerRanges(c, ents) {
    if (!c || !c.original) return [];
    const out = [{ ...c.original.chunk, kind: "original" }];
    if (c.anonymized) out.push({ ...toOriginal(c.anonymized.chunk.start, c.anonymized.chunk.end, ents), kind: "anonymized" });
    return out.map(({ start, end, kind }) => ({ start, end, kind }));
  }

  // Abschnitte, die [start, end) berühren.
  const kindsAt = (start, end, ranges) => ranges.filter((r) => r.start < end && start < r.end).map((r) => r.kind);

  // Ein freies Textstück [a, b), geteilt an den Grenzen der Abschnitte, je Teil mit seinen Abschnitten.
  function pieces(a, b, ranges) {
    const cuts = [a, b];
    for (const r of ranges) for (const x of [r.start, r.end]) if (x > a && x < b) cuts.push(x);
    const xs = [...new Set(cuts)].sort((p, q) => p - q);
    return xs.slice(0, -1).map((s, i) => ({ start: s, end: xs[i + 1], kinds: kindsAt(s, xs[i + 1], ranges) }));
  }

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (p) => Math.round(p * 100) + " %";
  const num = (x) => x.toLocaleString("de-DE");

  // Expertenansicht: je Abschnitt die Wahrscheinlichkeiten aller Stufen, dazu die Schwelle. Werte ab der
  // Schwelle sind hervorgehoben, der auslösende Abschnitt ebenso. Den Zugangsdaten-Wert berechnet der
  // Server; die Spalte erscheint, sobald ein Abschnitt ihn trägt.
  function expertHtml(c, rules) {
    if (!c || !c.original) return "";
    const table = (title, t) => {
      const cred = t.chunks.some((k) => typeof k.credentials === "number");
      const name = (id) => (rules.levels.find((l) => l.id === id) || { name: id }).name;
      const head = `<tr><th>Zeichen</th><th>Stufe</th>${rules.levels.map((l) => `<th>${esc(l.name)}</th>`).join("")}${cred ? "<th>Zugang</th>" : ""}</tr>`;
      const rows = t.chunks.map((k) => {
        const trig = k.start === t.chunk.start && k.end === t.chunk.end ? ' class="trig"' : "";
        const probs = rules.levels.map((l) => {
          const p = k.probabilities[l.id] || 0;
          return `<td${p >= rules.schwelle ? ' class="hit"' : ""}>${pct(p)}</td>`;
        }).join("");
        const zugang = cred ? `<td>${typeof k.credentials === "number" ? pct(k.credentials) : "–"}</td>` : "";
        return `<tr${trig}><td>${num(k.start)}–${num(k.end)}</td><td>${esc(name(k.level))}</td>${probs}${zugang}</tr>`;
      }).join("");
      return `<h4>${title}</h4><table>${head}${rows}</table>`;
    };
    const parts = [table(c.anonymized ? "Original" : "Text", c.original)];
    if (c.anonymized) parts.push(table("Anonymisiert", c.anonymized));
    return `<div class="classexpert expert-only"><div class="muted">Je Abschnitt · Schwelle ${pct(rules.schwelle)}</div>${parts.join("")}</div>`;
  }

  const api = { toOriginal, triggerRanges, kindsAt, pieces, expertHtml };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ClassMark = api;
})(this);
