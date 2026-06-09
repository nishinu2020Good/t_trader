"""实时仪表盘 — 启动后挂在屏幕上，显示双股监控状态"""
import os
import sys
import time
import json
from datetime import datetime

STATUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "status.json")

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def main():
    clear()
    print("  小T · 实时仪表盘")
    print("  等待 feishu_alert.py 写入状态...")
    print("-" * 50)

    last_mod = 0
    while True:
        try:
            mtime = os.path.getmtime(STATUS_PATH)
        except OSError:
            mtime = 0

        if mtime > last_mod:
            last_mod = mtime
            try:
                with open(STATUS_PATH, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                time.sleep(2)
                continue

            clear()
            now_ts = datetime.now().strftime("%H:%M:%S")
            print(f"  小T · 实时仪表盘  [{now_ts}]")
            print("=" * 55)
            print(f"  大盘: {data.get('market', 'N/A')}")
            print("-" * 55)

            for stock in data.get("stocks", []):
                name = stock["name"]
                price = stock.get("price", 0)
                chg = stock.get("chg", 0)
                amp = stock.get("amp", 0)
                turnover = stock.get("turnover", 0)
                trend = stock.get("trend", "-")
                signal = stock.get("signal", "-")
                ts = stock.get("time", "")

                emoji = "[DOWN]" if chg < 0 else "[UP]" if chg > 0 else "[-]"
                bar = "█" * min(int(abs(chg) * 3), 15)

                print(f"  {emoji} {name:4s} {price:>6.2f}  {chg:>+.2f}% {bar}")
                print(f"     振幅:{amp:.1f}%  换手:{turnover:.1f}%  {trend}  [{ts}]")
                if signal and signal != "wait":
                    print(f"     >>> {signal} <<<")
                print()

            print("-" * 55)
            print(f"  刷新间隔: 10秒 | Ctrl+C 退出")

        time.sleep(3)


if __name__ == "__main__":
    main()
