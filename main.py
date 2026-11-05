"""Günlük iddaa maç analiz akışı.

Kullanım:
  python main.py                 # tüm akış
  python main.py --adim bulten   # yalnızca belirtilen adıma kadar çalış (ilk çalıştırma onay akışı)
  python main.py --mac <kod>     # tek maç detaylı analiz
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.table import Table

import datetime as dt

from scrapers.common import ScrapeError, iso_now
from scrapers.footballdata import FootballData
from model.engine import Engine
from model.value import evaluate_match
from model.confidence import FORMUL, eligible_for_summary, score
from report import DISCLAIMER, build as build_report
from scrapers.news import collect_news
from scrapers.uefa import fetch_coefficients
from scrapers.stats import IddaaStats, collect_match
from filtre import apply_filter
from scrapers.iddaa import (diff_bulletins, fetch_bulletin, market,
                             previous_snapshot, save_bulletin)

ROOT = Path(__file__).resolve().parent
con = Console()

ADIMLAR = ["bulten", "filtre", "istatistik", "haber", "model", "deger", "guven", "rapor"]


def odds_str(m, names):
    if not m:
        return "-"
    by = {o["name"]: o for o in m["outcomes"]}
    return " / ".join(
        ("kapalı" if by[n]["closed"] else f"{by[n]['odd']:.2f}") if n in by else "-" for n in names
    )


def adim_bulten() -> dict:
    con.rule("[bold]Adım 2: Bülten")
    data = fetch_bulletin()
    prev = previous_snapshot(ROOT, data["tarih"], data["cekilme_zamani"])
    p = save_bulletin(data, ROOT)
    data["degisim"] = diff_bulletins(prev, data)
    con.print(f"Yöntem: {data['yontem']}  |  Çekilme: {data['cekilme_zamani']}  |  Kayıt: {p.relative_to(ROOT)}")
    for url, m in data["uc_noktalar"].items():
        con.print(f"  [dim]{url} -> {m}[/dim]")
    con.print(f"Toplam etkinlik: {data['toplam_etkinlik']}  |  Atlanan: {data['atlanan']}")
    con.print(f"Bugün başlayacak ve başlamamış maç: [bold]{len(data['maclar'])}[/bold]")

    dg = data["degisim"]
    if dg["onceki"]:
        con.print(f"[bold]Önceki çekime göre ({dg['onceki'][11:16]}):[/bold] yeni {len(dg['yeni'])}, "
                  f"kalkan/başlayan {len(dg['kalkan'])}, oranı ≥%8 oynayan {len(dg['hareket'])} maç")
        for k, ch in list(dg["hareket"].items())[:15]:
            con.print(f"  {k}: " + ", ".join(f"{s} {a:.2f}→{b:.2f} ({d:+.0%})" for s, (a, b, d) in ch.items()))
    else:
        con.print("Bugün için önceki çekim yok; oran hareketi bir sonraki çalıştırmada görünecek.")
    lig = Counter(m["lig"] for m in data["maclar"])
    t = Table(title="Lig dağılımı")
    t.add_column("Lig"); t.add_column("Maç", justify="right")
    for k, v in lig.most_common():
        t.add_row(k, str(v))
    con.print(t)

    keys = Counter(m["key"] for x in data["maclar"] for m in x["pazarlar"] if m["key"])
    con.print("Pazar kapsamı (maç sayısı): " + ", ".join(f"{k}={v}" for k, v in sorted(keys.items())))

    t = Table(title=f"Bülten (oranlar {data['cekilme_zamani'][11:16]} itibarıyla)", show_lines=False)
    for c in ["Saat", "Kod", "Lig", "Maç", "MBS", "MS 1/X/2", "2.5 A/Ü", "KG V/Y", "Pazar"]:
        t.add_column(c)
    for x in data["maclar"]:
        t.add_row(
            x["saat"], str(x["mac_kodu"]), x["lig"][:28], f"{x['ev']} - {x['deplasman']}"[:40], str(x["mbs"]),
            odds_str(market(x, "MS"), ["1", "0", "2"]),
            odds_str(market(x, "AU_2.5"), ["Alt", "Üst"]),
            odds_str(market(x, "KG"), ["Var", "Yok"]),
            str(len(x["pazarlar"])),
        )
    con.print(t)
    return data


def adim_filtre(data: dict) -> dict:
    con.rule("[bold]Adım 3: Filtre")
    f = apply_filter(data)
    out = ROOT / "data" / data["tarih"] / "filtre.json"
    out.write_text(json.dumps(f, ensure_ascii=False, indent=1), encoding="utf-8")
    con.print(f"Kurallar: config/{f['kurallar']}  |  Seçilen: [bold]{len(f['secilen'])}[/bold]  |  Elenen: {len(f['elenen'])}  |  Kayıt: {out.relative_to(ROOT)}")
    t = Table(title="Detaylı analize girecek maçlar")
    for c in ["Sv", "Saat", "Kod", "Lig", "Maç", "MBS"]:
        t.add_column(c)
    for r in f["secilen"]:
        t.add_row(str(r["seviye"]), r["saat"], str(r["mac_kodu"]), r["lig"][:30], r["mac"][:42], str(r["mbs"]))
    con.print(t)
    g = Counter(r["gerekce"] if "dk var" not in r["gerekce"] else "başlamasına çok az kaldı" for r in f["elenen"])
    t = Table(title="Elenme gerekçeleri")
    t.add_column("Gerekçe"); t.add_column("Maç", justify="right")
    for k, v in g.most_common():
        t.add_row(k, str(v))
    con.print(t)
    return f


def adim_istatistik(data: dict, f: dict, only: int | None = None) -> dict:
    con.rule("[bold]Adım 4: İstatistik")
    day = data["tarih"]
    ddir = ROOT / "data" / day
    cfg = json.loads((ROOT / "config" / "filtre.json").read_text(encoding="utf-8"))
    by_code = {m["mac_kodu"]: m for m in data["maclar"]}
    codes = [only] if only else [r["mac_kodu"] for r in f["secilen"]]

    fd = FootballData(ddir / "footballdata", dt.date.fromisoformat(day))
    fd.load()
    data["_fd"] = fd  # model adımı aynı nesneyi kullanır
    con.print(f"football-data: {len(fd.leagues)} lig yüklendi -> " +
              ", ".join(f"{k}({len(v['maclar'])})" for k, v in fd.leagues.items()))
    for e in fd.log:
        if e.get("error"):
            con.print(f"  [yellow]veri yok:[/yellow] {e['url']} ({e['error']})")

    api = IddaaStats(ddir / "iddaa_stats")
    out = {}
    with con.status("iddaa istatistikleri çekiliyor...") as s:
        for i, code in enumerate(codes, 1):
            m = by_code[code]
            s.update(f"[{i}/{len(codes)}] {m['ev']} - {m['deplasman']}")
            st = collect_match(api, m, data["tum_gunler"], cfg["min_erisilebilir_mac"])
            st["fd"] = {"ev": fd.team_profile(m["ev"], st["ev"]["maclar"]),
                       "dep": fd.team_profile(m["deplasman"], st["dep"]["maclar"])}
            out[str(code)] = st
    api.close()
    res = {"cekilme_zamani": iso_now(), "maclar": out, "istek_log": api.log, "fd_log": fd.log}
    (ddir / "istatistik.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    t = Table(title="İstatistik özeti (son 10 maç, tüm kortlar)")
    for c in ["Kod", "Maç", "Form Ev", "Form Dep", "Gol A/Y ev", "Gol A/Y dep", "Ü2.5% e/d", "KG% e/d",
              "H2H", "Maç kart e/d", "Korner e/d", "xG eşleşme e/d", "Son7g e/d", "Veri"]:
        t.add_column(c, overflow="fold")
    fmt = lambda x: "-" if x is None else f"{x:g}"  # noqa: E731
    for code, st in out.items():
        m = by_code[int(code)]; e, d = st["ev"]["son10"], st["dep"]["son10"]
        ke, kd = st["kart_korner"]["ev"], st["kart_korner"]["dep"]
        fe, fdp = st["fd"]["ev"], st["fd"]["dep"]
        xg = lambda p: (f"{p['fd_takim']}[{p['lig_kodu']},{p['dogrulanan_mac']}✓]" if p.get("fd_takim") else "yok")  # noqa: E731
        t.add_row(str(code), f"{m['ev']} - {m['deplasman']}", e["form"], d["form"],
                  f"{fmt(e['atilan_ort'])}/{fmt(e['yenilen_ort'])}", f"{fmt(d['atilan_ort'])}/{fmt(d['yenilen_ort'])}",
                  f"{fmt(e['ust25_yuzde'])}/{fmt(d['ust25_yuzde'])}", f"{fmt(e['kg_var_yuzde'])}/{fmt(d['kg_var_yuzde'])}",
                  str(len(st["kafa_kafaya"])),
                  f"{fmt(ke.get('mac_kart_ort'))}/{fmt(kd.get('mac_kart_ort'))}",
                  f"{fmt(ke.get('takim_korner_ort'))}/{fmt(kd.get('takim_korner_ort'))}",
                  f"{xg(fe)} / {xg(fdp)}",
                  f"{st['ev']['son7_gun_mac']}/{st['dep']['son7_gun_mac']}",
                  "DÜŞÜK" if st["veri_yeterliligi"]["dusuk_veri"] else "ok")
    con.print(t)
    errs = [x for x in api.log if x.get("error")]
    con.print(f"iddaa istek: {len(api.log)} (hata/veri yok: {len(errs)})  |  Kayıt: data/{day}/istatistik.json")
    for x in errs[:10]:
        con.print(f"  [yellow]veri yok:[/yellow] {x['url']} -> {x['error']}")
    return res


def adim_haber(data: dict, stats: dict) -> dict:
    """Haberler her çalıştırmada yeniden taranır (önbellek yok)."""
    con.rule("[bold]Adım 5: Haber ve kadro")
    by_code = {m["mac_kodu"]: m for m in data["maclar"]}
    out = {}
    with con.status("haberler taranıyor...") as s:
        for i, (code, st) in enumerate(stats["maclar"].items(), 1):
            m = by_code[int(code)]
            s.update(f"[{i}/{len(stats['maclar'])}] {m['ev']} - {m['deplasman']}")
            en = tuple((st["fd"][k].get("fd_takim") or n) for k, n in (("ev", m["ev"]), ("dep", m["deplasman"])))
            out[code] = collect_news(m, st["kadro"], en)
    res = {"cekilme_zamani": iso_now(), "maclar": out}
    p = ROOT / "data" / data["tarih"] / "haberler.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    t = Table(title="Haber taraması (son 72 saat, yalnızca başlıklar)")
    for c in ["Kod", "Maç", "İlgili haber", "Sakat/ceza", "TD/kriz", "Rotasyon", "Doğrulanmalı: olası eksik", "Kadro"]:
        t.add_column(c, overflow="fold")
    for code, n in out.items():
        m = by_code[int(code)]; r = n["risk"]
        eks = "; ".join(f"{x['takim']}: {x['oyuncu']}" for x in r["olasi_eksik_oyuncu"]) or "-"
        t.add_row(str(code), f"{m['ev']} - {m['deplasman']}", str(len([h for h in n["haberler"] if not h["eski"]])),
                  str(r["sakatlik_ceza_haberi"]), str(r["td_kriz_haberi"]), str(r["rotasyon_haberi"]), eks,
                  "tahmini" if r["kadro_belirsiz"] else "kesin")
    con.print(t)
    con.print(f"Kayıt: {p.relative_to(ROOT)}")
    return res


def adim_model(data: dict, stats: dict) -> dict:
    con.rule("[bold]Adım 6: Olasılık modeli")
    day = dt.date.fromisoformat(data["tarih"])
    ddir = ROOT / "data" / data["tarih"]
    season_end = day.year + 1 if day.month >= 7 else day.year
    uefa = fetch_coefficients(ddir, season_end)
    eng = Engine(data["_fd"], stats, data, uefa, day, ROOT / "config" / "manuel_duzeltme.json")
    acache = ddir / "alpha_kalibrasyon.json"
    if eng.alpha.get("alpha") is not None:
        acache.write_text(json.dumps(eng.alpha, ensure_ascii=False), encoding="utf-8")
    elif acache.exists():   # --mac gibi küçük örneklerde günün tam kalibrasyonu kullanılır
        eng.alpha = {**json.loads(acache.read_text(encoding="utf-8")), "not": "günün tam çalıştırmasındaki kalibrasyon"}
    con.print(f"Lig modeli: {len(eng.fits)} lig  |  Dixon-Coles ρ = {eng.rho:.3f}  |  İY gol payı (medyan) = {eng.iy_med:.3f}")
    al = eng.alpha
    con.print(f"Ligler arası α = {al.get('alpha')} (std. hata {al.get('std_hata')}, {al['orneklem']} Avrupa kupası maçı)"
              + (f"  [yellow]{al['not']}[/yellow]" if al.get("not") else ""))
    con.print(f"UEFA katsayıları: {uefa['kaynak']} ({uefa['cekilme_zamani']})")
    con.print(f"Manuel düzeltme (bugün): {len(eng.manual)} kayıt")
    by_code = {str(m["mac_kodu"]): m for m in data["maclar"]}
    out = {}
    for code in stats["maclar"]:  # anahtarlar int (bellek) ya da str (JSON) olabilir
        out[str(code)] = eng.predict(by_code[str(code)])
    res = {"hesap_zamani": iso_now(), "rho": eng.rho, "alpha": al, "uefa": uefa, "maclar": out}
    p = ddir / "model.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    t = Table(title="Model sonuçları")
    for c in ["Kod", "Maç", "λ ev", "λ dep", "Lig ayarı", "MS 1/X/2 %", "2.5Ü %", "KG %", "En olası 3 skor", "Veri kal."]:
        t.add_column(c, overflow="fold")
    for code, r in out.items():
        m = by_code[code]; P = r["olasiliklar"]
        t.add_row(code, f"{m['ev']} - {m['deplasman']}", f"{r['lambda']['ev']:.2f}", f"{r['lambda']['dep']:.2f}",
                  f"{r['bilesenler']['ligler_arasi']:+.2f}",
                  " / ".join(f"{100*P['MS'][k]:.0f}" for k in ("1", "0", "2")),
                  f"{100*P['AU_2.5']['Üst']:.0f}", f"{100*P['KG']['Var']:.0f}",
                  ", ".join(f"{x['skor']} ({100*x['olasilik']:.0f}%)" for x in P["_en_olasi_skorlar"]),
                  f"{r['veri_kalitesi']:.2f}")
    con.print(t)
    con.print(f"Kayıt: {p.relative_to(ROOT)}")
    return res


def adim_deger(data: dict, stats: dict, haber: dict | None, model: dict) -> dict:
    con.rule("[bold]Adım 7: Değer analizi (oranlar yeniden çekiliyor)")
    fresh = fetch_bulletin()
    prev = previous_snapshot(ROOT, fresh["tarih"], fresh["cekilme_zamani"])
    save_bulletin(fresh, ROOT)
    dg = diff_bulletins(prev, fresh)
    by_code = {str(m["mac_kodu"]): m for m in fresh["maclar"]}
    gone = [c for c in model["maclar"] if c not in by_code]
    con.print(f"Oranlar: {fresh['cekilme_zamani']}  |  analizdeki {len(model['maclar'])} maçtan "
              f"{len(gone)} tanesi artık bültende yok/başladı")
    moved = {str(k): v for k, v in dg["hareket"].items() if str(k) in model["maclar"]}
    for k, ch in moved.items():
        m = by_code.get(k)
        con.print(f"  [cyan]oran hareketi[/cyan] {m['ev']} - {m['deplasman']}: " +
                  ", ".join(f"{s} {a:.2f}→{b:.2f} ({d:+.0%})" for s, (a, b, d) in ch.items()))
    res = {"oran_zamani": fresh["cekilme_zamani"], "dusen_maclar": gone, "oran_hareketi": moved, "maclar": {}}
    for code, pred in model["maclar"].items():
        if code not in by_code:
            continue
        recs, anc = evaluate_match(by_code[code], pred, stats["maclar"].get(code))
        res["maclar"][code] = recs
        res.setdefault("tahmin", {})[code] = anc
    p = ROOT / "data" / data["tarih"] / "deger.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    # MS marjı
    margins = [r["marj"] for rs in res["maclar"].values() for r in rs if r["pazar"] == "MS" and r.get("marj") is not None]
    if margins:
        con.print(f"iddaa MS marjı: ortalama %{100 * sum(margins) / len(margins):.1f} "
                  f"(min %{100 * min(margins):.1f}, maks %{100 * max(margins):.1f})")
    allrecs = [(c, r) for c, rs in res["maclar"].items() for r in rs if not r["kapali"] and r.get("piyasa") is not None]
    n_val = sum(1 for _, r in allrecs if r["degerli"]); n_sus = sum(1 for _, r in allrecs if r["supheli"])
    con.print(f"Değerlendirilen seçenek: {len(allrecs)}  |  pozitif değer: {n_val}  |  şüpheli (>15 puan fark): {n_sus}")

    w = next(iter(res.get("tahmin", {}).values()), {}).get("agirlik", {})
    con.print(f"Tahmin yöntemi: piyasaya dayalı λ, istatistik ağırlığı w = {w.get('w_istatistik')} ({w.get('kaynak')})")
    rm = [a["piyasa_lambda"]["uyum_rmse"] for a in res.get("tahmin", {}).values() if a.get("piyasa_lambda")]
    if rm:
        con.print(f"Piyasa λ uyumu (pazarlar arası RMSE): medyan {sorted(rm)[len(rm)//2]:.4f}, en kötü {max(rm):.4f}")
    t = Table(title="Pozitif değerli seçenekler (p × oran > 1): iddaa'nın pazarlar arası fiyat tutarsızlıkları")
    for c in ["Kod", "Maç", "MBS", "Pazar", "Seçenek", "Oran", "Tahmin %", "Pazar fiyatı %", "İstatistik %", "Değer", "Şüpheli"]:
        t.add_column(c)
    for code, r in sorted(allrecs, key=lambda x: -x[1]["deger"]):
        if not r["degerli"]:
            continue
        m = by_code[code]
        t.add_row(code, f"{m['ev']} - {m['deplasman']}"[:34], str(r["mbs"]), r["pazar_adi"][:24], r["secenek"],
                  f"{r['oran']:.2f}", f"{100*r['model']:.1f}", f"{100*r['piyasa']:.1f}",
                  "-" if r["istatistik"] is None else f"{100*r['istatistik']:.1f}", f"{r['deger']:+.2f}",
                  "EVET" if r["supheli"] else "")
    con.print(t)

    sus_matches = sorted({c for c, r in allrecs if r["supheli"]})
    if sus_matches:
        con.print("[bold yellow]Şüpheli maçlar — haberler yeniden kontrol (son 72 saat, risk taşıyan başlıklar):[/bold yellow]")
        for c in sus_matches:
            m = by_code[c]
            q = model["maclar"][c]["veri_kalitesi"]
            hs = [h for h in ((haber or {}).get("maclar", {}).get(c, {}).get("haberler", []))
                  if not h["eski"] and set(h["kategori"]) - {"kadro", "onizleme"}]
            con.print(f"  {m['ev']} - {m['deplasman']} (veri kalitesi {q}): " +
                      ("; ".join(f"{h['kaynak']}: {h['baslik'][:80]}" for h in hs[:3]) or "ilgili risk haberi yok → "
                       "fark büyük ihtimalle model/veri eksikliğinden"))
    con.print(f"Kayıt: {p.relative_to(ROOT)}")
    return res


def adim_guven(data: dict, stats: dict, haber: dict | None, model: dict, deger: dict) -> dict:
    con.rule("[bold]Adım 8: Güven skoru")
    con.print(f"[dim]{FORMUL}[/dim]")
    starts = {str(m["mac_kodu"]): m["baslama"] for m in data["maclar"]}
    out = {}
    for code, recs in deger["maclar"].items():
        st = stats["maclar"][code]; nw = (haber or {}).get("maclar", {}).get(code)
        scored = []
        for r in recs:
            if r["kapali"] or r.get("deger") is None:
                continue
            g = score(r, model["maclar"][code], st, nw, starts[code])
            ok, why = eligible_for_summary(r)
            scored.append({**r, **g, "ozete_uygun": ok, "uygunsuzluk": why})
        scored.sort(key=lambda x: -x["guven"])
        out[code] = scored
    res = {"formul": FORMUL, "hesap_zamani": iso_now(), "maclar": out}
    p = ROOT / "data" / data["tarih"] / "guven.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    by_code = {str(m["mac_kodu"]): m for m in data["maclar"]}
    best = []
    for code, rs in out.items():
        el = [r for r in rs if r["ozete_uygun"]]
        if el:
            best.append((code, el[0], el[1] if len(el) > 1 else None))
    best.sort(key=lambda x: -x[1]["guven"])
    t = Table(title="Maç başına en yüksek güvenli seçenek (özet kurallarına uygun)")
    for c in ["Saat", "Maç", "MBS", "Seçenek", "Oran", "Tahmin %", "İstatistik %", "Değer", "Güven", "O/U/V/İ/H", "Alternatif"]:
        t.add_column(c, overflow="fold")
    for code, r, alt in best:
        m = by_code[code]; b = r["bilesen"]
        t.add_row(m["saat"], f"{m['ev']} - {m['deplasman']}", str(r["mbs"]), f"{r['pazar_adi']}: {r['secenek']}",
                  f"{r['oran']:.2f}", f"{100*r['model']:.0f}",
                  "-" if r["istatistik"] is None else f"{100*r['istatistik']:.0f}", f"{r['deger']:+.2f}",
                  f"{r['guven']:.0f}", f"{b['O']:.2f}/{b['U']:.2f}/{b['V']:.2f}/{b['I']:.2f}/{b['H']:.0f}",
                  f"{alt['pazar_adi']}: {alt['secenek']} @{alt['oran']:.2f} ({alt['guven']:.0f})" if alt else "-")
    con.print(t)
    con.print(f"Kayıt: {p.relative_to(ROOT)}")
    return res


def adim_rapor(data, f, stats, haber, model, deger, guven) -> None:
    con.rule("[bold]Adım 9: Rapor")
    bt = ROOT / "config" / "backtest_son.json"
    note = json.loads(bt.read_text(encoding="utf-8"))["not"] if bt.exists() else \
        "Geri test henüz çalıştırılmadı (python backtest.py); modelin piyasaya karşı başarısı bilinmiyor."
    md, js = build_report(data["tarih"], ROOT, data, f, stats, haber, model, deger, guven, note, iso_now(),
                          single=data.get("_tek_mac"))
    if data.get("_tek_mac"):
        con.print(md.read_text(encoding="utf-8"))
    con.print(f"Rapor: {md.relative_to(ROOT)}" + ("" if data.get("_tek_mac") else f" (ve reports/{data['tarih']}.md, .json)"))
    j = json.loads(js.read_text(encoding="utf-8"))
    t = Table(title=f"Günün özeti — oranlar {j['oran_zamani'][11:16]} itibarıyla")
    for c in ["Saat", "Lig", "Maç", "MBS", "Seçenek", "Oran", "Model %", "Piyasa %", "Değer", "Güven"]:
        t.add_column(c, overflow="fold")
    for p in j["ozet"]:
        r = p["secim"]
        t.add_row(p["saat"], p["lig"], p["mac"], str(r["mbs"]), f"{r['pazar_adi']}: {r['secenek']}", f"{r['oran']:.2f}",
                  f"{100*r['model']:.1f}", f"{100*r['piyasa']:.1f}", f"{r['deger']:+.2f}", f"{r['guven']:.0f}")
    con.print(t)
    for c in j["kuponlar"].values():
        con.print(f"[bold]{c['ad']}[/bold]: oran {c['toplam_oran']:.2f}, kombine olasılık {c['carpim_metni']}"
                  + (f" [red]{c['uyari']}[/red]" if c.get("uyari") else ""))
    con.print(f"[yellow]{note}[/yellow]")
    con.print(f"[bold]{DISCLAIMER}[/bold]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adim", choices=ADIMLAR, help="Bu adımdan sonra dur")
    ap.add_argument("--mac", type=int, help="Tek maç kodu")
    ap.add_argument("--haber-atla", action="store_true", help="(geliştirme) haber taramasını atla")
    a = ap.parse_args()
    try:
        data = adim_bulten()
        if a.adim == "bulten":
            return 0
        f = adim_filtre(data)
        if a.mac:
            if not any(m["mac_kodu"] == a.mac for m in data["maclar"]):
                con.print(f"[bold red]DURDU:[/bold red] {a.mac} kodlu maç bugünün bülteninde yok ya da başladı.")
                return 2
            m = next(m for m in data["maclar"] if m["mac_kodu"] == a.mac)
            f["secilen"] = [{"mac_kodu": a.mac, "saat": m["saat"], "lig": m["lig"],
                             "mac": f"{m['ev']} - {m['deplasman']}", "mbs": m["mbs"], "seviye": 0,
                             "gerekce": "--mac ile seçildi"}]
            f["elenen"] = []
            data["_tek_mac"] = a.mac
        if a.adim == "filtre":
            return 0
        stats = adim_istatistik(data, f, a.mac)
        if a.adim == "istatistik":
            return 0
        haber = None if a.haber_atla else adim_haber(data, stats)
        if a.adim == "haber":
            return 0
        model = adim_model(data, stats)
        if a.adim == "model":
            return 0
        if haber is None:
            p = ROOT / "data" / data["tarih"] / "haberler.json"
            haber = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        deger = adim_deger(data, stats, haber, model)
        if a.adim == "deger":
            return 0
        guven = adim_guven(data, stats, haber, model, deger)
        if a.adim == "guven":
            return 0
        adim_rapor(data, f, stats, haber, model, deger, guven)
        return 0
    except ScrapeError as e:
        con.print(f"[bold red]DURDU:[/bold red] {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
