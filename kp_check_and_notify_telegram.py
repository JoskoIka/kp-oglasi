# kp_check_and_notify_telegram.py
import os, re, json, subprocess
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from time import sleep

# ================= CONFIG =================

SEARCHES = [
    {
        "url": "https://www.kupujemprodajem.com/tv-i-video/tv-lcd-plazma-led/pretraga?categoryId=1054&groupId=640&priceFrom=70&priceTo=180&currency=eur&condition=used&condition=as-new&condition=new&ignoreUserId=no&order=posted%20desc&page=1",
        "name_filter": "SIZES"
    },
    {
        "url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s20&categoryId=23&groupId=75&priceFrom=65&priceTo=100&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&ignoreUserId=no&page=1",
        "name_filter": None
    },
    {
        "url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s21&categoryId=23&groupId=75&priceFrom=75&priceTo=125&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&ignoreUserId=no",
        "name_filter": None
    },
    {
        "url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s22&categoryId=23&groupId=75&priceFrom=80&priceTo=150&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&ignoreUserId=no",
        "name_filter": None
    },
    {
        "url": "https://www.kupujemprodajem.com/kompjuteri-laptop-i-tablet/tableti/pretraga?keywords=a9%2B&categoryId=1221&groupId=766&priceFrom=80&priceTo=180&currency=eur&condition=used&condition=as-new&condition=new&keywordsScope=description&hasPrice=yes&order=posted%20desc&ignoreUserId=no&page=1",
        "name_filter": "A9PLUS"
    },
    {
        "url": "https://www.kupujemprodajem.com/kompjuteri-laptop-i-tablet/laptopovi/pretraga?keywords=HP%20RYZEN&categoryId=1221&groupId=101&priceTo=350&currency=eur&condition=new&condition=as-new&condition=used&order=posted%20desc&ignoreUserId=no",
        "name_filter": None
    }
]

SIZES = ["40","42","43","46","47","48","49","50","55","60","4k","ultra hd","uhd","3840"]
A9_KEYWORDS = ["a9+", "a9 +", "a9plus", "a9 plus"]

USER_AGENT = "Mozilla/5.0"

DATA_DIR = ".kp_data"
os.makedirs(DATA_DIR, exist_ok=True)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ================= HELPERS =================

def slug_from_url(u):
    p = urlparse(u)
    return re.sub(r'[^a-zA-Z0-9]', '_', p.path + p.query)[:120]

def fetch_html(url):
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.text

def parse_ads(html):
    soup = BeautifulSoup(html, "html.parser")
    ads = []
    for sec in soup.select('section[class*="AdItem_adOuterHolder"]'):
        a = sec.select_one('a[href]')
        title = sec.select_one('.AdItem_name__iOZvA')
        desc = sec.select_one('.AdItem_adInfoHolder__Vljfb p:not(:has(svg))')
        price = sec.select_one('.AdItem_price__VZ_at')
        posted = sec.select_one('.AdItem_postedStatus__4y6Ca svg')

        nonrenewed = posted and posted.get("fill","").lower() == "none"

        ads.append({
            "title": title.get_text(strip=True) if title else "",
            "desc": desc.get_text(strip=True) if desc else "",
            "price": price.get_text(strip=True) if price else "",
            "link": urljoin("https://www.kupujemprodajem.com", a["href"]) if a else "",
            "nonrenewed": nonrenewed
        })
    return ads

def name_match(ad, mode):
    text = (ad["title"] + " " + ad["desc"]).lower()
    if mode == "SIZES":
        return any(s in text for s in SIZES)
    if mode == "A9PLUS":
        return any(k in text for k in A9_KEYWORDS)
    return True

def send_message(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text}
    )
    sleep(0.3)

# ================= MAIN LOGIC =================

def process_search(cfg):
    slug = slug_from_url(cfg["url"])
    state_file = f"{DATA_DIR}/{slug}.json"

    old = set(json.load(open(state_file))) if os.path.exists(state_file) else set()

    ads = parse_ads(fetch_html(cfg["url"]))
    ads = [a for a in ads if a["nonrenewed"] and name_match(a, cfg["name_filter"])]

    new_titles = [a["title"] for a in ads]
    added = [a for a in ads if a["title"] not in old]

    if added:
        msg = ""
        for i, a in enumerate(added, 1):
            msg += f"{i}. {a['title']}\n{a['desc']}\n{a['price']}\n{a['link']}\n\n"
        send_message(msg.strip())
        send_message("NOVI OGLASI\n\n")

    json.dump(new_titles, open(state_file,"w"), ensure_ascii=False, indent=2)
    return len(added)

def git_push():
    subprocess.run(["git","add",DATA_DIR])
    subprocess.run(["git","commit","-m","KP update [ci skip]"], check=False)
    subprocess.run(["git","pull","--rebase","origin","main"], check=False)
    subprocess.run(["git","push","origin","main"], check=False)

def main():
    total = 0
    for cfg in SEARCHES:
        total += process_search(cfg)
    git_push()
    print("Done. New ads:", total)

if __name__ == "__main__":
    main()
