"""Run one foreground child; rotate bounded logs without logging argv/secrets."""
import os
import signal
import subprocess
import sys
from pathlib import Path

LIMIT = 5 * 1024 * 1024

def run(logfile, command):
    path = Path(logfile)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    def stop(signum, frame):
        if child.poll() is None:
            child.terminate()
    for name in ("SIGTERM", "SIGHUP", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    try:
        with path.open("ab", buffering=0) as output:
            while True:
                chunk = os.read(child.stdout.fileno(), 65536)
                if not chunk:
                    break
                if output.tell() + len(chunk) > LIMIT:
                    output.close()
                    previous = path.with_name(path.name + ".1")
                    os.replace(path, previous)
                    output = path.open("ab", buffering=0)
                output.write(chunk)
            output.close()
        return child.wait()
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("Uso: log-runner.py LOG COMMAND [ARG...]")
    raise SystemExit(run(sys.argv[1], sys.argv[2:]))
