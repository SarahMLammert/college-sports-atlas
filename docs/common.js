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
  // map_data.json since Oct 28 packs the players' columns (scripts/build.py, pack_players): school, first season and
  // division as runs [value, count, ...], the last season as seasons after the first ("len"), and transfer, previous
  // school and its level as [gap, value, ...] for the players they apply to. Unpacked here into plain columns.
  function unpackPlayers(Q) {
    const n = Q.n;
    const runs = (a) => { const out = new Array(n); let k = 0; for (let i = 0; i < a.length; i += 2) for (let j = 0; j < a[i + 1]; j++) out[k++] = a[i]; return out; };
    const sparse = (a, empty) => { const out = new Array(n).fill(empty); let k = -1; for (let i = 0; i < a.length; i += 2) { k += a[i] + 1; out[k] = a[i + 1]; } return out; };
    const f = runs(Q.f);
    return { s: runs(Q.s), t: Q.t, p: Q.p, f, l: f.map((v, i) => v + Q.len[i]), x: sparse(Q.x, 0), o: sparse(Q.o, -1),
             v: sparse(Q.v, 0), d: runs(Q.d), h: Q.h };
  }
  // Big sports (football, baseball) split their players in two (Oct 28): map_data.json has the D1 schools'
  // players, data.more the files with the rest. loadData() waits for all of them unless asked for
  // { all: false } (the dot map, which opens on D1 and calls data.loadAll() when a view needs the others).
  // data.complete says whether everything is in; data.loadAll() adds the rest to the same columns, in place.
  async function loadData({ all = true } = {}) {
    const data = await fetch("map_data.json").then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
    if (data.players.packed) data.players = unpackPlayers(data.players);
    const P = data.players;
    const seasons = () => {
      const set = new Set(); for (let k = 0; k < P.f.length; k++) { set.add(P.f[k]); set.add(P.l[k]); }
      data.SEASONS = [...set].map((f) => f + 2000).sort((a, b) => a - b);   // every season anyone was on a roster
      data.FIRST = data.SEASONS[0]; data.LAST = data.SEASONS[data.SEASONS.length - 1];
    };
    data.N = P.s.length;
    seasons();
    // Players' names: in names.txt since Oct 28 (only the dot map needs them, and it draws before they arrive).
    // data.nameList is filled in place when they load, so code holding it sees them; data.loadNames() fetches
    // them once and resolves when they're in. Data built before then still has them in map_data.json.
    data.nameList = new Array(data.N).fill("");
    let allNames = null, namesLoad = null;
    const fillNames = () => { if (allNames) for (let i = 0; i < data.N; i++) data.nameList[i] = allNames[i] || ""; };
    data.loadNames = () => namesLoad || (namesLoad = (typeof data.names === "string" ? Promise.resolve(data.names)
      : fetch("names.txt").then((r) => { if (!r.ok) throw new Error(r.status); return r.text(); }))
      .then((text) => { allNames = text.split("\n"); fillNames(); data.namesLoaded = true; delete data.names; }));
    if (typeof data.names === "string") data.loadNames();
    // the rest of a split sport
    const more = data.more || [];
    data.complete = more.length === 0;
    let allLoad = null;
    data.loadAll = () => allLoad || (allLoad = Promise.all(more.map((f) => fetch(f).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })))
      .then((parts) => {
        for (const part of parts) {
          const Q = part.players.packed ? unpackPlayers(part.players) : part.players;
          for (const key of Object.keys(P)) { const col = P[key], add = Q[key]; for (let i = 0; i < add.length; i++) col.push(add[i]); }
        }
        data.N = P.s.length;
        for (let i = data.nameList.length; i < data.N; i++) data.nameList.push("");
        fillNames(); seasons();
        data.complete = true;
        return data;
      }));
    if (data.complete) allLoad = Promise.resolve(data);
    data.spring = springOf(data);
    data.seasonLabel = (y) => seasonLabel(y, data.spring);
    data.seasonSpan = (a, b) => seasonSpan(a, b, data.spring);
    data.posLabel = data.posLabels || POS_LABEL;
    data.d1 = data.d1 || D1_DIVS;
    data.divLabel = data.divLabels || DIV_TITLE;
    data.posName = (p) => data.posLabel[p] || p;
    data.tState = data.towns.map((t) => { const parts = t[2].split(", "); return parts[parts.length - 1]; });   // state abbr, or a country
    data.schoolIndex = new Map(data.schools.map((s, i) => [s[0].toLowerCase(), i]));
    // campus city, state and coordinates (built from config/school_locations.csv); the pages work without it
    let loc = null;
    const locLoad = fetch("school_locations.json").then((r) => r.ok ? r.json() : null).catch(() => null);
    if (all) await data.loadAll();
    try { loc = await locLoad; } catch (e) {}
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
    // groups: the set of picked school groups (see below); empty = every school.
    // conf and div are read by the pages: conf is a conference index when exactly one conference is picked,
    // div a division choice when exactly one whole division is picked; otherwise "".
    const state = { school: -1, allSchools: false, groups: new Set(), conf: "", div: "", from: data.FIRST, to: data.LAST, entry: "", pos: allPos() };
    const hasSchool = !!$("school"), hasConf = !!$("conf");
    const confs = data.confs || [];
    const isD1 = (d) => data.d1.includes(data.divs[d]);
    const divName = (v) => v === "D1" ? "D1" : data.divs[+v];

    // ---- Schools sorted into groups: one per division and conference (today's, 2026), e.g. "D2 · GLIAC" ----
    // The Division chips and the Conference list both pick groups, so a chip is "every school in that division"
    // and the list can narrow it to some conferences. Only schools with players count.
    const confOf = (i) => { const c = data.schools[i][1]; return Number.isInteger(c) && c >= 0 && c < confs.length ? c : -1; };
    const confLabel = (c) => (c >= 0 && confs[c]) || "No conference";
    const hasPlayers = new Uint8Array(data.schools.length); P.s.forEach((s) => { hasPlayers[s] = 1; });
    if (!data.complete) hasPlayers.fill(1);   // a big sport with only its D1 part loaded: every school in the data has players
    const groups = [], gKey = new Map(), schoolGroup = new Int32Array(data.schools.length).fill(-1);
    data.schools.forEach((s, i) => {
      if (!hasPlayers[i]) return;
      const div = s[2], conf = confOf(i), key = div + ":" + conf;
      if (!gKey.has(key)) { gKey.set(key, groups.length); groups.push({ div, conf, name: confLabel(conf), n: 0 }); }
      const g = gKey.get(key); groups[g].n++; schoolGroup[i] = g;
    });
    const shownDivs = [...new Set(groups.map((g) => g.div))].sort((a, b) => a - b);
    const groupsOfDiv = new Map(shownDivs.map((d) => [d, groups.map((g, i) => i).filter((i) => groups[i].div === d)
      .sort((a, b) => (groups[a].conf < 0) - (groups[b].conf < 0) || groups[a].name.localeCompare(groups[b].name))]));
    // a name used by more than one division (only "No conference" today) goes in links as "DIV~name"
    const nameCount = new Map(); groups.forEach((g) => nameCount.set(g.name, (nameCount.get(g.name) || 0) + 1));

    // Division chips: one per division with players, plus "D1" when D1 is split (football: FBS + FCS) and other
    // divisions are there too. Each chip is on (all its schools), part on (some of its conferences) or off.
    const d1Group = shownDivs.filter(isD1).length > 1 && shownDivs.some((d) => !isD1(d));
    const chipVals = [...(d1Group ? ["D1"] : []), ...shownDivs.map(String)];
    const chipGroups = (v) => v === "D1" ? shownDivs.filter(isD1).flatMap((d) => groupsOfDiv.get(d)) : groupsOfDiv.get(+v) || [];
    const titleOf = (v) => v === "D1" ? `Division I (${data.d1.join(" and ")})` : data.divLabel[divName(v)] || divName(v);
    const covered = (gs) => gs.length > 0 && gs.every((g) => state.groups.has(g));
    function setGroups(gs, on) {
      gs.forEach((g) => on ? state.groups.add(g) : state.groups.delete(g));
      if (state.groups.size === groups.length) state.groups.clear();   // everything picked = no filter
    }
    // flip a set of groups: from "every school" it starts a pick of just these; otherwise all on, or all off
    function toggleGroups(gs) {
      if (!state.groups.size) { state.groups = new Set(gs); if (state.groups.size === groups.length) state.groups.clear(); }
      else setGroups(gs, !covered(gs));
    }
    // keep the pages' single-choice fields in step with the groups
    function deriveLegacy() {
      state.div = ""; state.conf = "";
      if (!state.groups.size) return;
      const exact = (gs) => gs.length === state.groups.size && covered(gs);
      const v = chipVals.find((x) => exact(chipGroups(x)));
      if (v !== undefined) state.div = v;
      if (state.groups.size === 1) { const g = groups[[...state.groups][0]]; if (g.conf >= 0 && nameCount.get(g.name) === 1) state.conf = String(g.conf); }
    }
    $("div").className = "chips divs";
    $("div").innerHTML = chipVals.map((v) =>
      `<button type="button" class="chip" data-v="${v}" aria-pressed="false" title="${esc(titleOf(v))}: every school">${esc(divName(v))}</button>`).join("");
    $("div").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      toggleGroups(chipGroups(b.dataset.v)); sync(); changed();
    });

    if (hasSchool) {
      $("schoolList").innerHTML = data.schools.map((s) => `<option value="${esc(s[0])}">`).join("");
      $("school").placeholder = `All ${data.schools.length} schools — type to search`;
      $("school").addEventListener("input", (e) => {
        const v = e.target.value.trim().toLowerCase();
        if (!v) onSchool && onSchool(-1);
        else if (data.schoolIndex.has(v)) onSchool && onSchool(data.schoolIndex.get(v));
      });
    }
    // Conference: a box like the season boxes (with the arrow) that opens a checklist below it, grouped by
    // division, with a search box. It replaces whatever control the page has with id="conf".
    let confBtn = null, confPop = null, confSearch = null;
    if (hasConf) {
      injectStyles();
      const old = $("conf"), wrap = document.createElement("div");
      wrap.className = "cpick";
      wrap.innerHTML = `
        <button type="button" class="field cpick-btn" id="conf" aria-expanded="false" aria-controls="confPop">
          <span class="cpick-text">All conferences</span>
          <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M2.5 4.5L6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        <div class="cpick-pop" id="confPop" hidden>
          <div class="cpick-top">
            <input class="cpick-search" type="search" placeholder="Search conferences" aria-label="Search conferences" autocomplete="off">
            <button type="button" class="link cpick-clear">All</button>
          </div>
          <div class="cpick-scroll">${shownDivs.map((d) => `
            <div class="cpick-div" data-d="${d}">
              <label class="cpick-head"><input type="checkbox" data-d="${d}"><span>${esc(data.divLabel[data.divs[d]] || data.divs[d])}</span></label>
              ${groupsOfDiv.get(d).map((g) => `<label class="cpick-row" data-name="${esc(groups[g].name.toLowerCase())}"><input type="checkbox" data-g="${g}"><span>${esc(groups[g].name)}</span><span class="cpick-n">${groups[g].n}</span></label>`).join("")}
            </div>`).join("")}
            <p class="cpick-none" hidden>No conference matches.</p>
          </div>
        </div>`;
      old.replaceWith(wrap);
      confBtn = wrap.querySelector(".cpick-btn"); confPop = wrap.querySelector(".cpick-pop"); confSearch = wrap.querySelector(".cpick-search");
      const openConf = (open) => { confPop.hidden = !open; confBtn.setAttribute("aria-expanded", open); if (open && !narrow()) confSearch.focus(); };
      confBtn.addEventListener("click", () => openConf(confPop.hidden));
      wrap.addEventListener("keydown", (e) => { if (e.key === "Escape" && !confPop.hidden) { e.stopPropagation(); openConf(false); confBtn.focus(); } });
      document.addEventListener("pointerdown", (e) => { if (!confPop.hidden && !e.target.closest(".cpick")) openConf(false); });
      confPop.addEventListener("change", (e) => {
        const t = e.target; if (t.type !== "checkbox") return;
        if (t.dataset.d !== undefined) toggleGroups(groupsOfDiv.get(+t.dataset.d));
        else { const g = +t.dataset.g; if (!state.groups.size) state.groups = new Set([g]); else setGroups([g], t.checked); }
        sync(); changed();
      });
      wrap.querySelector(".cpick-clear").addEventListener("click", () => { state.groups.clear(); sync(); changed(); });
      confSearch.addEventListener("input", () => {
        const q = confSearch.value.trim().toLowerCase(); let any = false;
        confPop.querySelectorAll(".cpick-div").forEach((box) => {
          let shown = 0;
          box.querySelectorAll(".cpick-row").forEach((r) => { const ok = !q || r.dataset.name.includes(q); r.hidden = !ok; shown += ok; });
          box.hidden = !shown; any = any || shown > 0;
        });
        confPop.querySelector(".cpick-none").hidden = any;
      });
    }
    // What the closed box says: "All conferences", "D2", "GLIAC", "D2, SEC", or "12 conferences"
    function confText() {
      if (!state.groups.size) return "All conferences";
      const left = new Set(state.groups), parts = [];
      for (const v of chipVals) { const gs = chipGroups(v); if (gs.every((g) => left.has(g))) { parts.push(divName(v)); gs.forEach((g) => left.delete(g)); } }
      left.forEach((g) => parts.push(nameCount.get(groups[g].name) > 1 ? `${groups[g].name} (${data.divs[groups[g].div]})` : groups[g].name));
      return parts.length <= 2 ? parts.join(", ") : `${state.groups.size} conferences`;
    }
    for (const id of ["from", "to"]) data.SEASONS.forEach((y) => { const o = document.createElement("option"); o.value = y; o.textContent = data.seasonLabel(y); $(id).appendChild(o); });
    $("from").addEventListener("change", (e) => { state.from = +e.target.value; if (state.from > state.to) state.to = state.from; sync(); changed(); });
    $("to").addEventListener("change", (e) => { state.to = +e.target.value; if (state.to < state.from) state.from = state.to; sync(); changed(); });
    data.pos.forEach((p, i) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "chip"; b.textContent = data.posName(p); b.dataset.i = i; b.setAttribute("aria-pressed", "false");
      // each chip is an on/off switch: click to show only the lit groups, click again to turn it off;
      // turning off the last lit chip (or lighting every one) means every position again
      b.addEventListener("click", () => {
        if (state.pos.size === data.pos.length) state.pos = new Set([i]);
        else if (state.pos.has(i)) { state.pos.delete(i); if (!state.pos.size) state.pos = allPos(); }
        else { state.pos.add(i); }
        sync(); changed();
      });
      $("pos").appendChild(b);
    });
    $("posAll").addEventListener("click", () => { state.pos = allPos(); sync(); changed(); });
    $("entry").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      // clicking the button that's already on turns it off (back to All)
      state.entry = state.entry === b.dataset.v ? "" : b.dataset.v; sync(); changed();
    });
    $("resetAll").addEventListener("click", () => { reset(); sync(); changed(); });

    function changed() { updateBadge(); onChange && onChange(); }
    function setSeg(id, v) { $(id).querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x.dataset.v === v)); }
    function sync() {
      deriveLegacy();
      if (hasSchool) $("school").value = state.school >= 0 ? data.schools[state.school][0] : "";
      $("from").value = state.from; $("to").value = state.to;
      setSeg("entry", state.entry);
      // division chips: lit = every school in it, "mixed" = some of its conferences, none lit = every school
      $("div").querySelectorAll("button").forEach((b) => {
        const gs = chipGroups(b.dataset.v), n = gs.filter((g) => state.groups.has(g)).length;
        b.setAttribute("aria-pressed", n && n === gs.length ? "true" : n ? "mixed" : "false");
      });
      if (confBtn) {
        confBtn.querySelector(".cpick-text").textContent = confText();
        confBtn.classList.toggle("on", state.groups.size > 0);
        confPop.querySelectorAll("input[data-g]").forEach((c) => { c.checked = state.groups.has(+c.dataset.g); });
        confPop.querySelectorAll("input[data-d]").forEach((c) => {
          const gs = groupsOfDiv.get(+c.dataset.d), n = gs.filter((g) => state.groups.has(g)).length;
          c.checked = n > 0 && n === gs.length; c.indeterminate = n > 0 && n < gs.length;
        });
      }
      // no position chip lit = every position; a lit chip is one you turned on
      const allOn = state.pos.size === data.pos.length;
      $("pos").querySelectorAll(".chip").forEach((b) => b.setAttribute("aria-pressed", !allOn && state.pos.has(+b.dataset.i)));
      updateBadge();
    }
    function reset() {
      Object.assign(state, { school: -1, allSchools: false, groups: new Set(), conf: "", div: "", from: data.FIRST, to: data.LAST, entry: "", pos: allPos() });
    }
    function activeCount() {
      return (hasSchool && state.school >= 0) + (state.groups.size > 0) + (state.from !== data.FIRST || state.to !== data.LAST)
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
      if (state.entry !== "" && P.x[k] !== +state.entry) return false;
      if (!state.pos.has(P.p[k])) return false;
      // division and conference: the school's (2026), picked as groups
      if (!skipConf && state.groups.size && !state.groups.has(schoolGroup[P.s[k]])) return false;
      return true;
    }
    // is this school inside the picked divisions and conferences?
    const schoolOk = (i) => !state.groups.size || state.groups.has(schoolGroup[i]);
    // A short description of the player filters, e.g. "FCS · 2019–2024 · transfers · QB, WR"
    function summary() {
      const parts = [];
      // a single conference is named by the page itself (its scope line), so only say the rest here
      if (state.groups.size && state.conf === "") parts.push(confText());
      if (state.from !== data.FIRST || state.to !== data.LAST) parts.push(data.seasonSpan(state.from, state.to));
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
      // div=D2,NAIA (whole divisions) and conf=SEC|GLIAC (single conferences; D2~No conference when a name repeats)
      if (state.groups.size) {
        const left = new Set(state.groups), divs = [], cs = [];
        for (const v of chipVals) { const gs = chipGroups(v); if (gs.every((g) => left.has(g))) { divs.push(divName(v)); gs.forEach((g) => left.delete(g)); } }
        left.forEach((g) => cs.push(nameCount.get(groups[g].name) > 1 ? `${data.divs[groups[g].div]}~${groups[g].name}` : groups[g].name));
        if (divs.length) q.set("div", divs.join(","));
        if (cs.length) q.set("conf", cs.join("|"));
      }
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
      // (an empty conf used to match the blank conference name and pick it on every load: skip empty pieces)
      for (const dv of v("div").toUpperCase().split(",").map((x) => x.trim()).filter(Boolean)) {
        const val = dv === "D1" && d1Group ? "D1" : String(data.divs.indexOf(dv));
        if (chipVals.includes(val)) chipGroups(val).forEach((g) => state.groups.add(g));
      }
      for (const tok of v("conf").split("|").map((x) => x.trim()).filter(Boolean)) {
        const [dn, name] = tok.includes("~") ? tok.split("~") : [null, tok];
        groups.forEach((g, i) => { if (g.name === name && (dn === null || data.divs[g.div] === dn)) state.groups.add(i); });
      }
      if (state.groups.size === groups.length) state.groups.clear();
      deriveLegacy();
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

    // true when every school the filters let through is a D1 school (the dot map then needn't load the rest)
    function onlyD1() {
      if (state.school >= 0) return isD1(data.schools[state.school][2]);
      return state.groups.size > 0 && [...state.groups].every((g) => isD1(groups[g].div));
    }
    return { state, passes, schoolOk, confText, sync, reset, activeCount, summary, toParams, fromParams, setOpen, isOpen, updateBadge, divName, isD1, onlyD1 };
  }

  // Styles for the conference checklist and the part-on division chip, so no page needs its own copy.
  function injectStyles() {
    if ($("cpickStyles")) return;
    const s = document.createElement("style"); s.id = "cpickStyles";
    s.textContent = `
      .chip[aria-pressed="mixed"] { border-style: dashed; border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
      .cpick { position: relative; }
      .cpick-btn { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; text-align: left; cursor: pointer; }
      .cpick-btn .cpick-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .cpick-btn svg { flex: none; transition: transform .15s; }
      .cpick-btn[aria-expanded="true"] svg { transform: rotate(180deg); }
      .cpick-btn[aria-expanded="true"], .cpick-btn.on { border-color: var(--accent); }
      .cpick-pop { margin-top: 6px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); overflow: hidden; }
      .cpick-pop[hidden] { display: none; }
      .cpick-top { display: flex; align-items: center; gap: 8px; padding: 8px; border-bottom: 1px solid var(--line); }
      .cpick-search { flex: 1; min-width: 0; font: inherit; font-size: 14px; color: inherit; padding: 6px 9px; border: 1px solid var(--line); border-radius: 6px; background: transparent; }
      .cpick-search:focus { outline: none; border-color: var(--accent); }
      .cpick-scroll { max-height: 280px; overflow: auto; overscroll-behavior: contain; padding: 4px 0 6px; }
      .cpick-div[hidden], .cpick-row[hidden] { display: none; }
      .cpick-head, .cpick-row { display: flex; align-items: center; gap: 8px; padding: 4px 10px; cursor: pointer; font-size: 14px; }
      .cpick-head { margin-top: 4px; font-weight: 700; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted, inherit); }
      .cpick-row { padding-left: 30px; }
      .cpick-head:hover, .cpick-row:hover { background: var(--accent-soft); }
      .cpick-row span:first-of-type { flex: 1; }
      .cpick-n { font-size: 12px; opacity: .65; font-variant-numeric: tabular-nums; }
      .cpick input[type="checkbox"] { accent-color: var(--accent); margin: 0; width: 15px; height: 15px; flex: none; }
      .cpick-none { margin: 8px 10px; font-size: 13px; opacity: .7; }`;
    document.head.appendChild(s);
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

  // staff_data.json since Oct 28 packs its stints (scripts/staff.py, pack_stints): per person the number of seasons
  // ("n"), the first season - 2000 then the gap to the next ("y"), and school, role and title as 0 when the same as
  // the season before, else value + 1. Unpacked here into plain columns p, s, y, r, t.
  function unpackStints(q) {
    if (!q.packed) return q;
    const people = q.people || q.n.map((_, i) => (q.first || 0) + i);
    const st = { p: [], s: [], y: [], r: [], t: [] };
    let k = 0;
    people.forEach((person, i) => {
      for (let j = 0; j < q.n[i]; j++, k++) {
        st.p.push(person);
        st.y.push(q.y[k] + (j === 0 ? 2000 : st.y[st.y.length - 1]));
        for (const c of ["s", "r", "t"]) st[c].push(j === 0 || q[c][k] ? q[c][k] - 1 : st[c][st[c].length - 1]);
      }
    });
    return st;
  }
  // Seasons are shown as school years: "2023-24". A season number is the year it starts for fall sports (football,
  // volleyball, soccer: 2023 = 2023-24) and the year it ends for the rest (2024 = 2023-24). data.spring says which;
  // data built before Oct 29 doesn't say, so the sport's name decides.
  const FALL_SPORT = /football|volleyball|soccer/i;
  const springOf = (d) => d.spring !== undefined ? !!d.spring : !FALL_SPORT.test(d.sport || "");
  function seasonLabel(y, spring) {
    const a = spring ? y - 1 : y;
    return `${a}-${String((a + 1) % 100).padStart(2, "0")}`;
  }
  function seasonSpan(a, b, spring) { return a === b ? seasonLabel(a, spring) : `${seasonLabel(a, spring)} to ${seasonLabel(b, spring)}`; }
  window.GP = { $, sport, saveKey, readSaved, POS_LABEL, STATE_ABBR, ABBR_STATE, fmt, pct, esc, css, narrow, loadData, unpackStints, springOf, seasonLabel, seasonSpan, makePalette, makeFilters, copyLink, trackBar, miles, median };
})();
