#!/usr/bin/env python3
"""Cost Plus Drugs availability checker (stealth) — self-contained, lives at repo root.
Writes data.json (+ history.csv) next to itself. No config files, no subfolders."""
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

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
PRICE = re.compile(r"\$\s?\d{1,4}(?:\.\d{2})?")
UNAVAIL = re.compile(r"currently unavailable|out of stock|sold out|no longer available|not available for", re.I)
AVAIL = re.compile(r"add to cart|add to subscription|buy now|in stock", re.I)

def parse_jsonld(page):
    for s in page.query_selector_all('script[type="application/ld+json"]'):
        raw = s.text_content() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            offers = node.get("offers")
            if offers:
                offer = offers[0] if isinstance(offers, list) else offers
                if isinstance(offer, dict):
                    return offer.get("price"), str(offer.get("availability") or "").lower()
    return None, None

def check(page, url):
    try:
        r = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        return {"url": url, "status": "unknown", "price": None, "len": 0}
    try:
        page.wait_for_function("() => (document.body ? document.body.innerText : '').includes('$')", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    if r and r.status >= 400:
        return {"url": url, "status": "unavailable", "price": None, "len": 0}

    price_ld, avail_ld = parse_jsonld(page)
    if avail_ld:
        pr = ("$" + str(price_ld)) if price_ld else None
        if "instock" in avail_ld or "preorder" in avail_ld or "limited" in avail_ld:
            return {"url": url, "status": "available", "price": pr, "len": -1}
        if "outofstock" in avail_ld or "soldout" in avail_ld or "discontinued" in avail_ld:
            return {"url": url, "status": "unavailable", "price": pr, "len": -1}

    text = page.inner_text("body") if page.query_selector("body") else ""
    n = len(text.strip())
    if n < 200:                        # got a blank / blocked page — don't claim "not listed"
        return {"url": url, "status": "unknown", "price": None, "len": n}
    m = PRICE.search(text)
    price = m.group(0).replace(" ", "") if m else None
    if UNAVAIL.search(text):
        return {"url": url, "status": "unavailable", "price": price, "len": n}
    if price or AVAIL.search(text):
        return {"url": url, "status": "available", "price": price, "len": n}
    return {"url": url, "status": "unknown", "price": price, "len": n}

def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    results, sample_len = [], None
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900},
                                      locale="en-US", timezone_id="America/Chicago",
                                      extra_http_headers={"Accept-Language": "en-US,en;q=0.9"})
        context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = context.new_page()
        for prod in PRODUCTS:
            entry = {"id": prod["id"], "label": prod["label"], "items": []}
            for strength, url in prod["items"]:
                r = check(page, url)
                if sample_len is None:
                    sample_len = r.pop("len", None)
                else:
                    r.pop("len", None)
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

    data = {"generated_at": now, "source": "https://www.costplusdrugs.com",
            "_debug": {"first_page_text_length": sample_len}, "products": results}
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
    print("wrote data.json — first_page_text_length =", sample_len)

if __name__ == "__main__":
    main()
