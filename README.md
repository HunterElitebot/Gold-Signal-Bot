# GoldSignal Bot

Altın (XAU/USD) ve Gümüş (XAG/USD) için EMA(9/21) kesişimi + RSI(14) teyidiyle
AL/SAT sinyali üretir, Telegram'a otomatik bildirim gönderir.

## Railway'e Deploy Etme

1. Bu klasördeki dosyaları (main.py, requirements.txt) GitHub reponuza pushlayın
2. Railway'de "New Project" → "Deploy from GitHub repo" ile bu repoyu seçin
3. Railway'in "Variables" sekmesinden şu environment variable'ları ekleyin:

   | Değişken | Açıklama | Zorunlu mu |
   |---|---|---|
   | `TOKEN` | Telegram bot token (@BotFather'dan) | Evet |
   | `SIGNAL_CHAT_ID` | Sinyallerin gideceği chat/grup id'si | Evet (yoksa sadece log'a yazar) |
   | `TWELVEDATA_API_KEY` | twelvedata.com/register üzerinden ücretsiz alın | Evet |
   | `SCAN_INTERVAL_SEC` | Kaç saniyede bir kontrol (varsayılan 300) | Hayır |
   | `CANDLE_INTERVAL` | Mum periyodu: 1min, 5min, 15min, 1h... (varsayılan 15min) | Hayır |

4. Kalıcı durum için (opsiyonel ama önerilir): Railway'de bir **Volume** oluşturup
   `/data` yoluna mount edin — böylece deploy/restart sonrası bot son sinyal
   durumunu unutmaz, aynı sinyali tekrar tekrar göndermez.

5. Deploy edin. Loglardan "GOLDSIGNAL ... STARTING" mesajını görmelisiniz.

## Telegram Chat ID Bulma

1. Botu oluşturun (@BotFather → /newbot)
2. Bota bir mesaj gönderin veya bir gruba ekleyip mesaj attırın
3. Tarayıcıda açın: `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Dönen JSON'da `"chat":{"id": ...}` kısmındaki sayıyı `SIGNAL_CHAT_ID` yapın

## Twelve Data API Key

1. https://twelvedata.com/register adresinden ücretsiz kayıt olun
2. Dashboard'dan API key'inizi kopyalayın
3. Ücretsiz katman günde 800 istek veriyor — varsayılan ayarlarla
   (5 dakikada bir, 2 sembol) günde ~576 istek harcanır, sınırın altında kalır

## Notlar

- Bu sistem **kripto sinyal botundan (HunterElite) tamamen bağımsız** çalışır —
  aynı Railway hesabında ayrı bir servis olarak deploy edilmesi önerilir,
  ikisini aynı process'te birleştirmeyin (farklı veri kaynakları, farklı mantık)
- Sinyal sadece **yön değiştiğinde** gönderilir, aynı sinyali spamlemez
- Bu bir teknik analiz aracıdır, yatırım tavsiyesi değildir
