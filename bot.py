import logging
import json
import os
import subprocess
import asyncio
import threading
import streamlit as st

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError

# --- Configuration ---
# Secrets are now fetched from Streamlit's secrets manager
CONFIG_FILE = 'bot_config.json'
BOT_APP_CONFIG = {}
DELAY_BOT_SEND = 1.5

# --- Logging ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Config Loading ---
# This function is now cached by Streamlit to avoid rereading the file on every interaction
@st.cache_data
def load_bot_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        if 'menus' not in config or 'actions' not in config:
            st.error(f"'{CONFIG_FILE}' is missing 'menus' or 'actions' keys.")
            return {}
        logger.info(f"Loaded bot configuration from '{CONFIG_FILE}'.")
        return config
    except Exception as e:
        st.error(f"Error loading '{CONFIG_FILE}': {e}")
        return {}

# --- Helper function to generate keyboards ---
def generate_keyboard_for_menu(menu_id: str) -> InlineKeyboardMarkup:
    menu_items = BOT_APP_CONFIG.get('menus', {}).get(menu_id, [])
    if not menu_items and menu_id != "root":
        return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="navigate:root")]])
    elif not menu_items and menu_id == "root":
        return InlineKeyboardMarkup([[InlineKeyboardButton("Configuration error.", callback_data="noop")]])

    keyboard = []
    for item in menu_items:
        keyboard.append([InlineKeyboardButton(item["button_label"], callback_data=item["callback_data"])])
    return InlineKeyboardMarkup(keyboard)

# --- Command, Button, and Message Handlers (Your Original Logic) ---
# NOTE: All your async functions (start_command, button_handler, etc.) remain exactly the same as in your original file.
# I am including them here for completeness.

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"User {user.username} (ID: {user.id}) started the bot.")

    if not BOT_APP_CONFIG or 'root' not in BOT_APP_CONFIG.get('menus', {}):
        await update.message.reply_text("Bot configuration is incomplete. Please contact the admin.")
        return

    keyboard = generate_keyboard_for_menu("root")
    await update.message.reply_html(
        rf"Hi {user.mention_html()}! Please choose an option:",
        reply_markup=keyboard
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    callback_data_str = query.data
    if callback_data_str == "noop":
        return

    user = query.from_user
    end_user_chat_id = str(query.message.chat_id)
    logger.info(f"User {user.id} clicked '{callback_data_str}'.")

    try:
        action_type, key = callback_data_str.split(":", 1)
    except ValueError:
        logger.warning(f"Invalid callback_data format: {callback_data_str}")
        await query.edit_message_text(text="⚠️ Invalid option selected.")
        return

    if action_type == "navigate":
        menu_display_name = key.replace("_submenu", "").replace("_", " ").title()
        if key == "root":
            menu_display_name = "Main Menu"

        new_keyboard = generate_keyboard_for_menu(key)
        try:
            await query.edit_message_text(
                text=f"📜 {menu_display_name}\nSelect an option:",
                reply_markup=new_keyboard,
                parse_mode='HTML'
            )
        except TelegramError as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Error editing message for navigation: {e}")

    elif action_type == "action":
        action_config = BOT_APP_CONFIG.get('actions', {}).get(key)
        if not action_config:
            logger.error(f"Action key '{key}' not found in configuration.")
            await query.edit_message_text(text="⚠️ Selected action is not configured.")
            return

        current_button_label = action_config.get("button_label", "the requested content")
        context.bot_data[f"last_button_for_{end_user_chat_id}"] = current_button_label

        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
        if not bot_username:
            logger.error("Bot requires a username!")
            await query.edit_message_text(text="⚠️ Bot error: I need a username.")
            return

        await query.edit_message_text(text=f"⏳ Requesting: {current_button_label}...\nHelper account will process and send items.")

        private_channel_id = action_config["private_channel_id"]
        messages_identifier = action_config["messages_identifier"]
        logger.info(f"Calling forwarder.py: Chan='{private_channel_id}', IDN='{messages_identifier}', TargetBot='@{bot_username}', ForUser='{end_user_chat_id}'")

        try:
            forwarder_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'forwarder.py')
            process = subprocess.run(
                [st.secrets["PYTHON_EXECUTABLE"], forwarder_script_path,
                 private_channel_id, messages_identifier, bot_username, end_user_chat_id],
                capture_output=True, text=True, check=False, timeout=600
            )

            stdout_data = process.stdout.strip()
            stderr_data = process.stderr.strip()
            logger.info(f"Forwarder stdout: {stdout_data}")
            if stderr_data: logger.error(f"Forwarder stderr: {stderr_data}")

            user_facing_message = f"Task for '{current_button_label}' has been processed."
            try:
                response_json = json.loads(stdout_data)
                if isinstance(response_json, dict):
                    message_from_fwd = response_json.get("message", "No specific status.")
                    if response_json.get("status") == "error":
                        user_facing_message = f"⚠️ Error: {message_from_fwd[:200]}"
                    elif "count_sent_to_bot" in response_json:
                        total_found = response_json.get("total_found", 0)
                        if total_found == 0:
                            user_facing_message = f"ℹ️ No messages found for '{current_button_label}'."
                        else:
                            user_facing_message = f"Helper has initiated transfer of {total_found} items. I will relay them shortly."
            except (json.JSONDecodeError, AttributeError):
                user_facing_message = "Helper script finished, but status is unclear."
                if process.returncode != 0:
                    output_to_show = stderr_data if stderr_data else stdout_data or "Unknown error."
                    user_facing_message = f"⚠️ Error processing request: {output_to_show[:300]}"

            await query.edit_message_text(text=user_facing_message)

        except subprocess.TimeoutExpired:
            logger.error(f"Forwarder script timed out for action '{key}'.")
            await context.bot.send_message(chat_id=end_user_chat_id, text=f"⏳ Helper script for '{current_button_label}' timed out.")
        except Exception as e:
            logger.error(f"Error in button_handler for action {key}: {e}", exc_info=True)
            await context.bot.send_message(chat_id=end_user_chat_id, text="🚨 Unexpected bot error.")

async def xercese_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # THIS ENTIRE FUNCTION IS IDENTICAL TO YOURS.
    # It has been omitted for brevity but should be copied from your original file.
    # ... (copy your full xercese_message_handler function here) ...
    pass # Placeholder for the copied function


# --- Streamlit Application and Bot Startup Logic ---

@st.cache_resource
def start_bot():
    """Initializes and runs the bot in a background thread."""
    # Ensure bot config is loaded
    global BOT_APP_CONFIG
    BOT_APP_CONFIG = load_bot_config()
    if not BOT_APP_CONFIG:
        st.error("Bot configuration failed to load. The bot cannot start.")
        return None

    # Get the Python executable path for the subprocess
    st.secrets["PYTHON_EXECUTABLE"] = os.sys.executable

    # Build the application
    application = Application.builder().token(st.secrets["BOT_TOKEN"]).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    xercese_filter = filters.User(user_id=int(st.secrets["XERCESE_USER_ID"]))
    application.add_handler(MessageHandler(xercese_filter & (~filters.COMMAND), xercese_message_handler))

    # Define the function that will run in the thread
    def run_bot():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(application.run_polling(allowed_updates=Update.ALL_TYPES))

    # Start the bot in a daemon thread
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    logger.info("Bot has been started in a background thread.")
    
    return application

# --- Streamlit UI ---
st.set_page_config(page_title="Bot Control Panel", page_icon="🤖")
st.title("🤖 Bot Control Panel")

st.info("This panel ensures the Telegram bot process is running on Streamlit Cloud.")

# Check for necessary secrets
if "BOT_TOKEN" not in st.secrets or "XERCESE_USER_ID" not in st.secrets:
    st.error("Essential secrets (BOT_TOKEN, XERCESE_USER_ID) are missing. Please configure them in Streamlit Cloud.")
else:
    # Start the bot
    app = start_bot()

    if app:
        st.success("Bot process has been started successfully.")
        st.write("The bot is now active and listening for messages in the background.")
        
        # Display bot info as a check
        try:
            # We need to run async code in Streamlit's main thread carefully
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            bot_info = loop.run_until_complete(app.bot.get_me())
            st.json({
                "Bot Name": bot_info.first_name,
                "Username": f"@{bot_info.username}",
                "User ID": bot_info.id
            })
        except Exception as e:
            st.error(f"Could not fetch bot info. The bot might still be running. Error: {e}")
