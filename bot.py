#!/usr/bin/env python3
import os, json, re, logging, requests
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
)
from telegram.ext import (
    Updater, CommandHandler, CallbackContext, MessageHandler, Filters, CallbackQueryHandler
)

# ==========================
# CONFIGURAZIONE INIZIALE
# ==========================
SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "TELEGRAM_TOKEN": "INSERISCI_TOKEN",
    "ADMIN_ID": 210492268,
    "TARGET_GROUP_ID": None,
    "AMAZON_TAG": "shoppingconve-21",
    "AMAZON_ACCESS_KEY": "",
    "AMAZON_SECRET_KEY": "",
    "MIN_DISCOUNT_PCT": 10
}

# ==========================
# LETTURA/SCRITTURA SETTINGS
# ==========================
def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS)
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

S = load_settings()

# ==========================
# LOGGING
# ==========================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================
# PLACEHOLDER AMAZON
# (qui dovrai integrare la PA-API ufficiale o scraping migliorato)
# ==========================
def fake_amazon_search(query, max_price=None, min_discount=None):
    """Simulazione ricerca Amazon (da sostituire con API ufficiali)."""
    results = [
        {
            "title": "Apple AirPods 4 Auricolari wireless",
            "price": 129.00,
            "old_price": 149.00,
            "url": f"https://www.amazon.it/dp/B0DGHWD7CT/?tag={S['AMAZON_TAG']}",
            "img": "https://m.media-amazon.com/images/I/41m7YJ+5JML._AC_SX679_.jpg"
        },
        {
            "title": "Cuffie Bluetooth 5.3 Wireless",
            "price": 7.99,
            "old_price": 149.00,
            "url": f"https://www.amazon.it/dp/B0FPR1W81P/?tag={S['AMAZON_TAG']}",
            "img": "https://m.media-amazon.com/images/I/51f1dfF9yML._AC_SX679_.jpg"
        }
    ]
    return results[:5]

# ==========================
# COMANDI BOT
# ==========================
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Benvenuto nel tuo Bot Amazon affiliato!\n"
        "Usa /help per vedere i comandi disponibili."
    )

def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "📌 Comandi disponibili:\n\n"
        "/cerca parole [prezzo€] [sconto%]\n"
        "/cerco … (alias)\n"
        "/post <link Amazon>\n"
        "/anteprima parole …\n"
        "/fix (in anteprima)\n\n"
        "⚙️ Config (solo admin):\n"
        "/setadmin <id>\n"
        "/setgroup <id>\n"
        "/settag <tag>\n"
        "/setkeys <access> <secret>\n"
        "/setminpct <numero>\n"
    )

def is_admin(update: Update):
    return update.effective_user.id == S["ADMIN_ID"]

def set_admin(update: Update, context: CallbackContext):
    if not is_admin(update): return
    if context.args:
        S["ADMIN_ID"] = int(context.args[0])
        save_settings(S)
        update.message.reply_text(f"✅ Admin aggiornato: {S['ADMIN_ID']}")

def set_group(update: Update, context: CallbackContext):
    if not is_admin(update): return
    if context.args:
        S["TARGET_GROUP_ID"] = int(context.args[0])
        save_settings(S)
        update.message.reply_text(f"✅ Gruppo target aggiornato: {S['TARGET_GROUP_ID']}")

def set_tag(update: Update, context: CallbackContext):
    if not is_admin(update): return
    if context.args:
        S["AMAZON_TAG"] = context.args[0]
        save_settings(S)
        update.message.reply_text(f"✅ Tag affiliato aggiornato: {S['AMAZON_TAG']}")

def set_keys(update: Update, context: CallbackContext):
    if not is_admin(update): return
    if len(context.args) == 2:
        S["AMAZON_ACCESS_KEY"] = context.args[0]
        S["AMAZON_SECRET_KEY"] = context.args[1]
        save_settings(S)
        update.message.reply_text("✅ Chiavi Amazon aggiornate.")

def set_minpct(update: Update, context: CallbackContext):
    if not is_admin(update): return
    if context.args:
        S["MIN_DISCOUNT_PCT"] = int(context.args[0])
        save_settings(S)
        update.message.reply_text(f"✅ Sconto minimo aggiornato: {S['MIN_DISCOUNT_PCT']}%")

# ==========================
# FUNZIONE CERCA
# ==========================
def parse_filters(args):
    query, max_price, min_discount = [], None, S["MIN_DISCOUNT_PCT"]
    for a in args:
        if a.endswith("€"):
            try: max_price = float(a[:-1])
            except: pass
        elif a.endswith("%"):
            try: min_discount = int(a[:-1])
            except: pass
        else:
            query.append(a)
    return " ".join(query), max_price, min_discount

def cerca(update: Update, context: CallbackContext):
    query, max_price, min_discount = parse_filters(context.args)
    if not query:
        update.message.reply_text("❌ Usa: /cerca parole [200€] [20%]")
        return
    results = fake_amazon_search(query, max_price, min_discount)
    if not results:
        update.message.reply_text("❌ Nessun risultato trovato.")
        return

    # Post multiplo (testo + immagini sotto)
    text_parts, media = [], []
    for r in results:
        old_price = f"{r['old_price']:.2f}€" if r['old_price'] else ""
        text_parts.append(
            f"📍 {r['title']}\n"
            f"{r['price']:.2f}€ invece di {old_price}\n"
            f"🛒 {r['url']}\n"
        )
        media.append(InputMediaPhoto(r["img"], caption=r["title"]))
    text = "\n".join(text_parts) + "\n\n#Adv ℹ️ Info prezzi visualizzati"
    update.message.reply_text(text)
    if media:
        update.message.reply_media_group(media)

# ==========================
# MAIN
# ==========================
def main():
    updater = Updater(S["TELEGRAM_TOKEN"], use_context=True)
    dp = updater.dispatcher

    # Comandi
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler(["cerca","cerco","Cerca","Cerco"], cerca))
    dp.add_handler(CommandHandler("setadmin", set_admin))
    dp.add_handler(CommandHandler("setgroup", set_group))
    dp.add_handler(CommandHandler("settag", set_tag))
    dp.add_handler(CommandHandler("setkeys", set_keys))
    dp.add_handler(CommandHandler("setminpct", set_minpct))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
