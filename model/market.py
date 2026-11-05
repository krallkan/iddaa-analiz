"""Piyasaya dayalı model: iddaa oranlarından (marj temizlenmiş) tek bir (λ_ev, λ_dep) çifti çıkarılır.

Uyum: MS 1/X/2, Alt/Üst 1.5-2.5-3.5, KG, Çifte Şans ve handikap pazarlarının marjsız olasılıklarına
ağırlıklı kareler toplamı ile en iyi uyan λ çifti. Kapalı seçenekli pazarlar (ör. MS 1 = 1.00) atlanır.
Son tahmin:  λ = λ_piyasa^(1−w) · λ_istatistik^w   (w geri testten; config/model.json)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from .poisson import markets

CFG = Path(__file__).resolve().parent.parent / "config" / "model.json"
FIT_KEYS = {"MS": 2.0, "AU_2.5": 1.5, "AU_1.5": 1.0, "AU_3.5": 1.0, "KG": 1.0, "CS": 0.5,
            "HMS_1:0": 0.5, "HMS_0:1": 0.5, "HMS_2:0": 0.5, "HMS_0:2": 0.5}
CS_TOTAL = 2.0


def load_weight() -> dict:
    if CFG.exists():
        return json.loads(CFG.read_text(encoding="utf-8"))
    return {"w_istatistik": 0.0, "kaynak": "varsayılan (geri test yok) — saf piyasa"}


def demargin(mk: dict) -> dict | None:
    """Pazarın marjsız olasılıkları; kapalı seçenek varsa None."""
    outs = mk["outcomes"]
    if any(o["closed"] for o in outs) or len(outs) < 2:
        return None
    inv = {o["name"]: 1 / o["odd"] for o in outs}
    tot = CS_TOTAL if mk["key"] == "CS" else 1.0
    s = sum(inv.values())
    return {k: v / s * tot for k, v in inv.items()}


def market_targets(match: dict) -> dict:
    t = {}
    for mk in match["pazarlar"]:
        if mk["key"] in FIT_KEYS:
            d = demargin(mk)
            if d:
                t[mk["key"]] = d
    return t


def fit_market_lambdas(match: dict, rho: float, iy_pay: float) -> dict | None:
    tg = market_targets(match)
    if "MS" not in tg and not ({"AU_2.5", "KG"} <= tg.keys() or "CS" in tg):
        return None

    def loss(x):
        lh, la = math.exp(x[0]), math.exp(x[1])
        P = markets(lh, la, rho, iy_pay, full=False)
        err = 0.0
        for k, probs in tg.items():
            w = FIT_KEYS[k]
            for name, q in probs.items():
                p = P.get(k, {}).get(name)
                if p is not None:
                    err += w * (p - q) ** 2
        return err

    best = None
    for start in ((0.3, 0.1), (0.0, 0.3), (0.6, -0.3), (-0.3, 0.6)):
        r = minimize(loss, np.array(start), method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-8})
        if best is None or r.fun < best.fun:
            best = r
    lh, la = math.exp(best.x[0]), math.exp(best.x[1])
    n = sum(len(v) for v in tg.values())
    return {"ev": lh, "dep": la, "rmse": math.sqrt(best.fun / max(n, 1)), "pazarlar": sorted(tg)}


def blend(stat: dict, mkt: dict | None, w: float) -> tuple[float, float, str]:
    if mkt is None:
        return stat["ev"], stat["dep"], "piyasa λ çıkarılamadı → yalnızca istatistik modeli"
    lh = math.exp((1 - w) * math.log(mkt["ev"]) + w * math.log(stat["ev"]))
    la = math.exp((1 - w) * math.log(mkt["dep"]) + w * math.log(stat["dep"]))
    return lh, la, f"λ = piyasa^{1 - w:.2f} · istatistik^{w:.2f}"
