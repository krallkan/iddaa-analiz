# iddaa Günlük Maç Analiz Sistemi

## Telefonda kullanım
- **Uygulama (APK):** https://github.com/krallkan/iddaa-analiz/releases/latest/download/iddaa-analiz.apk
  Sekmeler: Seçimler (güven halkalı günün seçimleri) · Maçlar (lig filtresi, dokunulabilir oranlar) ·
  Favoriler (☆ ile işaretlenen maçlar, canlı olanlar üstte; cihazda saklanır) · Kupon
  (toplam oran, kombine olasılık, MBS uyarısı) · Geçmiş. Bir maça dokununca tüm pazarlar, en olası skorlar, form,
  haberler açılır. Kupon yalnızca cihazda tutulur; uygulama bahis yapmaz ve hiçbir bahis hesabına bağlanmaz.
  Maç detayı sekmeleri: **Oranlar** · **Bilgiler** (Özet, Kadro: sahada dizilim, Sakat/Ceza haberleri) ·
  **İstatistik** (Canlı: gol/İY/korner/kart, Karşılaştırma: form, ortalamalar, son maçlar, kafa kafaya, Puan Durumu) ·
  **Analiz** (model yorumu, iddaa analiz notları, Üst tahminleri). Detaylar maça dokununca iddaa istatistik
  servisinden anlık çekilir. Gece yarısını geçen maçların canlı skoru için iki günün listesi birleştirilir.
  Kupon ekranı: **Kuponu kopyala** (maç · seçim · güncel oran listesi), **Bilyoner'i aç** (kuponu orada elle kurmak için)
  ve **oran kontrolü** (kupondaki her seçimin güncel oranı 10 sn'de bir iddaa maç servisinden; değiştiyse/kapandıysa uyarı).
  **Canlı skor:** başlayan maçlarda dakika, skor, İY skoru, korner ve kırmızı kart; Üst tahminlerinin anlık durumu
  (Tuttu / Kaçtı / X gol daha). Telefon doğrudan iddaa canlı sonuç servisinden çeker
  (`statisticsv2.iddaa.com/live-results`); bizim maçlardan biri canlıyken her yanıttan 1 sn sonra (pratikte 1-2 sn'de bir, ~40 MB/saat), maç başlamak
  üzereyken 15 sn'de, canlı maç yokken 5 dk'da bir; yalnızca uygulama ekrandayken. Aynı gün önceki analizlerde
  gösterilip başlamış maçlar, son tahminleriyle listede kalır (`site.py` → `carry_over`).
  **Canlı oranlar:** canlı maç kartında iddaa'nın açık canlı Üst çizgisi (gol oldukça 4.5, 5.5… açılır) 2 sn'de bir
  (`sportsbook/events?type=1`, yalnızca değişenler); maç detayı açıkken o maçın BÜTÜN canlı Üst çizgileri
  (`sportsbook/event/<kod>`) 2 sn'de bir. Her çizgide canlı tahmin (maç öncesi λ'nın kalan süreye düşen payı +
  mevcut skor, Poisson), piyasa olasılığı ve değer. Canlı orana dokununca o anki oranla kupona eklenir.
- **Bülten ve Canlı:** iddaa'daki bütün maçlar (telefon bülteni doğrudan iddaa'dan çeker, ~1 MB ilk açılışta, sonra
  yalnızca değişenler) ve o an oynanan bütün maçlar. Listede her maç tek satır: saat/canlı dakika, takımlar, MS 1-X-2.
  Satıra dokununca maçın bütün bahisleri (kategorili), canlı oranlar, kadro, istatistik ve analiz açılır.
  **Maç akışı:** gol (golcü, asist, penaltı, kendi kalesine), sarı/kırmızı kart, kaçan/kurtarılan penaltı dakikalarıyla;
  kaynak ESPN herkese açık skor servisi (büyük ligler ve Avrupa kupaları); diğer maçlarda aynı bölümde iddaa canlı
  özeti (skor, İY, korner, kartlar) gösterilir. Canlı maç detayı açıkken
  her saniye yenilenir. iddaa ↔ ESPN maç eşleştirmesi başlama saati + takım adı benzerliği + canlı skorla yapılır.
  Uygulama kapalıyken bildirim gönderilmez.
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
