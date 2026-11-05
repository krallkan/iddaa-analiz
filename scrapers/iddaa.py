"""iddaa.com futbol bülteni.

Site (Next.js) bülteni şu JSON uç noktalarından yüklüyor (2026-11-05'te Playwright
ile page.on("response") dinlenerek tespit edildi):
  - https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0&version=0   -> maçlar + oranlar
  - https://sportsbookv2.iddaa.com/sportsbook/get_market_config              -> pazar adları
  - https://sportsbookv2.iddaa.com/sportsbook/competitions                   -> lig adları

Önce httpx ile doğrudan istenir; başarısız olursa Playwright ile sayfa açılıp aynı
yanıtlar ağdan yakalanır.

Alan anlamları (gözlemle çıkarıldı):
  i=etkinlik id (sitede ayrı kısa kod yok; maç kodu olarak bu kullanılıyor),
  hn/an=ev/deplasman, d=başlama (unix sn), ci=lig id, mbc=MBS, s=1 ise canlı/başlamış,
  m=pazarlar [t,st=pazar tipi, sov=çizgi, mbc=pazar MBS, s=1 açık, o=seçenekler(n, odd)].
  odd sitede gösterilen orandır; 1.00 kapalı/oynanamaz seçenek demektir.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .common import (CHROMIUM_PATH, TR_TZ, USER_AGENT, ScrapeError, iso_now,
                     make_client, now_tr, polite_sleep)

BASE = "https://sportsbookv2.iddaa.com/sportsbook"
PAGE_URL = "https://www.iddaa.com/program/futbol"
EVENTS_URL = f"{BASE}/events?st=1&type=0&version=0"
CONFIG_URL = f"{BASE}/get_market_config"
COMPS_URL = f"{BASE}/competitions"

# (t, st) -> kısa anahtar. Çizgili pazarlarda anahtar sonuna çizgi eklenir.
MARKET_KEYS = {
    (1, 1): "MS",
    (2, 92): "CS",            # Çifte Şans
    (2, 88): "IY",            # 1. Yarı Sonucu
    (2, 90): "IYMS",          # İY/MS
    (2, 101): "AU",           # Alt/Üst {line}
    (2, 60): "IY_AU",         # 1. Yarı Alt/Üst {line}
    (2, 89): "KG",            # Karşılıklı Gol
    (2, 100): "HMS",          # Handikaplı MS {h}
    (2, 48): "KORNER_AU",     # Toplam Korner Alt/Üst {line}
    (2, 49): "IY_KORNER_AU",
    (2, 4): "TOPLAM_GOL",
    (2, 720): "IY_KG",
}
# Kimlikler değişirse diye ada göre yedek eşleme (pazar adı, {0}/{h} yer tutucularıyla).
MARKET_NAME_KEYS = {
    "Maç Sonucu": "MS", "Çifte Şans": "CS", "1. Yarı Sonucu": "IY",
    "1. Yarı / Maç Sonucu": "IYMS", "Alt/Üst {0}": "AU", "1. Yarı Alt/Üst {0}": "IY_AU",
    "Karşılıklı Gol": "KG", "Handikaplı Maç Sonucu {h}": "HMS",
    "Toplam Korner Sayısı Alt/Üst {0}": "KORNER_AU", "1. Yarı Toplam Korner Sayısı Alt/Üst {0}": "IY_KORNER_AU",
    "Toplam Gol": "TOPLAM_GOL", "1. Yarı Karşılıklı Gol": "IY_KG",
}
# Kart pazarları bültende nadiren var; adında "Kart" geçen her pazar KART_* olarak işaretlenir.


def _hcp_label(sov: str | None) -> str | None:
    """Handikap çizgisini sitedeki gösterime çevirir: '1' -> '1:0', '-2' -> '0:2'."""
    if sov is None:
        return None
    v = float(sov)
    n = int(abs(v)) if v == int(v) else abs(v)
    return f"{n}:0" if v > 0 else f"0:{n}"


def _fetch_http() -> tuple[dict, dict, dict, dict]:
    meta = {}
    with make_client(Origin="https://www.iddaa.com", Referer="https://www.iddaa.com/") as c:
        out = []
        for url in (CONFIG_URL, COMPS_URL, EVENTS_URL):
            r = c.get(url)
            r.raise_for_status()
            j = r.json()
            if not j.get("isSuccess"):
                raise ScrapeError(f"{url} isSuccess=false: {j.get('message')}")
            out.append(j["data"])
            meta[url] = {"status": r.status_code, "bytes": len(r.content), "fetched_at": iso_now()}
            polite_sleep()
    return out[0], out[1], out[2], meta


def _fetch_playwright() -> tuple[dict, dict, dict, dict]:
    from playwright.sync_api import sync_playwright

    got, meta = {}, {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROMIUM_PATH)
        pg = b.new_context(user_agent=USER_AGENT, locale="tr-TR").new_page()

        def on_response(r):
            for key, prefix in (("config", CONFIG_URL), ("comps", COMPS_URL),
                                ("events", f"{BASE}/events?st=1")):
                if r.url.startswith(prefix) and key not in got:
                    try:
                        got[key] = r.json()["data"]
                        meta[r.url] = {"status": r.status, "fetched_at": iso_now(), "via": "playwright"}
                    except Exception:
                        pass

        pg.on("response", on_response)
        # networkidle'a hiç ulaşılmıyor (reklam/websocket), sabit bekleme kullanılıyor
        pg.goto(PAGE_URL, wait_until="domcontentloaded", timeout=60000)
        for _ in range(30):
            if len(got) == 3:
                break
            pg.wait_for_timeout(1000)
        b.close()
    missing = {"config", "comps", "events"} - got.keys()
    if missing:
        raise ScrapeError(f"Playwright ile yakalanamayan yanıtlar: {missing}")
    return got["config"], got["comps"], got["events"], meta


def parse_market(m: dict, cfg: dict, fetched_at: str) -> dict:
    t, st = m["t"], m["st"]
    c = cfg.get(f"{t}_{st}", {})
    sov = m.get("sov")
    tmpl = c.get("n", f"bilinmeyen {t}_{st}")
    name = tmpl.replace("{0}", sov or "").replace("{h}", _hcp_label(sov) or "").strip()
    key = MARKET_KEYS.get((t, st))
    by_name = MARKET_NAME_KEYS.get(tmpl)
    if by_name and key != by_name:
        key = by_name  # iddaa kimlikleri değiştirmiş; ad esas alınır
    if key is None and "Kart" in name:
        key = f"KART_{t}_{st}"
    if key and sov is not None:
        key = f"{key}_{_hcp_label(sov) if key == 'HMS' else sov}"
    return {
        "key": key,
        "type": f"{t}_{st}",
        "name": name,
        "line": sov,
        "mbs": m.get("mbc"),
        "open": m.get("s") == 1,
        "outcomes": [
            {"name": o["n"], "odd": o["odd"], "closed": o["odd"] <= 1.0}
            for o in m["o"]
        ],
        "odds_fetched_at": fetched_at,
    }


def fetch_bulletin(day: dt.date | None = None) -> dict:
    """Bugün başlayacak ve henüz başlamamış futbol maçlarını döndürür."""
    errors = []
    try:
        cfg, comps, ev, meta = _fetch_http()
        method = "httpx"
    except Exception as e:  # noqa: BLE001
        errors.append(f"httpx: {e!r}")
        try:
            cfg, comps, ev, meta = _fetch_playwright()
            method = "playwright"
        except Exception as e2:  # noqa: BLE001
            errors.append(f"playwright: {e2!r}")
            raise ScrapeError("Bülten çekilemedi: " + " | ".join(errors)) from e2

    fetched_at = iso_now()
    now = now_tr()
    day = day or now.date()
    market_cfg = cfg["m"]
    comp_by_id = {c["i"]: c for c in comps}

    # Fikstür yoğunluğu için bültendeki tüm günlerin hafif listesi
    upcoming = [{"ev": e["hn"].strip(), "deplasman": e["an"].strip(),
                 "lig": comp_by_id.get(e["ci"], {}).get("n", "?"),
                 "baslama": dt.datetime.fromtimestamp(e["d"], TR_TZ).isoformat()}
                for e in ev["events"] if e.get("sid") == 1 and e.get("m")]
    matches, skipped = [], {"başlamış": 0, "başka_gün": 0, "pazarsız_özel_bahis": 0, "futbol_değil": 0}
    for e in ev["events"]:
        if e.get("sid") != 1:
            skipped["futbol_değil"] += 1
            continue
        start = dt.datetime.fromtimestamp(e["d"], TR_TZ)
        if start.date() != day:
            skipped["başka_gün"] += 1
            continue
        if start <= now or e.get("s") == 1 or str(e["i"]) in ev.get("sc", {}):
            skipped["başlamış"] += 1
            continue
        if not e.get("m"):
            skipped["pazarsız_özel_bahis"] += 1
            continue
        comp = comp_by_id.get(e["ci"], {})
        markets = [parse_market(m, market_cfg, fetched_at) for m in e["m"]]
        matches.append({
            "mac_kodu": e["i"],
            "betradar_id": e.get("bri"),
            "lig": comp.get("n", "veri yok"),
            "lig_id": e["ci"],
            "ulke": comp.get("cid"),
            "baslama": start.isoformat(),
            "saat": start.strftime("%H:%M"),
            "ev": e["hn"].strip(),
            "deplasman": e["an"].strip(),
            "mbs": e.get("mbc"),
            "toplam_secenek": e.get("oc"),
            "pazarlar": markets,
        })
    matches.sort(key=lambda x: (x["baslama"], x["lig"]))
    return {
        "kaynak": PAGE_URL,
        "uc_noktalar": meta,
        "yontem": method,
        "cekilme_zamani": fetched_at,
        "tarih": day.isoformat(),
        "hatalar": errors,
        "toplam_etkinlik": len(ev["events"]),
        "atlanan": skipped,
        "maclar": matches,
        "tum_gunler": upcoming,
    }


def save_bulletin(data: dict, root: Path) -> Path:
    """Her çekim saat damgalı ayrı dosyaya yazılır; bulten.json en son çekimdir."""
    d = root / "data" / data["tarih"]
    d.mkdir(parents=True, exist_ok=True)
    stamp = data["cekilme_zamani"][11:19].replace(":", "")
    txt = json.dumps(data, ensure_ascii=False, indent=1)
    (d / f"bulten_{stamp}.json").write_text(txt, encoding="utf-8")
    p = d / "bulten.json"
    p.write_text(txt, encoding="utf-8")
    return p


def previous_snapshot(root: Path, day: str, before: str) -> dict | None:
    """Aynı gün, verilen çekimden önceki en son anlık görüntü."""
    d = root / "data" / day
    stamp = before[11:19].replace(":", "")
    snaps = sorted(p for p in d.glob("bulten_*.json") if p.stem.split("_")[1] < stamp)
    return json.loads(snaps[-1].read_text(encoding="utf-8")) if snaps else None


def _main_odds(match: dict) -> dict:
    out = {}
    for key in ("MS", "AU_2.5", "KG"):
        m = market(match, key)
        if m:
            for o in m["outcomes"]:
                if not o["closed"]:
                    out[f"{key}:{o['name']}"] = o["odd"]
    return out


def diff_bulletins(old: dict | None, new: dict, threshold: float = 0.08) -> dict:
    """Yeni/kalkan maçlar ve ana pazarlarda >= %8 oran hareketi."""
    if not old:
        return {"onceki": None, "yeni": [], "kalkan": [], "hareket": {}}
    o = {m["mac_kodu"]: m for m in old["maclar"]}
    n = {m["mac_kodu"]: m for m in new["maclar"]}
    moves = {}
    for k in o.keys() & n.keys():
        a, b = _main_odds(o[k]), _main_odds(n[k])
        ch = {s: (a[s], b[s], round(b[s] / a[s] - 1, 3)) for s in a.keys() & b.keys()
              if abs(b[s] / a[s] - 1) >= threshold}
        if ch:
            moves[k] = ch
    return {
        "onceki": old["cekilme_zamani"],
        "yeni": sorted(n.keys() - o.keys()),
        "kalkan": sorted(o.keys() - n.keys()),   # başladı ya da bültenden çıkarıldı
        "hareket": moves,
    }


def market(match: dict, key: str) -> dict | None:
    for m in match["pazarlar"]:
        if m["key"] == key:
            return m
    return None
