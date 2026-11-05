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

  let DATA = null, live = true, tab = "secim", lig = "Tümü", q = "";
  let kupon = LS.get("kupon", {}); // {kod: {p,s,o,m,pk,mbs,mac,pa,tarih}}

  // ---------- veri ----------
  async function load(url, isLive) {
    const btn = $("#refresh"); btn.classList.add("spin");
    try {
      const r = await fetch(url + (url.includes("?") ? "&" : "?") + "t=" + Date.now(), { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      DATA = await r.json(); live = isLive;
      if (isLive) LS.set("son_veri", DATA);
      cleanKupon();
      render();
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
      if (!m || new Date(m.baslama).getTime() < now) delete kupon[k];
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
    const best = m.secim && m.secim.p === o.p && m.secim.s === o.s;
    return `<button class="odd ${isOn(m, o) ? "on" : ""} ${best ? "best" : ""} ${extraCls}" data-k="${esc(m.kod)}" data-p="${esc(o.p)}" data-s="${esc(o.s)}">
      <span class="n">${esc(label)}</span><span class="o">${odd(o.o)}</span><span class="p">${pct(o.m)}</span></button>`;
  }
  function ring(g) {
    const c = g >= 70 ? "var(--acc)" : g >= 60 ? "#9be15d" : g >= 50 ? "var(--amber)" : "var(--red)";
    return `<div class="ring" style="--v:${g};--c:${c}"><b>${Math.round(g)}<small>güven</small></b></div>`;
  }
  function valChip(d) { return `<span class="chip ${d > 0 ? "pos" : "neg"}">değer ${d > 0 ? "+" : ""}${d.toFixed(2)}</span>`; }
  const teams = (m) => `<div class="teams">${esc(m.ev)}<span class="vs">–</span>${esc(m.dep)}</div>`;
  const meta = (m) => `<div class="meta"><span class="lig">${esc(m.lig)}</span><span>${esc(m.saat)} · MBS ${esc(m.mbs)}</span></div>`;

  // ---------- sekmeler ----------
  function vSecim() {
    const picks = DATA.ozet.map((p) => ({ m: byKod(p.kod), o: null, p })).filter((x) => x.m);
    picks.forEach((x) => (x.o = opt(x.m, x.p.p, x.p.s)));
    let h = `<div class="hero"><div class="big">${picks.length}</div><p><b>Günün seçimleri</b><br>Güven skoru ≥55, maç başına en fazla 1 seçim. Oranlar ${esc((DATA.oran_zamani || "").slice(11, 16))} itibarıyla.</p></div>`;
    for (const { m, o } of picks) {
      if (!o) continue;
      h += `<div class="card tap" data-open="${esc(m.kod)}">${meta(m)}${teams(m)}
        <div class="pick">${ring(o.g)}<div class="lbl"><div class="mk">${esc(o.pa)}</div><div class="sel">${esc(nice(o.s))}</div></div>${oddBtn(m, o, "oran")}</div>
        <div class="stats"><span class="chip">tahmin ${pct(o.m)}</span><span class="chip">istatistik ${pct(o.i)}</span>${valChip(o.d)}
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

  function vMac() {
    const ligs = ["Tümü", ...new Set(DATA.maclar.map((m) => m.lig))];
    let h = `<input class="search" id="q" placeholder="Takım ara…" value="${esc(q)}">
      <div class="filters">${ligs.map((l) => `<button class="fchip ${l === lig ? "on" : ""}" data-lig="${esc(l)}">${esc(l)}</button>`).join("")}</div>`;
    const ql = q.toLocaleLowerCase("tr");
    const list = DATA.maclar.filter((m) => (lig === "Tümü" || m.lig === lig) && (!ql || (m.ev + " " + m.dep).toLocaleLowerCase("tr").includes(ql)));
    let last = "";
    for (const m of list) {
      if (m.lig !== last) { h += `<div class="lgroup">${esc(m.lig)}</div>`; last = m.lig; }
      const g = (p, s) => opt(m, p, s);
      h += `<div class="card mrow"><div class="tap" data-open="${esc(m.kod)}">${meta(m)}${teams(m)}</div>
        <div class="glbl"><span>Maç Sonucu</span><span></span><span>2.5 Alt/Üst</span></div>
        <div class="grid">${oddBtn(m, g("MS", "1"), "1")}${oddBtn(m, g("MS", "0"), "X")}${oddBtn(m, g("MS", "2"), "2")}<div class="sep"></div>
        ${oddBtn(m, g("AU_2.5", "Alt"), "Alt")}${oddBtn(m, g("AU_2.5", "Üst"), "Üst")}</div>
        <button class="more" data-open="${esc(m.kod)}">+${m.secenekler.length} seçenek · detay ve istatistik</button></div>`;
    }
    if (!list.length) h += `<div class="empty">Eşleşen maç yok.</div>`;
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
        <div class="t">tahmin ${pct(s.m)} · MBS ${esc(s.mbs)}</div></div><div class="o">${odd(s.o)}</div></div>`;
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
    curMt = m.secim ? (MT.find(([, , f]) => f && f(m.secim.p))?.[0] || "MS") : "MS";
    drawDetail(m);
    $("#sheet").classList.remove("hidden"); document.body.style.overflow = "hidden";
    $("#sheetBody").scrollTop = 0;
    history.pushState({ detay: kod }, "");   // Android geri tuşu paneli kapatsın
  }
  function drawDetail(m) {
    const has = MT.filter(([id, , f]) => m.secenekler.some((o) => (f ? f(o.p) : !MT.some(([, , g]) => g && g(o.p)))));
    if (!has.find(([id]) => id === curMt)) curMt = has[0]?.[0];
    const f = MT.find(([id]) => id === curMt)?.[2];
    const opts = m.secenekler.filter((o) => (f ? f(o.p) : !MT.some(([, , g]) => g && g(o.p))));
    const groups = {}; opts.forEach((o) => (groups[o.pa] = groups[o.pa] || []).push(o));
    const bar = (cls, v, l) => `<div>${l} ${pct(v)}</div><div class="bar ${cls}"><i style="width:${v == null ? 0 : Math.min(100, 100 * v)}%"></i></div>`;
    const fb = (s) => [...(s || "")].map((c) => `<span class="fb ${c}">${c}</span>`).join("");
    const o2 = (x) => (x == null ? "–" : Number(x).toFixed(2));
    const pr = (p) => (p ? `${p.sira}. · ${p.puan} puan` : "–");
    let h = `<div class="sh-top"><div class="grab"></div><div class="sh-head"><div>${meta(m)}<h3>${esc(m.ev)} – ${esc(m.dep)}</h3></div>
      <button class="close" data-close="1" aria-label="Kapat">✕</button></div>
      <div class="mtabs">${has.map(([id, ad]) => `<button class="mt ${id === curMt ? "on" : ""}" data-mt="${id}">${ad}</button>`).join("")}</div></div>
      <div class="legend"><span><i style="background:var(--acc)"></i>tahmin</span><span><i style="background:var(--blue)"></i>pazar fiyatı</span><span><i style="background:var(--amber)"></i>istatistik</span></div>`;
    for (const [pa, os] of Object.entries(groups)) {
      h += `<div class="sec" style="margin-top:10px">${esc(pa)}</div><div class="optgrid">`;
      for (const o of os) h += `<div class="opt">${oddBtn(m, o, nice(o.s))}<div class="bars">${bar("", o.m, "tahmin")}${bar("mk", o.pk, "pazar")}${bar("st", o.i, "istatistik")}</div>
        <div style="font-size:.66rem;color:${o.d > 0 ? "#7ff0a8" : "var(--muted)"}">değer ${o.d > 0 ? "+" : ""}${o.d.toFixed(2)} · güven ${Math.round(o.g)}${o.sup ? " · <span style='color:#ffcf70'>şüpheli</span>" : ""}</div></div>`;
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
  }
  function hideDetail() { $("#sheet").classList.add("hidden"); document.body.style.overflow = ""; curKod = null; }
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
    view.innerHTML = tab === "secim" ? vSecim() : tab === "mac" ? vMac() : vKupon();
    if (keepScroll) window.scrollTo(0, y);
    if (curKod && byKod(curKod)) drawDetail(byKod(curKod));
  }
  let toastT;
  function toast(t) { const el = $("#toast"); el.textContent = t; el.classList.remove("hidden"); clearTimeout(toastT); toastT = setTimeout(() => el.classList.add("hidden"), 1800); }

  // ---------- olaylar ----------
  document.addEventListener("click", (e) => {
    const t = e.target.closest("button,a,[data-open]");
    if (!t) { if (e.target.id === "sheet") closeDetail(); return; }
    const d = t.dataset;
    if (d.tab) { tab = d.tab; window.scrollTo(0, 0); render(); return; }
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
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });
  // Android geri tuşu: önce detay panelini kapat
  window.addEventListener("popstate", () => hideDetail());

  saveKupon();
  load("../data.json", true);
})();
