from bot import LOGGER, user_data
from bot.helper.ext_utils.links_utils import (
    is_gdrive_id,
    is_gdrive_link,
    is_magnet,
    is_mega_link,
    is_rclone_path,
    is_telegram_link,
    is_url,
)
from bot.modules.mirror_leech import leech, mirror
from bot.modules.ytdlp import ytdl_leech


class AutoMessage:
    def __init__(self, original_message, command_text):
        self._msg = original_message
        self.text = command_text
        self.reply_to_message = original_message

    def __getattr__(self, name):
        return getattr(self._msg, name)


async def auto_leech_handler(client, message):
    user_id = message.from_user.id
    user_dict = user_data.get(user_id, {})

    # Check if any Auto setting is enabled
    if not any(
        user_dict.get(k) for k in ["AUTO_LEECH", "AUTO_MIRROR", "AUTO_YTDL"]
    ):
        return

    text = message.text or message.caption or ""
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    is_media = bool(
        message.document
        or message.photo
        or message.video
        or message.audio
        or message.voice
    )

    if not lines and not is_media:
        return

    # If it's media, we treat the whole caption as one task if not multi-line
    # If multi-line text/caption, we process each line
    for line in lines or [""]:
        # If media and first line, 'line' might be the caption
        # We need to check if this specific line has a link
        first_word = line.split(maxsplit=1)[0] if line else ""
        line_is_link = (
            is_url(first_word)
            or is_magnet(first_word)
            or is_rclone_path(first_word)
            or is_gdrive_link(first_word)
            or is_mega_link(first_word)
            or is_gdrive_id(first_word)
            or is_telegram_link(first_word)
        )

        if not line_is_link and not (is_media and (not lines or line == lines[0])):
            continue

        # Determine mode (Priority: YTDL > Leech > Mirror)
        mode = None
        cmd = ""

        if user_dict.get("AUTO_YTDL") and line_is_link:
            mode = "ytdl"
            cmd = "/yl"
        elif user_dict.get("AUTO_LEECH"):
            mode = "leech"
            cmd = "/leech"
        elif user_dict.get("AUTO_MIRROR"):
            mode = "mirror"
            cmd = "/mirror"

        if not mode:
            continue

        # Helper to append flags
        flags = []

        # AutoFlags
        if user_dict.get("AUTO_FLAGS") and user_dict.get("AUTO_FLAGS_VALUE"):
            flags.append(user_dict["AUTO_FLAGS_VALUE"])

        # AutoFFmpeg
        if user_dict.get("AUTO_FFMPEG") and user_dict.get("AUTO_FFMPEG_FLAGS"):
            flags.append(user_dict["AUTO_FFMPEG_FLAGS"])

        # AutoMirror Flags (Only for Mirror)
        if mode == "mirror" and user_dict.get("AUTO_MIRROR_FLAGS"):
            flags.append(user_dict["AUTO_MIRROR_FLAGS"])

        full_cmd = f"{cmd} {' '.join(flags)} {line}".strip()
        while "  " in full_cmd:
            full_cmd = full_cmd.replace("  ", " ")

        # Create Mock Message
        mock_msg = AutoMessage(message, full_cmd)

        LOGGER.info(f"AutoLeech Triggered for User {user_id}: {full_cmd}")

        if mode == "ytdl":
            await ytdl_leech(client, mock_msg)
        elif mode == "leech":
            await leech(client, mock_msg)
        elif mode == "mirror":
            await mirror(client, mock_msg)
