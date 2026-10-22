"""Check Renfe for seat availability on specific trains and report status.

Usage: python check_renfe.py [--date DD/MM/YYYY] [--times 13:25,18:29] [--json]
Exit code 0 = ran fine (see output), 2 = page could not be read.
"""
import argparse
import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

ORIGIN = ("GRANADA", "0071,05000,05000")
DEST = ("MÁLAGA MARÍA ZAMBRANO", "0071,54413,54413")

SUBMIT_JS = """([orig, dest, date]) => {
  const f = document.createElement('form');
  f.method = 'post';
  f.action = 'https://venta.renfe.com/vol/buscarTren.do?Idioma=es&Pais=ES';
  const fields = {
    tipoBusqueda: 'autocomplete', currenLocation: 'menuBusqueda', vengoderenfecom: 'SI',
    desOrigen: orig[0], desDestino: dest[0], cdgoOrigen: orig[1], cdgoDestino: dest[1],
    idiomaBusqueda: 'ES', FechaIdaSel: date, FechaVueltaSel: '', _fechaIdaVisual: date,
    _fechaVueltaVisual: '', minPriceDeparture: 'false', minPriceReturn: 'false',
    adultos_: '1', ninos_: '0', ninosMenores: '0', codPromocional: '', plazaH: 'false',
    sinEnlace: 'false', conMascota: 'false', conBicicleta: 'false', asistencia: 'false',
    franjaHoraI: '', franjaHoraV: '', Idioma: 'es', Pais: 'ES'
  };
  for (const [k, v] of Object.entries(fields)) {
    const i = document.createElement('input');
    i.type = 'hidden'; i.name = k; i.value = v; f.appendChild(i);
  }
  document.body.appendChild(f);
  f.submit();
}"""


def classify(text):
    if "Precio desde" in text or re.search(r"\d+,\d{2}\s*€", text):
        return "AVAILABLE"
    if "Solo plaza H" in text:
        return "ONLY_WHEELCHAIR_SEAT"
    if "Completo" in text:
        return "FULL"
    return "UNKNOWN"


def read_rows(browser, date):
    """Run one search in a fresh browser context and return each train row's text."""
    ctx = browser.new_context(
        locale="es-ES",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    )
    try:
        page = ctx.new_page()
        page.goto("https://www.renfe.com/es/es", wait_until="domcontentloaded", timeout=60000)
        with page.expect_navigation(timeout=60000):
            page.evaluate(SUBMIT_JS, [list(ORIGIN), list(DEST), date])
        page.wait_for_selector("div.selectedTren[id^='tren_']", timeout=60000)
        page.wait_for_timeout(1500)
        return page.eval_on_selector_all(
            "div.selectedTren[id^='tren_']", "els => els.map(e => e.innerText)"
        )
    finally:
        ctx.close()


def launch(p):
    return p.chromium.launch(headless=True, channel=os.environ.get("PW_CHANNEL") or None)


def fetch_trains(date, browser=None):
    if browser is None:
        with sync_playwright() as p:
            b = launch(p)
            try:
                return fetch_trains(date, b)
            finally:
                b.close()
    rows = read_rows(browser, date)

    trains = []
    for text in rows:
        times = re.findall(r"\b(\d{2}:\d{2}) h", text)
        if len(times) < 2:
            continue
        trains.append({"departs": times[0], "arrives": times[1], "status": classify(text)})
    return trains


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="30/10/2026")
    ap.add_argument("--times", default="13:25")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        trains = fetch_trains(args.date)
    except Exception as e:
        print(f"ERROR reading Renfe: {e}", file=sys.stderr)
        sys.exit(2)
    if not trains:
        print("ERROR: no trains parsed", file=sys.stderr)
        sys.exit(2)

    wanted = [t.strip() for t in args.times.split(",") if t.strip()]
    hits = [t for t in trains if t["departs"] in wanted and t["status"] == "AVAILABLE"]
    result = {"date": args.date, "trains": trains, "watched": wanted, "available": hits}
    if args.json:
        print(json.dumps(result))
    else:
        for t in trains:
            mark = "*" if t["departs"] in wanted else " "
            print(f"{mark} {t['departs']} -> {t['arrives']}  {t['status']}")
        print("AVAILABLE:", ", ".join(t["departs"] for t in hits) or "none")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"available={' '.join(t['departs'] for t in hits)}\n")


if __name__ == "__main__":
    main()
