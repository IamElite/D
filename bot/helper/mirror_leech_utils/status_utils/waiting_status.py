from ...ext_utils.status_utils import MirrorStatus

class WaitingStatus:
    def __init__(self, listener, obj, gid, status):
        self._listener = listener
        self._obj = obj
        self._gid = gid
        self._status = status

    def gid(self):
        return self._gid

    def progress(self):
        return self._obj.progress

    def speed(self):
        return self._obj.speed

    def name(self):
        return self._listener.name

    def size(self):
        return self._listener.size

    def eta(self):
        return self._obj.eta()

    def status(self):
        return "Waiting for others..."

    def processed_bytes(self):
        return self._obj.processed_bytes()

    def download(self):
        return self._obj
