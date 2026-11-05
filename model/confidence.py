"""Adım 8: güven skoru (0-100).

GÜVEN = 30·O + 30·U + 20·V + 20·İ − H        (0-100 aralığına kırpılır)

  O (olasılık)  = (p_model − 0.40) / 0.45 , [0,1]      -> %40'ta 0, %85'te 1
  U (uyum)      = 1 − |p_istatistik − p| / 0.15 , [0,1]  -> bağımsız istatistik modeli piyasaya dayalı
                  tahmini doğruluyor mu? şüpheli (>15 puan) -> 0; istatistik yoksa 0.5
  V (veri)      = modelin veri kalitesi (football-data+xG 1.0, xG'siz 0.85, yalnız iddaa son 10 maç 0.45);
                  "düşük veri" (<8 maç) ise ×0.5
  İ (istikrar)  = 1 − (ort. puan std. sapması − 0.9) / 0.6 , [0,1]  -> sapma ≤0.9 tam puan, ≥1.5 sıfır
  H (haber)     = min(15, 3·sakatlık/ceza haberi(en fazla 2) + 4·TD/kriz + 3·rotasyon
                         + 2·doğrulanmamış eksik oyuncu + 2·yoğun fikstür)

Gerekçe: geri testte saf piyasa λ'sı en iyi sonucu verdi (config/model.json); p bu yüzden piyasaya dayalı.
İstatistik modeli bağımsız ikinci görüş olarak U bileşeninde kullanılır. "Değer" skora girmez, raporlanır.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

W_O, W_U, W_V, W_I = 30, 30, 20, 20
H_MAX = 15
MIN_ORAN, MAX_ORAN = 1.25, 5.0
MIN_OLASILIK = 0.55  # özete girmek için model olasılığı alt sınırı
_PZ = Path(__file__).resolve().parent.parent / "config" / "pazarlar.json"
IZINLI = {(x["pazar"], x["secenek"]) for x in json.loads(_PZ.read_text(encoding="utf-8"))["izinli"]} if _PZ.exists() else None

FORMUL = ("GÜVEN = 30·O + 30·U + 20·V + 20·İ − H | p=piyasaya dayalı olasılık | O=(p−0.40)/0.45 | "
          "U=1−|p_istatistik−p|/0.15 (şüpheli→0) | "
          "V=veri kalitesi | İ=1−(puan_sd−0.9)/0.6 | H=haber/rotasyon riski (≤15) | "
          "Özet şartı: yalnızca config/pazarlar.json'daki seçenekler (İY 1.5 Üst, 2.5/3.5/4.5 Üst), oran 1.25-5.00, model ≥%55")


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def news_risk(news: dict | None, stats: dict, start_iso: str) -> tuple[float, list[str]]:
    reasons, h = [], 0.0
    r = (news or {}).get("risk", {})
    if not news:
        reasons.append("haber taraması yok"); h += 3
    sc = min(r.get("sakatlik_ceza_haberi", 0), 2)
    if sc:
        h += 3 * sc; reasons.append(f"{r['sakatlik_ceza_haberi']} sakatlık/ceza haberi")
    if r.get("td_kriz_haberi"):
        h += 4; reasons.append("teknik direktör/kriz haberi")
    if r.get("rotasyon_haberi"):
        h += 3; reasons.append("rotasyon haberi")
    if r.get("olasi_eksik_oyuncu"):
        h += 2; reasons.append("doğrulanmamış eksik oyuncu: " +
                               ", ".join(x["oyuncu"] for x in r["olasi_eksik_oyuncu"]))
    t0 = dt.datetime.fromisoformat(start_iso)
    for side in ("ev", "dep"):
        nxt = stats["fikstur"].get(f"{side}_sonraki", [])
        soon = [x for x in nxt if (dt.datetime.fromisoformat(x[:16] + ":00+03:00") - t0).days < 3]
        if soon and stats[side]["son7_gun_mac"] >= 2:
            h += 2; reasons.append(f"{side}: yoğun fikstür (son 7 günde {stats[side]['son7_gun_mac']} maç, 3 gün içinde yeni maç)")
    return min(h, H_MAX), reasons


def score(rec: dict, pred: dict, stats: dict, news: dict | None, start_iso: str) -> dict:
    p = rec["model"]
    O = _clip((p - 0.40) / 0.45)
    if rec.get("istatistik") is None:
        U = 0.5
    elif rec.get("supheli"):
        U = 0.0
    else:
        U = _clip(1 - abs(rec["istatistik"] - p) / 0.15)
    V = pred["veri_kalitesi"] * (0.5 if stats["veri_yeterliligi"]["dusuk_veri"] else 1.0)
    sds = [stats[s]["puan_sd"] for s in ("ev", "dep") if stats[s]["puan_sd"] is not None]
    I = _clip(1 - ((sum(sds) / len(sds)) - 0.9) / 0.6) if sds else 0.5
    H, why = news_risk(news, stats, start_iso)
    g = W_O * O + W_U * U + W_V * V + W_I * I - H
    return {"guven": round(_clip(g, 0, 100), 1),
            "bilesen": {"O": round(O, 3), "U": round(U, 3), "V": round(V, 3), "I": round(I, 3), "H": H},
            "haber_riski_nedenleri": why}


def eligible_for_summary(rec: dict) -> tuple[bool, str]:
    if IZINLI is not None and (rec["pazar"], rec["secenek"]) not in IZINLI:
        return False, "izinli pazarlar dışında (config/pazarlar.json)"
    if rec["kapali"]:
        return False, "seçenek kapalı"
    if rec.get("piyasa") is None:
        return False, "piyasa olasılığı hesaplanamadı"
    if not (MIN_ORAN <= rec["oran"] <= MAX_ORAN):
        return False, f"oran {rec['oran']:.2f} özet aralığı dışında ({MIN_ORAN}-{MAX_ORAN})"
    if rec["model"] < MIN_OLASILIK:
        return False, f"model olasılığı %{100*rec['model']:.0f} < %{100*MIN_OLASILIK:.0f}"
    if rec["guvenilirlik"] != "normal":
        return False, "düşük güvenilirlikli pazar (korner)"
    return True, ""
