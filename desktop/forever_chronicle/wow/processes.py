"""Whether the game runs: a process whose program lies in the client folder (Windows only; elsewhere never).

Reads the running programs' paths through the Windows API (EnumProcesses, QueryFullProcessImageNameW), so another
WoW version (e.g. retail's Wow.exe in _retail_) does not count.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def program_paths() -> list[str]:
    """The full paths of the running programs this user may query (empty outside Windows)."""
    if sys.platform != "win32":
        return []
    from ctypes import wintypes
    psapi, kernel = ctypes.WinDLL("psapi"), ctypes.WinDLL("kernel32")
    kernel.OpenProcess.restype = wintypes.HANDLE
    count = 1024
    while True:
        ids = (wintypes.DWORD * count)()
        used = wintypes.DWORD()
        if not psapi.EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(used)):
            return []
        if used.value < ctypes.sizeof(ids):
            break
        count *= 2
    paths = []
    buffer = ctypes.create_unicode_buffer(1024)
    for pid in ids[:used.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            continue
        try:
            size = wintypes.DWORD(len(buffer))
            if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                paths.append(buffer.value)
        finally:
            kernel.CloseHandle(handle)
    return paths


def game_running(client: Path | None) -> bool:
    if client is None:
        return False
    folder = str(client).rstrip("\\/").lower() + "\\"
    return any(p.lower().startswith(folder) for p in program_paths())
