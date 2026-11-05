"""Adım 7: oranla karşılaştırma.

- İma edilen olasılık = 1/oran
- Marj temizleme: pazar içindeki açık seçeneklerin ima olasılıkları, olması gereken toplama
  (tek sonuçlu pazarlarda 1, Çifte Şans'ta 2) normalize edilir. Kapalı (1.00) seçenek varsa
  pazar normalize edilemez -> piyasa % "veri yok".
- Değer = model olasılığı × oran − 1  (pozitifse "değerli" işaretlenir)
- |model − piyasa| > 15 puan -> "şüpheli, muhtemelen eksik bilgi var"

Son tahmin piyasaya dayalıdır (model/market.py): iddaa'nın tüm ana pazarlarına uyan tek bir λ çifti.
Bu yüzden "değer", iddaa'nın bir pazarının kendi diğer pazarlarıyla tutarsız fiyatlanmasından doğar.
İstatistik modeli ikinci görüştür; piyasadan >15 puan ayrılırsa "şüpheli" işaretlenir.
"""
from __future__ import annotations

from .market import blend, fit_market_lambdas, load_weight
from .poisson import corners_market, markets

SUPHELI_ESIK = 0.15
TOPLAM = {"CS": 2.0}  # Çifte Şans seçenekleri örtüşür


def _model_key(key: str) -> str:
    return key


def anchor(match: dict, pred: dict) -> dict:
    """Taze oranlardan piyasa λ'sı + istatistik λ'sı karışımı -> son olasılıklar."""
    b = pred["bilesenler"]
    mkt = fit_market_lambdas(match, b["rho"], b["iy_gol_payi"])
    w = load_weight()
    lh, la, how = blend(pred["lambda"], mkt, float(w["w_istatistik"]))
    P = markets(lh, la, b["rho"], b["iy_gol_payi"])
    return {"lambda": {"ev": round(lh, 3), "dep": round(la, 3)}, "yontem": how, "agirlik": w,
            "piyasa_lambda": {"ev": round(mkt["ev"], 3), "dep": round(mkt["dep"], 3), "uyum_rmse": round(mkt["rmse"], 4),
                              "pazarlar": mkt["pazarlar"]} if mkt else None,
            "istatistik_lambda": pred["lambda"], "olasiliklar": P}


def evaluate_match(match: dict, pred: dict, stats: dict | None) -> tuple[list[dict], dict]:
    A = anchor(match, pred)
    P = A["olasiliklar"]                 # son tahmin (piyasaya dayalı)
    S = pred["olasiliklar"]              # istatistik modeli (ikinci görüş)
    out = []
    for mk in match["pazarlar"]:
        key = mk["key"]
        if not key:
            continue
        probs = None
        reliability = "normal"
        if key.startswith("KORNER_AU_"):
            kk = (stats or {}).get("kart_korner", {})
            e, d = kk.get("ev", {}).get("mac_korner_ort"), kk.get("dep", {}).get("mac_korner_ort")
            if e is not None and d is not None:
                probs = corners_market((e + d) / 2, float(mk["line"]))
                reliability = "düşük (korner modeli basit Poisson, son 6 maç)"
        elif key in P:
            probs = P[key]
        if not probs:
            continue
        base = key.split("_")[0] if key.startswith(("CS",)) else key
        expected_total = TOPLAM.get(base, 1.0)
        opens = [o for o in mk["outcomes"] if not o["closed"]]
        normalizable = len(opens) == len(mk["outcomes"]) and len(opens) >= 2
        inv_sum = sum(1 / o["odd"] for o in opens) if normalizable else None
        margin = (inv_sum / expected_total - 1) if inv_sum else None
        for o in mk["outcomes"]:
            pm = probs.get(o["name"])
            pm = None if pm is None else float(pm)
            if pm is None:
                continue
            ps = (S.get(key) or {}).get(o["name"]) if not key.startswith("KORNER_AU_") else None
            rec = {"pazar": key, "pazar_adi": mk["name"], "secenek": o["name"], "oran": o["odd"],
                   "kapali": o["closed"], "mbs": mk["mbs"] or match["mbs"], "model": round(pm, 4),
                   "istatistik": round(float(ps), 4) if ps is not None else None,
                   "oran_zamani": mk["odds_fetched_at"], "guvenilirlik": reliability}
            if o["closed"]:
                rec.update({"piyasa": None, "deger": None, "not": "seçenek kapalı (oran 1.00)"})
                out.append(rec)
                continue
            pk = (1 / o["odd"]) / inv_sum * expected_total if normalizable else None
            rec["ima"] = round(1 / o["odd"], 4)
            rec["piyasa"] = round(pk, 4) if pk is not None else None
            rec["marj"] = round(margin, 4) if margin is not None else None
            rec["deger"] = round(pm * o["odd"] - 1, 4)
            rec["degerli"] = bool(rec["deger"] > 0)
            # fark: son tahmin − bu pazarın kendi marjsız fiyatı (iddaa'nın pazarlar arası tutarsızlığı)
            rec["fark"] = round(pm - pk, 4) if pk is not None else None
            # şüpheli: istatistik modeli piyasadan >15 puan ayrılıyor -> eksik bilgi olabilir
            rec["istatistik_farki"] = round(float(ps) - pm, 4) if ps is not None else None
            rec["supheli"] = bool(ps is not None and abs(float(ps) - pm) > SUPHELI_ESIK)
            out.append(rec)
    return out, A
