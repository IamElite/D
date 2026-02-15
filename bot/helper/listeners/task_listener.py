from asyncio import gather, sleep
from html import escape
from time import time
from mimetypes import guess_type
from contextlib import suppress
from os import path as ospath

from aiofiles.os import listdir, remove, path as aiopath
from requests import utils as rutils

from ... import (
    intervals,
    task_dict,
    task_dict_lock,
    LOGGER,
    non_queued_up,
    non_queued_dl,
    queued_up,
    queued_dl,
    queue_dict_lock,
    same_directory_lock,
    DOWNLOAD_DIR,
)
from ..common import TaskConfig, SUPPORTED_UPHOSTERS
from ...core.tg_client import TgClient
from ...core.config_manager import Config
from ...core.torrent_manager import TorrentManager
from ..ext_utils.bot_utils import encode_slink, sync_to_async
from ..ext_utils.db_handler import database
from ..ext_utils.files_utils import (
    clean_download,
    clean_target,
    create_recursive_symlink,
    get_path_size,
    join_files,
    remove_excluded_files,
    move_and_merge,
)
from ..ext_utils.links_utils import is_gdrive_id
from ..ext_utils.status_utils import get_readable_file_size, get_readable_time
from ..ext_utils.task_manager import check_running_tasks, start_from_queued
from ..mirror_leech_utils.gdrive_utils.upload import GoogleDriveUpload
from ..mirror_leech_utils.rclone_utils.transfer import RcloneTransferHelper
from ..mirror_leech_utils.status_utils.gdrive_status import GoogleDriveStatus
from ..mirror_leech_utils.status_utils.queue_status import QueueStatus
from ..mirror_leech_utils.status_utils.rclone_status import RcloneStatus
from ..mirror_leech_utils.status_utils.telegram_status import TelegramStatus
from ..mirror_leech_utils.status_utils.uphoster_status import UphosterStatus
from ..mirror_leech_utils.upload_utils.telegram_uploader import TelegramUploader
from ..mirror_leech_utils.upload_utils.uphoster_uploader import UphosterUploader
from ...modules.users_settings import SUPPORTED_UPHOSTERS
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.message_utils import (
    delete_message,
    delete_status,
    send_message,
    update_status_message,
)
from ...core.startup import update_aria2_options, update_qb_options


class TaskListener(TaskConfig):
    def __init__(self):
        super().__init__()

    async def clean(self):
        with suppress(Exception):
            if st := intervals["status"]:
                for intvl in list(st.values()):
                    intvl.cancel()
            intervals["status"].clear()
            await gather(TorrentManager.aria2.purgeDownloadResult(), delete_status())
            # Auto-Scale Down to Eco Mode when Idle
            LOGGER.info("No active tasks. Switching to Eco Mode (Low CPU/RAM).")
            await update_aria2_options(force_mode=False)
            await update_qb_options(force_mode=False)

    def clear(self):
        self.subname = ""
        self.subsize = 0
        self.files_to_proceed = []
        self.proceed_count = 0
        self.progress = True

    async def remove_from_same_dir(self):
        async with task_dict_lock:
            if (
                self.folder_name
                and self.same_dir
                and self.mid in self.same_dir[self.folder_name]["tasks"]
            ):
                self.same_dir[self.folder_name]["tasks"].remove(self.mid)
                self.same_dir[self.folder_name]["total"] -= 1

    async def on_download_start(self):
        # Auto-Scale Up to Performance Mode (if enabled) when First Task Starts
        async with task_dict_lock:
             if len(task_dict) == 0 and Config.HIGH_PERFORMANCE_MODE:
                 LOGGER.info("First task started. Switching to High Performance Mode.")
                 await update_aria2_options(force_mode=True)
                 await update_qb_options(force_mode=True)

        mode_name = "Leech" if self.is_leech else "Mirror"
        if self.bot_pm and self.is_super_chat:
            self.pm_msg = await send_message(
                self.user_id,
                f"""➲ <b><u>Task Started :</u></b>
➲ <b>Link:</b> <a href='{self.source_url}'>Click Here</a>
""",
            )
        if Config.LINKS_LOG_ID:
            await send_message(
                Config.LINKS_LOG_ID,
                f"""➲  <b><u>{mode_name} Started:</u></b>
 
 ╭ <b>User :</b> {self.tag} ( #ID{self.user_id} )
 ┊ <b>Message Link :</b> <a href='{self.message.link}'>Click Here</a>
 ╰ <b>Link:</b> <a href='{self.source_url}'>Click Here</a>
 """,
            )
        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            with suppress(Exception):
                await database.add_incomplete_task(
                    self.message.chat.id, self.message.link, self.tag
                )

    async def on_download_complete(self):
        await sleep(2)
        if self.is_cancelled:
            return
        multi_links = False
        if (
            self.folder_name
            and self.same_dir
            and self.mid in self.same_dir[self.folder_name]["tasks"]
        ):
            async with same_directory_lock:
                while True:
                    async with task_dict_lock:
                        if self.mid not in self.same_dir[self.folder_name]["tasks"]:
                            return
                        if (
                            self.same_dir[self.folder_name]["total"] <= 1
                            or len(self.same_dir[self.folder_name]["tasks"]) > 1
                        ):
                            if self.same_dir[self.folder_name]["total"] > 1:
                                self.same_dir[self.folder_name]["tasks"].remove(
                                    self.mid
                                )
                                self.same_dir[self.folder_name]["total"] -= 1
                                spath = f"{self.dir}{self.folder_name}"
                                des_id = list(self.same_dir[self.folder_name]["tasks"])[
                                    0
                                ]
                                des_path = f"{DOWNLOAD_DIR}{des_id}{self.folder_name}"
                                LOGGER.info(f"Moving files from {self.mid} to {des_id}")
                                await move_and_merge(spath, des_path, self.mid)
                                multi_links = True
                            elif self.zip_all:
                                des_id = list(self.same_dir[self.folder_name]["tasks"])[0]
                                if self.mid != des_id:
                                    multi_links = True
                            break
                    await sleep(1)
        async with task_dict_lock:
            if self.is_cancelled:
                return
            if self.mid not in task_dict:
                return
            download = task_dict[self.mid]
            self.name = download.name()
            gid = download.gid()
        LOGGER.info(f"Download completed: {self.name}")

        if not (self.is_torrent or self.is_qbit):
            self.seed = False

        if multi_links:
            self.seed = False
            await self.on_upload_error(
                f"{self.name} Downloaded!\n\nWaiting for other tasks to finish..."
            )
            return
        elif self.same_dir:
            self.seed = False

        if self.folder_name:
            self.name = self.folder_name.strip("/").split("/", 1)[0]

        if not await aiopath.exists(f"{self.dir}/{self.name}"):
            try:
                files = await listdir(self.dir)
                self.name = files[-1]
                if self.name == "yt-dlp-thumb":
                    self.name = files[0]
            except Exception as e:
                await self.on_upload_error(str(e))
                return

        dl_path = f"{self.dir}/{self.name}"
        self.size = await get_path_size(dl_path)
        self.is_file = await aiopath.isfile(dl_path)

        if self.seed:
            up_dir = self.up_dir = f"{self.dir}10000"
            up_path = f"{self.up_dir}/{self.name}"
            await create_recursive_symlink(self.dir, self.up_dir)
            LOGGER.info(f"Shortcut created: {dl_path} -> {up_path}")
        else:
            up_dir = self.dir
            up_path = dl_path

        await remove_excluded_files(self.up_dir or self.dir, self.excluded_extensions)

        if not Config.QUEUE_ALL:
            async with queue_dict_lock:
                if self.mid in non_queued_dl:
                    non_queued_dl.remove(self.mid)
            await start_from_queued()

        if self.join and not self.is_file:
            await join_files(up_path)

        if self.extract:
            up_path = await self.proceed_extract(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()
            await remove_excluded_files(up_dir, self.excluded_extensions)

        if self.ffmpeg_cmds:
            up_path = await self.proceed_ffmpeg(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.is_leech:
           up_path = await self.proceed_metadata(up_path, gid)
           if self.is_cancelled:
               return
           self.is_file = await aiopath.isfile(up_path)
           self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
           self.size = await get_path_size(up_dir)
           self.clear()

        if self.is_leech and self.is_file:
            fname = ospath.basename(up_path)
            self.file_details["filename"] = fname
            self.file_details["mime_type"] = (guess_type(fname))[
                0
            ] or "application/octet-stream"

        if self.name_swap:
            up_path = await self.substitute(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]

        if self.screen_shots or self.screenshot_timestamps:
            up_path = await self.generate_screenshots(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)

        if self.convert_audio or self.convert_video:
            up_path = await self.convert_media(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.sample_video:
            up_path = await self.generate_sample_video(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.compress:
            up_path = await self.proceed_compress(
                up_path,
                gid,
            )
            self.is_file = await aiopath.isfile(up_path)
            if self.is_cancelled:
                return
            self.clear()

        self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
        self.size = await get_path_size(up_dir)

        if self.is_leech and not self.compress:
            await self.proceed_split(up_path, gid)
            if self.is_cancelled:
                return
            self.clear()

        self.subproc = None

        add_to_queue, event = await check_running_tasks(self, "up")
        await start_from_queued()
        if add_to_queue:
            LOGGER.info(f"Added to Queue/Upload: {self.name}")
            async with task_dict_lock:
                task_dict[self.mid] = QueueStatus(self, gid, "Up")
            await event.wait()
            if self.is_cancelled:
                return
            LOGGER.info(f"Start from Queued/Upload: {self.name}")

        self.size = await get_path_size(up_dir)

        if self.is_leech:
            LOGGER.info(f"Leech Name: {self.name}")
            tg = TelegramUploader(self, up_dir)
            async with task_dict_lock:
                task_dict[self.mid] = TelegramStatus(self, tg, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                tg.upload(),
            )
            del tg

        elif self.up_dest in SUPPORTED_UPHOSTERS["download"] or self.up_dest in SUPPORTED_UPHOSTERS["stream"] or self.up_dest.lower() == "all":
            LOGGER.info(f"Uphoster Upload Name: {self.name} to {self.up_dest}")
            uphoster = UphosterUploader(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = UphosterStatus(self, uphoster, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                uphoster.upload()
            )
            del uphoster
        elif is_gdrive_id(self.up_dest):
            LOGGER.info(f"Gdrive Upload Name: {self.name}")
            drive = GoogleDriveUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = GoogleDriveStatus(self, drive, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                sync_to_async(drive.upload),
            )
            del drive
        else:
            LOGGER.info(f"Rclone Upload Name: {self.name}")
            RCTransfer = RcloneTransferHelper(self)
            async with task_dict_lock:
                task_dict[self.mid] = RcloneStatus(self, RCTransfer, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                RCTransfer.upload(up_path),
            )
            del RCTransfer
        return

    async def on_upload_complete(
        self, link, files, folders, mime_type, rclone_path="", dir_id=""
    ):
        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)
        msg = (
            f"<b><i>{escape(self.name)}</i></b>\n"
            f"\n╭ <b>Task Size</b> → {get_readable_file_size(self.size)}"
            f"\n┊ <b>Time Taken</b> → {get_readable_time(time() - self.message.date.timestamp())}"
            f"\n┊ <b>In Mode</b> → {self.mode[0]}"
            f"\n┊ <b>Out Mode</b> → {self.mode[1]}"
        )
        LOGGER.info(f"Task Done: {self.name}")
        if self.is_leech:
            msg += f"\n┊ <b>Total Files</b> → {folders}"
            if mime_type != 0:
                msg += f"\n┊ <b>Corrupted Files</b> → {mime_type}"
            msg += f"\n╰ <b>Task By</b> → {self.tag}\n\n"

            if self.bot_pm:
                pmsg = msg
                pmsg += "〶 <b><u>Action Performed :</u></b>\n"
                pmsg += "⋗ <i>File(s) have been sent to User PM</i>\n\n"
                if self.is_super_chat:
                    await send_message(self.message, pmsg)
            elif not files and not self.is_super_chat:
                await send_message(self.message, msg)
            else:
                log_chat = self.user_id if self.bot_pm else self.message
                msg += "〶 <b><u>Files List :</u></b>\n"
                fmsg = ""
                for index, (link, name) in enumerate(files.items(), start=1):
                    chat_id, msg_id = link.split("/")[-2:]
                    fmsg += f"{index}. <a href='{link}'>{name}</a>"
        elif self.zip_all:
             msg += f"\n┊ <b>File Name</b> → {self.name}"
             msg += f"\n┊ <b>Total Files</b> → {self.same_dir[self.folder_name]['total'] if self.same_dir and self.folder_name in self.same_dir else 1}"
             msg += f"\n┊ <b>Total Size</b> → {get_readable_file_size(self.size)}"
             msg += f"\n╰ <b>Task By</b> → {self.tag}\n\n"
             if self.bot_pm:
                 pmsg = msg
                 pmsg += "〶 <b><u>Action Performed :</u></b>\n"
                 pmsg += "⋗ <i>File(s) have been sent to User PM</i>\n\n"
                 if self.is_super_chat:
                      await send_message(self.message, pmsg)
                 final_sent_msg = await send_message(self.user_id, msg)
             else:
                 final_sent_msg = await send_message(self.message, msg)
             
             if self.up_dest.lower() == "all" and final_sent_msg:
                 await send_message(final_sent_msg, link)
             
             # Skip the rest as we handled it
             await self.clean()
             return

        else:
            msg += f"\n╰ <b>Type</b> → {mime_type}"
            if mime_type == "Folder":
                msg += f"\n╭ <b>SubFolders</b> → {folders}"
                msg += f"\n╰ <b>Files</b> → {files}"
            if (
                link
                or rclone_path
                and Config.RCLONE_SERVE_URL
                and not self.private_link
            ):
                buttons = ButtonMaker()
                if link and (Config.SHOW_CLOUD_LINK or self.up_dest in SUPPORTED_UPHOSTERS["download"] or self.up_dest in SUPPORTED_UPHOSTERS["stream"]):
                    btn_name = f"☁️ {self.up_dest} Link" if self.up_dest in SUPPORTED_UPHOSTERS["download"] or self.up_dest in SUPPORTED_UPHOSTERS["stream"] else "☁️ Cloud Link"
                    buttons.url_button(btn_name, link)
                elif not link or self.up_dest.lower() != "all":
                    msg += f"\n\nPath: <code>{rclone_path or link}</code>"
                if rclone_path and Config.RCLONE_SERVE_URL and not self.private_link:
                    remote, rpath = rclone_path.split(":", 1)
                    url_path = rutils.quote(f"{rpath}")
                    share_url = f"{Config.RCLONE_SERVE_URL}/{url_path}"
                    if mime_type == "Folder" or not share_url.endswith("/"):
                        share_url = share_url.rstrip("/")
                    buttons.url_button("🔗 Rclone Link", share_url)
                if not rclone_path and dir_id:
                    INDEX_URL = ""
                    if self.private_link:
                        INDEX_URL = self.user_dict.get("INDEX_URL", "") or ""
                    elif Config.INDEX_URL:
                        INDEX_URL = Config.INDEX_URL
                    if INDEX_URL:
                        share_url = f"{INDEX_URL}findpath?id={dir_id}"
                        buttons.url_button("⚡ Index Link", share_url)
                        if mime_type.startswith(("image", "video", "audio")):
                            share_urls = f"{INDEX_URL}findpath?id={dir_id}&view=true"
                            buttons.url_button("🌐 View Link", share_urls)
                button = buttons.build_menu(2)
            else:
                msg += f"\n┊ Path: <code>{rclone_path}</code>"
                button = None

            complete_msg = f"{msg}\n\n➾ <b>Task By</b> → {self.tag}\n\n"
            group_msg = (
                complete_msg + "〶 <b><u>Action Performed :</u></b>\n"
                "⋗ <i>Cloud link(s) have been sent to User PM</i>\n\n"
            )

            chat_type = self.message.chat.type
            chat_type_str = str(chat_type)
            if hasattr(chat_type, "value"):
                chat_type_str = chat_type.value
            chat_type_str = chat_type_str.lower()
            is_private_chat = chat_type_str == "private"
            is_group_chat = chat_type_str in ("group", "supergroup")
            final_sent_msg = None
            if self.bot_pm and is_group_chat:
                await send_message(self.message, group_msg)
                final_sent_msg = await send_message(self.user_id, msg, button)
            elif self.bot_pm and is_private_chat:
                final_sent_msg = await send_message(self.user_id, msg, button)
            elif not self.bot_pm and is_group_chat:
                final_sent_msg = await send_message(self.message, complete_msg, button)
            elif not self.bot_pm and is_private_chat:
                final_sent_msg = await send_message(self.message, msg, button)
            else:
                final_sent_msg = await send_message(self.message, complete_msg, button)

            if self.up_dest.lower() == "all" and final_sent_msg:
                await send_message(final_sent_msg, link)

            mirror_log_id = getattr(Config, "MIRROR_LOG_ID", None)
            if mirror_log_id:
                try:
                    await send_message(mirror_log_id, complete_msg, button)
                except Exception as e:
                    LOGGER.error(
                        f"[TaskListener] Failed to send to MIRROR_LOG_ID: {mirror_log_id} - {e}"
                    )

        if self.seed:
            await clean_target(self.up_dir)
            async with queue_dict_lock:
                if self.mid in non_queued_up:
                    non_queued_up.remove(self.mid)
            await start_from_queued()
            return

        if self.pm_msg and (not Config.DELETE_LINKS or Config.CLEAN_LOG_MSG):
            await delete_message(self.pm_msg)

        await clean_download(self.dir)
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        async with queue_dict_lock:
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()

    async def on_download_error(self, error, button=None, is_limit=False):
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        await self.remove_from_same_dir()
        msg = (
            f"""〶 <b><i><u>Limit Breached:</u></i></b>

╭ <b>Task Size</b> → {get_readable_file_size(self.size)}
┊ <b>In Mode</b> → {self.mode[0]}
┊ <b>Out Mode</b> → {self.mode[1]}
{error}"""
            if is_limit
            else f"""<i><b>〶 Download Stopped!</b></i>

╭ <b>Due To</b> → {escape(str(error))}
┊ <b>Task Size</b> → {get_readable_file_size(self.size)}
┊ <b>Time Taken</b> → {get_readable_time(time() - self.message.date.timestamp())}
┊ <b>In Mode</b> → {self.mode[0]}
┊ <b>Out Mode</b> → {self.mode[1]}
╰ <b>Task By</b> → {self.tag}"""
        )

        await send_message(self.message, msg, button)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()
        await sleep(3)
        await clean_download(self.dir)
        if self.up_dir:
            await clean_download(self.up_dir)
        if self.thumb and await aiopath.exists(self.thumb):
            await remove(self.thumb)

    async def on_upload_error(self, error):
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        await send_message(self.message, f"{self.tag} {escape(str(error))}")
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()
        await sleep(3)
        await clean_download(self.dir)
        if self.up_dir:
            await clean_download(self.up_dir)
        if self.thumb and await aiopath.exists(self.thumb):
            await remove(self.thumb)