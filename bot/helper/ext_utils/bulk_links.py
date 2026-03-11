from aiofiles import open as aiopen
from aiofiles.os import remove


def filter_links(links_list: list, bulk_start: int, bulk_end: int) -> list:
    if bulk_start != 0 and bulk_end != 0:
        links_list = links_list[bulk_start:bulk_end]
    elif bulk_start != 0:
        links_list = links_list[bulk_start:]
    elif bulk_end != 0:
        links_list = links_list[:bulk_end]
    return links_list


def _clean_link(line: str) -> str:
    line = line.strip()
    if "://" in line:
        for prefix in ["http", "magnet"]:
            if prefix in line:
                idx = line.find(prefix)
                return line[idx:].strip()
    return line


def get_links_from_message(text: str) -> list:
    links_list = text.split("\n")
    return [
        cleaned
        for item in links_list
        if (cleaned := _clean_link(item)) and len(cleaned) != 0
    ]


async def get_links_from_file(message) -> list:
    links_list = []
    text_file_dir = await message.download()
    async with aiopen(text_file_dir, "r+") as f:
        lines = await f.readlines()
        for line in lines:
            if cleaned := _clean_link(line):
                links_list.append(cleaned)
    await remove(text_file_dir)
    return links_list


async def extract_bulk_links(message, bulk_start: str, bulk_end: str) -> list:
    bulk_start = int(bulk_start)
    bulk_end = int(bulk_end)
    links_list = []
    if reply_to := message.reply_to_message:
        if (file_ := reply_to.document) and (file_.mime_type == "text/plain"):
            links_list = await get_links_from_file(reply_to)
        elif text := reply_to.text:
            links_list = get_links_from_message(text)
    return filter_links(links_list, bulk_start, bulk_end) if links_list else links_list
