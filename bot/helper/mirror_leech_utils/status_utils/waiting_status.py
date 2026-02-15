from ...ext_utils.status_utils import get_readable_file_size, MirrorStatus, EngineStatus
from .... import LOGGER

class WaitingStatus:
    def __init__(self, listener, gid):
        self.listener = listener
        self._gid = gid
        self.engine = "Waiting..."

    def gid(self):
        return self._gid

    def name(self):
        return self.listener.name

    def size(self):
        return get_readable_file_size(self.listener.size)

    def status(self):
        return "Waiting..."

    def processed_bytes(self):
        return self.listener.size

    def progress(self):
        return "100%"

    def speed(self):
        return "0B/s"

    def eta(self):
        return "-"

    def task(self):
        return self

    async def cancel_task(self):
        self.listener.is_cancelled = True
        LOGGER.info(f"Cancelling Waiting Task: {self.listener.name}")
        await self.listener.on_upload_error("Waiting task cancelled!")
