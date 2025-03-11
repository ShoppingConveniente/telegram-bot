import logging
import time
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import re

# Configura il logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# CONFIGURAZIONE DEL BOT
TOKEN = "7637611635:AAEfPOwt9Sfd86bgPOjNIhv9aL3zLKYbXGQ"
CHAT_ID = "7348792795"

bot = Bot(token=TOKEN)

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Ciao! Inviami un link per ottenere il link affiliato.")

def handle_message(update: Update, context: CallbackContext) -> None:
    user_message = update.message.text
    update.message.reply_text("Attendi, elaborazione in corso...")
    
    # Simulazione di generazione link affiliato
    affiliate_link = generate_affiliate_link(user_message)
    update.message.reply_text(f"Ecco il tuo link affiliato: {affiliate_link}")

def generate_affiliate_link(original_link: str) -> str:
    # Verifica se il link contiene già un tag di affiliazione
    if "tag=" in original_link:
        return original_link  # Se è già affiliato, lo lasciamo invariato
    
    # Aggiunge il codice di affiliazione correttamente
    if "?" in original_link:
        return original_link + "&tag=shoppingconve-21"
    else:
        return original_link + "?tag=shoppingconve-21"

def monitor_offers():
    while True:
        try:
            offers = ["Offerta 1", "Offerta 2", "Offerta 3"]
            for offer in offers:
                bot.send_message(chat_id=CHAT_ID, text=f"🔔 Nuova offerta: {offer}")
            
            time.sleep(1800)  # Ogni 30 minuti
        except Exception as e:
            logger.error(f"Errore nel monitoraggio offerte: {e}")

# Configura il bot
updater = Updater(TOKEN)
dp = updater.dispatcher
dp.add_handler(CommandHandler("start", start))
dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

if __name__ == "__main__":
    updater.start_polling()
    updater.idle()
