# kp_check_and_notify_telegram.py
import os, re, json, subprocess
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from time import sleep

# ------------- CONFIG -------------

URLS = [
    # ORIGINAL TV SEARCH (zadrzava SIZES filter)
    {
        "url": "https://www.kupujemprodajem.com/tv-i-video/tv-lcd-plazma-led/pretraga?categoryId=1054&groupId=640&priceFrom=70&priceTo=180&currency=eur&condition=used&condition=as-new&condition=new&ignoreUserId=no&order=posted%20desc&page=1",
        "mode": "tv"
    },

    # 1. S20
    {
        "url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s20&categoryId=23&groupId=75&priceFrom=65&priceTo=100&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&prev_keywords=s20&ignoreUserId=no&page=1",
        "mode": "nonrenewed_only"
    },

    # 2. S21
    {
        "url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s21&categoryId=23&groupId=75&priceFrom=75&priceTo=125&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&prev_keywords=s21&ignoreUserId=no",
        "mode": "nonrenewed_only"
    },

    # 3. S22
    {
        "url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s22&categoryId=23&groupId=75&priceFrom=80&priceTo=150&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&prev_keywords=s21&ignoreUserId=no",
        "mode": "nonrenewed_only"
    },

    # 4. A9+
    {
        "url": "https://www.kupujemprodajem.com/kompjuteri-laptop-i-tablet/tableti/pretraga?keywords=a9%2B&categoryId=1221&groupId=766&priceFrom=80&priceTo=180&currency=eur&condition=used&condition=as-new&condition=new&keywordsScope=description&hasPrice=yes&order=posted%20desc&prev_keywords=a9%2B&ignoreUserId=no&page=1",
        "mode": "a9plus"
    },

    # 5. HP Ryzen
    {
        "url": "https://www.kupujemprodajem.com/kompjuteri-laptop-i-tablet/laptopovi/pretraga?keywords=HP%20RYZEN&categoryId=1221&groupId=101&priceTo=350&currency=eur&condition=new&condition=as-new&condition=used&order=posted%20desc&prev_keywords=HP%20RYZEN&ignoreUserId=no",
        "mode": "nonrenewed_only"
    }
]

SIZES = ["40","42","43","46","47","48","49","50","55","60","4K","ultra hd","uhd","3840 x 2160"]
SIZES_LOWER = [s.lower() for s in SIZES]

A9_PATTERNS = ["a9+", "a9 +", "a9plus", "a9 plus"]

USER_AGENT = "Mozilla/5.0"

DATA_DIR = ".kp_data"
os.makedirs(DATA_DIR, exist_ok=True)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ------------- HELPERS -------------

def slug_from_url(u):
    p = urlparse(u)
    return re.sub(r'[^a-zA-Z0-9]', '_', p.path + p.query)[:120]

def fetch_html(url):
    return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30).text

def parse_ads(html):
    soup = BeautifulSoup(html, "html.parser")
    ads = []
    for sec in soup.select('section[class*="AdItem_adOuterHolder"]'):
        a = sec.select_one('a[href]')
        title_tag = sec.select_one('.AdItem_name__iOZvA')
        price_tag = sec.select_one('.AdItem_price__VZ_at')

        desc = ""
        for p in sec.select('.AdItem_adInfoHolder__Vljfb p'):
            if not p.find('svg'):
                desc = p.get_text(strip=True)
                break

        nonrenewed = False
        posted = sec.select_one('.AdItem_postedStatus__4y6Ca svg')
        if posted and posted.get("fill", "").lower() == "none":
            nonrenewed = True

        ads.append({
            "title": title_tag.get_text(strip=True) if title_tag else "",
            "desc": desc,
            "price": price_tag.get_text(strip=True) if price_tag else "",
            "link": urljoin("https://www.kupujemprodajem.com", a["href"]) if a else "",
            "nonrenewed": nonrenewed
        })
    return ads

def matches_tv(text):
    t = text.lower()
    if any(s in t for s in SIZES_LOWER):
        return True
    return bool(re.search(r'3840\s*[x×]\s*2160', t))

def matches_a9(text):
    t = text.lower()
    return any(p in t for p in A9_PATTERNS)

def send_telegram(ad_blocks):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for block in ad_blocks:
        requests.post(url, data={"chat_id": CHAT_ID, "text": block})
        sleep(0.2)
        requests.post(url, data={"chat_id": CHAT_ID, "text": "SLEDECA PORUKA"})
        sleep(0.2)

def load_old(fn):
    if os.path.exists(fn):
        with open(fn, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_old(fn, titles):
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(list(titles), f, ensure_ascii=False, indent=2)

# ------------- MAIN -------------

def process(entry):
    url = entry["url"]
    mode = entry["mode"]

    slug = slug_from_url(url)
    json_file = os.path.join(DATA_DIR, f"{slug}.json")

    ads = parse_ads(fetch_html(url))
    ads = [a for a in ads if a["nonrenewed"]]

    if mode == "tv":
        ads = [a for a in ads if matches_tv(a["title"] + " " + a["desc"])]
    elif mode == "a9plus":
        ads = [a for a in ads if matches_a9(a["title"] + " " + a["desc"])]

    old = load_old(json_file)
    new_ads = [a for a in ads if a["title"] not in old]

    if new_ads:
        blocks = []
        for i, a in enumerate(new_ads, 1):
            blocks.append(
                f"{i}.\n{a['title']}\n{a['desc']}\n{a['price']}\n{a['link']}\n" + "-"*30
            )
        send_telegram(blocks)

    save_old(json_file, {a["title"] for a in ads})

def main():
    for entry in URLS:
        try:
            process(entry)
        except Exception as e:
            print("Error:", e)

if __name__ == "__main__":
    main()
