#!/usr/bin/env python3
import os, json, logging, requests, random, datetime as dt
from zoneinfo import ZoneInfo
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackContext, CallbackQueryHandler
)

# =============== CONFIG ===============
with open("settings.json", "r", encoding="utf-8") as f:
    S = json.load(f)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
TZ = ZoneInfo("Europe/Rome")

# Autopost
AUTOPOST_ENABLED = S.get("AUTOPOST_ENABLED", False)
AUTOPOST_GROUP_ID = S.get("AUTOPOST_GROUP_ID")
AUTOPOST_QUERIES = S.get("AUTOPOST_QUERIES", [])
AUTOPOST_INTERVAL_MIN = S.get("AUTOPOST_INTERVAL_MIN", 60)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

bot = Bot(token=TOKEN)


# =============== FUNZIONI ===============
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Benvenuto! Questo è il bot Shopping Conveniente.\n"
        "Usa /cerca + parola per trovare offerte.\n"
        "Esempio: /cerca airpods"
    )


def cerca(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("❌ Usa: /cerca prodotto")
        return
    query = " ".join(context.args)
    log.info(f"[CERCA] {query}")
    # Simulazione risultato (qui ci va la chiamata API Amazon/PAAPI)
    fake_url = f"https://www.amazon.it/s?k={query.replace(' ', '+')}&tag={S['PAAPI_PARTNER_TAG']}"
    msg = f"📍 {query.title()}\n99,00€ invece di 149,00€\n🛒 {fake_url}"
    update.message.reply_text(msg)


def fix(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        _, asin, prezzo, prezzo_old = update.message.text.split()
        msg = (
            f"📍 Prodotto {asin}\n"
            f"{prezzo} invece di {prezzo_old}\n"
            f"🛒 https://www.amazon.it/dp/{asin}/?tag={S['PAAPI_PARTNER_TAG']}"
        )
        update.message.reply_text("✅ Corretto:\n\n" + msg)
    except Exception as e:
        update.message.reply_text("❌ Uso: /fix ASIN PREZZO PREZZO_OLD")
        log.error(e)


def autopost(context: CallbackContext):
    if not AUTOPOST_ENABLED:
        return
    query = random.choice(AUTOPOST_QUERIES)
    fake_url = f"https://www.amazon.it/s?k={query.replace(' ', '+')}&tag={S['PAAPI_PARTNER_TAG']}"
    msg = f"📍 Offerta automatica: {query}\n79,00€ invece di 119,00€\n🛒 {fake_url}"
    bot.send_message(chat_id=AUTOPOST_GROUP_ID, text=msg)


# =============== MAIN ===============
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("cerca", cerca))
    dp.add_handler(CommandHandler("fix", fix))

    # Avvio autopost
    if AUTOPOST_ENABLED:
        job = updater.job_queue
        job.run_repeating(autopost, interval=AUTOPOST_INTERVAL_MIN * 60, first=10)
        log.info("AUTOPOST attivo")

    log.info("Bot avviato ✅")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
