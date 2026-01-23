# kp_check_and_notify_telegram_fixed_modified.py
# Modifikovana verzija originalne skripte.
# Dodat je filter koji za pretrage sa name_filter 'SIZES' i 'SIZES1'
# izbacuje oglase iz notifikacija ukoliko naslov/desc sadrže neželjene reči:
# akcija, fox, vox, vivax, 27", 27 inca, 27 inča, 32", 32 inca, 32 inča

import os, re, json, subprocess, time
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

# ============== CONFIG ==============

SEARCHES = [
    {"url": "https://www.kupujemprodajem.com/tv-i-video/tv-lcd-plazma-led/pretraga?categoryId=1054&groupId=640&priceFrom=70&priceTo=180&currency=eur&condition=used&condition=as-new&condition=new&ignoreUserId=no&order=posted%20desc&page=1", "name_filter": "SIZES"},
    {"url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s20&categoryId=23&groupId=75&priceFrom=65&priceTo=100&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&ignoreUserId=no&page=1", "name_filter": None},
    {"url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s21&categoryId=23&groupId=75&priceFrom=75&priceTo=125&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&ignoreUserId=no&page=1", "name_filter": None},
    {"url": "https://www.kupujemprodajem.com/mobilni-telefoni/samsung/pretraga?keywords=s22&categoryId=23&groupId=75&priceFrom=80&priceTo=150&currency=eur&condition=used&keywordsScope=description&hasPrice=no&order=posted%20desc&ignoreUserId=no&page=1", "name_filter": None},
    {"url": "https://www.kupujemprodajem.com/kompjuteri-laptop-i-tablet/tableti/pretraga?keywords=a9%2B&categoryId=1221&groupId=766&priceFrom=80&priceTo=180&currency=eur&condition=used&condition=as-new&condition=new&keywordsScope=description&hasPrice=yes&order=posted%20desc&ignoreUserId=no&page=1", "name_filter": "A9PLUS"},
    {"url": "https://www.kupujemprodajem.com/kompjuteri-laptop-i-tablet/laptopovi/pretraga?keywords=HP%20RYZEN&categoryId=1221&groupId=101&priceTo=350&currency=eur&condition=new&condition=as-new&condition=used&order=posted%20desc&ignoreUserId=no&page=1", "name_filter": None},
    # additional requested searches:
    {"url": "https://www.kupujemprodajem.com/tv-i-video/tv-lcd-plazma-led/pretraga?categoryId=1054&groupId=640&priceFrom=180&priceTo=260&currency=eur&condition=used&condition=as-new&condition=new&order=posted%20desc&ignoreUserId=no&page=1", "name_filter": "SIZES1"},
    {"url": "https://www.kupujemprodajem.com/pretraga?priceTo=400&order=posted%20desc&categoryId=1221&currency=eur&keywordsScope=description&priceFrom=300&keywords=m1&prev_keywords=m1&page=1", "name_filter": None},
]

# name-filter keyword lists
SIZES = ["40","42","43","46","47","48","49","50","55","60","4k","ultra hd","uhd","3840"]
SIZES1 = ["49","50","55","60","65","4k","ultra hd","uhd","3840"]
A9_KEYWORDS = ["a9+", "a9 +", "a9plus", "a9 plus"]

# Exclude keywords for the SIZES/SIZES1 searches (ads containing any of these in title/desc will NOT be notified)
EXCLUDE_SIZES = ["akcija","fox","vox","vivax","tesla",'27"','27 inca','27 inča','27 inca-','32"','32 inca','32 inča','32 inca-']

# realistic browser UA + headers to reduce server differences vs real browser
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "sr-RS,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": "https://www.kupujemprodajem.com/"
}

DATA_DIR = ".kp_data"
os.makedirs(DATA_DIR, exist_ok=True)

STATE_FILE = os.path.join(DATA_DIR, ".kp_state.json")
SEEN_FILE = os.path.join(DATA_DIR, "seen_base.txt")

# base capacity logic
SEEN_TRIM_THRESHOLD = 1000  # kada dođemo do ovoga ili više -> trim
SEEN_MAX = 1100
SEEN_KEEP = 300

GIT_RETRY = 3
GIT_RETRY_SLEEP = 2  # sec

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ============== HELPERS ==============

def log(*args):
    print("[kp]", *args)


def safe_slug(url):
    p = urlparse(url)
    return re.sub(r'[^0-9a-zA-Z_]', '_', (p.path + "?" + (p.query or "")))[:120]


def fetch_html(url):
    """
    Vraća HTML prve strane (ignorise JSON-LD itemlist).
    """
    headers = DEFAULT_HEADERS.copy()
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log("fetch error:", e)
        raise


def parse_ads_from_html(html):
    """
    Parsira oglase isključivo iz HTML prve strane.
    Vraća listu dictova sa poljima:
      link, title, desc, price, nonrenewed, date_ok, _static
    date_ok = True samo ako pise 'danas' ili 'juče'/'juce' u status bloku.
    nonrenewed = True ako je svg fill == "none" (kao u originalnoj verziji).
    """
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for sec in soup.select('section[class*="AdItem_adOuterHolder"]'):
        try:
            a = sec.select_one('a[href]')
            if not a:
                continue
            href = a.get('href','')
            link = urljoin("https://www.kupujemprodajem.com", href)
            static = extract_static_part(link)

            title_tag = sec.select_one('.AdItem_name__iOZvA')
            title = title_tag.get_text(strip=True) if title_tag else ""

            desc = ""
            info_holders = sec.select('.AdItem_adInfoHolder__Vljfb')
            if info_holders:
                for ih in info_holders:
                    for p in ih.find_all('p', recursive=False):
                        # preskoci svg (ikonice) u tekstu
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

            # status svg (za nonrenewed detekciju)
            posted_svg = sec.select_one('.AdItem_postedStatus__4y6Ca svg')
            nonrenewed = False
            if posted_svg:
                # original logic: svg.get('fill') == 'none' => nonrenewed
                fill = (posted_svg.get('fill') or "").strip().lower()
                if fill == "none":
                    nonrenewed = True

            # datum: 'danas' ili 'juče'/'juce'
            date_tag = sec.select_one('.AdItem_postedStatus__4y6Ca p')
            date_text = date_tag.get_text(strip=True).lower() if date_tag else ""
            date_ok = False
            if date_text:
                if "danas" in date_text:
                    date_ok = True
                elif "juče" in date_text or "juce" in date_text:
                    date_ok = True

            out.append({
                "link": link,
                "title": title,
                "desc": desc,
                "price": price,
                "nonrenewed": nonrenewed,
                "date_ok": date_ok,
                "_static": static
            })
        except Exception:
            continue
    return out


def extract_static_part(link):
    """
    Izvlači statični deo linka: segment pre 'oglas' + '/oglas/' + id
    npr: .../hp-.../oglas/187961167?...  ->  hp-.../oglas/187961167
    Ako ne može naći pattern, vraća path bez query kao fallback.
    """
    try:
        p = urlparse(link)
        path = p.path.strip('/')
        parts = path.split('/')
        # naći index 'oglas'
        if 'oglas' in parts:
            idx = parts.index('oglas')
            if idx >= 1 and idx + 1 < len(parts):
                slug = parts[idx-1]
                oid = parts[idx+1]
                return f"{slug}/oglas/{oid}"
        # fallback: uzmi zadnja 2 segmenta
        if len(parts) >= 2:
            return "/".join(parts[-2:])
        return path
    except Exception:
        return link.split('?',1)[0]


def name_match(ad, mode):
    """Proverava da li oglas prolazi name_filter.
    Za SIZES i SIZES1: prvo isključimo oglase koji sadrže EXCLUDE_SIZES.
    Nakon toga vraćamo True samo ako sadrže neku od odobrenih veličina/ključeva.
    """
    text = (ad.get("title","") + " " + ad.get("desc",""))
    text = text.lower()

    # ako je SIZES ili SIZES1 -> prvo proverimo exclude listu
    if mode in ("SIZES", "SIZES1"):
        for ex in EXCLUDE_SIZES:
            if ex in text:
                # nalazimo isključeni termin -> oglas se IGNORIŠE
                return False

    if mode == "SIZES":
        return any(s in text for s in SIZES)
    if mode == "SIZES1":
        return any(s in text for s in SIZES1)
    if mode == "A9PLUS":
        return any(k in text for k in A9_KEYWORDS)
    return True


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log("State load error:", e)
            return {}
    return {}


def write_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
                return lines  # newest at index 0 expected
        except Exception as e:
            log("Seen load error:", e)
            return []
    return []


def write_seen(seen_list):
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            # newest first
            for s in seen_list:
                f.write(s + "\n")
    except Exception as e:
        log("Seen write error:", e)


def git_pull():
    subprocess.run(["git","config","user.name","github-actions[bot]"], check=False)
    subprocess.run(["git","config","user.email","41898282+github-actions[bot]@users.noreply.github.com"], check=False)
    res = subprocess.run(["git","pull","--rebase","origin","main"], check=False)
    return res.returncode == 0


def git_commit_and_push(files_to_add):
    for attempt in range(1, GIT_RETRY+1):
        try:
            subprocess.run(["git","add"] + files_to_add, check=False)
            subprocess.run(["git","commit","-m","kp: update state/seen [ci skip]"], check=False)
            subprocess.run(["git","pull","--rebase","origin","main"], check=False)
            res = subprocess.run(["git","push","origin","main"], check=False)
            if res.returncode == 0:
                log("git push succeeded")
                return True
            else:
                log(f"git push attempt {attempt} failed (code {res.returncode}). Retrying...")
        except Exception as e:
            log("git push exception:", e)
        time.sleep(GIT_RETRY_SLEEP)
    log("git push failed after retries")
    return False


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        log("Telegram env missing.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text})
        if r.status_code == 200:
            return True
        else:
            log("Telegram API error:", r.status_code, r.text)
            return False
    except Exception as e:
        log("Telegram send exception:", e)
        return False

# ============== MAIN ==============

def main():
    log("Starting. Doing initial git pull to sync state...")
    git_pull()

    state = load_state()
    if not isinstance(state, dict):
        state = {}

    seen_list = load_seen()  # newest first
    seen_set = set(seen_list)

    all_new_ads = {}  # slug -> list of ad dicts (new only)
    new_state = {}    # slug -> current links (to be written)

    for cfg in SEARCHES:
        url = cfg["url"]
        mode = cfg.get("name_filter")
        slug = safe_slug(url)
        log("Processing", slug)
        try:
            # fetch html (ignore JSON-LD itemlist)
            html = fetch_html(url)
            # parse ads from HTML first page
            ads = parse_ads_from_html(html)

            # keep only nonrenewed, matching name filter, AND posted danas/juče
            ads = [a for a in ads if a.get("nonrenewed") and a.get("date_ok")]
            ads = [a for a in ads if name_match(a, mode)]

            current_links = [a["link"] for a in ads]

            # determine new by static part vs seen_set
            new_ads = []
            for a in ads:
                static = a.get("_static") or extract_static_part(a["link"])
                a["_static"] = static
                if static not in seen_set:
                    new_ads.append(a)

            all_new_ads[slug] = new_ads
            new_state[slug] = current_links
            log(f"Found {len(ads)} ads (nonrenewed+filter+date). New: {len(new_ads)}")
        except Exception as e:
            log("Error processing", slug, e)
            all_new_ads[slug] = []
            new_state[slug] = state.get(slug, [])

    # Update seen_list in memory by inserting statics of new ads (newest first),
    # but DO NOT send notifications yet. We'll write files and push; only after successful push we send.
    # We must keep insertion order: newest first. Also avoid duplicates.
    for slug, new_ads in all_new_ads.items():
        for a in new_ads:
            static = a.get("_static")
            if not static:
                continue
            # remove if already exists (shouldn't happen because checked earlier, but safe)
            if static in seen_list:
                seen_list.remove(static)
            # insert at front
            seen_list.insert(0, static)
            seen_set.add(static)

    # Trim seen_list if passes threshold (keep newest SEEN_KEEP)
    if len(seen_list) >= SEEN_TRIM_THRESHOLD or len(seen_list) > SEEN_MAX:
        log(f"Seen list length {len(seen_list)} >= threshold {SEEN_TRIM_THRESHOLD}/{SEEN_MAX}. Trimming to {SEEN_KEEP}.")
        seen_list = seen_list[:SEEN_KEEP]
        seen_set = set(seen_list)

    # Write new_state and seen_list to disk
    write_state(new_state)
    write_seen(seen_list)

    # Commit & push both STATE_FILE and SEEN_FILE. Only if push succeeds -> we will send notifications
    files_to_push = [STATE_FILE, SEEN_FILE]
    if not git_commit_and_push(files_to_push):
        log("Aborting notifications because git push failed. This avoids duplicate notifications.")
        return

    # push succeeded -> send notifications for each search that has new ads
    total_new = 0
    for cfg in SEARCHES:
        slug = safe_slug(cfg["url"])
        new_ads = all_new_ads.get(slug, [])
        if not new_ads:
            continue
        total_new += len(new_ads)
        # build single message for this link (numeration from 1)
        lines = []
        for i, a in enumerate(new_ads, 1):
            # each ad block: numbered, title, desc, price, link
            block = f"{i}. {a['title']}\n{a['desc']}\n{a['price']}\n{a['link']}"
            lines.append(block)
        message = "\n\n".join(lines).strip()
        ok = send_telegram(message)
        if ok:
            # send separator message exactly as requested
            send_telegram("NOVI OGLASI\n.\n.")
        else:
            log("Warning: telegram send failed for", slug)

    log("Done. Total new ads notified:", total_new)


if __name__ == "__main__":
    main()
