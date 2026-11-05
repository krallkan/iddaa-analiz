"""Kayıtlı günlük veriden (data/YYYY-MM-DD/) uygulama verisini yeniden üretir; analiz yeniden çalışmaz.
Kullanım: python rebuild_app.py [YYYY-MM-DD]"""
import json
import sys
from pathlib import Path

from report import _coupons, _pick_summary, build_app
from scrapers.common import iso_now, now_tr

ROOT = Path(__file__).resolve().parent
day = sys.argv[1] if len(sys.argv) > 1 else now_tr().date().isoformat()
D = ROOT / "data" / day
L = lambda n: json.loads((D / n).read_text(encoding="utf-8"))  # noqa: E731
data, stats, model, deger, guven = L("bulten.json"), L("istatistik.json"), L("model.json"), L("deger.json"), L("guven.json")
haber = L("haberler.json") if (D / "haberler.json").exists() else None
bt = ROOT / "config" / "backtest_son.json"
note = json.loads(bt.read_text(encoding="utf-8"))["not"] if bt.exists() else ""
by_code = {str(m["mac_kodu"]): m for m in data["maclar"]}
picks = _pick_summary(guven, by_code)
print(build_app(day, ROOT, data, stats, haber, model, deger, guven, note, iso_now(), picks, _coupons(picks)))
