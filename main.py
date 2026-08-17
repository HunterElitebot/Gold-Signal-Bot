import os
import json
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

# =============================================================================
# GoldSignal Bot — Altın (XAU/USD) ve Gümüş (XAG/USD) için EMA/RSI tabanlı
# yön sinyali üretir, Telegram'a otomatik bildirim gönderir.
#
# Railway'de gerekli environment variable'lar:
#   TOKEN            - Telegram bot token (@BotFather'dan)
#   SIGNAL_CHAT_ID    - sinyallerin gönderileceği chat id
#   TWELVEDATA_API_KEY - twelvedata.com/register üzerinden ücretsiz alınır
#
# Opsiyonel (varsayılanlar makul, dokunmasanız da çalışır):
#   SCAN_INTERVAL_SEC   - kaç saniyede bir kontrol edilsin (varsayılan 300 = 5dk)
#   CANDLE_INTERVAL     - mum periyodu (1min, 5min, 15min, 1h ...) (varsayılan 15min)
#   EMA_FAST / EMA_SLOW - EMA periyotları (varsayılan 9 / 21)
#   RSI_PERIOD          - RSI periyodu (varsayılan 14)
# =============================================================================

VERSION = "GoldSignal V1.0"

TOKEN = os.getenv("TOKEN", "").strip()
SIGNAL_CHAT_ID = os.getenv("SIGNAL_CHAT_ID", "").strip()
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "").strip()

SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300"))
CANDLE_INTERVAL = os.getenv("CANDLE_INTERVAL", "15min")
EMA_FAST = int(os.getenv("EMA_FAST", "9"))
EMA_SLOW = int(os.getenv("EMA_SLOW", "21"))
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_LOWER = float(os.getenv("RSI_LOWER", "30"))
RSI_UPPER = float(os.getenv("RSI_UPPER", "70"))

SYMBOLS = {
    "ALTIN (XAU/USD)": "XAU/USD",
    "GÜMÜŞ (XAG/USD)": "XAG/USD",
}

if not TOKEN:
    raise RuntimeError("Railway TOKEN degiskeni eksik (Telegram bot token)")
if not SIGNAL_CHAT_ID:
    print("WARNING: SIGNAL_CHAT_ID eksik - otomatik bildirim gonderilemeyecek.", flush=True)
if not TWELVEDATA_API_KEY:
    print("WARNING: TWELVEDATA_API_KEY eksik - fiyat verisi cekilemeyecek.", flush=True)

TG_API = f"https://api.telegram.org/bot{TOKEN}"

# -----------------------------------------------------------------------
# Kalıcı durum (Railway Volume varsa /data, yoksa /tmp'ye düşer)
# -----------------------------------------------------------------------

def _resolve_data_dir():
    candidate = os.getenv("DATA_DIR", "/data")
    try:
        os.makedirs(candidate, exist_ok=True)
        probe = os.path.join(candidate, ".write_test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return candidate
    except Exception as e:
        print(f"DATA_DIR '{candidate}' yazilamiyor ({e!r}) - /tmp kullanilacak "
              f"(Railway Volume eklenene kadar durum deploy'lar arasi kalici olmaz).", flush=True)
        return "/tmp"

DATA_DIR = _resolve_data_dir()
STATE_FILE = os.path.join(DATA_DIR, "goldsignal_state.json")
state_lock = threading.Lock()


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    with state_lock:
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(state, f)
        except Exception as e:
            print("STATE SAVE ERROR:", repr(e), flush=True)


# -----------------------------------------------------------------------
# Telegram yardımcıları
# -----------------------------------------------------------------------

def telegram(method, data=None, timeout=30):
    url = f"{TG_API}/{method}"
    body = urllib.parse.urlencode(data or {}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def send(chat_id, text):
    try:
        telegram("sendMessage", {
            "chat_id": str(chat_id),
            "text": text[:4000],
            "parse_mode": "Markdown",
            "disable_web_page_preview": "true",
        })
    except Exception as e:
        print("SEND ERROR:", repr(e), flush=True)


# -----------------------------------------------------------------------
# Twelve Data'dan fiyat verisi çekme
# -----------------------------------------------------------------------

def fetch_candles(symbol, outputsize=100):
    """Twelve Data time_series endpoint'inden OHLC verisini çeker.
    Dönen liste en eskiden en yeniye sıralı (index 0 = en eski)."""
    params = {
        "symbol": symbol,
        "interval": CANDLE_INTERVAL,
        "outputsize": str(outputsize),
        "apikey": TWELVEDATA_API_KEY,
    }
    url = "https://api.twelvedata.com/time_series?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"FETCH ERROR ({symbol}):", repr(e), flush=True)
        return None

    if data.get("status") == "error":
        print(f"TWELVEDATA ERROR ({symbol}):", data.get("message"), flush=True)
        return None

    values = data.get("values")
    if not values:
        return None

    values = list(reversed(values))  # API en yeniden en eskiye veriyor, çeviriyoruz
    closes = [float(v["close"]) for v in values]
    return closes


# -----------------------------------------------------------------------
# İndikatörler (harici kütüphane gerektirmez)
# -----------------------------------------------------------------------

def ema_series(values, period):
    k = 2 / (period + 1)
    ema = [values[0]]
    for price in values[1:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema


def rsi_last(values, period):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def generate_signal(closes):
    """EMA kesişimi + RSI teyidiyle AL / SAT / NÖTR üretir."""
    min_len = max(EMA_SLOW, RSI_PERIOD) + 2
    if len(closes) < min_len:
        return "NÖTR", closes[-1] if closes else None, None

    ema_f = ema_series(closes, EMA_FAST)
    ema_s = ema_series(closes, EMA_SLOW)
    rsi = rsi_last(closes, RSI_PERIOD)
    price = closes[-1]

    prev_diff = ema_f[-2] - ema_s[-2]
    curr_diff = ema_f[-1] - ema_s[-1]

    if rsi is None:
        return "NÖTR", price, rsi

    if prev_diff <= 0 and curr_diff > 0 and RSI_LOWER < rsi < RSI_UPPER:
        return "AL", price, rsi
    if prev_diff >= 0 and curr_diff < 0 and RSI_LOWER < rsi < RSI_UPPER:
        return "SAT", price, rsi
    return "NÖTR", price, rsi


def format_message(name, signal, price, rsi):
    emoji = "🟢" if signal == "AL" else "🔴"
    return (
        f"{emoji} *{signal} SİNYALİ* — {name}\n"
        f"Fiyat: {price:.2f}\n"
        f"RSI: {rsi:.1f}\n"
        f"Zaman dilimi: {CANDLE_INTERVAL}\n\n"
        f"_Otomatik teknik sinyal, yatırım tavsiyesi değildir._"
    )


# -----------------------------------------------------------------------
# Ana tarama döngüsü
# -----------------------------------------------------------------------

def scan_once(state):
    if not TWELVEDATA_API_KEY:
        return

    for name, symbol in SYMBOLS.items():
        closes = fetch_candles(symbol)
        if not closes:
            print(f"[UYARI] {name} icin veri alinamadi.", flush=True)
            continue

        signal, price, rsi = generate_signal(closes)
        last_signal = state.get(symbol)

        print(
            f"[{time.strftime('%H:%M:%S')}] {name}: {signal} "
            f"(Fiyat: {price:.2f}, RSI: {rsi if rsi is None else round(rsi,1)})",
            flush=True,
        )

        if signal != "NÖTR" and signal != last_signal:
            if SIGNAL_CHAT_ID:
                send(SIGNAL_CHAT_ID, format_message(name, signal, price, rsi))
            state[symbol] = signal
            save_state(state)
        elif signal == "NÖTR" and last_signal is not None:
            state[symbol] = None
            save_state(state)


def auto_scanner():
    state = load_state()
    while True:
        try:
            scan_once(state)
        except Exception as e:
            print("SCANNER ERROR:", repr(e), flush=True)
        time.sleep(SCAN_INTERVAL_SEC)


# -----------------------------------------------------------------------
# Railway health check
# -----------------------------------------------------------------------

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"GoldSignal {VERSION} ONLINE".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


def health_server():
    port = int(os.getenv("PORT", "8080"))
    HTTPServer(("0.0.0.0", port), Health).serve_forever()


def startup_notify():
    if not SIGNAL_CHAT_ID:
        return
    send(SIGNAL_CHAT_ID, f"""GoldSignal {VERSION} ONLINE

Takip edilen: {', '.join(SYMBOLS.keys())}
Zaman dilimi: {CANDLE_INTERVAL}
Tarama aralığı: {SCAN_INTERVAL_SEC} sn
EMA: {EMA_FAST}/{EMA_SLOW} | RSI: {RSI_PERIOD} ({RSI_LOWER}-{RSI_UPPER})

Sistem aktif, sinyal değişimlerinde bildirim gelecek.""")


if __name__ == "__main__":
    print(f"GOLDSIGNAL {VERSION} STARTING", flush=True)
    print(f"SCAN INTERVAL: {SCAN_INTERVAL_SEC}s | CANDLE: {CANDLE_INTERVAL}", flush=True)
    print(f"TWELVEDATA KEY: {'READY' if TWELVEDATA_API_KEY else 'MISSING'}", flush=True)

    threading.Thread(target=health_server, daemon=True).start()
    time.sleep(1)
    startup_notify()
    auto_scanner()
