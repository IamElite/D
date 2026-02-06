from ...ext_utils.status_utils import (
    MirrorStatus,
    EngineStatus,
    get_readable_file_size,
    get_readable_time,
)


class MergeStatus:
    def __init__(self, listener, obj, gid):
        self._obj = obj
        self._gid = gid
        self.listener = listener
        self.engine = EngineStatus().STATUS_YTDLP

    def gid(self):
        return self._gid

    def processed_bytes(self):
        return get_readable_file_size(self._obj.downloaded_bytes)

    def size(self):
        return get_readable_file_size(self._obj.size)

    def status(self):
        return MirrorStatus.STATUS_MERGE

    def name(self):
        return self.listener.name

    def progress(self):
        return f"{round(self._obj.progress, 2)}%"

    def speed(self):
        return f"{get_readable_file_size(self._obj.download_speed)}/s"

    def eta(self):
        return self._obj.eta

    def task(self):
        return self._obj

    def cancel_task(self):
        return self._obj.cancel_task()
