/* Schutzstufe im Text: Markierung des auslösenden Abschnitts, Freigabe und Warnbanner, Expertenansicht
   je Abschnitt (docs/specs/klassifikation.md, Abschnitt 7). Reine Funktionen ohne DOM; im Browser als
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
  // Ist sie veraltet (`stale`), gehören ihre Offsets zu einem früheren anonymisierten Text und
  // würden an falscher Stelle landen; dann bleibt nur die Markierung des Originals.
  function triggerRanges(c, ents) {
    if (!c || !c.original) return [];
    const out = [{ ...c.original.chunk, kind: "original" }];
    if (c.anonymized && !c.stale) out.push({ ...toOriginal(c.anonymized.chunk.start, c.anonymized.chunk.end, ents), kind: "anonymized" });
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
    if (c.anonymized) parts.push(table(c.stale ? "Anonymisiert (veraltet)" : "Anonymisiert", c.anonymized));
    return `<div class="classexpert expert-only"><div class="muted">Je Abschnitt · Schwelle ${pct(rules.schwelle)}</div>${parts.join("")}</div>`;
  }

  // Rang = Position in rules.levels, von niedrig nach hoch. Bis freigegeben_bis geht eine Stufe ohne Warnung durch.
  const rank = (rules, id) => rules.levels.findIndex((l) => l.id === id);
  const overApproval = (rules, id) => rank(rules, id) > rank(rules, rules.freigegeben_bis);

  // Dieselbe Regel wie classification.summarize auf dem Server; „neu bewerten“ rechnet damit nach.
  const warns = (c, rules) => Boolean(c.credentials)
    || [c.original, c.anonymized].some((t) => t && overApproval(rules, t.level));

  // Überschrift des Banners: welcher Text über der Freigabe liegt und wessen Stufe danach folgt.
  // Liegt nur das Original darüber, ist die genannte Stufe die des anonymisierten Texts, nicht die überschrittene.
  function bannerHead(c, rules, name) {
    const over = (t) => t && overApproval(rules, t.level);
    if (c.anonymized && over(c.anonymized)) return `Der anonymisierte Text liegt über der Freigabe. Für die Schutzstufe ${name} gilt:`;
    if (c.anonymized && over(c.original)) return `Das Original liegt über der Freigabe. Für den anonymisierten Text (${name}) gilt:`;
    if (over(c.original)) return `Der Text liegt über der Freigabe. Für die Schutzstufe ${name} gilt:`;
    return `Für die Schutzstufe ${name} gilt:`;
  }

  // Warnbanner: der Text der Stufe, die für die KI gilt, bei Zugangsdaten zusätzlich deren Hinweis.
  // Der Satz zur Freigabe steht nur, wenn eine Stufe sie wirklich überschreitet.
  function bannerHtml(c, rules, markdown) {
    if (!c || !c.warn) return "";
    const parts = [];
    // Maßgeblich ist der Text, der in die KI geht: der anonymisierte, ohne eigene Bewertung das Original.
    const t = c.anonymized || c.original;
    if (t) {
      const lv = rules.levels.find((l) => l.id === t.level) || { name: t.level, text: "" };
      parts.push(`<div><strong>${bannerHead(c, rules, esc(lv.name))}</strong>${lv.text ? markdown(lv.text) : ""}</div>`);
    }
    // Bleibt stehen, auch wenn alle Zugangsdaten ersetzt sind: Ein Secret in der Zwischenablage gilt als offengelegt.
    if (c.credentials) {
      parts.push(`<div><strong>Im Original stehen Zugangsdaten. Auch wenn sie ersetzt sind, sollten sie als offengelegt gelten und ausgetauscht werden.</strong>${markdown(rules.zugangsdaten_text || "Zugangsdaten gehören nicht in KI-Systeme.")}</div>`);
    }
    return `<div class="classwarn" role="alert">${parts.join("")}</div>`;
  }

  const api = { toOriginal, triggerRanges, kindsAt, pieces, expertHtml, overApproval, warns, bannerHtml };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ClassMark = api;
})(this);
