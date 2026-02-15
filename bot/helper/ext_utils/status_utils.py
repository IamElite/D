from asyncio import gather, iscoroutinefunction
from html import escape
from re import findall
from time import time

from psutil import cpu_percent, disk_usage, virtual_memory

from ... import (
    DOWNLOAD_DIR,
    bot_cache,
    bot_start_time,
    status_dict,
    task_dict,
    task_dict_lock,
)
from ...core.config_manager import Config
from ..telegram_helper.bot_commands import BotCommands
from ..telegram_helper.button_build import ButtonMaker

SIZE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


class MirrorStatus:
    STATUS_UPLOAD = "Upload"
    STATUS_DOWNLOAD = "Download"
    STATUS_CLONE = "Clone"
    STATUS_QUEUEDL = "QueueDl"
    STATUS_QUEUEUP = "QueueUp"
    STATUS_PAUSED = "Pause"
    STATUS_ARCHIVE = "Archive"
    STATUS_EXTRACT = "Extract"
    STATUS_SPLIT = "Split"
    STATUS_CHECK = "CheckUp"
    STATUS_SEED = "Seed"
    STATUS_SAMVID = "SamVid"
    STATUS_CONVERT = "Convert"
    STATUS_FFMPEG = "FFmpeg"
    STATUS_MERGE = "Merge"


class EngineStatus:
    def __init__(self):
        self.STATUS_ARIA2 = f"Aria2 v{bot_cache['eng_versions']['aria2']}"
        self.STATUS_AIOHTTP = f"AioHttp v{bot_cache['eng_versions']['aiohttp']}"
        self.STATUS_GDAPI = f"Google-API v{bot_cache['eng_versions']['gapi']}"
        self.STATUS_QBIT = f"qBit v{bot_cache['eng_versions']['qBittorrent']}"
        self.STATUS_TGRAM = f"Pyro v{bot_cache['eng_versions']['pyrofork']}"
        self.STATUS_MEGA = f"MegaAPI v{bot_cache['eng_versions']['mega']}"
        self.STATUS_YTDLP = f"yt-dlp v{bot_cache['eng_versions']['yt-dlp']}"
        self.STATUS_FFMPEG = f"ffmpeg v{bot_cache['eng_versions']['ffmpeg']}"
        self.STATUS_7Z = f"7z v{bot_cache['eng_versions']['7z']}"
        self.STATUS_RCLONE = f"RClone v{bot_cache['eng_versions']['rclone']}"
        self.STATUS_QUEUE = "QSystem v2"
        self.STATUS_JD = "JDownloader v2"


STATUSES = {
    "ALL": "All",
    "DL": MirrorStatus.STATUS_DOWNLOAD,
    "UP": MirrorStatus.STATUS_UPLOAD,
    "QD": MirrorStatus.STATUS_QUEUEDL,
    "QU": MirrorStatus.STATUS_QUEUEUP,
    "AR": MirrorStatus.STATUS_ARCHIVE,
    "EX": MirrorStatus.STATUS_EXTRACT,
    "SD": MirrorStatus.STATUS_SEED,
    "CL": MirrorStatus.STATUS_CLONE,
    "CM": MirrorStatus.STATUS_CONVERT,
    "SP": MirrorStatus.STATUS_SPLIT,
    "SV": MirrorStatus.STATUS_SAMVID,
    "FF": MirrorStatus.STATUS_FFMPEG,
    "PA": MirrorStatus.STATUS_PAUSED,
    "CK": MirrorStatus.STATUS_CHECK,
}


async def get_task_by_gid(gid: str):
    async with task_dict_lock:
        for tk in task_dict.values():
            if hasattr(tk, "seeding"):
                await tk.update()
            if tk.gid() == gid:
                return tk
        return None


async def get_specific_tasks(status, user_id):
    if status == "All":
        if user_id:
            return [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        else:
            return list(task_dict.values())
    tasks_to_check = (
        [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        if user_id
        else list(task_dict.values())
    )
    coro_tasks = []
    coro_tasks.extend(tk for tk in tasks_to_check if iscoroutinefunction(tk.status))
    coro_statuses = await gather(*[tk.status() for tk in coro_tasks])
    result = []
    coro_index = 0
    for tk in tasks_to_check:
        if tk in coro_tasks:
            st = coro_statuses[coro_index]
            coro_index += 1
        else:
            st = tk.status()
        if (st == status) or (
            status == MirrorStatus.STATUS_DOWNLOAD and st not in STATUSES.values()
        ):
            result.append(tk)
    return result


async def get_all_tasks(req_status: str, user_id):
    async with task_dict_lock:
        return await get_specific_tasks(req_status, user_id)


def get_raw_file_size(size):
    num, unit = size.split()
    return int(float(num) * (1024 ** SIZE_UNITS.index(unit)))


def get_readable_file_size(size_in_bytes):
    if not size_in_bytes:
        return "0B"

    index = 0
    while size_in_bytes >= 1024 and index < len(SIZE_UNITS) - 1:
        size_in_bytes /= 1024
        index += 1

    return f"{size_in_bytes:.2f}{SIZE_UNITS[index]}"


def get_readable_time(seconds: int):
    periods = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
    result = ""
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f"{int(period_value)}{period_name}"
    return result


def get_raw_time(time_str: str) -> int:
    time_units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(
        int(value) * time_units[unit]
        for value, unit in findall(r"(\d+)([dhms])", time_str)
    )


def time_to_seconds(time_duration):
    try:
        parts = time_duration.split(":")
        if len(parts) == 3:
            hours, minutes, seconds = map(float, parts)
        elif len(parts) == 2:
            hours = 0
            minutes, seconds = map(float, parts)
        elif len(parts) == 1:
            hours = 0
            minutes = 0
            seconds = float(parts[0])
        else:
            return 0
        return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return 0


def speed_string_to_bytes(size_text: str):
    size = 0
    size_text = size_text.lower()
    if "k" in size_text:
        size += float(size_text.split("k")[0]) * 1024
    elif "m" in size_text:
        size += float(size_text.split("m")[0]) * 1048576
    elif "g" in size_text:
        size += float(size_text.split("g")[0]) * 1073741824
    elif "t" in size_text:
        size += float(size_text.split("t")[0]) * 1099511627776
    elif "b" in size_text:
        size += float(size_text.split("b")[0])
    return size


def get_progress_bar_string(pct):
    pct = float(str(pct).strip("%"))
    p = min(max(pct, 0), 100)
    c_p = int(p / 10)
    p_str = "⬢" * c_p
    p_str += "⬡" * (10 - c_p)
    return f"〘{p_str}〙"


async def get_readable_message(sid, is_user, page_no=1, status="All", page_step=1):
    msg = ""
    button = None

    tasks = await get_specific_tasks(status, sid if is_user else None)

    STATUS_LIMIT = Config.STATUS_LIMIT
    tasks_no = len(tasks)
    pages = (max(tasks_no, 1) + STATUS_LIMIT - 1) // STATUS_LIMIT
    if page_no > pages:
        page_no = (page_no - 1) % pages + 1
        status_dict[sid]["page_no"] = page_no
    elif page_no < 1:
        page_no = pages - (abs(page_no) % pages)
        status_dict[sid]["page_no"] = page_no
    start_position = (page_no - 1) * STATUS_LIMIT

    total_dl = 0
    total_ul = 0
    for tk in tasks:
        try:
            if iscoroutinefunction(tk.status):
                st = await tk.status()
            else:
                st = tk.status()
            sp = speed_string_to_bytes(tk.speed())
            if st == MirrorStatus.STATUS_DOWNLOAD or st == MirrorStatus.STATUS_ARCHIVE:
                total_dl += sp
            elif st == MirrorStatus.STATUS_UPLOAD or st == MirrorStatus.STATUS_SEED:
                total_ul += sp
        except:
            pass

    for index, task in enumerate(
        tasks[start_position : STATUS_LIMIT + start_position], start=1
    ):
        if status != "All":
            tstatus = status
        elif iscoroutinefunction(task.status):
            tstatus = await task.status()
        else:
            tstatus = task.status()

        msg += f"{index + start_position}. {escape(f'{task.name()}')}\n"
        msg += f"<b>By:</b> {task.listener.message.from_user.mention(style='html')} [<code>{task.listener.message.from_user.id}</code>]\n"

        if (
            tstatus not in [MirrorStatus.STATUS_SEED, MirrorStatus.STATUS_QUEUEUP]
            and task.listener.progress
        ):
            progress = task.progress()
            msg += f"╭ <a href='{task.listener.message.link if task.listener.is_super_chat else ''}'>{tstatus} » {progress}</a>"
            msg += f"\n┊ {get_progress_bar_string(progress)}"
            if task.listener.subname:
                msg += f"\n┊ <b>{task.processed_bytes()} of {task.size()}</b> / {get_readable_file_size(task.listener.subsize)}"
            else:
                msg += f"\n┊ <b>{task.processed_bytes()} of {task.size()}</b>"
            if task.listener.total_count > 1 and task.status() != MirrorStatus.STATUS_UPLOAD:
                msg += f"\n┊ <b>Cᴏᴜɴᴛ:</b> {task.listener.proceed_count}/{task.listener.total_count}"
            msg += f"\n┊ <b>Sᴘᴇᴇᴅ:</b> {task.speed()}"
            msg += f"\n┊ <b>ETA:</b> {task.eta()}"
            msg += f"\n┊ <b>Pᴀsᴛ:</b> {get_readable_time(time() - task.listener.message.date.timestamp() + get_raw_time(task.eta()))}"
            msg += f"\n┊ <b>Eɴɢɪɴᴇ:</b> {task.engine}"
            msg += f"\n┊ <b>Mᴏᴅᴇ:</b> {task.listener.mode[1]}\n"
        elif tstatus == MirrorStatus.STATUS_SEED:
            msg += f"╭ Sᴇᴇᴅɪɴɢ » {task.ratio()}"
            msg += f"\n┊ {get_progress_bar_string(100)}"
            msg += f"\n┊ <b>Sɪᴢᴇ:</b> {task.size()}"
            msg += f"\n┊ <b>Sᴘᴇᴇᴅ:</b> {task.seed_speed()}"
            msg += f"\n┊ <b>Uᴘʟᴏᴀᴅᴇᴅ:</b> {task.uploaded_bytes()}"
            msg += f"\n╰ <b>Pᴀsᴛ:</b> {get_readable_time(time() - task.listener.message.date.timestamp())}\n"
        else:
            msg += f"╭ <b>Status:</b> {tstatus}\n"
            msg += f"╰ <b>Size:</b> {task.size()}\n"

        msg += f"╰ /{BotCommands.CancelTaskCommand[1]}_{task.gid()}\n\n"

    if len(msg) == 0:
        if status == "All":
            return None, None
        else:
            msg = f"No Active {status} Tasks!\n\n"

    buttons = ButtonMaker()
    if not is_user:
        buttons.data_button("☲", f"status {sid} ov", position="header")
    if len(tasks) > STATUS_LIMIT:
        msg += f"<b>Page:</b> {page_no}/{pages} | <b>Tasks:</b> {tasks_no} | <b>Step:</b> {page_step}\n"
        buttons.data_button("<<", f"status {sid} pre", position="header")
        buttons.data_button(">>", f"status {sid} nex", position="header")
        if tasks_no > 30:
            for i in [1, 2, 4, 6, 8, 10, 15]:
                buttons.data_button(i, f"status {sid} ps {i}", position="footer")
    if status != "All" or tasks_no > 20:
        for label, status_value in list(STATUSES.items()):
            if status_value != status:
                buttons.data_button(label, f"status {sid} st {status_value}")
    buttons.data_button("♻️", f"status {sid} ref", position="header")
    button = buttons.build_menu(8)
    msg += "\n〄 <b>Sʏsᴛᴇᴍ Sᴛᴀᴛɪsᴛɪᴄs...</b>"
    msg += f"\n╭ <b>Cᴘᴜ:</b> {cpu_percent()}% | <b>F:</b> {get_readable_file_size(disk_usage(DOWNLOAD_DIR).free)}"
    msg += f"\n┊ <b>Rᴀᴍ:</b> {virtual_memory().percent}% | <b>Uᴘ:</b> {get_readable_time(time() - bot_start_time)}"
    msg += f"\n┊ 🔻 <b>Total DL:</b> {get_readable_file_size(total_dl)}/s"
    msg += f"\n╰ 🔺 <b>Total UL:</b> {get_readable_file_size(total_ul)}/s"
    return msg, button
