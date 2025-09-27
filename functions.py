from telegram import Update
from telegram.ext import ContextTypes
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
Token = '5873483525:AAFBY74pem2W2iGONEhpEz6yN09vCmqqy0Q'
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
                    channel_id = channel.get('channel_name')  # This should be the actual @username or chat_id
                    try:
                        await bot.send_message(chat_id=channel_id, text=message_text)
                        total_sent += 1
                    except Exception as channel_error:
                        print(f"Error sending to channel {channel_id}: {channel_error}")

        await bot.send_message(chat_id=user_id, text=f"✅ Scheduled message sent to {total_sent} channels!")

    except Exception as e:
        await bot.send_message(chat_id=user_id, text=f"❌ Error sending scheduled message: {e}")

async def check_channel_admin_with_send_permission(update, context, channel_username):
    """
    Returns True if the bot is an admin in the channel with permission to send messages, False otherwise.
    """
    try:
        chat = await context.bot.get_chat(channel_username)  # username or ID of the channel
        bot_member = await chat.get_member(context.bot.id)

        if bot_member.status == 'administrator':
            can_send = getattr(bot_member, 'can_post_messages', False)
            # can_post_messages is True if the bot can send messages in channels
            return can_send
        else:
            return False
    except Exception:
        return False


from datetime import datetime
from google.cloud import firestore

def normalize_channel_name(name: str) -> str:
    """
    Lowercase, strip whitespace, remove trailing dots.
    """
    return name.strip().lower().rstrip(".")

async def add_channel_for_user(update, context, user_data, user_id, text):
    if user_id in user_data and user_data[user_id].get("awaiting_channel_name"):
        user_data[user_id]["channel_name"] = text
        user_data[user_id]["awaiting_channel_name"] = False
        await update.message.reply_text(f"Checking if I am an admin in the channel {text}...")

        try:
            # 1️⃣ Check if bot is admin with send permission
            is_admin = await check_channel_admin_with_send_permission(update, context, text)

            if not is_admin:
                await update.message.reply_text(
                    f"❌ I am not an admin with send messages permission in {text}. Cannot add this channel."
                )
                return

            # Normalize input text for duplicate check
            normalized_text = normalize_channel_name(text)

            # 2️⃣ Access Firestore user document
            user_doc_ref = db.collection("users").document(str(user_id))
            user_doc = user_doc_ref.get()

            if user_doc.exists:
                # Existing user: check duplicates
                user_data_db = user_doc.to_dict()
                existing_channels = user_data_db.get("channels", [])

                channel_exists = any(
                    normalize_channel_name(channel["channel_name"]) == normalized_text
                    for channel in existing_channels
                )

                if channel_exists:
                    await update.message.reply_text(f"⚠️ Channel {text} already exists in your list!")
                else:
                    # Add new channel safely
                    user_doc_ref.update({
                        "channels": firestore.ArrayUnion([{
                            "channel_name": normalized_text,  # store normalized version
                            "added_at": datetime.now()
                        }]),
                        "last_updated": datetime.now()
                    })
                    await update.message.reply_text(f"✅ Channel {text} added to your list!")
            else:
                # New user: create document
                user_doc_ref.set({
                    "name": user_data[user_id]["name"],
                    "channels": [{
                        "channel_name": normalized_text,
                        "added_at": datetime.now()
                    }],
                    "created_at": datetime.now()
                })
                await update.message.reply_text(f"✅ Your info and channel {text} have been saved!")

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            print(e)
        return

async def store_message_for_user(user_id: int, message: str):
    """
    Store a message for the user in Firestore under 'stored_messages' collection.
    Each document contains:
        - user_id
        - message
        - created_at
    """
    try:
        db.collection("stored_messages").document('mssg').set({
            "user_id": user_id,
            "message": message,
            "created_at": datetime.utcnow()
        })
        return True, None
    except Exception as e:
        return False, str(e)


from firebase_admin import firestore

async def send_stored_messages(update, context, user_id):
    """
    Send all stored messages of the user to their channels.
    """
    try:
        # Get user document
        user_doc_ref = db.collection("users").document(str(user_id))
        user_doc = user_doc_ref.get()

        if not user_doc.exists:
            await update.message.reply_text("❌ No user data found. Please add your channels first.")
            return

        user_data_db = user_doc.to_dict()
        user_channels = user_data_db.get("channels", [])

        if not user_channels:
            await update.message.reply_text("📭 You have no channels added.")
            return

        # Get stored messages
        stored_messages_query = db.collection("stored_messages").where("user_id", "==", user_id).stream()
        stored_messages = [doc.to_dict() for doc in stored_messages_query]

        if not stored_messages:
            await update.message.reply_text("📭 No stored messages found to send.")
            return

        total_sent = 0
        for message_doc in stored_messages:
            message_text = message_doc.get("message", "")
            if not message_text:
                continue

            for channel in user_channels:
                channel_name = channel.get("channel_name")
                try:
                    await context.bot.send_message(chat_id=channel_name, text=message_text)
                    total_sent += 1
                except Exception as e:
                    print(f"Error sending to {channel_name}: {e}")

        await update.message.reply_text(f"✅ Messages sent to {total_sent} channels!")

    except Exception as e:
        await update.message.reply_text(f"❌ Error sending messages: {e}")
        
