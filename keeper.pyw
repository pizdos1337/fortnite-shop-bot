"""Держит бота запущенным на этом ПК: без окна, перезапуск после падения, один экземпляр.
Запуск: pythonw keeper.pyw (автозапуск при входе в Windows — задача планировщика)."""
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "data" / "bot.log"

# Второй экземпляр не нужен: два бота с одним токеном мешают друг другу
lock = socket.socket()
try:
    lock.bind(("127.0.0.1", 47613))
except OSError:
    sys.exit(0)

python = Path(sys.executable).with_name("python.exe")


def kill_with_me():
    """Job object с KILL_ON_JOB_CLOSE: если keeper остановят (schtasks /End),
    бот закроется вместе с ним, а не останется висеть со старым кодом."""
    import ctypes
    from ctypes import wintypes as w

    class LIMIT(ctypes.Structure):
        _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("flags", w.DWORD),
                    ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", w.DWORD),
                    ("f", ctypes.c_size_t), ("g", w.DWORD), ("h", w.DWORD)]

    class EXT(ctypes.Structure):
        _fields_ = [("basic", LIMIT), ("io", ctypes.c_uint64 * 6),
                    ("pm", ctypes.c_size_t), ("jm", ctypes.c_size_t),
                    ("ppm", ctypes.c_size_t), ("pjm", ctypes.c_size_t)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = w.HANDLE
    k.GetCurrentProcess.restype = w.HANDLE
    k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    job = k.CreateJobObjectW(None, None)
    info = EXT()
    info.basic.flags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    k.AssignProcessToJobObject(job, k.GetCurrentProcess())   # дети наследуют job
    return job


try:
    _job = kill_with_me()
except Exception:
    _job = None
while True:
    LOG.parent.mkdir(exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > 2_000_000:
        LOG.replace(LOG.with_suffix(".old.log"))
    with open(LOG, "a", encoding="utf-8") as log:
        log.write(f"\n--- запуск {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log.flush()
        subprocess.run([str(python), "-X", "utf8", "bot.py"], cwd=ROOT, stdout=log,
                       stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(30)     # упал (нет интернета и т.п.) — пробуем снова
