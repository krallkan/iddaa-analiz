"""Adım 9: rapor (Markdown + JSON)."""
from __future__ import annotations

import json
import math
from pathlib import Path

DISCLAIMER = ("Bu analiz istatistiksel bir tahmindir, sonuç garantisi vermez. "
              "Kaybetmeyi göze alabileceğin miktarla oyna.")
OZET_MIN_GUVEN = 55
OZET_MAX = 10


def pct(x):
    return "veri yok" if x is None else f"%{100 * x:.1f}"


def ist_pct(r: dict) -> str:
    v = r.get("istatistik")
    return "-" if v is None else f"{100 * v:.1f}"


def num(x, f="{:.2f}"):
    return "veri yok" if x is None else f.format(x)


def _pick_summary(guven: dict, by_code: dict, min_guven: float = OZET_MIN_GUVEN) -> list[dict]:
    rows = []
    for code, rs in guven["maclar"].items():
        el = [r for r in rs if r["ozete_uygun"]]
        if el and el[0]["guven"] >= min_guven:
            alt = next((r for r in el[1:] if r["pazar"] != el[0]["pazar"]), None)
            rows.append({"mac_kodu": code, "mac": by_code[code], "secim": el[0], "alternatif": alt})
    rows.sort(key=lambda x: -x["secim"]["guven"])
    return rows[:OZET_MAX]


def _coupons(picks: list[dict]) -> dict:
    """MBS kuralı: kupondaki maç sayısı, kupondaki en yüksek MBS'den az olamaz."""
    def make(items, name):
        n = len(items)
        mbs = max(int(p["secim"]["mbs"] or 1) for p in items)
        pm = math.prod(p["secim"]["model"] for p in items)
        pk = math.prod(p["secim"]["piyasa"] for p in items)
        odd = math.prod(p["secim"]["oran"] for p in items)
        return {"ad": name, "mac_sayisi": n, "gereken_mbs": mbs, "mbs_uygun": n >= mbs,
                "secimler": [{"mac_kodu": p["mac_kodu"], "mac": f"{p['mac']['ev']} - {p['mac']['deplasman']}",
                              "secenek": f"{p['secim']['pazar_adi']}: {p['secim']['secenek']}",
                              "oran": p["secim"]["oran"], "model": p["secim"]["model"], "mbs": p["secim"]["mbs"]}
                             for p in items],
                "toplam_oran": round(odd, 2), "model_olasilik": pm, "piyasa_olasilik": pk,
                "beklenen_deger": round(pm * odd - 1, 3),
                "carpim_metni": " × ".join(f"%{100*p['secim']['model']:.0f}" for p in items) + f" ≈ %{100*pm:.0f}"}
    out = {}
    singles = [p for p in picks if int(p["secim"]["mbs"] or 1) == 1]
    if singles:
        out["dusuk_risk_tekli"] = make(singles[:1], "Düşük risk — tekli")
    if len(picks) >= 2:
        two = picks[:2]
        out["dusuk_risk_ikili"] = make(two, "Düşük risk — ikili")
    if len(picks) >= 3:
        out["dengeli"] = make(picks[:3], "Dengeli — 3'lü")
    for c in out.values():
        if not c["mbs_uygun"]:
            c["uyari"] = f"MBS {c['gereken_mbs']} — bu kupon {c['mac_sayisi']} maçla OYNANAMAZ"
    return out


def _form_line(s: dict) -> str:
    b = s["son10"]
    return (f"{b['form']} | atılan {num(b['atilan_ort'])} / yenilen {num(b['yenilen_ort'])} | "
            f"2.5Ü {pct(b['ust25_yuzde'] / 100 if b['ust25_yuzde'] is not None else None)} | "
            f"KG {pct(b['kg_var_yuzde'] / 100 if b['kg_var_yuzde'] is not None else None)} | "
            f"gol yemeden {pct(b['gol_yemeden_yuzde'] / 100 if b['gol_yemeden_yuzde'] is not None else None)} | "
            f"İY gol ort. {num(b['iy_gol_ort'])}")


def _block(s):
    return (f"{s['form'] or '-'} ({s['mac']} maç), atılan {num(s['atilan_ort'])}, yenilen {num(s['yenilen_ort'])}")


def match_detail(code: str, m: dict, st: dict, nw: dict | None, pr: dict, gv: list[dict],
                 pick: dict | None, alt: dict | None, deger_time: str, anc: dict | None = None) -> list[str]:
    L = [f"### {m['saat']} · {m['lig']} · {m['ev']} – {m['deplasman']} (kod {code}, MBS {m['mbs']})", ""]
    # Form
    L += ["**Form (son 10 maç, tüm turnuvalar — kaynak: iddaa istatistik)**", "",
          "| | Son 10 | İç saha son 5 | Dış saha son 5 | Son 7 gün maç | Puan sapması |",
          "|---|---|---|---|---|---|"]
    for side, name in (("ev", m["ev"]), ("dep", m["deplasman"])):
        s = st[side]
        L.append(f"| {name} | {_form_line(s)} | {_block(s['ic_saha_son5'])} | {_block(s['dis_saha_son5'])} | "
                 f"{s['son7_gun_mac']} | {num(s['puan_sd'])} |")
    L.append("")
    fe, fdp = st["fd"]["ev"], st["fd"]["dep"]
    for side, name, f in (("ev", m["ev"], fe), ("dep", m["deplasman"], fdp)):
        if f.get("fd_takim"):
            L.append(f"- {name} — {f['lig']} sezon verisi: iç saha {num(f['ic_saha']['atilan'])}/"
                     f"{num(f['ic_saha']['yenilen'])} ({f['ic_saha']['mac']} maç), dış saha "
                     f"{num(f['dis_saha']['atilan'])}/{num(f['dis_saha']['yenilen'])} ({f['dis_saha']['mac']} maç), "
                     f"xG {num(f['xg_ort'])} / xGA {num(f['xga_ort'])} "
                     f"(eşleşme {f['fd_takim']}, {f['dogrulanan_mac']} maç tarih+skor ile doğrulandı)")
        else:
            L.append(f"- {name} — sezon verisi/xG: veri yok ({f.get('neden', '')})")
    ps = st["puan_durumu"]
    if ps.get("turnuva"):
        ev, dp = ps["ev"], ps["dep"]
        fmt = lambda x: "veri yok" if isinstance(x, str) else f"{x['r']}. sıra, {x['pt']} puan ({x['p']} maç, {x['gf']}-{x['ga']})"  # noqa: E731
        L.append(f"- Puan durumu ({ps['turnuva']}): {m['ev']} {fmt(ev)}; {m['deplasman']} {fmt(dp)}; "
                 f"puan farkı {ps['puan_farki'] if ps['puan_farki'] is not None else 'veri yok'}")
    nx = st["fikstur"]
    L.append(f"- Sonraki maç (5 gün): {m['ev']}: {'; '.join(nx['ev_sonraki']) or 'bültende yok'} | "
             f"{m['deplasman']}: {'; '.join(nx['dep_sonraki']) or 'bültende yok'}")
    L.append("")
    # H2H
    L.append("**Kafa kafaya**: " + ("; ".join(f"{h['tarih']} {h['turnuva']}: {h['skor']} (İY {h['iy']})"
                                              for h in st["kafa_kafaya"]) or "veri yok (kaynakta geçmiş karşılaşma yok)"))
    L.append("")
    # Kart/korner
    kk = st["kart_korner"]
    L.append(f"**Kart/korner (son 6 maç)**: {m['ev']}: maç başı kart {num(kk['ev'].get('mac_kart_ort'))}, "
             f"maç başı korner {num(kk['ev'].get('mac_korner_ort'))} | {m['deplasman']}: maç başı kart "
             f"{num(kk['dep'].get('mac_kart_ort'))}, maç başı korner {num(kk['dep'].get('mac_korner_ort'))}. "
             "Kart pazarı bültende yok.")
    L.append("")
    # Kadro & haber
    k = st["kadro"]
    L.append("**Kadro ve haberler**")
    if k.get("ev"):
        L.append(f"- Tahmini 11 (iddaa kadro servisi, resmi değil): {m['ev']} ({k['ev']['teknik_direktor']}, "
                 f"{k['ev']['dizilis']}): {', '.join(p.split(' (')[0] for p in k['ev']['oyuncular'])}")
        L.append(f"- {m['deplasman']} ({k['dep']['teknik_direktor']}, {k['dep']['dizilis']}): "
                 f"{', '.join(p.split(' (')[0] for p in k['dep']['oyuncular'])}")
    else:
        L.append("- Tahmini 11: veri yok")
    hs = [h for h in (nw or {}).get("haberler", []) if set(h["kategori"]) - {"kadro", "onizleme"}]
    if hs:
        for h in hs[:6]:
            tag = " (ESKİ >72s)" if h["eski"] else ""
            L.append(f"- [{', '.join(h['kategori'])}] {h['baslik']} — {h['kaynak']}, {h['yayin'][:16]}{tag} "
                     f"([bağlantı]({h['link']}))")
    else:
        L.append("- Son 72 saatte risk taşıyan haber başlığı bulunamadı.")
    if (nw or {}).get("risk", {}).get("olasi_eksik_oyuncu"):
        L.append("- Başlıktan çıkarılan, DOĞRULANMAMIŞ olası eksik: " +
                 ", ".join(x["oyuncu"] for x in nw["risk"]["olasi_eksik_oyuncu"]))
    if pr["manuel_duzeltmeler"]:
        for d in pr["manuel_duzeltmeler"]:
            L.append(f"- Manuel λ düzeltmesi: {d['takim']} ×{d['carpan']} (rakip ×{d['rakip_carpan']}) — "
                     f"{d['gerekce']} ([kaynak]({d['kaynak']}))")
    else:
        L.append("- Manuel λ düzeltmesi: yok (doğrulanmış, kilit oyuncu eksikliği bulunamadı).")
    L.append("")
    # Model
    S, b = pr["olasiliklar"], pr["bilesenler"]
    P = anc["olasiliklar"] if anc else S
    if anc:
        pl = anc["piyasa_lambda"]
        L += [f"**Tahmin (piyasaya dayalı)**: λ ev {anc['lambda']['ev']:.2f}, λ dep {anc['lambda']['dep']:.2f} — "
              f"{anc['yontem']} (w kaynağı: {anc['agirlik'].get('kaynak')})"]
        if pl:
            L.append(f"- Piyasa λ: {pl['ev']:.2f} / {pl['dep']:.2f}, uyduruldu: {', '.join(pl['pazarlar'])} "
                     f"(pazarlar arası RMSE {pl['uyum_rmse']:.4f})")
    L += [f"**İstatistik modeli (ikinci görüş)**: λ ev {pr['lambda']['ev']:.2f}, λ dep {pr['lambda']['dep']:.2f} "
          f"(μ {b['mu']}, ev avantajı {b['ev_avantaji']}, ligler arası {b['ligler_arasi']:+.3f}, ρ {b['rho']}); "
          f"veri kalitesi {pr['veri_kalitesi']}"]
    for n_ in pr["notlar"]:
        L.append(f"- {n_}")
    L.append(f"- Güç kaynağı: {m['ev']}: {b['ev']['kaynak']} | {m['deplasman']}: {b['dep']['kaynak']}")
    L.append("- En olası 3 skor: " + ", ".join(f"{x['skor']} (%{100*x['olasilik']:.1f})" for x in P["_en_olasi_skorlar"]))
    L.append("")
    L += [f"| Pazar | Tahmin | Pazar fiyatı (marjsız) | İstatistik | Oran ({deger_time[11:16]}) |", "|---|---|---|---|---|"]
    izin = _izinli()
    want = [(z["pazar"], z["secenek"]) for z in izin] if izin else [("AU_2.5", "Üst"), ("AU_3.5", "Üst")]
    idx = {(r["pazar"], r["secenek"]): r for r in gv}
    for mk, oc in want:
        r = idx.get((mk, oc))
        pm = P.get(mk, {}).get(oc)
        L.append(f"| {mk} {oc} | {pct(pm)} | {pct(r['piyasa']) if r else 'veri yok'} | "
                 f"{pct(S.get(mk, {}).get(oc))} | {num(r['oran']) if r else 'kapalı/yok'} |")
    L.append("")
    # Öneri
    if pick:
        L.append(f"**Önerilen seçenek**: {pick['pazar_adi']}: **{pick['secenek']}** @{pick['oran']:.2f} — "
                 f"tahmin {pct(pick['model'])}, pazar fiyatı {pct(pick['piyasa'])}, istatistik {pct(pick.get('istatistik'))}, "
                 f"değer {pick['deger']:+.2f}, "
                 f"güven **{pick['guven']:.0f}** (O {pick['bilesen']['O']}, U {pick['bilesen']['U']}, "
                 f"V {pick['bilesen']['V']}, İ {pick['bilesen']['I']}, H −{pick['bilesen']['H']})")
        if alt:
            L.append(f"**Alternatif**: {alt['pazar_adi']}: {alt['secenek']} @{alt['oran']:.2f} — "
                     f"model {pct(alt['model'])}, piyasa {pct(alt['piyasa'])}, güven {alt['guven']:.0f}")
        risks = list(pick["haber_riski_nedenleri"])
        if pick["bilesen"]["U"] < 0.5 and pick.get("istatistik") is not None:
            risks.insert(0, f"istatistik modeli piyasadan ayrılıyor ({100*(pick['istatistik']-pick['model']):+.0f} puan)")
        if pr["veri_kalitesi"] < 0.7:
            risks.insert(0, "takımlardan biri için sezon verisi yok (yalnızca son 10 maç, rakip gücü düzeltilmemiş)")
        if pick["bilesen"]["I"] < 0.35:
            risks.append("sonuçları dalgalı takım(lar)")
        if not risks:
            risks = ["kadro resmi değil (resmi 11 maçtan ~1 saat önce açıklanır)"]
        L.append(f"**En büyük risk**: {risks[0]}" + (f" (diğer: {'; '.join(risks[1:])})" if len(risks) > 1 else ""))
    L.append("")
    # Kaynaklar
    L.append("**Kaynaklar**")
    L.append(f"- Oranlar: https://www.iddaa.com/program/futbol/mac-detay/1/{code}/tum-oranlar ({deger_time})")
    L.append(f"- İstatistik: {st['kaynak']}")
    for f in (fe, fdp):
        if f.get("kaynak"):
            L.append(f"- Sezon verisi: {f['kaynak']}")
    for q in (nw or {}).get("sorgular", [])[:4]:
        if q.get("url"):
            L.append(f"- Haber araması: {q['url']} ({q['fetched_at']})")
    L.append("")
    return L


def build(day: str, root: Path, data: dict, filtre: dict, stats: dict, haber: dict | None, model: dict,
          deger: dict, guven: dict, backtest_note: str, stamp: str, single: int | None = None) -> tuple[Path, Path]:
    by_code = {str(m["mac_kodu"]): m for m in data["maclar"]}
    by_code_fresh = by_code  # deger adımı oranları yeniledi; maç bilgisi aynı
    picks = _pick_summary(guven, by_code, 0 if single else OZET_MIN_GUVEN)
    coupons = _coupons(picks)
    pick_by_code = {p["mac_kodu"]: p for p in picks}
    L = [f"# iddaa Günlük Maç Analizi — {day}", "",
         f"Rapor zamanı: {stamp} · Oranların çekildiği an: **{deger['oran_zamani']}** (oranlar değişir; oynamadan önce kontrol edin)",
         "", "> **Model hakkında dürüst not.** " + backtest_note, "",
         f"> Güven skoru formülü: `{guven['formul']}`", ""]
    # A
    L += ["## A) Günün özeti", "",
          f"Güven ≥ {OZET_MIN_GUVEN}, maç başına en fazla 1 seçim (aynı maçın seçenekleri birbirine bağlıdır).", "",
          "Model % = piyasaya dayalı tahmin (tüm pazarlara uyan λ); Piyasa % = o pazarın kendi marjsız fiyatı; "
          "İst. % = bağımsız istatistik modeli.", "",
          "| Saat | Lig | Maç | MBS | Seçenek | Oran | Model % | Piyasa % | İst. % | Değer | Güven |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in picks:
        m, r = p["mac"], p["secim"]
        L.append(f"| {m['saat']} | {m['lig']} | {m['ev']} – {m['deplasman']} | {r['mbs']} | {r['pazar_adi']}: {r['secenek']} | "
                 f"{r['oran']:.2f} | {100*r['model']:.1f} | {100*r['piyasa']:.1f} | "
                 f"{ist_pct(r)} | "
                 f"{r['deger']:+.2f} | {r['guven']:.0f} |")
    if not picks:
        L.append("| – | – | Bugün güven eşiğini geçen seçim yok | – | – | – | – | – | – | – | – |")
    L.append("")
    if deger.get("oran_hareketi"):
        L.append("**Gün içi oran hareketleri (≥%8, önceki çekime göre)**: " + "; ".join(
            f"{by_code[k]['ev']}–{by_code[k]['deplasman']}: " + ", ".join(f"{s} {a:.2f}→{b:.2f}" for s, (a, b, _) in v.items())
            for k, v in deger["oran_hareketi"].items() if k in by_code))
        L.append("")
    # B
    L += ["## B) Maç maç detaylı analiz", ""]
    for p in picks:
        code = p["mac_kodu"]
        L += match_detail(code, by_code_fresh[code], stats["maclar"][code], (haber or {}).get("maclar", {}).get(code),
                          model["maclar"][code], guven["maclar"][code], p["secim"], p["alternatif"], deger["oran_zamani"],
                          deger.get("tahmin", {}).get(code))
    # C
    L += ["## C) Kupon önerileri", "",
          "Kombine olasılık, maçların birbirinden bağımsız olduğu varsayımıyla çarpılarak hesaplanır.", ""]
    for c in coupons.values():
        L.append(f"**{c['ad']}** — toplam oran {c['toplam_oran']:.2f}, kombine model olasılığı: {c['carpim_metni']} "
                 f"(piyasa: %{100*c['piyasa_olasilik']:.0f}), beklenen değer {c['beklenen_deger']:+.2f} "
                 f"(birim başına), en yüksek MBS {c['gereken_mbs']}" + (f" — ⚠ {c['uyari']}" if c.get("uyari") else ""))
        for s in c["secimler"]:
            L.append(f"- {s['mac']}: {s['secenek']} @{s['oran']:.2f} (model %{100*s['model']:.0f}, MBS {s['mbs']})")
        L.append("")
    if not coupons:
        L += ["Bugün kupon önerisi yok (yeterli güvenli seçim yok).", ""]
    L += ["Not: iddaa marjı (~%15) nedeniyle bu seçimlerin beklenen değeri negatiftir; kupon büyüdükçe kayıp beklentisi artar.", ""]
    # D
    L += ["## D) Elenen maçlar", "", "| Saat | Maç | Lig | Neden |", "|---|---|---|---|"]
    for r in filtre["elenen"]:
        L.append(f"| {r['saat']} | {r['mac']} | {r['lig']} | {r['gerekce']} |")
    for code in model["maclar"]:
        if code in pick_by_code:
            continue
        m = by_code.get(code)
        if not m:
            continue
        if code in deger.get("dusen_maclar", []):
            why = "analiz sırasında başladı/bültenden kalktı"
        else:
            el = [r for r in guven["maclar"].get(code, []) if r["ozete_uygun"]]
            why = (f"en iyi uygun seçenek güveni {el[0]['guven']:.0f} < {OZET_MIN_GUVEN} "
                   f"({el[0]['pazar_adi']}: {el[0]['secenek']} @{el[0]['oran']:.2f})") if el else \
                  "özet kurallarına uyan seçenek yok (olasılık <%55 veya oran aralık dışı)"
        L.append(f"| {m['saat']} | {m['ev']} – {m['deplasman']} | {m['lig']} | analiz edildi, seçilmedi: {why} |")
    L += ["", "---", "", f"**{DISCLAIMER}**", ""]

    rep = root / "reports"
    rep.mkdir(exist_ok=True)
    hhmm = stamp[11:16].replace(":", "")
    md = "\n".join(L)
    js = {"tarih": day, "rapor_zamani": stamp, "oran_zamani": deger["oran_zamani"], "model_notu": backtest_note,
          "guven_formulu": guven["formul"], "ozet": [{"mac_kodu": p["mac_kodu"], "saat": p["mac"]["saat"],
          "lig": p["mac"]["lig"], "mac": f"{p['mac']['ev']} - {p['mac']['deplasman']}", "secim": p["secim"],
          "alternatif": p["alternatif"]} for p in picks],
          "kuponlar": coupons, "elenen_filtre": filtre["elenen"],
          "maclar": {c: {"model": model["maclar"][c], "secenekler": guven["maclar"].get(c, [])} for c in model["maclar"]},
          "uyari": DISCLAIMER}
    if not single:
        build_app(day, root, data, stats, haber, model, deger, guven, backtest_note, stamp, picks, coupons)
    names = [f"{day}_mac_{single}"] if single else [f"{day}_{hhmm}", day]
    for name in names:
        (rep / f"{name}.md").write_text(md, encoding="utf-8")
        (rep / f"{name}.json").write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep / f"{names[0]}.md", rep / f"{names[0]}.json"


# ---------------- Uygulama verisi (telefon arayüzü için sade JSON) ----------------

PAZAR_SIRA = ["MS", "CS", "AU_0.5", "AU_1.5", "AU_2.5", "AU_3.5", "AU_4.5", "KG", "TOPLAM_GOL", "IY", "IY_AU_0.5",
              "IY_AU_1.5", "IY_KG", "IYMS", "HMS_1:0", "HMS_0:1", "HMS_2:0", "HMS_0:2", "HMS_3:0", "HMS_0:3"]


def _izinli() -> list[dict] | None:
    f = Path(__file__).resolve().parent / "config" / "pazarlar.json"
    return json.loads(f.read_text(encoding="utf-8"))["izinli"] if f.exists() else None


def _r(x, n=4):
    return None if x is None else round(float(x), n)


def build_app(day: str, root: Path, data: dict, stats: dict, haber: dict | None, model: dict, deger: dict,
              guven: dict, backtest_note: str, stamp: str, picks: list[dict], coupons: dict) -> Path:
    by_code = {str(m["mac_kodu"]): m for m in data["maclar"]}
    pick_codes = {p["mac_kodu"]: p for p in picks}
    maclar = []
    for code, recs in guven["maclar"].items():
        m = by_code.get(code)
        if not m:
            continue
        st = stats["maclar"].get(code, {})
        anc = deger.get("tahmin", {}).get(code, {})
        nw = (haber or {}).get("maclar", {}).get(code, {})
        opts = []
        for r in recs:
            if r["kapali"] or r.get("deger") is None:
                continue
            opts.append({"p": r["pazar"], "pa": r["pazar_adi"], "s": r["secenek"], "o": r["oran"], "m": _r(r["model"]),
                         "pk": _r(r.get("piyasa")), "i": _r(r.get("istatistik")), "d": _r(r["deger"], 3),
                         "g": r["guven"], "ok": r["ozete_uygun"], "sup": r.get("supheli", False), "mbs": r["mbs"]})
        # pazar sırası sabit; pazar içi seçenekler bültendeki doğal sırada (1, X, 2 / Alt, Üst ...)
        natural = {(r["pazar"], r["secenek"]): i for i, r in enumerate(deger["maclar"].get(code, []))}
        izin = _izinli()
        if izin:
            opts = [o for o in opts if (o["p"], o["s"]) in {(z["pazar"], z["secenek"]) for z in izin}]
            have = {(o["p"], o["s"]) for o in opts}
            P = (anc.get("olasiliklar") or {}); S = model["maclar"][code]["olasiliklar"]
            for z in izin:   # bültende oranı olmayan izinli seçenek: yalnızca tahmin
                if (z["pazar"], z["secenek"]) not in have and z["pazar"] in P:
                    opts.append({"p": z["pazar"], "pa": z["pazar_adi"], "s": z["secenek"], "o": None,
                                 "m": _r(P[z["pazar"]][z["secenek"]]), "pk": None,
                                 "i": _r((S.get(z["pazar"]) or {}).get(z["secenek"])), "d": None, "g": None,
                                 "ok": False, "sup": False, "mbs": m["mbs"], "not": "iddaa bu pazarı açmamış"})
            for o in opts:
                o["etiket"] = next(z["etiket"] for z in izin if (z["pazar"], z["secenek"]) == (o["p"], o["s"]))
        opts.sort(key=lambda x: (PAZAR_SIRA.index(x["p"]) if x["p"] in PAZAR_SIRA else 99, x["p"],
                                 natural.get((x["p"], x["s"]), 999)))
        hs = [h for h in nw.get("haberler", []) if not h["eski"]]
        risky = [h for h in hs if set(h["kategori"]) - {"kadro", "onizleme"}]
        other = [h for h in hs if h not in risky][:4]
        ev_s, dep_s = st.get("ev", {}), st.get("dep", {})
        ps = st.get("puan_durumu", {})

        def row(x):
            return None if not isinstance(x, dict) else {"sira": x.get("r"), "puan": x.get("pt"), "mac": x.get("p"),
                                                          "ag": x.get("gf"), "yg": x.get("ga")}
        pk = pick_codes.get(code)
        maclar.append({
            "kod": code, "saat": m["saat"], "baslama": m["baslama"], "lig": m["lig"], "ev": m["ev"], "dep": m["deplasman"],
            "mbs": m["mbs"], "lambda": anc.get("lambda"),
            "iy_pay": model["maclar"][code]["bilesenler"].get("iy_gol_payi"),
            "skorlar": (anc.get("olasiliklar") or {}).get("_en_olasi_skorlar", []),
            "veri_kalitesi": model["maclar"][code]["veri_kalitesi"],
            "form": {"ev": ev_s.get("son10", {}).get("form"), "dep": dep_s.get("son10", {}).get("form")},
            "ort": {s: {k: (st.get(s, {}).get("son10", {}) or {}).get(k) for k in
                        ("atilan_ort", "yenilen_ort", "ust25_yuzde", "kg_var_yuzde", "gol_yemeden_yuzde")}
                    for s in ("ev", "dep")},
            "puan": {"turnuva": ps.get("turnuva"), "ev": row(ps.get("ev")), "dep": row(ps.get("dep"))},
            "h2h": st.get("kafa_kafaya", [])[:5],
            "sonraki": st.get("fikstur", {}),
            "haberler": [{"b": h["baslik"], "k": h["kaynak"], "t": h["yayin"], "l": h["link"], "kat": h["kategori"]}
                         for h in (risky + other)[:8]],
            "risk": (pk["secim"]["haber_riski_nedenleri"] if pk else
                     (next((r["haber_riski_nedenleri"] for r in recs if "haber_riski_nedenleri" in r), []))),
            "secim": None if not pk else {"p": pk["secim"]["pazar"], "s": pk["secim"]["secenek"]},
            "alternatif": None if not pk or not pk["alternatif"] else {"p": pk["alternatif"]["pazar"], "s": pk["alternatif"]["secenek"]},
            "secenekler": opts,
        })
    maclar.sort(key=lambda x: (x["baslama"], x["lig"]))
    app = {"pazarlar": _izinli(), "tarih": day, "rapor_zamani": stamp, "oran_zamani": deger["oran_zamani"], "not": backtest_note,
           "formul": guven["formul"], "uyari": DISCLAIMER,
           "ozet": [{"kod": p["mac_kodu"], "p": p["secim"]["pazar"], "s": p["secim"]["secenek"]} for p in picks],
           "kuponlar": [{"ad": c["ad"], "uyari": c.get("uyari"), "secimler": [s["mac_kodu"] for s in c["secimler"]]}
                        for c in coupons.values()],
           "maclar": maclar}
    rep = root / "reports"
    hhmm = stamp[11:16].replace(":", "")
    p = rep / f"app_{day}_{hhmm}.json"
    txt = json.dumps(app, ensure_ascii=False, separators=(",", ":"))
    p.write_text(txt, encoding="utf-8")
    (rep / "app.json").write_text(txt, encoding="utf-8")
    return p
