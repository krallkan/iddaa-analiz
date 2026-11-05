"""Adım 6: güç değerleri, beklenen goller (λ), Dixon-Coles skor matrisi ve pazar olasılıkları.

Lig içi model (her lig ayrı, football-data verisi):
    log λ_ev  = μ + h + hücum_ev  − savunma_dep
    log λ_dep = μ     + hücum_dep − savunma_ev
  - Hedef: gol ile xG'nin ağırlıklı karışımı (xG varsa %50/%50) -> şansa daha az duyarlı.
  - Zaman ağırlığı: w = 0.5 ** (gün / YARI_OMUR) -> son maçlar daha ağır.
  - Ridge cezası: az maçlı takımları lig ortalamasına çeker.
Ligler arası (Avrupa kupaları vb.):
    log λ_ev += α · (ln C_ev − ln C_dep),  log λ_dep += α · (ln C_dep − ln C_ev)
  C = UEFA ülke katsayısı; α takımların son Avrupa kupası maçlarından MLE ile kalibre edilir.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

from scrapers.footballdata import parse_date

YARI_OMUR_GUN = 180
RIDGE = 2.0
XG_AGIRLIK = 0.5
MAXG = 8  # 0..7


# ---------------- lig içi güç modeli ----------------

def _rows_for_fit(league: dict, day: dt.date) -> list[tuple]:
    rows = []
    for m in league.get("onceki_sezon", []) + league["maclar"]:
        d = parse_date(m["tarih"])
        if d is None or d >= day or m["eg"] is None:
            continue
        w = 0.5 ** ((day - d).days / YARI_OMUR_GUN)
        ye = m["eg"] if m["exg"] is None else (1 - XG_AGIRLIK) * m["eg"] + XG_AGIRLIK * m["exg"]
        ya = m["dg"] if m["dxg"] is None else (1 - XG_AGIRLIK) * m["dg"] + XG_AGIRLIK * m["dxg"]
        rows.append((m["ev"], m["dep"], ye, ya, w, m["eg"], m["dg"]))
    return rows


def fit_league(league: dict, day: dt.date) -> dict | None:
    rows = _rows_for_fit(league, day)
    if len(rows) < 30:
        return None
    teams = sorted({r[0] for r in rows} | {r[1] for r in rows})
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = np.array([ix[r[0]] for r in rows]); ai = np.array([ix[r[1]] for r in rows])
    yh = np.array([r[2] for r in rows]); ya = np.array([r[3] for r in rows]); w = np.array([r[4] for r in rows])

    def nll(p):
        mu, h, att, de = p[0], p[1], p[2:2 + n], p[2 + n:]
        lh = mu + h + att[hi] - de[ai]
        la = mu + att[ai] - de[hi]
        eh, ea = np.exp(lh), np.exp(la)
        f = -np.sum(w * (yh * lh - eh + ya * la - ea)) + RIDGE * (att @ att + de @ de)
        g = np.zeros_like(p)
        rh, ra = w * (yh - eh), w * (ya - ea)
        g[0] = -(rh.sum() + ra.sum()); g[1] = -rh.sum()
        ga = np.zeros(n); gd = np.zeros(n)
        np.add.at(ga, hi, -rh); np.add.at(ga, ai, -ra)
        np.add.at(gd, ai, rh); np.add.at(gd, hi, ra)
        g[2:2 + n] = ga + 2 * RIDGE * att
        g[2 + n:] = gd + 2 * RIDGE * de
        return f, g

    p0 = np.zeros(2 + 2 * n); p0[0] = math.log(max(ya.mean(), 0.3)); p0[1] = 0.2
    res = minimize(nll, p0, jac=True, method="L-BFGS-B")
    p = res.x
    att, de = p[2:2 + n], p[2 + n:]
    # ağırlıklı maç sayısı (veri miktarı göstergesi)
    wcount = {t: 0.0 for t in teams}
    for r in rows:
        wcount[r[0]] += r[4]; wcount[r[1]] += r[4]
    # İY gol payı (İY/MS ve İY pazarları için)
    ht = [(m["iy_eg"] + m["iy_dg"], m["eg"] + m["dg"]) for m in league["maclar"] + league.get("onceki_sezon", [])
          if m.get("iy_eg") is not None and m["eg"] is not None]
    iy_pay = (sum(a for a, _ in ht) / max(sum(b for _, b in ht), 1)) if len(ht) >= 50 else None
    return {"mu": float(p[0]), "h": float(p[1]), "att": dict(zip(teams, map(float, att))),
            "def": dict(zip(teams, map(float, de))), "agirlikli_mac": wcount, "mac": len(rows),
            "iy_pay": iy_pay, "basarili": bool(res.success),
            "rows": [(r[0], r[1], r[5], r[6]) for r in rows[-400:]]}


def fallback_rating(summary: dict, lig_ort_takim_gol: float = 1.35, k: float = 5.0) -> dict:
    """football-data'da olmayan takım: iddaa son 10 maç (rakip gücü bilinmiyor), lig ortalamasına çekilmiş."""
    s = summary["son10"]
    n = s["mac"] or 0
    if not n:
        return {"att": 0.0, "def": 0.0, "kaynak": "veri yok"}
    gf, ga = s["atilan_ort"] * n, s["yenilen_ort"] * n
    m = lig_ort_takim_gol
    att = math.log(((gf + k * m) / (n + k)) / m)
    de = -math.log(((ga + k * m) / (n + k)) / m)
    return {"att": att, "def": de, "kaynak": f"iddaa son {n} maç (rakip gücü düzeltilmemiş)"}


# ---------------- Dixon-Coles ----------------

def _tau(x, y, lh, la, rho):
    if x == 0 and y == 0:
        return 1 - lh * la * rho
    if x == 0 and y == 1:
        return 1 + lh * rho
    if x == 1 and y == 0:
        return 1 + la * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def score_matrix(lh: float, la: float, rho: float = 0.0, maxg: int = MAXG) -> np.ndarray:
    ph = poisson.pmf(np.arange(maxg), lh)
    pa = poisson.pmf(np.arange(maxg), la)
    M = np.outer(ph, pa)
    for x in (0, 1):
        for y in (0, 1):
            M[x, y] *= _tau(x, y, lh, la, rho)
    M = np.clip(M, 0, None)
    return M / M.sum()   # 7'den fazla gol olasılığı (çok küçük) yeniden dağıtılır


def fit_rho(samples: list[tuple[float, float, int, int]]) -> float:
    """Ortak ρ: verilen (λev, λdep, gol_ev, gol_dep) örnekleri üzerinden MLE."""
    def nll(r):
        s = 0.0
        for lh, la, x, y in samples:
            if x <= 1 and y <= 1:
                t = _tau(x, y, lh, la, r)
                if t <= 0:
                    return 1e9
                s -= math.log(t)
        return s
    return float(minimize_scalar(nll, bounds=(-0.2, 0.2), method="bounded").x)


# ---------------- pazarlar ----------------

def markets(lh: float, la: float, rho: float, iy_pay: float = 0.45, full: bool = True) -> dict:
    M = score_matrix(lh, la, rho)
    g = np.arange(MAXG)
    tot = g[:, None] + g[None, :]
    diff = g[:, None] - g[None, :]
    p = {}
    p["MS"] = {"1": float(M[diff > 0].sum()), "0": float(M[diff == 0].sum()), "2": float(M[diff < 0].sum())}
    p["CS"] = {"1 ve 0": p["MS"]["1"] + p["MS"]["0"], "1 ve 2": p["MS"]["1"] + p["MS"]["2"],
               "0 ve 2": p["MS"]["0"] + p["MS"]["2"]}
    for line in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
        u = float(M[tot > line].sum())
        p[f"AU_{line}"] = {"Alt": 1 - u, "Üst": u}
    kg = float(M[1:, 1:].sum())
    p["KG"] = {"Var": kg, "Yok": 1 - kg}
    p["TOPLAM_GOL"] = {"0-1 gol": float(M[tot <= 1].sum()), "2-3 gol": float(M[(tot >= 2) & (tot <= 3)].sum()),
                       "4-5 gol": float(M[(tot >= 4) & (tot <= 5)].sum()), "6+ gol": float(M[tot >= 6].sum())}
    # Handikap (iddaa "a:b": ev sahibine a, deplasmana b gol avans; 3 yollu)
    for hcp in (1, 2, 3):
        d1 = diff + hcp
        p[f"HMS_{hcp}:0"] = {"1": float(M[d1 > 0].sum()), "0": float(M[d1 == 0].sum()), "2": float(M[d1 < 0].sum())}
        d2 = diff - hcp
        p[f"HMS_0:{hcp}"] = {"1": float(M[d2 > 0].sum()), "0": float(M[d2 == 0].sum()), "2": float(M[d2 < 0].sum())}
    if not full:   # λ uydurma sırasında yalnızca maç sonu pazarları gerekir
        return p
    # İlk yarı / ikinci yarı: bağımsız Poisson yarılar (ρ yalnız maç sonu matrisinde)
    H1 = score_matrix(lh * iy_pay, la * iy_pay, 0.0)
    H2 = score_matrix(lh * (1 - iy_pay), la * (1 - iy_pay), 0.0)
    d1 = diff
    p["IY"] = {"1": float(H1[d1 > 0].sum()), "0": float(H1[d1 == 0].sum()), "2": float(H1[d1 < 0].sum())}
    for line in (0.5, 1.5, 2.5):
        u = float(H1[tot > line].sum())
        p[f"IY_AU_{line}"] = {"Alt": 1 - u, "Üst": u}
    p["IY_KG"] = {"Var": float(H1[1:, 1:].sum()), "Yok": 1 - float(H1[1:, 1:].sum())}
    # İY/MS: ilk yarı skoru + ikinci yarı skoru
    iyms = {f"{a}/{b}": 0.0 for a in "102" for b in "102"}
    sign = lambda v: "1" if v > 0 else "0" if v == 0 else "2"  # noqa: E731
    for x1 in range(MAXG):
        for y1 in range(MAXG):
            q1 = H1[x1, y1]
            if q1 < 1e-7:
                continue
            for x2 in range(MAXG):
                for y2 in range(MAXG):
                    q = q1 * H2[x2, y2]
                    if q < 1e-9:
                        continue
                    iyms[f"{sign(x1 - y1)}/{sign(x1 + x2 - y1 - y2)}"] += q
    s = sum(iyms.values())
    p["IYMS"] = {k: v / s for k, v in iyms.items()}
    # En olası skorlar
    flat = sorted(((float(M[x, y]), f"{x}-{y}") for x in range(MAXG) for y in range(MAXG)), reverse=True)
    p["_en_olasi_skorlar"] = [{"skor": sc, "olasilik": round(q, 4)} for q, sc in flat[:3]]
    p["_lambda"] = {"ev": round(lh, 3), "dep": round(la, 3)}
    return p


def corners_market(mean_total: float | None, line: float) -> dict | None:
    """Toplam korner ~ Poisson(ortalama). Kornerler aşırı yayılımlı olduğundan düşük güvenilirlik."""
    if mean_total is None:
        return None
    u = 1 - poisson.cdf(math.floor(line), mean_total)
    return {"Alt": float(1 - u), "Üst": float(u)}
