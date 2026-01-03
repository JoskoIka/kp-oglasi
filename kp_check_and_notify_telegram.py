# kp_check_and_notify_telegram.py
import os, re, json, subprocess
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from time import sleep

# ------------- CONFIG -------------
URLS = [
    # originalni TV link sa filterom dimenzija
    "https://www.kupujemprodajem.com/tv-i-video/tv-lcd-plazma-led/pretraga?categoryId=1054&groupId=640&priceFrom=70&priceTo=180&currency=eur&condition=used&condition=as-new&condition=new&ignoreUserId=no&order=posted%20desc&page=1",

    # 1. Samsung S20 - samo nonrenewed
    "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s20&categoryId=23&groupId=75&priceFrom=65&priceTo=100&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&prev_keywords=s20&ignoreUserId=no&page=1",

    # 2. Samsung S21 - samo nonrenewed
    "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s21&categoryId=23&groupId=75&priceFrom=75&priceTo=125&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&prev_keywords=s21&ignoreUserId=no",

    # 3. Samsung S22 - samo nonrenewed
    "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s22&categoryId=23&groupId=75&priceFrom=80&priceTo=150&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&prev_keywords=s21&ignoreUserId=no",

    # 4. Tablet A9+ - nonrenewed + filter po naslovu i tekstu
    "https://www.kupujemprodajem.com/kompjuteri-laptop-i-tablet/tableti/pretraga?keywords=a9%2B&categoryId=1221&groupId=766&priceFrom=80&priceTo=180&currency=eur&condition=used&condition=as-new&condition=new&keywordsScope=description&hasPrice=yes&order=posted%20desc&prev_keywords=a9%2B&ignoreUserId=no&page=1",

    # 5. Laptop HP Ryzen - samo nonrenewed
    "https://www.kupujemprodajem.com/kompjuteri-laptop-i-tablet/laptopovi/pretraga?keywords=HP%20RYZEN&categoryId=1221&groupId=101&priceTo=350&currency=eur&condition=new&condition=as-new&condition=used&order=posted%20desc&prev_keywords=HP%20RYZEN&ignoreUserId=no"
]

# Tražene dimenzije / ključevi (samo za originalni TV link)
SIZES = ["40","42","43","46","47","48","49","50","55","60","4K","ultra hd","uhd","3840 x 2160"]
SIZES_LOWER = [s.lower() for s in SIZES]

# Filter keywords za A9+
A9_KEYWORDS = ["a9+", "a9 +", "a9plus", "a9 plus"]

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"

DATA_DIR = ".kp_data"
os.makedirs(DATA_DIR, exist_ok=True)

# Telegram
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ------------- HELPERS -------------
def slug_from_url(u):
    p = urlparse(u)
    slug = (p.path + "_" + (p.query or "")).replace('/', '_').replace('&','_').replace('=','_')
    slug = re.sub(r'[^0-9a-zA-Z_\-\.]', '', slug)
    return slug[:120]

def fetch_html(url):
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text

def parse_ads_from_html(html, base_url="https://www.kupujemprodajem.com"):
    soup = BeautifulSoup(html, "html.parser")
    ads = []
    sections = soup.select('section[class*="AdItem_adOuterHolder"]')
    for sec in sections:
        try:
            section_id = sec.get('id') or ""
            a = sec.select_one('a[href]')
            href = a['href'] if a else ""
            link = urljoin(base_url, href) if href else ""
            title_tag = sec.select_one('.AdItem_name__iOZvA')
            title = title_tag.get_text(strip=True) if title_tag else ""
            desc = ""
            info_holders = sec.select('.AdItem_adInfoHolder__Vljfb')
            if info_holders:
                for ih in info_holders:
                    pdesc = ih.find_all('p', recursive=False)
                    for p in pdesc:
                        if p.find('svg'):
                            continue
                        txt = p.get_text(strip=True)
                        if txt:
                            desc = txt
                            break
                    if desc:
                        break
            price_tag = sec.select_one('.AdItem_price__VZ_at')
            price = price_tag.get_text(" ", strip=True) if price_tag else ""
            posted_div = sec.select_one('.AdItem_postedStatus__4y6Ca')
            is_nonrenewed = False
            if posted_div:
                svg = posted_div.find('svg')
                if svg:
                    fill = svg.get('fill')
                    if fill and fill.strip().lower() == 'none':
                        is_nonrenewed = True
            ads.append({
                "id": section_id,
                "link": link,
                "title": title,
                "desc": desc,
                "price": price,
                "nonrenewed": is_nonrenewed
            })
        except Exception:
            continue
    return ads

def matches_size(text):
    t = (text or "").lower()
    for s in SIZES_LOWER:
        if s in t:
            return True
    if re.search(r'3840\s*[x×]\s*2160', t):
        return True
    return False

def send_telegram_messages(lines):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram token/ID not set in env.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    msgs = []
    cur = ""
    for line in lines:
        if len(cur) + len(line) + 1 > 3800:
            msgs.append(cur)
            cur = ""
        cur += line + "\n\n"
    if cur:
        msgs.append(cur)
    ok = True
    for m in msgs:
        resp = requests.post(url, data={"chat_id": CHAT_ID, "text": m})
        if resp.status_code != 200:
            print("Telegram respons:", resp.status_code, resp.text)
            ok = False
        else:
            print("Telegram notifikacija poslana.")
        sleep(0.2)
    return ok

def load_old_titles(fn):
    if os.path.exists(fn):
        try:
            with open(fn, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_old_titles(fn, titles):
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(list(titles), f, ensure_ascii=False, indent=2)

def safe_git_commit_push(file_paths, commit_message="Update neobnovljeni results [ci skip]"):
    try:
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        for p in file_paths:
            subprocess.run(["git", "add", p], check=False)
        subprocess.run(["git", "commit", "-m", commit_message], check=False)
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=False)
        res = subprocess.run(["git", "push", "origin", "main"], check=False)
        if res.returncode != 0:
            print("Git push failed (non-zero).")
    except Exception as e:
        print("Git commit/push error:", e)

def process_url(url):
    slug = slug_from_url(url)
    json_file = os.path.join(DATA_DIR, f"neobnovljeni_{slug}.json")
    txt_file = os.path.join(DATA_DIR, f"neobnovljeni_{slug}.txt")

    html = fetch_html(url)
    ads = parse_ads_from_html(html)
    ads_nonrenewed = [a for a in ads if a.get("nonrenewed")]

    # --- FILTER LOGIC ---
    if "pretraga?categoryId=1054" in url:
        # originalni TV link → filter by sizes
        filtered = []
        for a in ads_nonrenewed:
            combined = (a.get("title","") + " " + a.get("desc","")).lower()
            if matches_size(combined):
                filtered.append(a)
    elif "tableti/pretraga" in url:
        # A9+ tablet → filter nonrenewed + A9 keywords
        filtered = []
        for a in ads_nonrenewed:
            combined = (a.get("title","") + " " + a.get("desc","")).lower()
            if any(k in combined for k in A9_KEYWORDS):
                filtered.append(a)
    else:
        # ostali linkovi → samo nonrenewed
        filtered = ads_nonrenewed

    new_titles = [a.get("title","") for a in filtered]
    old_titles = load_old_titles(json_file)
    set_new = set(new_titles)
    set_old = set(old_titles)
    added = [t for t in new_titles if t not in set_old]

    lines_txt = []
    for a in filtered:
        lines_txt.append(a.get("title",""))
        lines_txt.append(a.get("desc",""))
        lines_txt.append(a.get("price",""))
        lines_txt.append(a.get("link",""))
        lines_txt.append("-" * 40)
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_txt))

    if added:
        msgs = []
        for t in added:
            for a in filtered:
                if a.get("title") == t:
                    block = f"{a.get('title')}\n{a.get('desc')}\n{a.get('price')}\n{a.get('link')}\n" + ("-"*30)
                    msgs.append(block)
                    break
        send_ok = send_telegram_messages(msgs)
        if send_ok:
            save_old_titles(json_file, new_titles)
            return True, len(added)
        else:
            print("Slanje notifikacije nije uspelo (pogledaj env varse i log).")
            return False, 0
    else:
        save_old_titles(json_file, new_titles)
        return True, 0

def main():
    total_added = 0
    overall_ok = True
    for url in URLS:
        try:
            ok, added = process_url(url)
            if not ok:
                overall_ok = False
            total_added += added
        except Exception as e:
            print("Error processing URL:", url, e)
            overall_ok = False

    try:
        all_files = [os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR)]
        safe_git_commit_push(all_files)
    except Exception as e:
        print("Git push problem:", e)

    print(f"Done. Total new ads added: {total_added}")
    if total_added == 0:
        print("Nema novih oglasa.")

if __name__ == "__main__":
    main()
