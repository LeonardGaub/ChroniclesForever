"""Pictures decoded off the main thread, so screenshots (4K JPEGs, ~15 ms each) and map tiles never stall the window
or the cinematic mode.

decode() reads a picture as a QImage, optionally scaled while reading (JPEG decodes at a reduced size directly).
ImageLoader runs decode() in a few worker threads and hands each result to its callback on the main thread.
QPixmap may only be made on the main thread, so callbacks get a QImage (None if the file could not be read).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QImage, QImageReader

THREADS = 2


def decode(path: str | None, size: QSize | None = None, fill: bool = False) -> QImage | None:
    """The picture at path, scaled to fit inside size (with fill: to cover it); None if it cannot be read.
    Safe in any thread."""
    if not path:
        return None
    reader = QImageReader(str(path))
    if size is not None:
        full = reader.size()
        if not full.isValid():
            return None
        mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding if fill else Qt.AspectRatioMode.KeepAspectRatio
        reader.setScaledSize(full.scaled(size, mode))
    image = reader.read()
    return None if image.isNull() else image


_pool: ThreadPoolExecutor | None = None


def _executor() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(THREADS, thread_name_prefix="images")
    return _pool


class ImageLoader(QObject):
    """Decodes pictures in worker threads; request() calls back on the main thread. clear() drops what is still
    pending (its callbacks are not called)."""

    _done = Signal(int, int, object)          # generation, ticket, QImage | None (from a worker thread)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._generation = 0
        self._ticket = 0
        self._callbacks: dict[int, Callable[[QImage | None], None]] = {}
        self._done.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    @property
    def pending(self) -> int:
        return len(self._callbacks)

    def request(self, path: str, callback: Callable[[QImage | None], None], size: QSize | None = None,
                fill: bool = False) -> None:
        self._ticket += 1
        ticket, generation = self._ticket, self._generation
        self._callbacks[ticket] = callback

        def work() -> None:
            try:
                image = decode(path, size, fill)
            except Exception:  # a broken file must not lose the callback slot
                image = None
            try:
                self._done.emit(generation, ticket, image)
            except RuntimeError:  # the loader was deleted meanwhile
                pass

        _executor().submit(work)

    def wait(self, timeout_ms: int = 10_000) -> None:
        """Blocks until every pending picture has been handed over (for tests and scripts)."""
        deadline = time.monotonic() + timeout_ms / 1000
        while self._callbacks and time.monotonic() < deadline:
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            QThread.msleep(2)

    def clear(self) -> None:
        self._generation += 1
        self._callbacks.clear()

    def _deliver(self, generation: int, ticket: int, image) -> None:
        callback = self._callbacks.pop(ticket, None)
        if callback is None or generation != self._generation:
            return
        callback(image)
