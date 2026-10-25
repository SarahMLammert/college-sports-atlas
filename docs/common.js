// Shared by every sport's pages (docs/<sport>/players-*.html):
// constants, loading the data, school colors, and the Filters dropdown (its controls, logic and link format).
// Load after d3.
(function () {
  const $ = (id) => document.getElementById(id);
  // Each sport's map_data.json says how it writes its positions and divisions (from config/<sport>.json):
  //   data.posLabels  position group -> chip text ("FO" -> "Faceoff")
  //   data.d1         the divisions that make up D1 (football: FBS and FCS; lacrosse: D1)
  //   data.divLabels  division -> its full name ("D2" -> "Division II")
  // Data built before these existed gets football's, so older map_data.json files still work.
  const POS_LABEL = { DEF: "Def (unlisted)", ST: "K/P/LS", ATH: "ATH/other" };
  const D1_DIVS = ["FBS", "FCS"];
  const DIV_TITLE = { FBS: "FBS (Division I)", FCS: "FCS (Division I)", D2: "Division II", D3: "Division III", NAIA: "NAIA", JUCO: "Junior college (NJCAA and California CCCAA)" };
  const STATE_ABBR = {"Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA","Colorado":"CO","Connecticut":"CT","Delaware":"DE","District of Columbia":"DC","Florida":"FL","Georgia":"GA","Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA","Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD","Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT","Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY","Puerto Rico":"PR"};
  const ABBR_STATE = Object.fromEntries(Object.entries(STATE_ABBR).map(([k, v]) => [v, k]));
  const fmt = d3.format(",");
  const pct = (x) => x > 0 && x < .005 ? "<1%" : d3.format(".0%")(x);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const narrow = () => matchMedia("(max-width: 760px)").matches;

  // ---------- data ----------
  async function loadData() {
    const data = await fetch("map_data.json").then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
    const P = data.players;
    data.N = P.s.length;
    data.SEASONS = [...new Set([...P.f, ...P.l])].map((f) => f + 2000).sort((a, b) => a - b);   // every season anyone was on a roster
    data.FIRST = data.SEASONS[0]; data.LAST = data.SEASONS[data.SEASONS.length - 1];
    data.nameList = data.names.split("\n");
    data.posLabel = data.posLabels || POS_LABEL;
    data.d1 = data.d1 || D1_DIVS;
    data.divLabel = data.divLabels || DIV_TITLE;
    data.posName = (p) => data.posLabel[p] || p;
    data.tState = data.towns.map((t) => { const parts = t[2].split(", "); return parts[parts.length - 1]; });   // state abbr, or a country
    data.schoolIndex = new Map(data.schools.map((s, i) => [s[0].toLowerCase(), i]));
    // campus city, state and coordinates (built from config/school_locations.csv); the pages work without it
    let loc = null;
    try { loc = await fetch("school_locations.json").then((r) => r.ok ? r.json() : null); } catch (e) {}
    data.campus = data.schools.map((s) => { const v = loc && loc.schools[s[0]]; return v ? { city: v[0], state: v[1], lat: v[2], lon: v[3] } : null; });
    return data;
  }

  // ---------- school colors ----------
  const lum = (hex) => { const c = d3.color(hex).rgb(); const f = (v) => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; return .2126 * f(c.r) + .7152 * f(c.g) + .0722 * f(c.b); };
  const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
  function makePalette(data) {
    let palette = null, key = "";
    // Fill with the primary color; if it disappears into the map (black on a dark map, gold on a pale one), swap to the secondary.
    function schoolPalette() {
      const land = d3.color(css("--land")).formatHex(), panel = d3.color(css("--panel")).formatHex();
      if (palette && key === land) return palette;
      palette = data.schools.map((sc) => {
        const prim = sc[3] || "#777777", sec = sc[4] || "#ffffff";
        let fill = prim, edge = sec;
        if (contrast(prim, land) < 1.6 && contrast(sec, land) > contrast(prim, land)) { fill = sec; edge = prim; }
        if (contrast(edge, fill) < 1.4) edge = contrast(panel, fill) > contrast(css("--fg"), fill) ? panel : d3.color(css("--fg")).formatHex();
        return { fill, edge };
      });
      key = land;
      return palette;
    }
    const swatch = (i) => { const c = schoolPalette()[i]; return `<span class="sw" style="background:${c.fill};--sw2:${c.edge}" aria-hidden="true"></span>`; };
    return { schoolPalette, swatch };
  }

  // ---------- Filters dropdown ----------
  // Builds and runs whatever filter controls the page has. The School and Conference controls are optional:
  // players-heatmap.html leaves them out because each of its boxes picks its own school.
  //   onChange()    called after any filter changes
  //   onSchool(i)   called when the School box picks a school (-1 = cleared)
  //   onOpen()      called when the dropdown opens (so the page can close other panels on phones)
  function makeFilters(data, { onChange, onSchool, onOpen } = {}) {
    const P = data.players;
    const allPos = () => new Set(data.pos.map((_, i) => i));
    const state = { school: -1, allSchools: false, conf: "", div: "", from: data.FIRST, to: data.LAST, entry: "", pos: allPos() };
    const hasSchool = !!$("school"), hasConf = !!$("conf");
    // Division choices: "" = all, "D1" = every D1 division together (football: FBS + FCS), otherwise an
    // index into data.divs. The "D1" group is only offered when D1 is split (football) and the data has
    // other divisions too; a sport whose D1 is one division already has a "D1" button.
    // Only divisions with players get a button (a D1-only sport shows no NAIA or JUCO button).
    const isD1 = (d) => data.d1.includes(data.divs[d]);
    const present = new Set(P.d);
    const shownDivs = data.divs.map((n, i) => i).filter((i) => present.has(i));
    const d1Group = data.d1.length > 1 && shownDivs.some((i) => isD1(i)) && shownDivs.some((i) => !isD1(i));
    const titleOf = (v) => v === "" ? "" : v === "D1" && d1Group ? `Division I (${data.d1.join(" and ")})` : data.divLabel[divName(v)] || "";
    const divChoices = [["", "All"], ...(d1Group ? [["D1", "D1"]] : []), ...shownDivs.map((i) => [String(i), data.divs[i]])];
    const divName = (v) => v === "D1" ? "D1" : data.divs[+v];
    const divOk = (v, d) => v === "" || (v === "D1" ? isD1(d) : d === +v);
    // the buttons come from the data, so new divisions show up as soon as map_data.json has them
    $("div").className = "chips divs";
    $("div").innerHTML = divChoices.map(([v, label]) =>
      `<button type="button" class="chip" data-v="${v}" aria-pressed="${v === ""}"${titleOf(v) ? ` title="${esc(titleOf(v))}"` : ""}>${esc(label)}</button>`).join("");

    if (hasSchool) {
      $("schoolList").innerHTML = data.schools.map((s) => `<option value="${esc(s[0])}">`).join("");
      $("school").placeholder = `All ${data.schools.length} schools — type to search`;
      $("school").addEventListener("input", (e) => {
        const v = e.target.value.trim().toLowerCase();
        if (!v) onSchool && onSchool(-1);
        else if (data.schoolIndex.has(v)) onSchool && onSchool(data.schoolIndex.get(v));
      });
    }
    if (hasConf) {
      data.confs.forEach((c, i) => { const o = document.createElement("option"); o.value = i; o.textContent = c; $("conf").appendChild(o); });
      $("conf").addEventListener("change", (e) => { state.conf = e.target.value; changed(); });
    }
    for (const id of ["from", "to"]) data.SEASONS.forEach((y) => { const o = document.createElement("option"); o.value = y; o.textContent = y; $(id).appendChild(o); });
    $("from").addEventListener("change", (e) => { state.from = +e.target.value; if (state.from > state.to) state.to = state.from; sync(); changed(); });
    $("to").addEventListener("change", (e) => { state.to = +e.target.value; if (state.to < state.from) state.from = state.to; sync(); changed(); });
    data.pos.forEach((p, i) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "chip"; b.textContent = data.posName(p); b.dataset.i = i; b.setAttribute("aria-pressed", "true");
      b.addEventListener("click", () => {
        if (state.pos.size === data.pos.length) state.pos = new Set([i]);      // first click isolates one group
        else if (state.pos.has(i)) { state.pos.delete(i); if (!state.pos.size) state.pos = allPos(); }
        else state.pos.add(i);
        sync(); changed();
      });
      $("pos").appendChild(b);
    });
    $("posAll").addEventListener("click", () => { state.pos = allPos(); sync(); changed(); });
    for (const key of ["div", "entry"]) $(key).addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      state[key] = b.dataset.v; sync(); changed();
    });
    $("resetAll").addEventListener("click", () => { reset(); sync(); changed(); });

    function changed() { updateBadge(); onChange && onChange(); }
    function setSeg(id, v) { $(id).querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x.dataset.v === v)); }
    function sync() {
      if (hasSchool) $("school").value = state.school >= 0 ? data.schools[state.school][0] : "";
      if (hasConf) $("conf").value = state.conf;
      $("from").value = state.from; $("to").value = state.to;
      setSeg("div", state.div); setSeg("entry", state.entry);
      $("pos").querySelectorAll(".chip").forEach((b) => b.setAttribute("aria-pressed", state.pos.has(+b.dataset.i)));
      updateBadge();
    }
    function reset() {
      Object.assign(state, { school: -1, allSchools: false, conf: "", div: "", from: data.FIRST, to: data.LAST, entry: "", pos: allPos() });
    }
    function activeCount() {
      return (hasSchool && state.school >= 0) + (hasConf && state.conf !== "") + (state.div !== "") + (state.from !== data.FIRST || state.to !== data.LAST)
        + (state.entry !== "") + (state.pos.size !== data.pos.length);
    }
    function updateBadge() {
      const n = activeCount();
      $("fcount").hidden = !n; $("fcount").textContent = n;
      $("filtersBtn").setAttribute("aria-label", n ? `Filters, ${n} active` : "Filters");
    }
    // skipSchool: ignore the school filter (rankings); skipConf: ignore the conference filter too
    function passes(k, skipSchool, skipConf) {
      if (!skipSchool && state.school >= 0 && P.s[k] !== state.school) return false;
      if (P.f[k] + 2000 > state.to || P.l[k] + 2000 < state.from) return false;   // on a roster in at least one season of the range
      if (!divOk(state.div, P.d[k])) return false;
      if (state.entry !== "" && P.x[k] !== +state.entry) return false;
      if (!state.pos.has(P.p[k])) return false;
      if (!skipConf && state.conf !== "" && data.schools[P.s[k]][1] !== +state.conf) return false;
      return true;
    }
    // A short description of the player filters, e.g. "FCS · 2019–2024 · transfers · QB, WR"
    function summary() {
      const parts = [];
      if (state.div !== "") parts.push(divName(state.div));
      if (state.from !== data.FIRST || state.to !== data.LAST) parts.push(state.from === state.to ? `${state.from}` : `${state.from}–${state.to}`);
      if (state.entry !== "") parts.push(state.entry === "1" ? "transfers" : "high school recruits");
      if (state.pos.size !== data.pos.length) parts.push([...state.pos].sort((a, b) => a - b).map((i) => data.posName(data.pos[i])).join(", "));
      return parts.join(" · ");
    }
    // Link format (see README): school, conf, div, from, to, arrived, pos
    function toParams(q, { includeSchool = true } = {}) {
      if (includeSchool) {
        if (state.school >= 0) q.set("school", data.schools[state.school][0]);
        else if (state.allSchools) q.set("school", "all");
      }
      if (state.conf !== "") q.set("conf", data.confs[+state.conf]);
      if (state.div !== "") q.set("div", divName(state.div));
      if (state.from !== data.FIRST) q.set("from", state.from);
      if (state.to !== data.LAST) q.set("to", state.to);
      if (state.entry !== "") q.set("arrived", state.entry === "1" ? "transfer" : "hs");
      if (state.pos.size !== data.pos.length) q.set("pos", [...state.pos].sort((a, b) => a - b).map((i) => data.pos[i]).join(","));
      return q;
    }
    function fromParams(q) {
      reset();
      const v = (key) => (q.get(key) || "").trim();
      const sc = v("school").toLowerCase();
      if (sc && data.schoolIndex.has(sc)) state.school = data.schoolIndex.get(sc);
      else if (sc === "all") state.allSchools = true;
      const ci = data.confs.indexOf(v("conf")); if (ci >= 0) state.conf = String(ci);
      const dv = v("div").toUpperCase(), di = data.divs.indexOf(dv);
      if (dv === "D1" && d1Group) state.div = "D1"; else if (di >= 0) state.div = String(di);
      if (data.SEASONS.includes(+v("from"))) state.from = +v("from");
      if (data.SEASONS.includes(+v("to"))) state.to = +v("to");
      if (state.from > state.to) [state.from, state.to] = [state.to, state.from];
      if (v("arrived") === "transfer") state.entry = "1"; else if (v("arrived") === "hs") state.entry = "0";
      if (v("pos")) { const s = new Set(v("pos").split(",").map((p) => data.pos.indexOf(p.trim().toUpperCase())).filter((i) => i >= 0)); if (s.size) state.pos = s; }
    }

    // the dropdown itself: hangs off its button, pointer aimed back at it, closes on any click elsewhere
    const panel = $("filters"), btn = $("filtersBtn");
    function place() {
      const b = btn.getBoundingClientRect();
      panel.style.right = "";
      const edge = 12, r0 = panel.getBoundingClientRect();
      if (r0.left < edge) panel.style.right = (r0.left - edge) + "px";   // nudge it back on screen
      const r = panel.getBoundingClientRect();
      panel.style.setProperty("--caret-x", Math.round(b.left + b.width / 2 - r.left) + "px");
      panel.style.setProperty("--pop-top", Math.round(b.bottom + 12) + "px");
    }
    function setOpen(open) {
      panel.hidden = !open; btn.setAttribute("aria-expanded", open);
      if (open) { place(); onOpen && onOpen(); }
    }
    const isOpen = () => !panel.hidden;
    btn.addEventListener("click", () => setOpen(!isOpen()));
    panel.querySelectorAll('[data-closepanel="filters"]').forEach((b) => b.addEventListener("click", () => setOpen(false)));
    addEventListener("resize", () => { if (isOpen()) place(); });
    document.addEventListener("pointerdown", (e) => { if (isOpen() && !e.target.closest(".fwrap")) setOpen(false); });

    return { state, passes, sync, reset, activeCount, summary, toParams, fromParams, setOpen, isOpen, updateBadge, divName, isD1 };
  }

  // Straight-line distance in miles between two lat/lon points.
  function miles(lat1, lon1, lat2, lon2) {
    const r = Math.PI / 180, a = Math.sin((lat2 - lat1) * r / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin((lon2 - lon1) * r / 2) ** 2;
    return 3958.8 * 2 * Math.asin(Math.min(1, Math.sqrt(a)));
  }
  const median = (arr) => { if (!arr.length) return null; const a = Float64Array.from(arr).sort(), m = a.length >> 1; return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2; };

  // Each page remembers its last view in the browser. The sport is the page's folder
  // (docs/football/players-dotmap.html -> "football"), so every sport keeps its own.
  const sport = decodeURIComponent(location.pathname.split("/").slice(-2, -1)[0] || "");
  const saveKey = (name) => `${sport}:${name}`;
  function readSaved(name) {
    try { return localStorage.getItem(saveKey(name)) || ""; }
    catch (e) { return ""; }
  }

  // Copy the page's link and say so under the button.
  async function copyLink(toast) {
    try { await navigator.clipboard.writeText(location.href); toast.textContent = "Link to this view copied"; }
    catch (e) { toast.textContent = "Copy the link from the address bar"; }
    toast.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => { toast.hidden = true; }, 2200);
  }
  // Keep --bar-h equal to the title bar's height, so panels and pages can start just under it.
  function trackBar(bar) {
    new ResizeObserver(() => document.documentElement.style.setProperty("--bar-h", bar.getBoundingClientRect().height + "px")).observe(bar);
  }

  window.GP = { $, sport, saveKey, readSaved, POS_LABEL, STATE_ABBR, ABBR_STATE, fmt, pct, esc, css, narrow, loadData, makePalette, makeFilters, copyLink, trackBar, miles, median };
})();
