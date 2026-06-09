"""
华塑控股 000509 + 达实智能 002421 双股监控
用法: python feishu_alert.py
"""
import json
import os
import requests
import time
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

# === 配置 ===
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feishu_config.json")
with open(CONFIG_PATH, encoding="utf-8") as f:
    WEBHOOK = json.load(f)["webhook"]

STOCKS = {
    "sz000509": {
        "name": "华塑",
        "cost": 4.55,
        "buy_low": 4.35,
        "buy_high": 4.50,
        "sell_t": 4.65,
        "anti_t_sell": 5.00,
        "stop_loss": 0.01,
        "hold": 500,
    },
}


def send_feishu(text):
    try:
        r = requests.post(WEBHOOK, json={"msg_type": "text", "content": {"text": text}}, timeout=10)
        return r.status_code == 200
    except:
        return False


def get_realtime(code):
    try:
        r = requests.get("https://qt.gtimg.cn/q=" + code, timeout=10)
        f = r.text.split("~")
        if len(f) < 50:
            return None
        return {
            "price": float(f[3]),
            "prev": float(f[4]),
            "high": float(f[33]),
            "low": float(f[34]),
            "turnover": float(f[38]),
        }
    except:
        return None


def main():
    names = ", ".join(cfg["name"] for cfg in STOCKS.values())
    print("Dual monitor: {}".format(names))
    for code, cfg in STOCKS.items():
        print("{} ({}) buy{}-{} sell{} stop{} hold{}".format(
            cfg["name"], code, cfg["buy_low"], cfg["buy_high"],
            cfg["anti_t_sell"], cfg["stop_loss"], cfg["hold"]))
    print("-" * 50)

    sent = {}  # code -> set of fired signals
    last_feishu = 0
    last_print = 0

    while True:
        now = datetime.now()
        h, m = now.hour, now.minute
        wd = now.weekday()

        if wd >= 5:
            print("Weekend, exit")
            break
        if h >= 15:
            print("Market closed, exit")
            break
        if h < 9 or (h == 9 and m < 15):
            wait = max((9 * 3600 + 15 * 60) - (h * 3600 + m * 60), 60)
            print("{} pre-open, wait {}min...".format(now.strftime("%H:%M"), wait // 60))
            time.sleep(min(wait, 300))
            continue

        # Fetch both stocks
        data = {}
        for code in STOCKS:
            d = get_realtime(code)
            if d:
                data[code] = d

        if not data:
            time.sleep(5)
            continue

        # Console print every 30s
        if time.time() - last_print >= 30:
            parts = []
            for code, d in data.items():
                name = STOCKS[code]["name"]
                chg = (d["price"] - d["prev"]) / d["prev"] * 100
                parts.append("{} {:.2f}({:+.1f}%)".format(name, d["price"], chg))
            print("{} {}".format(now.strftime("%H:%M:%S"), " | ".join(parts)))
            last_print = time.time()

        # 5-min Feishu push
        if time.time() - last_feishu >= 300:
            lines = []
            for code, d in data.items():
                cfg = STOCKS[code]
                price = d["price"]
                chg = (price - d["prev"]) / d["prev"] * 100
                amp = (d["high"] - d["low"]) / d["prev"] * 100 if d["high"] > 0 else 0

                if cfg["buy_low"] <= price <= cfg["buy_high"]:
                    status = "BUY!"
                elif price >= cfg["anti_t_sell"]:
                    status = "SELL!"
                elif price <= cfg["stop_loss"]:
                    status = "STOP!"
                else:
                    status = "wait"

                lines.append("{} {:.2f} {:+.2f}% 振{:.1f}% 换{:.1f}% {}".format(
                    cfg["name"], price, chg, amp, d["turnover"], status))
            send_feishu("\n".join(lines))
            last_feishu = time.time()

        # Signals
        for code, d in data.items():
            cfg = STOCKS[code]
            price = d["price"]
            name = cfg["name"]

            if code not in sent:
                sent[code] = set()

            sigs = []
            if cfg["buy_low"] <= price <= cfg["buy_high"]:
                sigs.append("BUY: {} {:.2f} {}!".format(name, price, "买回200股" if cfg["hold"] > 0 else "建仓1手"))
            if price >= cfg["anti_t_sell"] and cfg["hold"] > 0:
                sigs.append("ANTI-T SELL: {} {:.2f} 卖底仓{}股!".format(name, price, cfg["hold"]))
            elif price >= cfg["sell_t"]:
                sigs.append("SELL: {} {:.2f} T仓止盈!".format(name, price))
            if price <= cfg["stop_loss"] and cfg["hold"] > 0:
                sigs.append("STOP: {} {:.2f} 止损!".format(name, price))
            elif price <= cfg["stop_loss"] * 1.05 and cfg["hold"] > 0:
                sigs.append("WARN: {} {:.2f} 接近止损".format(name, price))

            for sig in sigs:
                if sig not in sent[code]:
                    print("  -> Alert: " + sig)
                    for i in range(3):
                        send_feishu("NO.{}!\n{}".format(i + 1, sig))
                        time.sleep(2)
                    sent[code].add(sig)

        time.sleep(10)


if __name__ == "__main__":
    main()
