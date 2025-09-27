#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, json, time, threading, hashlib, hmac
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl

import requests
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto
)

# =========================
# CONFIG DI BASE (persistenza su settings.json)
# =========================
HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "settings.json")

DEFAULT_SETTINGS = {
    "TELEGRAM_TOKEN": "",         # <-- inserito al deploy (Render/Termux) come env o file
    "ADMIN_ID": 0,                # si imposta da /setadmin (prende l'ID di chi lancia il comando)
    "TARGET_GROUP_ID": 0,         # dove pubblicare con il bottone "Pubblica"
    "PAAPI_ENABLED": True,
    "PAAPI_PARTNER_TAG": "",      # tag affiliato (es. "cianfrusagliegruppo-21")
    "PAAPI_ACCESS_KEY": "",
    "PAAPI_SECRET_KEY": "",
    "PAAPI_REGION": "eu-west-1",
    "PAAPI_HOST": "webservices.amazon.it",
    "MIN_DISCOUNT_PCT_DEFAULT": 10,   # sconto minimo di default per /cerca
    "USER_SEARCH_MAX_RESULTS": 5      # quanti prodotti mostrare al massimo
}

def load_settings():
    if not os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SETTINGS, f, ensure_ascii=False, indent=2)
        return DEFAULT_SETTINGS.copy()
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            data = {}
    # merge con default
    out = DEFAULT_SETTINGS.copy()
    out.update(data or {})
    return out

def save_settings(d):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

S = load_settings()

# Permette di usare il token anche da env (se non presente nel file)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", S.get("TELEGRAM_TOKEN","")).strip()
if not TELEGRAM_TOKEN:
    raise SystemExit("⚠️ TELEGRAM_TOKEN mancante. Mettilo in settings.json o come variabile d'ambiente.")

ADMIN_ID = int(S.get("ADMIN_ID", 0) or 0)

# =========================
# TELEGRAM BOT
# =========================
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
def log(msg): print(datetime.now().strftime("[%d/%m/%Y %H:%M]"), msg, flush=True)

# =========================
# PA-API 5 (Amazon)
# =========================
PAAPI_HOST        = S.get("PAAPI_HOST", "webservices.amazon.it")
PAAPI_ENDPOINT    = f"https://{PAAPI_HOST}/paapi5"
PAAPI_ACCESS_KEY  = S.get("PAAPI_ACCESS_KEY","").strip()
PAAPI_SECRET_KEY  = S.get("PAAPI_SECRET_KEY","").strip()
PAAPI_PARTNER_TAG = S.get("PAAPI_PARTNER_TAG","").strip()
PAAPI_REGION      = S.get("PAAPI_REGION","eu-west-1")
PAAPI_ENABLED     = bool(S.get("PAAPI_ENABLED", True))

PAAPI_MIN_INTERVAL_SEC = 1.5
PAAPI_MAX_RETRIES = 3
_paapi_last_call_ts = 0.0

def _paapi_sigv4_headers(target, payload):
    # Firma AWS SigV4
    import datetime as dt
    from hashlib import sha256

    t = dt.datetime.utcnow()
    amzdate = t.strftime("%Y%m%dT%H%M%SZ")
    datestamp = t.strftime("%Y%m%d")
    service = "ProductAdvertisingAPI"
    host = PAAPI_HOST
    region = PAAPI_REGION
    method = "POST"
    uri = "/paapi5/" + target.split(".")[-1].lower()
    query = ""
    headers = (
        "content-encoding:amz-1.0\n"
        "content-type:application/json; charset=utf-8\n"
        f"host:{host}\n"
        f"x-amz-date:{amzdate}\n"
        f"x-amz-target:{target}\n"
    )
    signed_headers = "content-encoding;content-type;host;x-amz-date;x-amz-target"
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = f"{method}\n{uri}\n{query}\n{headers}\n{signed_headers}\n{payload_hash}"
    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = f"{algorithm}\n{amzdate}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"

    def sign(key, msg): return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
    kDate = sign(("AWS4" + PAAPI_SECRET_KEY).encode("utf-8"), datestamp)
    kRegion = sign(kDate, region)
    kService = sign(kRegion, service)
    kSigning = sign(kService, "aws4_request")
    signature = hmac.new(kSigning, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    headers_out = {
        "Content-Encoding": "amz-1.0",
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-Amz-Date": amzdate,
        "X-Amz-Target": target,
        "Authorization": f"{algorithm} Credential={PAAPI_ACCESS_KEY}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
    }
    return headers_out

def _paapi_post(target, body):
    global _paapi_last_call_ts
    import json as js
    if not (PAAPI_ENABLED and PAAPI_ACCESS_KEY and PAAPI_SECRET_KEY and PAAPI_PARTNER_TAG):
        return None
    payload = js.dumps(body)
    headers = _paapi_sigv4_headers(target, payload)
    url = f"{PAAPI_ENDPOINT}/{target.split('.')[-1].lower()}"
    last_exc = None
    for attempt in range(PAAPI_MAX_RETRIES+1):
        now = time.time()
        delay = PAAPI_MIN_INTERVAL_SEC - (now - _paapi_last_call_ts)
        if delay > 0:
            time.sleep(delay)
        try:
            r = requests.post(url, data=payload.encode("utf-8"), headers=headers, timeout=12)
            if r.status_code in (429,500,502,503,504):
                log(f"[PAAPI] HTTP {r.status_code}: {r.text[:120]}")
                time.sleep((2**attempt)*1.4)
                last_exc = requests.HTTPError(f"{r.status_code} {r.text}")
                continue
            r.raise_for_status()
            _paapi_last_call_ts = time.time()
            return r.json()
        except Exception as e:
            last_exc = e
            break
    if last_exc:
        log(f"[PAAPI] errore: {last_exc}")
    return None

def _parse_item(it, partner_tag):
    asin = it.get("ASIN")
    title = (it.get("ItemInfo",{}).get("Title",{}) or {}).get("DisplayValue") or "Articolo Amazon"
    images = []
    try:
        imgs = it.get("Images",{}).get("Primary",{})
        for size_key in ("Large","Medium","Small"):
            url = (imgs.get(size_key) or {}).get("URL")
            if url:
                images.append(url)
                break
    except: pass

    listing = (it.get("Offers",{}) or {}).get("Listings",[{}])[0]
    price = listing.get("Price",{}).get("Amount")
    savings = listing.get("Price",{}).get("Savings",{})
    pct = savings.get("Percentage")  # es. 15
    pct_bot = -int(pct or 0)         # es. -15 (coerente con vecchia firma)

    old_price = None
    if price and pct:
        try:
            old_price = round(price/(1-(pct/100)),2)
        except: pass

    # URL affiliato canonico
    url = f"https://www.amazon.it/dp/{asin}"
    if partner_tag:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}tag={partner_tag}"

    return {
        "asin": asin,
        "title": title,
        "img": images[0] if images else None,
        "price": price,
        "old_price": old_price,
        "pct": pct_bot,
        "url": url
    }

def paapi_search(keywords, max_items=5):
    body = {
        "Keywords": keywords,
        "SearchIndex": "All",
        "ItemPage": 1,
        "PartnerTag": PAAPI_PARTNER_TAG,
        "PartnerType": "Associates",
        "Marketplace": "www.amazon.it",
        "Resources": [
            "Images.Primary.Small",
            "Images.Primary.Medium",
            "Images.Primary.Large",
            "ItemInfo.Title",
            "Offers.Listings.Price"
        ]
    }
    data = _paapi_post("com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems", body)
    items = (data or {}).get("SearchResult",{}).get("Items") or []
    return [_parse_item(it, PAAPI_PARTNER_TAG) for it in items if it]

def paapi_get_item(asin):
    body = {
        "ItemIds": [asin],
        "PartnerTag": PAAPI_PARTNER_TAG,
        "PartnerType": "Associates",
        "Marketplace": "www.amazon.it",
        "Resources": [
            "Images.Primary.Small",
            "Images.Primary.Medium",
            "Images.Primary.Large",
            "ItemInfo.Title",
            "Offers.Listings.Price"
        ]
    }
    data = _paapi_post("com.amazon.paapi5.v1.ProductAdvertisingAPIv1.GetItems", body)
    items = (data or {}).get("ItemsResult",{}).get("Items") or []
    if not items: return None
    return _parse_item(items[0], PAAPI_PARTNER_TAG)

# =========================
# AMZ URL UTILS (shortlink, estrazione ASIN)
# =========================
AMZ_HOSTS = (
    "amazon.", "amzn.to", "amzn.eu", "amzn.asia", "amzn.in", "amzn.com",
    "amzn.co", "amzn.de", "amzn.it", "amzn.fr", "amzn.es", "amzn.co.uk"
)
ASIN_RE = re.compile(r"\b([A-Z0-9]{10})\b")
HEADERS_WEB = {
    "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

def is_amazon_like(url: str) -> bool:
    try:
        u = url.lower()
        return any(h in u for h in AMZ_HOSTS)
    except:
        return False

def expand_url(url: str, timeout=8) -> str:
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout, headers=HEADERS_WEB)
        if r.url and is_amazon_like(r.url):
            return r.url
    except Exception:
        pass
    try:
        r = requests.get(url, allow_redirects=True, timeout=timeout, headers=HEADERS_WEB)
        if r.url and is_amazon_like(r.url):
            return r.url
    except Exception:
        pass
    return url

def extract_asin_from_url(url: str):
    if not url:
        return None
    u = url.split("?")[0]
    parts = u.strip("/").split("/")
    for i, p in enumerate(parts):
        if p.lower() == "dp" and i+1 < len(parts):
            cand = parts[i+1].upper()
            if ASIN_RE.fullmatch(cand):
                return cand
    for i in range(len(parts)-2):
        if parts[i].lower()=="gp" and parts[i+1].lower()=="product":
            cand = parts[i+2].upper()
            if ASIN_RE.fullmatch(cand):
                return cand
    if "asin=" in url.lower():
        m = re.search(r"[?&]asin=([A-Za-z0-9]{10})", url, re.I)
        if m:
            return m.group(1).upper()
    m = ASIN_RE.search(url.upper())
    if m:
        return m.group(1)
    return None

def extract_asin_smart(url: str):
    final_url = expand_url(url)
    asin = extract_asin_from_url(final_url)
    if asin:
        return asin, final_url
    # fallback: prova a leggere HTML per data-asin o canonical
    try:
        r = requests.get(final_url, headers=HEADERS_WEB, timeout=10)
        html = r.text or ""
        m = re.search(r'data-asin="([A-Z0-9]{10})"', html, re.I)
        if not m:
            m = re.search(r"/dp/([A-Z0-9]{10})", html, re.I)
        if not m:
            m2 = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html, re.I)
            if not m2:
                m2 = re.search(r'<meta[^>]+property="og:url"[^>]+content="([^"]+)"', html, re.I)
            if m2:
                maybe = m2.group(1)
                asin = extract_asin_from_url(maybe)
                return asin, maybe
        if m:
            asin = m.group(1).upper()
            return asin, final_url
    except Exception:
        pass
    return None, final_url

# =========================
# PARSING / FORMAT
# =========================
EURO_RE = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*€")
PCT_RE  = re.compile(r"(\d{1,3})\s*%")

def parse_price_max_and_pct(text):
    """Ritorna (price_max_eur, pct_min) o (None, None) se non trovati"""
    price_max = None
    pct_min = None
    m1 = EURO_RE.search(text.replace(",", "."))
    if m1:
        try:
            price_max = float(m1.group(1).replace(",", "."))
        except: pass
    m2 = PCT_RE.search(text)
    if m2:
        try:
            pct_min = int(m2.group(1))
        except: pass
    return price_max, pct_min

def fmt_eur(v):
    try:
        return f"{v:,.2f}€".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return f"{v}€"

def build_multi_text(products, disclaimer_url=None):
    """Formato richiesto con riga vuota tra prodotti"""
    blocks = []
    for p in products:
        title = p["title"]
        url = p["url"]
        price = p.get("price")
        old  = p.get("old_price")
        if price and old:
            line = f"📍 {title}\n{fmt_eur(price)} invece di {fmt_eur(old)}\n🛒 {url}"
        elif price:
            line = f"📍 {title}\n📉 In offerta a {fmt_eur(price)}\n🛒 {url}"
        else:
            line = f"📍 {title}\n🛒 {url}"
        blocks.append(line)
    out = "\n\n".join(blocks)
    if disclaimer_url:
        out += f"\n\n#Adv ℹ️ Info prezzi visualizzati - {disclaimer_url}"
    return out

def order_and_filter(items, pct_min=10, price_max=None, limit=5):
    # Filtra per sconto minimo e (opzionale) prezzo max, ordina per sconto desc poi prezzo asc
    out = []
    for it in items:
        pct = it.get("pct")
        if pct is None:
            continue
        # pct è negativo (-15). Confronto su valore assoluto:
        if abs(pct) < pct_min:
            continue
        if price_max is not None and it.get("price") and it["price"] > price_max:
            continue
        out.append(it)
    out.sort(key=lambda x: (abs(x.get("pct") or 0), -(x.get("price") or 0)*-1), reverse=True)
    return out[:limit]

# =========================
# STATO ANTEPRIMA / FIX
# =========================
# preview_state[user_id] = {
#   "text": testo_formattato,
#   "photos": [url_img1, url_img2, ...],
#   "group_id": int (target),
# }
preview_state = {}

# =========================
# HELPERS
# =========================
def is_admin(user_id: int) -> bool:
    return ADMIN_ID and user_id == ADMIN_ID

def ensure_private(m):
    if m.chat.type != "private":
        bot.reply_to(m, "Usa questo comando **in privato** con il bot.", parse_mode="Markdown")
        return False
    return True

def make_keyboard_preview():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📣 Pubblica nel gruppo", callback_data="pubblica"),
        InlineKeyboardButton("🛠️ Fix prezzo", callback_data="fix")
    )
    return kb

def send_media_group(chat_id, photos):
    if not photos:
        return
    media = []
    for i, url in enumerate(photos[:10]):  # max 10
        try:
            media.append(InputMediaPhoto(url))
        except:
            continue
    if media:
        bot.send_media_group(chat_id, media)

# =========================
# COMANDI BOT
# =========================
@bot.message_handler(commands=["start","help"])
def start_help(m):
    txt = (
        "Ciao! 👋\n"
        "Comandi disponibili:\n\n"
        "• /cerca <testo> [200€] [20%] – Cerca su Amazon (sconto min di default).\n"
        "   Alias: /cerco /Cerca /Cerco\n"
        "• /anteprima <testo> – Mostra l’anteprima in privato con bottoni Pubblica/Fix.\n"
        "• /post <link Amazon> – Anteprima singolo prodotto da link.\n"
        "• /fix – In anteprima ti permette di incollare un testo corretto.\n\n"
        "Config (solo admin): /setadmin /settag /setgroup /setmindiscount\n"
    )
    bot.reply_to(m, txt)

# Alias per /cerca
@bot.message_handler(commands=["cerca","cerco","Cerca","Cerco"])
def cmd_cerca(m):
    q = (m.text or "").split(" ", 1)
    if len(q) < 2:
        return bot.reply_to(m, "Dimmi cosa cercare: es. /cerca tv 200€ 20%")
    query_raw = q[1].strip()

    # Parse eur/pct dal testo
    price_max, pct_min_user = parse_price_max_and_pct(query_raw)
    pct_min = pct_min_user or int(S.get("MIN_DISCOUNT_PCT_DEFAULT",10))

    # keywords (togliamo numeri tipo 200€, 20%)
    query_keywords = re.sub(EURO_RE, "", query_raw)
    query_keywords = re.sub(PCT_RE, "", query_keywords).strip()

    # Cerca
    items = paapi_search(query_keywords, max_items=int(S.get("USER_SEARCH_MAX_RESULTS",5)))
    items = order_and_filter(items, pct_min=pct_min, price_max=price_max, limit=int(S.get("USER_SEARCH_MAX_RESULTS",5)))

    if not items:
        return bot.reply_to(m, "Nessun risultato utile trovato (prova a ridurre i filtri).")

    # Testo multiplo + invio immagini sotto
    text = build_multi_text(items, disclaimer_url=None)
    bot.send_message(m.chat.id, text)
    # immagini (usa la prima di ciascun prodotto)
    photos = [it["img"] for it in items if it.get("img")]
    if photos:
        send_media_group(m.chat.id, photos)

@bot.message_handler(commands=["anteprima"])
def cmd_anteprima(m):
    if not ensure_private(m): return
    q = (m.text or "").split(" ", 1)
    if len(q) < 2:
        return bot.reply_to(m, "Dimmi cosa cercare: es. /anteprima auricolari 100€ 20%")
    query_raw = q[1].strip()

    price_max, pct_min_user = parse_price_max_and_pct(query_raw)
    pct_min = pct_min_user or int(S.get("MIN_DISCOUNT_PCT_DEFAULT",10))
    query_keywords = re.sub(EURO_RE, "", query_raw)
    query_keywords = re.sub(PCT_RE, "", query_keywords).strip()

    items = paapi_search(query_keywords, max_items=int(S.get("USER_SEARCH_MAX_RESULTS",5)))
    items = order_and_filter(items, pct_min=pct_min, price_max=price_max, limit=int(S.get("USER_SEARCH_MAX_RESULTS",5)))
    if not items:
        return bot.reply_to(m, "Nessun risultato utile trovato per l’anteprima.")

    text = build_multi_text(items, disclaimer_url=None)
    photos = [it["img"] for it in items if it.get("img")]

    preview_state[m.from_user.id] = {
        "text": text,
        "photos": photos,
        "group_id": int(S.get("TARGET_GROUP_ID",0))
    }

    bot.send_message(m.chat.id, text, reply_markup=make_keyboard_preview())
    if photos:
        send_media_group(m.chat.id, photos)

@bot.message_handler(commands=["post"])
def cmd_post(m):
    q = (m.text or "").split(" ", 1)
    if len(q) < 2:
        return bot.reply_to(m, "Uso: /post <link Amazon>")
    url = q[1].strip()
    asin, resolved = extract_asin_smart(url)
    if not asin:
        return bot.reply_to(m, "Link non valido o ASIN non trovato.")
    p = paapi_get_item(asin)
    if not p:
        return bot.reply_to(m, "Prodotto non trovato.")
    text = build_multi_text([p], disclaimer_url=None)
    photos = [p["img"]] if p.get("img") else []
    if m.chat.type == "private":
        preview_state[m.from_user.id] = {
            "text": text, "photos": photos, "group_id": int(S.get("TARGET_GROUP_ID",0))
        }
        bot.send_message(m.chat.id, text, reply_markup=make_keyboard_preview())
        if photos: send_media_group(m.chat.id, photos)
    else:
        bot.send_message(m.chat.id, text)
        if photos: send_media_group(m.chat.id, photos)

@bot.message_handler(commands=["fix"])
def cmd_fix(m):
    # Flow: in anteprima premi "Fix", il bot risponde con "invia testo corretto"
    # Se usi /fix direttamente, spiego come fare.
    if not ensure_private(m): return
    uid = m.from_user.id
    if uid not in preview_state:
        return bot.reply_to(m, "Non hai nessuna anteprima aperta. Usa prima /anteprima o /post in privato.")
    bot.reply_to(m, "Incolla qui sotto il **testo corretto** del post.\n(Dopo potrai premere di nuovo 📣 Pubblica)", parse_mode="Markdown")
    preview_state[uid]["await_fix"] = True

@bot.message_handler(func=lambda m: m.chat.type=="private")
def on_private_text(m):
    # Se siamo in attesa del testo corretto per /fix
    st = preview_state.get(m.from_user.id)
    if st and st.get("await_fix"):
        text = (m.text or "").strip()
        if len(text) < 10:
            return bot.reply_to(m, "Testo troppo corto. Incolla il testo completo del post.")
        st["text"] = text
        st["await_fix"] = False
        bot.reply_to(m, "✅ Testo aggiornato. Ora puoi premere **📣 Pubblica nel gruppo**.", parse_mode="Markdown")

# =========================
# CALLBACK BOTTONI
# =========================
@bot.callback_query_handler(func=lambda c: c.data in ("pubblica","fix"))
def on_cb(c):
   
