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
  const LIVE_FAST = 1000;      // canlı maç varken: her yanıttan 1 sn sonra yeni istek (~12 KB, sıkıştırılmış)
  const LIVE_SOON = 15000;     // maç başlamak üzereyken
  const LIVE_IDLE = 5 * 60e3;  // canlı maç yokken

  // ---------- canlı skor (telefondan doğrudan; iddaa canlı sonuç servisi) ----------
  const LIVE_URL = (d) => `https://statisticsv2.iddaa.com/live-results?sportId=1&date=${d}`;
  async function fetchLive() {
    if (!DATA || !live || liveBusy) return;
    liveBusy = true;
    try {
      const r = await fetch(LIVE_URL(DATA.tarih), { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const j = (await r.json()).data || {};
      const sc = j.sc || {}, out = {};
      for (const e of j.events || []) {
        const k = String(e.eventId), x = sc[k];
        if (!x || !e.phase) continue;           // phase 0 = başlamadı
        out[k] = { phase: e.phase, s: x.s, min: x.min, h: x.ht?.r ?? 0, a: x.at?.r ?? 0,
                   hh: x.ht?.ht ?? null, ha: x.at?.ht ?? null, hco: x.ht?.co, aco: x.at?.co,
                   hrc: x.ht?.rc || 0, arc: x.at?.rc || 0 };
      }
      LIVE = out; liveAt = Date.now();
      paintLive();
      if (!oddsTimer && DATA.maclar.some((m) => LIVE[m.kod]?.phase === 1)) fetchOdds();
      if (curKod && !evTimer && !evBusy && LIVE[curKod]?.phase === 1) fetchEvent(curKod);
    } catch (e) { /* ağ hatası: bir sonraki turda tekrar dener */ }
    liveBusy = false;
    scheduleLive();
  }
  function scheduleLive() {
    clearTimeout(liveTimer);
    if (!DATA || !live) return;
    const now = Date.now();
    const anyLive = DATA.maclar.some((m) => LIVE[m.kod]?.phase === 1);   // yalnızca bizim maçlar
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
      const mine = new Set(DATA.maclar.map((m) => m.kod));
      if (!d.isdiff) LODDS = {};
      for (const e of d.events || []) {          // değişen maç, bütün pazarlarıyla gelir
        const k = String(e.i);
        if (e.sid === 1 && mine.has(k)) LODDS[k] = { m: e.m || [], at: Date.now() };
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
    const anyLive = DATA.maclar.some((m) => LIVE[m.kod]?.phase === 1);
    oddsTimer = setTimeout(() => { if (document.visibilityState === "visible") fetchOdds(); else scheduleOdds(); },
                           anyLive ? ODDS_EVERY : 60e3);
  }
  // Detay paneli açıkken: o maçın BÜTÜN canlı çizgileri (sportsbook/event/<kod>, ~3 KB), 2 sn'de bir
  const EVENT_URL = (k) => `https://sportsbookv2.iddaa.com/sportsbook/event/${k}`;
  let EVODDS = {}, evTimer = null, evBusy = false;
  async function fetchEvent(kod) {
    clearTimeout(evTimer); evTimer = null;
    if (!DATA || !live || evBusy || curKod !== kod || LIVE[kod]?.phase !== 1) return;
    evBusy = true;
    try {
      const r = await fetch(EVENT_URL(kod), { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      let e = (await r.json()).data; if (Array.isArray(e)) e = e[0];
      if (e) { EVODDS[kod] = { m: e.m || [], at: Date.now() }; oddsAt = Date.now(); paintLive(); }
    } catch (e) { /* bir sonraki turda tekrar dener */ }
    evBusy = false;
    if (curKod === kod && LIVE[kod]?.phase === 1)
      evTimer = setTimeout(() => { if (document.visibilityState === "visible") fetchEvent(kod); else evTimer = setTimeout(() => fetchEvent(kod), 3000); }, 2000);
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
    const zs = liveOvers(m) || [];
    if (!zs.length) return `<div class="sec">Canlı Üst oranları</div><div class="lodds-note">${LODDS[kod] ? "Şu an açık canlı Üst oranı yok (askıda olabilir)." : "Yükleniyor…"}</div>`;
    const bar = (cls, v, l) => `<div>${l} ${pct(v)}</div><div class="bar ${cls}"><i style="width:${v == null ? 0 : Math.min(100, 100 * v)}%"></i></div>`;
    return `<div class="sec">Canlı Üst oranları <span style="font-size:.7rem;color:var(--muted);font-weight:500">iddaa · ${new Date(oddsAt).toLocaleTimeString("tr-TR", { timeZone: "Europe/Istanbul" })}</span></div><div class="optgrid">${zs.map((z) => `<div class="opt">${liveOddBtn(m, z)}
      <div class="bars">${bar("", z.m, "canlı tahmin")}${bar("mk", z.pk, "piyasa")}</div>
      <div style="font-size:.66rem;color:${z.m != null && z.m * z.o > 1 ? "#7ff0a8" : "var(--muted)"}">${z.m == null ? "" : `değer ${z.m * z.o - 1 > 0 ? "+" : ""}${(z.m * z.o - 1).toFixed(2)}`}</div></div>`).join("")}</div>
      <div class="lodds-note">Canlı tahmin: maç öncesi gol beklentisinin kalan süreye düşen payı ve mevcut skorla hesaplanır (kırmızı kart, tempo gibi canlı etkenleri bilmez).</div>`;
  }

  // Maç durumu etiketi
  function liveTag(kod, big) {
    const x = LIVE[kod];
    if (!x) return "";
    const sc = `${x.h} - ${x.a}`;
    const red = (n) => (n ? `<i class="rc">${n > 1 ? n : ""}</i>` : "");
    if (x.phase === 2) return `<span class="lv end">MS <b>${sc}</b></span>`;
    const t = x.s === 4 ? "İY" : `${x.min ?? ""}'`;
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
    document.querySelectorAll("[data-ldet]").forEach((el) => (el.innerHTML = liveDetail(el.dataset.ldet)));
    document.querySelectorAll("[data-pre]").forEach((el) => el.classList.toggle("pre-live", LIVE[el.dataset.pre]?.phase === 1));
    const mine = DATA.maclar.filter((m) => LIVE[m.kod]?.phase === 1).length;
    const el = $("#livecount"); if (el) { el.textContent = mine ? `● ${mine} canlı` : ""; el.classList.toggle("hidden", !mine); }
  }
  function liveBox(kod) {
    const x = LIVE[kod]; if (!x) return "";
    const st = x.phase === 2 ? "Maç sonu" : x.s === 4 ? "Devre arası" : `${x.min}. dakika`;
    return `<div class="lbox ${x.phase === 1 ? "on" : ""}"><div class="lst">${x.phase === 1 ? '<i class="dot"></i>' : ""}${st}</div>
      <div class="lsc">${x.h} <span>-</span> ${x.a}</div>
      <div class="lmeta">İY ${x.hh ?? "–"}-${x.ha ?? "–"}${x.hco != null ? ` · korner ${x.hco}-${x.aco}` : ""}${x.hrc || x.arc ? ` · kırmızı ${x.hrc}-${x.arc}` : ""}</div>
      <div class="lmeta" style="opacity:.7">güncelleme ${new Date(liveAt).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Istanbul" })}</div></div>`;
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
      if (isLive) toast("Güncel rapor yüklendi");
    } catch (e) {
      const cached = LS.get("son_veri", null);
      if (cached && isLive) { DATA = cached; live = true; render(); toast("Çevrimdışı: son kaydedilen rapor gösteriliyor"); }
      else view.innerHTML = `<div class="empty"><p>Rapor yüklenemedi.<br>İnternet bağlantınızı kontrol edip yenileyin.</p></div>`;
    } finally { btn.classList.remove("spin"); }
  }
  const byKod = (k) => DATA.maclar.find((m) => m.kod === k);
  const opt = (m, p, s) => m.secenekler.find((o) => o.p === p && o.s === s);

  function cleanKupon() { // başlamış maçları ve farklı günün seçimlerini kupondan çıkar
    const now = Date.now();
    for (const k of Object.keys(kupon)) {
      const m = byKod(k);
      if (!live) continue;
      if (!m || now - new Date(m.baslama).getTime() > 6 * 3600e3) delete kupon[k];   // maç bittikten sonra da sonucu görünsün
    }
    saveKupon();
  }
  function saveKupon() { LS.set("kupon", kupon); const n = Object.keys(kupon).length; const b = $("#kcount"); b.textContent = n; b.classList.toggle("hidden", !n); }

  function toggle(m, o) {
    const cur = kupon[m.kod];
    if (cur && cur.p === o.p && cur.s === o.s) { delete kupon[m.kod]; toast("Kupondan çıkarıldı"); }
    else {
      kupon[m.kod] = { p: o.p, s: o.s, o: o.o, m: o.m, pk: o.pk, mbs: o.mbs || m.mbs, mac: `${m.ev} – ${m.dep}`, pa: o.pa, saat: m.saat };
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
  const meta = (m) => `<div class="meta"><span class="lig">${esc(m.lig)}</span><span><span data-live="${esc(m.kod)}">${liveTag(m.kod)}</span> ${esc(m.saat)} · MBS ${esc(m.mbs)}</span></div>`;

  // ---------- sekmeler ----------
  function vSecim() {
    const picks = DATA.ozet.map((p) => ({ m: byKod(p.kod), o: null, p })).filter((x) => x.m);
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
    h += `<div class="note">${esc(DATA.not)}</div><div class="disc">${esc(DATA.uyari)}</div>`;
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
    const ks = Object.keys(FAV);
    if (!ks.length) return `<div class="empty"><div style="font-size:2.6rem;opacity:.5">☆</div>
      <p>Henüz favori maçın yok.<br>Takip etmek istediğin maçın yanındaki <b>☆</b> yıldıza dokun.</p></div>`;
    const here = DATA.maclar.filter((m) => FAV[m.kod]);
    const liveN = here.filter((m) => LIVE[m.kod]?.phase === 1).length;
    let h = `<div class="h"><h2>★ Favorilerim</h2><span>${ks.length} maç${liveN ? ` · <b style="color:#ff8a85">${liveN} canlı</b>` : ""}</span></div>`;
    // canlı olanlar üstte, sonra başlama saatine göre
    here.sort((a, b) => ((LIVE[b.kod]?.phase === 1) - (LIVE[a.kod]?.phase === 1)) || a.baslama.localeCompare(b.baslama));
    for (const m of here) h += matchRow(m);
    const other = ks.filter((k) => !byKod(k));
    if (other.length) {
      h += `<div class="lgroup">Bu raporda olmayan favoriler</div>`;
      for (const k of other) { const f = FAV[k];
        h += `<div class="card"><div class="meta"><span class="lig">${esc(f.lig)}</span><span>${esc(f.tarih)} ${esc(f.saat)}</span></div>
          <div class="teams"><span>${esc(f.ev)}<span class="vs">–</span>${esc(f.dep)}</span><button class="fav on" data-fav="${esc(k)}">★</button></div></div>`; }
    }
    return h + `<div class="disc">Favoriler yalnızca bu cihazda saklanır; maçtan 2 gün sonra kendiliğinden silinir.</div>`;
  }

  function vMac() {
    const ligs = ["Tümü", "Canlı", ...new Set(DATA.maclar.map((m) => m.lig))];
    let h = `<input class="search" id="q" placeholder="Takım ara…" value="${esc(q)}">
      <div class="filters">${ligs.map((l) => `<button class="fchip ${l === lig ? "on" : ""}" data-lig="${esc(l)}">${esc(l)}</button>`).join("")}</div>`;
    const ql = q.toLocaleLowerCase("tr");
    const list = DATA.maclar.filter((m) => (lig === "Tümü" || m.lig === lig || (lig === "Canlı" && LIVE[m.kod]?.phase === 1)) && (!ql || (m.ev + " " + m.dep).toLocaleLowerCase("tr").includes(ql)));
    let last = "";
    for (const m of list) {
      if (m.lig !== last) { h += `<div class="lgroup">${esc(m.lig)}</div>`; last = m.lig; }
      h += matchRow(m);
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
        <div class="info"><div class="t">${esc(s.saat)} · ${esc(s.mac)}</div><div class="s">${esc(s.pa)}: ${esc(nice(s.s))}</div>
        <div class="t">tahmin ${pct(s.m)} · MBS ${esc(s.mbs)} <span data-live="${esc(k)}">${liveTag(k)}</span> <span data-ps="${esc(k)}|${esc(s.p)}">${pickState(k, s.p)}</span></div></div><div class="o">${odd(s.o)}</div></div>`;
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
      </div><button class="btn" id="clear">Kuponu temizle</button>
      <div class="disc">Kupon yalnızca bu cihazda tutulur; bahis yapılmaz. ${esc(DATA.uyari)}</div>`;
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
    curKod = kod;
    drawDetail(m);
    $("#sheet").classList.remove("hidden"); document.body.style.overflow = "hidden";
    $("#sheetBody").scrollTop = 0;
    history.pushState({ detay: kod }, "");   // Android geri tuşu paneli kapatsın
    fetchEvent(kod);
  }
  function drawDetail(m) {
    const ord = (o) => (DATA.pazarlar || []).findIndex((z) => z.pazar === o.p && z.secenek === o.s);
    const groups = { "Maç öncesi Üst tahminleri": [...m.secenekler].sort((a, b) => ord(a) - ord(b)) };
    const bar = (cls, v, l) => `<div>${l} ${pct(v)}</div><div class="bar ${cls}"><i style="width:${v == null ? 0 : Math.min(100, 100 * v)}%"></i></div>`;
    const fb = (s) => [...(s || "")].map((c) => `<span class="fb ${c}">${c}</span>`).join("");
    const o2 = (x) => (x == null ? "–" : Number(x).toFixed(2));
    const pr = (p) => (p ? `${p.sira}. · ${p.puan} puan` : "–");
    let h = `<div class="sh-top"><div class="grab"></div><div class="sh-head"><div>${meta(m)}<h3>${esc(m.ev)} – ${esc(m.dep)}</h3></div>
      <button class="close" data-close="1" aria-label="Kapat">✕</button></div>
</div>
      <div data-livebox="${esc(m.kod)}">${liveBox(m.kod)}</div>
      <div data-ldet="${esc(m.kod)}">${liveDetail(m.kod)}</div>
      <div class="legend"><span><i style="background:var(--acc)"></i>tahmin</span><span><i style="background:var(--blue)"></i>pazar fiyatı</span><span><i style="background:var(--amber)"></i>istatistik</span></div>`;
    for (const [pa, os] of Object.entries(groups)) {
      h += `<div class="sec" style="margin-top:10px">${esc(pa)}</div><div class="optgrid">`;
      for (const o of os) h += `<div class="opt">${oddBtn(m, o, o.etiket || o.s)}<div class="bars">${bar("", o.m, "tahmin")}${bar("mk", o.pk, "pazar")}${bar("st", o.i, "istatistik")}</div>
        <div style="font-size:.66rem;color:${o.d > 0 ? "#7ff0a8" : "var(--muted)"}">${o.o == null ? "iddaa bu pazarı açmamış" : `değer ${o.d > 0 ? "+" : ""}${o.d.toFixed(2)} · güven ${Math.round(o.g)}`}${o.sup ? " · <span style='color:#ffcf70'>şüpheli</span>" : ""}</div></div>`;
      h += `</div>`;
    }
    h += `<div class="sec">En olası skorlar</div><div class="scores">${(m.skorlar || []).map((s) => `<div class="score"><b>${esc(s.skor)}</b><small>${pct(s.olasilik, 1)}</small></div>`).join("")}
      <div class="score"><b>${o2(m.lambda?.ev)} : ${o2(m.lambda?.dep)}</b><small>beklenen gol</small></div></div>
      <div class="sec">Form (son 10)</div><div style="font-size:.8rem;color:var(--muted);margin-bottom:4px">${esc(m.ev)}</div><div class="form">${fb(m.form?.ev)}</div>
      <div style="font-size:.8rem;color:var(--muted);margin:8px 0 4px">${esc(m.dep)}</div><div class="form">${fb(m.form?.dep)}</div>
      <div class="sec">Son 10 maç ortalamaları</div><div class="kv"><span class="k"></span><div><b>${esc(m.ev)}</b></div><div><b>${esc(m.dep)}</b></div>
      ${[["Atılan gol", "atilan_ort", 0], ["Yenilen gol", "yenilen_ort", 0], ["2.5 Üst %", "ust25_yuzde", 1], ["KG Var %", "kg_var_yuzde", 1], ["Gol yemeden %", "gol_yemeden_yuzde", 1]]
        .map(([l, k, p]) => `<span class="k">${l}</span><div>${m.ort?.ev?.[k] ?? "–"}${p && m.ort?.ev?.[k] != null ? "%" : ""}</div><div>${m.ort?.dep?.[k] ?? "–"}${p && m.ort?.dep?.[k] != null ? "%" : ""}</div>`).join("")}
      ${m.puan?.turnuva ? `<span class="k">${esc(m.puan.turnuva)}</span><div>${pr(m.puan.ev)}</div><div>${pr(m.puan.dep)}</div>` : ""}</div>
      <div class="sec">Kafa kafaya</div><div style="font-size:.84rem">${m.h2h?.length ? m.h2h.map((x) => `<div>${esc(x.tarih)} · ${esc(x.skor)} <span style="color:var(--muted)">(İY ${esc(x.iy)})</span></div>`).join("") : "<span style='color:var(--muted)'>Veri yok</span>"}</div>
      <div class="sec">Haberler (son 72 saat)</div><div class="news">${m.haberler?.length ? m.haberler.map((n) => `<a href="${esc(safeUrl(n.l))}" target="_blank" rel="noopener">${esc(n.b)}<small>${esc(n.k)} · ${esc((n.t || "").slice(0, 16).replace("T", " "))}${(n.kat || []).filter((c) => c !== "kadro" && c !== "onizleme").length ? " · " + esc(n.kat.join(", ")) : ""}</small></a>`).join("") : "<span style='color:var(--muted);font-size:.84rem'>İlgili haber bulunamadı</span>"}</div>
      ${(m.risk || []).length ? `<div class="note">⚠ Risk: ${m.risk.map(esc).join(" · ")}</div>` : ""}
      <div class="note">Veri kalitesi ${m.veri_kalitesi} · İstatistik modelinin beklenen golü ${o2(m.ist_lambda?.ev)} : ${o2(m.ist_lambda?.dep)} · maç kodu ${esc(m.kod)}</div>`;
    $("#sheetBody").innerHTML = h;
    paintLive();
  }
  function hideDetail() { $("#sheet").classList.add("hidden"); document.body.style.overflow = ""; curKod = null; clearTimeout(evTimer); evTimer = null; }
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
    view.innerHTML = tab === "secim" ? vSecim() : tab === "mac" ? vMac() : tab === "fav" ? vFav() : vKupon();
    if (keepScroll) window.scrollTo(0, y);
    if (curKod && byKod(curKod)) drawDetail(byKod(curKod));
    paintLive();
  }
  let toastT;
  function toast(t) { const el = $("#toast"); el.textContent = t; el.classList.remove("hidden"); clearTimeout(toastT); toastT = setTimeout(() => el.classList.add("hidden"), 1800); }

  // ---------- olaylar ----------
  document.addEventListener("click", (e) => {
    const t = e.target.closest("button,a,[data-open]");
    if (!t) { if (e.target.id === "sheet") closeDetail(); return; }
    const d = t.dataset;
    if (d.tab) { tab = d.tab; window.scrollTo(0, 0); render(); return; }
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
    if (d.fav) { e.stopPropagation(); toggleFav(d.fav); render(true); return; }
    if (d.k) { e.stopPropagation(); const m = byKod(d.k); const o = opt(m, d.p, d.s); if (m && o) toggle(m, o); return; }
    if (d.open) { openDetail(d.open); return; }
    if (d.close) { closeDetail(); return; }
    if (d.mt) { curMt = d.mt; if (curKod) drawDetail(byKod(curKod)); return; }
    if (d.lig) { lig = d.lig; render(); return; }
    if (d.del) { delete kupon[d.del]; saveKupon(); render(true); return; }
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
  document.addEventListener("input", (e) => {
    if (e.target.id === "q") { q = e.target.value; const pos = e.target.selectionStart; render(); const el = $("#q"); el.focus(); el.setSelectionRange(pos, pos); }
    if (e.target.id === "stake") { const v = Math.max(1, Number(e.target.value) || 1); LS.set("stake", v);
      clearTimeout(window.__st); window.__st = setTimeout(() => { render(true); const el = $("#stake"); if (el) { el.focus(); el.setSelectionRange?.(9, 9); } }, 500); }
  });
  // Uygulama arka plandan 10 dakikadan sonra dönerse güncel raporu kendiliğinden çek
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if (live && Date.now() - lastLoad > 10 * 60 * 1000) load("../data.json", true);
    else { fetchLive(); fetchOdds(); if (curKod) fetchEvent(curKod); }   // ekrana dönünce hemen güncelle
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });
  // Android geri tuşu: önce detay panelini kapat
  window.addEventListener("popstate", () => hideDetail());

  saveKupon();
  saveFav();
  load("../data.json", true);
})();
