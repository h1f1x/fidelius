/* Sensible Inhalte für ChatGPT ersetzen: UI-Logik. Der Server ist zustandslos; Treffer, Tabelle und
   Text liegen im Browser (localStorage). */
(() => {
  const $ = (id) => document.getElementById(id);
  const SOURCE_BADGE = { gliner: "G", spacy: "S", regex: "R" };
  const STORAGE_KEY = "pii-app-state-v2";
  const EXPERT_KEY = "pii-app-expert";

  let CONFIG = { categories: {} };
  let state = { text: "", entities: [], mapping: [], anonymized: "", gate: null, timing: null };
  let lastInputWasPaste = false;

  // ---------- Hilfen ----------
  const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const color = (cat) => (CONFIG.categories[cat] || {}).color || "#999";
  const label = (cat) => (CONFIG.categories[cat] || {}).label || cat;
  function toast(msg) { const t = $("toast"); t.textContent = msg; t.classList.remove("hidden"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 1800); }
  function showError(msg) { const e = $("error"); if (!msg) { e.classList.add("hidden"); return; } e.textContent = msg; e.classList.remove("hidden"); }
  async function copy(text, msg) { try { await navigator.clipboard.writeText(text); toast(msg); } catch { toast("Kopieren nicht möglich, bitte Text manuell markieren."); } }
  function save() { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch {} }
  function load() { try { const s = JSON.parse(localStorage.getItem(STORAGE_KEY)); if (s && s.text) state = s; } catch {} }
  async function api(path, body) {
    const r = await fetch(path, body ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : {});
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }

  // ---------- Initialisierung ----------
  async function init() {
    setExpert(localStorage.getItem(EXPERT_KEY) === "1");
    try {
      CONFIG = await api("/api/config");
    } catch {
      showError("Die App ist gerade nicht erreichbar. Bitte prüfen, ob die Docker-Container laufen, und die Seite neu laden.");
      return;
    }
    $("threshold").value = CONFIG.gate_threshold; $("thresholdValue").textContent = Number(CONFIG.gate_threshold).toFixed(2);
    try {
      const ex = await api("/api/examples");
      for (const e of ex) $("example").insertAdjacentHTML("beforeend", `<option value="${esc(e.name)}">${esc(e.title)}</option>`);
    } catch {}
    checkHealth();
    load();
    if (state.text) { $("text").value = state.text; render(); }
  }
  async function checkHealth() {
    try {
      const h = await api("/api/health");
      if (!(h.laya && h.laya.status === "ok")) showError("Das Bewertungsmodell (Laya) ist nicht erreichbar. Die Erkennung funktioniert trotzdem, nur die Vorab-Einschätzung fehlt.");
      else showError(null);
    } catch { showError("Die App ist gerade nicht erreichbar. Bitte prüfen, ob die Docker-Container laufen, und die Seite neu laden."); }
  }
  function setExpert(on) {
    document.body.classList.toggle("expert", on);
    $("expertMode").checked = on;
    try { localStorage.setItem(EXPERT_KEY, on ? "1" : "0"); } catch {}
  }

  // ---------- Analyse ----------
  async function run(force) {
    const text = $("text").value;
    if (!text.trim()) { toast("Bitte zuerst eine E-Mail einfügen."); return; }
    $("run").disabled = true; $("force").disabled = true; $("busy").classList.remove("hidden");
    try {
      const res = await api("/api/analyze", { text, gate_threshold: Number($("threshold").value), force, use_laya_check: $("layaCheck").checked });
      state = { text: res.text, entities: res.entities, mapping: res.mapping, anonymized: res.anonymized_text, gate: res.gate, timing: res.timing };
      save(); render();
      showError(null);
    } catch (e) { showError("Die Prüfung ist fehlgeschlagen: " + e.message + ". Bitte noch einmal versuchen."); }
    finally { $("run").disabled = false; $("force").disabled = false; $("busy").classList.add("hidden"); }
  }
  async function reapply() {
    try {
      const res = await api("/api/apply", { text: state.text, entities: state.entities });
      state.entities = res.entities; state.mapping = res.mapping; state.anonymized = res.anonymized_text;
      save(); render();
    } catch (e) { showError("Die Änderung konnte nicht übernommen werden: " + e.message); }
  }

  // ---------- Darstellung ----------
  function render() {
    renderGate(); renderResult(); renderMapping();
    const t = state.timing;
    $("timing").textContent = t ? `Einschätzung ${t.gate_ms} ms · Erkennung ${t.detect_ms} ms · Laya-Bestätigung ${t.laya_check_ms} ms · gesamt ${t.total_ms} ms` : "";
  }
  function gateWord(p) {
    if (p < 0.1) return "sehr unwahrscheinlich";
    if (p < 0.3) return "eher unwahrscheinlich";
    if (p < 0.5) return "unsicher";
    if (p < 0.8) return "wahrscheinlich";
    return "sehr sicher";
  }
  function renderGate() {
    const g = state.gate, box = $("gate");
    if (!g) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const p = g.probability;
    $("gatefill").style.width = p == null ? "0%" : (p * 100).toFixed(0) + "%";
    $("gatemark").style.left = (g.threshold * 100).toFixed(0) + "%";
    const ran = g.sensitive || g.skipped;
    if (p == null) {
      $("gateword").textContent = "keine Einschätzung möglich";
      $("gatetext").textContent = g.note || "";
    } else {
      $("gateword").textContent = gateWord(p) + ".";
      $("gatetext").textContent = ran
        ? (g.sensitive ? "Der Text wurde anonymisiert." : "Der Text wurde auf deinen Wunsch trotzdem anonymisiert.")
        : "Eine Anonymisierung ist wahrscheinlich nicht nötig. Trotzdem anonymisieren?";
    }
    $("force").classList.toggle("hidden", ran);
  }
  // Ein Kürzel je Quelle; GLiNER liefert sonst vier G für person/full_name/first_name/last_name.
  function groupSources(sources) {
    const out = [];
    for (const s of sources) {
      const lbl = s.label + (s.score != null ? " " + (s.score * 100).toFixed(0) + "%" : "");
      const g = out.find((x) => x.name === s.name);
      if (g) g.title += ", " + lbl; else out.push({ name: s.name, title: lbl });
    }
    return out;
  }
  // ---------- Ergebnis: eine Box, zwei Ansichten ----------
  let viewMode = "annot";  // "annot": Original durchgestrichen + Platzhalter; "plain": so wie kopiert

  function tokens(text, ents, mode) {
    let html = "", pos = 0;
    for (const e of ents) {
      if (e.start < pos) continue;
      html += esc(text.slice(pos, e.start));
      const rejected = e.status === "rejected_laya" || e.status === "rejected_user";
      const badges = groupSources(e.sources).map((g) => `<b title="${esc(g.title)}">${SOURCE_BADGE[g.name] || "?"}</b>`).join("");
      const laya = e.laya ? `<span class="${e.laya.accepted ? "ok" : "no"}" title="Laya: ${esc(e.laya.category)} ${(e.laya.probability * 100).toFixed(0)}%">L${e.laya.accepted ? "✓" : "✗"}</span>` : "";
      const bd = `<span class="badges expert-only">${badges}${laya}</span>`;
      const st = `style="--c:${color(e.category)}" data-id="${e.id}"`;
      if (rejected) {
        html += mode === "plain" ? esc(e.text) : `<mark class="ent rejected" ${st} title="${esc(label(e.category))}, bleibt stehen"><s>${esc(e.text)}</s>${bd}</mark>`;
      } else if (mode === "plain") {
        html += `<mark class="ent chip" ${st} title="Original: ${esc(e.text)}">${esc(e.placeholder)}${bd}</mark>`;
      } else {
        html += `<mark class="ent" ${st} title="${esc(label(e.category))}"><s>${esc(e.text)}</s><span class="ph">${esc(e.placeholder)}</span>${bd}</mark>`;
      }
      pos = e.end;
    }
    return html + esc(text.slice(pos));
  }

  function renderResult() {
    const area = $("resultArea"), text = state.text || "";
    const ents = [...state.entities].sort((a, b) => a.start - b.start);
    const empty = !text ? '<span class="hint">Hier erscheint der anonymisierte Text.</span>' : "";
    area.innerHTML = `<div class="resulthead"><h2>Anonymisierter Text</h2><div class="seg"><button data-view="annot" class="${viewMode === "annot" ? "on" : ""}">mit Markierungen</button><button data-view="plain" class="${viewMode === "plain" ? "on" : ""}">so wie er kopiert wird</button></div><button id="copyAnon" class="primary">Anonymisierten Text kopieren</button></div>
      <div class="viewnote">${viewMode === "annot" ? "Durchgestrichen = Original, farbig = Platzhalter. Kopiert wird nur der anonymisierte Text, ohne Originale. Klick auf eine Stelle, um sie zu ändern." : "Genau dieser Text landet in der Zwischenablage. Klick auf einen Platzhalter zeigt das Original."}</div>
      <div class="annotated-text${viewMode === "plain" ? " plain" : ""}">${empty || tokens(text, ents, viewMode)}</div>`;
    area.querySelectorAll(".seg button").forEach((b) => { b.onclick = () => { viewMode = b.dataset.view; renderResult(); }; });
  }


  function renderMapping() {
    const tb = $("mapping").querySelector("tbody");
    tb.innerHTML = state.mapping.map((m) => `<tr class="cat" style="--c:${color(m.category)}"><td class="ph" style="--c:${color(m.category)}">${esc(m.placeholder)}</td><td>${esc(m.original)}${m.variants.map((v) => `<span class="variant">auch: ${esc(v)}</span>`).join("")}</td><td class="src expert-only">${m.sources.map((s) => s === "laya" ? "L" : SOURCE_BADGE[s] || s).join(" ")}</td></tr>`).join("")
      || '<tr><td colspan="3" class="hint">Noch keine Ersetzungen.</td></tr>';
  }

  // ---------- Treffer bearbeiten ----------
  function sameValueEntities(e) {
    if (e.placeholder) return state.entities.filter((x) => x.placeholder === e.placeholder);
    const key = e.text.trim().toLowerCase();
    return state.entities.filter((x) => x.text.trim().toLowerCase() === key && x.category === e.category);
  }
  function openPopover(mark) {
    const id = Number(mark.dataset.id), e = state.entities.find((x) => x.id === id);
    if (!e) return;
    const pop = $("popover");
    const rejected = e.status === "rejected_laya" || e.status === "rejected_user";
    const srcs = groupSources(e.sources).map((g) => `${SOURCE_BADGE[g.name]}: ${g.title}`).join(" · ");
    const laya = e.laya ? `Laya: ${e.laya.category} ${(e.laya.probability * 100).toFixed(0)} %${e.laya.recategorized_from ? " (vorher " + e.laya.recategorized_from + ")" : ""}` : "Laya: nicht geprüft";
    const same = sameValueEntities(e), n = same.length;
    const nTxt = n > 1 ? ` <span class="muted">· ${n} Vorkommen</span>` : "";
    const ph = e.placeholder ? `<span class="ph" style="--c:${color(e.category)}">${esc(e.placeholder)}</span>` : `<span class="muted">bleibt stehen</span>`;
    const chips = Object.keys(CONFIG.categories).map((k) => `<button class="catchip${k === e.category ? " on" : ""}" data-cat="${k}" style="--c:${color(k)}">${esc(label(k))}</button>`).join("");
    pop.innerHTML = `<div class="title">${esc(e.text)} <span class="arrow">→</span> ${ph}${nTxt}<button id="popClose" class="x" title="Schließen">×</button></div>
      <div class="meta expert-only">${esc(srcs)}<br>${esc(laya)}</div>
      <div class="chips">${chips}</div>
      <button id="popToggle" class="switch ${rejected ? "off" : "on"}"><i></i>${rejected ? "Bleibt stehen, nicht ersetzen" : "Wird ersetzt"}</button>`;
    pop.classList.remove("hidden");
    const r = mark.getBoundingClientRect();
    const w = pop.offsetWidth || 300;
    pop.style.left = Math.max(10, Math.min(window.scrollX + r.left, window.scrollX + window.innerWidth - w - 10)) + "px";
    pop.style.top = window.scrollY + r.bottom + 6 + "px";
    // Änderungen gelten für alle Vorkommen desselben Werts.
    pop.querySelectorAll(".catchip").forEach((b) => { b.onclick = () => { for (const x of same) { x.category = b.dataset.cat; x.status = "manual"; } closePopover(); reapply(); }; });
    $("popToggle").onclick = () => { for (const x of same) x.status = rejected ? "manual" : "rejected_user"; closePopover(); reapply(); };
    $("popClose").onclick = closePopover;
  }


  function closePopover() { $("popover").classList.add("hidden"); }

  // ---------- Rückübersetzung (rein im Browser) ----------
  function placeholderPattern(ph) {
    const core = ph.replace(/^\[|\]$/g, ""), i = core.lastIndexOf("_"), cat = core.slice(0, i), num = core.slice(i + 1);
    return new RegExp(`(?:[\\[\\(\\{<«„"']\\s*)?${cat.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[\\s_\\-]?${num}(?![0-9])(?:\\s*[\\]\\)\\}>»“"'])?`, "gi");
  }
  function deanonymize(text, mapping) {
    let hits = 0;
    for (const m of [...mapping].sort((a, b) => b.placeholder.length - a.placeholder.length)) {
      text = text.replace(placeholderPattern(m.placeholder), () => { hits++; return m.original; });
    }
    return { text, hits };
  }

  // ---------- Export/Import ----------
  function exportMapping() {
    const blob = new Blob([JSON.stringify({ mapping: state.mapping, created: new Date().toISOString() }, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "ersetzungstabelle.json"; a.click(); URL.revokeObjectURL(a.href);
  }
  function importMapping(file) {
    const rd = new FileReader();
    rd.onload = () => { try { const j = JSON.parse(rd.result); state.mapping = j.mapping || j; save(); renderMapping(); toast("Tabelle importiert."); } catch { toast("Die Datei ist keine gültige Tabelle."); } };
    rd.readAsText(file);
  }

  // ---------- Events ----------
  $("run").onclick = () => run(false);
  $("force").onclick = () => run(true);
  $("clear").onclick = () => {
    $("text").value = ""; $("example").value = ""; $("reply").value = ""; $("restored").value = ""; $("restoreInfo").textContent = "";
    state = { text: "", entities: [], mapping: [], anonymized: "", gate: null, timing: null }; save(); render();
  };
  $("threshold").oninput = (e) => { $("thresholdValue").textContent = Number(e.target.value).toFixed(2); };
  $("expertMode").onchange = (e) => setExpert(e.target.checked);
  $("infoToggle").onclick = (e) => { e.preventDefault(); $("info").classList.toggle("hidden"); };
  $("example").onchange = async (e) => {
    if (!e.target.value) return;
    try { const ex = await api("/api/examples/" + encodeURIComponent(e.target.value)); $("text").value = ex.text; run(false); }
    catch (err) { showError("Das Beispiel konnte nicht geladen werden: " + err.message); }
  };
  // Eingefügter Text wird sofort geprüft; getippter Text erst auf Knopfdruck.
  $("text").addEventListener("paste", () => { lastInputWasPaste = true; });
  $("text").addEventListener("input", () => { if (lastInputWasPaste) { lastInputWasPaste = false; run(false); } });
  $("text").addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") run(false); });
  $("resultArea").addEventListener("click", (e) => { const m = e.target.closest("mark.ent"); if (m) openPopover(m); });
  document.addEventListener("click", (e) => { if (!e.target.closest("#popover") && !e.target.closest("mark.ent")) closePopover(); });
  document.addEventListener("click", (e) => { if (e.target.closest("#copyAnon")) copy(state.anonymized || "", "Anonymisierter Text kopiert. Er enthält keine Markierungen und keine Originale."); });
  $("exportMap").onclick = exportMapping;
  $("importMap").onchange = (e) => { if (e.target.files[0]) importMapping(e.target.files[0]); e.target.value = ""; };
  $("restore").onclick = () => { const r = deanonymize($("reply").value, state.mapping); $("restored").value = r.text; $("restoreInfo").textContent = `${r.hits} Platzhalter ersetzt.`; };
  $("copyRestored").onclick = () => copy($("restored").value, "Rückübersetzte Antwort kopiert.");

  init();
})();
