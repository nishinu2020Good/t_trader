"""Auto commit + push on file changes. Runs silently in background."""
import os
import subprocess
import time
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
WATCH_EXT = {".py", ".html", ".md", ".txt", ".gitignore"}
IGNORE_FILES = {"feishu_config.json", "trades.csv"}
DEBOUNCE = 10  # seconds to wait after last change before committing


class AutoPush(FileSystemEventHandler):
    def __init__(self):
        self.last_change = 0
        self.timer = None

    def on_modified(self, event):
        path = event.src_path
        if event.is_directory:
            return
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1]
        if ext not in WATCH_EXT or name in IGNORE_FILES:
            return
        if ".git" in path.replace("\\", "/").split("/"):
            return

        self.last_change = time.time()

    def run(self):
        while True:
            time.sleep(5)
            if self.last_change == 0:
                continue
            if time.time() - self.last_change >= DEBOUNCE:
                self._commit_and_push()
                self.last_change = 0

    def _commit_and_push(self):
        os.chdir(ROOT)
        subprocess.run(["git", "add", "-A"], capture_output=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], capture_output=True
        )
        if result.returncode == 0:
            return  # no changes

        subprocess.run(
            ["git", "commit", "-m", f"auto: {datetime.now().strftime('%H:%M')}"],
            capture_output=True,
        )
        subprocess.run(["git", "push"], capture_output=True)
        print(f"[auto-push] {datetime.now().strftime('%H:%M:%S')} 已同步到GitHub")


if __name__ == "__main__":
    os.chdir(ROOT)
    print(f"[auto-push] 启动，监控 {ROOT}")
    print(f"[auto-push] 首次推送...")

    # Push any pending changes first
    subprocess.run(["git", "add", "-A"], capture_output=True)
    r = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if r.returncode != 0:
        subprocess.run(
            ["git", "commit", "-m", f"auto: startup {datetime.now().strftime('%H:%M')}"],
            capture_output=True,
        )
        subprocess.run(["git", "push"], capture_output=True)
        print("[auto-push] 启动推送完成")

    handler = AutoPush()
    observer = Observer()
    observer.schedule(handler, ROOT, recursive=True)
    observer.start()
    print("[auto-push] 监控中... (10秒无改动后自动推送)")

    try:
        handler.run()
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
        print("[auto-push] 已停止")
