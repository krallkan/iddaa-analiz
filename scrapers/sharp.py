"""Keskin piyasa karşılaştırması: The Odds API (Pinnacle, Betfair Exchange, Matchbook) ↔ iddaa.

Fikir: dünyanın en keskin piyasasının marjsız fiyatı "doğru fiyat" kabul edilir. iddaa'nın Üst oranı bu doğru
fiyata göre yüksekse (beklenen değer > 0) seçenek "gerçek değer" olarak işaretlenir. Yalnızca Üst (Alt verilmez).

Çizgi dönüşümü: keskin şirketler ana çizgiyi çoğu zaman 2.75 / 3.25 gibi Asya çizgilerinde verir. Marjsız orandan
toplam gol beklentisi μ (Poisson) çözülür — Asya çizgilerinde iade (push) hesaba katılır — ve iddaa'nın 2,5 / 3,5 /
4,5 çizgilerine P(gol > çizgi) olarak çevrilir.

Kredi (ücretsiz plan 500/ay): /sports ve /sports/{lig}/events kredi harcamaz. /odds yalnızca iddaa maçı eşleşen
ligler için, markets=totals ve en fazla 10 şirketle (= 1 bölge) çağrılır -> lig başına 1 kredi. Günlük tavan,
kalan kredinin ayın kalan günlerine bölünmesiyle belirlenir.
Anahtar: ortam değişkeni ODDS_API_KEY (GitHub Actions secret). Anahtar hiçbir dosyaya/rapora yazılmaz.
"""
from __future__ import annotations

import calendar
import datetime as dt
import difflib
import math
import os
import re
import statistics
import unicodedata

import httpx

from .common import TR_TZ, iso_now, polite_sleep

BASE = "https://api.the-odds-api.com/v4"
SHARP = ["pinnacle", "betfair_ex_eu", "matchbook"]          # öncelik sırası (keskin kaynaklar)
OTHER = ["williamhill", "unibet_eu", "marathonbet", "onexbet", "sport888", "betsson", "nordicbet"]  # yedek ortalama
CIZGILER = [2.5, 3.5, 4.5]                                    # karşılaştırılan iddaa Üst çizgileri
EXO = {"kopenhag": "copenhagen", "marsilya": "marseille", "lizbon": "lisbon", "prag": "prague", "sofya": "sofia",
       "munih": "munich", "belgrad": "belgrade", "atina": "athens", "zurih": "zurich", "viyana": "vienna",
       "kizil yildiz": "red star", "bayer leverkusen": "leverkusen", "b leverkusen": "leverkusen"}
STOP = {"fc", "cf", "sc", "ac", "afc", "fk", "sk", "cd", "club", "de", "the", "sv", "if", "bk", "ss", "us", "as",
        "nk", "kf", "ca", "cs", "ud", "rc", "sd", "1907", "1903", "1899", "spor", "kulubu"}


class SharpError(Exception):
    pass


# ---------------------------------------------------------------- takım eşleştirme
def _norm(s: str) -> list[str]:
    t = unicodedata.normalize("NFKD", (s or "").replace("ı", "i").replace("İ", "I").lower())
    t = t.encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for k, v in EXO.items():
        t = re.sub(rf"\b{k}\b", v, t)
    return [w for w in t.split() if w not in STOP and len(w) > 1]


def team_sim(a: str, b: str) -> float:
    A, B = _norm(a), _norm(b)
    if not A or not B:
        return 0.0
    hit = sum(1 for x in A if any(x == y or (len(x) >= 4 and len(y) >= 4 and x[:4] == y[:4]) for y in B))
    return max(hit / min(len(A), len(B)), difflib.SequenceMatcher(None, " ".join(A), " ".join(B)).ratio())


def match_events(iddaa_matches: list[dict], events: list[dict]) -> dict[str, dict]:
    """iddaa maçı -> The Odds API etkinliği. Başlama ±30 dk ve iki takım adı benzerliği birlikte aranır."""
    out = {}
    for m in iddaa_matches:
        t0 = dt.datetime.fromisoformat(m["baslama"]).astimezone(dt.timezone.utc)
        best = None
        for e in events:
            te = dt.datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
            if abs((te - t0).total_seconds()) > 1800:
                continue
            sh, sa = team_sim(m["ev"], e["home_team"]), team_sim(m["deplasman"], e["away_team"])
            ok = (sh >= 0.6 and sa >= 0.4) or (sa >= 0.6 and sh >= 0.4) or min(sh, sa) >= 0.5
            if ok and (best is None or sh + sa > best[0]):
                best = (sh + sa, e)
        if best:
            out[str(m["mac_kodu"])] = best[1]
    return out


# ---------------------------------------------------------------- HTTP
def _get(c: httpx.Client, path: str, key: str, **params):
    try:
        r = c.get(f"{BASE}{path}", params={"apiKey": key, **params}, timeout=40)
    except httpx.HTTPError as e:
        raise SharpError(f"{path}: bağlantı hatası {type(e).__name__}") from None
    polite_sleep(0.15, 0.35)
    return r


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def daily_cap(remaining: int | None, today: dt.date) -> int:
    """Kalan krediyi ayın kalan günlerine böler (bugün dahil)."""
    if remaining is None:
        return 10
    days_left = calendar.monthrange(today.year, today.month)[1] - today.day + 1
    return max(0, min(40, remaining // max(days_left, 1)))


def fetch_raw(iddaa_matches: list[dict], hours: int = 30, cap: int | None = None) -> dict:
    """Keskin oranları çeker. Dönüş: ham kayıt (eşleşme + etkinlik oranları + kredi bilgisi)."""
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        raise SharpError("ODDS_API_KEY tanımlı değil")
    now = dt.datetime.now(dt.timezone.utc)
    frm, to = _iso(now), _iso(now + dt.timedelta(hours=hours))
    log = []
    with httpx.Client(headers={"User-Agent": "mac-analiz/1.0"}) as c:
        r = _get(c, "/sports", key)
        if r.status_code == 401:
            raise SharpError("anahtar geçersiz (401)")
        if r.status_code != 200:
            raise SharpError(f"/sports HTTP {r.status_code}: {r.text[:150]}")
        remaining = r.headers.get("x-requests-remaining")
        remaining = int(float(remaining)) if remaining not in (None, "") else None
        sports = [s["key"] for s in r.json()
                  if s.get("group") == "Soccer" and s.get("active") and not s.get("has_outrights")]
        # 1) kredi harcamayan etkinlik listeleri -> iddaa eşleşmesi
        ev_by_sport, all_ev = {}, []
        for sk in sports:
            er = _get(c, f"/sports/{sk}/events", key, commenceTimeFrom=frm, commenceTimeTo=to)
            if er.status_code == 200 and er.json():
                ev_by_sport[sk] = er.json()
                for e in er.json():
                    all_ev.append({**e, "_lig": sk})
        matched = match_events(iddaa_matches, all_ev)
        per_sport = {}
        for kod, e in matched.items():
            per_sport.setdefault(e["_lig"], []).append(kod)
        # 2) yalnızca eşleşen ligler, en çok eşleşen önce, günlük kredi tavanı içinde
        limit = daily_cap(remaining, now.astimezone(TR_TZ).date()) if cap is None else cap
        order = sorted(per_sport, key=lambda s: -len(per_sport[s]))
        odds = {}
        spent = 0
        for sk in order:
            if spent >= limit:
                log.append({"lig": sk, "atlandi": "günlük kredi tavanı", "mac": len(per_sport[sk])})
                continue
            orr = _get(c, f"/sports/{sk}/odds", key, bookmakers=",".join(SHARP + OTHER), markets="totals",
                       oddsFormat="decimal", commenceTimeFrom=frm, commenceTimeTo=to)
            used = orr.headers.get("x-requests-last")
            spent += int(float(used)) if used not in (None, "") else 1
            rem = orr.headers.get("x-requests-remaining")
            if rem not in (None, ""):
                remaining = int(float(rem))
            log.append({"lig": sk, "durum": orr.status_code, "mac": len(per_sport[sk]), "harcanan": used})
            if orr.status_code == 200:
                for e in orr.json():
                    odds[e["id"]] = e
            elif orr.status_code in (401, 429):
                log.append({"hata": f"HTTP {orr.status_code}: {orr.text[:120]}"})
                break
    eslesme = {kod: {"id": e["id"], "lig": e["_lig"], "ev": e["home_team"], "dep": e["away_team"],
                     "baslama": e["commence_time"]} for kod, e in matched.items()}
    return {"cekilme_zamani": iso_now(), "kalan_kredi": remaining, "harcanan": spent, "tavan": limit,
            "lig_sayisi": len(sports), "log": log, "eslesme": eslesme, "oranlar": odds}


# ---------------------------------------------------------------- olasılık
def _pois_cdf(k: int, mu: float) -> float:
    if k < 0:
        return 0.0
    term, s = math.exp(-mu), math.exp(-mu)
    for i in range(1, k + 1):
        term *= mu / i
        s += term
    return s


def p_over(line: float, mu: float) -> float:
    """P(toplam gol > line), line = x.5"""
    return 1 - _pois_cdf(int(math.floor(line)), mu)


def _ev_over_single(line: float, odd: float, mu: float) -> float:
    """Tek çizgide (x.5 ya da tam sayı) birim bahsin beklenen kazancı; tam sayıda eşitlik iade."""
    if abs(line - round(line)) < 1e-9:
        L = int(round(line))
        pw = 1 - _pois_cdf(L, mu)
        pl = _pois_cdf(L - 1, mu)
    else:
        pw = 1 - _pois_cdf(int(math.floor(line)), mu)
        pl = 1 - pw
    return pw * (odd - 1) - pl


def ev_over(line: float, odd: float, mu: float) -> float:
    frac = round(line * 4) % 2  # çeyrek çizgi mi? (x.25 / x.75)
    if frac == 1:
        return 0.5 * (_ev_over_single(line - 0.25, odd, mu) + _ev_over_single(line + 0.25, odd, mu))
    return _ev_over_single(line, odd, mu)


def solve_mu(line: float, fair_odd: float) -> float | None:
    """Adil Üst oranının sıfır beklenen değer verdiği Poisson μ (bisection)."""
    lo, hi = 0.05, 9.0
    f_lo, f_hi = ev_over(line, fair_odd, lo), ev_over(line, fair_odd, hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        fm = ev_over(line, fair_odd, mid)
        if (fm > 0) == (f_hi > 0):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def book_mu(book: dict) -> tuple[float | None, list[dict]]:
    """Bir şirketin totals pazarından marjsız μ. Birden çok çizgi varsa ortalaması."""
    mus, lines = [], []
    for mk in book.get("markets", []):
        if mk.get("key") != "totals":
            continue
        by = {}
        for o in mk.get("outcomes", []):
            by.setdefault(o.get("point"), {})[o.get("name")] = o.get("price")
        for pt, d in by.items():
            if pt is None or not d.get("Over") or not d.get("Under") or d["Over"] <= 1 or d["Under"] <= 1:
                continue
            io, iu = 1 / d["Over"], 1 / d["Under"]
            fair_over = (io + iu) / io            # marjsız Üst oranı (oransal yöntem)
            mu = solve_mu(float(pt), fair_over)
            if mu:
                mus.append(mu)
                lines.append({"cizgi": float(pt), "ust": d["Over"], "alt": d["Under"], "marj": round(io + iu - 1, 4)})
    return (sum(mus) / len(mus) if mus else None), lines


def fair_mu(ev: dict) -> dict | None:
    """Önce keskin şirket; yoksa en az 4 şirketin medyanı (piyasa ortalaması)."""
    books = {b["key"]: b for b in ev.get("bookmakers", [])}
    for k in SHARP:
        if k in books:
            mu, lines = book_mu(books[k])
            if mu:
                return {"mu": mu, "kaynak": k, "keskin": True, "cizgiler": lines,
                        "guncelleme": books[k].get("last_update")}
    mus = [m for m in (book_mu(b)[0] for k, b in books.items() if k not in SHARP) if m]
    if len(mus) >= 4:
        return {"mu": statistics.median(mus), "kaynak": f"piyasa ortalaması ({len(mus)} şirket)", "keskin": False,
                "cizgiler": [], "guncelleme": None}
    return None


def compare(iddaa_match: dict, fair: dict, min_deger: float = 0.02) -> list[dict]:
    """iddaa Üst oranlarını keskin μ'dan elde edilen doğru olasılıkla karşılaştırır."""
    out = []
    by = {p.get("key"): p for p in iddaa_match.get("pazarlar", [])}
    for line in CIZGILER:
        mk = by.get(f"AU_{line}")
        p = p_over(line, fair["mu"])
        o = None
        if mk:
            o = next((x["odd"] for x in mk["outcomes"] if x["name"] == "Üst" and not x.get("closed")), None)
        deger = (p * o - 1) if o else None
        esik = min_deger if fair["keskin"] else 0.05    # ortalama kaynakta daha yüksek eşik
        out.append({"secenek": f"{str(line).replace('.', ',')} Üst", "pazar": f"AU_{line}", "iddaa_oran": o,
                    "dogru_olasilik": round(p, 4), "adil_oran": round(1 / p, 2) if p > 0 else None,
                    "deger": round(deger, 4) if deger is not None else None,
                    "gercek_deger": bool(deger is not None and deger >= esik and 1.25 <= o <= 6.0)})
    return out
