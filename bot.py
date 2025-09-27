from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from datetime import datetime
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from threading import Thread

from functions import send_stored_messages, send_to_channel, add_channel_for_user, send_scheduled_message, store_message_for_user, Token, db

app_web = Flask(__name__)


@app_web.route('/')
def home():
    return "Bot is running!"


def run_web():
    app_web.run(host='0.0.0.0', port=8080)


Thread(target=run_web).start()

# Initialize Scheduler with misfire grace time (will be started later)
scheduler = AsyncIOScheduler(
    job_defaults={'misfire_grace_time': 30}  # Allow 30 seconds grace time
)

# Temporary in-memory storage for conversation state
user_data = {}


# /start command with inline buttons
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [  # Row 1
            InlineKeyboardButton("Add Your Channel",
                                 callback_data='add_channel'),
            InlineKeyboardButton("Show My Channels",
                                 callback_data='show_channels'),
        ],
        [InlineKeyboardButton("Send Message Now", callback_data='send_mssg')],
        [  # Row 2
            InlineKeyboardButton("Schedule Message",
                                 callback_data='schedule_mssg'),
            InlineKeyboardButton("Store Message", callback_data='store_mssgs')
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome! Choose an option:",
                                    reply_markup=reply_markup)


# Handle button clicks
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'send_mssg':
        await query.message.reply_text(
            "This will send stored messages to all channels. Type 'confirm' to proceed:"
        )
        user_data[query.from_user.id] = {"awaiting_send_mssg": True}
        return

    if query.data == 'schedule_mssg':
        nowtime = datetime.now().strftime("%Y-%m-%d %H:%M")

        await query.message.reply_text(
            "📅 Schedule a message!\n\n"
            "Send me the datetime in this format:\n"
            "YYYY-MM-DD HH:MM\n\n"
            f"Example: {nowtime}\n"
            "This will schedule for December 25, 2024 at 2:30 PM")
        user_data[query.from_user.id] = {"awaiting_schedule_time": True}
        return

    if query.data == 'add_channel':
        await query.message.reply_text("What's your name?")
        user_data[query.from_user.id] = {"awaiting_name": True}
        return

    if query.data == 'show_channels':
        try:
            user_doc_ref = db.collection("users").document(
                str(query.from_user.id))
            user_doc = user_doc_ref.get()

            if user_doc.exists:
                user_data_db = user_doc.to_dict()
                channels = user_data_db.get("channels", [])

                if not channels:
                    await query.message.reply_text(
                        "📭 No channels found for your account.")
                else:
                    response = f"📋 Your Channels ({len(channels)}):\n\n"
                    for i, channel in enumerate(channels, 1):
                        channel_name = channel.get('channel_name', 'Unknown')
                        added_at = channel.get('added_at', 'Unknown date')
                        response += f"{i}. {channel_name}\n   📅 Added: {added_at}\n\n"
                    await query.message.reply_text(response)
            else:
                await query.message.reply_text(
                    "❌ No user data found. Please add a channel first!")

        except Exception as e:
            await query.message.reply_text(f"❌ Error: {str(e)}")
        return

    if query.data == 'store_mssgs':
        await query.message.reply_text("Enter your message to store:")
        user_data[query.from_user.id] = {"awaiting_store_mssg": True}
        return


# Handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    chat_type = update.message.chat.type  # 'private', 'group', 'supergroup', 'channel'

    if chat_type == 'private' and chat_type != 'channel':

        # Handle store message
        if user_id in user_data and user_data[user_id].get(
                "awaiting_store_mssg"):
            text_to_store = update.message.text.strip()
            success, error = await store_message_for_user(
                user_id, text_to_store)
            user_data[user_id]["awaiting_store_mssg"] = False

            if success:
                await update.message.reply_text(
                    "✅ Message stored successfully!")
            else:
                await update.message.reply_text(
                    f"❌ Error storing message: {error}")
            return

        # Handle immediate message sending
        if user_id in user_data and user_data[user_id].get(
                "awaiting_send_mssg"):
            user_data[user_id]["awaiting_send_mssg"] = False
            if text.lower() == "confirm":
                await send_stored_messages(update, context, user_id)
            else:
                await update.message.reply_text(
                    "❌ Send cancelled. Type 'confirm' to send messages.")
            return

        # Handle scheduling time input
        if user_id in user_data and user_data[user_id].get(
                "awaiting_schedule_time"):
            try:
                # Parse the datetime
                schedule_time = datetime.strptime(text, "%Y-%m-%d %H:%M")

                # Check if the time is in the future
                if schedule_time <= datetime.now():
                    await update.message.reply_text(
                        "❌ Please enter a future date and time!")
                    return

                user_data[user_id]["schedule_time"] = schedule_time
                user_data[user_id]["awaiting_schedule_time"] = False
                user_data[user_id]["awaiting_schedule_message"] = True

                await update.message.reply_text(
                    f"⏰ Scheduled for: {schedule_time.strftime('%Y-%m-%d %H:%M')}\n\n"
                    "Now send me the message you want to schedule:")
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid format! Please use: YYYY-MM-DD HH:MM\n"
                    "Example: 2024-12-25 14:30")
            return

        # Handle scheduled message content
        if user_id in user_data and user_data[user_id].get(
                "awaiting_schedule_message"):
            schedule_time = user_data[user_id]["schedule_time"]
            user_data[user_id]["awaiting_schedule_message"] = False

            try:
                # Schedule the message
                scheduler.add_job(
                    send_scheduled_message,
                    DateTrigger(run_date=schedule_time),
                    args=[context.bot, user_id, text],
                    id=
                    f"scheduled_msg_{user_id}_{int(schedule_time.timestamp())}"
                )

                # Save scheduled message to database
                db.collection("scheduled_messages").add({
                    "user_id":
                    user_id,
                    "message":
                    text,
                    "scheduled_time":
                    schedule_time,
                    "created_at":
                    datetime.now()
                })

                await update.message.reply_text(
                    f"✅ Message scheduled successfully!\n\n"
                    f"📅 Date: {schedule_time.strftime('%Y-%m-%d')}\n"
                    f"⏰ Time: {schedule_time.strftime('%H:%M')}\n"
                    f"📝 Message: {text[:50]}{'...' if len(text) > 50 else ''}")
            except Exception as e:
                await update.message.reply_text(
                    f"❌ Error scheduling message: {e}")
            return

        # Step 1: Name input
        if user_id in user_data and user_data[user_id].get("awaiting_name"):
            user_data[user_id]["name"] = text
            user_data[user_id]["awaiting_name"] = False
            user_data[user_id]["awaiting_channel_name"] = True
            await update.message.reply_text(
                f"Thanks {text}! Now, please enter your channel username (e.g., @channelname):"
            )
            return

        # Step 2: Channel username input
        if user_id in user_data and user_data[user_id].get(
                "awaiting_channel_name"):
            # User is sending the channel username now
            await add_channel_for_user(update, context, user_data, user_id,
                                       text)
            return

        # Default response
        await update.message.reply_text(
            "Please click a button first to start an action.")


# Command to show scheduled messages
async def show_scheduled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        docs = db.collection("scheduled_messages").where(
            "user_id", "==", user_id).stream()
        scheduled_messages = [doc.to_dict() for doc in docs]

        if not scheduled_messages:
            await update.message.reply_text("📭 No scheduled messages found.")
        else:
            response = "📅 Your Scheduled Messages:\n\n"
            for i, msg in enumerate(scheduled_messages, 1):
                schedule_time = msg['scheduled_time']
                message_preview = msg['message'][:30] + "..." if len(
                    msg['message']) > 30 else msg['message']
                response += f"{i}. 📅 {schedule_time.strftime('%Y-%m-%d %H:%M')}\n   📝 {message_preview}\n\n"
            await update.message.reply_text(response)
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error fetching scheduled messages: {e}")


# Main function
async def main():
    # Start the scheduler after asyncio loop is running
    scheduler.start()

    app = ApplicationBuilder().token(Token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scheduled", show_scheduled))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running...")

    # Initialize and run the bot
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        try:
            # Keep the bot running
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            print("Bot stopped by user")
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
            
