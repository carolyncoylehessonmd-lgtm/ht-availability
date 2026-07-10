#!/usr/bin/env python3
"""Cost Plus Drugs availability checker — self-contained, lives at repo root.
Writes data.json (and history.csv) next to itself. No config files, no subfolders."""
import json, re, csv, datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent

PRODUCTS = [
    {"id": "patch-2x", "label": "Estradiol patch — twice-weekly", "items": [
        ["0.025 mg/day",  "https://www.costplusdrugs.com/medications/estradioltwiceweekly-0_025mg-patch8pack/"],
        ["0.0375 mg/day", "https://www.costplusdrugs.com/medications/estradioltwiceweekly-0_0375mg-patch8pack/"],
        ["0.05 mg/day",   "https://www.costplusdrugs.com/medications/estradioltwiceweekly-0_05mg-patch8pack/"],
        ["0.075 mg/day",  "https://www.costplusdrugs.com/medications/estradioltwiceweekly-0_075mg-patch8pack/"],
        ["0.1 mg/day (Dotti)", "https://www.costplusdrugs.com/medications/dotti-(estradiol-twice-weekly)-0_1-mg_24hr-box-of-8-patches-8/"],
    ]},
    {"id": "patch-1x", "label": "Estradiol patch — once-weekly (Climara)", "items": [
        ["0.025 mg/day",  "https://www.costplusdrugs.com/medications/climara-0_025mg-24hr-patch-weekly-4/"],
        ["0.0375 mg/day", "https://www.costplusdrugs.com/medications/climara-0_0375mg-24hr-patch-weekly-4/"],
        ["0.05 mg/day",   "https://www.costplusdrugs.com/medications/climara-0_05mg-24hr-patch-weekly-4/"],
        ["0.06 mg/day",   "https://www.costplusdrugs.com/medications/climara-0_06mg-24hr-patch-weekly-4/"],
        ["0.075 mg/day",  "https://www.costplusdrugs.com/medications/climara-0_075mg-24hr-patch-weekly-4/"],
        ["0.1 mg/day",    "https://www.costplusdrugs.com/medications/climara-0_1mg-24hr-patch-weekly-4/"],
    ]},
    {"id": "gel", "label": "Estradiol gel — sachet (Divigel)", "items": [
        ["0.25 mg / 0.25 g", "https://www.costplusdrugs.com/medications/estradiol-0_25mg-0_25g-gel-packet-divigel/"],
        ["0.5 mg / 0.5 g",   "https://www.costplusdrugs.com/medications/estradiol-0_5mg-0_5g-gel-packet-divigel/"],
        ["0.75 mg / 0.75 g", "https://www.costplusdrugs.com/medications/estradiol-0_75mg-0_75g-gel-packet-divigel/"],
        ["1 mg / 1 g",       "https://www.costplusdrugs.com/medications/estradiol-1mg-g-gel-packet-divigel/"],
        ["1.25 mg / 1.25 g", "https://www.costplusdrugs.com/medications/estradiol-1_25-mg_1_25gm-gel-37_5/"],
    ]},
    {"id": "omp", "label": "Oral micronized progesterone", "items": [
        ["100 mg", "https://www.costplusdrugs.com/medications/progesterone-100mg-capsule/"],
        ["200 mg", "https://www.costplusdrugs.com/medications/progesterone-200mg-capsule/"],
    ]},
]

PRICE = re.compile(r"\$\s?\d{1,4}(?:\.\d{2})?")
UNAVAIL = re.compile(r"out of stock|currently unavailable|not available|no longer|notify me|temporarily", re.I)
AVAIL = re.compile(r"add to cart|add to subscription|buy now|in stock", re.I)

def classify(text):
    if not text or "page not found" in text.lower():
        return "unavailable", None
    m = PRICE.search(text)
    price = m.group(0).replace(" ", "") if m else None
    if UNAVAIL.search(text):
        return "unavailable", price
    if AVAIL.search(text) or price:
        return "available", price
    return "unknown", price

def check(page, url):
    try:
        r = page.goto(url, wait_until="networkidle", timeout=45000)
    except Exception:
        try:
            r = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception:
            return {"url": url, "status": "unknown", "price": None}
    page.wait_for_timeout(2500)
    if r and r.status >= 400:
        return {"url": url, "status": "unavailable", "price": None}
    text = page.inner_text("body") if page.query_selector("body") else ""
    st, price = classify(text)
    return {"url": url, "status": st, "price": price}

def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent="Mozilla/5.0 (availability-tracker; educational)")
        for prod in PRODUCTS:
            entry = {"id": prod["id"], "label": prod["label"], "items": []}
            for strength, url in prod["items"]:
                r = check(page, url)
                r["strength"] = strength
                entry["items"].append(r)
            states = [i["status"] for i in entry["items"]]
            if "available" in states:
                entry["status"] = "available"
            elif states and all(s == "unavailable" for s in states):
                entry["status"] = "unavailable"
            else:
                entry["status"] = "unknown"
            results.append(entry)
        browser.close()

    data = {"generated_at": now, "source": "https://www.costplusdrugs.com", "products": results}
    (HERE / "data.json").write_text(json.dumps(data, indent=2))

    hist = HERE / "history.csv"
    new = not hist.exists()
    with hist.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["checked_at", "product", "strength", "status", "price", "url"])
        for prod in results:
            for i in prod["items"]:
                w.writerow([now, prod["id"], i["strength"], i["status"], i.get("price", ""), i["url"]])
    print("wrote data.json —", len(results), "products")

if __name__ == "__main__":
    main()
