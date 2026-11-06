/* Maç Analiz — telefon arayüzü. Veri: ../data.json (GitHub Actions her gün üretir). */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const view = $("#view");
  const LS = { get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
               set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const pct = (x, d = 0) => (x == null ? "–" : (100 * x).toFixed(d) + "%");
  const odd = (x) => Number(x).toFixed(2);

  const MT = [ // detay paneli pazar sekmeleri
    ["MS", "Maç Sonucu", (p) => p === "MS"], ["CS", "Çifte Şans", (p) => p === "CS"],
    ["AU", "Alt/Üst", (p) => /^AU_/.test(p)], ["KG", "KG", (p) => p === "KG"],
    ["TG", "Toplam Gol", (p) => p === "TOPLAM_GOL"], ["IY", "İlk Yarı", (p) => /^IY(_AU|_KG)?/.test(p) && p !== "IYMS"],
    ["IYMS", "İY/MS", (p) => p === "IYMS"], ["HMS", "Handikap", (p) => /^HMS_/.test(p)], ["DIG", "Diğer", null],
  ];
  const NAME = { "1": "1", "0": "X", "2": "2", "1 ve 0": "1-X", "1 ve 2": "1-2", "0 ve 2": "X-2" };
  const nice = (s) => NAME[s] || s.replace(/\b0\b/g, "X");

  let DATA = null, live = true, tab = "secim", lig = "Tümü", q = "", lastLoad = 0;
  let kupon = LS.get("kupon", {}); // {kod: {p,s,o,m,pk,mbs,mac,pa,tarih}}
  // Favoriler: {kod: {ev, dep, lig, saat, baslama, tarih}} — cihazda saklanır, 2 gün sonra silinir
  let FAV = LS.get("favs", {});
  function saveFav() {
    const now = Date.now();
    for (const [k, f] of Object.entries(FAV)) if (now - new Date(f.baslama).getTime() > 48 * 3600e3) delete FAV[k];
    LS.set("favs", FAV);
    const n = Object.keys(FAV).length, b = $("#fcount"); if (b) { b.textContent = n; b.classList.toggle("hidden", !n); }
  }
  const isFav = (kod) => !!FAV[kod];
  function toggleFav(kod) {
    const m = byKod(kod);
    if (FAV[kod]) { delete FAV[kod]; toast("Favorilerden çıkarıldı"); }
    else if (m) { FAV[kod] = { ev: m.ev, dep: m.dep, lig: m.lig, saat: m.saat, baslama: m.baslama, tarih: DATA.tarih }; toast("★ Favorilere eklendi"); }
    saveFav();
  }
  const favBtn = (m) => `<button class="fav ${isFav(m.kod) ? "on" : ""}" data-fav="${esc(m.kod)}" aria-label="Favori">${isFav(m.kod) ? "★" : "☆"}</button>`;
  let LIVE = {}, liveAt = 0, liveTimer = null, liveBusy = false;   // canlı skorlar: {kod: {...}}
  const LIVEMETA = {}, LIVECOMP = {};   // canlı sonuç servisinden takım/lig adları
  const LIVE_FAST = 1000;      // canlı maç varken: her yanıttan 1 sn sonra yeni istek (~12 KB, sıkıştırılmış)
  const LIVE_SOON = 15000;     // maç başlamak üzereyken
  const LIVE_IDLE = 5 * 60e3;  // canlı maç yokken

  // ---------- canlı skor (telefondan doğrudan; iddaa canlı sonuç servisi) ----------
  const LIVE_URL = (d) => `https://statisticsv2.iddaa.com/live-results?sportId=1&date=${d}`;
  // Türkiye saatine göre bugünün tarihi (YYYY-MM-DD)
  const todayTR = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Istanbul" });
  async function fetchLive() {
    if (!DATA || !live || liveBusy) return;
    liveBusy = true;
    try {
      // Gece yarısından sonra süren maçlar yeni günün listesine geçer: iki günü de çek, birleştir
      const dates = [...new Set([DATA.tarih, todayTR(), ...DATA.maclar.map((m) => (m.baslama || "").slice(0, 10)).filter(Boolean)])].slice(0, 3);
      const res = await Promise.all(dates.map((d) => fetch(LIVE_URL(d), { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null)).catch(() => null)));
      if (!res.some(Boolean)) throw new Error("canlı veri yok");
      const out = {};
      for (const j of res) {
        const data = (j && j.data) || {}, sc = data.sc || {};
        for (const c of Object.values(data.competitions || {})) LIVECOMP[c.i] = c.n;
        for (const e of data.events || []) {
          const k = String(e.eventId), x = sc[k];
          LIVEMETA[k] = { ev: e.homeTeam, dep: e.awayTeam, ci: e.ci, d: e.eventDate };
          if (!x || !e.phase) continue;           // phase 0 = başlamadı
          const prev = out[k];
          if (prev && prev.phase === 1 && e.phase !== 1) continue;   // canlı kayıt öncelikli
          out[k] = { phase: e.phase, s: x.s, min: x.min, h: x.ht?.r ?? 0, a: x.at?.r ?? 0,
                     hh: x.ht?.ht ?? null, ha: x.at?.ht ?? null, hco: x.ht?.co, aco: x.at?.co,
                     hrc: x.ht?.rc || 0, arc: x.at?.rc || 0, hyc: x.ht?.yc, ayc: x.at?.yc };
        }
      }
      const finBefore = new Set(DATA.maclar.filter((m) => LIVE[m.kod]?.phase === 2).map((m) => m.kod));
      LIVE = out; liveAt = Date.now();
      const finNow = DATA.maclar.filter((m) => LIVE[m.kod]?.phase === 2).map((m) => m.kod);
      if (finNow.some((k) => !finBefore.has(k)) && ["secim", "mac", "fav"].includes(tab) && document.activeElement?.id !== "q") render(true);
      paintLive();
      if (curKod && dTab === "ist" && dSub.ist === "canli") { const el = $("#dtab"); if (el) el.innerHTML = tabIst(byKod(curKod)); }
      if (!oddsTimer && DATA.maclar.some((m) => LIVE[m.kod]?.phase === 1)) fetchOdds();
      if (curKod && !evTimer && !evBusy && LIVE[curKod]?.phase === 1) fetchEvent(curKod);
    } catch (e) { /* ağ hatası: bir sonraki turda tekrar dener */ }
    liveBusy = false;
    scheduleLive();
  }
  // Sık yenileme yalnızca gerektiğinde: bizim/favori/kupon maçları canlıyken, Canlı sekmesinde ya da açık detay canlıyken
  function wantFast() {
    const L = (k) => LIVE[k]?.phase === 1;
    return DATA.maclar.some((m) => L(m.kod)) || Object.keys(FAV).some(L) || Object.keys(kupon).some(L)
      || (curKod && L(curKod)) || (tab === "canli" && Object.values(LIVE).some((x) => x.phase === 1));
  }
  function scheduleLive() {
    clearTimeout(liveTimer);
    if (!DATA || !live) return;
    const now = Date.now();
    const anyLive = wantFast();
    const soon = DATA.maclar.some((m) => { const t = new Date(m.baslama).getTime(); return t - now < 15 * 60e3 && now - t < 3 * 3600e3; });
    liveTimer = setTimeout(() => { if (document.visibilityState === "visible") fetchLive(); else scheduleLive(); },
                           anyLive ? LIVE_FAST : soon ? LIVE_SOON : LIVE_IDLE);
  }
  // ---------- canlı oranlar (iddaa canlı bülteni; yalnızca değişenler) ----------
  const ODDS_URL = (v) => `https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=${v}`;
  const ODDS_EVERY = 2000;
  const FT_ST = new Set([14]), IY_ST = new Set([63, 64, 806]);   // Alt/Üst {x} ve 1. Yarı Alt/Üst {x}
  let LODDS = {}, oddsVer = 0, oddsTimer = null, oddsBusy = false, oddsAt = 0;
  async function fetchOdds() {
    if (!DATA || !live || oddsBusy) return;
    oddsBusy = true;
    try {
      const r = await fetch(ODDS_URL(oddsVer), { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const d = (await r.json()).data || {};
      if (!d.isdiff) LODDS = {};
      for (const e of d.events || []) {          // değişen maç, bütün pazarlarıyla gelir
        const k = String(e.i);
        if (e.sid === 1) LODDS[k] = { m: e.m || [], at: Date.now() };
      }
      oddsVer = d.version || oddsVer; oddsAt = Date.now();
      paintLive();
    } catch (e) { oddsVer = 0; /* hata: bir sonraki turda baştan çek */ }
    oddsBusy = false;
    scheduleOdds();
  }
  function scheduleOdds() {
    clearTimeout(oddsTimer);
    if (!DATA || !live) return;
    const anyLive = wantFast();
    oddsTimer = setTimeout(() => { if (document.visibilityState === "visible") fetchOdds(); else scheduleOdds(); },
                           anyLive ? ODDS_EVERY : 60e3);
  }
  // Detay paneli açıkken: o maçın BÜTÜN canlı çizgileri (sportsbook/event/<kod>, ~3 KB), 2 sn'de bir
  const EVENT_URL = (k) => `https://sportsbookv2.iddaa.com/sportsbook/event/${k}`;
  let EVODDS = {}, evTimer = null, evBusy = false;
  async function fetchEvent(kod) {
    clearTimeout(evTimer); evTimer = null;
    if (!DATA || evBusy || curKod !== kod) return;
    evBusy = true;
    try {
      const r = await fetch(EVENT_URL(kod), { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      let e = (await r.json()).data; if (Array.isArray(e)) e = e[0];
      if (e) { EVODDS[kod] = { m: e.m || [], at: Date.now() }; oddsAt = Date.now(); paintLive(); paintMarkets(); }
    } catch (e) { /* bir sonraki turda tekrar dener */ }
    evBusy = false;
    if (curKod === kod) {
      const wait = LIVE[kod]?.phase === 1 ? 2000 : 30000;
      evTimer = setTimeout(() => { if (document.visibilityState === "visible") fetchEvent(kod); else evTimer = setTimeout(() => fetchEvent(kod), 3000); }, wait);
    }
  }

  // ---------- tüm iddaa bülteni (telefondan doğrudan) ----------
  const SB = "https://sportsbookv2.iddaa.com/sportsbook";
  let BUL = null, bulVer = 0, bulBusy = false, bulTimer = null, bulErr = false;
  let COMPS = LS.get("comps", null), MCFG = LS.get("mcfg", null);
  let bday = null, blig = "", bq = "", bshow = 60, mcatSel = "Tümü";
  async function loadMeta() {        // lig ve pazar adları: günde bir, cihazda saklanır
    const d = todayTR();
    if (!COMPS || COMPS._d !== d) { try { const j = await (await fetch(`${SB}/competitions`)).json();
      COMPS = { _d: d, m: Object.fromEntries((j.data || []).map((c) => [c.i, [c.n, c.p ?? 9999]])) }; LS.set("comps", COMPS); } catch (e) {} }
    if (!MCFG || MCFG._d !== d) { try { const j = await (await fetch(`${SB}/get_market_config`)).json();
      const m = {}; for (const [k, v] of Object.entries((j.data && j.data.m) || {})) m[k] = v.n;
      MCFG = { _d: d, m }; LS.set("mcfg", MCFG); } catch (e) {} }
  }
  async function loadBulletin() {
    if (bulBusy) return; bulBusy = true;
    try {
      await loadMeta();
      const r = await fetch(`${SB}/events?st=1&type=0&version=${BUL ? bulVer : 0}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const d = (await r.json()).data || {};
      const first = !BUL;
      if (!BUL || !d.isdiff) BUL = new Map();
      for (const e of d.events || []) if (e.sid === 1) BUL.set(String(e.i), e);
      bulVer = d.version || bulVer; bulErr = false;
      if (tab === "bulten" && (first || document.activeElement?.id !== "bq")) render(!first);
    } catch (e) { bulErr = true; if (tab === "bulten" && !BUL) render(); }
    bulBusy = false;
    clearTimeout(bulTimer);
    bulTimer = setTimeout(() => { if (document.visibilityState === "visible" && (tab === "bulten" || tab === "fav")) loadBulletin(); }, 60000);
  }
  const ligName = (ci) => (COMPS?.m?.[ci] || [])[0] || LIVECOMP[ci] || "";
  const ligPrio = (ci) => (COMPS?.m?.[ci] || [])[1] ?? 9999;
  const isoTR = (sec) => new Date(sec * 1000 + 3 * 3600e3).toISOString().slice(0, 19) + "+03:00";
  function extMatch(e) {
    const iso = isoTR(e.d);
    return { kod: String(e.i), ev: (e.hn || "").trim(), dep: (e.an || "").trim(), lig: ligName(e.ci), ci: e.ci,
             baslama: iso, saat: iso.slice(11, 16), mbs: e.mbc ?? 1, ext: true, secenekler: [], raw: e };
  }
  const hcpLbl = (sov) => { const v = parseFloat(sov); if (isNaN(v)) return sov; const a = Math.abs(v); return v > 0 ? `${a}:0` : `0:${a}`; };
  function marketName(mk) {
    let n = MCFG?.m?.[`${mk.t}_${mk.st}`] || "Bahis";
    const sov = mk.sov == null ? "" : String(mk.sov), parts = sov.split("|");
    n = n.replace("{h}", hcpLbl(sov)).replace("{0}", sov.replace(".", ",")).replace("{1}", parts[1] || "").replace("{2}", (parts[2] || parts[0] || "").replace(".", ","));
    return n.replace(/\s+/g, " ").trim();
  }
  function niceOut(n) {
    if (/^[012]$/.test(n)) return { 1: "1", 0: "X", 2: "2" }[n];
    if (/^[012] ve [012]$/.test(n) || /^[012]\/[012]$/.test(n)) return n.replace(/0/g, "X").replace(" ve ", "-");
    return n;
  }
  function mcat(name) {
    if (/Korner/i.test(name)) return "Korner";
    if (/Kart/i.test(name)) return "Kart";
    if (/Handikap/i.test(name)) return "Handikap";
    if (/Yarı/i.test(name)) return "Yarı";
    if (/Alt|Üst|Gol|Tek \/ Çift/i.test(name)) return "Gol";
    if (/Maç Sonucu|Çifte Şans|Kazanır/i.test(name)) return "Maç Sonucu";
    return "Diğer";
  }
  const mktSource = (kod) => (EVODDS[kod] && EVODDS[kod].m) || (LODDS[kod] && LODDS[kod].m) || (BUL && BUL.get(kod) && BUL.get(kod).m) || [];
  const mkKey = (mk) => `M_${mk.t}_${mk.st}_${mk.sov ?? ""}`;
  function mOddBtn(m, mk, o, label) {
    const p = mkKey(mk), on = kupon[m.kod] && kupon[m.kod].p === p && kupon[m.kod].s === o.n;
    const closed = !(o.odd > 1) || (mk.s != null && mk.s !== 1);
    if (closed) return `<div class="odd nood"><span class="n">${esc(label || niceOut(o.n))}</span><span class="o">–</span><span class="p">kapalı</span></div>`;
    return `<button class="odd ${on ? "on" : ""} ${mk.t === 4 ? "live" : ""}" data-mk="${esc(m.kod)}|${mk.t}|${mk.st}|${esc(mk.sov ?? "")}|${esc(o.n)}">
      <span class="n">${esc(label || niceOut(o.n))}</span><span class="o">${odd(o.odd)}</span></button>`;
  }
  function genericToggle(kod, t, st, sov, name) {
    const m = byKod(kod); if (!m) return;
    const mk = mktSource(kod).find((x) => x.t == t && x.st == st && String(x.sov ?? "") === sov);
    const o = mk && mk.o.find((x) => x.n === name);
    if (!mk || !o || !(o.odd > 1)) { toast("Bu oran şu an kapalı"); return; }
    const p = mkKey(mk), cur = kupon[kod];
    if (cur && cur.p === p && cur.s === name) { delete kupon[kod]; toast("Kupondan çıkarıldı"); }
    else {
      const inv = mk.o.filter((x) => x.odd > 1).map((x) => 1 / x.odd), sum = inv.reduce((a, b) => a + b, 0) || 1;
      const pk = (1 / o.odd) / sum;
      kupon[kod] = { p, s: name, o: o.odd, m: pk, pk, mbs: mk.mbc || m.mbs || 1, mac: `${m.ev} – ${m.dep}`, pa: marketName(mk),
                     saat: m.saat, baslama: m.baslama, mk: { t: mk.t, st: mk.st, sov: mk.sov ?? null } };
      toast(cur ? "Aynı maçtan tek seçim: değiştirildi" : `Kupona eklendi · ${Object.keys(kupon).length} maç`);
    }
    saveKupon(); render(true);
  }
  // Bütün pazarlar (maç detayı)
  function renderMarkets(m) {
    const full = EVODDS[m.kod] && EVODDS[m.kod].m;
    const list = (full || mktSource(m.kod)).filter((mk) => mk.o && mk.o.length);
    if (!list.length) return `<div class="lodds-note">${full ? "Bu maç için açık bahis yok." : "Bahisler yükleniyor…"}</div>`;
    const cats = ["Tümü", ...["Maç Sonucu", "Gol", "Yarı", "Handikap", "Korner", "Kart", "Diğer"].filter((c) => list.some((mk) => mcat(marketName(mk)) === c))];
    if (!cats.includes(mcatSel)) mcatSel = "Tümü";
    const shown = list.filter((mk) => mcatSel === "Tümü" || mcat(marketName(mk)) === mcatSel);
    return `<div class="dsubs">${cats.map((c) => `<button class="dsub ${c === mcatSel ? "on" : ""}" data-mcat="${esc(c)}">${c === "Yarı" ? "İlk/2. Yarı" : c}</button>`).join("")}</div>
      ${shown.map((mk) => `<div class="mkt"><div class="mkt-h">${mk.t === 4 ? '<span class="lbadge">CANLI</span> ' : ""}${esc(marketName(mk))}${mk.mbc ? ` <span class="mkt-s">MBS ${esc(mk.mbc)}</span>` : ""}</div>
        <div class="mgrid c${Math.min(mk.o.length, 3)}">${mk.o.map((o) => mOddBtn(m, mk, o)).join("")}</div></div>`).join("")}
      ${full ? "" : `<div class="lodds-note">Bütün bahisler yükleniyor…</div>`}`;
  }
  function paintMarkets() {
    const el = document.querySelector("[data-allmk]");
    if (el && curKod) el.innerHTML = renderMarkets(byKod(curKod));
  }
  function msGrid(m, live) {      // satır için MS 1-X-2 (canlıysa canlı oran)
    const src = live ? (LODDS[m.kod] && LODDS[m.kod].m) || [] : (m.raw ? m.raw.m : (BUL && BUL.get(m.kod) ? BUL.get(m.kod).m : [])) || [];
    const mk = src.find((x) => (live ? x.t === 4 && x.st === 4 : x.t === 1 && x.st === 1));
    if (!mk) return `<div class="lodds-note">${live ? "canlı MS oranı kapalı/askıda" : "MS oranı yok"}</div>`;
    return `<div class="mgrid c3">${["1", "0", "2"].map((n) => { const o = mk.o.find((x) => x.n === n); return o ? mOddBtn(m, mk, o, (live ? "CANLI " : "MS ") + niceOut(n)) : ""; }).join("")}</div>`;
  }

  // ---- iddaa ↔ ESPN maç eşleştirme (app.js'e eklenecek blok) ----
  const EXO = { kopenhag: "kobenhavn", marsilya: "marseille", lizbon: "lisboa", prag: "praha", sofya: "sofia", munih: "munchen",
    belgrad: "beograd", atina: "athens", zurih: "zurich", viyana: "wien", bruksel: "bruxelles", varsova: "warszawa",
    kiev: "kyiv", moskova: "moskva", roma: "roma", milano: "milan", napoli: "napoli", torino: "torino", lyon: "lyon",
    "kizil yildiz": "red star", "kizilyildiz": "red star", "b leverkusen": "leverkusen", "bayer leverkusen": "leverkusen",
    "un craiova": "universitatea craiova", "k almaty": "kairat", "ofi crete": "ofi", "kuopion": "kups", "inter club de escaldes": "inter escaldes" };
  const STOP = new Set(["fc", "cf", "sc", "ac", "afc", "fk", "sk", "cd", "club", "de", "the", "sv", "if", "bk", "ss", "us", "as", "nk", "kf", "ca", "cs", "ud", "rc", "sd", "real", "1907", "1999", "1903", "1899"]);
  function normTeam(s) {
    let t = String(s || "").toLocaleLowerCase("tr").replace(/ı/g, "i").normalize("NFKD").replace(/[̀-ͯ]/g, "")
      .replace(/ø/g, "o").replace(/æ/g, "ae").replace(/ß/g, "ss").replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
    for (const [k, v] of Object.entries(EXO)) if (t === k || t.startsWith(k + " ") || t.endsWith(" " + k) || t.includes(" " + k + " ")) t = t.replace(k, v);
    return t.split(" ").filter((w) => w && !STOP.has(w));
  }
  function teamSim(a, b) {
    const A = normTeam(a), B = normTeam(b);
    if (!A.length || !B.length) return 0;
    let hit = 0;
    for (const x of A) if (B.some((y) => x === y || (x.length >= 4 && y.length >= 4 && (x.startsWith(y.slice(0, 4)) && y.startsWith(x.slice(0, 4)))))) hit++;
    const tok = hit / Math.min(A.length, B.length);
    const bg = (s) => { const r = []; for (let i = 0; i < s.length - 1; i++) r.push(s.slice(i, i + 2)); return r; };
    const a2 = bg(A.join("")), b2 = bg(B.join("")); let inter = 0; const pool = [...b2];
    for (const g of a2) { const i = pool.indexOf(g); if (i >= 0) { inter++; pool.splice(i, 1); } }
    const dice = (2 * inter) / ((a2.length + b2.length) || 1);
    return Math.max(tok, dice);
  }
  // m: {ev, dep, baslama(ISO TR)}, x: canlı skor (opsiyonel), evs: ESPN olayları
  function espnMatch(m, evs, x) {
    const t0 = Date.parse(m.baslama);
    let best = null;
    for (const e of evs) {
      if (Math.abs(Date.parse(e.date) - t0) > 30 * 60e3) continue;
      const c = e.competitions && e.competitions[0]; if (!c) continue;
      const H = c.competitors.find((q) => q.homeAway === "home"), A = c.competitors.find((q) => q.homeAway === "away");
      const nm = (q) => [q.team.displayName, q.team.shortDisplayName, q.team.name, q.team.location].filter(Boolean);
      const sh = Math.max(...nm(H).map((n) => teamSim(m.ev, n))), sa = Math.max(...nm(A).map((n) => teamSim(m.dep, n)));
      let sc = sh + sa;
      if (x && x.phase && +H.score === x.h && +A.score === x.a) sc += 0.3;
      const ok = (sh >= 0.5 && sa >= 0.3) || (sa >= 0.5 && sh >= 0.3) || sh >= 0.85 || sa >= 0.85;
      if (ok && (!best || sc > best.sc)) best = { e, sc, sh, sa };
    }
    return best;
  }
  // ---------- maç akışı (ESPN herkese açık skor servisi) ----------
  const ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard";
  const ESPNDAY = {}, ESPNEV = {}; let ESPNID = LS.get("espnid", {}), espnTimer = null, espnBusy = false;
  const ymd = (iso) => iso.slice(0, 10).replace(/-/g, "");
  async function espnDay(d) {
    const c = ESPNDAY[d]; if (c && Date.now() - c.at < 120e3) return c.evs;
    try { const j = await (await fetch(`${ESPN}?dates=${d}&limit=1000`, { cache: "no-store" })).json();
      ESPNDAY[d] = { at: Date.now(), evs: j.events || [] }; return ESPNDAY[d].evs; } catch (e) { return c ? c.evs : []; }
  }
  async function findEspn(m) {
    if (ESPNID[m.kod] !== undefined) return ESPNID[m.kod];
    const d0 = m.baslama.slice(0, 10), prev = new Date(Date.parse(d0 + "T12:00:00Z") - 864e5).toISOString().slice(0, 10);
    let best = null;
    for (const d of [ymd(d0), ymd(prev)]) { const b = espnMatch(m, await espnDay(d), LIVE[m.kod]); if (b && (!best || b.sc > best.sc)) best = b; }
    ESPNID[m.kod] = best ? best.e.id : null;
    if (best) { LS.set("espnid", ESPNID); ESPNEV[m.kod] = { e: best.e, at: Date.now() }; }
    else setTimeout(() => { if (ESPNID[m.kod] === null) delete ESPNID[m.kod]; }, 600e3);   // 10 dk sonra yeniden dene
    return ESPNID[m.kod];
  }
  async function fetchEspn(kod) {
    clearTimeout(espnTimer); espnTimer = null;
    if (curKod !== kod || espnBusy) return;
    const m = byKod(kod); if (!m) return;
    espnBusy = true;
    try {
      const id = await findEspn(m);
      if (id) { const r = await fetch(`${ESPN}/${id}`, { cache: "no-store" }); if (r.ok) ESPNEV[kod] = { e: await r.json(), at: Date.now() }; }
    } catch (e) {}
    espnBusy = false;
    paintAkis();
    if (curKod !== kod) return;
    const st = ESPNEV[kod] && ESPNEV[kod].e && ESPNEV[kod].e.status ? ESPNEV[kod].e.status.type.state : null;   // pre | in | post
    const wait = st === "in" || LIVE[kod]?.phase === 1 ? 1000 : st === "post" ? 0 : 30000;
    if (wait) espnTimer = setTimeout(() => { if (document.visibilityState === "visible") fetchEspn(kod); else espnTimer = setTimeout(() => fetchEspn(kod), 2000); }, wait);
  }
  function evInfo(d) {
    const t = (d.type && d.type.text) || "";
    if (d.shootout) return { ic: "🎯", tx: d.scoringPlay ? "Seri penaltı golü" : "Seri penaltı kaçtı" };
    if (d.ownGoal) return { ic: "⚽", tx: "Kendi kalesine gol", goal: true, og: true, tag: "KK" };
    if (d.penaltyKick && d.scoringPlay) return { ic: "⚽", tx: "Penaltı golü", goal: true, tag: "P" };
    if (/Penalty - (Missed|Saved)/i.test(t)) return { ic: "❌", tx: /Saved/i.test(t) ? "Penaltı kurtarıldı" : "Penaltı kaçtı" };
    if (d.scoringPlay) return { ic: "⚽", tx: /Header/i.test(t) ? "Gol (kafa)" : /Free-kick/i.test(t) ? "Gol (serbest vuruş)" : "Gol", goal: true };
    if (d.redCard) return { ic: "🟥", tx: /Yellow/i.test(t) ? "İkinci sarıdan kırmızı" : "Kırmızı kart", red: true };
    if (d.yellowCard) return { ic: "🟨", tx: "Sarı kart" };
    if (/Substitution/i.test(t)) return { ic: "🔁", tx: "Oyuncu değişikliği" };
    return { ic: "•", tx: t };
  }
  function espnParts(kod) {
    const ev = ESPNEV[kod] && ESPNEV[kod].e; if (!ev || !ev.competitions) return null;
    const c = ev.competitions[0], H = c.competitors.find((q) => q.homeAway === "home");
    const dets = [...(c.details || [])].sort((a, b) => ((a.clock && a.clock.value) || 0) - ((b.clock && b.clock.value) || 0));
    return { ev, c, homeId: H && H.team ? H.team.id : null, dets };
  }
  // Skor tablosunun altında golcüler ve kırmızı kartlar
  function scorersUnder(kod) {
    const P = espnParts(kod); if (!P) return "";
    const line = (d) => { const i = evInfo(d); if (!i.goal && !i.red) return "";
      const who = (d.athletesInvolved || [])[0]; const nm = who ? (who.shortName || who.displayName) : "";
      return `<div>${i.goal ? "⚽" : "🟥"} ${esc((d.clock && d.clock.displayValue) || "")} ${esc(nm)}${i.tag ? ` (${i.tag})` : ""}</div>`; };
    const tid = (d) => d.team && d.team.id;
    const home = P.dets.filter((d) => tid(d) === P.homeId).map(line).join(""), away = P.dets.filter((d) => tid(d) !== P.homeId).map(line).join("");
    if (!home && !away) return "";
    return `<div class="sb-goals"><div>${home}</div><div>${away}</div></div>`;
  }
  const ST_TR = { "Full Time": "Maç sonu", "Halftime": "Devre arası", "Scheduled": "Başlamadı", "First Half": "1. yarı", "Second Half": "2. yarı",
    "Final": "Maç sonu", "Postponed": "Ertelendi", "Canceled": "İptal", "Abandoned": "Yarıda kaldı", "Extra Time": "Uzatma", "Penalties": "Penaltılar" };
  const stTr = (t) => ST_TR[t] || t || "";
  function akisView(m) {
    if (ESPNID[m.kod] === undefined || (ESPNID[m.kod] && !ESPNEV[m.kod])) return `<div class="lodds-note">Maç akışı yükleniyor…</div>`;
    if (!ESPNID[m.kod]) return `<div class="mkt"><div class="lodds-note">Bu maç için ücretsiz kaynakta (ESPN) maç akışı bulunamadı. ESPN büyük ligleri ve Avrupa kupalarını kapsıyor; küçük liglerde gol/kart dakikaları gösterilemiyor.</div></div>`;
    const P = espnParts(m.kod); if (!P) return "";
    const st = (P.ev.status && P.ev.status.type) || {};
    if (!P.dets.length) return `<div class="mkt"><div class="mkt-h">Maç akışı <span class="mkt-s">${esc(stTr(st.description))} · kaynak ESPN</span></div>
      <div class="lodds-note">${st.state === "pre" ? "Maç başlayınca gol, kart ve penaltı olayları burada saniyesinde görünür." : "Henüz gol/kart olayı yok."}</div></div>`;
    let hs = 0, as = 0, h = "", htDone = false;
    const dv = (d) => (d.clock && d.clock.displayValue) || "";
    const isFirst = (d) => ((d.clock && d.clock.value) || 0) <= 2700 || /^45'\+/.test(dv(d));
    for (const d of P.dets) {
      if (!htDone && !isFirst(d)) { htDone = true; h += `<div class="tl-div">İlk yarı sonucu ${hs} - ${as}</div>`; }
      const i = evInfo(d), home = d.team && d.team.id === P.homeId;
      if (i.goal) { if (home) hs++; else as++; }   // ESPN kendi kalesine golü yararlanan takıma yazar
      const ath = d.athletesInvolved || [];
      const who = ath[0] ? ath[0].displayName : "";
      const sub = i.goal && ath[1] ? `${i.tx} · asist: ${ath[1].displayName}` : i.tx;
      const body = `<div class="tl-b ${home ? "l" : "r"}"><div class="tl-n">${i.ic} ${esc(who || i.tx)}${i.goal ? ` <span class="tl-sc">${hs}-${as}</span>` : ""}</div><div class="tl-s">${who ? esc(sub) : ""}</div></div>`;
      h += `<div class="tl-row">${home ? body : "<div></div>"}<div class="tl-m">${esc(dv(d))}</div>${home ? "<div></div>" : body}</div>`;
    }
    const sc = (ha) => (P.c.competitors.find((q) => q.homeAway === ha) || {}).score;
    if (st.state === "post") h += `<div class="tl-div">Maç sonucu ${sc("home")} - ${sc("away")}</div>`;
    return `<div class="mkt"><div class="mkt-h">Maç akışı <span class="mkt-s">${esc(st.state === "in" ? (P.ev.status.displayClock || "canlı") : stTr(st.description))} · kaynak ESPN</span></div>
      <div class="tl-teams"><b>${esc(m.ev)}</b><b>${esc(m.dep)}</b></div>${h}</div>`;
  }
  function paintAkis() {
    document.querySelectorAll("[data-akis]").forEach((el) => { const m = byKod(el.dataset.akis); if (m) el.innerHTML = akisView(m); });
    document.querySelectorAll("[data-goals]").forEach((el) => (el.innerHTML = scorersUnder(el.dataset.goals)));
  }

  // ---------- kupon oran kontrolü ----------
  let KODDS = {}, kTimer = null, kBusy = false;      // {kod: {m, at}}
  async function fetchKuponOdds() {
    clearTimeout(kTimer); kTimer = null;
    if (!DATA || kBusy || tab !== "kupon" || !Object.keys(kupon).length) return;
    kBusy = true;
    for (const k of Object.keys(kupon)) {
      try {
        const r = await fetch(EVENT_URL(k), { cache: "no-store" });
        if (!r.ok) continue;
        let e = (await r.json()).data; if (Array.isArray(e)) e = e[0];
        KODDS[k] = { m: (e && e.m) || [], at: Date.now() };
      } catch (e) {}
    }
    kBusy = false;
    paintKupon();
    if (tab === "kupon" && document.visibilityState === "visible") kTimer = setTimeout(fetchKuponOdds, 10000);
  }
  // Kupondaki seçimin şu anki oranı: {o} | {kapali: neden} | null (henüz bilinmiyor)
  function currentOdd(k, sel) {
    const K = KODDS[k]; if (!K) return null;
    if (sel.mk) {     // iddaa'nın herhangi bir pazarı
      if (LIVE[k]?.phase === 2) return { kapali: "maç bitti" };
      if (sel.mk.t !== 4 && LIVE[k]?.phase === 1) return { kapali: "maç başladı; maç öncesi oran artık oynanamaz" };
      const mk = K.m.find((x) => x.t === sel.mk.t && x.st === sel.mk.st && String(x.sov ?? "") === String(sel.mk.sov ?? ""));
      const o = mk && mk.o.find((x) => x.n === sel.s);
      if (!mk || !o || !(o.odd > 1) || (mk.s != null && mk.s !== 1)) return { kapali: "bu oran şu an kapalı/askıda" };
      return { o: o.odd };
    }
    const mt = /^(LIVE_)?(IY_)?AU_(\d+\.5)$/.exec(sel.p); if (!mt) return null;
    const fh = !!mt[2], line = mt[3], isLive = LIVE[k]?.phase === 1 || !!mt[1];
    if (LIVE[k]?.phase === 2) return { kapali: "maç bitti" };
    if (!mt[1] && LIVE[k]?.phase === 1) return { kapali: "maç başladı; maç öncesi oran artık oynanamaz" };
    const ok = (mk) => isLive ? mk.t === 4 && (fh ? IY_ST.has(mk.st) : FT_ST.has(mk.st))
                              : mk.t === 2 && mk.st === (fh ? 60 : 101);
    const mk = K.m.find((x) => ok(x) && String(x.sov) === line);
    const ov = mk && mk.o.find((o) => o.n === "Üst");
    if (!mk || !ov || ov.odd <= 1 || mk.s !== 1) return { kapali: isLive ? "bu canlı oran şu an kapalı/askıda" : "bu oran şu an kapalı" };
    return { o: ov.odd };
  }
  function kuponCheck(k) {
    const sel = kupon[k]; if (!sel) return "";
    const c = currentOdd(k, sel);
    if (!c) return `<span class="kc wait">oran kontrol ediliyor…</span>`;
    if (c.kapali) return `<span class="kc bad">⚠ ${esc(c.kapali)}</span>`;
    if (Math.abs(c.o - sel.o) < 0.005) return `<span class="kc ok">✓ oran güncel</span>`;
    const up = c.o > sel.o;
    return `<span class="kc ${up ? "up" : "down"}">${up ? "↑" : "↓"} oran değişti: ${odd(sel.o)} → <b>${odd(c.o)}</b></span>
      <button class="kc-upd" data-kupd="${esc(k)}">güncelle</button>`;
  }
  function paintKupon() {
    document.querySelectorAll("[data-kchk]").forEach((el) => (el.innerHTML = kuponCheck(el.dataset.kchk)));
    const changed = Object.keys(kupon).filter((k) => { const c = currentOdd(k, kupon[k]); return c && (c.kapali || Math.abs(c.o - kupon[k].o) >= 0.005); });
    const pv = $("#kprev"); if (pv && Object.keys(kupon).length) pv.innerHTML = esc(kuponText()).replace(/\n/g, "<br>");
    const el = $("#kwarn");
    if (el) el.innerHTML = changed.length ? `⚠ ${changed.length} seçimde oran değişti veya seçenek kapandı. Bilyoner'de oynamadan önce kontrol et.` : "";
  }
  function kuponText() {
    const ks = Object.entries(kupon);
    const lines = ks.map(([k, s], i) => {
      const c = currentOdd(k, s), o = c && c.o ? c.o : s.o;
      const lbl = s.mk ? `${s.pa}: ${niceOut(s.s)}` : (s.pa || "").replace(/^(Canlı )?(1\. Yarı )?Alt\/Üst (\d)\.5$/, (_, cl, iy, n) => `${cl ? "CANLI " : ""}${iy ? "İY " : ""}${n},5 Üst`);
      return `${i + 1}) ${s.mac} · ${lbl || s.s} · ${odd(o)}${c && c.kapali ? " (⚠ " + c.kapali + ")" : ""}`;
    });
    const to = ks.reduce((a, [k, s]) => { const c = currentOdd(k, s); return a * (c && c.o ? c.o : s.o); }, 1);
    const maxMbs = Math.max(...ks.map(([, s]) => Number(s.mbs) || 1));
    return `Maç Analiz kuponu (${DATA.tarih})\n${lines.join("\n")}\nToplam oran: ${odd(to)} · ${ks.length} maç · en yüksek MBS ${maxMbs}`;
  }
  async function copyText(t) {
    try { await navigator.clipboard.writeText(t); return true; } catch (e) {}
    try {   // WebView/eski tarayıcı yedeği
      const ta = document.createElement("textarea"); ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select(); const ok = document.execCommand("copy"); ta.remove(); return ok;
    } catch (e) { return false; }
  }

  // Poisson: P(N >= k), N ~ Poisson(mu)
  function pAtLeast(k, mu) {
    if (k <= 0) return 1;
    let term = Math.exp(-mu), cum = term;
    for (let i = 1; i < k; i++) { term *= mu / i; cum += term; }
    return Math.max(0, 1 - cum);
  }
  // Maç öncesi λ'nın kalan süreye düşen payı + mevcut gollerle canlı Üst olasılığı
  function liveProb(m, firstHalf, line) {
    const x = LIVE[m.kod]; if (!x || !m.lambda) return null;
    const lt = (m.lambda.ev || 0) + (m.lambda.dep || 0), iy = m.iy_pay || 0.44;
    const t = Math.min(x.min ?? 0, 95), ht = x.s === 4;
    let goals, rem;
    if (firstHalf) {
      if (ht || t > 47) return null;                       // ilk yarı bitti
      goals = (x.hh ?? 0) + (x.ha ?? 0);
      rem = lt * iy * Math.max(0, 47 - t) / 45;            // ~2 dk uzatma payı
    } else {
      goals = x.h + x.a;
      rem = ht ? lt * (1 - iy) * 47 / 45
          : t <= 45 ? lt * (iy * Math.max(0, 47 - t) / 45 + (1 - iy) * 47 / 45)
          : lt * (1 - iy) * Math.max(0, 94 - t) / 45;
    }
    return pAtLeast(Math.floor(line) + 1 - goals, rem);
  }
  // Bir maçın canlı Üst seçenekleri: [{p, s, pa, et, o, pk, m}]
  function liveOvers(m) {
    const E = EVODDS[m.kod];
    const L = E && Date.now() - E.at < 15000 ? E : LODDS[m.kod]; if (!L) return null;
    const out = [];
    for (const mk of L.m) {
      if (mk.t !== 4 || !(FT_ST.has(mk.st) || IY_ST.has(mk.st)) || mk.sov == null) continue;
      const fh = IY_ST.has(mk.st), line = parseFloat(mk.sov);
      const ov = mk.o.find((o) => o.n === "Üst"), al = mk.o.find((o) => o.n === "Alt");
      if (!ov || ov.odd <= 1) continue;
      const pk = al && al.odd > 1 ? (1 / ov.odd) / (1 / ov.odd + 1 / al.odd) : null;
      const p = `LIVE_${fh ? "IY_" : ""}AU_${mk.sov}`;
      if (out.some((z) => z.p === p)) continue;
      out.push({ p, s: "Üst", pa: `Canlı ${fh ? "1. Yarı " : ""}Alt/Üst ${mk.sov}`, et: `${fh ? "İY " : ""}${mk.sov}Ü`,
                 o: ov.odd, pk, m: liveProb(m, fh, line), open: mk.s === 1, line, fh });
    }
    return out.sort((a, b) => (a.fh - b.fh) || a.line - b.line);
  }
  function liveOddBtn(m, z) {
    const on = kupon[m.kod] && kupon[m.kod].p === z.p;
    if (!z.open) return `<div class="odd nood"><span class="n">CANLI ${esc(z.et)}</span><span class="o">${odd(z.o)}</span><span class="p">askıda</span></div>`;
    return `<button class="odd live ${on ? "on" : ""}" data-lk="${esc(m.kod)}" data-lp="${esc(z.p)}"><span class="n">CANLI ${esc(z.et)}</span>
      <span class="o">${odd(z.o)}</span><span class="p">${z.m == null ? "–" : pct(z.m)}</span></button>`;
  }
  function liveOddsGrid(kod) {
    const m = byKod(kod), x = LIVE[kod];
    if (!m || !x || x.phase !== 1) return "";
    const zs = liveOvers(m);
    if (zs === null) return `<div class="lodds-note">canlı oranlar yükleniyor…</div>`;
    if (!zs.length) return `<div class="lodds-note">⏸ canlı Üst oranı şu an kapalı/askıda</div>`;
    return `<div class="lodds-h">Canlı Üst oranları <span>iddaa · ${new Date(oddsAt).toLocaleTimeString("tr-TR", { timeZone: "Europe/Istanbul" })}</span></div>
      <div class="grid4">${zs.map((z) => liveOddBtn(m, z)).join("")}</div>`;
  }
function liveDetail(kod) {
    const m = byKod(kod), x = LIVE[kod];
    if (!m || !x || x.phase !== 1) return "";
    const zs = liveOvers(m);
    const when = `iddaa · ${new Date(oddsAt).toLocaleTimeString("tr-TR", { timeZone: "Europe/Istanbul" })}`;
    if (!zs || !zs.length) return `<div class="mkt"><div class="mkt-h"><span class="lbadge">CANLI</span> Toplam Gol Üst <span class="mkt-s">${when}</span></div>
      <div class="lodds-note">${LODDS[kod] || EVODDS[kod] ? "Şu an açık canlı Üst oranı yok (askıda olabilir)." : "Canlı oranlar yükleniyor…"}</div></div>`;
    const block = (title, list) => !list.length ? "" : `<div class="mkt"><div class="mkt-h"><span class="lbadge">CANLI</span> ${title} <span class="mkt-s">${when}</span></div>
      ${list.map((z) => oddRow(`${tr(z.line)} Üst`,
        `canlı tahmin ${z.m == null ? "–" : pct(z.m)} · piyasa ${z.pk == null ? "–" : pct(z.pk)}${z.m != null ? ` · değer ${z.m * z.o - 1 > 0 ? "+" : ""}${(z.m * z.o - 1).toFixed(2)}` : ""}`,
        rowBtn(`data-lk="${esc(m.kod)}" data-lp="${esc(z.p)}"`, z.o, kupon[m.kod]?.p === z.p, z.open ? null : "askıda"))).join("")}</div>`;
    return block("Toplam Gol Üst", zs.filter((z) => !z.fh)) + block("1. Yarı Gol Üst", zs.filter((z) => z.fh))
      + `<div class="lodds-note">Canlı tahmin: maç öncesi gol beklentisinin kalan süreye düşen payı ve mevcut skorla hesaplanır (kırmızı kart, tempo gibi etkenleri bilmez).</div>`;
  }

  // Dakika etiketi: ilk yarı (durum 2) 45'ten sonra "45+N", ikinci yarı 90'dan sonra "90+N"
  function minLabel(x) {
    const mn = x.min ?? 0;
    if (x.s === 2) return mn > 45 ? `45+${mn - 45}'` : `${mn}'`;
    if (mn > 120) return `120+${mn - 120}'`;     // uzatma devreleri (kupa maçları)
    if (mn > 105 && mn <= 120) return `${mn}'`;
    if (mn > 90) return `90+${mn - 90}'`;
    return `${mn}'`;
  }

  // Maç durumu etiketi
  function liveTag(kod, big) {
    const x = LIVE[kod];
    if (!x) return "";
    const sc = `${x.h} - ${x.a}`;
    const red = (n) => (n ? `<i class="rc">${n > 1 ? n : ""}</i>` : "");
    if (x.phase === 2) return `<span class="lv end">MS <b>${sc}</b></span>`;
    const t = x.s === 4 ? "İY" : minLabel(x);
    return `<span class="lv on"><i class="dot"></i>${t} <b>${red(x.hrc)}${sc}${red(x.arc)}</b></span>`;
  }
  // Üst tahmininin canlı durumu
  function pickState(kod, p) {
    const x = LIVE[kod]; if (!x) return "";
    const m = /^(?:LIVE_)?(IY_)?AU_(\d+\.5)$/.exec(p); if (!m) return "";
    const line = parseFloat(m[2]);
    const firstHalf = !!m[1];
    const goals = firstHalf ? (x.hh ?? 0) + (x.ha ?? 0) : x.h + x.a;
    const need = Math.floor(line) + 1 - goals;
    const over = firstHalf ? (x.phase === 2 || x.s === 4 || (x.min ?? 0) > 45 && x.s !== 2) : x.phase === 2;
    if (need <= 0) return `<span class="ps ok">✓ Tuttu</span>`;
    if (over) return `<span class="ps no">✗ Kaçtı</span>`;
    return `<span class="ps wait">${need} gol daha</span>`;
  }
  function paintLive() {
    document.querySelectorAll("[data-live]").forEach((el) => (el.innerHTML = liveTag(el.dataset.live)));
    document.querySelectorAll("[data-ps]").forEach((el) => { const [k, p] = el.dataset.ps.split("|"); el.innerHTML = pickState(k, p); });
    document.querySelectorAll("[data-livebox]").forEach((el) => (el.innerHTML = liveBox(el.dataset.livebox)));
    document.querySelectorAll("[data-lodds]").forEach((el) => (el.innerHTML = liveOddsGrid(el.dataset.lodds)));
    document.querySelectorAll("[data-crow]").forEach((el) => { const m = byKod(el.dataset.crow); if (m) { el.innerHTML = compactInner(m); el.classList.toggle("is-live", LIVE[m.kod]?.phase === 1); } });
    document.querySelectorAll("[data-lms]").forEach((el) => { const m = byKod(el.dataset.lms); if (m) el.innerHTML = msGrid(m, LIVE[m.kod]?.phase === 1); });
    document.querySelectorAll("[data-ldet]").forEach((el) => (el.innerHTML = liveDetail(el.dataset.ldet)));
    document.querySelectorAll("[data-pre]").forEach((el) => el.classList.toggle("pre-live", LIVE[el.dataset.pre]?.phase === 1));
    const mine = DATA.maclar.filter((m) => LIVE[m.kod]?.phase === 1).length;
    const all = Object.values(LIVE).filter((x) => x.phase === 1).length, lc = $("#lcount");
    if (lc) { lc.textContent = all > 99 ? "99+" : all; lc.classList.toggle("hidden", !all); }
    const el = $("#livecount"); if (el) { el.textContent = mine ? `● ${mine} canlı` : ""; el.classList.toggle("hidden", !mine); }
  }
  function liveBox(kod) {
    const m = byKod(kod); if (!m) return "";
    const x = LIVE[kod];
    const chips = (co, yc, rc) => `<div class="sb-chips">${co != null ? `<span title="korner">⚑ ${co}</span>` : ""}${yc != null ? `<span title="sarı kart"><i class="yc"></i>${yc}</span>` : ""}<span title="kırmızı kart"><i class="rc2"></i>${rc || 0}</span></div>`;
    let mid;
    if (!x) mid = `<div class="sb-pill sb-pre">${esc(m.saat)}</div><div class="sb-score sb-vs">vs</div><div class="sb-ht">başlamadı</div>`;
    else {
      const pill = x.phase === 2 ? `<div class="sb-pill sb-end">MS</div>` : x.s === 4 ? `<div class="sb-pill">İY</div>` : `<div class="sb-pill"><i class="dot"></i>${minLabel(x)}</div>`;
      mid = `${pill}<div class="sb-score">${x.h} <span>-</span> ${x.a}</div><div class="sb-ht">İY: ${x.hh ?? "–"}-${x.ha ?? "–"}</div>`;
    }
    return `<div class="sb ${x?.phase === 1 ? "on" : ""}">
      <div class="sb-team"><b>${esc(m.ev)}</b>${x ? chips(x.hco, x.hyc, x.hrc) : ""}</div>
      <div class="sb-mid">${mid}</div>
      <div class="sb-team"><b>${esc(m.dep)}</b>${x ? chips(x.aco, x.ayc, x.arc) : ""}</div></div>
      ${x ? `<div class="sb-upd">güncelleme ${new Date(liveAt).toLocaleTimeString("tr-TR", { timeZone: "Europe/Istanbul" })}</div>` : ""}`;
  }

  // Oran satırı: "2,5 Üst ............ [1.43]" + altında tahmin/piyasa
  const tr = (line) => String(line).replace(".", ",");
  function oddRow(label, sub, btn) {
    return `<div class="orow"><div class="olab">${label}<small>${sub}</small></div>${btn}</div>`;
  }
  function rowBtn(attrs, o, on, dis) {
    if (dis) return `<div class="obtn dis">${dis}</div>`;
    return `<button class="obtn ${on ? "on" : ""}" ${attrs}>${odd(o)}</button>`;
  }

  // ---------- veri ----------
  async function load(url, isLive) {
    const btn = $("#refresh"); btn.classList.add("spin");
    try {
      const r = await fetch(url + (url.includes("?") ? "&" : "?") + "t=" + Date.now(), { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      DATA = await r.json(); live = isLive; lastLoad = Date.now();
      if (isLive) LS.set("son_veri", DATA);
      cleanKupon();
      render();
      fetchLive();
      const hm = /^#mac=(\d+)$/.exec(location.hash || "");   // paylaşılabilir bağlantı: .../app/#mac=<kod>
      if (hm && !curKod && byKod(hm[1])) openDetail(hm[1]);
      if (isLive) toast("Güncel rapor yüklendi");
    } catch (e) {
      const cached = LS.get("son_veri", null);
      if (cached && isLive) { DATA = cached; live = true; render(); toast("Çevrimdışı: son kaydedilen rapor gösteriliyor"); }
      else view.innerHTML = `<div class="empty"><p>Rapor yüklenemedi.<br>İnternet bağlantınızı kontrol edip yenileyin.</p></div>`;
    } finally { btn.classList.remove("spin"); }
  }
  const byKod = (k) => {
    const a = DATA && DATA.maclar.find((m) => m.kod === k); if (a) return a;
    const e = BUL && BUL.get(k); if (e) return extMatch(e);
    const L = LIVEMETA[k]; if (L) return extMatch({ i: k, hn: L.ev, an: L.dep, ci: L.ci, d: L.d, mbc: null, m: [] });
    return null;
  };
  // Biten maç: canlı servis "MS" diyorsa ya da (canlı kaydı yoksa) başlamasının üzerinden 2,5 saat geçmişse
  const isFinished = (m) => { const x = LIVE[m.kod]; if (x) return x.phase === 2;
    return Date.now() - new Date(m.baslama).getTime() > 150 * 60e3; };
  const opt = (m, p, s) => m.secenekler.find((o) => o.p === p && o.s === s);

  function cleanKupon() { // başlamış maçları ve farklı günün seçimlerini kupondan çıkar
    const now = Date.now();
    for (const k of Object.keys(kupon)) {
      if (!live) continue;
      const b = kupon[k].baslama || (byKod(k) || {}).baslama;
      if (b && now - new Date(b).getTime() > 6 * 3600e3) delete kupon[k];   // maç bittikten sonra 6 saat sonucu görünsün
    }
    saveKupon();
  }
  function saveKupon() { LS.set("kupon", kupon); const n = Object.keys(kupon).length; const b = $("#kcount"); b.textContent = n; b.classList.toggle("hidden", !n); }

  function toggle(m, o) {
    const cur = kupon[m.kod];
    if (cur && cur.p === o.p && cur.s === o.s) { delete kupon[m.kod]; toast("Kupondan çıkarıldı"); }
    else {
      kupon[m.kod] = { p: o.p, s: o.s, o: o.o, m: o.m, pk: o.pk, mbs: o.mbs || m.mbs, mac: `${m.ev} – ${m.dep}`, pa: o.pa, saat: m.saat, baslama: m.baslama };
      toast(cur ? "Aynı maçtan tek seçim: değiştirildi" : `Kupona eklendi · ${Object.keys(kupon).length} maç`);
    }
    saveKupon(); render(true);
  }
  const isOn = (m, o) => kupon[m.kod] && kupon[m.kod].p === o.p && kupon[m.kod].s === o.s;

  // ---------- parçalar ----------
  function oddBtn(m, o, label, extraCls = "") {
    if (!o) return `<button class="odd dis"><span class="n">${esc(label)}</span><span class="o">–</span><span class="p">kapalı</span></button>`;
    if (m.baslamis) return `<div class="odd nood" title="maç başladı"><span class="n">${esc(label)}</span><span class="o">${o.o == null ? "–" : odd(o.o)}</span><span class="p">${pct(o.m)}</span></div>`;
    if (o.o == null) return `<div class="odd nood" title="iddaa bu pazarı açmamış"><span class="n">${esc(label)}</span><span class="o">${pct(o.m)}</span><span class="p">oran yok</span></div>`;
    const best = m.secim && m.secim.p === o.p && m.secim.s === o.s;
    return `<button class="odd ${isOn(m, o) ? "on" : ""} ${best ? "best" : ""} ${extraCls}" data-k="${esc(m.kod)}" data-p="${esc(o.p)}" data-s="${esc(o.s)}">
      <span class="n">${esc(label)}</span><span class="o">${odd(o.o)}</span><span class="p">${pct(o.m)}</span></button>`;
  }
  function ring(g) {
    const c = g >= 70 ? "var(--acc)" : g >= 60 ? "#9be15d" : g >= 50 ? "var(--amber)" : "var(--red)";
    return `<div class="ring" style="--v:${g};--c:${c}"><b>${Math.round(g)}<small>güven</small></b></div>`;
  }
  function valChip(d) { return `<span class="chip ${d > 0 ? "pos" : "neg"}">değer ${d > 0 ? "+" : ""}${d.toFixed(2)}</span>`; }
  const teams = (m) => `<div class="teams"><span>${esc(m.ev)}<span class="vs">–</span>${esc(m.dep)}</span>${favBtn(m)}</div>`;
  const meta = (m) => `<div class="meta"><span class="lig">${esc(m.lig)}</span><span class="mlive" data-live="${esc(m.kod)}">${liveTag(m.kod)}</span><span class="mtime">${esc(m.saat)} · MBS ${esc(m.mbs)}</span></div>`;

  // ---------- sekmeler ----------
  function vSecim() {
    const picks = DATA.ozet.map((p) => ({ m: byKod(p.kod), o: null, p })).filter((x) => x.m && !isFinished(x.m));
    picks.forEach((x) => (x.o = opt(x.m, x.p.p, x.p.s)));
    let h = `<div class="hero"><div class="big">${picks.length}</div><p><b>Günün seçimleri</b><br>Yalnızca Üst tahminleri (İY 1.5, 2.5, 3.5, 4.5). Güven ≥55, maç başına 1 seçim. Başlamış maçlar canlı skoruyla listede kalır. Oranlar ${esc((DATA.oran_zamani || "").slice(11, 16))} itibarıyla.</p></div>`;
    for (const { m, o } of picks) {
      if (!o) continue;
      h += `<div class="card tap" data-open="${esc(m.kod)}">${meta(m)}${teams(m)}
        <div class="pick">${ring(o.g)}<div class="lbl"><div class="mk">Üst tahmini</div><div class="sel">${esc(o.etiket || o.pa + " " + o.s)}</div></div>${oddBtn(m, o, "oran")}</div>
        <div class="stats"><span data-ps="${esc(m.kod)}|${esc(o.p)}">${pickState(m.kod, o.p)}</span><span class="chip">tahmin ${pct(o.m)}</span><span class="chip">istatistik ${pct(o.i)}</span>${valChip(o.d)}
        ${(m.risk || []).slice(0, 1).map((r) => `<span class="chip warn">${esc(r)}</span>`).join("")}</div></div>`;
    }
    if (DATA.kuponlar && DATA.kuponlar.length) {
      h += `<div class="h"><h2>Hazır kuponlar</h2><span>dokun → kupona ekle</span></div>`;
      DATA.kuponlar.forEach((c, i) => {
        const items = c.secimler.map((k) => { const m = byKod(k); const p = DATA.ozet.find((z) => z.kod === k); return m && p ? { m, o: opt(m, p.p, p.s) } : null; }).filter((x) => x && x.o);
        const to = items.reduce((a, x) => a * x.o.o, 1), tp = items.reduce((a, x) => a * x.o.m, 1);
        h += `<div class="card"><div class="meta"><span>${esc(c.ad)}</span><span>${items.length} maç</span></div>
          <div class="stats" style="margin:8px 0"><span class="chip">toplam oran ${odd(to)}</span><span class="chip">kombine olasılık ${pct(tp)}</span></div>
          <button class="btn" data-hazir="${i}">Kupona ekle</button></div>`;
      });
    }
    h += `<button class="btn" data-tab="gecmis">🕘 Geçmiş raporlar</button><div class="note">${esc(DATA.not)}</div><div class="disc">${esc(DATA.uyari)}</div>`;
    return h;
  }

  function matchRow(m) {
    const g = (p, s) => opt(m, p, s);
    return `<div class="card mrow"><div class="tap" data-open="${esc(m.kod)}">${meta(m)}${teams(m)}</div>
        <div data-lodds="${esc(m.kod)}">${liveOddsGrid(m.kod)}</div>
        <div class="pre-h">Maç öncesi</div>
        <div class="grid4" data-pre="${esc(m.kod)}">${(DATA.pazarlar || []).map((z) => oddBtn(m, g(z.pazar, z.secenek), z.etiket.replace(" Üst", "Ü"))).join("")}</div>
        <button class="more" data-open="${esc(m.kod)}">detay · form · skor olasılıkları · haberler</button></div>`;
  }

  function vFav() {
    if (!BUL && !bulBusy) loadBulletin();     // MS oranları için
    const ks = Object.keys(FAV);
    if (!ks.length) return `<div class="empty"><div style="font-size:2.6rem;opacity:.5">☆</div>
      <p>Henüz favori maçın yok.<br>Takip etmek istediğin maçın yanındaki <b>☆</b> yıldıza dokun.</p></div>`;
    const here = Object.keys(FAV).map(byKod).filter((m) => m && !isFinished(m));
    const liveN = here.filter((m) => LIVE[m.kod]?.phase === 1).length;
    let h = `<div class="h"><h2>★ Favorilerim</h2><span>${ks.length} maç${liveN ? ` · <b style="color:#ff8a85">${liveN} canlı</b>` : ""}</span></div>`;
    // canlı olanlar üstte, sonra başlama saatine göre
    here.sort((a, b) => ((LIVE[b.kod]?.phase === 1) - (LIVE[a.kod]?.phase === 1)) || a.baslama.localeCompare(b.baslama));
    for (const m of here) h += compactRow(m);
    const other = ks.filter((k) => !byKod(k));
    if (other.length) {
      h += `<div class="lgroup">Bu raporda olmayan favoriler</div>`;
      for (const k of other) { const f = FAV[k];
        h += `<div class="card"><div class="meta"><span class="lig">${esc(f.lig)}</span><span>${esc(f.tarih)} ${esc(f.saat)}</span></div>
          <div class="teams"><span>${esc(f.ev)}<span class="vs">–</span>${esc(f.dep)}</span><button class="fav on" data-fav="${esc(k)}">★</button></div></div>`; }
    }
    return h + `<div class="disc">Favoriler yalnızca bu cihazda saklanır; maçtan 2 gün sonra kendiliğinden silinir.</div>`;
  }

  const dayLabel = (d) => { const t = todayTR(); const tm = new Date(Date.parse(t + "T12:00:00Z") + 864e5).toISOString().slice(0, 10);
    return d === t ? "Bugün" : d === tm ? "Yarın" : d.slice(8, 10) + "." + d.slice(5, 7); };
  function msMarket(m) {
    const lv = LIVE[m.kod]?.phase === 1;
    const src = lv ? (LODDS[m.kod] && LODDS[m.kod].m) || [] : (m.raw ? m.raw.m : (BUL && BUL.get(m.kod) ? BUL.get(m.kod).m : [])) || [];
    return src.find((x) => (lv ? x.t === 4 && x.st === 4 : x.t === 1 && x.st === 1));
  }
  function compactInner(m) {
    const x = LIVE[m.kod], lv = x?.phase === 1;
    const left = lv ? `<span class="cl live"><i class="dot"></i>${x.s === 4 ? "İY" : minLabel(x)}</span>`
      : `<span class="cl">${esc(m.saat)}</span>`;
    const sc = (v) => (lv ? `<b class="csc">${v}</b>` : "");
    const mk = msMarket(m);
    const btn = (n) => { const o = mk && mk.o.find((q) => q.n === n);
      if (!o || !(o.odd > 1) || (mk.s != null && mk.s !== 1)) return `<span class="cms-o dis">–</span>`;
      const on = kupon[m.kod] && kupon[m.kod].p === mkKey(mk) && kupon[m.kod].s === n;
      return `<button class="cms-o ${on ? "on" : ""}" data-mk="${esc(m.kod)}|${mk.t}|${mk.st}|${esc(mk.sov ?? "")}|${n}"><small>${niceOut(n)}</small>${odd(o.odd)}</button>`; };
    const an = DATA.maclar.some((q) => q.kod === m.kod);
    return `${left}<div class="ct"><div class="ctn">${sc(x?.h)}<span>${esc(m.ev)}</span></div><div class="ctn">${sc(x?.a)}<span>${esc(m.dep)}</span></div>
      ${an || isFav(m.kod) ? `<div class="ctag">${an ? "📊" : ""}${isFav(m.kod) ? "★" : ""}</div>` : ""}</div>
      <div class="cms">${["1", "0", "2"].map(btn).join("")}</div>`;
  }
  const compactRow = (m) => `<div class="crow ${LIVE[m.kod]?.phase === 1 ? "is-live" : ""}" data-open="${esc(m.kod)}" data-crow="${esc(m.kod)}">${compactInner(m)}</div>`;
  function bultenRow(m) { return compactRow(m); }
  function bultenRowOld(m) {
    const a = DATA.maclar.find((x) => x.kod === m.kod);
    const o25 = a && a.secenekler.find((o) => o.p === "AU_2.5");
    const lv = LIVE[m.kod]?.phase === 1;
    const n = (m.raw && m.raw.oc) || (BUL && BUL.get(m.kod) && BUL.get(m.kod).oc);
    return `<div class="card mrow"><div class="tap" data-open="${esc(m.kod)}">${meta(m)}${teams(m)}</div>
      ${a ? `<div class="abadge">📊 Analiz${o25 ? ` · 2,5 Üst %${Math.round(100 * o25.m)}` : ""}</div>` : ""}
      <div data-lms="${esc(m.kod)}">${msGrid(m, lv)}</div>
      ${lv ? `<div data-lodds="${esc(m.kod)}">${liveOddsGrid(m.kod)}</div>` : ""}
      <button class="more" data-open="${esc(m.kod)}">${n ? `+${n} bahis · ` : ""}bütün bahisler · istatistik · kadro</button></div>`;
  }
  function vBulten() {
    if (!BUL) { loadBulletin();
      return `<div class="empty">${bulErr ? "Bülten yüklenemedi. İnternet bağlantını kontrol edip yenile." : "Tüm iddaa bülteni yükleniyor… (yaklaşık 1 MB, yalnızca ilk açılışta)"}</div>`; }
    const all = [...BUL.values()].map(extMatch).filter((m) => !isFinished(m));
    const days = [...new Set(all.map((m) => m.baslama.slice(0, 10)))].sort();
    if (!bday || (bday !== "analiz" && !days.includes(bday))) bday = days.includes(todayTR()) ? todayTR() : days[0] || "analiz";
    let h = `<div class="filters">${[["analiz", "📊 Analizli"], ...days.map((d) => [d, dayLabel(d)])].map(([id, ad]) =>
      `<button class="fchip ${bday === id ? "on" : ""}" data-bday="${id}">${ad}</button>`).join("")}</div>`;
    if (bday === "analiz") return h + vMac();   // BUL zaten yüklü (MS oranları)
    const dayList = all.filter((m) => m.baslama.slice(0, 10) === bday);
    const ligs = [...new Map(dayList.map((m) => [m.ci, m.lig])).entries()].sort((a, b) => ligPrio(a[0]) - ligPrio(b[0]));
    h += `<input class="search" id="bq" placeholder="Takım veya lig ara…" value="${esc(bq)}">
      <select class="lsel" id="blig"><option value="">Bütün ligler (${ligs.length})</option>${ligs.map(([ci, n]) => `<option value="${esc(ci)}" ${String(ci) === blig ? "selected" : ""}>${esc(n || "Lig " + ci)}</option>`).join("")}</select>`;
    const ql = bq.toLocaleLowerCase("tr");
    const list = dayList.filter((m) => (!blig || String(m.ci) === blig) && (!ql || `${m.ev} ${m.dep} ${m.lig}`.toLocaleLowerCase("tr").includes(ql)))
      .sort((a, b) => a.baslama.localeCompare(b.baslama) || ligPrio(a.ci) - ligPrio(b.ci));
    h += `<div class="h"><h2>${dayLabel(bday)} · ${list.length} maç</h2><span>oranlar iddaa</span></div>`;
    let last = "";
    for (const m of list.slice(0, bshow)) {
      const grp = `${m.saat} · ${m.lig}`;
      if (m.lig !== last) { h += `<div class="lgroup">${esc(m.lig || "Diğer")}</div>`; last = m.lig; }
      h += bultenRow(m);
    }
    if (list.length > bshow) h += `<button class="btn" data-more="1">Daha fazla göster (${list.length - bshow} maç daha)</button>`;
    if (!list.length) h += `<div class="empty">Eşleşen maç yok.</div>`;
    return h;
  }
  function vCanli() {
    const ks = Object.keys(LIVE).filter((k) => LIVE[k].phase === 1);
    if (!liveAt) return `<div class="empty">Canlı maçlar yükleniyor…</div>`;
    if (!ks.length) return `<div class="empty">Şu an oynanan maç yok.</div>`;
    const ms = ks.map(byKod).filter(Boolean).sort((a, b) => ligPrio(a.ci) - ligPrio(b.ci) || a.lig.localeCompare(b.lig) || a.baslama.localeCompare(b.baslama));
    let h = `<div class="h"><h2>● Canlı · ${ms.length} maç</h2><span>skor 1 sn, oran 2 sn'de bir</span></div>`, last = "";
    for (const m of ms) {
      if (m.lig !== last) { h += `<div class="lgroup">${esc(m.lig || "Diğer")}</div>`; last = m.lig; }
      h += compactRow(m);
    }
    return h;
  }

  function vMac() {
    const ligs = ["Tümü", "Canlı", ...new Set(DATA.maclar.filter((m) => !isFinished(m)).map((m) => m.lig))];
    let h = `<input class="search" id="q" placeholder="Takım ara…" value="${esc(q)}">
      <div class="filters">${ligs.map((l) => `<button class="fchip ${l === lig ? "on" : ""}" data-lig="${esc(l)}">${esc(l)}</button>`).join("")}</div>`;
    const ql = q.toLocaleLowerCase("tr");
    const list = DATA.maclar.filter((m) => !isFinished(m) && (lig === "Tümü" || m.lig === lig || (lig === "Canlı" && LIVE[m.kod]?.phase === 1)) && (!ql || (m.ev + " " + m.dep).toLocaleLowerCase("tr").includes(ql)));
    let last = "";
    for (const m of list) {
      if (m.lig !== last) { h += `<div class="lgroup">${esc(m.lig)}</div>`; last = m.lig; }
      h += compactRow(m);
    }
    if (!list.length) h += `<div class="empty">${lig === "Canlı" ? "Şu an oynanan maç yok." : "Eşleşen maç yok."}</div>`;
    return h;
  }

  function vKupon() {
    const ks = Object.entries(kupon);
    if (!ks.length) return `<div class="empty"><svg viewBox="0 0 24 24"><path d="M5 4h14v5a3 3 0 0 0 0 6v5H5v-5a3 3 0 0 0 0-6z" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>
      <p>Kuponun boş.<br>Seçimler veya Maçlar sekmesinde bir orana dokun.</p></div>`;
    let h = `<div class="h"><h2>Kuponum</h2><span>${ks.length} maç</span></div>`;
    for (const [k, s] of ks) {
      h += `<div class="card kitem"><button class="x" data-del="${esc(k)}" aria-label="Sil">✕</button>
        <div class="info"><div class="t">${esc(s.saat)} · ${esc(s.mac)}</div><div class="s">${esc(s.pa)}: ${esc(s.mk ? niceOut(s.s) : nice(s.s))}</div>
        <div class="t">tahmin ${pct(s.m)} · MBS ${esc(s.mbs)} <span data-live="${esc(k)}">${liveTag(k)}</span> <span data-ps="${esc(k)}|${esc(s.p)}">${pickState(k, s.p)}</span></div>
        <div class="kchk" data-kchk="${esc(k)}">${kuponCheck(k)}</div></div><div class="o">${odd(s.o)}</div></div>`;
    }
    const to = ks.reduce((a, [, s]) => a * s.o, 1), tp = ks.reduce((a, [, s]) => a * s.m, 1);
    const maxMbs = Math.max(...ks.map(([, s]) => Number(s.mbs) || 1));
    const stake = LS.get("stake", 10);
    const ev = stake * (tp * to - 1);
    h += `<div class="sum">
      <div class="row"><span>Toplam oran</span><b>${odd(to)}</b></div>
      <div class="row"><span>Kombine olasılık</span><b>${pct(tp, 1)}</b></div>
      <div class="row" style="font-size:.76rem;color:var(--muted)"><span>${ks.map(([, s]) => pct(s.m)).join(" × ")}</span><span></span></div>
      <div class="stake"><span>Tutar</span><input id="stake" type="number" min="1" inputmode="decimal" value="${esc(stake)}"><span>₺</span></div>
      <div class="row"><span>Olası kazanç</span><b>${(stake * to).toFixed(2)} ₺</b></div>
      <div class="row"><span>Beklenen sonuç (uzun vadede)</span><b style="color:${ev >= 0 ? "#7ff0a8" : "#ff9b97"}">${ev >= 0 ? "+" : ""}${ev.toFixed(2)} ₺</b></div>
      ${ks.length < maxMbs ? `<div class="warn">⚠ Bu kupondaki en yüksek MBS ${maxMbs}. En az ${maxMbs} maç eklemelisin; bu haliyle oynanamaz.</div>` : ""}
      ${ks.length >= 4 ? `<div class="warn">Her eklenen maç kazanma ihtimalini düşürür (şu an ${pct(tp)}).</div>` : ""}
      </div>
      <div class="warn" id="kwarn"></div>
      <div class="kbtns"><button class="btn pri" id="kcopy">📋 Kuponu kopyala</button>
        <a class="btn bil" href="https://www.bilyoner.com/" target="_blank" rel="noopener">Bilyoner'i aç ↗</a></div>
      <div class="kpreview" id="kprev">${esc(kuponText()).replace(/\n/g, "<br>")}</div>
      <button class="btn" id="clear">Kuponu temizle</button>
      <div class="disc">Kupon yalnızca bu cihazda tutulur; uygulama bahis yapmaz ve hesabına bağlanmaz. Kopyaladığın listeye bakarak kuponu Bilyoner'de kendin kurup oynarsın. ${esc(DATA.uyari)}</div>`;
    return h;
  }

  async function vGecmis() {
    view.innerHTML = `<div class="empty">Yükleniyor…</div>`;
    let man = [];
    try { const r = await fetch("../manifest.json?t=" + Date.now(), { cache: "no-store" }); man = await r.json(); } catch (e) {}
    let h = `<div class="h"><h2>Geçmiş raporlar</h2><span>${man.length} rapor</span></div><div class="hist">`;
    if (!live) h += `<a href="#" data-latest="1"><span><b>← Güncel rapora dön</b></span><span></span></a>`;
    for (const m of man) if (m.data) h += `<a href="#" data-hist="${esc(m.data)}"><span>${esc(m.tarih)}</span><span>${esc(m.saat)}</span></a>`;
    if (!man.length) h += `<div class="empty">Henüz geçmiş rapor yok.</div>`;
    view.innerHTML = h + "</div>";
  }

  // ---------- detay paneli ----------
  let curMt = "MS", curKod = null;
  function openDetail(kod) {
    const m = byKod(kod); if (!m) return;
    curKod = kod; dTab = "oran";
    drawDetail(m);
    $("#sheet").classList.remove("hidden"); document.body.style.overflow = "hidden";
    $("#sheetBody").scrollTop = 0;
    history.pushState({ detay: kod }, "");   // Android geri tuşu paneli kapatsın
    fetchEvent(kod); fetchEspn(kod);
  }
  // ---------- maç detayı: sekmeler ----------
  const ST = "https://statisticsv2.iddaa.com/statistics/soccer";
  const DET = {};   // {kod: {lineup, standings, rh, ra, h2h, ins, cc}}  (oturum içi önbellek)
  let dTab = "oran", dSub = { bilgi: "akis", ist: "canli" };
  async function detFetch(kod, key, path) {
    DET[kod] = DET[kod] || {};
    if (DET[kod][key] !== undefined) return DET[kod][key];
    DET[kod][key] = null;   // yükleniyor
    try {
      const r = await fetch(`${ST}/${path}`, { cache: "no-store" });
      const j = r.ok ? await r.json() : null;
      DET[kod][key] = j && j.isSuccess ? j.data : false;
    } catch (e) { DET[kod][key] = false; }
    if (curKod === kod) drawTab(byKod(kod));
    return DET[kod][key];
  }
  const need = (kod, key, path) => { const v = DET[kod]?.[key]; if (v === undefined) detFetch(kod, key, path); return v; };
  const loading = `<div class="lodds-note">Yükleniyor…</div>`;
  const nodata = (t) => `<div class="lodds-note">${t || "Kaynakta veri yok."}</div>`;
  const fbadge = (s) => [...(s || "")].map((c) => `<span class="fb ${c}">${c}</span>`).join("");
  const o2 = (x) => (x == null ? "–" : Number(x).toFixed(2));
  const dt = (ts) => { const d = new Date(ts * 1000); return d.toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit", year: "2-digit", timeZone: "Europe/Istanbul" }); };

  function drawDetail(m) {
    const tabs = [["oran", "Oranlar"], ["bilgi", "Bilgiler"], ["ist", "İstatistik"], ["analiz", "Analiz"]];
    $("#sheetBody").innerHTML = `<div class="sh-top"><div class="grab"></div><div class="sh-head"><div>${meta(m)}<h3>${esc(m.ev)} – ${esc(m.dep)}</h3></div>
      <div class="shbtns"><span data-favd="${esc(m.kod)}">${favBtn(m)}</span><button class="close" data-close="1" aria-label="Kapat">✕</button></div></div>
      <div data-livebox="${esc(m.kod)}">${liveBox(m.kod)}</div>
      <div data-goals="${esc(m.kod)}">${scorersUnder(m.kod)}</div>
      <div class="dtabs">${tabs.map(([id, ad]) => `<button class="dtab ${id === dTab ? "on" : ""}" data-dtab="${id}">${ad}${id === "ist" && LIVE[m.kod]?.phase === 1 ? ' <i class="dot"></i>' : ""}</button>`).join("")}</div></div>
      <div id="dtab"></div>`;
    drawTab(m);
    paintLive();
  }
  function subtabs(group, list) {
    return `<div class="dsubs">${list.map(([id, ad]) => `<button class="dsub ${dSub[group] === id ? "on" : ""}" data-dsub="${group}|${id}">${ad}</button>`).join("")}</div>`;
  }
  function drawTab(m) {
    const el = $("#dtab"); if (!el || !m) return;
    const y = $("#sheetBody").scrollTop;
    el.innerHTML = dTab === "oran" ? tabOran(m) : dTab === "bilgi" ? tabBilgi(m) : dTab === "ist" ? tabIst(m) : tabAnaliz(m);
    $("#sheetBody").scrollTop = y;
    paintLive();
  }

  // --- Oranlar ---
  function tabOran(m) {
    const ord = (o) => (DATA.pazarlar || []).findIndex((z) => z.pazar === o.p && z.secenek === o.s);
    let h = `<div data-ldet="${esc(m.kod)}">${liveDetail(m.kod)}</div>`;
    if (!m.secenekler.length) return h + `<div class="sec">Bütün bahisler <span class="mkt-s">iddaa</span></div><div data-allmk="1">${renderMarkets(m)}</div>`;
    h += `
      <div class="mkt"><div class="mkt-h">Maç öncesi Üst tahminleri <span class="mkt-s">oranlar ${esc((m.oran_zamani || DATA.oran_zamani || "").slice(11, 16))}</span></div>`;
    for (const o of [...m.secenekler].sort((a, b) => ord(a) - ord(b))) {
      const sub = `tahmin ${pct(o.m)} · piyasa ${o.pk == null ? "–" : pct(o.pk)} · istatistik ${o.i == null ? "–" : pct(o.i)}`
        + (o.o == null ? "" : ` · güven ${Math.round(o.g)}`) + (o.sup ? " · <span style='color:#ffcf70'>şüpheli</span>" : "");
      const dis = o.o == null ? "yok" : m.baslamis ? odd(o.o) : null;
      h += oddRow(esc((o.etiket || o.s).replace(/(\d)\.5/, "$1,5")), sub, rowBtn(`data-k="${esc(m.kod)}" data-p="${esc(o.p)}" data-s="${esc(o.s)}"`, o.o, isOn(m, o), dis));
    }
    return h + `</div><div class="sec">Bütün bahisler <span class="mkt-s">iddaa</span></div><div data-allmk="1">${renderMarkets(m)}</div>`;
  }

  // --- Bilgiler ---
  function tabBilgi(m) {
    let h = subtabs("bilgi", [["akis", "Maç Akışı"], ["ozet", "Özet"], ["kadro", "Kadro"], ["sakat", "Sakat/Ceza"]]);
    if (dSub.bilgi === "akis") {
      h += `<div data-akis="${esc(m.kod)}">${akisView(m)}</div>`;
    } else if (dSub.bilgi === "ozet") {
      const x = LIVE[m.kod];
      h += `<div class="mkt"><div class="mkt-h">Maç bilgisi</div>
        <div class="kv2"><span>Turnuva</span><b>${esc(m.lig)}</b><span>Başlama</span><b>${esc(m.baslama.slice(0, 10).split("-").reverse().join("."))} ${esc(m.saat)}</b>
        <span>MBS</span><b>${esc(m.mbs)}</b><span>Maç kodu</span><b>${esc(m.kod)}</b>
        ${x ? `<span>Durum</span><b>${x.phase === 2 ? "Maç sonu" : x.s === 4 ? "Devre arası" : minLabel(x)}</b><span>İlk yarı</span><b>${x.hh ?? "–"} - ${x.ha ?? "–"}</b>` : ""}</div></div>
        <div class="mkt"><div class="mkt-h">En olası skorlar <span class="mkt-s">maç öncesi model</span></div><div class="scores">${(m.skorlar || []).map((s) => `<div class="score"><b>${esc(s.skor)}</b><small>${pct(s.olasilik, 1)}</small></div>`).join("")}
        <div class="score"><b>${o2(m.lambda?.ev)} : ${o2(m.lambda?.dep)}</b><small>beklenen gol</small></div></div></div>
        <div class="mkt"><div class="mkt-h">Sonraki maçlar</div><div class="kv2"><span>${esc(m.ev)}</span><b>${esc((m.sonraki?.ev_sonraki || [])[0] || "bültende yok")}</b>
        <span>${esc(m.dep)}</span><b>${esc((m.sonraki?.dep_sonraki || [])[0] || "bültende yok")}</b></div></div>
        <div class="lodds-note">Gol, kart ve penaltı dakikaları "Maç Akışı" sekmesinde (kaynak ESPN); anlık skor, korner ve kartlar İstatistik › Canlı sekmesinde.</div>`;
    } else if (dSub.bilgi === "kadro") {
      const L = need(m.kod, "lineup", `lineup/${m.kod}`);
      h += L === null || L === undefined ? loading : !L ? nodata("Kadro bilgisi yok.") : lineupView(L);
    } else {
      const hs = (m.haberler || []);
      const inj = hs.filter((n) => (n.kat || []).some((c) => c === "sakatlik" || c === "ceza"));
      h += `<div class="mkt"><div class="mkt-h">Sakat / cezalı haberleri <span class="mkt-s">son 72 saat</span></div>
        <div class="news">${inj.length ? inj.map(newsItem).join("") : nodata("Bu maç için sakatlık/ceza haberi bulunamadı.")}</div></div>
        <div class="mkt"><div class="mkt-h">Diğer haberler</div><div class="news">${hs.filter((n) => !inj.includes(n)).map(newsItem).join("") || nodata("Haber yok.")}</div></div>
        <div class="lodds-note">Resmi sakat/cezalı listesi kaynakta yok; haber başlıklarından derlenir, doğruluğu garanti değildir.</div>`;
    }
    return h;
  }
  const newsItem = (n) => `<a href="${esc(safeUrl(n.l))}" target="_blank" rel="noopener">${esc(n.b)}<small>${esc(n.k)} · ${esc((n.t || "").slice(0, 16).replace("T", " "))}</small></a>`;
  function lineupView(L) {
    const rows = (team) => {
      const xi = (team.p || []).filter((p) => !p.r);
      const g = { Kaleci: [], Savunma: [], Orta: [], Forvet: [] };
      for (const p of xi) {
        const pos = (p.lp || p.p || "");
        (/kaleci/i.test(pos) ? g.Kaleci : /savun|defans|bek|stoper/i.test(pos) ? g.Savunma : /forvet|santrafor|kanat forvet/i.test(pos) ? g.Forvet : g.Orta).push(p);
      }
      return [g.Kaleci, g.Savunma, g.Orta, g.Forvet].filter((r) => r.length);
    };
    const player = (p, cls) => `<div class="pl ${cls}"><span class="pj">${esc(p.j ?? "")}</span><span class="pn">${esc((p.n || "").replace(/^(\w)\.\s?/, "$1. "))}</span></div>`;
    const half = (team, cls, rev) => { const rs = rows(team); return `<div class="half ${cls}">${(rev ? [...rs].reverse() : rs).map((r) => `<div class="prow">${r.map((p) => player(p, cls)).join("")}</div>`).join("")}</div>`; };
    const subs = (team) => (team.p || []).filter((p) => p.r).map((p) => `${esc(p.n)}${p.j ? ` (${esc(p.j)})` : ""}`).join(", ") || "–";
    return `<div class="mkt"><div class="mkt-h">Kadro <span class="mkt-s">${L.pm === true || L.pm === "true" ? "resmi" : "tahmini"}</span></div>
      <div class="lteams"><div><b>${esc(L.h?.n)}</b><small>${esc(L.h?.f || "")} · TD ${esc(L.h?.m || "–")}</small></div><div style="text-align:right"><b>${esc(L.a?.n)}</b><small>${esc(L.a?.f || "")} · TD ${esc(L.a?.m || "–")}</small></div></div>
      <div class="pitch">${half(L.a || {}, "away", false)}<div class="midline"></div>${half(L.h || {}, "home", true)}</div>
      <div class="lodds-note"><b>${esc(L.h?.n)} yedekler:</b> ${subs(L.h || {})}<br><b>${esc(L.a?.n)} yedekler:</b> ${subs(L.a || {})}</div></div>`;
  }

  // --- İstatistik ---
  function cmpBar(label, a, b) {
    const A = Number(a) || 0, B = Number(b) || 0, t = A + B || 1;
    return `<div class="cmp"><div class="cmp-h"><b>${a ?? "–"}</b><span>${label}</span><b>${b ?? "–"}</b></div>
      <div class="cmp-b"><div class="ca"><i style="width:${100 * A / t}%"></i></div><div class="cb"><i style="width:${100 * B / t}%"></i></div></div></div>`;
  }
  function tabIst(m) {
    let h = subtabs("ist", [["canli", "Canlı"], ["kars", "Karşılaştırma"], ["puan", "Puan Durumu"]]);
    if (dSub.ist === "canli") {
      const x = LIVE[m.kod];
      if (!x) return h + nodata("Maç başlayınca canlı istatistikler burada görünür.");
      h += `<div class="mkt"><div class="cmp-t"><b>${esc(m.ev)}</b><b>${esc(m.dep)}</b></div>
        ${cmpBar("Gol", x.h, x.a)}${cmpBar("İlk yarı gol", x.hh, x.ha)}${cmpBar("Korner", x.hco, x.aco)}${cmpBar("Sarı kart", x.hyc, x.ayc)}${cmpBar("Kırmızı kart", x.hrc, x.arc)}</div>
        <div class="lodds-note">xG, topla oynama ve şut istatistikleri iddaa'nın açık servislerinde bulunmuyor. Veriler saniyede bir güncellenir.</div>`;
    } else if (dSub.ist === "kars") {
      if (m.form) h += `<div class="mkt"><div class="mkt-h">Form (son 10)</div><div class="frow"><span>${esc(m.ev)}</span><div class="form">${fbadge(m.form?.ev)}</div></div>
        <div class="frow"><span>${esc(m.dep)}</span><div class="form">${fbadge(m.form?.dep)}</div></div></div>
        <div class="mkt"><div class="mkt-h">Son 10 maç ortalamaları</div><div class="cmp-t"><b>${esc(m.ev)}</b><b>${esc(m.dep)}</b></div>
        ${[["Attığı gol", "atilan_ort"], ["Yediği gol", "yenilen_ort"], ["2,5 Üst %", "ust25_yuzde"], ["KG Var %", "kg_var_yuzde"], ["Gol yemeden %", "gol_yemeden_yuzde"]].map(([l, k]) => cmpBar(l, m.ort?.ev?.[k], m.ort?.dep?.[k])).join("")}</div>`;
      const cc = need(m.kod, "cc", `card-corners/${m.kod}`);
      if (cc) {
        const av = (t) => { const ms = t?.m || []; const me = t?.n; let co = 0, n = 0, ca = 0;
          for (const g of ms) { const mine = g.h?.n === me ? g.h : g.a; if ((g.h?.c || 0) + (g.a?.c || 0) > 0) { co += mine?.c || 0; n++; } ca += (mine?.yc || 0) + (mine?.rc || 0); }
          return { co: n ? (co / n).toFixed(1) : null, ca: ms.length ? (ca / ms.length).toFixed(1) : null }; };
        const A = av(cc.h), B = av(cc.a);
        h += `<div class="mkt"><div class="mkt-h">Korner ve kart (son 6 maç ort.)</div>${cmpBar("Korner", A.co, B.co)}${cmpBar("Kart", A.ca, B.ca)}</div>`;
      }
      const rh = need(m.kod, "rh", `recent-matches/${m.kod}?matchHistoryType=0&isOnlyCurrentTournament=false`);
      const ra = need(m.kod, "ra", `recent-matches/${m.kod}?matchHistoryType=1&isOnlyCurrentTournament=false`);
      const hh = need(m.kod, "h2h", `recent-matches/${m.kod}?matchHistoryType=2&isOnlyCurrentTournament=false`);
      const list = (d, team) => !d ? (d === false ? nodata() : loading) : (d.m || []).slice(0, 8).map((g) => {
        const res = g.mr || "", me = team;
        return `<div class="rm"><span class="rd">${dt(g.t)}</span><span class="rl">${esc(g.l?.a || "")}</span>
          <span class="rt ${g.h?.n === me ? "me" : ""}">${esc(g.h?.n)}</span><b>${g.h?.rs ?? "–"} - ${g.a?.rs ?? "–"}</b><span class="rt ${g.a?.n === me ? "me" : ""}">${esc(g.a?.n)}</span>${res ? `<span class="fb ${res}">${res}</span>` : ""}</div>`; }).join("") || nodata();
      h += `<div class="mkt"><div class="mkt-h">Kafa kafaya</div>${list(hh, null)}</div>
        <div class="mkt"><div class="mkt-h">${esc(m.ev)} son maçlar</div>${list(rh, rh && rh.h?.n)}</div>
        <div class="mkt"><div class="mkt-h">${esc(m.dep)} son maçlar</div>${list(ra, ra && ra.a?.n)}</div>`;
    } else {
      const S = need(m.kod, "standings", `standings/${m.kod}?standingType=0&isLive=false`);
      if (S === null || S === undefined) return h + loading;
      if (!S || !(S.g || []).length) return h + nodata("Puan durumu yok.");
      const names = [m.ev, m.dep];
      for (const g of S.g) {
        h += `<div class="mkt"><div class="mkt-h">${esc(g.n || S.ss?.n || "Puan durumu")}</div><div class="tbl"><div class="tr th"><span>#</span><span>Takım</span><span>O</span><span>G</span><span>B</span><span>M</span><span>A</span><span>P</span></div>
          ${(g.t || []).map((r) => `<div class="tr ${names.some((n) => n && r.n && (r.n.includes(n) || n.includes(r.n))) ? "hl" : ""}"><span>${r.r}</span><span class="tn">${esc(r.n)}</span><span>${r.p}</span><span>${r.w}</span><span>${r.d}</span><span>${r.l}</span><span>${r.gd > 0 ? "+" : ""}${r.gd}</span><b>${r.pt}</b></div>`).join("")}</div></div>`;
      }
    }
    return h;
  }

  // --- Analiz ---
  function tabAnaliz(m) {
    const ins = need(m.kod, "ins", `bet-insights/${m.kod}`);
    if (!m.secenekler.length) return `<div class="mkt ai"><div class="mkt-h">🤖 Model yorumu</div><p>Bu maç günlük analiz listesinde değil (filtre: öncelikli ligler, yeterli veri). Model tahmini yok; iddaa'nın analiz notları aşağıda.</p></div>
      <div class="mkt"><div class="mkt-h">Akıllı analiz notları <span class="mkt-s">iddaa istatistik</span></div>${ins === null || ins === undefined ? loading
        : !ins || !(ins.bi || []).length ? nodata("Bu maç için analiz notu yok.") : ins.bi.map((x) => `<div class="insight">💡 ${esc(x.f)}</div>`).join("")}</div>`;
    const best = m.secim ? m.secenekler.find((o) => o.p === m.secim.p && o.s === m.secim.s) : null;
    const top = [...m.secenekler].filter((o) => o.o != null).sort((a, b) => (b.g || 0) - (a.g || 0))[0];
    const lt = (m.lambda?.ev || 0) + (m.lambda?.dep || 0);
    const o25 = m.secenekler.find((o) => o.p === "AU_2.5");
    const lines = [];
    lines.push(`Model bu maçta toplam <b>${lt.toFixed(2)}</b> gol bekliyor (${esc(m.ev)} ${o2(m.lambda?.ev)}, ${esc(m.dep)} ${o2(m.lambda?.dep)}).`);
    if (o25) lines.push(`2,5 Üst olasılığı <b>${pct(o25.m)}</b>${o25.o ? ` (iddaa oranı ${odd(o25.o)}, piyasa ${pct(o25.pk)})` : ""}${o25.i != null ? `; bağımsız istatistik modeli ${pct(o25.i)} diyor` : ""}.`);
    const e = m.ort?.ev, d = m.ort?.dep;
    if (e && d) lines.push(`Son 10 maçta ${esc(m.ev)} maç başı ${e.atilan_ort ?? "–"} gol atıp ${e.yenilen_ort ?? "–"} yedi (2,5 Üst %${e.ust25_yuzde ?? "–"}); ${esc(m.dep)} ${d.atilan_ort ?? "–"} atıp ${d.yenilen_ort ?? "–"} yedi (2,5 Üst %${d.ust25_yuzde ?? "–"}).`);
    if (m.form?.ev && m.form?.dep) lines.push(`Form: ${esc(m.ev)} ${fbadge(m.form.ev.slice(0, 5))} · ${esc(m.dep)} ${fbadge(m.form.dep.slice(0, 5))} (son 5).`);
    if (m.risk?.length) lines.push(`Dikkat: ${m.risk.map(esc).join(" · ")}.`);
    let h = `<div class="mkt ai"><div class="mkt-h">🤖 Model yorumu</div>${lines.map((l) => `<p>${l}</p>`).join("")}
      ${best || top ? `<div class="pickbox"><span>Öne çıkan Üst tahmini</span><b>${esc((best || top).etiket || "")}</b><em>${odd((best || top).o)} · %${Math.round(100 * (best || top).m)} · güven ${Math.round((best || top).g)}</em></div>` : ""}</div>`;
    h += `<div class="mkt"><div class="mkt-h">Akıllı analiz notları <span class="mkt-s">iddaa istatistik</span></div>${ins === null || ins === undefined ? loading
      : !ins || !(ins.bi || []).length ? nodata("Bu maç için analiz notu yok.") : ins.bi.map((x) => `<div class="insight">💡 ${esc(x.f)}</div>`).join("")}</div>`;
    h += `<div class="mkt"><div class="mkt-h">Üst tahminleri</div>${[...m.secenekler].map((o) => oddRow(esc((o.etiket || o.s).replace(/(\d)\.5/, "$1,5")),
      `tahmin ${pct(o.m)}${o.g != null ? ` · güven ${Math.round(o.g)}` : ""}${o.d != null ? ` · değer ${o.d > 0 ? "+" : ""}${o.d.toFixed(2)}` : ""}`,
      rowBtn(`data-k="${esc(m.kod)}" data-p="${esc(o.p)}" data-s="${esc(o.s)}"`, o.o, isOn(m, o), o.o == null ? "yok" : m.baslamis ? odd(o.o) : null))).join("")}</div>
      <div class="lodds-note">Bu yorumlar istatistiksel tahmindir, sonuç garantisi vermez.</div>`;
    return h;
  }
  function hideDetail() { $("#sheet").classList.add("hidden"); document.body.style.overflow = ""; curKod = null; clearTimeout(evTimer); evTimer = null; clearTimeout(espnTimer); espnTimer = null; }
  function closeDetail() { if (history.state && history.state.detay) history.back(); else hideDetail(); }

  // ---------- çizim ----------
  function render(keepScroll) {
    if (!DATA) return;
    const y = window.scrollY;
    $("#sub").textContent = `${DATA.tarih} · oranlar ${(DATA.oran_zamani || "").slice(11, 16)}`;
    const b = $("#banner");
    b.classList.toggle("hidden", live);
    if (!live) b.innerHTML = `Geçmiş rapor görüntüleniyor (${esc(DATA.tarih)} ${esc((DATA.rapor_zamani || "").slice(11, 16))}). Geçmiş sekmesinden güncele dönebilirsin.`;
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x.dataset.tab === tab));
    if (tab === "gecmis") { vGecmis(); return; }
    if (tab === "mac") { tab = "bulten"; bday = "analiz"; }
    view.innerHTML = tab === "secim" ? vSecim() : tab === "bulten" ? vBulten() : tab === "canli" ? vCanli() : tab === "fav" ? vFav() : vKupon();
    if (keepScroll) window.scrollTo(0, y);
    if (curKod && byKod(curKod)) drawTab(byKod(curKod));
    paintLive();
    if (tab === "kupon") paintKupon();
  }
  let toastT;
  function toast(t) { const el = $("#toast"); el.textContent = t; el.classList.remove("hidden"); clearTimeout(toastT); toastT = setTimeout(() => el.classList.add("hidden"), 1800); }

  // ---------- olaylar ----------
  document.addEventListener("click", (e) => {
    const t = e.target.closest("button,a,[data-open]");
    if (!t) { if (e.target.id === "sheet") closeDetail(); return; }
    const d = t.dataset;
    if (d.tab) { tab = d.tab; window.scrollTo(0, 0); render(); if (tab === "canli") { fetchLive(); fetchOdds(); } if (tab === "kupon") fetchKuponOdds(); else { clearTimeout(kTimer); kTimer = null; } return; }
    if (d.dtab) { dTab = d.dtab; document.querySelectorAll(".dtab").forEach((b) => b.classList.toggle("on", b.dataset.dtab === dTab)); drawTab(byKod(curKod)); $("#sheetBody").scrollTop = 0; return; }
    if (d.dsub) { const [g, id] = d.dsub.split("|"); dSub[g] = id; drawTab(byKod(curKod)); return; }
    if (d.lk) {
      e.stopPropagation(); const m = byKod(d.lk); const z = m && (liveOvers(m) || []).find((q) => q.p === d.lp);
      if (m && z) {
        const cur = kupon[m.kod];
        if (cur && cur.p === z.p) { delete kupon[m.kod]; toast("Kupondan çıkarıldı"); }
        else { kupon[m.kod] = { p: z.p, s: "Üst", o: z.o, m: z.m ?? z.pk ?? 0, pk: z.pk, mbs: m.mbs, mac: `${m.ev} – ${m.dep}`, pa: z.pa, saat: m.saat };
               toast(`Canlı oran kupona eklendi · ${odd(z.o)}`); }
        saveKupon(); render(true);
      }
      return;
    }
    if (d.mk) { e.stopPropagation(); const [k, t, st, sov, ...rest] = d.mk.split("|"); genericToggle(k, +t, +st, sov, rest.join("|")); return; }
    if (d.mcat) { mcatSel = d.mcat; paintMarkets(); return; }
    if (d.bday) { bday = d.bday; bshow = 60; window.scrollTo(0, 0); render(); return; }
    if (d.more) { bshow += 60; render(true); return; }
    if (d.fav) { e.stopPropagation(); toggleFav(d.fav); render(true);
      document.querySelectorAll("[data-favd]").forEach((el) => { const m = byKod(el.dataset.favd); if (m) el.innerHTML = favBtn(m); }); return; }
    if (d.k) { e.stopPropagation(); const m = byKod(d.k); const o = opt(m, d.p, d.s); if (m && o) toggle(m, o); return; }
    if (d.open) { openDetail(d.open); return; }
    if (d.close) { closeDetail(); return; }
    if (d.mt) { curMt = d.mt; if (curKod) drawDetail(byKod(curKod)); return; }
    if (d.lig) { lig = d.lig; render(); return; }
    if (d.del) { delete kupon[d.del]; saveKupon(); render(true); return; }
    if (t.id === "kcopy") { copyText(kuponText()).then((ok) => toast(ok ? "📋 Kupon panoya kopyalandı" : "Kopyalanamadı; aşağıdaki listeyi elle seçebilirsin")); return; }
    if (d.kupd) { const c = currentOdd(d.kupd, kupon[d.kupd]); if (c && c.o) { kupon[d.kupd].o = c.o; saveKupon(); toast("Oran güncellendi"); render(true); } return; }
    if (t.id === "clear") { kupon = {}; saveKupon(); render(); return; }
    if (d.hazir !== undefined) {
      const c = DATA.kuponlar[+d.hazir];
      c.secimler.forEach((k) => { const m = byKod(k); const p = DATA.ozet.find((z) => z.kod === k); const o = m && p && opt(m, p.p, p.s);
        if (o) kupon[k] = { p: o.p, s: o.s, o: o.o, m: o.m, pk: o.pk, mbs: o.mbs || m.mbs, mac: `${m.ev} – ${m.dep}`, pa: o.pa, saat: m.saat }; });
      saveKupon(); toast(`${c.ad} kupona eklendi`); render(true); return;
    }
    if (d.hist) { e.preventDefault(); tab = "secim"; load("../" + d.hist, false); return; }
    if (d.latest) { e.preventDefault(); tab = "secim"; load("../data.json", true); return; }
    if (t.id === "refresh") { load("../data.json", true); return; }
  });
  document.addEventListener("change", (e) => { if (e.target.id === "blig") { blig = e.target.value; bshow = 60; render(); } });
  document.addEventListener("input", (e) => {
    if (e.target.id === "bq") { bq = e.target.value; bshow = 60; const pos = e.target.selectionStart; render(true); const el = $("#bq"); if (el) { el.focus(); el.setSelectionRange(pos, pos); } return; }
    if (e.target.id === "q") { q = e.target.value; const pos = e.target.selectionStart; render(); const el = $("#q"); el.focus(); el.setSelectionRange(pos, pos); }
    if (e.target.id === "stake") { const v = Math.max(1, Number(e.target.value) || 1); LS.set("stake", v);
      clearTimeout(window.__st); window.__st = setTimeout(() => { render(true); const el = $("#stake"); if (el) { el.focus(); el.setSelectionRange?.(9, 9); } }, 500); }
  });
  // Uygulama arka plandan 10 dakikadan sonra dönerse güncel raporu kendiliğinden çek
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if (live && Date.now() - lastLoad > 10 * 60 * 1000) load("../data.json", true);
    else { fetchLive(); fetchOdds(); if (curKod) { fetchEvent(curKod); fetchEspn(curKod); } if (tab === "kupon") fetchKuponOdds(); }   // ekrana dönünce hemen güncelle
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });
  // Android geri tuşu: önce detay panelini kapat
  window.addEventListener("popstate", () => hideDetail());

  saveKupon();
  saveFav();
  load("../data.json", true);
})();
