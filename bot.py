# In bot.py

# ... (other parts of bot.py remain the same as previously corrected) ...

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
        bot_username = bot_info.username # This is typically @YourBotUsername
        if not bot_username:
            logger.error("Bot requires a username!")
            await query.edit_message_text(text="⚠️ Bot error: I need a username.")
            return

        await query.edit_message_text(text=f"⏳ Requesting: {current_button_label}...\nHelper account will process and send items.")

        private_channel_id = action_config["private_channel_id"]
        messages_identifier = action_config["messages_identifier"]
        
        # Log before calling the subprocess
        logger.info(f"Preparing to call forwarder.py: Chan='{private_channel_id}', IDN='{messages_identifier}', TargetBot='{bot_username}', ForUser='{end_user_chat_id}'")

        try:
            # Retrieve Telethon API credentials from Streamlit secrets
            telethon_api_id = st.secrets.get("TELETHON_API_ID")
            telethon_api_hash = st.secrets.get("TELETHON_API_HASH")

            if not telethon_api_id or not telethon_api_hash:
                logger.error("Telethon API ID or Hash is missing from secrets.")
                await query.edit_message_text(text="⚠️ Bot configuration error: Missing API credentials for helper script.")
                return

            forwarder_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'forwarder.py')
            
            process_args = [
                PYTHON_EXECUTABLE_PATH,
                forwarder_script_path,
                str(telethon_api_id),    # api_id_arg
                telethon_api_hash,       # api_hash_arg
                private_channel_id,      # pci_arg
                messages_identifier,     # mi_arg
                bot_username,            # tbu_arg (e.g. @BotUsername)
                end_user_chat_id         # orci_arg
            ]
            
            # Log the arguments being passed to the script, excluding the executable and script path for brevity if needed
            logger.info(f"Calling forwarder.py with arguments (excluding exec/path): {process_args[2:]}")


            process = subprocess.run(
                process_args,
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
            except (json.JSONDecodeError, AttributeError): # Handle cases where stdout is not valid JSON
                logger.warning(f"Forwarder output was not valid JSON or attribute error. stdout: '{stdout_data}', stderr: '{stderr_data}'")
                user_facing_message = "Helper script finished, but status is unclear."
                if process.returncode != 0:
                    output_to_show = stderr_data if stderr_data else stdout_data or "Unknown error."
                    user_facing_message = f"⚠️ Error processing request: {output_to_show[:300]}"
                elif not stdout_data and not stderr_data: # No output, could be an issue
                     user_facing_message = f"Helper script for '{current_button_label}' finished with no output. Please check logs."


            await query.edit_message_text(text=user_facing_message)

        except subprocess.TimeoutExpired:
            logger.error(f"Forwarder script timed out for action '{key}'.")
            # await query.edit_message_text(text=f"⏳ Helper script for '{current_button_label}' timed out.") # Query might be too old
            await context.bot.send_message(chat_id=end_user_chat_id, text=f"⏳ Helper script for '{current_button_label}' timed out.")
        except Exception as e:
            logger.error(f"Error in button_handler for action {key}: {e}", exc_info=True)
            # await query.edit_message_text(text="🚨 Unexpected bot error.") # Query might be too old
            await context.bot.send_message(chat_id=end_user_chat_id, text="🚨 Unexpected bot error.")

# ... (rest of bot.py, including xercese_message_handler, start_bot, and Streamlit UI) ...
