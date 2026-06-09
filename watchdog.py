"""小T进程守护 — 确保 feishu_alert.py 始终运行，挂了自动重启"""
import subprocess
import time
import sys
from datetime import datetime

SCRIPT = r"C:\Users\Administrator\Desktop\t_trader\feishu_alert.py"
PYTHON = sys.executable
MAX_RESTARTS = 10
RESTART_DELAY = 5  # seconds

print("  [小T守护] 启动")
print(f"  [小T守护] 监控: feishu_alert.py")
print(f"  [小T守护] 最大重启: {MAX_RESTARTS}次")

restarts = 0

while True:
    now = datetime.now()
    wd = now.weekday()
    h = now.hour

    # Only run on weekdays, only between 9:00-15:30
    if wd >= 5:
        print(f"  [小T守护] {now:%H:%M} 周末休市")
        time.sleep(3600)
        continue
    if h < 8 or h >= 16:
        wait = max(3600, (9 * 3600 - h * 3600 - now.minute * 60))
        print(f"  [小T守护] {now:%H:%M} 非交易时间，等待{wait // 60}分钟")
        time.sleep(min(wait, 3600))
        continue

    print(f"  [小T守护] {now:%H:%M:%S} 启动 feishu_alert.py (第{restarts + 1}次)")
    proc = subprocess.Popen([PYTHON, SCRIPT])

    try:
        proc.wait()
        exit_code = proc.returncode
        print(f"  [小T守护] feishu_alert.py 退出, 代码: {exit_code}")
    except KeyboardInterrupt:
        proc.terminate()
        print("  [小T守护] 收到停止信号")
        break

    restarts += 1
    if restarts >= MAX_RESTARTS:
        print(f"  [小T守护] 达到最大重启次数({MAX_RESTARTS})，停止")
        break

    print(f"  [小T守护] {RESTART_DELAY}秒后重启...")
    time.sleep(RESTART_DELAY)

print("  [小T守护] 已停止")
