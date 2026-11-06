"""Gerçek değer: iddaa Üst oranlarını keskin piyasanın (Pinnacle vb.) marjsız fiyatıyla karşılaştırır.

Kullanım: python keskin.py [--onceki https://<kullanıcı>.github.io/<depo>/keskin_gecmis.json] [--zorla]
  - Keskin oranlar günde bir kez çekilir (ilk çalıştırma TR saatiyle 11:00 sonrası ya da --zorla); sonraki
    çalıştırmalar önbellekteki keskin fiyatı güncel iddaa oranlarıyla yeniden karşılaştırır.
  - Çıktı: reports/keskin.json (uygulama) ve reports/keskin_gecmis.json (işaretlenen seçimler + sonuçları).
  - Anahtar yoksa ya da hata olursa analiz durmaz; durum dosyaya yazılır.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import httpx

from scrapers.common import TR_TZ, iso_now
from scrapers.sharp import SharpError, compare, fair_mu, fetch_raw

ROOT = Path(__file__).resolve().parent
LIVE = "https://statisticsv2.iddaa.com/live-results?sportId=1&date={}"
EVENT = "https://sportsbookv2.iddaa.com/sportsbook/event/{}"
SAAT_ESIGI = 11          # keskin oranları günün bu saatinden sonra çek (akşam maçlarına yakın fiyat)
TUT_GUN = 45             # geçmişte tutulacak gün


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _dump(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def latest_bulletin(day: str) -> dict:
    p = ROOT / "data" / day / "bulten.json"
    b = _load(p)
    if not b:
        raise SystemExit(f"{p} yok — önce python main.py")
    return b


def detail_totals(kod: str) -> list[dict]:
    """iddaa maç detayındaki tüm Alt/Üst çizgileri (bültende çoğu zaman yalnızca 2,5 bulunur)."""
    try:
        d = httpx.get(EVENT.format(kod), timeout=20).json().get("data") or {}
    except Exception:  # noqa: BLE001
        return []
    out = []
    for m in d.get("m") or []:
        if m.get("t") == 2 and m.get("st") == 101 and m.get("sov"):
            out.append({"key": f"AU_{m['sov']}", "outcomes": [
                {"name": o["n"], "odd": o["odd"], "closed": o["odd"] <= 1.0} for o in m.get("o", [])]})
    return out


def results(dates: set[str]) -> dict[str, dict]:
    out = {}
    for d in sorted(dates):
        try:
            j = httpx.get(LIVE.format(d), timeout=30).json().get("data") or {}
        except Exception:  # noqa: BLE001
            continue
        sc = j.get("sc") or {}
        for e in j.get("events") or []:
            x = sc.get(str(e["eventId"]))
            if e.get("phase") == 2 and x:
                out[str(e["eventId"])] = {"h": (x.get("ht") or {}).get("r"), "a": (x.get("at") or {}).get("r")}
    return out


def settle(hist: list[dict], now: dt.datetime) -> None:
    due = [h for h in hist if h.get("sonuc") is None
           and now - dt.datetime.fromisoformat(h["baslama"]) > dt.timedelta(hours=2, minutes=15)]
    if not due:
        return
    dates = set()
    for h in due:
        d0 = dt.datetime.fromisoformat(h["baslama"]).astimezone(TR_TZ).date()
        dates |= {d0.isoformat(), (d0 + dt.timedelta(days=1)).isoformat()}
    res = results(dates)
    for h in due:
        r = res.get(str(h["kod"]))
        if r and r["h"] is not None and r["a"] is not None:
            tot = r["h"] + r["a"]
            h["skor"] = f"{r['h']}-{r['a']}"
            h["sonuc"] = "tuttu" if tot > h["cizgi"] else "yatti"
            h["kar"] = round(h["iddaa_oran"] - 1, 3) if h["sonuc"] == "tuttu" else -1.0
        elif now - dt.datetime.fromisoformat(h["baslama"]) > dt.timedelta(days=2):
            h["sonuc"] = "bilinmiyor"     # ertelendi / sonuç bulunamadı (kâr hesabına girmez)


def summary(hist: list[dict]) -> dict:
    done = [h for h in hist if h.get("sonuc") in ("tuttu", "yatti")]
    n = len(done)
    if not n:
        return {"adet": 0}
    kar = sum(h["kar"] for h in done)
    return {"adet": n, "tuttu": sum(h["sonuc"] == "tuttu" for h in done), "kar_birim": round(kar, 2),
            "roi": round(kar / n, 4), "beklenen_tutma": round(sum(h["dogru_olasilik"] for h in done) / n, 4),
            "ort_deger": round(sum(h["deger"] for h in done) / n, 4)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onceki", help="Yayındaki keskin_gecmis.json adresi")
    ap.add_argument("--zorla", action="store_true", help="Saat eşiğini bekleme, bugün henüz çekilmediyse çek")
    a = ap.parse_args()
    now = dt.datetime.now(TR_TZ)
    day = now.date().isoformat()
    bul = latest_bulletin(day)
    ham_p = ROOT / "data" / day / "keskin_ham.json"
    ham = _load(ham_p)
    durum = "önbellek"
    if ham is None:
        if a.zorla or now.hour >= SAAT_ESIGI:
            try:
                ham = fetch_raw([m for m in bul["maclar"] if dt.datetime.fromisoformat(m["baslama"]) > now])
                _dump(ham_p, ham)
                durum = "yeni çekildi"
            except SharpError as e:
                durum = f"çekilemedi: {e}"
        else:
            durum = f"bugün henüz çekilmedi (TR {SAAT_ESIGI}:00 sonrası çekilir)"

    maclar, isaret = {}, []
    by_code = {str(m["mac_kodu"]): m for m in bul["maclar"]}
    if ham:
        for kod, es in ham["eslesme"].items():
            ev = ham["oranlar"].get(es["id"])
            m = by_code.get(kod)
            if not ev or not m:
                continue
            fair = fair_mu(ev)
            if not fair:
                continue
            if dt.datetime.fromisoformat(m["baslama"]) > now:      # güncel ve eksiksiz Üst oranları
                extra = detail_totals(kod)
                if extra:
                    have = {p["key"] for p in extra}
                    m = {**m, "pazarlar": extra + [p for p in m["pazarlar"] if p.get("key") not in have]}
            rows = compare(m, fair)
            maclar[kod] = {"kaynak": fair["kaynak"], "keskin": fair["keskin"], "mu": round(fair["mu"], 3),
                           "kaynak_guncelleme": fair["guncelleme"], "kaynak_cizgiler": fair["cizgiler"],
                           "eslesen": f"{es['ev']} - {es['dep']}", "satirlar": rows}
            for r in rows:
                if r["gercek_deger"] and dt.datetime.fromisoformat(m["baslama"]) > now:
                    isaret.append({"kod": kod, "mac": f"{m['ev']} - {m['deplasman']}", "lig": m.get("lig"),
                                   "baslama": m["baslama"], "kaynak": fair["kaynak"], **r})
    isaret.sort(key=lambda x: -x["deger"])

    # geçmiş: yayındaki dosya + bugünkü işaretler (maç başlayana kadar son oranla güncellenir)
    hist = []
    if a.onceki:
        try:
            r = httpx.get(a.onceki, timeout=20)
            if r.status_code == 200:
                hist = r.json().get("kayitlar", [])
        except Exception:  # noqa: BLE001
            hist = []
    idx = {(h["kod"], h["secenek"]): h for h in hist}
    for x in isaret:
        k = (x["kod"], x["secenek"])
        rec = {"tarih": day, "kod": x["kod"], "mac": x["mac"], "lig": x["lig"], "baslama": x["baslama"],
               "secenek": x["secenek"], "cizgi": float(x["pazar"][3:]), "iddaa_oran": x["iddaa_oran"],
               "adil_oran": x["adil_oran"], "dogru_olasilik": x["dogru_olasilik"], "deger": x["deger"],
               "kaynak": x["kaynak"], "kayit_zamani": iso_now(), "sonuc": None}
        if k in idx and idx[k].get("sonuc") is None:
            rec["ilk_kayit"] = idx[k].get("ilk_kayit") or idx[k]["kayit_zamani"]
            idx[k].update(rec)
        elif k not in idx:
            rec["ilk_kayit"] = rec["kayit_zamani"]
            hist.append(rec)
            idx[k] = rec
    settle(hist, now)
    sinir = (now.date() - dt.timedelta(days=TUT_GUN)).isoformat()
    hist = [h for h in hist if h["tarih"] >= sinir]
    hist.sort(key=lambda h: h["baslama"], reverse=True)

    out = {"tarih": day, "olusturma": iso_now(), "durum": durum,
           "kaynak_zamani": (ham or {}).get("cekilme_zamani"), "kalan_kredi": (ham or {}).get("kalan_kredi"),
           "eslesen_mac": len((ham or {}).get("eslesme", {})), "karsilastirilan": len(maclar),
           "aciklama": "Doğru olasılık: keskin piyasanın (Pinnacle > Betfair Borsa > Matchbook; yoksa ≥4 şirket "
                       "medyanı) marjsız Alt/Üst fiyatından çözülen gol beklentisiyle (Poisson) hesaplanır. "
                       "Değer = olasılık × iddaa oranı − 1. Keskin oran günde bir kez çekilir; arada fiyat değişebilir.",
           "isaretler": isaret, "maclar": maclar, "gecmis_ozet": summary(hist)}
    _dump(ROOT / "reports" / "keskin.json", out)
    _dump(ROOT / "reports" / "keskin_gecmis.json", {"guncelleme": iso_now(), "ozet": summary(hist), "kayitlar": hist})
    log = (ham or {}).get("log", [])
    print(f"Keskin karşılaştırma: {durum} | eşleşen {out['eslesen_mac']} | karşılaştırılan {len(maclar)} | "
          f"gerçek değer {len(isaret)} | kalan kredi {out['kalan_kredi']} | geçmiş {out['gecmis_ozet']}")
    for l in log:
        print("  ", l)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
