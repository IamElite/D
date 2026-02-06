from aiofiles.os import path as aiopath
from aiohttp import ClientSession
from requests_toolbelt import MultipartEncoder

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
            self.__client = session # For status updates tracking if needed
            
            # Use requests_toolbelt for multipart upload with progress monitoring if possible
            # But for now, simple aiohttp post
            
            # Note: A proper progress bar requires a custom AsyncIterable or using a library that supports it with aiohttp.
            # For simplicity in this first pass, we might rely on the status object polling logical size if we can't hook directly.
            # But UphosterStatus will probably look at `self.processed_bytes`.
            
            # Simplified upload for now
            with open(self.__path, "rb") as f:
                async with session.post(upload_url, data={"file": f, "sess_id": "", "utype": "anon"}) as upload_resp:
                    res = await upload_resp.json()
                    files = res.get("files", [])
                    if not files:
                         raise Exception(f"Upload failed: {res}")
                    
                    # Success
                    link = files[0].get("url")
                    await self.__listener.on_upload_complete(link, {link: self.__name}, None, "File", None, None)

    @property
    def speed(self):
        return "0 B/s" # TODO: Implement progress tracking

    @property
    def processed_bytes(self):
        return 0 # TODO: Implement progress tracking
