"""Send an alert by email (Gmail SMTP) and phone push (ntfy.sh).

Configured through environment variables (GitHub secrets):
  GMAIL_USER, GMAIL_APP_PASSWORD  - Gmail account + app password used to send
  EMAIL_TO                        - comma-separated recipients
  NTFY_TOPIC                      - optional ntfy.sh topic for phone push alerts
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS - optional Telegram bot + comma-separated chat ids
Usage: python notify.py "subject" "body"
       python notify.py --alert   (builds the message from AVAILABLE, DATE, TIMES env vars)
"""
import os
import smtplib
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage


def send_email(subject, body):
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    to = [a.strip() for a in os.environ.get("EMAIL_TO", "").split(",") if a.strip()]
    if not (user and pw and to):
        print("email: not configured, skipping")
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, ", ".join(to)
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.send_message(msg)
    print(f"email: sent to {len(to)} recipient(s)")
    return True


def send_push(subject, body):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("push: not configured, skipping")
        return False
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=body.encode(),
        headers={"Title": subject.encode("ascii", "ignore").decode(), "Priority": "urgent",
                 "Tags": "rotating_light,train",
                 "Click": os.environ.get("CLICK_URL", "https://www.renfe.com/es/es")},
    )
    urllib.request.urlopen(req, timeout=20)
    print("push: sent")
    return True


def send_telegram(subject, body):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]
    if not (token and chats):
        print("telegram: not configured, skipping")
        return False
    sent = 0
    for chat in chats:
        data = urllib.parse.urlencode({"chat_id": chat, "text": f"{subject}\n\n{body}"}).encode()
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=20)
            sent += 1
        except Exception as e:
            print(f"telegram: failed for one chat: {e}")
    print(f"telegram: sent to {sent} chat(s)")
    return sent > 0


def search_url(date):
    """Renfe link that opens the train list for this route and date, ready to buy."""
    params = {
        "Idioma": "es", "Pais": "ES", "tipoBusqueda": "autocomplete",
        "currenLocation": "menuBusqueda", "vengoderenfecom": "SI",
        "desOrigen": "GRANADA", "desDestino": "MÁLAGA MARÍA ZAMBRANO",
        "cdgoOrigen": "0071,05000,05000", "cdgoDestino": "0071,54413,54413",
        "idiomaBusqueda": "ES", "FechaIdaSel": date, "_fechaIdaVisual": date,
        "FechaVueltaSel": "", "_fechaVueltaVisual": "", "adultos_": "1", "ninos_": "0",
        "ninosMenores": "0", "plazaH": "false", "sinEnlace": "false",
        "conMascota": "false", "conBicicleta": "false", "asistencia": "false",
    }
    return "https://venta.renfe.com/vol/buscarTren.do?" + urllib.parse.urlencode(params, safe=",/")


def build_alert(available=None, date=None, watched=None):
    date = date or os.environ.get("DATE", "30/10/2026")
    if available is None:
        available = os.environ.get("AVAILABLE", "").split()
    url = search_url(date)
    if available:
        trains = " & ".join(available)
        subject = f"🚨🚨 RENFE TICKETS AVAILABLE NOW: {trains} GRANADA → MÁLAGA {date} 🚨🚨"
        body = (
            f"🚨🚨🚨 BUY NOW 🚨🚨🚨\n\n"
            f"SEATS JUST OPENED ON THE {trains} TRAIN: Granada → Málaga María Zambrano, {date}.\n\n"
            f"👉 BUY HERE (opens the train list for that day):\n{url}\n\n"
            f"Tap the {trains} train, pick a fare, and check out. "
            f"SEATS CAN DISAPPEAR FAST, BOOK IMMEDIATELY. ⏰\n\n"
            f"Backup link: https://www.renfe.com/es/es"
        )
    else:
        watched = watched or os.environ.get("TIMES", "13:25")
        subject = "🧪 TEST: Renfe monitor is working (no seats yet)"
        body = (
            f"🧪 This is a TEST. No seats yet, no action needed.\n\n"
            f"Watching the {watched} train Granada → Málaga on {date}. "
            f"A real alert will look like 🚨🚨 RENFE TICKETS AVAILABLE NOW 🚨🚨 and include this buy link:\n{url}"
        )
    return subject, body, url


def send_all(subject, body, url=None):
    """Send on every configured channel at once; returns True if any succeeded."""
    if url:
        os.environ["CLICK_URL"] = url

    def safe(send):
        try:
            return send(subject, body)
        except Exception as e:
            print(f"{send.__name__}: failed: {e}")
            return False

    with ThreadPoolExecutor() as pool:
        return any(pool.map(safe, (send_telegram, send_push, send_email)))


if __name__ == "__main__":
    if sys.argv[1:] == ["--alert"]:
        ok = send_all(*build_alert())
    else:
        ok = send_all(sys.argv[1], sys.argv[2])
    if not ok:
        sys.exit("no notification channel worked")
