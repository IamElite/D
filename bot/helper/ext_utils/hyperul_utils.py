from asyncio import (
    CancelledError,
    Event,
    Queue,
    create_task,
    gather,
    sleep,
    Lock,
    Semaphore,
)
from hashlib import md5 as md5_hash
from math import ceil
from os import path as ospath
from random import randint
from time import time

from aiofiles import open as aiopen
from pyrogram import raw
from pyrogram.session import Session

from ... import LOGGER
from ...core.config_manager import Config


HYPER_UL_MIN_SIZE = 50 * 1024 * 1024


class HyperTGUpload:
    _global_semaphore = Semaphore(16)

    def __init__(self):
        self.num_workers = Config.HYPER_THREADS if Config.HYPER_THREADS else 6
        self._per_task_limit = 8
        if not Config.HYPER_THREADS:
            self.num_workers = min(self.num_workers, self._per_task_limit)
        self._processed_bytes = 0
        self.file_size = 0
        self._cancel_event = Event()
        self._session_lock = Lock()
        self._sessions = []
        self._start_time = time()

    @property
    def processed_bytes(self):
        return self._processed_bytes

    @property
    def speed(self):
        elapsed = time() - self._start_time
        return self._processed_bytes / elapsed if elapsed > 0 else 0

    def cancel(self):
        self._cancel_event.set()

    async def _start_session(self, client, dc_id, auth_key, test_mode, i):
        try:
            session = Session(
                client, dc_id, auth_key, test_mode, is_media=True
            )
            await session.start()
            return session
        except Exception as e:
            LOGGER.error(f"HyperUL: Failed to start session {i}: {e}")
            return None

    async def _upload_worker(self, worker_id, client, queue, file_path, file_id, is_big, total_parts, chunk_size):
        async with self._global_semaphore:
            session = None
            try:
                dc_id = await client.storage.dc_id()
                auth_key = await client.storage.auth_key()
                test_mode = await client.storage.test_mode()
                session = await self._start_session(client, dc_id, auth_key, test_mode, worker_id)
                if not session:
                    return
                async with self._session_lock:
                    self._sessions.append(session)
            except Exception as e:
                LOGGER.error(f"HyperUL: Worker {worker_id} session init failed: {e}")
                return

            try:
                async with aiopen(file_path, "rb") as f:
                    while True:
                        part_no = -1
                        try:
                            part_no = await queue.get()
                            if part_no is None:
                                queue.task_done()
                                break

                            if self._cancel_event.is_set():
                                queue.task_done()
                                break

                            await f.seek(part_no * chunk_size)
                            data = await f.read(chunk_size)
                            if not data:
                                queue.task_done()
                                break

                            if is_big:
                                rpc = raw.functions.upload.SaveBigFilePart(
                                    file_id=file_id,
                                    file_part=part_no,
                                    file_total_parts=total_parts,
                                    bytes=data,
                                )
                            else:
                                rpc = raw.functions.upload.SaveFilePart(
                                    file_id=file_id,
                                    file_part=part_no,
                                    bytes=data,
                                )

                            for attempt in range(3):
                                try:
                                    success = await session.invoke(rpc)
                                    if success:
                                        break
                                    LOGGER.warning(
                                        f"HyperUL: Worker {worker_id} part {part_no} "
                                        f"failed attempt {attempt + 1}/3"
                                    )
                                except Exception as invoke_err:
                                    if attempt == 2:
                                        raise invoke_err
                                    await sleep(1 * (attempt + 1))

                            self._processed_bytes += len(data)
                            queue.task_done()

                        except CancelledError:
                            break
                        except Exception as e:
                            if self._cancel_event.is_set():
                                queue.task_done()
                                break

                            if part_no != -1:
                                is_transport_err = any(x in str(e).lower() for x in ["handler is closed", "broken pipe", "connection reset", "socket closed", "peer reset"]) or isinstance(e, (ConnectionError, RuntimeError, BrokenPipeError))
                                LOGGER.warning(
                                    f"HyperUL: Worker {worker_id} error on part {part_no} "
                                    f"({'transport' if is_transport_err else 'fatal'}): {e}"
                                )

                                if is_transport_err:
                                    await queue.put(part_no)
                                    queue.task_done()

                                    try:
                                        await session.stop()
                                        session = await self._start_session(client, dc_id, auth_key, test_mode, worker_id)
                                        if not session:
                                            LOGGER.error(f"HyperUL: Worker {worker_id} failed to recover session")
                                            break
                                        LOGGER.info(f"HyperUL: Worker {worker_id} recovered session successfully")
                                        continue
                                    except Exception as rec_err:
                                        LOGGER.error(f"HyperUL: Worker {worker_id} recovery failed: {rec_err}")
                                        break
                                else:
                                    queue.task_done()
                                    self._cancel_event.set()
                                    break
            finally:
                if session:
                    try:
                        await session.stop()
                        async with self._session_lock:
                            if session in self._sessions:
                                self._sessions.remove(session)
                    except:
                        pass

    async def save_file(self, client, path, progress=None, progress_args=()):
        self.file_size = ospath.getsize(path)
        file_name = ospath.basename(path)
        self._processed_bytes = 0
        self._cancel_event.clear()

        is_big = self.file_size > 10 * 1024 * 1024
        chunk_size = 512 * 1024

        total_parts = ceil(self.file_size / chunk_size)
        if total_parts > 8000:
            chunk_size = 1024 * 1024
            total_parts = ceil(self.file_size / chunk_size)

        file_id = randint(0, (2**63) - 1)

        if not Config.HYPER_THREADS:
            if self.file_size > 500 * 1024 * 1024:
                self.num_workers = 8
            if self.file_size > 2 * 1024 * 1024 * 1024:
                self.num_workers = 12

        num_workers = min(self.num_workers, total_parts, 12 if Config.HYPER_THREADS else self._per_task_limit)
        if self.file_size < HYPER_UL_MIN_SIZE:
            num_workers = 1

        LOGGER.info(
            f"HyperUL: Starting parallel upload | file={file_name} "
            f"size={(self.file_size/1024/1024):.1f}MB parts={total_parts} "
            f"workers={num_workers} chunk_size={chunk_size/1024}KB"
        )

        queue = Queue(maxsize=num_workers * 2)

        self._start_time = time()

        workers = []
        for i in range(num_workers):
            worker = create_task(
                self._upload_worker(i, client, queue, path, file_id, is_big, total_parts, chunk_size)
            )
            workers.append(worker)

        prog_task = None
        if progress:
            async def _progress_loop():
                while not self._cancel_event.is_set():
                    try:
                        await progress(self._processed_bytes, self.file_size, *progress_args)
                    except Exception:
                        pass
                    await sleep(1)
            prog_task = create_task(_progress_loop())

        try:
            for part_no in range(total_parts):
                if self._cancel_event.is_set():
                    break
                await queue.put(part_no)

            for _ in workers:
                await queue.put(None)

            await gather(*workers)

        except Exception as e:
            LOGGER.error(f"HyperUL: Upload queue failed: {e}", exc_info=True)
            self._cancel_event.set()
            return None
        finally:
            if prog_task and not prog_task.done():
                prog_task.cancel()
            await self._cleanup_sessions()

        if self._cancel_event.is_set():
            return None

        elapsed = time() - self._start_time
        speed_mbs = (self.file_size / (1024 * 1024)) / elapsed if elapsed > 0 else 0
        LOGGER.info(
            f"HyperUL: Upload complete | speed={speed_mbs:.1f}MB/s time={elapsed:.1f}s"
        )

        if is_big:
            return raw.types.InputFileBig(id=file_id, parts=total_parts, name=file_name)
        else:
            from hashlib import md5
            md5_hash = md5()
            async with aiopen(path, "rb") as f:
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    md5_hash.update(chunk)
            return raw.types.InputFile(id=file_id, parts=total_parts, name=file_name, md5_checksum=md5_hash.hexdigest())

    async def _cleanup_sessions(self):
        for session in self._sessions:
            try:
                await session.stop()
            except Exception:
                pass
        self._sessions.clear()
