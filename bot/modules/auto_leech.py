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
from bot.modules.mirror_leech import leech, mirror
from bot.modules.ytdlp import ytdl_leech


class AutoMessage:
    def __init__(self, original_message, command_text):
        self._msg = original_message
        self.text = command_text
        self.reply_to_message = None

    def __getattr__(self, name):
        return getattr(self._msg, name)


def _check_link(line):
    """Check if the first word of a line is a valid link."""
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


async def _process_line(client, line, mode, cmd, auto_flags, user_id):
    """Process a single line as a task."""
    full_cmd = f"{cmd} {' '.join(auto_flags)} {line}".strip()
    while "  " in full_cmd:
        full_cmd = full_cmd.replace("  ", " ")

    mock_msg = AutoMessage(client._msg_ref, full_cmd)
    LOGGER.info(f"AutoLeech [{user_id}]: {full_cmd}")

    if mode == "ytdl":
        await ytdl_leech(client, mock_msg)
    elif mode == "leech":
        await leech(client, mock_msg)
    elif mode == "mirror":
        await mirror(client, mock_msg)


async def auto_leech_handler(client, message):
    user_id = message.from_user.id
    user_dict = user_data.get(user_id, {})

    if not any(
        user_dict.get(k) for k in ["AUTO_LEECH", "AUTO_MIRROR", "AUTO_YTDL"]
    ):
        return

    text = message.text or message.caption or ""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    if not lines:
        return

    # Check if at least one line has a valid link or message has media
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

    # Build auto flags
    auto_flags = []
    if user_dict.get("AUTO_FLAGS") and user_dict.get("AUTO_FLAGS_VALUE"):
        auto_flags.append(user_dict["AUTO_FLAGS_VALUE"])
    if user_dict.get("AUTO_FFMPEG") and user_dict.get("AUTO_FFMPEG_FLAGS"):
        auto_flags.append(user_dict["AUTO_FFMPEG_FLAGS"])
    if mode == "mirror" and user_dict.get("AUTO_MIRROR_FLAGS"):
        auto_flags.append(user_dict["AUTO_MIRROR_FLAGS"])

    # Store message ref for AutoMessage
    client._msg_ref = message

    if is_media and not valid_lines:
        # Media without links — single task with just cmd + flags
        full_cmd = f"{cmd} {' '.join(auto_flags)}".strip()
        mock_msg = AutoMessage(message, full_cmd)
        mock_msg.reply_to_message = message
        LOGGER.info(f"AutoLeech [{user_id}]: {full_cmd} (media)")
        if mode == "leech":
            bot_loop.create_task(leech(client, mock_msg))
        elif mode == "mirror":
            bot_loop.create_task(mirror(client, mock_msg))
        return

    # Process each valid line as a separate task (bulk style)
    for line in valid_lines:
        full_cmd = f"{cmd} {' '.join(auto_flags)} {line}".strip()
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
