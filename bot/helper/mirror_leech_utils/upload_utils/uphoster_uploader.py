import aiofiles
from aiohttp import ClientSession, FormData
from time import time
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
                await self.__xfs_upload(site_name, "https://freedl.ink/api", api_key, "https://frdl.my", "file_0")
            elif site_name == "ZapUpload":
                await self.__zapupload_upload(api_key)
            elif site_name == "VidNest":
                await self.__xfs_upload(site_name, "https://vidnest.io/api", api_key, "https://vidnest.io", "file")
            else:
                await self.__listener.on_upload_error(f"Uploader not implemented for {site_name}")
        except Exception as e:
            LOGGER.error(f"Upload failed: {e}")
            await self.__listener.on_upload_error(str(e))

    async def __zapupload_upload(self, api_key):
        async with ClientSession() as session:
            # Custom iterator to track progress (reused logic)
            async def file_sender(file_path):
                async with aiofiles.open(file_path, 'rb') as f:
                    chunk = await f.read(64 * 1024)
                    while chunk:
                        self.__processed_bytes += len(chunk)
                        yield chunk
                        chunk = await f.read(64 * 1024)

            data = FormData()
            data.add_field('file', file_sender(self.__path), filename=self.__name)
            data.add_field('visibility', '1')

            headers = {"Authorization": f"Bearer {api_key}"}

            async with session.post("https://zapupload.top/api/v1/upload/binary", data=data, headers=headers) as upload_resp:
                res = await upload_resp.json()
                
                if not res.get("success"):
                    error = res.get("error", {}).get("message") or res.get("message") or "Unknown Error"
                    raise Exception(f"ZapUpload Error: {error}")

                file_data = res.get("data", {})
                link = file_data.get("share_url") or file_data.get("short_url")
                
                if not link:
                    raise Exception(f"Upload link not found in response: {res}")
                
                await self.__listener.on_upload_complete(link, {link: self.__name}, None, "File", "", "")

    async def __xfs_upload(self, site_name, api_url, api_key, base_url, field_name="file_0"):
        async with ClientSession() as session:
            # Step 1: Get Upload Server
            async with session.get(f"{api_url}/upload/server?key={api_key}") as resp:
                data = await resp.json()
                if resp.status != 200 or not data.get("result"):
                    raise Exception(f"Failed to get upload server: {data}")
                upload_url = data["result"]
                sess_id = data.get("sess_id", "")

            # Step 2: Upload File with progress tracking
            async def file_sender(file_path):
                async with aiofiles.open(file_path, 'rb') as f:
                    chunk = await f.read(64 * 1024)
                    while chunk:
                        self.__processed_bytes += len(chunk)
                        yield chunk
                        chunk = await f.read(64 * 1024)

            data = FormData()
            data.add_field(field_name, file_sender(self.__path), filename=self.__name)
            data.add_field('key', api_key)
            if sess_id:
                data.add_field('sess_id', sess_id)
            if site_name != "VidNest":
                data.add_field('utype', 'prem')
            data.add_field('html_redirect', '0')
            data.add_field('json', '1')

            async with session.post(upload_url, data=data) as upload_resp:
                if upload_resp.status != 200:
                    try:
                        err_text = await upload_resp.text()
                        LOGGER.error(f"{site_name} Upload Error {upload_resp.status}: {err_text[:500]}")
                    except:
                        pass
                    raise Exception(f"Upload server returned status {upload_resp.status}")

                try:
                    res = await upload_resp.json()
                except Exception as e:
                    raw_text = await upload_resp.text()
                    LOGGER.error(f"Failed to decode JSON from {site_name}. Raw response: {raw_text[:500]}")
                    raise Exception(f"Failed to decode JSON response from {site_name}")
                
                if isinstance(res, list):
                    files = res
                elif isinstance(res, dict):
                    files = res.get("files", [])
                else:
                    raise Exception(f"Unexpected response format from {site_name}: {res}")

                if not files:
                    raise Exception(f"Upload failed: {res}")
                
                f_data = files[0]
                if f_data.get("file_status", "").lower() == "failed":
                    error_msg = f_data.get("file_status_msg") or f_data.get("file_status")
                    raise Exception(f"Upload failed server-side: {error_msg}")

                link = f_data.get("url") or f_data.get("link")
                if link and "undef" in link.lower():
                    link = None
                
                if not link:
                    file_code = f_data.get("file_code") or f_data.get("filecode")
                    if file_code and "undef" not in str(file_code).lower():
                        link = f"{base_url}/{file_code}"
                
                if not link:
                    LOGGER.warning(f"Upload link not found in response from {site_name}: {res}")
                
                await self.__listener.on_upload_complete(link, {link: self.__name}, None, "File", "", "")

    @property
    def speed(self):
        try:
            return self.__processed_bytes / (time() - self.__start_time)
        except Exception:
            return 0

    @property
    def processed_bytes(self):
        return self.__processed_bytes
