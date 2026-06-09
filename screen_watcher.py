"""实时截屏 — 每30秒拍一次屏幕，保存到 screencap.png"""
import time
import sys
import mss

OUTPUT = r"C:\Users\Administrator\Desktop\t_trader\screencap.png"

def main(interval: int = 30):
    print(f"屏幕监控启动，每{interval}秒截屏 -> {OUTPUT}")
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # 主显示器
        while True:
            sct.compressed_png = True  # 压缩PNG，更快
            sct.shot(mon=0, output=OUTPUT)  # mon=0 = 全屏
            print(".", end="", flush=True)
            time.sleep(interval)


if __name__ == "__main__":
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    main(interval)
