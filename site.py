"""Raporu telefona uygun HTML sayfasına çevirir (GitHub Pages için).

Kullanım: python site.py [--onceki https://<kullanıcı>.github.io/<depo>/manifest.json]
Çıktı: site/index.html (son rapor), site/r/<rapor>.html, site/manifest.json (geçmiş liste)
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path

import math

import httpx
import markdown

ROOT = Path(__file__).resolve().parent
TUT = 60  # listede tutulacak rapor sayısı

CSS = """
:root{--bg:#f6f7f9;--fg:#15181d;--muted:#5d6672;--card:#fff;--line:#dfe3e8;--acc:#0b6bcb;--warn:#8a5a00;--warnbg:#fff4dc}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--fg:#e8ebef;--muted:#9aa4b0;--card:#171b21;--line:#2a3039;--acc:#5aa9ff;--warn:#ffcf70;--warnbg:#2b2312}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:12px 16px 48px}
h1{font-size:1.35rem;margin:.6rem 0}h2{font-size:1.15rem;margin:1.6rem 0 .6rem;padding-top:.6rem;border-top:1px solid var(--line)}
h3{font-size:1rem;margin:1.4rem 0 .4rem;background:var(--card);padding:10px 12px;border:1px solid var(--line);border-radius:10px}
a{color:var(--acc)}p,li{overflow-wrap:anywhere}
blockquote{margin:.8rem 0;padding:10px 12px;background:var(--warnbg);color:var(--fg);border-left:4px solid var(--warn);border-radius:6px;font-size:.9rem}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:.5rem 0;border:1px solid var(--line);border-radius:8px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:.85rem;white-space:nowrap}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}th{position:sticky;top:0;background:var(--card)}
code{font-size:.8rem;white-space:normal}
nav{display:flex;gap:12px;flex-wrap:wrap;font-size:.9rem;margin:.4rem 0 1rem;color:var(--muted)}
.arsiv a{display:block;padding:10px 12px;margin:6px 0;background:var(--card);border:1px solid var(--line);border-radius:8px;text-decoration:none}
"""


def page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='tr'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>")


def render_md(md_text: str) -> str:
    h = markdown.markdown(md_text, extensions=["tables"])
    return h.replace("<table>", "<div class='tw'><table>").replace("</table>", "</table></div>")


def carry_over(cur: dict, manifest_url: str, manifest: list[dict]) -> dict:
    """Aynı gün önceki analizlerde gösterilip artık başlamış maçları (son tahminleriyle) listede tutar;
    böylece uygulama bu maçların canlı skorunu ve tahminin tutup tutmadığını gösterebilir."""
    base = manifest_url.rsplit("/", 1)[0]
    have = {m["kod"] for m in cur["maclar"]}
    picks = {o["kod"] for o in cur["ozet"]}
    import datetime as _dt
    today = _dt.date.fromisoformat(cur["tarih"])
    prev_day = (today - _dt.timedelta(days=1)).isoformat()
    now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=3)))
    for mm in sorted(manifest, key=lambda x: x["ad"], reverse=True):
        # aynı gün + önceki gün (gece yarısını geçen maçlar için; aşağıda son 6 saatle sınırlanır)
        if mm.get("tarih") not in (cur["tarih"], prev_day) or not mm.get("data"):
            continue
        try:
            r = httpx.get(f"{base}/{mm['data']}", timeout=20)
            old = r.json() if r.status_code == 200 else None
        except Exception:  # noqa: BLE001
            old = None
        if not old:
            continue
        for m in old.get("maclar", []):
            if m["kod"] in have:
                continue
            if mm.get("tarih") == prev_day:   # önceki gün: yalnızca son 6 saatte başlamış (hâlâ sürüyor olabilecek) maçlar
                try:
                    if now - _dt.datetime.fromisoformat(m["baslama"]) > _dt.timedelta(hours=6):
                        continue
                except (KeyError, ValueError):
                    continue
            m["baslamis"] = True              # oranlar artık güncellenmiyor; canlı skor uygulamada
            m["oran_zamani"] = old.get("oran_zamani")
            if cur.get("pazarlar"):           # eski analizde izinli olmayan seçenekleri gösterme
                ok = {(z["pazar"], z["secenek"]) for z in cur["pazarlar"]}
                m["secenekler"] = [o for o in m["secenekler"] if (o["p"], o["s"]) in ok]
                have_o = {(o["p"], o["s"]) for o in m["secenekler"]}
                lam = m.get("lambda") or {}
                for z in cur["pazarlar"]:     # eksik izinli seçenek: kayıtlı λ'dan Poisson ile tahmin
                    if (z["pazar"], z["secenek"]) in have_o or not lam or not z["pazar"].startswith("AU_"):
                        continue
                    line, mu = float(z["pazar"][3:]), lam["ev"] + lam["dep"]
                    p_over = 1 - sum(math.exp(-mu) * mu ** k / math.factorial(k) for k in range(int(line) + 1))
                    m["secenekler"].append({"p": z["pazar"], "pa": z["pazar_adi"], "s": z["secenek"], "o": None,
                                            "m": round(p_over, 4), "pk": None, "i": None, "d": None, "g": None,
                                            "ok": False, "sup": False, "mbs": m.get("mbs"), "etiket": z["etiket"]})
                for o in m["secenekler"]:
                    o.setdefault("etiket", next((z["etiket"] for z in cur["pazarlar"]
                                                 if (z["pazar"], z["secenek"]) == (o["p"], o["s"])), o["s"]))
                if m.get("secim") and (m["secim"]["p"], m["secim"]["s"]) not in ok:
                    m["secim"] = None
            cur["maclar"].append(m)
            have.add(m["kod"])
            for o in old.get("ozet", []):
                if o["kod"] == m["kod"] and o["kod"] not in picks and (
                        not cur.get("pazarlar") or (o["p"], o["s"]) in {(z["pazar"], z["secenek"]) for z in cur["pazarlar"]}):
                    cur["ozet"].append({**o, "baslamis": True})
                    picks.add(o["kod"])
    cur["maclar"].sort(key=lambda x: (x["baslama"], x["lig"]))
    return cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onceki", help="Önceki manifest.json adresi (geçmiş raporlar listesi için)")
    a = ap.parse_args()
    reps = sorted(p for p in (ROOT / "reports").glob("????-??-??_????.md"))
    if not reps:
        raise SystemExit("reports/ içinde rapor yok — önce python main.py çalıştırın")
    latest = reps[-1]
    out = ROOT / "site"
    (out / "r").mkdir(parents=True, exist_ok=True)

    manifest = []
    if a.onceki:
        try:
            r = httpx.get(a.onceki, timeout=20)
            if r.status_code == 200:
                manifest = r.json()
        except Exception:  # noqa: BLE001
            manifest = []
    # Uygulama (web/) ve veri dosyaları
    shutil.copytree(ROOT / "web", out / "app", dirs_exist_ok=True)
    (out / "d").mkdir(exist_ok=True)
    if (ROOT / "reports" / "app.json").exists():
        cur = json.loads((ROOT / "reports" / "app.json").read_text(encoding="utf-8"))
        if a.onceki:
            cur = carry_over(cur, a.onceki, manifest)
        (out / "data.json").write_text(json.dumps(cur, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for p in (ROOT / "reports").glob("app_????-??-??_????.json"):
        shutil.copy(p, out / "d" / f"{p.stem[4:]}.json")
    for p in reps:
        name = p.stem
        body = render_md(p.read_text(encoding="utf-8"))
        nav = "<nav><a href='../rapor.html'>Son rapor</a><a href='../arsiv.html'>Geçmiş raporlar</a><a href='../app/'>Uygulama</a></nav>"
        (out / "r" / f"{name}.html").write_text(page(f"iddaa analiz {name}", nav + body), encoding="utf-8")
        if name not in [m["ad"] for m in manifest]:
            d, t = name.split("_")
            manifest.append({"ad": name, "tarih": d, "saat": f"{t[:2]}:{t[2:]}"})
    for dp in (out / "d").glob("*.json"):   # yalnızca uygulama verisi olan çalıştırmalar da listelensin
        if dp.stem not in [m["ad"] for m in manifest]:
            d, t = dp.stem.split("_")
            manifest.append({"ad": dp.stem, "tarih": d, "saat": f"{t[:2]}:{t[2:]}"})
    manifest = sorted(manifest, key=lambda m: m["ad"], reverse=True)[:TUT]
    for mm in manifest:
        if (out / "d" / f"{mm['ad']}.json").exists():
            mm["data"] = f"d/{mm['ad']}.json"
    manifest = sorted(manifest, key=lambda m: m["ad"], reverse=True)[:TUT]

    nav = "<nav><a href='arsiv.html'>Geçmiş raporlar</a></nav>"
    idx = render_md(latest.read_text(encoding="utf-8")).replace("href='../", "href='")
    (out / "rapor.html").write_text(page("iddaa Günlük Analiz", nav + idx), encoding="utf-8")
    # Ana adres uygulamaya yönlenir; düz metin rapor rapor.html'de
    (out / "index.html").write_text("<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='0;url=app/'>"
                                    "<a href='app/'>Maç Analiz</a> · <a href='rapor.html'>Metin rapor</a>", encoding="utf-8")
    items = "".join(f"<a href='r/{m['ad']}.html'>{m['tarih']} · {m['saat']}</a>" for m in manifest)
    (out / "arsiv.html").write_text(page("Geçmiş raporlar",
                                         "<nav><a href='rapor.html'>Son rapor</a><a href='app/'>Uygulama</a></nav><h1>Geçmiş raporlar</h1>"
                                         f"<div class='arsiv'>{items}</div>"), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"site/ hazır: son rapor {latest.name}, arşivde {len(manifest)} rapor")


if __name__ == "__main__":
    main()
