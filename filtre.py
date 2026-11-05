"""Adım 3: genel (güne bağlı olmayan) maç filtresi. Kurallar config/filtre.json'da."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from scrapers.common import now_tr
from scrapers.iddaa import market

CFG_PATH = Path(__file__).resolve().parent / "config" / "filtre.json"


def load_cfg() -> dict:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def _any(patterns, text):
    return next((p for p in patterns if re.search(p, text, re.I)), None)


def classify(match: dict, cfg: dict, now: dt.datetime) -> tuple[int | None, str]:
    """(seviye, gerekçe). seviye None ise maç elenir."""
    lig = match["lig"]
    for etiket, pat in cfg["her_zaman_ele"].items():
        if re.search(pat, lig, re.I):
            return None, f"lig türü dışarıda ({etiket})"
    if re.search(cfg["takim_adi_ele"], match["ev"]) or re.search(cfg["takim_adi_ele"], match["deplasman"]):
        return None, "kadın/genç/B takımı"

    start = dt.datetime.fromisoformat(match["baslama"])
    kalan = (start - now).total_seconds() / 60
    if kalan < cfg["min_baslamaya_dakika"]:
        return None, f"başlamasına {kalan:.0f} dk var; analiz yetişmez (min {cfg['min_baslamaya_dakika']})"

    ms = market(match, "MS")
    if cfg["ms_pazari_zorunlu"] and (not ms or all(o["closed"] for o in ms["outcomes"])):
        return None, "MS pazarı yok/kapalı"
    if len(match["pazarlar"]) < cfg["min_pazar_sayisi"]:
        return None, f"sınırlı pazar ({len(match['pazarlar'])} < {cfg['min_pazar_sayisi']})"

    if _any(cfg["seviye_1_oncelikli"], lig):
        return 1, "öncelikli lig"
    if _any(cfg["seviye_2_buyuk_ikinci_ligler"], lig):
        return 2, "büyük ikinci lig / güçlü lig"
    if cfg["seviye_3_dahil_et"]:
        return 3, "diğer lig (düşük veri olasılığı)"
    return None, "öncelik listesi dışındaki lig"


def apply_filter(bulletin: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or load_cfg()
    now = now_tr()
    secilen, elenen = [], []
    for m in bulletin["maclar"]:
        tier, why = classify(m, cfg, now)
        rec = {"mac_kodu": m["mac_kodu"], "saat": m["saat"], "lig": m["lig"],
               "mac": f"{m['ev']} - {m['deplasman']}", "mbs": m["mbs"], "gerekce": why}
        if tier is None:
            elenen.append(rec)
        else:
            secilen.append({**rec, "seviye": tier})
    # Seviye önce, sonra başlama saati; kapasite aşılırsa kalanlar elenir
    secilen.sort(key=lambda r: (r["seviye"], r["saat"]))
    cap = cfg["max_detayli_analiz"]
    for r in secilen[cap:]:
        elenen.append({**r, "gerekce": f"günlük analiz kapasitesi ({cap}) doldu"})
    return {"filtre_zamani": now.isoformat(timespec="seconds"), "kurallar": str(CFG_PATH.name),
            "secilen": secilen[:cap], "elenen": elenen}
