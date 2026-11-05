"""Model doğrulaması: haftalık yeniden kurulum, sonraki haftayı tahmin (geleceği görmeden).
Karşılaştırma: piyasa (football-data ortalama kapanış oranları, marj temizlenmiş) ve temel (lig ortalaması).
Kullanım: python backtest.py [--hafta 10]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import math
from pathlib import Path

import numpy as np

from model.market import fit_market_lambdas
from model.poisson import fit_league, markets
from scrapers.footballdata import MAIN, FootballData, parse_date

ROOT = Path(__file__).resolve().parent


def odds_rows(path: Path) -> dict:
    out = {}
    for r in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))):
        try:
            o = [float(r[k]) for k in ("AvgCH", "AvgCD", "AvgCA")]
            ou = [float(r["AvgC>2.5"]), float(r["AvgC<2.5"])] if r.get("AvgC>2.5") else None
        except (KeyError, ValueError):
            continue
        out[(r["Date"], r["HomeTeam"])] = (o, ou)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--hafta", type=int, default=10); a = ap.parse_args()
    today = dt.date.today()
    fd = FootballData(ROOT / "data" / today.isoformat() / "footballdata", today)
    fd.load(codes=list(MAIN))
    agg = {"model": [0, 0.0], "piyasa": [0, 0.0], "temel": [0, 0.0]}
    agg25 = {"model": [0, 0.0], "piyasa": [0, 0.0]}
    calib = []  # (model olasılığı, gerçekleşti mi) — kalibrasyon kontrolü
    pairs = []  # (model, piyasa, sonuç) — karışım ağırlığı için
    lam = []    # (istatistik λ, piyasa λ, sonuç) — λ karışımı için
    for w in range(a.hafta, 0, -1):
        cut = today - dt.timedelta(days=7 * w)
        end = cut + dt.timedelta(days=7)
        for code, L in fd.leagues.items():
            f = fit_league(L, cut)
            if not f:
                continue
            odds = odds_rows(fd.dir / f"{code}.csv")
            base = [np.mean([m["eg"] > m["dg"] for m in L["onceki_sezon"]]) if L["onceki_sezon"] else 0.45]
            pb = None
            if L["onceki_sezon"]:
                n = len(L["onceki_sezon"])
                pb = [sum(m["eg"] > m["dg"] for m in L["onceki_sezon"]) / n,
                      sum(m["eg"] == m["dg"] for m in L["onceki_sezon"]) / n,
                      sum(m["eg"] < m["dg"] for m in L["onceki_sezon"]) / n]
            for m in L["maclar"]:
                d = parse_date(m["tarih"])
                if d is None or not (cut <= d < end) or m["ev"] not in f["att"] or m["dep"] not in f["att"]:
                    continue
                lh = math.exp(f["mu"] + f["h"] + f["att"][m["ev"]] - f["def"][m["dep"]])
                la = math.exp(f["mu"] + f["att"][m["dep"]] - f["def"][m["ev"]])
                P = markets(lh, la, -0.05, f["iy_pay"] or 0.44)
                res = 0 if m["eg"] > m["dg"] else 1 if m["eg"] == m["dg"] else 2
                pm = [P["MS"]["1"], P["MS"]["0"], P["MS"]["2"]]
                o = odds.get((m["tarih"], m["ev"]))
                if not o or not pb:
                    continue
                inv = [1 / x for x in o[0]]; s = sum(inv); pk = [x / s for x in inv]
                # piyasa λ (kapanış 1X2 + 2.5 A/Ü'den) — iddaa bültenindeki yöntemin aynısı
                fake = {"pazarlar": [
                    {"key": "MS", "outcomes": [{"name": n, "odd": x, "closed": False} for n, x in zip("102", o[0])]}]}
                if o[1]:
                    fake["pazarlar"].append({"key": "AU_2.5", "outcomes": [
                        {"name": "Üst", "odd": o[1][0], "closed": False}, {"name": "Alt", "odd": o[1][1], "closed": False}]})
                mkt = fit_market_lambdas(fake, -0.05, 0.44)
                lam.append((lh, la, mkt["ev"], mkt["dep"], res, (m["eg"] + m["dg"]) > 2.5, d) if mkt else None)
                pairs.append((pm, pk, res, d))
                for k, pr in (("model", pm), ("piyasa", pk), ("temel", pb)):
                    agg[k][0] += 1; agg[k][1] -= math.log(max(pr[res], 1e-9))
                over = (m["eg"] + m["dg"]) > 2.5
                calib.append((P["AU_2.5"]["Üst"], over)); calib.append((pm[0], res == 0))
                if o[1]:
                    inv = [1 / x for x in o[1]]; s = sum(inv); po = inv[0] / s
                    for k, pr in (("model", P["AU_2.5"]["Üst"]), ("piyasa", po)):
                        agg25[k][0] += 1; agg25[k][1] -= math.log(max(pr if over else 1 - pr, 1e-9))
    print(f"Test: son {a.hafta} hafta, {agg['model'][0]} maç (17 ana lig, her hafta yalnızca geçmiş veriyle kurulum)")
    print("MS 1X2 log-loss (düşük = iyi):", {k: round(v[1] / v[0], 4) for k, v in agg.items() if v[0]})
    print("2.5 Alt/Üst log-loss:", {k: round(v[1] / v[0], 4) for k, v in agg25.items() if v[0]})
    # Logaritmik karışım: p ∝ model^w · piyasa^(1−w). Ağırlık ilk yarıda seçilir, ikinci yarıda test edilir.
    pairs.sort(key=lambda x: x[3])
    half = len(pairs) // 2

    def ll(ps, w):
        t = 0.0
        for pm, pk, r, _ in ps:
            q = [max(a, 1e-9) ** w * max(b, 1e-9) ** (1 - w) for a, b in zip(pm, pk)]
            t -= math.log(q[r] / sum(q))
        return t / len(ps)
    grid = [i / 20 for i in range(0, 21)]
    w_best = min(grid, key=lambda w: ll(pairs[:half], w))
    print(f"Karışım ağırlığı (eğitim yarısı, {half} maç): w_model = {w_best}")
    print(f"Test yarısı ({len(pairs) - half} maç) log-loss: piyasa {ll(pairs[half:], 0):.4f} | "
          f"karışım {ll(pairs[half:], w_best):.4f} | model {ll(pairs[half:], 1):.4f}")
    print("Tüm örnek, ağırlığa göre:", {w: round(ll(pairs, w), 4) for w in (0, 0.1, 0.2, 0.3, 0.5)})
    # λ karışımı: λ = piyasa^(1-w) · istatistik^w ; ağırlık eğitim yarısında seçilir
    lam = sorted([x for x in lam if x], key=lambda x: x[6])
    hl = len(lam) // 2

    def ll_lam(rows, w):
        t = 0.0
        for sh, sa, mh, ma, r, ov, _ in rows:
            P = markets(math.exp((1 - w) * math.log(mh) + w * math.log(sh)),
                        math.exp((1 - w) * math.log(ma) + w * math.log(sa)), -0.05, 0.44, full=False)
            pr = [P["MS"]["1"], P["MS"]["0"], P["MS"]["2"]]
            t -= math.log(max(pr[r], 1e-9)) + math.log(max(P["AU_2.5"]["Üst"] if ov else P["AU_2.5"]["Alt"], 1e-9))
        return t / len(rows)
    wgrid = [0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0]
    tr = {w: ll_lam(lam[:hl], w) for w in wgrid}
    w_lam = min(tr, key=tr.get)
    te = {w: ll_lam(lam[hl:], w) for w in (0.0, w_lam, 1.0)}
    print(f"λ karışımı (MS+2.5 toplam log-loss) eğitim: { {k: round(v, 4) for k, v in tr.items()} }")
    print(f"  seçilen w_istatistik = {w_lam} | test yarısı: saf piyasa {te[0.0]:.4f}, karışım {te[w_lam]:.4f}, "
          f"saf istatistik {te[1.0]:.4f}")
    (ROOT / "config" / "model.json").write_text(__import__("json").dumps({
        "w_istatistik": w_lam, "kaynak": f"backtest.py {today.isoformat()} ({len(lam)} maç, eğitim/test yarıları)",
        "test_logloss": {"saf_piyasa": round(te[0.0], 4), "karisim": round(te[w_lam], 4), "saf_istatistik": round(te[1.0], 4)}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print("Kaydedildi: config/model.json")
    import json as _json
    note = (f"Tahminler piyasaya dayalıdır: iddaa'nın MS, Alt/Üst, KG, Çifte Şans ve handikap oranlarından marj "
            f"temizlenip tüm pazarlara uyan tek bir gol beklentisi (λ) çifti çıkarılır; İY, İY/MS, toplam gol gibi diğer "
            f"pazarlar bu λ'dan tutarlı biçimde türetilir. Geri testte ({today.isoformat()}, {len(lam)} maç) bağımsız "
            f"istatistik modelinin en iyi ağırlığı w={w_lam} çıktı (test log-loss: saf piyasa {te[0.0]:.3f}, "
            f"saf istatistik {te[1.0]:.3f}); istatistik modeli bu yüzden ikinci görüş olarak güven skorunda kullanılır. "
            f"'Değer', iddaa'nın bir pazarını kendi diğer pazarlarıyla tutarsız fiyatlamasından doğar; ~%15 marj "
            f"nedeniyle çoğu seçimin beklenen değeri negatiftir.")
    (ROOT / "config" / "backtest_son.json").write_text(_json.dumps({"tarih": today.isoformat(), "not": note},
                                                                ensure_ascii=False, indent=1), encoding="utf-8")
    print("Kaydedildi: config/backtest_son.json")
    print("Kalibrasyon (model olasılığı kovası -> gerçekleşme oranı):")
    for lo in np.arange(0.0, 1.0, 0.1):
        b = [y for p, y in calib if lo <= p < lo + 0.1]
        if len(b) >= 20:
            print(f"  %{100*lo:.0f}-{100*(lo+0.1):.0f}: n={len(b):4d}  gerçekleşen %{100*np.mean(b):.1f}")


if __name__ == "__main__":
    main()
