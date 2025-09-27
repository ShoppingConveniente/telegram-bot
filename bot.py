#!/usr/bin/env python3
import os, json, logging, requests, random
from zoneinfo import ZoneInfo
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater, CommandHandler, MessageHandler,
    CallbackContext, CallbackQueryHandler, Filters
)

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
TZ = ZoneInfo("Europe/Rome")

# ================ HANDLERS ================

def start(update: Update, context: CallbackContext):
    update.message.reply_text("👋 Benvenuto! Usa /cerca per trovare offerte.")

def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "📌 Comandi disponibili:\n"
        "/cerca keyword [prezzo] [sconto%]\n"
        "/anteprima keyword\n"
        "/post link_amazon\n"
        "/fix\n"
    )

def cerca(update: Update, context: CallbackContext):
    # TODO: logica di ricerca Amazon
    update.message.reply_text("🔎 Ricerca in corso... (placeholder)")
    pass

def anteprima(update: Update, context: CallbackContext):
    # TODO: generare anteprima con bottoni
    update.message.reply_text("👀 Anteprima in privato (placeholder)")
    pass

def post(update: Update, context: CallbackContext):
    # TODO: post singolo da link Amazon
    update.message.reply_text("📦 Post singolo generato (placeholder)")
    pass

def fix(update: Update, context: CallbackContext):
    # TODO: correzione manuale post
    update.message.reply_text("✏️ Correzione attiva, invia il testo corretto.")
    pass

# ================ MAIN ====================

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler(["cerca","cerco","Cerca","Cerco"], cerca))
    dp.add_handler(CommandHandler("anteprima", anteprima))
    dp.add_handler(CommandHandler("post", post))
    dp.add_handler(CommandHandler("fix", fix))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
