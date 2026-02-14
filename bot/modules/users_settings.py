from asyncio import sleep
from functools import partial
from html import escape
from io import BytesIO
from os import getcwd, path as ospath
from re import sub
from time import time

from aiofiles.os import makedirs, remove
from aiofiles.os import path as aiopath
from langcodes import Language
from pyrogram.filters import create
from pyrogram.handlers import MessageHandler

from bot.helper.ext_utils.status_utils import get_readable_file_size

from .. import LOGGER, auth_chats, excluded_extensions, sudo_users, user_data
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import (
    get_size_bytes,
    new_task,
    update_user_ldata,
)
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.media_utils import create_thumb
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_file,
    send_message,
)

handler_dict = {}

leech_options = [
    "THUMBNAIL",
    "LEECH_SPLIT_SIZE",
    "LEECH_DUMP_CHAT",
    "LEECH_PREFIX",
    "LEECH_SUFFIX",
    "LEECH_CAPTION",
    "THUMBNAIL_LAYOUT",
    "METADATA_KEY",
]
rclone_options = ["RCLONE_CONFIG", "RCLONE_PATH", "RCLONE_FLAGS"]
gdrive_options = ["TOKEN_PICKLE", "GDRIVE_ID", "INDEX_URL"]
ffset_options = ["FFMPEG_CMDS"]
advanced_options = [
    "EXCLUDED_EXTENSIONS",
    "NAME_SWAP",
    "YT_DLP_OPTIONS",
    "UPLOAD_PATHS",
    "USER_COOKIE_FILE",
]
auto_leech_options = ["AUTO_MIRROR_FLAGS", "AUTO_FFMPEG_FLAGS", "AUTO_FLAGS_VALUE", "AUTO_THUMB", "AUTO_MODE"]

user_settings_text = {
    "THUMBNAIL": (
        "Photo or Doc",
        "Custom Thumbnail is used as the thumbnail for the files you upload to telegram in media or document mode.",
        "<i>Send a photo to save it as custom thumbnail.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_CONFIG": (
        "",
        "",
        "<i>Send your <code>rclone.conf</code> file to use as your Upload Dest to RClone.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "TOKEN_PICKLE": (
        "",
        "",
        "<i>Send your <code>token.pickle</code> to use as your Upload Dest to GDrive</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_SPLIT_SIZE": (
        "",
        "",
        f"Send Leech split size in bytes or use gb or mb. Example: 40000000 or 2.5gb or 1000mb. PREMIUM_USER: {TgClient.IS_PREMIUM_USER}.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_DUMP_CHAT": (
        "",
        "",
        """Send leech destination ID/USERNAME/PM. 
* b:id/@username/pm (b: means leech by bot) (id or username of the chat or write pm means private message so bot will send the files in private to you) when you should use b:(leech by bot)? When your default settings is leech by user and you want to leech by bot for specific task.
* u:id/@username(u: means leech by user) This incase OWNER added USER_STRING_SESSION.
* h:id/@username(hybrid leech) h: to upload files by bot and user based on file size.
* id/@username|topic_id(leech in specific chat and topic) add | without space and write topic id after chat id or username.
╰ <b>Time Left :</b> <code>60 sec</code>""",
    ),
    "LEECH_PREFIX": (
        "",
        "",
        "Send Leech Filename Prefix. You can add HTML tags. Example: <code>@mychannel</code>.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_SUFFIX": (
        "",
        "",
        "Send Leech Filename Suffix. You can add HTML tags. Example: <code>@mychannel</code>.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_CAPTION": (
        "",
        "",
        "Send Leech Caption. You can add HTML tags. Example: <code>@mychannel</code>.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "THUMBNAIL_LAYOUT": (
        "",
        "",
        "Send thumbnail layout (widthxheight, 2x2, 3x3, 2x4, 4x4, ...). Example: 3x3.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_PATH": (
        "",
        "",
        "Send Rclone Path. If you want to use your rclone config edit using owner/user config from usetting or add mrcc: before rclone path. Example mrcc:remote:folder. </i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_FLAGS": (
        "",
        "",
        "key:value|key|key|key:value . Check here all <a href='https://rclone.org/flags/'>RcloneFlags</a>\nEx: --buffer-size:8M|--drive-starred-only",
    ),
    "GDRIVE_ID": (
        "",
        "",
        "Send Gdrive ID. If you want to use your token.pickle edit using owner/user token from usetting or add mtp: before the id. Example: mtp:F435RGGRDXXXXXX . </i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "INDEX_URL": (
        "",
        "",
        "Send Index URL for your gdrive option. </i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "UPLOAD_PATHS": (
        "",
        "",
        "Send Dict of keys that have path values. Example: {'path 1': 'remote:rclonefolder', 'path 2': 'gdrive1 id', 'path 3': 'tg chat id', 'path 4': 'mrcc:remote:', 'path 5': b:@username} . </i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "EXCLUDED_EXTENSIONS": (
        "",
        "",
        "Send exluded extenions seperated by space without dot at beginning. </i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "NAME_SWAP": (
        "",
        "",
        """<i>Send your Name Swap. You can add pattern instead of normal text according to the format.</i>
<b>Full Documentation Guide</b> <a href="https://t.me/WZML_X/77">Click Here</a>
╰ <b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "YT_DLP_OPTIONS": (
        "",
        "",
        """Format: {key: value, key: value, key: value}.
Example: {"format": "bv*+mergeall[vcodec=none]", "nocheckcertificate": True, "playliststart": 10, "fragment_retries": float("inf"), "matchtitle": "S13", "writesubtitles": True, "live_from_start": True, "postprocessor_args": {"ffmpeg": ["-threads", "4"]}, "wait_for_video": (5, 100), "download_ranges": [{"start_time": 0, "end_time": 10}]}
Check all yt-dlp api options from this <a href='https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py#L184'>FILE</a> or use this <a href='https://t.me/mltb_official_channel/177'>script</a> to convert cli arguments to api options.

<i>Send dict of YT-DLP Options according to format.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>""",
    ),
    "FFMPEG_CMDS": (
        "",
        "",
        """Dict of list values of ffmpeg commands. You can set multiple ffmpeg commands for all files before upload. Don't write ffmpeg at beginning, start directly with the arguments.
Examples: {"subtitle": ["-i mltb.mkv -c copy -c:s srt mltb.mkv", "-i mltb.video -c copy -c:s srt mltb"], "convert": ["-i mltb.m4a -c:a libmp3lame -q:a 2 mltb.mp3", "-i mltb.audio -c:a libmp3lame -q:a 2 mltb.mp3"], extract: ["-i mltb -map 0:a -c copy mltb.mka -map 0:s -c copy mltb.srt"]}
Notes:
- Add `-del` to the list which you want from the bot to delete the original files after command run complete!
- To execute one of those lists in bot for example, you must use -ff subtitle (list key) or -ff convert (list key)
Here I will explain how to use mltb.* which is reference to files you want to work on.
1. First cmd: the input is mltb.mkv so this cmd will work only on mkv videos and the output is mltb.mkv also so all outputs is mkv. -del will delete the original media after complete run of the cmd.
2. Second cmd: the input is mltb.video so this cmd will work on all videos and the output is only mltb so the extenstion is same as input files.
3. Third cmd: the input in mltb.m4a so this cmd will work only on m4a audios and the output is mltb.mp3 so the output extension is mp3.
4. Fourth cmd: the input is mltb.audio so this cmd will work on all audios and the output is mltb.mp3 so the output extension is mp3.

<i>Send dict of FFMPEG_CMDS Options according to format.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "METADATA_CMDS": (
        "",
        "",
        """<i>Send your Meta data. You can according to the format title="Join @WZML_X".</i>
<b>Full Documentation Guide</b> <a href="https://t.me/WZML_X/">Click Here</a>
╰ <b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "USER_COOKIE_FILE": (
        "File",
        "User's YT-DLP Cookie File to authenticate access to websites and youtube.",
        "<i>Send your cookie file (e.g., cookies.txt).</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "METADATA_KEY": (
        "",
        "",
        "<i>Send your Metadata. Default: <code>[ @SyntaxRealm ]</code>.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "UPHOSTER": (
        "",
        "",
        "<i>Send the API Key / Token for <b>{name}</b>.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "EQUAL_SPLITS": (
        "on|off",
        "Split files equally.",
        "<i>Send on or off in order to enable or disable equal splits.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "MEDIA_GROUP": (
        "on|off",
        "Send files in media group.",
        "<i>Send on or off in order to enable or disable media group.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "AUTO_MIRROR_FLAGS": (
        "Flags",
        "Set Auto Mirror Flags (e.g. -up all, -up streamtape).",
        "<i>Send Flags to use with Auto Mirror.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "AUTO_FFMPEG_FLAGS": (
        "Flags",
        "Set Auto FFmpeg Flags (e.g. -ff on2).",
        "<i>Send Flags to use with Auto FFmpeg.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "AUTO_FLAGS_VALUE": (
        "Flags",
        "Set Auto Flags (e.g. -n hi, -ss 10).",
        "<i>Send Flags to use with Auto Flags.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
}

SUPPORTED_UPHOSTERS = {
    "stream": {
        "Vidara": "VIDARA_API",
        "StreamUP": "STREAMUP_API",
        "VidNest": "VIDNEST_API",
    },
    "download": {
        "FreeDL": "FREEDL_API",
        "ZapUpload": "ZAPUPLOAD_API",
    }
}


async def get_user_settings(from_user, stype="main"):
    user_id = from_user.id
    user_name = from_user.mention(style="html")
    buttons = ButtonMaker()
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    user_dict = user_data.get(user_id, {})

    if stype == "main":
        buttons.data_button(
            "General Settings", f"userset {user_id} general", position="header"
        )
        buttons.data_button("Mirror Settings", f"userset {user_id} mirror")
        buttons.data_button("Leech Settings", f"userset {user_id} leech")
        buttons.data_button("Uphoster Settings", f"userset {user_id} uphoster")
        buttons.data_button("AutoLeech Settings", f"userset {user_id} autoleech")
        buttons.data_button("FF Media Settings", f"userset {user_id} ffset")
        buttons.data_button(
            "Misc Settings", f"userset {user_id} advanced", position="l_body"
        )

        if user_dict and any(
            key in user_dict
            for key in list(user_settings_text.keys())
            + [
                "USER_TOKENS",
                "AS_DOCUMENT",
                "EQUAL_SPLITS",
                "MEDIA_GROUP",
                "USER_TRANSMISSION",
                "HYBRID_LEECH",
                "STOP_DUPLICATE",
                "STOP_DUPLICATE",
                "DEFAULT_UPLOAD",
                "AUTO_LEECH",
                "AUTO_MIRROR",
                "AUTO_YTDL",
                "AUTO_FFMPEG",
                "AUTO_FLAGS",
                "AUTO_MIRROR_FLAGS",
                "AUTO_FFMPEG_FLAGS",
                "AUTO_FLAGS_VALUE",
            ]
        ):
            buttons.data_button(
                "Reset All", f"userset {user_id} reset all", position="footer"
            )
        buttons.data_button("Close", f"userset {user_id} close", position="footer")

        text = f"""⌬ <b>User Settings :</b>

╭ <b>Name</b> → {user_name}
┊ <b>UserID</b> → #ID{user_id}
┊ <b>Username</b> → @{from_user.username}
┊ <b>Telegram DC</b> → {from_user.dc_id}
╰ <b>Telegram Lang</b> → {Language.get(lc).display_name() if (lc := from_user.language_code) else "N/A"}"""

        btns = buttons.build_menu(2)

    elif stype == "general":
        if user_dict.get("DEFAULT_UPLOAD", ""):
            default_upload = user_dict["DEFAULT_UPLOAD"]
        elif "DEFAULT_UPLOAD" not in user_dict:
            default_upload = Config.DEFAULT_UPLOAD
        du = "GDRIVE API" if default_upload == "gd" else "RCLONE"
        dur = "GDRIVE API" if default_upload != "gd" else "RCLONE"
        buttons.data_button(
            f"Swap to {dur} Mode", f"userset {user_id} {default_upload}"
        )

        user_tokens = user_dict.get("USER_TOKENS", False)
        tr = "USER" if user_tokens else "OWNER"
        trr = "OWNER" if user_tokens else "USER"
        buttons.data_button(
            f"Swap to {trr} token/config",
            f"userset {user_id} tog USER_TOKENS {'f' if user_tokens else 't'}",
        )

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        use_user_cookie = user_dict.get("USE_USER_COOKIE", False)
        cookie_mode = "USER's" if use_user_cookie else "OWNER's"
        buttons.data_button(
            f"Swap to {'OWNER' if use_user_cookie else 'USER'}'s Cookie",
            f"userset {user_id} tog USE_USER_COOKIE {'f' if use_user_cookie else 't'}",
        )
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>General Settings :</b>
╭ <b>Name</b> → {user_name}
┊ <b>Default Upload Package</b> → <b>{du}</b>
┊ <b>Default Usage Mode</b> → <b>{tr}'s</b> token/config
╰ <b>Cookie Mode</b> → <b>{cookie_mode}</b>
"""

    elif stype == "leech":
        thumbpath = f"thumbnails/{user_id}.jpg"
        buttons.data_button("Thumbnail", f"userset {user_id} menu THUMBNAIL")
        thumbmsg = "Exists" if await aiopath.exists(thumbpath) else "Not Exists"
        buttons.data_button(
            "Leech Split Size", f"userset {user_id} menu LEECH_SPLIT_SIZE"
        )
        if user_dict.get("LEECH_SPLIT_SIZE", False):
            split_size = user_dict["LEECH_SPLIT_SIZE"]
        else:
            split_size = Config.LEECH_SPLIT_SIZE
        buttons.data_button(
            "Leech Destination", f"userset {user_id} menu LEECH_DUMP_CHAT"
        )
        if user_dict.get("LEECH_DUMP_CHAT", False):
            leech_dest = user_dict["LEECH_DUMP_CHAT"]
        elif "LEECH_DUMP_CHAT" not in user_dict and Config.LEECH_DUMP_CHAT:
            leech_dest = Config.LEECH_DUMP_CHAT
        else:
            leech_dest = "None"
        buttons.data_button("Leech Prefix", f"userset {user_id} menu LEECH_PREFIX")
        if user_dict.get("LEECH_PREFIX", False):
            lprefix = user_dict["LEECH_PREFIX"]
        elif "LEECH_PREFIX" not in user_dict and Config.LEECH_PREFIX:
            lprefix = Config.LEECH_PREFIX
        else:
            lprefix = "Not Exists"
        buttons.data_button("Leech Suffix", f"userset {user_id} menu LEECH_SUFFIX")
        if user_dict.get("LEECH_SUFFIX", False):
            lsuffix = user_dict["LEECH_SUFFIX"]
        elif "LEECH_SUFFIX" not in user_dict and Config.LEECH_SUFFIX:
            lsuffix = Config.LEECH_SUFFIX
        else:
            lsuffix = "Not Exists"

        buttons.data_button("Leech Caption", f"userset {user_id} menu LEECH_CAPTION")
        if user_dict.get("LEECH_CAPTION", False):
            lcap = user_dict["LEECH_CAPTION"]
        elif "LEECH_CAPTION" not in user_dict and Config.LEECH_CAPTION:
            lcap = Config.LEECH_CAPTION
        else:
            lcap = "Not Exists"

        buttons.data_button("Metadata", f"userset {user_id} menu METADATA_KEY")
        if user_dict.get("METADATA_KEY", False):
            meta = user_dict["METADATA_KEY"]
        elif "METADATA_KEY" not in user_dict and Config.METADATA_KEY:
            meta = Config.METADATA_KEY
        else:
            meta = "[ @SyntaxRealm ]"

        if (
            user_dict.get("AS_DOCUMENT", False)
            or "AS_DOCUMENT" not in user_dict
            and Config.AS_DOCUMENT
        ):
            ltype = "DOCUMENT"
            buttons.data_button("Send As Media", f"userset {user_id} tog AS_DOCUMENT f")
        else:
            ltype = "MEDIA"
            buttons.data_button(
                "Send As Document", f"userset {user_id} tog AS_DOCUMENT t"
            )
        if (
            user_dict.get("EQUAL_SPLITS", False)
            or "EQUAL_SPLITS" not in user_dict
            and Config.EQUAL_SPLITS
        ):
            buttons.data_button(
                "Disable Equal Splits", f"userset {user_id} tog EQUAL_SPLITS f"
            )
            equal_splits = "Enabled ✓"
        else:
            buttons.data_button(
                "Enable Equal Splits", f"userset {user_id} tog EQUAL_SPLITS t"
            )
            equal_splits = "Disabled ✘"
        if (
            user_dict.get("MEDIA_GROUP", False)
            or "MEDIA_GROUP" not in user_dict
            and Config.MEDIA_GROUP
        ):
            buttons.data_button(
                "Disable Media Group", f"userset {user_id} tog MEDIA_GROUP f"
            )
            media_group = "Enabled ✓"
        else:
            buttons.data_button(
                "Enable Media Group", f"userset {user_id} tog MEDIA_GROUP t"
            )
            media_group = "Disabled ✘"
        if (
            TgClient.IS_PREMIUM_USER
            and user_dict.get("USER_TRANSMISSION", False)
            or "USER_TRANSMISSION" not in user_dict
            and Config.USER_TRANSMISSION
        ):
            buttons.data_button(
                "Leech by Bot", f"userset {user_id} tog USER_TRANSMISSION f"
            )
            leech_method = "user"
        elif TgClient.IS_PREMIUM_USER:
            leech_method = "bot"
            buttons.data_button(
                "Leech by User", f"userset {user_id} tog USER_TRANSMISSION t"
            )
        else:
            leech_method = "bot"

        if (
            TgClient.IS_PREMIUM_USER
            and user_dict.get("HYBRID_LEECH", False)
            or "HYBRID_LEECH" not in user_dict
            and Config.HYBRID_LEECH
        ):
            hybrid_leech = "Enabled ✓"
            buttons.data_button(
                "Disable Hybride Leech", f"userset {user_id} tog HYBRID_LEECH f"
            )
        elif TgClient.IS_PREMIUM_USER:
            hybrid_leech = "Disabled ✘"
            buttons.data_button(
                "Enable HYBRID Leech", f"userset {user_id} tog HYBRID_LEECH t"
            )
        else:
            hybrid_leech = "Disabled ✘"

        buttons.data_button(
            "Thumbnail Layout", f"userset {user_id} menu THUMBNAIL_LAYOUT"
        )
        if user_dict.get("THUMBNAIL_LAYOUT", False):
            thumb_layout = user_dict["THUMBNAIL_LAYOUT"]
        elif "THUMBNAIL_LAYOUT" not in user_dict and Config.THUMBNAIL_LAYOUT:
            thumb_layout = Config.THUMBNAIL_LAYOUT
        else:
            thumb_layout = "None"

        ss_mode_labels = {"image": "📷 Image", "doc": "📄 Document", "title": "🕐 Title", "detailed": "📋 Detailed"}
        current_ss_mode = user_dict.get("SCREENSHOT_MODE", "image")
        ss_orient_labels = {"landscape": "🖼️ Landscape", "portrait": "📱 Portrait"}
        current_ss_orient = user_dict.get("SCREENSHOT_ORIENTATION", "landscape")

        buttons.data_button(
            "Screenshot", f"userset {user_id} sset"
        )

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""⌬ <b>Leech Settings :</b>
╭ <b>Name</b> → {user_name}
┊ Leech Type → <b>{ltype}</b>
┊ Custom Thumbnail → <b>{thumbmsg}</b>
┊ Leech Split Size → <b>{get_readable_file_size(split_size)}</b>
┊ Equal Splits → <b>{equal_splits}</b>
┊ Media Group → <b>{media_group}</b>
┊ Leech Prefix → <code>{escape(lprefix)}</code>
┊ Leech Suffix → <code>{escape(lsuffix)}</code>
┊ Leech Caption → <code>{escape(lcap)}</code>
┊ Leech Destination → <code>{leech_dest}</code>
┊ Leech by <b>{leech_method}</b> session
┊ Mixed Leech → <b>{hybrid_leech}</b>
┊ Metadata → <code>{escape(meta)}</code>
┊ Thumbnail Layout → <b>{thumb_layout}</b>
┊ Screenshot Mode → <b>{ss_mode_labels.get(current_ss_mode, 'Image')}</b>
╰ Screenshot Orient → <b>{ss_orient_labels.get(current_ss_orient, 'Landscape')}</b>
"""


    elif stype == "rclone":
        buttons.data_button("Rclone Config", f"userset {user_id} menu RCLONE_CONFIG")
        buttons.data_button(
            "Default Rclone Path", f"userset {user_id} menu RCLONE_PATH"
        )
        buttons.data_button("Rclone Flags", f"userset {user_id} menu RCLONE_FLAGS")

        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        rccmsg = "Exists" if await aiopath.exists(rclone_conf) else "Not Exists"
        if user_dict.get("RCLONE_PATH", False):
            rccpath = user_dict["RCLONE_PATH"]
        elif Config.RCLONE_PATH:
            rccpath = Config.RCLONE_PATH
        else:
            rccpath = "None"
        btns = buttons.build_menu(1)

        if user_dict.get("RCLONE_FLAGS", False):
            rcflags = user_dict["RCLONE_FLAGS"]
        elif "RCLONE_FLAGS" not in user_dict and Config.RCLONE_FLAGS:
            rcflags = Config.RCLONE_FLAGS
        else:
            rcflags = "None"

        text = f"""⌬ <b>RClone Settings :</b>
╭ <b>Name</b> → {user_name}
┊ <b>Rclone Config</b> → <b>{rccmsg}</b>
┊ <b>Rclone Flags</b> → <code>{rcflags}</code>
╰ <b>Rclone Path</b> → <code>{rccpath}</code>"""

    elif stype == "gdrive":
        buttons.data_button("token.pickle", f"userset {user_id} menu TOKEN_PICKLE")
        buttons.data_button("Default Gdrive ID", f"userset {user_id} menu GDRIVE_ID")
        buttons.data_button("Index URL", f"userset {user_id} menu INDEX_URL")
        if (
            user_dict.get("STOP_DUPLICATE", False)
            or "STOP_DUPLICATE" not in user_dict
            and Config.STOP_DUPLICATE
        ):
            buttons.data_button(
                "Disable Stop Duplicate", f"userset {user_id} tog STOP_DUPLICATE f"
            )
            sd_msg = "Enabled ✓"
        else:
            buttons.data_button(
                "Enable Stop Duplicate",
                f"userset {user_id} tog STOP_DUPLICATE t",
                "l_body",
            )
            sd_msg = "Disabled ✘"
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        tokenmsg = "Exists" if await aiopath.exists(token_pickle) else "Not Exists"
        if user_dict.get("GDRIVE_ID", False):
            gdrive_id = user_dict["GDRIVE_ID"]
        elif GDID := Config.GDRIVE_ID:
            gdrive_id = GDID
        else:
            gdrive_id = "None"
        index = user_dict["INDEX_URL"] if user_dict.get("INDEX_URL", False) else "None"
        btns = buttons.build_menu(2)

        text = f"""⌬ <b>GDrive Tools Settings :</b>
╭ <b>Name</b> → {user_name}
┊ <b>Gdrive Token</b> → <b>{tokenmsg}</b>
┊ <b>Gdrive ID</b> → <code>{gdrive_id}</code>
┊ <b>Index URL</b> → <code>{index}</code>
╰ <b>Stop Duplicate</b> → <b>{sd_msg}</b>"""
    elif stype == "mirror":
        buttons.data_button("RClone Tools", f"userset {user_id} rclone")
        rccmsg = "Exists" if await aiopath.exists(rclone_conf) else "Not Exists"
        if user_dict.get("RCLONE_PATH", False):
            rccpath = user_dict["RCLONE_PATH"]
        elif RP := Config.RCLONE_PATH:
            rccpath = RP
        else:
            rccpath = "None"

        buttons.data_button("GDrive Tools", f"userset {user_id} gdrive")
        tokenmsg = "Exists" if await aiopath.exists(token_pickle) else "Not Exists"
        if user_dict.get("GDRIVE_ID", False):
            gdrive_id = user_dict["GDRIVE_ID"]
        elif GI := Config.GDRIVE_ID:
            gdrive_id = GI
        else:
            gdrive_id = "None"

        index = user_dict["INDEX_URL"] if user_dict.get("INDEX_URL", False) else "None"
        if (
            user_dict.get("STOP_DUPLICATE", False)
            or "STOP_DUPLICATE" not in user_dict
            and Config.STOP_DUPLICATE
        ):
            sd_msg = "Enabled ✓"
        else:
            sd_msg = "Disabled ✘"

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>Mirror Settings :</b>
╭ <b>Name</b> → {user_name}
┊ <b>Rclone Config</b> → <b>{rccmsg}</b>
┊ <b>Rclone Path</b> → <code>{rccpath}</code>
┊ <b>Gdrive Token</b> → <b>{tokenmsg}</b>
┊ <b>Gdrive ID</b> → <code>{gdrive_id}</code>
┊ <b>Index Link</b> → <code>{index}</code>
╰ <b>Stop Duplicate</b> → <b>{sd_msg}</b>
"""

    elif stype == "screenshot":
        # Screenshot Mode cycling
        ss_modes = ["image", "doc", "title", "detailed"]
        ss_mode_labels = {"image": "📷 Image", "doc": "📄 Doc", "title": "🕐 Title", "detailed": "📋 Detailed"}
        current_ss_mode = user_dict.get("SCREENSHOT_MODE", "image")
        next_ss_mode = ss_modes[(ss_modes.index(current_ss_mode) + 1) % len(ss_modes)]
        buttons.data_button(
            f"Mode: {ss_mode_labels.get(current_ss_mode, 'Image')}",
            f"userset {user_id} ssmode {next_ss_mode}"
        )

        # Orientation cycling
        ss_orientations = ["landscape", "portrait"]
        ss_orient_labels = {"landscape": "🖼️ Landscape", "portrait": "📱 Portrait"}
        current_ss_orient = user_dict.get("SCREENSHOT_ORIENTATION", "landscape")
        next_ss_orient = ss_orientations[(ss_orientations.index(current_ss_orient) + 1) % len(ss_orientations)]
        buttons.data_button(
            f"Orient: {ss_orient_labels.get(current_ss_orient, 'Land')}",
            f"userset {user_id} ssorient {next_ss_orient}"
        )

        buttons.data_button("Back", f"userset {user_id} back leech", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""⌬ <b>Screenshot Settings</b>

<b>Flags:</b> <code>-ss count:mode:orient</code>
<b>Timestamps:</b> <code>-sst 10 01:20 01:10:05</code>

<b>Modes:</b> Image, Doc, Title, Detailed
<b>Orients:</b> Land, Port (9:16)"""

    elif stype == "ffset":
        buttons.data_button("FFmpeg Cmds", f"userset {user_id} menu FFMPEG_CMDS")
        if user_dict.get("FFMPEG_CMDS", False):
            ffc = user_dict["FFMPEG_CMDS"]
        elif "FFMPEG_CMDS" not in user_dict and Config.FFMPEG_CMDS:
            ffc = Config.FFMPEG_CMDS
        else:
            ffc = "<b>Not Exists</b>"

        if isinstance(ffc, dict):
            ffc = "\n" + "\n".join(
                [
                    f"{no}. <b>{key}</b>: <code>{value[0]}</code>"
                    for no, (key, value) in enumerate(ffc.items(), start=1)
                ]
            )

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""⌬ <b>FF Settings :</b>
╭ <b>Name</b> → {user_name}
╰ <b>FFmpeg Commands</b> → {ffc}"""

    elif stype == "advanced":
        buttons.data_button(
            "Excluded Extensions", f"userset {user_id} menu EXCLUDED_EXTENSIONS"
        )
        if user_dict.get("EXCLUDED_EXTENSIONS", False):
            ex_ex = user_dict["EXCLUDED_EXTENSIONS"]
        elif "EXCLUDED_EXTENSIONS" not in user_dict:
            ex_ex = excluded_extensions
        else:
            ex_ex = "None"

        if ex_ex != "None":
            ex_ex = ", ".join(ex_ex)

        ns_msg = (
            f"<code>{swap}</code>"
            if (swap := user_dict.get("NAME_SWAP", False))
            else "<b>Not Exists</b>"
        )
        buttons.data_button("Name Swap", f"userset {user_id} menu NAME_SWAP")

        buttons.data_button("YT-DLP Options", f"userset {user_id} menu YT_DLP_OPTIONS")
        if user_dict.get("YT_DLP_OPTIONS", False):
            ytopt = user_dict["YT_DLP_OPTIONS"]
        elif "YT_DLP_OPTIONS" not in user_dict and Config.YT_DLP_OPTIONS:
            ytopt = Config.YT_DLP_OPTIONS
        else:
            ytopt = "None"

        upload_paths = user_dict.get("UPLOAD_PATHS", {})
        if not upload_paths and "UPLOAD_PATHS" not in user_dict and Config.UPLOAD_PATHS:
            upload_paths = Config.UPLOAD_PATHS
        else:
            upload_paths = "None"
        buttons.data_button("Upload Paths", f"userset {user_id} menu UPLOAD_PATHS")

        yt_cookie_path = f"cookies/{user_id}.txt"
        user_cookie_msg = (
            "Exists" if await aiopath.exists(yt_cookie_path) else "Not Exists"
        )
        buttons.data_button(
            "YT Cookie File", f"userset {user_id} menu USER_COOKIE_FILE"
        )

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>Advanced Settings :</b>
╭ <b>Name</b> → {user_name}
┊ <b>Name Swaps</b> → {ns_msg}
┊ <b>Excluded Extensions</b> → <code>{ex_ex}</code>
┊ <b>Upload Paths</b> → <b>{upload_paths}</b>
┊ <b>YT-DLP Options</b> → <code>{ytopt}</code>
╰ <b>YT User Cookie File</b> → <b>{user_cookie_msg}</b>"""

    elif stype == "uphoster":
        buttons.data_button("Stream Sites", f"userset {user_id} upstream")
        buttons.data_button("Download Sites", f"userset {user_id} updown")
        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""⌬ <b>Uphoster Settings :</b>
╭ <b>Name</b> → {user_name}
╰ <b>Select a category to configure uphoster keys.</b>"""

    elif stype == "upstream":
        for name, key in SUPPORTED_UPHOSTERS["stream"].items():
            val = "Exits" if user_dict.get(key) or getattr(Config, key, None) else "None"
            buttons.data_button(f"{name} ({val})", f"userset {user_id} upedit {key}")
        
        buttons.data_button("Back", f"userset {user_id} uphoster", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""⌬ <b>Stream Uphoster Settings :</b>
╭ <b>Name</b> → {user_name}
╰ <b>Select a site to configure its API Key.</b>"""

    elif stype == "updown":
        for name, key in SUPPORTED_UPHOSTERS["download"].items():
            val = "Exits" if user_dict.get(key) or getattr(Config, key, None) else "None"
            buttons.data_button(f"{name} ({val})", f"userset {user_id} upedit {key}")

        buttons.data_button("Back", f"userset {user_id} uphoster", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        text = f"""⌬ <b>Download Uphoster Settings :</b>
╭ <b>Name</b> → {user_name}
╰ <b>Select a site to configure its API Key.</b>"""

    elif stype.startswith("upedit"):
        _, key = stype.split(maxsplit=1)
        name = next((n for n, k in SUPPORTED_UPHOSTERS["stream"].items() if k == key), None) or \
               next((n for n, k in SUPPORTED_UPHOSTERS["download"].items() if k == key), "Unknown")
        buttons.data_button("Back", f"userset {user_id} uphoster", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)
        
        val = user_dict.get(key) or getattr(Config, key, None) or "None"
        text = f"""⌬ <b>Edit {name} :</b>
╭ <b>Name</b> → {user_name}
┊ <b>Current Key</b> → <code>{val}</code>
╰ <b>Send new API Key / Token for {name}.</b>"""

    elif stype == "autoleech":
        # Row 1: Auto Mode
        mode = user_dict.get("AUTO_MODE", "All")
        buttons.data_button(f"Auto Mode: {mode} 🔄", f"userset {user_id} cycle AUTO_MODE")

        # Row 2: Auto Thumb
        if user_dict.get("AUTO_THUMB", False):
            buttons.data_button("Set Auto Thumbnail ✓", f"userset {user_id} tog AUTO_THUMB f")
            at_msg = "Enabled ✓"
        else:
            buttons.data_button("Set Auto Thumbnail ✘", f"userset {user_id} tog AUTO_THUMB t")
            at_msg = "Disabled ✘"

        # Row 2: Auto Leech
        if user_dict.get("AUTO_LEECH", False):
            buttons.data_button("Auto Leech Mode ✓", f"userset {user_id} tog AUTO_LEECH f")
            al_msg = "Enabled ✓"
        else:
            buttons.data_button("Auto Leech Mode ✘", f"userset {user_id} tog AUTO_LEECH t")
            al_msg = "Disabled ✘"

        # Row 3: Auto YTDL
        if user_dict.get("AUTO_YTDL", False):
            buttons.data_button("Auto YTDL Leech ✓", f"userset {user_id} tog AUTO_YTDL f")
            ay_msg = "Enabled ✓"
        else:
            buttons.data_button("Auto YTDL Leech ✘", f"userset {user_id} tog AUTO_YTDL t")
            ay_msg = "Disabled ✘"

        # Row 4: Auto Mirror | Mirror Flags
        if user_dict.get("AUTO_MIRROR", False):
            buttons.data_button("Auto Mirror ✓", f"userset {user_id} tog AUTO_MIRROR f")
            am_msg = "Enabled ✓"
        else:
            buttons.data_button("Auto Mirror ✘", f"userset {user_id} tog AUTO_MIRROR t")
            am_msg = "Disabled ✘"
        
        buttons.data_button("Mirror Flags ✎", f"userset {user_id} menu AUTO_MIRROR_FLAGS")
        if user_dict.get("AUTO_MIRROR_FLAGS", False):
            am_flags = user_dict["AUTO_MIRROR_FLAGS"]
        else:
            am_flags = "None"

        # Row 5: Auto FFmpeg | FFmpeg Flags
        if user_dict.get("AUTO_FFMPEG", False):
            buttons.data_button("Auto FFmpeg ✓", f"userset {user_id} tog AUTO_FFMPEG f")
            aff_msg = "Enabled ✓ "
        else:
            buttons.data_button("Auto FFmpeg ✘", f"userset {user_id} tog AUTO_FFMPEG t")
            aff_msg = "Disabled ✘"
            
        buttons.data_button("FFmpeg Flags ✎", f"userset {user_id} menu AUTO_FFMPEG_FLAGS")
        if user_dict.get("AUTO_FFMPEG_FLAGS", False):
            aff_flags = user_dict["AUTO_FFMPEG_FLAGS"]
        else:
            aff_flags = "None"

        # Row 6: Auto Flags | Common Flags
        if user_dict.get("AUTO_FLAGS", False):
            buttons.data_button("Auto Flags ✓", f"userset {user_id} tog AUTO_FLAGS f")
            af_msg = "Enabled ✓"
        else:
            buttons.data_button("Auto Flags ✘", f"userset {user_id} tog AUTO_FLAGS t")
            af_msg = "Disabled ✘"
            
        buttons.data_button("Set Flags ✎", f"userset {user_id} menu AUTO_FLAGS_VALUE")
        if user_dict.get("AUTO_FLAGS_VALUE", False):
            af_val = user_dict["AUTO_FLAGS_VALUE"]
        else:
            af_val = "None"

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        # Layout: 1, 1, 1, 1, 2, 2, 2
        btns = buttons.build_menu([1, 1, 1, 1, 2, 2, 2])

        text = f"""⌬ <b>AutoLeech Settings :</b>
        
╭ <b>Name</b> → {user_name}
┊ <b>Auto Mode</b> → <b>{mode}</b>
┊ <b>Auto Thumb</b> → <b>{at_msg}</b>
┊ <b>Auto Leech</b> → <b>{al_msg}</b> 
┊ <b>Auto YTDL</b> → <b>{ay_msg}</b>
┊ <b>Auto Mirror</b> → <b>{am_msg}</b>
┊ <b>Mirror Flags</b> → <code>{am_flags}</code>
┊ <b>Auto FFmpeg</b> → <b>{aff_msg}</b>
┊ <b>FFmpeg Flags</b> → <code>{aff_flags}</code>
┊ <b>Auto Flags</b> → <b>{af_msg}</b>
╰ <b>Common Flags</b> → <code>{af_val}</code>"""

    return text, btns

async def update_user_settings(query, stype="main"):
    handler_dict[query.from_user.id] = False
    msg, button = await get_user_settings(query.from_user, stype)
    await edit_message(query.message, msg, button)



async def handle_direct_update(message):
    user_id = message.from_user.id
    reply_to = message.reply_to_message
    if not reply_to or not reply_to.from_user.is_bot:
        reply_to = message

    HELP_MSG = """
㊂ <b><u>Available Flags :</u></b>
>> Reply to the Value with appropriate arg respectively to set directly without opening USet.

➲ <b>Custom Thumbnail :</b>
    /cmd -s thumb

➲ <b>Leech Filename Prefix :</b>
    /cmd -s prefix

➲ <b>Leech Filename Suffix :</b>
    /cmd -s suffix

➲ <b>Leech Caption :</b>
    /cmd -s caption

➲ <b>Leech Destination :</b>
    /cmd -s dest

➲ <b>Leech Split Size :</b>
    /cmd -s split

➲ <b>Equal Splits :</b>
    /cmd -s equalsplit on|off

➲ <b>Media Group :</b>
    /cmd -s mediagroup on|off

➲ <b>Metadata :</b>
    /cmd -s metadata
"""

    args = message.text.split(maxsplit=2)
    if len(args) < 3 and args[1] != "-s":
        return

    mapping = {
        "prefix": "LEECH_PREFIX",
        "suffix": "LEECH_SUFFIX",
        "caption": "LEECH_CAPTION",
        "dest": "LEECH_DUMP_CHAT",
        "split": "LEECH_SPLIT_SIZE",
        "equalsplit": "EQUAL_SPLITS",
        "mediagroup": "MEDIA_GROUP",
        "thumb": "THUMBNAIL",
        "metadata": "METADATA_KEY",
    }
    
    if len(args) < 3:
        await send_message(message, HELP_MSG)
        return

    key_arg = args[2].lower()
    value = args[3] if len(args) > 3 else ""

    if key_arg not in mapping:
        await send_message(message, HELP_MSG)
        return

    key = mapping[key_arg]

    if key == "THUMBNAIL":
        if message.reply_to_message and (message.reply_to_message.photo or message.reply_to_message.document):
            rfunc = partial(get_menu, key, message, user_id, False)
            await add_file(None, message.reply_to_message, key, rfunc, forced_user_id=user_id)
            await delete_message(message)
        else:
            await get_menu(key, message, user_id, False)
            await delete_message(message)
        return

    if not value and message.reply_to_message:
        value = message.reply_to_message.text or message.reply_to_message.caption

    if not value:
        await get_menu(key, message, user_id, False)
        await delete_message(message)
        return

    if key == "LEECH_SPLIT_SIZE":
        try:
            if not value.isdigit():
                value = get_size_bytes(value)
            value = min(int(value), TgClient.MAX_SPLIT_SIZE)
        except:
             await send_message(message, "Invalid size format!")
             return
    
    elif key in ["EQUAL_SPLITS", "MEDIA_GROUP"]:
        if value.lower() not in ["on", "off"]:
            await send_message(message, "Value must be on or off!")
            return
        value = value.lower() == "on"

    update_user_ldata(user_id, key, value)
    await database.update_user_data(user_id)
    
    await delete_message(message)
    
    # Refresh logic
    if reply_to and reply_to.from_user.is_self:
         try:
             msg, btn = await get_user_settings(message.from_user, "leech")
             await edit_message(reply_to, msg, btn)
         except:
             pass
    else:
        await get_menu(key, message, user_id, False)

@new_task
async def send_user_settings(_, message):
    if len(message.command) > 1 and message.command[1] == "-s":
        return await handle_direct_update(message)

    from_user = message.from_user
    handler_dict[from_user.id] = False
    msg, button = await get_user_settings(from_user)
    await send_message(message, msg, button)


@new_task
async def add_file(_, message, ftype, rfunc, forced_user_id=None):
    user_id = forced_user_id or message.from_user.id
    handler_dict[user_id] = False
    if ftype == "THUMBNAIL":
        des_dir = await create_thumb(message, user_id)
    elif ftype == "RCLONE_CONFIG":
        rpath = f"{getcwd()}/rclone/"
        await makedirs(rpath, exist_ok=True)
        des_dir = f"{rpath}{user_id}.conf"
        await message.download(file_name=des_dir)
    elif ftype == "TOKEN_PICKLE":
        tpath = f"{getcwd()}/tokens/"
        await makedirs(tpath, exist_ok=True)
        des_dir = f"{tpath}{user_id}.pickle"
        await message.download(file_name=des_dir)
    elif ftype == "USER_COOKIE_FILE":
        cpath = f"{getcwd()}/cookies/{user_id}"
        await makedirs(cpath, exist_ok=True)
        des_dir = f"{cpath}/cookies.txt"
        await message.download(file_name=des_dir)
    await delete_message(message)
    LOGGER.info(f"User {user_id} updated {ftype}. Path: {des_dir}")
    update_user_ldata(user_id, ftype, des_dir)
    await rfunc()
    await database.update_user_doc(user_id, ftype, des_dir)


@new_task
async def add_one(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    value = message.text
    if value.startswith("{") and value.endswith("}"):
        try:
            value = eval(value)
            if user_dict[option]:
                user_dict[option].update(value)
            else:
                update_user_ldata(user_id, option, value)
        except Exception as e:
            await send_message(message, str(e))
            return
    else:
        await send_message(message, "It must be Dict!")
        return
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


@new_task
async def remove_one(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    names = message.text.split("/")
    for name in names:
        if name in user_dict[option]:
            del user_dict[option][name]
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


@new_task
async def set_option(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    value = message.text
    if option == "LEECH_SPLIT_SIZE":
        if not value.isdigit():
            value = get_size_bytes(value)
        value = min(int(value), TgClient.MAX_SPLIT_SIZE)

    elif option == "EXCLUDED_EXTENSIONS":
        fx = value.split()
        value = ["aria2", "!qB"]
        for x in fx:
            x = x.lstrip(".")
            value.append(x.strip().lower())
    elif option in ["UPLOAD_PATHS", "FFMPEG_CMDS", "YT_DLP_OPTIONS"]:
        if value.startswith("{") and value.endswith("}"):
            try:
                value = eval(sub(r"\s+", " ", value))
            except Exception as e:
                await send_message(message, str(e))
                return
        else:
            await send_message(message, "It must be dict!")
            return
    update_user_ldata(user_id, option, value)
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


async def get_menu(option, message, user_id, edit_mode=True):
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})

    file_dict = {
        "THUMBNAIL": f"thumbnails/{user_id}.jpg",
        "RCLONE_CONFIG": f"rclone/{user_id}.conf",
        "TOKEN_PICKLE": f"tokens/{user_id}.pickle",
        "USER_COOKIE_FILE": f"cookies/{user_id}/cookies.txt",
    }

    buttons = ButtonMaker()
    if option in ["THUMBNAIL", "RCLONE_CONFIG", "TOKEN_PICKLE", "USER_COOKIE_FILE"]:
        key = "file"
    else:
        key = "set"
    buttons.data_button(
        "Change" if user_dict.get(option, False) else "Set",
        f"userset {user_id} {key} {option}",
    )
    if user_dict.get(option, False):
        if option == "THUMBNAIL":
            buttons.data_button(
                "View Thumb", f"userset {user_id} view THUMBNAIL", "header"
            )
        elif option in ["YT_DLP_OPTIONS", "FFMPEG_CMDS", "UPLOAD_PATHS"]:
            buttons.data_button(
                "Add One", f"userset {user_id} addone {option}", "header"
            )
            buttons.data_button(
                "Remove One", f"userset {user_id} rmone {option}", "header"
            )

        if key != "file":
            buttons.data_button("Reset", f"userset {user_id} reset {option}")
        elif await aiopath.exists(file_dict[option]):
            buttons.data_button("Remove", f"userset {user_id} remove {option}")
    if option in leech_options:
        back_to = "leech"
    elif option in rclone_options:
        back_to = "rclone"
    elif option in gdrive_options:
        back_to = "gdrive"
    elif option in ffset_options:
        back_to = "ffset"
    elif option in advanced_options:
        back_to = "advanced"
    elif option in auto_leech_options:
        back_to = "autoleech"
    else:
        back_to = "back"
    buttons.data_button("Back", f"userset {user_id} {back_to}", "footer")
    buttons.data_button("Close", f"userset {user_id} close", "footer")
    val = user_dict.get(option)
    if option in file_dict and await aiopath.exists(file_dict[option]):
        val = "<b>Exists</b>"
    elif option == "LEECH_SPLIT_SIZE":
        val = get_readable_file_size(val)
    desc = user_settings_text[option][1]
    kwargs = {"disable_web_page_preview": True}
    if option == "THUMBNAIL" and val == "<b>Exists</b>" and Config.BASE_URL:
        mtime = int(ospath.getmtime(file_dict[option]))
        desc = f"<a href=\"{Config.BASE_URL.rstrip('/')}/thumbnails/{user_id}.jpg?v={mtime}\">&#8203;</a>{desc}"
        kwargs["disable_web_page_preview"] = False

    text = f"""⌬ <b><u>Menu Settings :</u></b>

╭ <b>Option</b> → {option}
┊ <b>Option's Value</b> → {val if val else "<b>Not Exists</b>"}
┊ <b>Default Input Type</b> → {user_settings_text[option][0]}
╰ <b>Description</b> → {desc}
"""
    func = edit_message if edit_mode else send_message
    await func(message, text, buttons.build_menu(2), **kwargs)


async def event_handler(client, query, pfunc, rfunc, photo=False, document=False):
    user_id = query.from_user.id
    handler_dict[user_id] = True
    start_time = update_time = time()

    async def event_filter(_, __, event):
        if photo:
            mtype = event.photo or event.document
        elif document:
            mtype = event.document
        else:
            mtype = event.text
        user = event.from_user or event.sender_chat
        return bool(
            user.id == user_id and event.chat.id == query.message.chat.id and mtype
        )

    handler = client.add_handler(
        MessageHandler(pfunc, filters=create(event_filter)), group=-1
    )

    while handler_dict[user_id]:
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[user_id] = False
            await rfunc()
        elif time() - update_time > 8 and handler_dict[user_id]:
            update_time = time()
            msg = await client.get_messages(query.message.chat.id, query.message.id)
            text = msg.text.split("\n")
            text[-1] = (
                f"╰ <b>Time Left :</b> <code>{round(60 - (time() - start_time), 2)} sec</code>"
            )
            await edit_message(msg, "\n".join(text), msg.reply_markup)
    client.remove_handler(*handler)


@new_task
async def edit_user_settings(client, query):
    from_user = query.from_user
    user_id = from_user.id
    name = from_user.mention
    message = query.message
    data = query.data.split()

    handler_dict[user_id] = False
    thumb_path = f"thumbnails/{user_id}.jpg"
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    yt_cookie_path = f"cookies/{user_id}/cookies.txt"

    user_dict = user_data.get(user_id, {})
    if user_id != int(data[1]):
        return await query.answer("Not Yours!", show_alert=True)
    elif data[2] == "setevent":
        await query.answer()
    elif data[2] in [
        "general",
        "mirror",
        "leech",
        "ffset",
        "advanced",
        "gdrive",
        "rclone",
        "rclone",
        "uphoster",
        "upstream",
        "updown",
        "autoleech",
    ]:
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == "menu":
        await query.answer()
        await get_menu(data[3], message, user_id)
    elif data[2] == "tog":
        await query.answer()
        update_user_ldata(user_id, data[3], data[4] == "t")
        if data[3] == "STOP_DUPLICATE":
            back_to = "gdrive"
        elif data[3] in ["USER_TOKENS", "USE_USER_COOKIE"]:
            back_to = "general"
        elif data[3] in ["AUTO_LEECH", "AUTO_MIRROR", "AUTO_YTDL", "AUTO_FFMPEG", "AUTO_FLAGS", "AUTO_THUMB"]:
            back_to = "autoleech"
        else:
            back_to = "leech"
    elif data[2] == "cycle":
        await query.answer()
        if data[3] == "AUTO_MODE":
            modes = ['All', 'Links', 'Video', 'Audio']
            current = user_dict.get("AUTO_MODE", "All")
            try:
                idx = modes.index(current)
            except ValueError:
                idx = 0
            next_mode = modes[(idx + 1) % len(modes)]
            update_user_ldata(user_id, "AUTO_MODE", next_mode)
            back_to = "autoleech"
        await update_user_settings(query, stype=back_to)
        await database.update_user_data(user_id)
    elif data[2] == "sset":
        await query.answer()
        await update_user_settings(query, "screenshot")
    elif data[2] == "ssmode":
        await query.answer(f"Screenshot Mode: {data[3].upper()}")
        update_user_ldata(user_id, "SCREENSHOT_MODE", data[3])
        await update_user_settings(query, stype="screenshot")
        await database.update_user_data(user_id)
    elif data[2] == "ssorient":
        await query.answer(f"SS Orientation: {data[3].upper()}")
        update_user_ldata(user_id, "SCREENSHOT_ORIENTATION", data[3])
        await update_user_settings(query, stype="screenshot")
        await database.update_user_data(user_id)
    elif data[2] == "file":
        await query.answer()
        buttons = ButtonMaker()
        text = user_settings_text[data[3]][2]
        buttons.data_button("Stop", f"userset {user_id} menu {data[3]} stop")
        buttons.data_button("Back", f"userset {user_id} menu {data[3]}", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        await edit_message(
            message, message.text.html + "\n\n" + text, buttons.build_menu(1)
        )
        rfunc = partial(get_menu, data[3], message, user_id)
        pfunc = partial(add_file, ftype=data[3], rfunc=rfunc)
        await event_handler(
            client,
            query,
            pfunc,
            rfunc,
            photo=data[3] == "THUMBNAIL",
            document=data[3] != "THUMBNAIL",
        )
    elif data[2] in ["set", "addone", "rmone"]:
        await query.answer()
        buttons = ButtonMaker()
        if data[2] == "set":
            text = user_settings_text[data[3]][2]
            func = set_option
        elif data[2] == "addone":
            text = f"Add one or more string key and value to {data[3]}. Example: {{'key 1': 62625261, 'key 2': 'value 2'}}. Timeout: 60 sec"
            func = add_one
        elif data[2] == "rmone":
            text = f"Remove one or more key from {data[3]}. Example: key 1/key2/key 3. Timeout: 60 sec"
            func = remove_one
        buttons.data_button("Stop", f"userset {user_id} menu {data[3]} stop")
        buttons.data_button("Back", f"userset {user_id} menu {data[3]}", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        await edit_message(
            message, message.text.html + "\n\n" + text, buttons.build_menu(1)
        )
        rfunc = partial(get_menu, data[3], message, user_id)
        pfunc = partial(func, option=data[3], rfunc=rfunc)
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == "remove":
        await query.answer("Removed!", show_alert=True)
        if data[3] in ["THUMBNAIL", "RCLONE_CONFIG", "TOKEN_PICKLE", "USER_COOKIE_FILE"]:
            if data[3] == "THUMBNAIL":
                fpath = thumb_path
            elif data[3] == "RCLONE_CONFIG":
                fpath = rclone_conf
            elif data[3] == "USER_COOKIE_FILE":
                fpath = yt_cookie_path
            else:
                fpath = token_pickle
            if await aiopath.exists(fpath):
                await remove(fpath)
            del user_dict[data[3]]
            await database.update_user_doc(user_id, data[3])
        else:
            update_user_ldata(user_id, data[3], "")
            await database.update_user_data(user_id)
        await get_menu(data[3], message, user_id)
    elif data[2] == "reset":
        await query.answer("Reset Done!", show_alert=True)
        if data[3] in user_dict:
            del user_dict[data[3]]
            await get_menu(data[3], message, user_id)
        else:
            for k in list(user_dict.keys()):
                if k not in ("SUDO", "AUTH", "VERIFY_TOKEN", "VERIFY_TIME"):
                    del user_dict[k]
            for fpath in [thumb_path, rclone_conf, token_pickle, yt_cookie_path]:
                if await aiopath.exists(fpath):
                    await remove(fpath)
            await update_user_settings(query)
        await database.update_user_data(user_id)
    elif data[2] == "view":
        await query.answer()
        await send_file(message, thumb_path, name)
    elif data[2] in ["gd", "rc"]:
        await query.answer()
        du = "rc" if data[2] == "gd" else "gd"
        update_user_ldata(user_id, "DEFAULT_UPLOAD", du)
        await update_user_settings(query, stype="general")
        await database.update_user_data(user_id)
    elif data[2] == "upedit":
        await query.answer()
        buttons = ButtonMaker()
        key = data[3]
        name = next((n for n, k in SUPPORTED_UPHOSTERS["stream"].items() if k == key), None) or \
               next((n for n, k in SUPPORTED_UPHOSTERS["download"].items() if k == key), "Unknown")
        text = user_settings_text["UPHOSTER"][2].format(name=name)
        stype = "upstream" if key in SUPPORTED_UPHOSTERS["stream"].values() else "updown"
        buttons.data_button("Stop", f"userset {user_id} {stype}")
        buttons.data_button("Back", f"userset {user_id} {stype}", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        await edit_message(
            message, message.text.html + "\n\n" + text, buttons.build_menu(1)
        )
        rfunc = partial(update_user_settings, query, stype)
        pfunc = partial(set_option, option=key, rfunc=rfunc)
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == "back":
        await query.answer()
        stype = data[3] if len(data) == 4 else "main"
        await update_user_settings(query, stype)
    else:
        await query.answer()
        await delete_message(message, message.reply_to_message)


@new_task
async def get_users_settings(_, message):
    msg = ""
    if auth_chats:
        msg += f"AUTHORIZED_CHATS: {auth_chats}\n"
    if sudo_users:
        msg += f"SUDO_USERS: {sudo_users}\n\n"
    if user_data:
        for u, d in user_data.items():
            kmsg = f"\n<b>{u}:</b>\n"
            if vmsg := "".join(
                f"{k}: <code>{v or None}</code>\n" for k, v in d.items()
            ):
                msg += kmsg + vmsg
        if not msg:
            await send_message(message, "No users data!")
            return
        msg_ecd = msg.encode()
        if len(msg_ecd) > 4000:
            with BytesIO(msg_ecd) as ofile:
                ofile.name = "users_settings.txt"
                await send_file(message, ofile)
        else:
            await send_message(message, msg)
    else:
        await send_message(message, "No users data!")