# kp_check_and_notify_telegram.py
import requests
from bs4 import BeautifulSoup
import re, os, sys, time
from typing import List

# ---------------- CONFIG ----------------
URL = "https://www.kupujemprodajem.com/pretraga?categoryId=1054&groupId=640&priceFrom=70&priceTo=180&currency=eur&condition=used,as-new,new&ignoreUserId=no&order=posted+desc"
HEADERS = {"User-Agent": "Mozilla/5.0"}
OUT_FILE = "neobnovljeni_dijagonale_direct.txt"
SEPARATOR = "-" * 40

# tražene dijagonale
SIZES = ["40","42","43","46","47","48","49","50","55","60","4K","ultra hd","uhd","3840 x 2160"]
SIZE_RE = re.compile(r"(?<!\d)(" + "|".join(SIZES) + r")(?!\d)")

# Telegram iz env (u Actions staviš u Secrets)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# ----------------------------------------

def find_status_div(section):
    for div in section.find_all("div"):
        cls = div.get("class") or []
        for c in cls:
            if c.startswith("AdItem_postedStatus__"):
                return div
    return None

def extract_title(section):
    name_div = section.find(lambda tag: tag.name=="div" and tag.get("class") and any(c.startswith("AdItem_name__") for c in tag.get("class")))
    if name_div and name_div.get_text(strip=True):
        return name_div.get_text(strip=True)
    a = section.find("a", attrs={"aria-label": True, "href": True})
    if a:
        return (a.get("aria-label") or a.get_text(strip=True)).strip()
    a2 = section.find("a", href=True)
    if a2:
        return (a2.get_text(strip=True) or a2.get("aria-label") or "").strip()
    txt = (section.get_text(separator=" ", strip=True) or "")
    return txt.split("\n")[0].strip()

def extract_description(section):
    desc_holder = section.find(lambda tag: tag.name=="div" and tag.get("class") and any(c.startswith("AdItem_descriptionHolder__") for c in tag.get("class")))
    if not desc_holder:
        return ""
    p_tags = desc_holder.find_all("p")
    best = ""
    for p in p_tags:
        text = p.get_text(" ", strip=True)
        if len(text) <= 3:
            continue
        if len(text) > len(best):
            best = text
    return " ".join(best.split())

def extract_price(section):
    price_div = section.find(lambda tag: tag.name=="div" and tag.get("class") and any("AdItem_price__" in c or "AdItem_priceHolder__" in c or "AdItem_adPrice__" in c for c in tag.get("class")))
    if price_div:
        text = price_div.get_text(" ", strip=True)
        return " ".join(text.split())
    ph = section.find("div", class_=re.compile(r"AdItem_priceHolder__|AdItem_adPrice__|AdItem_price__"))
    if ph:
        return ph.get_text(" ", strip=True)
    return ""

def extract_link(section):
    a = section.find("a", href=True)
    if not a:
        return ""
    href = a.get("href") or ""
    return href if href.startswith("http") else "https://www.kupujemprodajem.com" + href

def parse_current():
    r = requests.get(URL, headers=HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    sections = soup.find_all("section", id=True)

    results = []
    for sec in sections:
        title = extract_title(sec)
        if not title:
            continue
        if not SIZE_RE.search(title):
            continue
        status_div = find_status_div(sec)
        if not status_div:
            continue
        shtml = str(status_div).lower()
        if 'fill="none"' not in shtml:
            continue
        desc = extract_description(sec)
        price = extract_price(sec)
        link = extract_link(sec)
        results.append({"title": title, "desc": desc, "price": price, "link": link})
    return results

def read_prev_titles_from_file(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read().strip()
    if not txt:
        return []
    blocks = [b.strip() for b in txt.split(SEPARATOR) if b.strip()]
    titles = []
    for b in blocks:
        lines = [l for l in b.splitlines() if l.strip()]
        if lines:
            titles.append(lines[0].strip())
    return titles

def write_out_file(path: str, items):
    with open(path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(it["title"] + "\n")
            f.write((it["desc"] or "") + "\n")
            f.write((it["price"] or "") + "\n")
            f.write(SEPARATOR + "\n")

def send_telegram(title: str, link: str, desc: str) -> bool:
    token = TELEGRAM_BOT_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or not chat_id:
        print("Telegram not configured via env vars (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID). Skipping notification.")
        return False
    msg = f"🆕 Novi KP oglas:\n{title}\n{desc}\n{link}"
    send_url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        res = requests.post(send_url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        if res.status_code == 200:
            print("Telegram notifikacija poslana.")
            return True
        else:
            print("Telegram respons:", res.status_code, res.text)
            return False
    except Exception as e:
        print("Greška pri slanju Telegram poruke:", e)
        return False

def main():
    print("Pokrećem fetch i parsing...")
    try:
        curr = parse_current()
    except Exception as e:
        print("Greška pri fetch/parsing:", e)
        sys.exit(1)

    print(f"Pronađeno {len(curr)} oglasa (neobnovljeni + dijagonale).")

    # prethodno čitamo naslove iz istog OUT_FILE koji se čuva u repo (Actions će commitovati)
    prev_titles = read_prev_titles_from_file(OUT_FILE)
    prev_empty = (len(prev_titles) == 0)
    curr_titles = [c["title"] for c in curr]

    notify = False
    notify_payload = None

    # Logic:
    if not os.path.exists(OUT_FILE):
        print("Prethodni fajl ne postoji -> inicijalni run, samo zapisujem, bez notifikacije.")
        write_out_file(OUT_FILE, curr)
        return

    if prev_empty and len(curr_titles) > 0:
        notify = True
        notify_payload = curr[0]
    elif len(curr_titles) == 0:
        print("Trenutna lista prazna -> ne saljem notifikaciju, samo prepisujem fajl.")
        write_out_file(OUT_FILE, curr)
        return
    else:
        prev_first = prev_titles[0] if prev_titles else None
        curr_first = curr_titles[0] if curr_titles else None
        if curr_first != prev_first:
            if curr_first in prev_titles:
                print("Prvi naslov se promenio, ali se nalazi među starim naslovima -> promena pozicije, NIJE novi oglas.")
            else:
                notify = True
                notify_payload = curr[0]
        else:
            print("Prvi naslov isti -> nema notifikacije.")

    # UVIJEK prepisujemo izlazni fajl (persist)
    write_out_file(OUT_FILE, curr)

    if notify and notify_payload:
        print("Detektovan NOVI oglas; saljem notifikaciju.")
        sent = send_telegram(notify_payload["title"], notify_payload["link"], notify_payload["desc"])
        if not sent:
            print("Slanje notifikacije nije uspelo (pogledaj env varse i log).")
    else:
        print("Nema notifikacije za poslati.")

if __name__ == "__main__":
    main()

