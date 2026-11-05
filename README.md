# iddaa Günlük Maç Analiz Sistemi

## Telefonda kullanım
- **Uygulama (APK):** https://github.com/krallkan/iddaa-analiz/releases/latest/download/iddaa-analiz.apk
  Sekmeler: Seçimler (güven halkalı günün seçimleri) · Maçlar (lig filtresi, dokunulabilir oranlar) · Kupon
  (toplam oran, kombine olasılık, MBS uyarısı) · Geçmiş. Bir maça dokununca tüm pazarlar, en olası skorlar, form,
  haberler açılır. Kupon yalnızca cihazda tutulur; uygulama bahis yapmaz.
- **Tarayıcıdan:** https://krallkan.github.io/iddaa-analiz/ (aynı arayüz) · metin rapor: `rapor.html`
- **Otomatik çalışma:** `.github/workflows/analiz.yml` her gün 09:07, 12:07, 15:07, 18:07 ve 20:07'de (TSİ) analizi
  çalıştırıp sayfayı günceller (GitHub zamanlanmış işleri bazen geciktirir/atlar; sık çalıştırma bunu telafi eder); elle çalıştırmak için Actions → "Günlük analiz" → Run workflow. Her pazartesi geri test yapılır.
- **APK derleme:** `.github/workflows/apk.yml`, `android/` değiştiğinde APK'yı derleyip Release olarak yayınlar.
  Arayüz (`web/`) GitHub Pages'ten yüklendiği için tasarım güncellemeleri APK'yı yeniden kurmadan gelir.
  APK her derlemede farklı hata ayıklama anahtarıyla imzalanır; yeni APK sürümünü kurmak için eskisini kaldırın.

## Kurulum
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
Playwright isteğe bağlıdır; yalnızca bülten JSON uç noktası doğrudan çekilemezse yedek olarak kullanılır
(`pip install playwright && playwright install chromium`; özel Chromium yolu için `CHROMIUM_PATH` ortam değişkeni).

## Çalıştırma
| Komut | Ne yapar |
|---|---|
| `python main.py` | Tüm akış: bülten → filtre → istatistik → haber → model → değer → güven → rapor |
| `python site.py` | Raporu ve uygulama arayüzünü `site/` klasörüne hazırlar (GitHub Pages) |
| `python rebuild_app.py` | Kayıtlı günlük veriden uygulama verisini yeniden üretir (analiz çalışmaz) |
| `python main.py --mac 3269194` | Tek maç (iddaa etkinlik kodu) detaylı analiz → `reports/YYYY-MM-DD_mac_<kod>.md` |
| `python main.py --adim <adım>` | Belirtilen adımdan sonra dur (bulten, filtre, istatistik, haber, model, deger, guven) |
| `python backtest.py` | Modeli son 10 haftada piyasaya karşı test eder; sonuç rapora "dürüst not" olarak girer. Haftada bir çalıştırın. |

Gün içinde birden fazla çalıştırılabilir: bülten ve oranlar her seferinde yeniden çekilir, takım istatistikleri
günlük önbellekten okunur, haberler ve tahmini 11'ler her seferinde yeniden taranır.

## Çıktılar
- `reports/YYYY-MM-DD.md/.json` — günün son raporu; `reports/YYYY-MM-DD_HHMM.md` — her çalıştırmanın kopyası
- `data/YYYY-MM-DD/` — ham ve işlenmiş veri: `bulten_HHMMSS.json` (her çekim), `istatistik.json`, `haberler.json`,
  `model.json`, `deger.json`, `guven.json`

## Ayarlar (`config/`)
- `filtre.json` — lig seviyeleri (regex), eleme kuralları, kapasite
- `manuel_duzeltme.json` — haber kaynaklı λ düzeltmeleri (gerekçe + kaynak zorunlu, yalnızca o günün tarihi uygulanır)
- `takim_alias.json` — iddaa ↔ football-data takım adı eşleme
- `takim_ulke.json` — otomatik bulunamayan takım ülkeleri
- `pazarlar.json` — uygulamada ve seçimlerde gösterilecek seçenekler (şu an: İY 1.5 Üst, 2.5/3.5/4.5 Üst; Alt yok)

## Kaynaklar
iddaa bülten (`sportsbookv2.iddaa.com`), iddaa istatistik (`statisticsv2.iddaa.com`, Betradar/Perform verisi),
football-data.co.uk (sezon sonuçları, xG, korner), UEFA ülke katsayıları (`comp.uefa.com`), Google News RSS.
Sofascore / FBref / Mackolik bot korumasıyla erişimi engelliyor; ClubElo bağlantıyı reddediyor.

## Bilinen sınırlar
- Tahminler piyasaya dayalıdır (iddaa oranlarına uyan λ); istatistik modeli geri testte piyasaya bilgi eklemediği
  için ikinci görüş olarak kullanılır. ~%15 marj nedeniyle seçimlerin çoğunun beklenen değeri negatiftir.
- Haberler yalnızca başlıktan okunur; başlıktan çıkan eksik oyuncu bilgisi "doğrulanmamış" sayılır ve λ'yı değiştirmez.
- football-data'da olmayan ligler (Çekya, Hırvatistan, Bulgaristan, Kıbrıs vb.) için güç, iddaa son 10 maçtan rakip
  gücü düzeltilmeden çıkarılır (veri kalitesi 0.45).
- iddaa kadro servisi resmi 11 değildir.

**Bu analiz istatistiksel bir tahmindir, sonuç garantisi vermez. Kaybetmeyi göze alabileceğin miktarla oyna.**
