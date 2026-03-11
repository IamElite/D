import random
from time import time

from bot import LOGGER, bot_loop, user_data
from bot.helper.ext_utils.links_utils import (
    is_gdrive_id,
    is_gdrive_link,
    is_magnet,
    is_mega_link,
    is_rclone_path,
    is_telegram_link,
    is_url,
)
from bot.modules.mirror_leech import Mirror, leech, mirror
from bot.modules.ytdlp import YtDlp, ytdl_leech
from bot.helper.telegram_helper.message_utils import send_message, delete_message
from bot.helper.ext_utils.db_handler import database
from bot.helper.ext_utils.bot_utils import update_user_ldata
from bot.helper.ext_utils.media_utils import create_thumb


class AutoMessage:
    def __init__(self, original_message, command_text):
        self._msg = original_message
        self.text = command_text
        self.reply_to_message = None
        self.id = original_message.id + int(time() * 1000) + random.randint(100, 10000000)

    def __getattr__(self, name):
        return getattr(self._msg, name)


def _check_link(line):
    first = line.split()[0] if line.split() else ""
    return (
        is_url(first)
        or is_magnet(first)
        or is_rclone_path(first)
        or is_gdrive_link(first)
        or is_mega_link(first)
        or is_gdrive_id(first)
        or is_telegram_link(first)
    )


async def auto_leech_handler(client, message):
    user_id = message.from_user.id
    user_dict = user_data.get(user_id, {})

    if not any(
        user_dict.get(k) for k in ["AUTO_LEECH", "AUTO_MIRROR", "AUTO_YTDL", "AUTO_THUMB"]
    ) and user_dict.get("AUTO_THUMB", False) is False: # Check if all are false (AutoThumb defaults to False)
        return

    # Auto Thumb
    if user_dict.get("AUTO_THUMB", False) and message.photo:
         path = await create_thumb(message, user_id)
         update_user_ldata(user_id, "THUMBNAIL", path)
         await database.update_user_doc(user_id, "THUMBNAIL", path)
         
         from bot.modules.users_settings import get_menu
         await get_menu("THUMBNAIL", message, user_id, edit_mode=False)
         return 

    text = message.text or message.caption or ""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    if not lines:
        return

    is_media = (
        message.document
        or message.photo
        or message.video
        or message.audio
        or message.voice
    )

    valid_lines = [l for l in lines if _check_link(l)]

    if not valid_lines and not is_media:
        return

    # Auto Mode Filter
    auto_mode = user_dict.get("AUTO_MODE", "All")
    if message.sticker or message.animation:
        return

    is_video = message.video or (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("video")
    )
    is_audio = (
        message.audio
        or message.voice
        or (
            message.document
            and message.document.mime_type
            and message.document.mime_type.startswith("audio")
        )
    )

    if auto_mode == "Links" and not valid_lines:
        return
    elif auto_mode == "Video" and not is_video:
        return
    elif auto_mode == "Audio" and not is_audio:
        return
    elif auto_mode == "All" and not valid_lines and not is_video and not is_audio:
        return

    # Determine mode (Priority: YTDL > Leech > Mirror)
    mode = None
    cmd = ""
    has_links = bool(valid_lines)

    if user_dict.get("AUTO_YTDL") and has_links:
        mode = "ytdl"
        cmd = "/yl"
    elif user_dict.get("AUTO_LEECH"):
        mode = "leech"
        cmd = "/leech"
    elif user_dict.get("AUTO_MIRROR"):
        mode = "mirror"
        cmd = "/mirror"

    if not mode:
        return

    # Build auto flags from settings
    auto_flags = []
    if user_dict.get("AUTO_FLAGS") and user_dict.get("AUTO_FLAGS_VALUE"):
        auto_flags.append(user_dict["AUTO_FLAGS_VALUE"])
    if user_dict.get("AUTO_FFMPEG") and user_dict.get("AUTO_FFMPEG_FLAGS"):
        auto_flags.append(user_dict["AUTO_FFMPEG_FLAGS"])
    if mode == "mirror" and user_dict.get("AUTO_MIRROR_FLAGS"):
        auto_flags.append(user_dict["AUTO_MIRROR_FLAGS"])

    flags_str = " ".join(auto_flags).strip()

    if is_media and not valid_lines:
        full_cmd = f"{cmd} {flags_str}".strip()
        mock_msg = AutoMessage(message, full_cmd)
        mock_msg.reply_to_message = message
        LOGGER.info(f"AutoLeech [{user_id}]: {full_cmd} (media)")
        if mode == "leech":
            bot_loop.create_task(leech(client, mock_msg))
        elif mode == "mirror":
            bot_loop.create_task(mirror(client, mock_msg))
        return

    if len(valid_lines) == 1:
        # Single link
        full_cmd = f"{cmd} {valid_lines[0]} {flags_str}".strip()
        while "  " in full_cmd:
            full_cmd = full_cmd.replace("  ", " ")
        mock_msg = AutoMessage(message, full_cmd)
        LOGGER.info(f"AutoLeech [{user_id}]: {full_cmd}")
        if mode == "ytdl":
            bot_loop.create_task(ytdl_leech(client, mock_msg))
        elif mode == "leech":
            bot_loop.create_task(leech(client, mock_msg))
        elif mode == "mirror":
            bot_loop.create_task(mirror(client, mock_msg))
        return

    # Multi-link: use init_bulk pattern
    # Build first command: /cmd first_line_flags first_link -i total options
    # Pass remaining lines as bulk list for run_multi to consume sequentially
    total = len(valid_lines)
    first_line = valid_lines[0]

    full_cmd = f"{cmd} {first_line} {flags_str} -i {total}".strip()
    while "  " in full_cmd:
        full_cmd = full_cmd.replace("  ", " ")

    # Send as real message so run_multi can pick it up
    nextmsg = await send_message(message, full_cmd)
    nextmsg = await client.get_messages(
        chat_id=message.chat.id, message_ids=nextmsg.id
    )
    if message.from_user:
        nextmsg.from_user = message.from_user
    else:
        nextmsg.sender_chat = message.sender_chat

    LOGGER.info(f"AutoLeech [{user_id}]: bulk {total} links")

    if mode == "ytdl":
        bot_loop.create_task(
            YtDlp(client, nextmsg, is_leech=True, bulk=valid_lines, options=flags_str).new_event()
        )
    elif mode == "leech":
        bot_loop.create_task(
            Mirror(client, nextmsg, is_leech=True, bulk=valid_lines, options=flags_str).new_event()
        )
    elif mode == "mirror":
        bot_loop.create_task(
            Mirror(client, nextmsg, bulk=valid_lines, options=flags_str).new_event()
        )
