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
