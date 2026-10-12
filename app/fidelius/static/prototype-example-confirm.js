/* PROTOTYP, wegwerfen: drei Varianten der Rückfrage, bevor ein Beispiel eingefügt wird.
   Umschaltbar über ?beispiel=A|B|C auf der Startseite; ohne Parameter bleibt alles wie bisher.
   app.js ruft window.exampleProto.confirm(ex, titel, aktuellerText) auf und fügt nur bei true ein. */
(() => {
  const VARIANTS = { A: "Modaler Dialog", B: "Popover am Auswahlfeld", C: "Vorschau im Textfeld" };
  const KEYS = Object.keys(VARIANTS);
  const current = new URLSearchParams(location.search).get("beispiel");
  if (!VARIANTS[current]) return;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (x) => x.toLocaleString("de-DE");
  const head = (text, n) => text.split("\n").slice(0, n).join("\n");
  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; };

  // ---------- A: modaler Dialog mit Vorschau ----------
  function confirmA(ex, title, existing) {
    return new Promise((resolve) => {
      const d = el(`<dialog class="proto-dialog" aria-labelledby="protoDlgTitle">
        <h2 id="protoDlgTitle">Beispiel einfügen?</h2>
        <p><strong>${esc(title)}</strong> <span class="muted">· ${num(ex.text.length)} Zeichen</span></p>
        <pre class="proto-preview">${esc(head(ex.text, 8))}${ex.text.split("\n").length > 8 ? "\n…" : ""}</pre>
        ${existing.trim() ? `<p class="proto-warn">Der Text im Eingabefeld (${num(existing.length)} Zeichen) wird ersetzt.</p>` : ""}
        <p class="muted">Danach wird das Beispiel sofort geprüft.</p>
        <div class="row proto-actions"><button class="ghost" value="no">Abbrechen</button><button class="primary" value="yes" autofocus>Einfügen und prüfen</button></div>
      </dialog>`);
      document.body.append(d);
      const done = (ok) => { d.close(); d.remove(); resolve(ok); };
      d.querySelectorAll("button").forEach((b) => (b.onclick = () => done(b.value === "yes")));
      d.addEventListener("cancel", (e) => { e.preventDefault(); done(false); });
      d.addEventListener("click", (e) => { if (e.target === d) done(false); }); // Klick auf den Hintergrund
      d.showModal();
    });
  }

  // ---------- B: kleines Popover direkt am Auswahlfeld ----------
  function confirmB(ex, title, existing) {
    return new Promise((resolve) => {
      const sel = $("example");
      const p = el(`<div class="proto-pop" role="dialog" aria-label="Beispiel einfügen?">
        <div>„${esc(title)}“ einfügen${existing.trim() ? " und deinen Text ersetzen" : ""}?</div>
        <div class="row"><button class="primary small" data-ok="1">Einfügen</button><button class="ghost small">Nein</button></div>
      </div>`);
      document.body.append(p);
      const r = sel.getBoundingClientRect();
      p.style.left = `${r.left + scrollX}px`; p.style.top = `${r.bottom + scrollY + 8}px`;
      const done = (ok) => { p.remove(); document.removeEventListener("keydown", onKey, true); document.removeEventListener("pointerdown", onOutside, true); sel.focus(); resolve(ok); };
      const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); done(false); } };
      const onOutside = (e) => { if (!p.contains(e.target)) done(false); };
      p.querySelectorAll("button").forEach((b) => (b.onclick = () => done(!!b.dataset.ok)));
      document.addEventListener("keydown", onKey, true);
      setTimeout(() => document.addEventListener("pointerdown", onOutside, true));
      p.querySelector("[data-ok]").focus();
    });
  }

  // ---------- C: Beispiel erscheint als Vorschau im Textfeld, Leiste darüber ----------
  function confirmC(ex, title, existing) {
    return new Promise((resolve) => {
      const ta = $("text");
      const bar = el(`<div class="proto-bar-c" role="region" aria-label="Vorschau des Beispiels">
        <span>Vorschau: <strong>${esc(title)}</strong>${existing.trim() ? ` <span class="muted">· ersetzt deinen Text</span>` : ""}</span>
        <span class="row"><button class="ghost small">Verwerfen <kbd>Esc</kbd></button><button class="primary small" data-ok="1">Übernehmen <kbd>↵</kbd></button></span>
      </div>`);
      ta.before(bar);
      ta.value = ex.text; ta.readOnly = true; ta.classList.add("proto-ghost"); ta.scrollTop = 0;
      const done = (ok) => {
        bar.remove(); ta.readOnly = false; ta.classList.remove("proto-ghost");
        if (!ok) ta.value = existing;
        document.removeEventListener("keydown", onKey, true);
        resolve(ok);
      };
      const onKey = (e) => {
        if (e.key === "Escape") { e.preventDefault(); done(false); }
        else if (e.key === "Enter" && !e.target.closest("button")) { e.preventDefault(); done(true); }
      };
      bar.querySelectorAll("button").forEach((b) => (b.onclick = () => done(!!b.dataset.ok)));
      document.addEventListener("keydown", onKey, true);
      bar.querySelector("[data-ok]").focus();
    });
  }

  // ---------- Schnittstelle für app.js, mit Zustandsanzeige ----------
  let last = "noch nichts gewählt";
  window.exampleProto = {
    async confirm(ex, title, existing) {
      setState(`fragt: „${title}“`);
      const ok = await ({ A: confirmA, B: confirmB, C: confirmC })[current](ex, title, existing);
      last = `${ok ? "übernommen" : "abgebrochen"}: „${title}“${existing.trim() ? ` (vorher ${num(existing.length)} Zeichen im Feld)` : " (Feld war leer)"}`;
      setState(last);
      return ok;
    },
  };

  // ---------- Umschalter unten ----------
  const sw = el(`<div class="proto-switch" aria-label="Prototyp-Umschalter">
    <button data-d="-1" aria-label="Vorherige Variante">←</button>
    <span class="proto-label"></span>
    <button data-d="1" aria-label="Nächste Variante">→</button>
    <span class="proto-state"></span>
  </div>`);
  document.body.append(sw);
  sw.querySelector(".proto-label").textContent = `${current} (${VARIANTS[current]})`;
  function setState(s) { sw.querySelector(".proto-state").textContent = s; }
  setState(last);
  const go = (d) => {
    const next = KEYS[(KEYS.indexOf(current) + d + KEYS.length) % KEYS.length];
    const u = new URL(location.href); u.searchParams.set("beispiel", next); location.replace(u);
  };
  sw.querySelectorAll("button").forEach((b) => (b.onclick = () => go(Number(b.dataset.d))));
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select, [contenteditable], dialog")) return;
    if (e.key === "ArrowLeft") go(-1);
    if (e.key === "ArrowRight") go(1);
  });
})();
