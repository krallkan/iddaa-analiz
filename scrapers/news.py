"""Adım 5: haber ve kadro taraması (Google News RSS, Türkçe + İngilizce, son 72 saat).

Kısıt: yalnızca haber BAŞLIKLARI okunur (Google yönlendirme bağlantıları metne güvenilir
şekilde açılamıyor). Bu yüzden başlıktan çıkarılan her bilgi "olası" kabul edilir.
λ düzeltmesi yalnızca başlıkta muhtemel 11'deki bir oyuncunun soyadı + açık bir
"yok/oynamayacak/sakatlandı" ifadesi birlikte geçerse önerilir.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET

from .common import TR_TZ, iso_now, make_client, polite_sleep

RSS = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{lang}"

KATEGORI = {
    "sakatlik": r"\bsakat|\binjur|\bruled out\b|\bfitness\b|\bhamstring\b|\bknock\b|\bdoubt(ful)?\b|\bameliyat",
    "ceza": r"\bcezal|\bsuspen|\bban\b|\bkırmızı kart|\bred card",
    "kadro": r"muhtemel (ilk )?11|ilk 11|predicted line|team news|line-?ups?\b|\bkadro|\bsquad\b|11'?\s?ler",
    "teknik_direktor": r"\bistifa|\bkovul|görevden al|yollar(ı)? ayrıl|yeni teknik direkt|\bsacked\b|\bresign|"
                       r"\bappointed\b|\bnew (manager|head coach)\b|\bparts ways\b",
    "kriz": r"\bkriz|\bcrisis\b|\bmaaş|\bprotesto|\bboykot|\bunrest\b|\bturmoil\b",
    "hava_saha": r"\byağmur|\bkar yağ|\bfırtına (uyarı|alarm|nedeniyle)|\bweather\b|\brain\b|\bsnow\b|\bpitch (condition|inspection)|"
                 r"\bzemin\b|saha koşul|\bpostpone|\bertelen",
    "rotasyon": r"\brotasyon|\brotation\b|\brested\b|\bdinlendir",
}
# Her maç için otomatik üretilen "maç önü" şablon başlıkları: risk sayılmaz
ONIZLEME = (r"hangi kanal|saat kaç|ne zaman|nereden izlenir|canlı izle|şifresiz|kimler (eksik|sakat)|"
            r"sakatlar, son durum|canlı anlatım|prediction|preview|betting tips|odds\b|where to watch|"
            r"live stream|tahmin|iddaa|maç önü|\?")
YOKLUK = (r"\byok\b|oynamayacak|forma giyemeyecek|kadroda yer almıyor|kadroya alınmadı|sakatlandı|"
          r"\bcezalı\b|ruled out|will miss|\bmisses\b|out for|sidelined|\bsuspended\b|unavailable|\babsent\b|injured")


def _ascii(s: str) -> str:
    s = s.replace("ı", "i").replace("İ", "I")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _tokens(team: str) -> list[str]:
    stop = {"fc", "cf", "sc", "ac", "fk", "afc", "club", "de", "united", "city", "town", "ca", "kf", "nk", "the"}
    return [t for t in re.findall(r"[a-z0-9]+", _ascii(team)) if len(t) >= 4 and t not in stop]


def _fetch(client, q: str, lang: str) -> tuple[str, list[dict]]:
    hl, gl = ("tr", "TR") if lang == "tr" else ("en-GB", "GB")
    url = RSS.format(q=urllib.parse.quote(q + " when:3d"), hl=hl, gl=gl, lang=lang)
    r = client.get(url)
    polite_sleep()
    items = []
    if r.status_code != 200:
        return url, items
    root = ET.fromstring(r.text)
    for it in root.findall(".//item"):
        pub = it.findtext("pubDate")
        try:
            t = email.utils.parsedate_to_datetime(pub).astimezone(TR_TZ)
        except Exception:  # noqa: BLE001
            t = None
        items.append({"baslik": it.findtext("title") or "", "kaynak": it.findtext("source"),
                      "link": it.findtext("link"), "yayin": t.isoformat() if t else None, "dil": lang})
    return url, items


def _surname(p: str) -> str:
    name = p.split(" (")[0]
    parts = name.replace(".", " ").split()
    return parts[-1] if parts else name


def analyze_news(items: list[dict], match: dict, kadro: dict, now: dt.datetime) -> dict:
    ev_t, dep_t = _tokens(match["ev"]), _tokens(match["deplasman"])
    players = {}
    for side in ("ev", "dep"):
        for p in (kadro.get(side) or {}).get("oyuncular", []):
            pos = p.split("(")[-1].rstrip(")") if "(" in p else "?"
            sn = _ascii(_surname(p))
            if len(sn) >= 4:
                players[sn] = (side, p, pos)
    seen, out, adjustments = set(), [], []
    for it in items:
        key = _ascii(it["baslik"])[:80]
        if key in seen:
            continue
        seen.add(key)
        tl = _ascii(it["baslik"])
        about_ev = any(t in tl for t in ev_t)
        about_dep = any(t in tl for t in dep_t)
        if not (about_ev or about_dep):
            continue  # alakasız
        title = re.sub(r"\s+-\s+[^-]+$", "", it["baslik"])  # sondaki " - Kaynak" kısmı
        onizleme = bool(re.search(ONIZLEME, title, re.I))
        cats = [k for k, pat in KATEGORI.items() if re.search(pat, title, re.I)]
        if onizleme:
            cats = ["onizleme"] + [c for c in cats if c == "kadro"]
        age_h = (now - dt.datetime.fromisoformat(it["yayin"])).total_seconds() / 3600 if it["yayin"] else None
        rec = {**it, "ilgili": "ev" if about_ev and not about_dep else "dep" if about_dep and not about_ev else "ikisi",
               "kategori": cats, "yas_saat": round(age_h, 1) if age_h is not None else None,
               "eski": age_h is None or age_h > 72}
        # oyuncu + yokluk ifadesi
        if not rec["eski"] and not onizleme and re.search(YOKLUK, title, re.I):
            for sn, (side, p, pos) in players.items():
                if re.search(rf"\b{re.escape(sn)}\b", tl):
                    rec.setdefault("oyuncu", []).append(p)
                    adjustments.append({"takim": side, "oyuncu": p, "mevki": pos, "durum": "doğrulanmalı",
                                        "baslik": it["baslik"], "kaynak": it["kaynak"], "link": it["link"],
                                        "yayin": it["yayin"]})
        out.append(rec)
    out.sort(key=lambda x: x["yayin"] or "", reverse=True)
    risk = {
        "sakatlik_ceza_haberi": sum(1 for x in out if not x["eski"] and {"sakatlik", "ceza"} & set(x["kategori"])),
        "td_kriz_haberi": sum(1 for x in out if not x["eski"] and {"teknik_direktor", "kriz"} & set(x["kategori"])),
        "rotasyon_haberi": sum(1 for x in out if not x["eski"] and "rotasyon" in x["kategori"]),
        "olasi_eksik_oyuncu": adjustments,
        # iddaa kadro servisinin "kesin" bayrağı güvenilir değil (cezalı oyuncu "kesin" kadroda görüldü);
        # resmi kadro maçtan ~1 saat önce açıklanır -> kadro her zaman tahmini kabul edilir.
        "kadro_belirsiz": True,
    }
    # Risk taşıyan haberlerin tamamı + en yeni diğer 20 haber saklanır
    riskli = [x for x in out if set(x["kategori"]) - {"kadro", "onizleme"}]
    diger = [x for x in out if x not in riskli][:20]
    return {"haberler": sorted(riskli + diger, key=lambda x: x["yayin"] or "", reverse=True), "risk": risk}


def collect_news(match: dict, kadro: dict, en_names: tuple[str, str] | None = None) -> dict:
    now = dt.datetime.now(TR_TZ)
    h, a = match["ev"], match["deplasman"]
    eh, ea = en_names or (h, a)
    queries = [
        (f'"{h}" "{a}"', "tr"),
        (f'{h} (sakat OR cezalı OR kadro OR "muhtemel 11")', "tr"),
        (f'{a} (sakat OR cezalı OR kadro OR "muhtemel 11")', "tr"),
        (f'{eh} {ea} (injury OR "team news" OR lineup OR suspended)', "en"),
    ]
    items, log = [], []
    with make_client() as c:
        for q, lang in queries:
            try:
                url, got = _fetch(c, q, lang)
                items += got
                log.append({"url": url, "sonuc": len(got), "fetched_at": iso_now()})
            except Exception as e:  # noqa: BLE001
                log.append({"sorgu": q, "error": repr(e), "fetched_at": iso_now()})
    res = analyze_news(items, match, kadro, now)
    res["sorgular"] = log
    res["cekilme_zamani"] = iso_now()
    return res
