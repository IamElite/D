import re
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


def get_links_from_message(text: str) -> list:
    if not text:
        return []
    links_list = re.findall(
        r"(?:https?|ftp)://[\n\S]+|magnet:\?[\n\S]+",
        text,
    )
    return [item.strip() for item in links_list if len(item) != 0]


async def get_links_from_file(message) -> list:
    links_list = []
    text_file_dir = await message.download()
    async with aiopen(text_file_dir, "r+") as f:
        lines = await f.readlines()
        links_list.extend(line.strip() for line in lines if len(line) != 0)
    await remove(text_file_dir)
    return links_list


async def extract_bulk_links(message, bulk_start: str, bulk_end: str) -> list:
    bulk_start = int(bulk_start)
    bulk_end = int(bulk_end)
    links_list = []
    if reply_to := message.reply_to_message:
        if (file_ := reply_to.document) and (file_.mime_type == "text/plain"):
            links_list = await get_links_from_file(reply_to)
        else:
            text = reply_to.text or reply_to.caption
            if text:
                links_list = get_links_from_message(text)
            
            entities = reply_to.entities or reply_to.caption_entities
            if entities:
                for entity in entities:
                    if entity.type.name == "TEXT_LINK":
                        links_list.append(entity.url)
                    elif entity.type.name == "URL":
                        offset = entity.offset
                        length = entity.length
                        url = text[offset : offset + length]
                        if url not in links_list:
                            links_list.append(url)

    if not links_list:
        return []
    
    # Remove duplicates while preserving order
    unique_links = []
    for link in links_list:
        if link not in unique_links:
            unique_links.append(link)

    return filter_links(unique_links, bulk_start, bulk_end)
