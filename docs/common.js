// Shared by every page of every sport (docs/players-*.html and staff-*.html, one set for all sports):
// which sport the page shows, constants, loading the data, school colors, and the Filters dropdown (its
// controls, logic and link format). Load after d3 and sports.js.
(function () {
  const $ = (id) => document.getElementById(id);

  // ---------- which sport ----------
  // The sport is in the address: players-dotmap.html?sport=softball. Its data is in its own folder
  // (docs/softball/map_data.json). The old addresses (docs/softball/players-dotmap.html) forward here.
  const SPORT_PAGES = window.SPORT_PAGES || {};
  const sport = new URLSearchParams(location.search).get("sport") || "";
  if (!SPORT_PAGES[sport]) {                  // no sport, or one that doesn't exist: the front page
    location.replace("index.html");
    throw new Error(`unknown sport "${sport}"`);
  }
  const dataUrl = (file) => `${encodeURIComponent(sport)}/${file}`;
  const women = !!SPORT_PAGES[sport].women;
  const pronoun = { he: women ? "she" : "he", his: women ? "her" : "his" };
  // The sport's own words on this page (sports.js): title, description, heading, subtitle.
  const pageName = location.pathname.split("/").pop().replace(/\.html$/, "") || "players-dotmap";
  const words = SPORT_PAGES[sport][pageName];
  function putWords() {
    if (!words) return;
    if (words.title) document.title = words.title;
    const meta = document.querySelector('meta[name="description"]');
    if (meta && words.description) meta.setAttribute("content", words.description);
    const h1 = document.querySelector("header h1") || document.querySelector("h1");
    if (h1 && words.h1) h1.innerHTML = words.h1;
    const sub = $("sub");
    if (sub && words.sub) sub.innerHTML = words.sub;
  }
  // Links to the other map pages keep the sport: players-heatmap.html -> players-heatmap.html?sport=softball.
  // Links written later by the pages' scripts are fixed as they appear.
  const PAGE_LINK = /^((?:players|staff|school)-[a-z-]+\.html)(\?[^#]*)?(#.*)?$/;
  function keepSport(a) {
    const href = a.getAttribute("href");
    const m = href && href.match(PAGE_LINK);
    if (!m || /[?&]sport=/.test(m[2] || "")) return;
    a.setAttribute("href", `${m[1]}${m[2] ? m[2] + "&" : "?"}sport=${encodeURIComponent(sport)}${m[3] || ""}`);
  }
  function keepSportIn(node) {
    if (node.nodeType !== 1) return;
    if (node.matches("a[href]")) keepSport(node);
    node.querySelectorAll("a[href]").forEach(keepSport);
  }
  function startPage() {
    putWords();
    mapTabs();
    keepSportIn(document.body);
    new MutationObserver((list) => list.forEach((m) => {
      if (m.type === "attributes") keepSport(m.target); else m.addedNodes.forEach(keepSportIn);
    })).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["href"] });
  }
  // ---------- tabs ----------
  // The strip of maps in every page's title bar. A map opens on the school this page is showing, which every page
  // keeps in its address (school=Alabama, or the first of compare=Alabama|Georgia on Footprints).
  const MAPS = [
    ["Players", [["players-dotmap", "Recruiting Map"], ["players-heatmap", "Footprints"], ["players-transfers", "Transfer Map"]]],
    ["Coaches", [["staff-moves", "Coaching Moves"], ["staff-directory", "Staff Directory"]]],
    ["Schools", [["school-influence", "School Influence"]]],
  ];
  function mapTabs() {
    const nav = $("mapTabs"), here = location.pathname.split("/").pop().replace(".html", "");
    if (!nav) return;
    nav.innerHTML = MAPS.map(([group, maps]) => `<span class="grp">${group}</span>` + maps.map(([page, name]) =>
      `<a href="${page}.html"${page === here ? ' aria-current="page"' : ""}>${name}</a>`).join("")).join("");
    const on = nav.querySelector("[aria-current]");
    if (on) nav.scrollLeft = on.offsetLeft - 60;      // phones: the strip scrolls, so show this page's tab
    const carry = (e) => {
      const a = e.target.closest && e.target.closest("a");
      if (!a) return;
      const q = new URLSearchParams(location.hash.slice(1)), school = q.get("school") || (q.get("compare") || "").split("|")[0];
      const page = a.getAttribute("href").split(/[?#]/)[0], key = page === "players-heatmap.html" ? "compare" : "school";
      a.setAttribute("href", `${page}?sport=${encodeURIComponent(sport)}${school && school !== "all" ? `#${key}=${encodeURIComponent(school)}` : ""}`);
    };
    nav.addEventListener("pointerdown", carry, true);
    nav.addEventListener("click", carry, true);
    sportPicker(nav, here);
  }
  // The sport dropdown: the same map for another sport, on the same school when it has one. Built sports only.
  function sportPicker(nav, here) {
    const discs = (window.SPORT_DISCS || []).filter((d) => d.teams.some((t) => t.built));
    if (!discs.length) return;
    const SEX = { m: " (Men's)", w: " (Women's)" }, seasons = ["fall", "winter", "spring"];
    const options = (ring) => discs.filter((d) => d.ring === ring).flatMap((d) => d.teams.filter((t) => t.built).map((t) =>
      `<option value="${t.id}"${t.id === sport ? " selected" : ""}>${d.name}${SEX[t.sex] || (d.sub ? ` (${d.sub})` : "")}</option>`)).join("");
    const pick = document.createElement("select");
    pick.className = "field sportpick"; pick.id = "sportPick"; pick.setAttribute("aria-label", "Sport");
    pick.innerHTML = seasons.map((r) => `<optgroup label="${r[0].toUpperCase() + r.slice(1)}">${options(r)}</optgroup>`).join("");
    const home = nav.parentElement.querySelector('a[href^="index.html"]');
    if (home) home.after(pick); else nav.parentElement.prepend(pick);
    pick.addEventListener("change", () => {
      const q = new URLSearchParams(location.hash.slice(1)), school = q.get("school") || (q.get("compare") || "").split("|")[0];
      const key = here === "players-heatmap" ? "compare" : "school";
      location.href = `${here}.html?sport=${encodeURIComponent(pick.value)}${school && school !== "all" ? `#${key}=${encodeURIComponent(school)}` : ""}`;
    });
  }
  // The active filters as chips under the title or above the map; a chip's × clears that filter.
  // items: [[label, clear], ...]
  function showChips(el, items) {
    if (!el) return;
    el._clear = items.map((x) => x[1]);
    el.innerHTML = items.map(([label], i) => `<button type="button" class="fchip" data-i="${i}" aria-label="Clear filter: ${esc(label)}">${esc(label)}<span aria-hidden="true">×</span></button>`).join("");
    el.hidden = !items.length;
    if (!el._wired) {
      el._wired = true;
      el.addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) el._clear[+b.dataset.i](); });
    }
  }
  const tabCount = (label, n) => `${label} <span class="ct">${fmt(n)}</span>`;
  // The dropdown under a page's Filters button: hangs off the button, pointer aimed back at it, closes on any click elsewhere.
  function dropdown(onOpen) {
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
    return { setOpen, isOpen };
  }
  // Tabs inside a page. A page has one set; the open tab is kept here, so a list redrawn with new numbers stays on it,
  // and in the address (tab=), like the rest of a view. A set is [[key, label, html], ...]; a tab with no html is left out.
  let tabKey = "";
  function tabsHTML(tabs, label) {
    tabs = tabs.filter((t) => t[2]);
    const on = tabs.some((t) => t[0] === tabKey) ? tabKey : tabs[0][0];
    return `<div class="tabset"><div class="tabs" role="tablist" aria-label="${label}">${tabs.map(([k, name]) =>
      `<button type="button" role="tab" data-tab="${k}" aria-selected="${k === on}"${k === on ? "" : ' tabindex="-1"'}>${name}</button>`).join("")}</div>
      ${tabs.map(([k, , html]) => `<div class="tabpanel" role="tabpanel" data-tab="${k}"${k === on ? "" : " hidden"}>${html}</div>`).join("")}</div>`;
  }
  function openTab(btn) {
    const set = btn.closest(".tabset"), k = btn.dataset.tab;
    set.querySelectorAll(":scope > .tabs [role=tab]").forEach((b) => {
      b.setAttribute("aria-selected", b === btn);
      if (b === btn) b.removeAttribute("tabindex"); else b.tabIndex = -1;
    });
    set.querySelectorAll(":scope > .tabpanel").forEach((p) => { p.hidden = p.dataset.tab !== k; });
    tabKey = k;
    document.dispatchEvent(new CustomEvent("gp-tab", { detail: k }));
  }
  function tabToParams(q) {         // the first tab is the default, so it stays out of the address
    const first = document.querySelector("[role=tab]");
    if (tabKey && first && tabKey !== first.dataset.tab) q.set("tab", tabKey);
  }
  function tabFromParams(q) { tabKey = q.get("tab") || ""; }
  function showTab(k) { const b = document.querySelector(`[role=tab][data-tab="${k}"]`); if (b) openTab(b); }
  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest("[role=tab]");
    if (!b) return;
    openTab(b);
    const q = new URLSearchParams(location.hash.slice(1));
    q.delete("tab"); tabToParams(q);
    setHash(q.toString());
  });
  document.addEventListener("keydown", (e) => {       // arrow keys move along the tabs
    const b = e.target.closest && e.target.closest("[role=tab]"), step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    if (!b || !step) return;
    const all = [...b.parentElement.children], next = all[(all.indexOf(b) + step + all.length) % all.length];
    next.focus(); next.click();
    e.preventDefault();
  });
  if (document.body) startPage(); else document.addEventListener("DOMContentLoaded", startPage);
  // Each sport's map_data.json says how it writes its positions and divisions (from config/<sport>/settings.json):
  //   data.posLabels  position group -> chip text ("FO" -> "Faceoff")
  //   data.d1         the divisions that make up D1 (football: FBS and FCS; lacrosse: D1)
  //   data.divLabels  division -> its full name ("D2" -> "Division II")
  const STATE_ABBR = {"Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA","Colorado":"CO","Connecticut":"CT","Delaware":"DE","District of Columbia":"DC","Florida":"FL","Georgia":"GA","Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA","Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD","Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT","Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY","Puerto Rico":"PR"};
  const ABBR_STATE = Object.fromEntries(Object.entries(STATE_ABBR).map(([k, v]) => [v, k]));
  const fmt = d3.format(",");
  const pct = (x) => x > 0 && x < .005 ? "<1%" : d3.format(".0%")(x);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const narrow = () => matchMedia("(max-width: 760px)").matches;

  // ---------- data ----------
  // map_data.json packs the players' columns (scripts/build.py, pack_players): school, first season and
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
  // Big sports (football, baseball) split their players in two: map_data.json has the D1 schools'
  // players, data.more the files with the rest. loadData() waits for all of them unless asked for
  // { all: false } (the dot map, which opens on D1 and calls data.loadAll() when a view needs the others).
  // data.complete says whether everything is in; data.loadAll() adds the rest to the same columns, in place.
  async function loadData({ all = true } = {}) {
    const data = await fetch(dataUrl("map_data.json")).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
    if (data.players.packed) data.players = unpackPlayers(data.players);
    const P = data.players;
    const seasons = () => {
      const set = new Set(); for (let k = 0; k < P.f.length; k++) { set.add(P.f[k]); set.add(P.l[k]); }
      data.SEASONS = [...set].map((f) => f + 2000).sort((a, b) => a - b);   // every season anyone was on a roster
      data.FIRST = data.SEASONS[0]; data.LAST = data.SEASONS[data.SEASONS.length - 1];
    };
    data.N = P.s.length;
    seasons();
    // Players' names: in names.txt (only the dot map needs them, and it draws before they arrive).
    // data.nameList is filled in place when they load, so code holding it sees them; data.loadNames() fetches
    // them once and resolves when they're in. Data built before then still has them in map_data.json.
    data.nameList = new Array(data.N).fill("");
    let allNames = null, namesLoad = null;
    const fillNames = () => { if (allNames) for (let i = 0; i < data.N; i++) data.nameList[i] = allNames[i] || ""; };
    data.loadNames = () => namesLoad || (namesLoad = (typeof data.names === "string" ? Promise.resolve(data.names)
      : fetch(dataUrl("names.txt")).then((r) => { if (!r.ok) throw new Error(r.status); return r.text(); }))
      .then((text) => { allNames = text.split("\n"); fillNames(); data.namesLoaded = true; delete data.names; }));
    if (typeof data.names === "string") data.loadNames();
    // the rest of a split sport
    const more = data.more || [];
    data.complete = more.length === 0;
    let allLoad = null;
    data.loadAll = () => allLoad || (allLoad = Promise.all(more.map((f) => fetch(dataUrl(f)).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })))
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
    data.spring = springOf();
    data.seasonLabel = (y) => seasonLabel(y, data.spring);
    data.seasonSpan = (a, b) => seasonSpan(a, b, data.spring);
    data.posLabel = data.posLabels;
    data.divLabel = data.divLabels;
    data.posName = (p) => data.posLabel[p] || p;
    data.tState = data.towns.map((t) => { const parts = t[2].split(", "); return parts[parts.length - 1]; });   // state abbr, or a country
    data.schoolIndex = new Map(data.schools.map((s, i) => [s[0].toLowerCase(), i]));
    // campus city, state and coordinates (built from config/school_locations.csv); the pages work without it
    let loc = null;
    const locLoad = fetch(dataUrl("school_locations.json")).then((r) => r.ok ? r.json() : null).catch(() => null);
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
      showChips($("fchips"), activeChips());
    }
    function activeChips() {
      const clear = (fn) => () => { fn(); sync(); changed(); }, out = [], dots = $("fchips");
      if (hasSchool && state.school >= 0 && !(dots && "noschool" in dots.dataset)) out.push([data.schools[state.school][0], clear(() => { state.school = -1; })]);
      if (state.groups.size) out.push([confText(), clear(() => { state.groups.clear(); })]);
      if (state.from !== data.FIRST || state.to !== data.LAST) out.push([`${data.seasonLabel(state.from)} to ${data.seasonLabel(state.to)}`, clear(() => { state.from = data.FIRST; state.to = data.LAST; })]);
      if (state.entry !== "") out.push([state.entry === "1" ? "Transfers" : "High school recruits", clear(() => { state.entry = ""; })]);
      if (state.pos.size !== data.pos.length) out.push([`${state.pos.size} of ${data.pos.length} positions`, clear(() => { state.pos = allPos(); })]);
      return out;
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

    const { setOpen, isOpen } = dropdown(onOpen);

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

  // Each page remembers its last view in the browser, separately for every sport.
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

  // staff_data.json packs its stints (scripts/staff.py, pack_stints): per person the number of seasons
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
  // volleyball, soccer: 2023 = 2023-24) and the year it ends for the rest (2024 = 2023-24). The sport's
  // settings say which (sports.js, from spring_season).
  const springOf = () => !!(SPORT_PAGES[sport] || {}).spring;
  function seasonLabel(y, spring) {
    const a = spring ? y - 1 : y;
    return `${a}-${String((a + 1) % 100).padStart(2, "0")}`;
  }
  function seasonSpan(a, b, spring) { return a === b ? seasonLabel(a, spring) : `${seasonLabel(a, spring)} to ${seasonLabel(b, spring)}`; }
  // ---------- small things every map page needs ----------
  const plural = (n, w) => `${fmt(n)} ${w}${n === 1 ? "" : "s"}`;
  const US_FIT = { type: "MultiPoint", coordinates: [[-124.7, 48.4], [-67, 47.4], [-80.1, 25.1], [-117.1, 32.5], [-97.2, 25.9], [-160, 21], [-150, 61]] };
  // The states' outlines. The route maps leave Puerto Rico out; the heat maps keep it.
  async function usStates(withPuertoRico) {
    const r = await fetch("https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json");
    if (!r.ok) throw new Error(r.status);
    const us = await r.json(), all = topojson.feature(us, us.objects.states).features;
    return withPuertoRico ? all : all.filter((f) => f.properties.name !== "Puerto Rico");
  }
  // A route's curve between two points on a map: a quadratic curve bending to one side.
  function curve(a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1, bend = Math.min(.22 * len, 90);
    return { a, b, c: [(a[0] + b[0]) / 2 + dy / len * bend, (a[1] + b[1]) / 2 - dx / len * bend] };
  }
  // ---------- the route map: Transfer Map, Coaching Moves and School Influence ----------
  // Campuses on a US map in a <canvas id="cv"> inside #tmap, with a tooltip #ttip. The page draws its own
  // content in draw(); this keeps the canvas sized, the states and campuses projected, and has the drawing
  // and pointing helpers the three pages share. hover: {move(mx, my), leave(), click(mx, my)} in map pixels.
  function routeMap(campus, draw, hover, failed) {
    const box = $("tmap"), cv = $("cv"), tip = $("ttip"), g = cv.getContext("2d"), albers = d3.geoAlbersUsa();
    let stateFeatures = [];
    const m = { g, size: { w: 0, h: 0, dpr: 1 }, xy: [], statePaths: [] };
    m.layout = () => {
      const r = box.getBoundingClientRect();
      if (!r.width) return;
      const dpr = Math.min(devicePixelRatio || 1, 2);
      m.size = { w: r.width, h: r.height, dpr };
      cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
      albers.fitExtent([[12, 12], [r.width - 12, r.height - 12]], US_FIT);
      const path = d3.geoPath(albers);
      m.statePaths = stateFeatures.map((f) => new Path2D(path(f) || ""));
      m.xy = campus.map((c) => c ? albers([c.lon, c.lat]) : null);
      draw();
    };
    // a cleared canvas with the states on it; false before the map has a size
    m.clear = () => {
      const { w, h, dpr } = m.size;
      if (!w) return false;
      g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
      g.fillStyle = css("--land"); for (const p of m.statePaths) g.fill(p);
      g.strokeStyle = css("--border"); g.lineWidth = .7; for (const p of m.statePaths) g.stroke(p);
      return true;
    };
    m.stroke = (q) => { g.beginPath(); g.moveTo(q.a[0], q.a[1]); g.quadraticCurveTo(q.c[0], q.c[1], q.b[0], q.b[1]); g.stroke(); };
    m.arrow = (q, color, w) => {              // direction at the end of a quadratic curve is b - c
      const ang = Math.atan2(q.b[1] - q.c[1], q.b[0] - q.c[0]), s = 4 + w * 1.6, tip = [q.b[0] - Math.cos(ang) * 5, q.b[1] - Math.sin(ang) * 5];
      g.beginPath(); g.moveTo(tip[0], tip[1]);
      g.lineTo(tip[0] - Math.cos(ang - .45) * s, tip[1] - Math.sin(ang - .45) * s);
      g.lineTo(tip[0] - Math.cos(ang + .45) * s, tip[1] - Math.sin(ang + .45) * s);
      g.closePath(); g.fillStyle = color; g.fill();
    };
    m.dot = (p, r, fill, ring, strong, fillAlpha) => {   // a campus; strong: hovered or picked
      const alpha = g.globalAlpha;
      g.beginPath(); g.arc(p[0], p[1], r, 0, Math.PI * 2); g.fillStyle = fill;
      if (fillAlpha !== undefined) g.globalAlpha = fillAlpha;
      g.fill(); g.globalAlpha = alpha;
      g.lineWidth = strong ? 2.5 : 1; g.strokeStyle = ring; g.stroke();
    };
    m.label = (i, text) => {                  // a school's name beside its campus
      const p = m.xy[i]; if (!p) return;
      g.font = `600 13px ${css("--body")}`; g.textBaseline = "middle";
      const tw = g.measureText(text).width, x = Math.min(p[0] + 12, m.size.w - tw - 8);
      g.lineWidth = 4; g.strokeStyle = css("--panel"); g.strokeText(text, x, p[1]); g.fillStyle = css("--fg"); g.fillText(text, x, p[1]);
    };
    // The routes between campuses (Transfer Map, Coaching Moves): r.from -> r.to, r.n people, busiest first.
    // look: {width: [min, extra], all: [alpha, extra], sel: [alpha, extra], arrowFrom: share of the busiest}.
    m.flows = (routes, sel, hoverRoute, look) => {
      const cIn = css("--in"), cOut = css("--out"), muted = css("--muted"), xy = m.xy;
      const drawable = routes.filter((r) => xy[r.from] && xy[r.to]);
      const shown = sel >= 0 ? drawable : drawable.slice(0, look.max);
      const maxN = Math.max(1, ...shown.map((r) => r.n)), width = (n) => look.width[0] + look.width[1] * Math.sqrt(n / maxN);
      const [a0, a1] = sel < 0 ? look.all : look.sel;
      g.lineCap = "round";
      for (let i = shown.length - 1; i >= 0; i--) {   // busiest last, so they draw on top
        const r = shown[i], q = curve(xy[r.from], xy[r.to]), color = sel < 0 ? muted : r.to === sel ? cIn : cOut;
        g.globalAlpha = a0 + a1 * Math.sqrt(r.n / maxN);
        g.strokeStyle = color; g.lineWidth = width(r.n); m.stroke(q);
        if (sel >= 0 && r.n / maxN > look.arrowFrom) m.arrow(q, color, width(r.n));
      }
      g.globalAlpha = 1;
      if (hoverRoute && xy[hoverRoute.from] && xy[hoverRoute.to]) {   // the route under the pointer, on top with an arrow
        const hr = hoverRoute, q = curve(xy[hr.from], xy[hr.to]), color = sel < 0 ? css("--accent") : hr.to === sel ? cIn : cOut;
        const lw = Math.max(2.5, width(hr.n) + 1);
        g.strokeStyle = css("--panel"); g.lineWidth = lw + 3; m.stroke(q);
        g.strokeStyle = color; g.lineWidth = lw; m.stroke(q); m.arrow(q, color, lw);
      }
    };
    // Every campus, sized by busy(i) (people in and out with these filters); the picked one big and named.
    m.campuses = (busy, sel, hoverSchool, pal, name) => {
      const fg = css("--fg"), panel = css("--panel"), muted = css("--muted");
      const ids = campus.map((_, i) => i).filter((i) => m.xy[i]), maxB = Math.max(1, ...campus.map((_, i) => busy(i)));
      for (const i of ids.sort((a, b) => busy(a) - busy(b))) {
        const b = busy(i), r = i === sel ? 7 : b ? 2.2 + 4.3 * Math.sqrt(b / maxB) : 1.6;
        g.globalAlpha = sel < 0 || i === sel || b > 0 ? 1 : .35;
        m.dot(m.xy[i], r, b || i === sel ? pal[i].fill : muted, i === hoverSchool ? fg : panel, i === sel || i === hoverSchool);
      }
      g.globalAlpha = 1;
      if (sel >= 0) m.label(sel, name(sel));
    };
    // the nearest campus within 14 px for which ok(i), or -1
    m.schoolAt = (mx, my, ok) => {
      let best = -1, bd = 14 * 14;
      m.xy.forEach((p, i) => { if (!p) return; const d = (p[0] - mx) ** 2 + (p[1] - my) ** 2; if (d < bd && ok(i)) { bd = d; best = i; } });
      return best;
    };
    // the route within 8 px of the pointer, or null
    m.routeAt = (routes, mx, my) => {
      let best = null, bd = 8;
      for (const r of routes) {
        const a = m.xy[r.from], b = m.xy[r.to]; if (!a || !b) continue;
        const q = curve(a, b);
        for (let t = 0; t <= 1; t += .05) {
          const x = (1 - t) ** 2 * q.a[0] + 2 * (1 - t) * t * q.c[0] + t * t * q.b[0], y = (1 - t) ** 2 * q.a[1] + 2 * (1 - t) * t * q.c[1] + t * t * q.b[1];
          const d = Math.hypot(x - mx, y - my); if (d < bd) { bd = d; best = r; }
        }
      }
      return best;
    };
    m.tip = (html, x, y) => {
      tip.innerHTML = html; tip.hidden = false;
      const tw = tip.offsetWidth, th = tip.offsetHeight;
      tip.style.left = Math.max(6, Math.min(x + 14, m.size.w - tw - 6)) + "px";
      tip.style.top = Math.max(6, y - th - 10 < 6 ? y + 16 : y - th - 10) + "px";
    };
    m.hideTip = () => { tip.hidden = true; };
    m.hot = (on) => cv.classList.toggle("hot", on);
    const at = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    cv.addEventListener("pointermove", (e) => { if (m.size.w) hover.move(...at(e)); });
    cv.addEventListener("pointerleave", () => { tip.hidden = true; hover.leave(); });
    cv.addEventListener("click", (e) => hover.click(...at(e)));
    // Start: size the map now; the states' outlines load in the background (campuses and routes draw without them).
    m.start = async () => {
      new ResizeObserver(m.layout).observe(box);
      m.layout();
      try { stateFeatures = await usStates(); m.layout(); } catch (e) { failed(); }
    };
    return m;
  }
  function loadFailed(what) {
    $("loading").classList.add("failed");
    $("loading").textContent = `${what} didn't load. If you opened this file directly, serve the folder instead (python -m http.server), or reload to try again.`;
  }
  // Put the view in the address without adding a history step (sandboxed previews can refuse).
  function setHash(h) {
    try { history.replaceState(null, "", location.pathname + location.search + (h ? "#" + h : "")); } catch (e) { /* stays as it was */ }
  }
  window.GP = { showChips, tabCount, dropdown, tabsHTML, tabToParams, tabFromParams, showTab, plural, US_FIT, usStates, curve, routeMap, loadFailed, setHash, $, dataUrl, he: pronoun.he, his: pronoun.his, saveKey, readSaved, STATE_ABBR, ABBR_STATE, fmt, pct, esc, css, narrow, loadData, unpackStints, springOf, seasonLabel, seasonSpan, makePalette, makeFilters, copyLink, trackBar, miles, median };
})();
