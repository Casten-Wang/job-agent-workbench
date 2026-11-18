"""One browser workflow across supported Web and CLI processes."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time

from offerpilot.browser.runtime import get_runtime_url

_thread_lock = threading.RLock()
_local = threading.local()


class BrowserBusyError(RuntimeError):
    pass


@contextmanager
def browser_execution(wait: float = 0.0):
    """Own the browser for one workflow.

    ``wait`` > 0 lets a short call (such as the readiness check every helper makes)
    queue behind another short call instead of failing at once; a long workflow
    still makes it give up after ``wait`` seconds with ``BrowserBusyError``.
    """
    if getattr(_local, "depth", 0):
        _local.depth += 1
        try:
            yield
        finally:
            _local.depth -= 1
        return
    got_thread_lock = _thread_lock.acquire(timeout=wait) if wait > 0 else _thread_lock.acquire(blocking=False)
    if not got_thread_lock:
        raise BrowserBusyError("浏览器正由其他后台任务使用，请先停止该任务")
    stream = None
    acquired = False
    try:
        key = hashlib.sha256(get_runtime_url().encode()).hexdigest()[:20]
        path = Path(tempfile.gettempdir()) / f"offerpilot-browser-{key}.lock"
        stream = path.open("a+b")
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
                stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BrowserBusyError("另一个 OfferPilot 进程正在使用浏览器") from exc
        else:
            import fcntl
            deadline = time.monotonic() + max(0.0, wait)
            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise BrowserBusyError("另一个 OfferPilot 进程正在使用浏览器") from exc
                    time.sleep(0.05)
        acquired = True
        _local.depth = 1
        yield
    finally:
        _local.depth = 0
        if stream is not None:
            if acquired:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()
        _thread_lock.release()
