// Markierung des auslösenden Abschnitts und Expertenansicht (docs/specs/klassifikation.md, Abschnitt 7).
const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../../fidelius/static/classmark.js");

// "Herr Müller wohnt in Köln." → "Herr [PERSON_1] wohnt in [ORT_1]."
const ENTS = [
  { start: 21, end: 25, placeholder: "[ORT_1]", status: "accepted" },
  { start: 5, end: 11, placeholder: "[PERSON_1]", status: "accepted" },
];

test("Abschnitt des anonymisierten Texts wird ins Original zurückgerechnet", () => {
  assert.deepEqual(M.toOriginal(15, 33, ENTS), { start: 11, end: 26 });
  assert.deepEqual(M.toOriginal(0, 5, ENTS), { start: 0, end: 5 });
});

test("ein angeschnittener Platzhalter zählt ganz zum Abschnitt", () => {
  assert.deepEqual(M.toOriginal(0, 10, ENTS), { start: 0, end: 11 });
  assert.deepEqual(M.toOriginal(27, 33, ENTS), { start: 21, end: 26 });
  assert.deepEqual(M.toOriginal(25, 32, ENTS), { start: 21, end: 25 });
});

test("abgelehnte Treffer ohne Platzhalter verschieben nichts", () => {
  const ents = [...ENTS, { start: 0, end: 4, placeholder: null, status: "rejected_user" }];
  assert.deepEqual(M.toOriginal(15, 33, ents), { start: 11, end: 26 });
});

test("markiert werden die auslösenden Abschnitte beider Texte, in Offsets des Originals", () => {
  const c = { original: { level: "vertraulich", chunk: { start: 0, end: 11 } },
              anonymized: { level: "intern", chunk: { start: 15, end: 33 } } };
  assert.deepEqual(M.triggerRanges(c, ENTS), [
    { start: 0, end: 11, kind: "original" },
    { start: 11, end: 26, kind: "anonymized" },
  ]);
});

test("ohne Bewertung des anonymisierten Texts nur der des Originals, ohne Bewertung nichts", () => {
  const c = { original: { level: "intern", chunk: { start: 3, end: 9 } }, anonymized: null };
  assert.deepEqual(M.triggerRanges(c, ENTS), [{ start: 3, end: 9, kind: "original" }]);
  assert.deepEqual(M.triggerRanges({ original: null, note: "Laya nicht erreichbar" }, ENTS), []);
  assert.deepEqual(M.triggerRanges(null, ENTS), []);
});

test("ein freies Textstück wird an den Grenzen der Abschnitte geteilt", () => {
  const ranges = [{ start: 0, end: 11, kind: "original" }, { start: 8, end: 26, kind: "anonymized" }];
  assert.deepEqual(M.pieces(4, 15, ranges), [
    { start: 4, end: 8, kinds: ["original"] },
    { start: 8, end: 11, kinds: ["original", "anonymized"] },
    { start: 11, end: 15, kinds: ["anonymized"] },
  ]);
  assert.deepEqual(M.pieces(30, 40, ranges), [{ start: 30, end: 40, kinds: [] }]);
});

const RULES = {
  levels: [{ id: "oeffentlich", name: "Öffentlich" }, { id: "intern", name: "Intern" }, { id: "geheim", name: "<Geheim>" }],
  freigegeben_bis: "intern", schwelle: 0.3,
};
const chunk = (start, end, level, probs, extra = {}) => ({ start, end, level, probabilities: probs, ...extra });

test("Expertenansicht: je Abschnitt die Wahrscheinlichkeiten aller Stufen und die Schwelle", () => {
  const c = { original: { level: "intern", chunk: { start: 600, end: 1200 }, chunks: [
    chunk(0, 600, "oeffentlich", { oeffentlich: 0.9, intern: 0.1, geheim: 0 }),
    chunk(600, 1200, "intern", { oeffentlich: 0.2, intern: 0.65, geheim: 0.05 }),
  ] }, anonymized: null };
  const html = M.expertHtml(c, RULES);
  assert.match(html, /Schwelle 30 %/);
  assert.match(html, /Öffentlich.*Intern.*&lt;Geheim&gt;/s);
  assert.match(html, /90 %/);
  assert.match(html, /65 %/);
  // Der auslösende Abschnitt ist in der Tabelle hervorgehoben.
  assert.match(html, /<tr class="trig"><td>600–1\.200<\/td>/);
  assert.doesNotMatch(html, /Zugang/);
});

test("Expertenansicht: Zugangsdaten-Wert nur, wenn die Abschnitte ihn tragen", () => {
  const t = (cred) => ({ level: "intern", chunk: { start: 0, end: 10 },
    chunks: [chunk(0, 10, "intern", { oeffentlich: 0.1, intern: 0.8, geheim: 0.1 }, cred)] });
  assert.doesNotMatch(M.expertHtml({ original: t({ credentials: null }) }, RULES), /Zugang/);
  const html = M.expertHtml({ original: t({ credentials: 0.42 }), anonymized: t({ credentials: 0.02 }) }, RULES);
  assert.match(html, /Zugang/);
  assert.match(html, /42 %/);
  assert.match(html, /Anonymisiert/);
});

test("Expertenansicht: nichts ohne Bewertung", () => {
  assert.equal(M.expertHtml({ original: null }, RULES), "");
  assert.equal(M.expertHtml(null, RULES), "");
});

test("ein Treffer gehört zu jedem Abschnitt, den er berührt", () => {
  const ranges = [{ start: 0, end: 11, kind: "original" }, { start: 11, end: 26, kind: "anonymized" }];
  assert.deepEqual(M.kindsAt(5, 11, ranges), ["original"]);
  assert.deepEqual(M.kindsAt(10, 12, ranges), ["original", "anonymized"]);
});
