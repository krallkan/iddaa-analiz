"""Adım 4: maç istatistikleri.

Kaynaklar (2026-11-05 erişim testi):
  1) iddaa istatistik servisi (Betradar/Perform verisi), maç kodu ile doğrudan:
     https://statisticsv2.iddaa.com/statistics/soccer/<tür>/<maç_kodu>
       recent-matches?matchHistoryType=0|1|2  -> ev son 10 | deplasman son 10 | kafa kafaya
       card-corners      -> son 6 maç kart/korner
       standings         -> puan durumu (maçın turnuvası)
       lineup            -> muhtemel 11 + teknik direktör  (ÖNBELLEĞE ALINMAZ)
       bet-insights      -> kısa istatistik notları
  2) football-data.co.uk sezon CSV'leri -> lig ortalamaları, xG, iç/dış saha (scrapers/footballdata.py)
  Sofascore/FBref/Mackolik: 403 (bot koruması), ClubElo: bağlantı reddediliyor.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .common import TR_TZ, ScrapeError, iso_now, make_client, polite_sleep

STATS = "https://statisticsv2.iddaa.com/statistics/soccer"
HEADERS = {"Origin": "https://www.iddaa.com", "Referer": "https://www.iddaa.com/"}


class IddaaStats:
    def __init__(self, cache_dir: Path):
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)
        self.client = make_client(**HEADERS)
        self.log: list[dict] = []

    def get(self, path: str, cache: bool = True) -> dict | None:
        """JSON 'data' alanını döndürür; erişilemezse None (veri yok)."""
        url = f"{STATS}/{path}"
        f = self.cache / (path.replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "-") + ".json")
        if cache and f.exists():
            j = json.loads(f.read_text(encoding="utf-8"))
            self.log.append({"url": url, "fetched_at": j["fetched_at"], "cache": True})
            return j["data"]
        try:
            r = self.client.get(url)
            polite_sleep()
            body = r.json() if r.status_code == 200 else {}
        except Exception as e:  # noqa: BLE001
            self.log.append({"url": url, "error": repr(e), "fetched_at": iso_now()})
            return None
        if not body.get("isSuccess") or body.get("data") is None:
            self.log.append({"url": url, "status": r.status_code, "error": body.get("message") or "veri yok",
                             "fetched_at": iso_now()})
            return None
        rec = {"url": url, "fetched_at": iso_now(), "data": body["data"]}
        if cache:
            f.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        self.log.append({"url": url, "fetched_at": rec["fetched_at"], "cache": False})
        return body["data"]

    def close(self):
        self.client.close()


# ---------- özetleme ----------

def _norm_match(m: dict, team: str) -> dict:
    """iddaa son-maç kaydını takım perspektifine çevirir."""
    home = m["h"]["n"] == team
    me, op = (m["h"], m["a"]) if home else (m["a"], m["h"])
    ts = dt.datetime.fromtimestamp(m["t"], TR_TZ)
    gf, ga = me.get("rs"), op.get("rs")
    hgf, hga = me.get("fhs"), op.get("fhs")
    res = None if gf is None or ga is None else ("G" if gf > ga else "B" if gf == ga else "M")
    return {"tarih": ts.date().isoformat(), "ts": m["t"], "turnuva": (m.get("l") or {}).get("n"), "ic_saha": home,
            "rakip": op["n"], "atilan": gf, "yenilen": ga, "iy_atilan": hgf, "iy_yenilen": hga, "sonuc": res}


def team_matches(raw: dict | None, team_key: str) -> list[dict]:
    if not raw:
        return []
    team = (raw.get(team_key) or {}).get("n")
    out = [_norm_match(m, team) for m in raw.get("m", [])
           if m.get("h") and m.get("a") and team in (m["h"].get("n"), m["a"].get("n"))]
    return sorted(out, key=lambda x: -x["ts"])


def _pct(xs):
    return round(100 * sum(xs) / len(xs), 1) if xs else None


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def summarize(ms: list[dict], now: dt.datetime) -> dict:
    ms = [m for m in ms if m["atilan"] is not None]
    home = [m for m in ms if m["ic_saha"]][:5]
    away = [m for m in ms if not m["ic_saha"]][:5]
    last7 = [m for m in ms if (now - dt.datetime.fromtimestamp(m["ts"], TR_TZ)).days < 7]
    pts = [3 if m["sonuc"] == "G" else 1 if m["sonuc"] == "B" else 0 for m in ms]

    def block(xs):
        return {
            "mac": len(xs),
            "form": "".join(m["sonuc"] for m in xs),
            "atilan_ort": _avg([m["atilan"] for m in xs]),
            "yenilen_ort": _avg([m["yenilen"] for m in xs]),
            "ust25_yuzde": _pct([m["atilan"] + m["yenilen"] > 2.5 for m in xs]),
            "kg_var_yuzde": _pct([m["atilan"] > 0 and m["yenilen"] > 0 for m in xs]),
            "gol_yemeden_yuzde": _pct([m["yenilen"] == 0 for m in xs]),
            "iy_gol_ort": _avg([(m["iy_atilan"] or 0) + (m["iy_yenilen"] or 0) for m in xs
                                if m["iy_atilan"] is not None]),
            "iy_gol_olan_yuzde": _pct([(m["iy_atilan"] or 0) + (m["iy_yenilen"] or 0) > 0 for m in xs
                                       if m["iy_atilan"] is not None]),
        }

    # form istikrarı: puan dizisinin standart sapması (0 = çok istikrarlı, ~1.5 = çok dalgalı)
    if len(pts) >= 3:
        mu = sum(pts) / len(pts)
        sd = (sum((p - mu) ** 2 for p in pts) / len(pts)) ** 0.5
    else:
        sd = None
    return {"son10": block(ms[:10]), "ic_saha_son5": block(home), "dis_saha_son5": block(away),
            "son7_gun_mac": len(last7), "puan_sd": round(sd, 2) if sd is not None else None,
            "son_mac": ms[0]["tarih"] if ms else None, "maclar": ms[:10]}


def cards_corners(raw: dict | None, side: str) -> dict:
    """Son 6 maçın kart/korner ortalamaları maç listesinden hesaplanır.
    (Kaynağın 'ca' özet alanının anlamı belirsiz olduğu için kullanılmıyor.)"""
    if not raw or side not in raw:
        return {"veri": "veri yok"}
    t = raw[side]
    me = t.get("n")
    own_y, own_c, tot_card, tot_c = [], [], [], []
    for m in t.get("m", []):
        h, a = m.get("h", {}), m.get("a", {})
        mine, opp = (h, a) if h.get("n") == me else (a, h)
        own_y.append(mine.get("yc", 0) + mine.get("rc", 0))
        tot_card.append(h.get("yc", 0) + h.get("rc", 0) + a.get("yc", 0) + a.get("rc", 0))
        if (h.get("c", 0), a.get("c", 0)) != (0, 0):   # 0-0 korner = kaynakta veri yok
            own_c.append(mine.get("c", 0))
            tot_c.append(h.get("c", 0) + a.get("c", 0))
    n = len(tot_card)
    card_ok = n >= 4 and (_avg(tot_card) or 0) >= 1.5   # maç başı <1.5 kart gerçekçi değil -> eksik kayıt
    corner_ok = len(tot_c) >= 4
    return {
        "mac": n,
        "takim_kart_ort": _avg(own_y) if card_ok else None,
        "mac_kart_ort": _avg(tot_card) if card_ok else None,
        "kart_not": None if card_ok else f"kart verisi eksik/yetersiz (maç başı {_avg(tot_card)})",
        "korner_veri_mac": len(tot_c),
        "takim_korner_ort": _avg(own_c) if corner_ok else None,
        "mac_korner_ort": _avg(tot_c) if corner_ok else None,
        "not": None if corner_ok else "korner verisi yetersiz (veri yok)",
    }


def standings_info(raw: dict | None, home: str, away: str) -> dict:
    if not raw:
        return {"veri": "veri yok"}
    rows = [dict(r, grup=g.get("n")) for g in raw.get("g", []) for r in g.get("t", [])]
    find = lambda n: next((r for r in rows if r["n"] == n), None)  # noqa: E731
    h, a = find(home), find(away)
    return {
        "turnuva": raw.get("ss", {}).get("n"),
        "takim_sayisi": len(rows),
        "ev": {k: h.get(k) for k in ("r", "p", "w", "d", "l", "gf", "ga", "pt", "f")} if h else "veri yok",
        "dep": {k: a.get(k) for k in ("r", "p", "w", "d", "l", "gf", "ga", "pt", "f")} if a else "veri yok",
        "puan_farki": (h["pt"] - a["pt"]) if h and a and h.get("pt") is not None and a.get("pt") is not None else None,
        "lider_puan": max((r.get("pt") or 0 for r in rows), default=None),
    }


def lineup_info(raw: dict | None) -> dict:
    if not raw:
        return {"veri": "veri yok"}
    def side(s):
        t = raw.get(s) or {}
        return {"teknik_direktor": t.get("m"), "dizilis": t.get("f"),
                # 'r': True -> yedek; yalnızca ilk 11
                "oyuncular": [f"{p['n']} ({p['p']})" for p in t.get("p", []) if not p.get("r")][:11],
                "yedekler": [p["n"] for p in t.get("p", []) if p.get("r")]}
    # Not: 'pm' bayrağı "kesin kadro" anlamına gelmiyor (2026-11-05 Trabzonspor: cezalı oyuncu listede).
    return {"tahmini": True, "kesin": False, "kaynak_bayraklari": {"pl": raw.get("pl"), "pm": raw.get("pm")},
            "ev": side("h"), "dep": side("a")}


def next_fixtures(bulletin_all_days: list[dict], team: str, after_iso: str) -> list[str]:
    """Bültende takımın bu maçtan sonraki 5 gündeki maçları (rotasyon riski)."""
    t0 = dt.datetime.fromisoformat(after_iso)
    out = []
    for e in bulletin_all_days:
        if team in (e["ev"], e["deplasman"]):
            t = dt.datetime.fromisoformat(e["baslama"])
            if t0 < t <= t0 + dt.timedelta(days=5):
                out.append(f"{e['baslama'][:16]} {e['lig']}: {e['ev']} - {e['deplasman']}")
    return out


def collect_match(api: IddaaStats, match: dict, upcoming: list[dict], min_matches: int) -> dict:
    code = match["mac_kodu"]
    now = dt.datetime.now(TR_TZ)
    rm_h = api.get(f"recent-matches/{code}?matchHistoryType=0&isOnlyCurrentTournament=false")
    rm_a = api.get(f"recent-matches/{code}?matchHistoryType=1&isOnlyCurrentTournament=false")
    h2h = api.get(f"recent-matches/{code}?matchHistoryType=2&isOnlyCurrentTournament=false")
    cc = api.get(f"card-corners/{code}")
    st = api.get(f"standings/{code}?standingType=0&isLive=false")
    lu = api.get(f"lineup/{code}", cache=False)
    bi = api.get(f"bet-insights/{code}")

    hm, am = team_matches(rm_h, "h"), team_matches(rm_a, "a")
    hn = ((rm_h or {}).get("h") or {}).get("n") or match["ev"]
    an = ((rm_a or {}).get("a") or {}).get("n") or match["deplasman"]
    h2h_list = []
    if h2h:
        for m in sorted(h2h.get("m", []), key=lambda x: -x["t"])[:10]:
            h2h_list.append({"tarih": dt.datetime.fromtimestamp(m["t"], TR_TZ).date().isoformat(),
                             "turnuva": (m.get("l") or {}).get("n"),
                             "skor": f"{m['h'].get('n')} {m['h'].get('rs')}-{m['a'].get('rs')} {m['a'].get('n')}",
                             "iy": f"{m['h'].get('fhs')}-{m['a'].get('fhs')}"})
    n_h, n_a = len([m for m in hm if m["atilan"] is not None]), len([m for m in am if m["atilan"] is not None])
    return {
        "mac_kodu": code,
        "ev": summarize(hm, now), "dep": summarize(am, now),
        "kafa_kafaya": h2h_list,
        "kart_korner": {"ev": cards_corners(cc, "h"), "dep": cards_corners(cc, "a")},
        "puan_durumu": standings_info(st, hn, an),
        "kadro": lineup_info(lu),
        "notlar": [x["f"] for x in (bi or {}).get("bi", [])],
        "fikstur": {"ev_sonraki": next_fixtures(upcoming, match["ev"], match["baslama"]),
                    "dep_sonraki": next_fixtures(upcoming, match["deplasman"], match["baslama"])},
        "veri_yeterliligi": {"ev_mac": n_h, "dep_mac": n_a,
                             "dusuk_veri": min(n_h, n_a) < min_matches},
        "kaynak": f"{STATS}/*/{code}",
    }
