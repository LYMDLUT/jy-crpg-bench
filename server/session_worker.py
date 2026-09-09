"""Run one gateway-owned server, exiting cleanly when its parent disappears."""
import os
import runpy
import signal
import sys
import threading


def watch_parent(fd):
    # Only the gateway holds the write end. EOF cannot refer to a recycled PID.
    try:
        while os.read(fd, 1):
            pass
        os.kill(os.getpid(), signal.SIGTERM)
    finally:
        os.close(fd)


if __name__ == "__main__":
    threading.Thread(target=watch_parent,
                     args=(int(os.environ["QUNXIA_PARENT_FD"]),), daemon=True).start()
    runpy.run_path(sys.argv[1], run_name="__main__")
