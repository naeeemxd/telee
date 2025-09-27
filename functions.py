from telegram import Update
from telegram.ext import ContextTypes
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
Token = '6822347037:AAHpA8YvUXGIV3YLw5DgE3BZtn1St_JEl3c'
# db = firestore.client()
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()


async def send_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text):
    channel_username = "@testttmmml"  # Replace with your channel username

    try:
        await context.bot.send_message(chat_id=channel_username, text=message_text)
        await update.message.reply_text("✅ Message sent to the channel!")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send message: {e}")

# Check if bot is in the channel
async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):

    channel_username = update.message.text.strip()  # e.g., "@testttmmml"
    try:
        bot_member = await context.bot.get_chat_member(channel_username, context.bot.id)
        status = bot_member.status
        if status in ["administrator", "member", "creator"]:
            await update.message.reply_text(f"✅ I am inside the channel {channel_username}. Status: {status}")
        else:
            await update.message.reply_text(f"❌ I am NOT in the channel {channel_username}. Status: {status}")
    except Exception as e:
        await update.message.reply_text(f"❌ Cannot access {channel_username}. Make sure the bot is added to the channel.\nError: {e}")
async def send_scheduled_message(bot, user_id, message_text):
    try:
        docs = db.collection("users").stream()
        total_sent = 0

        for doc in docs:
            user_data_db = doc.to_dict()
            user_channels = user_data_db.get("channels", [])

            if user_channels:
                for channel in user_channels:
