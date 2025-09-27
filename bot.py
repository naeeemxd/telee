import os
import json
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from datetime import datetime
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from threading import Thread
from firebase_admin import credentials, firestore
import firebase_admin

Token = '5873483525:AAFBY74pem2W2iGONEhpEz6yN09vCmqqy0Q'

def clean_private_key(key_str):
    """Clean and validate private key format"""
    if not key_str:
        return None
    
    # Remove quotes and extra whitespace
    key_str = key_str.strip().strip('"').strip("'")
    
    # Handle different newline representations
    key_str = key_str.replace('\\n', '\n')
    key_str = key_str.replace('\\r\\n', '\n')
    key_str = key_str.replace('\r\n', '\n')
    key_str = key_str.replace('\r', '\n')
    
    # Remove any non-printable characters and extra spaces
    import re
    # Keep only printable ASCII characters, newlines, and dashes
    key_str = re.sub(r'[^\x20-\x7E\n]', '', key_str)
    
    # Ensure proper PEM structure
    lines = key_str.split('\n')
    cleaned_lines = []
    
    for line in lines:
        line = line.strip()
        if line:  # Skip empty lines
            cleaned_lines.append(line)
    
    # Reconstruct with proper formatting
    if cleaned_lines and cleaned_lines[0].startswith('-----BEGIN'):
        key_str = '\n'.join(cleaned_lines) + '\n'
    else:
        print(f"❌ Invalid private key format. Should start with '-----BEGIN PRIVATE KEY-----'")
        return None
    
    return key_str

def initialize_firebase():
    try:
        # Method 1: Try loading from complete JSON string (recommended)
        firebase_config_json = os.environ.get('FIREBASE_CONFIG_JSON')
        if firebase_config_json:
            try:
                # Clean the JSON string first
                firebase_config_json = firebase_config_json.strip().strip('"').strip("'")
                cred_dict = json.loads(firebase_config_json)
                
                # Clean the private key within the JSON
                if 'private_key' in cred_dict:
                    cred_dict['private_key'] = clean_private_key(cred_dict['private_key'])
                    if not cred_dict['private_key']:
                        raise ValueError("Invalid private key in JSON config")
                
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                print("✅ Firebase initialized from JSON string")
                return firestore.client()
                
            except json.JSONDecodeError as e:
                print(f"❌ JSON decode error: {e}")
                print("First 100 chars of JSON:", firebase_config_json[:100])
            except Exception as e:
                print(f"❌ Firebase init error from JSON: {e}")
        
        # Method 2: Try loading from individual environment variables
        print("Trying individual environment variables...")
        
        # Get and clean the private key
        private_key_raw = os.environ.get("FIREBASE_PRIVATE_KEY", "")
        private_key = clean_private_key(private_key_raw)
        
        if not private_key:
            print("❌ Failed to clean/validate private key")
            return None
        
        # Debug: Show key structure (without revealing the actual key)
        key_lines = private_key.split('\n')
        print(f"Private key structure: {len(key_lines)} lines")
        print(f"First line: {key_lines[0] if key_lines else 'None'}")
        print(f"Last non-empty line: {[line for line in key_lines if line.strip()][-1] if key_lines else 'None'}")

        cred_dict = {
            "type": os.environ.get("FIREBASE_TYPE", "service_account"),
            "project_id": os.environ.get("FIREBASE_PROJECT_ID", ""),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID", ""),
            "private_key": private_key,
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL", ""),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID", ""),
            "auth_uri": os.environ.get("FIREBASE_AUTH_URI", "https://accounts.google.com/o/oauth2/auth"),
            "token_uri": os.environ.get("FIREBASE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
            "auth_provider_x509_cert_url": os.environ.get("FIREBASE_AUTH_PROVIDER_CERT_URL", "https://www.googleapis.com/oauth2/v1/certs"),
            "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_CERT_URL", "")
        }
        
        # Validate required fields
        required_fields = ["type", "project_id", "private_key", "client_email"]
        missing_fields = [field for field in required_fields if not cred_dict.get(field)]
        
        if missing_fields:
            print(f"❌ Missing required Firebase config fields: {missing_fields}")
            return None
        
        # Validate project_id and client_email format
        if not cred_dict["project_id"] or not cred_dict["client_email"]:
            print("❌ project_id or client_email is empty")
            return None
            
        if "@" not in cred_dict["client_email"]:
            print("❌ client_email doesn't look like an email address")
            return None
        
        print("All validation passed, trying to initialize Firebase...")
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase initialized from individual env vars")
        return firestore.client()
        
    except Exception as e:
        print(f"❌ Firebase initialization failed: {e}")
        print(f"Error type: {type(e).__name__}")
        
        # Try to provide more specific error info
        if "Unable to load PEM file" in str(e):
            print("🔍 Private key PEM format issue detected.")
            print("Please ensure your private key:")
            print("1. Starts with '-----BEGIN PRIVATE KEY-----'")
            print("2. Ends with '-----END PRIVATE KEY-----'")
            print("3. Has proper line breaks (\\n)")
            print("4. Contains only valid base64 characters between headers")
            
        return None

# Initialize Firebase
db = initialize_firebase()

if not db:
    print("❌ Failed to initialize Firebase. Bot will not work properly.")
    exit(1)

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
            InlineKeyboardButton("Add Your Channel", callback_data='add_channel'),
            InlineKeyboardButton("Show My Channels", callback_data='show_channels'),
        ],
        [
            InlineKeyboardButton("Send Message Now", callback_data='send_mssg')
        ],
        [  # Row 2
            InlineKeyboardButton("Schedule Message", callback_data='schedule_mssg'),
            InlineKeyboardButton("Store Message", callback_data='store_mssgs')
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=reply_markup)

# Handle button clicks
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'send_mssg':
        await query.message.reply_text("This will send stored messages to all channels. Type 'confirm' to proceed:")
        user_data[query.from_user.id] = {"awaiting_send_mssg": True}
        return

    if query.data == 'schedule_mssg':
        nowtime = datetime.now().strftime("%Y-%m-%d %H:%M")

        await query.message.reply_text(
            "📅 Schedule a message!\n\n"
            "Send me the datetime in this format:\n"
            "YYYY-MM-DD HH:MM\n\n"
            f"Example: {nowtime}\n"
            "This will schedule for December 25, 2024 at 2:30 PM"
        )
        user_data[query.from_user.id] = {"awaiting_schedule_time": True}
        return

    if query.data == 'add_channel':
        await query.message.reply_text("What's your name?")
        user_data[query.from_user.id] = {"awaiting_name": True}
        return

    if query.data == 'show_channels':
        try:
            user_doc_ref = db.collection("users").document(str(query.from_user.id))
            user_doc = user_doc_ref.get()

            if user_doc.exists:
                user_data_db = user_doc.to_dict()
                channels = user_data_db.get("channels", [])

                if not channels:
                    await query.message.reply_text("📭 No channels found for your account.")
                else:
                    response = f"📋 Your Channels ({len(channels)}):\n\n"
                    for i, channel in enumerate(channels, 1):
                        channel_name = channel.get('channel_name', 'Unknown')
                        added_at = channel.get('added_at', 'Unknown date')
                        response += f"{i}. {channel_name}\n   📅 Added: {added_at}\n\n"
                    await query.message.reply_text(response)
            else:
                await query.message.reply_text("❌ No user data found. Please add a channel first!")

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

    if chat_type == 'private':
        # Handle store message
        if user_id in user_data and user_data[user_id].get("awaiting_store_mssg"):
            text_to_store = update.message.text.strip()
            success, error = await store_message_for_user(user_id, text_to_store)
            user_data[user_id]["awaiting_store_mssg"] = False

            if success:
                await update.message.reply_text("✅ Message stored successfully!")
            else:
                await update.message.reply_text(f"❌ Error storing message: {error}")
            return

        # Handle immediate message sending
        if user_id in user_data and user_data[user_id].get("awaiting_send_mssg"):
            user_data[user_id]["awaiting_send_mssg"] = False
            if text.lower() == "confirm":
                await send_stored_messages(update, context, user_id)
            else:
                await update.message.reply_text("❌ Send cancelled. Type 'confirm' to send messages.")
            return

        # Handle scheduling time input
        if user_id in user_data and user_data[user_id].get("awaiting_schedule_time"):
            try:
                # Parse the datetime
                schedule_time = datetime.strptime(text, "%Y-%m-%d %H:%M")

                # Check if the time is in the future
                if schedule_time <= datetime.now():
                    await update.message.reply_text("❌ Please enter a future date and time!")
                    return

                user_data[user_id]["schedule_time"] = schedule_time
                user_data[user_id]["awaiting_schedule_time"] = False
                user_data[user_id]["awaiting_schedule_message"] = True

                await update.message.reply_text(
                    f"⏰ Scheduled for: {schedule_time.strftime('%Y-%m-%d %H:%M')}\n\n"
                    "Now send me the message you want to schedule:"
                )
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid format! Please use: YYYY-MM-DD HH:MM\n"
                    "Example: 2024-12-25 14:30"
                )
            return

        # Handle scheduled message content
        if user_id in user_data and user_data[user_id].get("awaiting_schedule_message"):
            schedule_time = user_data[user_id]["schedule_time"]
            user_data[user_id]["awaiting_schedule_message"] = False

            try:
                # Schedule the message
                scheduler.add_job(
                    send_scheduled_message,
                    DateTrigger(run_date=schedule_time),
                    args=[context.bot, user_id, text],
                    id=f"scheduled_msg_{user_id}_{int(schedule_time.timestamp())}"
                )

                # Save scheduled message to database
                db.collection("scheduled_messages").add({
                    "user_id": user_id,
                    "message": text,
                    "scheduled_time": schedule_time,
                    "created_at": datetime.now()
                })

                await update.message.reply_text(
                    f"✅ Message scheduled successfully!\n\n"
                    f"📅 Date: {schedule_time.strftime('%Y-%m-%d')}\n"
                    f"⏰ Time: {schedule_time.strftime('%H:%M')}\n"
                    f"📝 Message: {text[:50]}{'...' if len(text) > 50 else ''}"
                )
            except Exception as e:
                await update.message.reply_text(f"❌ Error scheduling message: {e}")
            return

        # Step 1: Name input
        if user_id in user_data and user_data[user_id].get("awaiting_name"):
            user_data[user_id]["name"] = text
            user_data[user_id]["awaiting_name"] = False
            user_data[user_id]["awaiting_channel_name"] = True
            await update.message.reply_text(f"Thanks {text}! Now, please enter your channel username (e.g., @channelname):")
            return

        # Step 2: Channel username input
        if user_id in user_data and user_data[user_id].get("awaiting_channel_name"):
            # User is sending the channel username now
            await add_channel_for_user(update, context, user_data, user_id, text)
            return

        # Default response
        await update.message.reply_text("Please click a button first to start an action.")

# Command to show scheduled messages
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

async def show_scheduled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        docs = db.collection("scheduled_messages").where("user_id", "==", user_id).stream()
        scheduled_messages = [doc.to_dict() for doc in docs]

        if not scheduled_messages:
            await update.message.reply_text("📭 No scheduled messages found.")
        else:
            response = "📅 Your Scheduled Messages:\n\n"
            for i, msg in enumerate(scheduled_messages, 1):
                schedule_time = msg['scheduled_time']
                message_preview = msg['message'][:30] + "..." if len(msg['message']) > 30 else msg['message']
                response += f"{i}. 📅 {schedule_time.strftime('%Y-%m-%d %H:%M')}\n   📝 {message_preview}\n\n"
            await update.message.reply_text(response)
    except Exception as e:
        await update.message.reply_text(f"❌ Error fetching scheduled messages: {e}")

# Main function
async def main():
    # Start the scheduler after asyncio loop is running
    scheduler.start()

    app = ApplicationBuilder().token(Token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scheduled", show_scheduled))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

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
