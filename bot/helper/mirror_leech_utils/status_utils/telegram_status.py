from ...ext_utils.status_utils import (
    MirrorStatus,
    EngineStatus,
    get_readable_file_size,
    get_readable_time,
)


class TelegramStatus:
    def __init__(self, listener, obj, gid, status, hyper=False):
        self.listener = listener
        self._obj = obj
        self._size = self.listener.size
        self._gid = gid
        self._status = status
        self.engine = EngineStatus().STATUS_TGRAM + (" (HyperDL)" if hyper else "")

    def processed_bytes(self):
        return get_readable_file_size(self._obj.processed_bytes)

    def size(self):
        return get_readable_file_size(self._size)

    def status(self):
        if self._status == "up":
            return MirrorStatus.STATUS_UPLOAD
        return MirrorStatus.STATUS_DOWNLOAD

    def name(self):
        return self.listener.name

    def progress(self):
        try:
            progress_raw = self._obj.processed_bytes / self._size * 100
        except ZeroDivisionError:
            progress_raw = 0
        return f"{round(progress_raw, 2)}%"

    def speed(self):
        return f"{get_readable_file_size(self._obj.speed)}/s"

    def eta(self):
        try:
            seconds = (self._size - self._obj.processed_bytes) / self._obj.speed
            return get_readable_time(seconds)
        except ZeroDivisionError:
            return "-"

    def gid(self):
        return self._gid

    def task(self):
        return self._obj

    def count(self):
        if self.listener.is_zip_all and self.listener.folder_name and self.listener.same_dir:
            try:
                folder_data = self.listener.same_dir[self.listener.folder_name]
                done = folder_data.get("done", 0)
                remaining = folder_data["total"]
                total = done + remaining
                # Current processing is implicitly part of "remaining" active tasks or "done".
                # If we want "Processing X of Y".
                # If done=0, remaining=5. Total=5. Progress: 0/5? Or 1/5 (current).
                # Let's show "Done: X / Total: Y"
                return f"{done}/{total}"
            except Exception:
                return "0/0"
        return None
