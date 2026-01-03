# kp_check_and_notify_telegram.py
import os, re, json, sys, subprocess
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from time import sleep

# ------------- CONFIG -------------
URLS = [
    "https://www.kupujemprodajem.com/tv-i-video/tv-lcd-plazma-led/pretraga?categoryId=1054&groupId=640&priceFrom=70&priceTo=180&currency=eur&condition=used&condition=as-new&condition=new&ignoreUserId=no&order=posted%20desc&page=1"
    # dodaj ostale search linkove ovde
]

# Tražene dimenzije / ključevi (user-provided)
SIZES = ["40","42","43","46","47","48","49","50","55","60","4K","ultra hd","uhd","3840 x 2160"]
# Normalize for search
SIZES_LOWER = [s.lower() for s in SIZES]

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"

# Folders and file name templates
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
    # select sections with outer holder (class name contains AdItem_adOuterHolder__)
    sections = soup.select('section[class*="AdItem_adOuterHolder"]')
    for sec in sections:
        try:
            # id or link
            section_id = sec.get('id') or ""
            a = sec.select_one('a[href]')
            href = a['href'] if a else ""
            link = urljoin(base_url, href) if href else ""
            title_tag = sec.select_one('.AdItem_name__iOZvA')
            title = title_tag.get_text(strip=True) if title_tag else ""
            # short description: the first <p> under AdItem_adInfoHolder__Vljfb (excluding location p)
            desc = ""
            info_holders = sec.select('.AdItem_adInfoHolder__Vljfb')
            if info_holders:
                # in sample, first info holder contains location p, second p contains description
                # find first <p> inside the first info holder that is not the location (heuristic)
                for ih in info_holders:
                    pdesc = ih.find_all('p', recursive=False)
                    # pdesc list may contain location p then description p
                    for p in pdesc:
                        # skip if p contains svg (location)
                        if p.find('svg'):
                            continue
                        txt = p.get_text(strip=True)
                        if txt:
                            desc = txt
                            break
                    if desc:
                        break
            # price
            price_tag = sec.select_one('.AdItem_price__VZ_at')
            price = price_tag.get_text(" ", strip=True) if price_tag else ""
            # posted status svg fill check
            posted_div = sec.select_one('.AdItem_postedStatus__4y6Ca')
            is_nonrenewed = False
            if posted_div:
                svg = posted_div.find('svg')
                if svg:
                    fill = svg.get('fill')
                    # if fill == 'none' -> non-renewed (fresh), else renewed
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
    # additional special case for pixel resolution variants (3840x2160 with/without spaces)
    if re.search(r'3840\s*[x×]\s*2160', t):
        return True
    return False

def send_telegram_messages(lines):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram token/ID not set in env.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    # chunk into messages < 3800 chars to be safe (telegram limit ~4096)
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

# ------------- MAIN -------------
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
        # pull rebase to avoid rejected push
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

    # filter only nonrenewed
    ads_nonrenewed = [a for a in ads if a.get("nonrenewed")]
    # filter by sizes present either in title or desc
    filtered = []
    for a in ads_nonrenewed:
        combined = (a.get("title","") + " " + a.get("desc","")).lower()
        if matches_size(combined):
            filtered.append(a)

    # build title lists for comparison
    new_titles = [a.get("title","") for a in filtered]
    old_titles = load_old_titles(json_file)

    set_new = set(new_titles)
    set_old = set(old_titles)

    added = [t for t in new_titles if t not in set_old]

    # prepare human readable txt (overwrite)
    lines_txt = []
    for a in filtered:
        lines_txt.append(a.get("title",""))
        lines_txt.append(a.get("desc",""))
        lines_txt.append(a.get("price",""))
        lines_txt.append(a.get("link",""))
        lines_txt.append("-" * 40)
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_txt))

    # notifications
    if added:
        # prepare message lines for telegram
        msgs = []
        for t in added:
            # find ad object
            for a in filtered:
                if a.get("title") == t:
                    block = f"{a.get('title')}\n{a.get('desc')}\n{a.get('price')}\n{a.get('link')}\n" + ("-"*30)
                    msgs.append(block)
                    break
        send_ok = send_telegram_messages(msgs)
        if send_ok:
            # only after successful send, save new titles
            save_old_titles(json_file, new_titles)
            return True, len(added)
        else:
            print("Slanje notifikacije nije uspelo (pogledaj env varse i log).")
            return False, 0
    else:
        # nothing added - update stored list anyway (keeps it fresh)
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

    # commit/push all data files
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
