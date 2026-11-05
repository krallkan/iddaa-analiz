"""Maç başına λ hesabı: lig güçleri + ligler arası UEFA ayarı (α kalibrasyonu) + manuel haber düzeltmeleri."""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import statistics
from pathlib import Path

from scipy.optimize import minimize_scalar

from scrapers.uefa import fd_country, league_country
from .poisson import fallback_rating, fit_league, fit_rho, markets

AVRUPA = re.compile(r"UEFA|Avrupa Ligi|Konferans|Şampiyonlar|Champions|Europa|Conference", re.I)


class Engine:
    def __init__(self, fd, stats: dict, bulletin: dict, uefa: dict, day: dt.date, manual_path: Path):
        self.fd, self.stats, self.b, self.day = fd, stats["maclar"], bulletin, day
        self.coef = uefa["katsayi"]
        self.uefa_src = uefa["kaynak"]
        self.fits = {code: f for code, L in fd.leagues.items() if (f := fit_league(L, day))}
        self.mu_med = statistics.median(f["mu"] for f in self.fits.values())
        self.h_med = statistics.median(f["h"] for f in self.fits.values())
        self.iy_med = statistics.median(f["iy_pay"] for f in self.fits.values() if f["iy_pay"])
        self.rho = self._fit_rho()
        self.country_by_name = self._countries_from_bulletin()
        self.ratings = self._team_ratings()
        self.alpha = self._calibrate_alpha()
        man = json.loads(manual_path.read_text(encoding="utf-8")) if manual_path.exists() else {}
        self.manual = [d for d in man.get("duzeltmeler", []) if d.get("tarih") == day.isoformat()]

    # ---- yardımcılar ----
    def _fit_rho(self) -> float:
        samples = []
        for f in self.fits.values():
            for h, a, x, y in f["rows"]:
                if h in f["att"] and a in f["att"]:
                    lh = math.exp(f["mu"] + f["h"] + f["att"][h] - f["def"][a])
                    la = math.exp(f["mu"] + f["att"][a] - f["def"][h])
                    samples.append((lh, la, int(x), int(y)))
        return fit_rho(samples)

    def _countries_from_bulletin(self) -> dict:
        """Bültendeki (5 gün) yurt içi lig maçlarından takım -> ülke."""
        out = {}
        cfg = Path(__file__).resolve().parent.parent / "config" / "takim_ulke.json"
        if cfg.exists():
            out.update({k: v for k, v in json.loads(cfg.read_text(encoding="utf-8")).items() if not k.startswith("_")})
        for e in self.b["tum_gunler"]:
            c = league_country(e["lig"])
            if c and not AVRUPA.search(e["lig"]):
                out.setdefault(e["ev"], c); out.setdefault(e["deplasman"], c)
        return out

    def _team_ratings(self) -> dict:
        r = {}
        for code, st in self.stats.items():
            m = next(x for x in self.b["maclar"] if str(x["mac_kodu"]) == str(code))
            for side, name in (("ev", m["ev"]), ("dep", m["deplasman"])):
                prof = st["fd"][side]
                if prof.get("fd_takim") and prof["lig_kodu"] in self.fits:
                    f = self.fits[prof["lig_kodu"]]
                    t = prof["fd_takim"]
                    r[name] = {"att": f["att"][t], "def": f["def"][t], "mu": f["mu"], "h": f["h"],
                               "iy_pay": f["iy_pay"] or self.iy_med,
                               "ulke": fd_country(prof["lig_kodu"]), "lig": prof["lig"],
                               "kaynak": f"football-data {prof['lig_kodu']} (zaman ağırlıklı, "
                                         f"{f['agirlikli_mac'][t]:.1f} ağırlıklı maç)",
                               "kalite": 1.0 if prof.get("xg_ort") is not None else 0.85}
                else:
                    fb = fallback_rating(st[side])
                    c = self.country_by_name.get(name) or league_country(m["lig"])
                    r[name] = {"att": fb["att"], "def": fb["def"], "mu": self.mu_med, "h": self.h_med,
                               "iy_pay": self.iy_med, "ulke": c, "lig": None,
                               "kaynak": fb["kaynak"], "kalite": 0.45 if fb["kaynak"] != "veri yok" else 0.0}
        return r

    def _calibrate_alpha(self) -> dict:
        """Takımların son maçlarındaki Avrupa kupası sonuçlarından α'nın MLE tahmini."""
        obs, seen = [], set()
        for code, st in self.stats.items():
            m = next(x for x in self.b["maclar"] if str(x["mac_kodu"]) == str(code))
            for side, name in (("ev", m["ev"]), ("dep", m["deplasman"])):
                for g in st[side]["maclar"]:
                    if not g["turnuva"] or not AVRUPA.search(g["turnuva"]):
                        continue
                    opp = g["rakip"]
                    a, b = self.ratings.get(name), self.ratings.get(opp)
                    if not a or not b or not a["ulke"] or not b["ulke"] or a["ulke"] == b["ulke"]:
                        continue
                    if a["ulke"] not in self.coef or b["ulke"] not in self.coef:
                        continue
                    key = (g["tarih"], *sorted((name, opp)))
                    if key in seen:
                        continue
                    seen.add(key)
                    home, away = (a, b) if g["ic_saha"] else (b, a)
                    gh, ga = (g["atilan"], g["yenilen"]) if g["ic_saha"] else (g["yenilen"], g["atilan"])
                    mu = (home["mu"] + away["mu"]) / 2
                    dc = math.log(self.coef[home["ulke"]]) - math.log(self.coef[away["ulke"]])
                    obs.append((mu + home["h"] + home["att"] - away["def"], mu + away["att"] - home["def"], dc, gh, ga))
        n = len(obs)
        if n < 15:
            return {"alpha": None, "orneklem": n, "not": "kalibrasyon için yetersiz örnek; ligler arası ayar yapılmadı"}

        def nll(al):
            s = 0.0
            for bh, ba, dc, gh, ga in obs:
                lh, la = bh + al * dc, ba - al * dc
                s -= gh * lh - math.exp(lh) + ga * la - math.exp(la)
            return s
        res = minimize_scalar(nll, bounds=(0.0, 1.0), method="bounded")
        al = float(res.x)
        # standart hata (sayısal 2. türev)
        e = 1e-3
        h2 = (nll(al + e) - 2 * nll(al) + nll(al - e)) / e**2
        se = 1 / math.sqrt(h2) if h2 > 0 else None
        return {"alpha": round(al, 4), "std_hata": round(se, 4) if se else None, "orneklem": n,
                "kaynak": self.uefa_src}

    # ---- maç tahmini ----
    def predict(self, match: dict) -> dict:
        h, a = self.ratings[match["ev"]], self.ratings[match["deplasman"]]
        same_league = h["lig"] is not None and h["lig"] == a["lig"]
        mu = h["mu"] if same_league else (h["mu"] + a["mu"]) / 2
        base_h = mu + h["h"] + h["att"] - a["def"]
        base_a = mu + a["att"] - h["def"]
        notes, cross = [], 0.0
        al = self.alpha.get("alpha")
        if h["ulke"] != a["ulke"]:
            if al is not None and h["ulke"] in self.coef and a["ulke"] in self.coef:
                cross = al * (math.log(self.coef[h["ulke"]]) - math.log(self.coef[a["ulke"]]))
                notes.append(f"Ligler arası ayar: α={al} × (ln C[{h['ulke']}]={math.log(self.coef[h['ulke']]):.2f} − "
                             f"ln C[{a['ulke']}]={math.log(self.coef[a['ulke']]):.2f}) = {cross:+.3f} (log-λ)")
            else:
                notes.append(f"Ligler arası ayar YAPILAMADI (ülke/katsayı veya α yok: {h['ulke']} / {a['ulke']})")
        lh, la = math.exp(base_h + cross), math.exp(base_a - cross)
        adj = []
        for d in self.manual:
            if int(d["mac_kodu"]) != int(match["mac_kodu"]):
                continue
            c, rc = float(d.get("carpan", 1.0)), float(d.get("rakip_carpan", 1.0))
            if d["takim"] == "ev":
                lh *= c; la *= rc
            else:
                la *= c; lh *= rc
            adj.append({k: d.get(k) for k in ("takim", "carpan", "rakip_carpan", "gerekce", "kaynak", "kaynak_tarihi")})
        iy = (h["iy_pay"] + a["iy_pay"]) / 2
        p = markets(lh, la, self.rho, iy)
        return {"lambda": {"ev": round(lh, 3), "dep": round(la, 3)},
                "bilesenler": {"ev": {k: h[k] for k in ("att", "def", "ulke", "kaynak", "kalite")},
                               "dep": {k: a[k] for k in ("att", "def", "ulke", "kaynak", "kalite")},
                               "mu": round(mu, 3), "ev_avantaji": round(h["h"], 3), "ligler_arasi": round(cross, 3),
                               "rho": round(self.rho, 4), "iy_gol_payi": round(iy, 3)},
                "notlar": notes, "manuel_duzeltmeler": adj, "olasiliklar": p,
                "veri_kalitesi": round((h["kalite"] + a["kalite"]) / 2, 2)}
