"""Auto-execution handler for AutoLeech Settings"""

from .. import LOGGER, user_data
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.links_utils import is_url, is_magnet
from ..helper.telegram_helper.filters import CustomFilters
from .mirror_leech import Mirror
from .ytdlp import YtDlp


def parse_auto_flags(flags_str):
    """
    Parse flag string into list of individual flags.
    Supports both space and comma separation.
    
    Args:
        flags_str: String containing flags (e.g., "-n hi -ss 10" or "-n hi, -ss 10")
    
    Returns:
        List of flags
    """
    if not flags_str:
        return []
    
    # Replace commas with spaces for uniform parsing
    flags_str = flags_str.replace(",", " ")
    
    # Split by space and filter empty strings
    return [f.strip() for f in flags_str.split() if f.strip()]


def merge_flags(*flag_lists):
    """
    Merge multiple flag lists into single string.
    Later flags override earlier ones.
    
    Args:
        *flag_lists: Variable number of flag lists
    
    Returns:
        Merged flag string
    """
    merged = []
    flag_dict = {}
    
    for flag_list in flag_lists:
        if not flag_list:
            continue
        
        i = 0
        while i < len(flag_list):
            flag = flag_list[i]
            
            # Check if this is a flag (starts with -)
            if flag.startswith("-"):
                # Check if next item is a value (doesn't start with -)
                if i + 1 < len(flag_list) and not flag_list[i + 1].startswith("-"):
                    flag_dict[flag] = flag_list[i + 1]
                    i += 2
                else:
                    flag_dict[flag] = None
                    i += 1
            else:
                i += 1
    
    # Build merged string
    for flag, value in flag_dict.items():
        merged.append(flag)
        if value is not None:
            merged.append(value)
    
    return " ".join(merged)


def should_auto_execute(message):
    """
    Check if message should trigger auto-execution.
    
    Args:
        message: Telegram message object
    
    Returns:
        bool: True if should auto-execute
    """
    # Don't auto-execute if it's a command
    if message.text and message.text.startswith("/"):
        return False
    
    # Check if message contains link, file, or media
    has_link = message.text and (is_url(message.text.split()[0]) or is_magnet(message.text.split()[0]))
    has_file = bool(
        message.document
        or message.photo
        or message.video
        or message.audio
        or message.voice
        or message.video_note
        or message.sticker
        or message.animation
    )
    
    return has_link or has_file




class FakeCommandMessage:
    """
    Wrapper class that mimics a command message while delegating
    all method calls to the original message object.
    """
    def __init__(self, original_message, command_text):
        self._original = original_message
        self.text = command_text
        self.command = command_text.split()
        
    def __getattr__(self, name):
        """Delegate all other attributes to the original message"""
        return getattr(self._original, name)


@new_task
async def auto_command_handler(client, message):
    """
    Main handler for automatic command execution.
    Checks user settings and triggers appropriate command.
    """
    user_id = message.from_user.id
    user_dict = user_data.get(user_id, {})
    
    # Check if should auto-execute
    if not should_auto_execute(message):
        return
    
    # Get AutoLeech settings
    auto_leech = user_dict.get("AUTO_LEECH", False)
    auto_mirror = user_dict.get("AUTO_MIRROR", False)
    auto_yl = user_dict.get("AUTO_YL", False)
    auto_ffmpeg = user_dict.get("AUTO_FFMPEG", False)
    auto_flags = user_dict.get("AUTO_FLAGS", False)
    
    # Determine which auto mode to use (priority: AutoYL > AutoLeech > AutoMirror)
    command = None
    is_leech = False
    is_ytdl = False
    
    if auto_yl:
        command = "/yl"
        is_leech = True
        is_ytdl = True
    elif auto_leech:
        command = "/leech"
        is_leech = True
    elif auto_mirror:
        command = "/mirror"
    
    # If no auto mode is enabled, return
    if not command:
        return
    
    # Build flags
    flag_lists = []
    
    # Add AutoMirror flags
    if auto_mirror and user_dict.get("AUTO_MIRROR_FLAGS"):
        mirror_flags = parse_auto_flags(user_dict["AUTO_MIRROR_FLAGS"])
        flag_lists.append(mirror_flags)
    
    # Add AutoFFmpeg flags (works with leech and ytdl)
    if (is_leech or is_ytdl) and auto_ffmpeg and user_dict.get("AUTO_FFMPEG_FLAGS"):
        ffmpeg_flags = parse_auto_flags(user_dict["AUTO_FFMPEG_FLAGS"])
        flag_lists.append(ffmpeg_flags)
    
    # Add AutoFlags
    if auto_flags and user_dict.get("AUTO_FLAGS_VALUE"):
        auto_flag_values = parse_auto_flags(user_dict["AUTO_FLAGS_VALUE"])
        flag_lists.append(auto_flag_values)
    
    # Merge all flags
    merged_flags = merge_flags(*flag_lists)
    
    # Extract link/file from message
    link = ""
    if message.text:
        link = message.text.split()[0]
    
    # Build command string
    command_str = f"{command} {link} {merged_flags}".strip()
    
    # Create fake command message that wraps the original
    fake_message = FakeCommandMessage(message, command_str)
    
    # Execute appropriate command
    try:
        if is_ytdl:
            await YtDlp(client, fake_message, is_leech=True).new_event()
        else:
            await Mirror(client, fake_message, is_leech=is_leech).new_event()
    except Exception as e:
        LOGGER.error(f"Auto-execution error: {e}")

