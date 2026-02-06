from aiofiles.os import path as aiopath
import aiofiles
from aiohttp import ClientSession
from requests_toolbelt import MultipartEncoder
from time import time

from ...ext_utils.bot_utils import sync_to_async
from ...ext_utils.status_utils import get_readable_file_size
from ....modules.users_settings import SUPPORTED_UPHOSTERS
from ..status_utils.uphoster_status import UphosterStatus
from .... import task_dict, task_dict_lock, LOGGER

class UphosterUploader:
    def __init__(self, listener, path):
        self.__listener = listener
        self.__path = path
        self.__name = listener.name
        self.__total_size = listener.size
        self.__user_settings = listener.user_dict
        self.__processed_bytes = 0
        self.__start_time = time()
        self.__client = None

    async def upload(self):
        site_name = self.__listener.up_dest
        api_key = self.__user_settings.get(SUPPORTED_UPHOSTERS["download"].get(site_name)) or \
                  self.__user_settings.get(SUPPORTED_UPHOSTERS["stream"].get(site_name))
        
        if not api_key:
            await self.__listener.on_upload_error(f"API Key not found for {site_name}!")
            return

        LOGGER.info(f"Uploading {self.__name} to {site_name}")



        try:
            if site_name == "FreeDL":
                await self.__freedl_upload(api_key)
            else:
                await self.__listener.on_upload_error(f"Uploader not implemented for {site_name}")
        except Exception as e:
            LOGGER.error(f"Upload failed: {e}")
            await self.__listener.on_upload_error(str(e))

    async def __freedl_upload(self, api_key):
        async with ClientSession() as session:
            # Get Upload Server
            async with session.get(f"https://freedl.ink/api/upload/server?key={api_key}") as resp:
                data = await resp.json()
                if resp.status != 200 or not data.get("result"):
                    raise Exception(f"Failed to get upload server: {data}")
                upload_url = data["result"]

            # Upload File
            # Custom iterator to track progress
            async def file_sender(file_path):
                async with aiofiles.open(file_path, 'rb') as f:
                    chunk = await f.read(64 * 1024)
                    while chunk:
                        self.__processed_bytes += len(chunk)
                        yield chunk
                        chunk = await f.read(64 * 1024)

            # Note: For XFileSharing, the param with the file is usually 'file'
            from aiohttp import FormData
            data = FormData()
            data.add_field('file', file_sender(self.__path), filename=self.__name)
            data.add_field('sess_id', '')
            data.add_field('utype', 'anon')

            async with session.post(upload_url, data=data) as upload_resp:
                res = await upload_resp.json()
                
                # Handle both list and dict response formats
                if isinstance(res, list):
                    files = res
                elif isinstance(res, dict):
                    files = res.get("files", [])
                else:
                    raise Exception(f"Unexpected response format: {res}")

                if not files:
                    raise Exception(f"Upload failed: {res}")
                
                # Success
                link = files[0].get("url")
                await self.__listener.on_upload_complete(link, {link: self.__name}, None, "File", None, None)

    @property
    def speed(self):
        try:
            return self.__processed_bytes / (time() - self.__start_time)
        except Exception:
            return 0

    @property
    def processed_bytes(self):
        return self.__processed_bytes
