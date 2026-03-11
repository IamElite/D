from aiofiles import open as aiopen
from aiofiles.os import remove
from .links_utils import is_url, is_magnet, is_rclone_path, is_gdrive_link, is_gdrive_id, is_mega_link, is_telegram_link

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

def filter_links(links_list: list, bulk_start: int, bulk_end: int) -> list:
    if bulk_start != 0 and bulk_end != 0:
        links_list = links_list[bulk_start:bulk_end]
    elif bulk_start != 0:
        links_list = links_list[bulk_start:]
    elif bulk_end != 0:
        links_list = links_list[:bulk_end]
    return links_list


def get_links_from_message(text: str) -> list:
    links_list = text.split("\n")
    return [item.strip() for item in links_list if _check_link(item)]


async def get_links_from_file(message) -> list:
    links_list = []
    text_file_dir = await message.download()
    async with aiopen(text_file_dir, "r+") as f:
        lines = await f.readlines()
        links_list.extend(line.strip() for line in lines if _check_link(line))
    await remove(text_file_dir)
    return links_list


async def extract_bulk_links(message, bulk_start, bulk_end) -> list:
    bulk_start = int(bulk_start) if bulk_start else 0
    bulk_end = int(bulk_end) if bulk_end else 0
    links_list = []
    if reply_to := message.reply_to_message:
        if (file_ := reply_to.document) and (file_.mime_type == "text/plain"):
            links_list = await get_links_from_file(reply_to)
        elif text := (reply_to.text or reply_to.caption):
            links_list = get_links_from_message(text)
    return filter_links(links_list, bulk_start, bulk_end) if links_list else links_list

