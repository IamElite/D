from re import match as re_match

from .. import bot_loop, user_data
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.links_utils import is_url


def _get_auto_flags(user_dict):
    """Merge AutoFFmpeg, AutoFlags, and AutoMirror flags into a single string."""
    parts = []
    if user_dict.get("AUTO_FFMPEG") and user_dict.get("AUTO_FFMPEG_FLAGS"):
        val = user_dict["AUTO_FFMPEG_FLAGS"].strip()
        if not val.startswith("-ff"):
            val = f"-ff {val}"
        parts.append(val)
    if user_dict.get("AUTO_FLAGS") and user_dict.get("AUTO_FLAGS_VALUE"):
        raw = user_dict["AUTO_FLAGS_VALUE"].strip()
        # Normalize: strip surrounding parentheses and commas
        raw = raw.strip("()")
        raw = raw.replace(",", " ")
        parts.append(raw)
    if user_dict.get("AUTO_MIRROR") and user_dict.get("AUTO_MIRROR_FLAGS"):
        val = user_dict["AUTO_MIRROR_FLAGS"].strip()
        parts.append(val)
    return " ".join(parts)


@new_task
async def auto_task_handler(client, message):
    # Skip commands
    if message.text and message.text.startswith("/"):
        return
    if not message.from_user:
        return

    user_id = message.from_user.id
    user_dict = user_data.get(user_id, {})

    auto_yl = user_dict.get("AUTO_YL", False)
    auto_leech = user_dict.get("AUTO_LEECH", False)
    auto_mirror = user_dict.get("AUTO_MIRROR", False)

    if not any([auto_yl, auto_leech, auto_mirror]):
        return

    # Detect content
    link = ""
    has_media = bool(
        message.document
        or message.photo
        or message.video
        or message.audio
        or message.voice
        or message.video_note
        or message.sticker
        or message.animation
    )

    if message.text:
        # Extract first URL from text
        for word in message.text.split():
            if is_url(word):
                link = word
                break
        if not link and not has_media:
            return
    elif not has_media:
        return

    # Build merged flags
    extra_flags = _get_auto_flags(user_dict)

    # Determine action by priority: AutoYL > AutoLeech > AutoMirror
    if auto_yl and link:
        # Check if it looks like a ytdl-supported link
        cmd = "yl"
        is_leech = True
        is_ytdlp = True
    elif auto_leech:
        cmd = "leech"
        is_leech = True
        is_ytdlp = False
    elif auto_mirror:
        cmd = "mirror"
        is_leech = False
        is_ytdlp = False
    else:
        return

    # Build synthetic command text for the existing parsers
    cmd_text = f"/{cmd}"
    if link:
        cmd_text += f" {link}"
    if extra_flags:
        cmd_text += f" {extra_flags}"

    # Patch message text to look like a real command
    message.text = cmd_text

    if is_ytdlp:
        from .ytdlp import YtDlp

        bot_loop.create_task(YtDlp(client, message, is_leech=is_leech).new_event())
    else:
        from .mirror_leech import Mirror

        bot_loop.create_task(
            Mirror(client, message, is_leech=is_leech).new_event()
        )
