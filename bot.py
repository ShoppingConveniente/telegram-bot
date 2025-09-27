#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, json, time, logging, tempfile
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, InputMediaPhoto
)
from telegram.ext import (
    Updater, CommandHandler, CallbackContext, CallbackQueryHandler, Filters, MessageHandler
)

# ======== LOGGING ========
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
log = logging.getLogger("cianfrusacc-ia")

# ======== CONFIG & STATE ========
SETTINGS_PATH = "settings.json"

@dataclass
class Settings:
    TELEGRAM_TOKEN: str = ""
    ADMIN_ID: Optional[int] = None            # può essere settato da /setadmin
    TARGET_GROUP_ID: Optional[int] = None     # può essere settato da /setgroup
    PARTNER_TAG: Optional[str] = None         # può essere settato da /settag
    MIN_DISCOUNT_DEFAULT: int = 10            # sconto minimo di default
    MAX_RESULTS_DEFAULT: int = 5              # quanti prodotti mostrare
    ALLOW_PUBLIC_POST: bool = False           # se True: tutti possono usare /post in gruppo

def load_settings() -> Settings:
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # override con ENV se presenti
        data["TELEGRAM_TOKEN"] = os.getenv("BOT_TOKEN", data.get("TELEGRAM_TOKEN", ""))
        if os.getenv("ADMIN_ID"):
            data["ADMIN_ID"] = int(os.getenv("ADMIN_ID"))
        if os.getenv("TARGET_GROUP_ID"):
            data["TARGET_GROUP_ID"] = int(os.getenv("TARGET_GROUP_ID"))
        if os.getenv("PARTNER_TAG"):
            data["PARTNER_TAG"] = os.getenv("PARTNER_TAG")
        return Settings(**data)
    s = Settings()
    # ENV iniziali
    s.TELEGRAM_TOKEN = os.getenv("BOT_TOKEN", "")
    if os.getenv("ADMIN_ID"): s.ADMIN_ID = int(os.getenv("ADMIN_ID"))
    if os.getenv("TARGET_GROUP_ID"): s.TARGET_GROUP_ID = int(os.getenv("TARGET_GROUP_ID"))
    if os.getenv("PARTNER_TAG"): s.PARTNER_TAG = os.getenv("PARTNER_TAG")
    save_settings(s)
    return s

def save_settings(s: Settings):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(s), f, ensure_ascii=False, indent=2)

S = load_settings()

# ======== SINGLE INSTANCE LOCK (portable, evita /tmp fisso) ========
LOCK_PATH = os.path.join(tempfile.gettempdir(), "cianfrusacc_ia.lock")

def ensure_single_instance() -> bool:
    try:
        if os.path.exists(LOCK_PATH):
            # se il processo precedente è ancora vivo non avviamo
            return False
        with open(LOCK_PATH, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        log.warning("Lock non creato (%s). Continuo comunque.", e)
        return True

def release_lock():
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except Exception:
        pass

# ======== UTIL ========
EURO_RE = re.compile(r"(\d+([.,]\d+)?)\s*€")
PCT_RE  = re.compile(r"(\d{1,2})\s*%")

def parse_query(text: str, default_min_pct: int, default_max_results: int) -> Tuple[str, Optional[float], int, int]:
    """
    Estrae: keywords, price_cap (float o None), min_discount_pct, max_results
    Esempi:
      "tv 200€ 20%" -> ("tv", 200.0, 20, 5)
      "airpods 120€" -> ("airpods", 120.0, 10, 5)
      "cuffie 25%" -> ("cuffie", None, 25, 5)
    """
    min_pct = default_min_pct
    price_cap = None
    max_results = default_max_results

    m_e = EURO_RE.search(text)
    if m_e:
        price_cap = float(m_e.group(1).replace(",", "."))
        text = EURO_RE.sub("", text)

    m_p = PCT_RE.search(text)
    if m_p:
        try:
            min_pct = max(default_min_pct, int(m_p.group(1)))
        except Exception:
            pass
        text = PCT_RE.sub("", text)

    # estrai eventuale "x risultati"
    m_n = re.search(r"\b(\d{1,2})\b", text)
    if m_n:
        n = int(m_n.group(1))
        if 1 <= n <= 10:
            max_results = n
            text = re.sub(r"\b"+re.escape(m_n.group(1))+r"\b", "", text, count=1)

    keywords = " ".join(text.split()).strip()
    return keywords, price_cap, min_pct, max_results

# ======== MODELLO RISULTATO & FORMATTING ========
@dataclass
class Offer:
    title: str
    price_now: float
    price_was: Optional[float]
    url: str
    image_url: Optional[str] = None
    discount_pct: Optional[int] = None
    has_coupon: bool = False

def format_offer_block(o: Offer) -> str:
    # calcolo % se non fornita
    pct = o.discount_pct
    if pct is None and o.price_was and o.price_was > 0:
        pct = round((1 - (o.price_now / o.price_was)) * 100)

    old = f"{o.price_was:,.2f}€".replace(",", "X").replace(".", ",").replace("X", ".") if o.price_was else "-"
    now = f"{o.price_now:,.2f}€".replace(",", "X").replace(".", ",").replace("X", ".")
    lines = [
        f"📍 {o.title}",
        f"{now} invece di {old}" if o.price_was else f"{now}",
        f"🛒 {o.url}"
    ]
    return "\n".join(lines)

def build_post_text(offers: List[Offer]) -> str:
    parts = [format_offer_block(o) for o in offers]
    text = "\n\n".join(parts)
    text += "\n\n#Adv ℹ️ Info prezzi visualizzati - https://cianfrusaglie.net/disclaimer-prezzi/"
    return text

# ======== MOTORE RICERCA (stub da collegare a Amazon PA-API) ========
def search_offers_amazon(keywords: str,
                         min_discount: int,
                         price_cap: Optional[float],
                         limit: int,
                         partner_tag: Optional[str]) -> List[Offer]:
    """
    QUI si collega la Amazon PA-API. Per partire subito lasciamo uno stub che
    restituisce lista vuota (il resto del bot funziona). Appena inserisci le API,
    sostituisci questa funzione con la chiamata reale.
    """
    log.info("Ricerca (stub) -> kw=%s, min%%=%s, cap=%s, limit=%s, tag=%s",
             keywords, min_discount, price_cap, limit, partner_tag)
    return []

# ======== HANDLERS ========
def is_admin(user_id: int) -> bool:
    return S.ADMIN_ID is not None and user_id == S.ADMIN_ID

def start(update: Update, context: CallbackContext):
    u = update.effective_user
    msg = [
        f"Ciao {u.first_name or ''}! 👋",
        "Sono *Cianfrusacc-IA* — il tuo bot per cercare offerte Amazon.",
        "",
        "Comandi rapidi:",
        "• /cerca parole 200€ 20%  → cerca con prezzo max e sconto minimo",
        "• /anteprima parole  → genera anteprima in privato con pulsanti",
        "• /post <link Amazon> → post singolo da link",
        "",
        "Setup admin (solo proprietario):",
        "• /setadmin <id>",
        "• /setgroup <id_gruppo>",
        "• /settag <partner_tag>",
        "",
        f"Sconto minimo attuale: {S.MIN_DISCOUNT_DEFAULT}%  | Risultati: {S.MAX_RESULTS_DEFAULT}"
    ]
    update.message.reply_text("\n".join(msg), parse_mode=ParseMode.MARKDOWN)

def cmd_setadmin(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Uso: /setadmin <telegram_id>")
        return
    try:
        S.ADMIN_ID = int(context.args[0])
        save_settings(S)
        update.message.reply_text(f"✅ ADMIN_ID impostato a {S.ADMIN_ID}")
    except Exception:
        update.message.reply_text("ID non valido.")

def cmd_setgroup(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Solo l'admin può farlo.")
        return
    if not context.args:
        update.message.reply_text("Uso: /setgroup <id_gruppo>")
        return
    try:
        S.TARGET_GROUP_ID = int(context.args[0])
        save_settings(S)
        update.message.reply_text(f"✅ Gruppo destinazione impostato a {S.TARGET_GROUP_ID}")
    except Exception:
        update.message.reply_text("ID gruppo non valido.")

def cmd_settag(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("Solo l'admin può farlo.")
        return
    if not context.args:
        update.message.reply_text("Uso: /settag <partner_tag>")
        return
    S.PARTNER_TAG = context.args[0]
    save_settings(S)
    update.message.reply_text(f"✅ Partner tag impostato a {S.PARTNER_TAG}")

def _handle_search(update: Update, context: CallbackContext):
    text = " ".join(context.args) if context.args else ""
    if not text:
        update.message.reply_text("Uso: /cerca parole_chiave [200€] [20%]")
        return

    keywords, price_cap, min_pct, max_results = parse_query(
        text, S.MIN_DISCOUNT_DEFAULT, S.MAX_RESULTS_DEFAULT
    )

    offers = search_offers_amazon(
        keywords=keywords,
        min_discount=min_pct,
        price_cap=price_cap,
        limit=max_results,
        partner_tag=S.PARTNER_TAG
    )

    if not offers:
        update.message.reply_text("Nessun risultato trovato.")
        return

    # testo + poi eventuali immagini
    post_text = build_post_text(offers)
    update.message.reply_text(post_text)

    photos = [o.image_url for o in offers if o.image_url]
    if photos:
        media = [InputMediaPhoto(p) for p in photos[:10]]
        try:
            update.message.reply_media_group(media)
        except Exception as e:
            log.warning("Invio media group fallito: %s", e)

def cmd_anteprima(update: Update, context: CallbackContext):
    # sempre in privato
    if update.effective_chat.type != "private":
        update.message.reply_text("Usa /anteprima in privato. ✅")
        return

    text = " ".join(context.args) if context.args else ""
    if not text:
        update.message.reply_text("Uso: /anteprima parole_chiave [200€] [20%]")
        return

    keywords, price_cap, min_pct, max_results = parse_query(
        text, S.MIN_DISCOUNT_DEFAULT, S.MAX_RESULTS_DEFAULT
    )
    offers = search_offers_amazon(
        keywords=keywords,
        min_discount=min_pct,
        price_cap=price_cap,
        limit=max_results,
        partner_tag=S.PARTNER_TAG
    )

    if not offers:
        update.message.reply_text("Nessun risultato trovato.")
        return

    preview = build_post_text(offers)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📣 Pubblica nel gruppo", callback_data="pubblica")],
        [InlineKeyboardButton("🛠️ Fix prezzo", callback_data="fix")]
    ])
    context.user_data["preview_text"] = preview
    context.user_data["preview_photos"] = [o.image_url for o in offers if o.image_url]
    update.message.reply_text(preview, reply_markup=kb)

def cmd_post(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Uso: /post <link Amazon>")
        return
    url = context.args[0]
    # qui potresti fare la fetch-singolo prodotto con PA-API
    update.message.reply_text("🔧 Post singolo da link in arrivo (collega PA-API)…")

def on_callback(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    data = q.data
    text = context.user_data.get("preview_text")
    photos = context.user_data.get("preview_photos", [])

    if not text:
        q.edit_message_text("Anteprima scaduta. Rifai /anteprima.")
        return

    if data == "fix":
        q.edit_message_text("Invia il testo corretto del post in un unico messaggio.")
        context.user_data["waiting_fix"] = True
        return

    if data == "pubblica":
        if not S.TARGET_GROUP_ID:
            q.edit_message_text("Nessun gruppo configurato. Usa /setgroup <id> (admin).")
            return
        bot: Bot = context.bot
        bot.send_message(chat_id=S.TARGET_GROUP_ID, text=text)
        if photos:
            try:
                media = [InputMediaPhoto(p) for p in photos[:10]]
                bot.send_media_group(chat_id=S.TARGET_GROUP_ID, media=media)
            except Exception as e:
                log.warning("Media group fail: %s", e)
        q.edit_message_text("✅ Pubblicato nel gruppo.")
        context.user_data.pop("preview_text", None)
        context.user_data.pop("preview_photos", None)

def on_text(update: Update, context: CallbackContext):
    # gestisce il testo dopo "Fix prezzo"
    if context.user_data.get("waiting_fix"):
        new_text = update.message.text
        context.user_data["preview_text"] = new_text
        context.user_data["waiting_fix"] = False
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📣 Pubblica nel gruppo", callback_data="pubblica")],
            [InlineKeyboardButton("🛠️ Fix prezzo", callback_data="fix")]
        ])
        update.message.reply_text("✅ Testo aggiornato. Pronto a pubblicare.", reply_markup=kb)

def main():
    if not S.TELEGRAM_TOKEN:
        raise SystemExit("BOT_TOKEN mancante. Imposta variabile d'ambiente BOT_TOKEN oppure settings.json")

    if not ensure_single_instance():
        log.error("Istanza già in esecuzione. Esco.")
        return

    updater = Updater(token=S.TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    # comandi
    for cmd in ("cerca","cerco","Cerca","Cerco"):
        dp.add_handler(CommandHandler(cmd, _handle_search, pass_args=True))
    dp.add_handler(CommandHandler("anteprima", cmd_anteprima, pass_args=True))
    dp.add_handler(CommandHandler("post", cmd_post, pass_args=True))
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", start))
    dp.add_handler(CommandHandler("setadmin", cmd_setadmin, pass_args=True))
    dp.add_handler(CommandHandler("setgroup", cmd_setgroup, pass_args=True))
    dp.add_handler(CommandHandler("settag", cmd_settag, pass_args=True))

    # callback & testo (fix)
    dp.add_handler(CallbackQueryHandler(on_callback))
    dp.add_handler(MessageHandler(Filters.text & Filters.private, on_text))

    log.info("Bot avviato.")
    try:
        updater.start_polling(clean=True)
        updater.idle()
    finally:
        release_lock()

if __name__ == "__main__":
    main()
