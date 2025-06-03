import asyncio
import sys
import logging
import os
import json
from telethon import TelegramClient
from telethon.tl.types import PeerChannel
from telethon.errors import FloodWaitError

# --- Logging ---
log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'forwarder.log')
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.FileHandler(log_file_path, encoding='utf-8')])
logger = logging.getLogger(__name__)

# --- Constants ---
FETCH_EVERYTHING = "__FETCH_EVERYTHING__"
FORWARD_BATCH_SIZE = 95
DELAY_BETWEEN_BATCHES = 2.0

# --- Helper Functions (Your Original Logic) ---
# NOTE: Your functions get_message_ids_for_forwarding and forward_content_to_bot remain exactly the same.
# I am including them here for completeness.

async def get_message_ids_for_forwarding(client, channel_entity, identifier_str):
    # This entire function is IDENTICAL to yours.
    # ... (copy your full get_message_ids_for_forwarding function here) ...
    pass # Placeholder

async def forward_content_to_bot(client, target_bot_peer, message_ids_to_forward, from_channel_entity):
    # This entire function is IDENTICAL to yours.
    # ... (copy your full forward_content_to_bot function here) ...
    pass # Placeholder


async def main_logic(api_id, api_hash, channel_id, msg_id, bot_user, req_id):
    client = TelegramClient('my_user_session', api_id, api_hash)
    count_forwarded = 0
    expected_count = 0
    
    try:
        await client.start()
        logger.info("Client connected and authorized.")

        from_channel = await client.get_entity(channel_id)
        target_bot = await client.get_entity(bot_user)

        message_ids = await get_message_ids_for_forwarding(client, from_channel, msg_id)
        expected_count = len(message_ids)

        # Send START control message
        await client.send_message(target_bot, f"CONTROL_TASK_START:{req_id}:{expected_count}")
        await asyncio.sleep(0.5)

        if message_ids:
            count_forwarded = await forward_content_to_bot(client, target_bot, message_ids, from_channel)

        # Send END control message
        await client.send_message(target_bot, f"CONTROL_TASK_END:{req_id}:{count_forwarded}")

        print(json.dumps({
            "status": "success",
            "message": f"Task initiated. Forwarded {count_forwarded}/{expected_count} items.",
            "count_sent_to_bot": count_forwarded,
            "total_found": expected_count
        }))

    except Exception as e:
        logger.error(f"Error in forwarder main_logic: {e}", exc_info=True)
        print(json.dumps({
            "status": "error", "message": f"Forwarder script failed: {e}",
            "count_sent_to_bot": count_forwarded, "total_found": expected_count
        }))
    finally:
        if client.is_connected():
            await client.disconnect()

if __name__ == "__main__":
    if len(sys.argv) != 7:
        print(json.dumps({"status": "error", "message": "Incorrect number of arguments."}))
        sys.exit(1)

    # Arguments are now passed from bot.py using st.secrets
    api_id_arg, api_hash_arg, pci_arg, mi_arg, tbu_arg, orci_arg = sys.argv[1:7]
    
    try:
        asyncio.run(main_logic(int(api_id_arg), api_hash_arg, pci_arg, mi_arg, tbu_arg, orci_arg))
    except Exception as e_run:
        logger.error(f"Critical exception in forwarder execution: {e_run}", exc_info=True)
        print(json.dumps({"status": "error", "message": f"Forwarder execution error: {e_run}"}))
        sys.exit(1)
