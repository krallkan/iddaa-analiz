"""football-data.co.uk sezon verisi: lig ortalamaları, takım xG/xGA, iç/dış saha gol ortalamaları.

Ana ligler (yaz-kış sezonu):  https://www.football-data.co.uk/mmz4281/<YYZZ>/<KOD>.csv
  (FTHG/FTAG, HTHG/HTAG, HxG/AxG varsa, HC/AC korner, HY/AY sarı kart)
Ek ligler (takvim yılı):       https://www.football-data.co.uk/new/<KOD>.csv (yalnızca skor)
Günde bir kez indirilir (data/YYYY-MM-DD/footballdata/).
"""
from __future__ import annotations

import csv
import datetime as dt
import difflib
import io
import json
import re
import unicodedata
from pathlib import Path

from .common import iso_now, make_client, polite_sleep

BASE = "https://www.football-data.co.uk"
MAIN = {"E0": "İngiltere Premier Lig", "E1": "İngiltere Championship", "E2": "İngiltere 1. Lig",
        "SC0": "İskoçya Premiership", "D1": "Almanya Bundesliga", "D2": "Almanya 2. Bundesliga",
        "I1": "İtalya Serie A", "I2": "İtalya Serie B", "SP1": "İspanya La Liga", "SP2": "İspanya La Liga 2",
        "F1": "Fransa Ligue 1", "F2": "Fransa Ligue 2", "N1": "Hollanda Eredivisie", "B1": "Belçika Pro Lig",
        "P1": "Portekiz Premier Lig", "T1": "Türkiye Süper Lig", "G1": "Yunanistan Süper Lig"}
EXTRA = {"AUT": "Avusturya Bundesliga", "SWZ": "İsviçre Süper Lig", "DNK": "Danimarka Süper Lig",
         "NOR": "Norveç Eliteserien", "SWE": "İsveç Allsvenskan", "POL": "Polonya Ekstraklasa",
         "ROU": "Romanya 1. Lig", "ARG": "Arjantin Primera LPF", "BRA": "Brezilya Serie A",
         "USA": "ABD Major Lig", "JPN": "Japonya J.Lig", "IRL": "İrlanda Premier Lig",
         "FIN": "Finlandiya Veikkausliiga", "CHN": "Çin Süper Lig", "MEX": "Meksika Liga MX"}

ALIAS_PATH = Path(__file__).resolve().parent.parent / "config" / "takim_alias.json"


def season_code(day: dt.date) -> str:
    y = day.year if day.month >= 7 else day.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.replace("ı", "i").replace("İ", "I")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    s = re.sub(r"\b(fc|cf|sc|ac|afc|sk|fk|bk|cd|ud|sd|as|ss|ssd|calcio|club|de|the|1907|1903|1899)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class FootballData:
    def __init__(self, cache_dir: Path, day: dt.date):
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.day = day
        self.leagues: dict[str, dict] = {}
        self.log: list[dict] = []
        self.alias = json.loads(ALIAS_PATH.read_text(encoding="utf-8")) if ALIAS_PATH.exists() else {}

    def _download(self, code: str, url: str) -> str | None:
        f = self.dir / f"{code}.csv"
        if f.exists():
            self.log.append({"url": url, "cache": True})
            return f.read_text(encoding="utf-8-sig")
        try:
            with make_client() as c:
                r = c.get(url)
            polite_sleep()
            if r.status_code != 200 or not r.text.strip():
                self.log.append({"url": url, "status": r.status_code, "error": "veri yok", "fetched_at": iso_now()})
                return None
            txt = r.content.decode("utf-8-sig", errors="replace")
            f.write_text(txt, encoding="utf-8")
            self.log.append({"url": url, "fetched_at": iso_now()})
            return txt
        except Exception as e:  # noqa: BLE001
            self.log.append({"url": url, "error": repr(e), "fetched_at": iso_now()})
            return None

    def load(self, codes: list[str] | None = None, prev_season: bool = True) -> None:
        """Bu sezon + (model için) bir önceki sezon. Takım eşleme yalnızca bu sezon üzerinden yapılır."""
        sc = season_code(self.day)
        prev = season_code(self.day.replace(year=self.day.year - 1))
        for code, lig in MAIN.items():
            if codes and code not in codes:
                continue
            url = f"{BASE}/mmz4281/{sc}/{code}.csv"
            txt = self._download(code, url)
            if txt:
                self.leagues[code] = self._parse_main(txt, lig, url)
                if prev_season:
                    purl = f"{BASE}/mmz4281/{prev}/{code}.csv"
                    ptxt = self._download(f"{code}_{prev}", purl)
                    self.leagues[code]["onceki_sezon"] = self._parse_main(ptxt, lig, purl)["maclar"] if ptxt else []
        for code, lig in EXTRA.items():
            if codes and code not in codes:
                continue
            url = f"{BASE}/new/{code}.csv"
            txt = self._download(code, url)
            if txt:
                self.leagues[code] = self._parse_extra(txt, lig, url)

    def _parse_main(self, txt, lig, url):
        rows = []
        for r in csv.DictReader(io.StringIO(txt)):
            if not r.get("HomeTeam") or _f(r.get("FTHG")) is None:
                continue
            rows.append({"tarih": r["Date"], "ev": r["HomeTeam"], "dep": r["AwayTeam"],
                         "eg": _f(r["FTHG"]), "dg": _f(r["FTAG"]),
                         "exg": _f(r.get("HxG")), "dxg": _f(r.get("AxG")),
                         "ek": _f(r.get("HC")), "dk": _f(r.get("AC")),
                         "es": _f(r.get("HY")), "ds": _f(r.get("AY")),
                         "iy_eg": _f(r.get("HTHG")), "iy_dg": _f(r.get("HTAG"))})
        return {"lig": lig, "url": url, "maclar": rows}

    def _parse_extra(self, txt, lig, url):
        rows = list(csv.DictReader(io.StringIO(txt)))
        if not rows:
            return {"lig": lig, "url": url, "maclar": [], "onceki_sezon": []}
        seasons = []
        for r in rows:
            if r.get("Season") and r["Season"] not in seasons:
                seasons.append(r["Season"])
        last = seasons[-1]
        prev = seasons[-2] if len(seasons) > 1 else None

        def conv(r):
            return {"tarih": r["Date"], "ev": r["Home"].strip(), "dep": r["Away"].strip(),
                    "eg": _f(r["HG"]), "dg": _f(r["AG"]), "exg": None, "dxg": None,
                    "ek": None, "dk": None, "es": None, "ds": None, "iy_eg": None, "iy_dg": None}
        cur = [conv(r) for r in rows if r.get("Season") == last and _f(r.get("HG")) is not None]
        old = [conv(r) for r in rows if prev and r.get("Season") == prev and _f(r.get("HG")) is not None]
        return {"lig": lig, "url": url, "sezon": last, "maclar": cur, "onceki_sezon": old}

    # ---- takım eşleme ----
    def candidates(self, iddaa_name: str, k: int = 6) -> list[tuple[str, str, float]]:
        target = self.alias.get(iddaa_name, iddaa_name)
        nt = norm(target)
        out = []
        for code, L in self.leagues.items():
            teams = {m["ev"] for m in L["maclar"]} | {m["dep"] for m in L["maclar"]}
            for t in teams:
                sc = 1.0 if t == target else difflib.SequenceMatcher(None, nt, norm(t)).ratio()
                if nt and set(nt.split()) & set(norm(t).split()):
                    sc = max(sc, 0.7)
                out.append((code, t, sc))
        return sorted(out, key=lambda x: -x[2])[:k]

    def confirm(self, code: str, team: str, recent: list[dict]) -> int:
        """iddaa son maçlarıyla (tarih ±1 gün, aynı skor) örtüşen maç sayısı."""
        fd = []
        for m in self.leagues[code]["maclar"]:
            if team not in (m["ev"], m["dep"]):
                continue
            try:
                d = dt.datetime.strptime(m["tarih"], "%d/%m/%Y").date()
            except ValueError:
                try:
                    d = dt.datetime.strptime(m["tarih"], "%d/%m/%y").date()
                except ValueError:
                    continue
            gf, ga = (m["eg"], m["dg"]) if m["ev"] == team else (m["dg"], m["eg"])
            fd.append((d, gf, ga))
        hits = 0
        for r in recent:
            if r.get("atilan") is None:
                continue
            rd = dt.date.fromisoformat(r["tarih"])
            if any(abs((rd - d).days) <= 1 and gf == r["atilan"] and ga == r["yenilen"] for d, gf, ga in fd):
                hits += 1
        return hits

    def find_team(self, iddaa_name: str, recent: list[dict] | None = None) -> tuple[str, str, float, int] | None:
        """Ad benzerliği + son maçların tarih/skor doğrulaması. (lig, takım, benzerlik, doğrulanan maç)"""
        for code, t, sc in self.candidates(iddaa_name):
            if sc < 0.6:
                break
            n = self.confirm(code, t, recent or [])
            if n >= 2:
                return code, t, sc, n
        return None

    def team_profile(self, iddaa_name: str, recent: list[dict] | None = None) -> dict:
        hit = self.find_team(iddaa_name, recent)
        if not hit:
            return {"veri": "veri yok",
                    "neden": "football-data'da tarih/skor ile doğrulanan takım yok (lig kapsam dışı olabilir)"}
        code, name, score, confirmed = hit
        L = self.leagues[code]
        ms = L["maclar"]
        n = len(ms)
        lg = {"mac": n,
              "ev_gol_ort": _mean([m["eg"] for m in ms]), "dep_gol_ort": _mean([m["dg"] for m in ms])}
        home = [m for m in ms if m["ev"] == name]
        away = [m for m in ms if m["dep"] == name]
        xg_for = [m["exg"] for m in home] + [m["dxg"] for m in away]
        xg_ag = [m["dxg"] for m in home] + [m["exg"] for m in away]
        return {
            "lig_kodu": code, "lig": L["lig"], "fd_takim": name, "eslesme_skoru": round(score, 2),
            "dogrulanan_mac": confirmed,
            "kaynak": L["url"], "lig_ort": lg,
            "ic_saha": {"mac": len(home), "atilan": _mean([m["eg"] for m in home]),
                        "yenilen": _mean([m["dg"] for m in home])},
            "dis_saha": {"mac": len(away), "atilan": _mean([m["dg"] for m in away]),
                         "yenilen": _mean([m["eg"] for m in away])},
            "xg_ort": _mean(xg_for), "xga_ort": _mean(xg_ag),
            "korner_ort": _mean([m["ek"] for m in home] + [m["dk"] for m in away]),
            "maclar_ham": home + away,
        }


def parse_date(s: str) -> dt.date | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None
