"""UEFA ülke katsayıları (resmi): https://comp.uefa.com/v2/coefficients  — günde bir kez çekilir."""
from __future__ import annotations

import json
from pathlib import Path

from .common import iso_now, make_client, polite_sleep

URL = ("https://comp.uefa.com/v2/coefficients?coefficientRange=OVERALL&coefficientType=MEN_ASSOCIATION"
       "&language=EN&page=1&pagesize=60&seasonYear={year}")

# iddaa lig adlarının başındaki Türkçe ülke adı -> UEFA ülke kodu
ULKE = {
    "Türkiye": "TUR", "İngiltere": "ENG", "England": "ENG", "İskoçya": "SCO", "İspanya": "ESP", "İtalya": "ITA",
    "Almanya": "GER", "Fransa": "FRA", "Hollanda": "NED", "Portekiz": "POR", "Portugal": "POR",
    "Belçika": "BEL", "Avusturya": "AUT", "İsviçre": "SUI", "Switzerland": "SUI", "Danimarka": "DEN",
    "Norveç": "NOR", "İsveç": "SWE", "Yunanistan": "GRE", "Çekya": "CZE", "Polonya": "POL",
    "Hırvatistan": "CRO", "Romanya": "ROU", "Bulgaristan": "BUL", "Sırbistan": "SRB", "Macaristan": "HUN",
    "Kıbrıs": "CYP", "Slovenya": "SVN", "Slovakya": "SVK", "Ukrayna": "UKR", "İsrail": "ISR",
    "Kazakistan": "KAZ", "Ermenistan": "ARM", "Azerbaycan": "AZE", "Gürcistan": "GEO", "Litvanya": "LTU",
    "Letonya": "LVA", "Estonya": "EST", "Finlandiya": "FIN", "Kuzey İrlanda": "NIR", "İrlanda": "IRL",
    "Galler": "WAL", "Bosna Hersek": "BIH", "Arnavutluk": "ALB", "Kosova": "KOS", "Andorra": "AND",
    "Cebelitarık": "GIB", "Malta": "MLT", "Lüksemburg": "LUX", "İzlanda": "ISL", "Faroe": "FRO",
    "Moldova": "MDA", "Belarus": "BLR", "Karadağ": "MNE", "Kuzey Makedonya": "MKD",
    "North Macedonia": "MKD", "San Marino": "SMR", "Lihtenştayn": "LIE", "Rusya": "RUS",
}
FD_ULKE = {"E": "ENG", "SC": "SCO", "D": "GER", "I": "ITA", "SP": "ESP", "F": "FRA", "N": "NED", "B": "BEL",
           "P": "POR", "T": "TUR", "G": "GRE", "AUT": "AUT", "SWZ": "SUI", "DNK": "DEN", "NOR": "NOR",
           "SWE": "SWE", "POL": "POL", "ROU": "ROU", "IRL": "IRL", "FIN": "FIN"}


def league_country(lig: str) -> str | None:
    for k in sorted(ULKE, key=len, reverse=True):   # "Kuzey İrlanda" "İrlanda"dan önce
        if lig.startswith(k):
            return ULKE[k]
    return None


def fd_country(code: str) -> str | None:
    base = code.rstrip("0123456789")
    return FD_ULKE.get(code) or FD_ULKE.get(base)


def fetch_coefficients(cache: Path, year: int) -> dict:
    f = cache / "uefa_katsayi.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    url = URL.format(year=year)
    with make_client() as c:
        r = c.get(url)
    polite_sleep()
    r.raise_for_status()
    members = r.json()["data"]["members"]
    coef = {m["member"]["countryCode"]: m["overallRanking"]["totalValue"] for m in members}
    out = {"kaynak": url, "cekilme_zamani": iso_now(), "katsayi": coef}
    cache.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
