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
            elif site_name == "Vidara":
                await self.__vidara_upload(api_key)
            elif site_name == "StreamUP":
                await self.__streamup_upload(api_key)
            else:
                await self.__listener.on_upload_error(f"Uploader not implemented for {site_name}")
        except Exception as e:
            LOGGER.error(f"Upload failed: {e}")
            await self.__listener.on_upload_error(str(e))

    async def __streamup_upload(self, api_key):
        async with ClientSession() as session:
            # StreamUP uses direct upload endpoint
            upload_url = "https://api.streamup.cc/v1/upload"

            # Step 2: Manual Multipart Upload
            boundary = f"----Boundary{int(time())}"
            field_name = "file"
            
            parts = [
                f'--{boundary}\r\nContent-Disposition: form-data; name="api_key"\r\n\r\n{api_key}\r\n'
            ]
            
            file_header = f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="{self.__name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
            file_footer = f'\r\n--{boundary}--\r\n'
            
            body_head = "".join(parts).encode() + file_header.encode()
            body_tail = file_footer.encode()
            total_len = len(body_head) + self.__total_size + len(body_tail)

            async def stream_body():
                yield body_head
                async with aiofiles.open(self.__path, 'rb') as f:
                    chunk = await f.read(64 * 1024)
                    while chunk:
                        self.__processed_bytes += len(chunk)
                        yield chunk
                        chunk = await f.read(64 * 1024)
                yield body_tail

            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(total_len),
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            async with session.post(upload_url, data=stream_body(), headers=headers) as upload_resp:
                if upload_resp.status != 200:
                    try:
                        err_text = await upload_resp.text()
                        LOGGER.error(f"StreamUP Upload Error {upload_resp.status}: {err_text[:500]}")
                    except:
                        pass
                    raise Exception(f"Upload server returned status {upload_resp.status}")

                try:
                    res = await upload_resp.json()
                except Exception:
                    raw_text = await upload_resp.text()
                    LOGGER.error(f"Failed to decode JSON from StreamUP. Raw response: {raw_text[:500]}")
                    raise Exception("Failed to decode JSON response from StreamUP")

                if not res.get("success", True) and "message" in res:
                    raise Exception(f"StreamUP Error: {res['message']}")

                link = res.get("filecode") or res.get("url")
                if not link:
                    raise Exception(f"Upload link not found in response: {res}")
                
                await self.__listener.on_upload_complete(link, {link: self.__name}, None, "File", "", "")

    async def __vidara_upload(self, api_key):
        async with ClientSession() as session:
            # Step 1: Get Upload Server
            async with session.get(f"https://api.vidara.so/v1/upload/server?api_key={api_key}") as resp:
                data = await resp.json()
                if resp.status != 200 or not data.get("result"):
                    raise Exception(f"Failed to get upload server: {data}")
                upload_url = data["result"]["upload_server"]

            # Step 2: Manual Multipart Upload
            boundary = f"----Boundary{int(time())}"
            field_name = "file"
            
            parts = [
                f'--{boundary}\r\nContent-Disposition: form-data; name="api_key"\r\n\r\n{api_key}\r\n'
            ]
            
            file_header = f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="{self.__name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
            file_footer = f'\r\n--{boundary}--\r\n'
            
            body_head = "".join(parts).encode() + file_header.encode()
            body_tail = file_footer.encode()
            total_len = len(body_head) + self.__total_size + len(body_tail)

            async def stream_body():
                yield body_head
                async with aiofiles.open(self.__path, 'rb') as f:
                    chunk = await f.read(64 * 1024)
                    while chunk:
                        self.__processed_bytes += len(chunk)
                        yield chunk
                        chunk = await f.read(64 * 1024)
                yield body_tail

            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(total_len),
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            async with session.post(upload_url, data=stream_body(), headers=headers) as upload_resp:
                if upload_resp.status != 200:
                    try:
                        err_text = await upload_resp.text()
                        LOGGER.error(f"Vidara Upload Error {upload_resp.status}: {err_text[:500]}")
                    except:
                        pass
                    raise Exception(f"Upload server returned status {upload_resp.status}")

                try:
                    res = await upload_resp.json()
                except Exception:
                    raw_text = await upload_resp.text()
                    LOGGER.error(f"Failed to decode JSON from Vidara. Raw response: {raw_text[:500]}")
                    raise Exception("Failed to decode JSON response from Vidara")

                link = res.get("url") or res.get("link")
                if not link:
                    f_code = res.get("filecode") or res.get("file_code")
                    if f_code:
                        if str(f_code).startswith("http"):
                            link = f_code
                        else:
                            link = f"https://vidara.so/v/{f_code}"

                if not link:
                    raise Exception(f"Upload link not found in response: {res}")
                
                await self.__listener.on_upload_complete(link, {link: self.__name}, None, "File", "", "")

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

            # Step 2: Manual Multipart Construction (to force Content-Length and avoid chunked/400 error)
            boundary = f"----Boundary{int(time())}"
            parts = [
                f'--{boundary}\r\nContent-Disposition: form-data; name="key"\r\n\r\n{api_key}\r\n',
                f'--{boundary}\r\nContent-Disposition: form-data; name="html_redirect"\r\n\r\n0\r\n',
                f'--{boundary}\r\nContent-Disposition: form-data; name="json"\r\n\r\n1\r\n'
            ]
            if sess_id:
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="sess_id"\r\n\r\n{sess_id}\r\n')
            if site_name == "FreeDL":
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="utype"\r\n\r\nprem\r\n')
            
            file_header = f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="{self.__name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
            file_footer = f'\r\n--{boundary}--\r\n'
            
            body_head = "".join(parts).encode() + file_header.encode()
            body_tail = file_footer.encode()
            total_len = len(body_head) + self.__total_size + len(body_tail)

            async def stream_body():
                yield body_head
                async with aiofiles.open(self.__path, 'rb') as f:
                    chunk = await f.read(64 * 1024)
                    while chunk:
                        self.__processed_bytes += len(chunk)
                        yield chunk
                        chunk = await f.read(64 * 1024)
                yield body_tail

            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(total_len),
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            async with session.post(upload_url, data=stream_body(), headers=headers) as upload_resp:
                if upload_resp.status != 200:
                    try:
                        err_text = await upload_resp.text()
                        LOGGER.error(f"{site_name} Upload Error {upload_resp.status}: {err_text[:500]}")
                    except:
                        pass
                    raise Exception(f"Upload server returned status {upload_resp.status}")

                try:
                    res = await upload_resp.json()
                except Exception:
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
