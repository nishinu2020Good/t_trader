"""
华塑控股 000509 + 达实智能 002421 双股监控（每日自动驾驶）
用法: python feishu_alert.py
"""
import json
import os
import requests
import subprocess
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
        "cost": 4.44,          # 底仓有效成本
        "buy_ref": 4.56,       # 每日更新: 昨收×0.95
        "buy_zone": (4.50, 4.60),  # 买入区间
        "sell_t": 4.70,        # T仓止盈
        "base_hold": 200,      # 底仓
        "t_hold": 0,           # T仓
    },
    "sz002421": {
        "name": "达实",
        "cost": 0,
        "buy_ref": 5.50,
        "buy_zone": (5.45, 5.55),
        "sell_t": 5.65,
        "base_hold": 0,        # 还没有底仓
        "t_hold": 0,
    },
}

UNSUITABLE_TURNOVER = 3.0   # 换手<3%不适合做T
UNSUITABLE_AMP = 3.0        # 振幅<3%不适合做T

VOICE_SCRIPT = r"C:\Users\Administrator\Desktop\jarvis_say.py"


def speak(text: str) -> None:
    """Push TTS voice to JARVIS."""
    try:
        subprocess.run(["python", VOICE_SCRIPT, text], capture_output=True, timeout=12)
    except Exception:
        pass


def send_feishu(text: str) -> bool:
    try:
        r = requests.post(WEBHOOK, json={"msg_type": "text", "content": {"text": text}}, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def get_realtime(code: str) -> dict | None:
    try:
        r = requests.get("https://qt.gtimg.cn/q=" + code, timeout=10)
        f = r.text.split("~")
        if len(f) < 50:
            return None
        return {
            "price": float(f[3]),
            "prev": float(f[4]),
            "open": float(f[5]),
            "high": float(f[33]),
            "low": float(f[34]),
            "turnover": float(f[38]),
            "volume": int(f[6]),
            "outer": int(f[7]),   # 外盘
            "inner": int(f[8]),   # 内盘
        }
    except Exception:
        return None


def analyze_stock(code: str, cfg: dict, d: dict) -> dict:
    """Multi-dimension analysis for one stock."""
    price = d["price"]
    prev = d["prev"]
    chg = (price - prev) / prev * 100
    amp = (d["high"] - d["low"]) / prev * 100 if d["high"] > 0 else 0
    turnover = d["turnover"]
    vol = d["volume"]
    outer_ratio = d["outer"] / d["inner"] if d["inner"] > 0 else 1.0

    # Signal determination
    buy_lo, buy_hi = cfg["buy_zone"]
    in_buy_zone = buy_lo <= price <= buy_hi
    above_sell = price >= cfg["sell_t"]
    unsuitable = turnover < UNSUITABLE_TURNOVER or amp < UNSUITABLE_AMP

    # Trend
    if chg >= 9.5:
        trend = "涨停"
    elif chg >= 3:
        trend = "强势"
    elif chg >= 0:
        trend = "偏强"
    elif chg >= -3:
        trend = "偏弱"
    else:
        trend = "弱势"

    # Flow
    if outer_ratio > 1.2:
        flow = "多头"
    elif outer_ratio < 0.8:
        flow = "空头"
    else:
        flow = "均衡"

    return {
        "price": price,
        "chg": chg,
        "amp": amp,
        "turnover": turnover,
        "volume": vol,
        "outer_ratio": outer_ratio,
        "trend": trend,
        "flow": flow,
        "in_buy_zone": in_buy_zone,
        "above_sell": above_sell,
        "unsuitable": unsuitable,
    }


def main() -> None:
    names = ", ".join(cfg["name"] for cfg in STOCKS.values())
    print(f"T-Trader 自动驾驶启动: {names}")
    for code, cfg in STOCKS.items():
        print(f"  {cfg['name']} ({code}) 买区{cfg['buy_zone']} 止盈{cfg['sell_t']}")
    print("-" * 60)

    sent = {}
    last_feishu = 0
    last_print = 0
    last_unsuit_warn = {}  # code -> last warn time (avoid spam)

    while True:
        now = datetime.now()
        h, m = now.hour, now.minute
        wd = now.weekday()

        # Market closed
        if wd >= 5:
            print(f"[{now:%H:%M}] 周末休市")
            time.sleep(300)
            continue
        if h >= 15:
            print(f"[{now:%H:%M}] 已收盘，停止监控")
            break
        if h < 9 or (h == 9 and m < 15):
            wait_sec = max((9 * 3600 + 15 * 60) - (h * 3600 + m * 60), 30)
            print(f"[{now:%H:%M}] 盘前等待 ({wait_sec // 60}分钟)...")
            time.sleep(min(wait_sec, 300))
            continue

        # Fetch
        data = {}
        for code in STOCKS:
            d = get_realtime(code)
            if d:
                data[code] = d

        if not data:
            time.sleep(5)
            continue

        # Console output (30s)
        if time.time() - last_print >= 30:
            parts = []
            for code, d in data.items():
                cfg = STOCKS[code]
                a = analyze_stock(code, cfg, d)
                parts.append(f"{cfg['name']} {a['price']:.2f}({a['chg']:+.1f}%)")
            print(f"[{now:%H:%M:%S}] {' | '.join(parts)}")
            last_print = time.time()

        # Feishu + Voice push (5 min)
        if time.time() - last_feishu >= 300:
            lines = []
            voice_lines = []
            for code, d in data.items():
                cfg = STOCKS[code]
                a = analyze_stock(code, cfg, d)

                if a["in_buy_zone"]:
                    status = "BUY"
                elif a["above_sell"]:
                    status = "SELL"
                elif a["unsuitable"]:
                    status = "SKIP"
                else:
                    status = "wait"

                line = (f"{cfg['name']} {a['price']:.2f} {a['chg']:+.2f}% "
                        f"振{a['amp']:.1f}% 换{a['turnover']:.1f}% "
                        f"{a['trend']}/{a['flow']} {status}")
                lines.append(line)

                if a["unsuitable"]:
                    voice_lines.append(f"{cfg['name']}换手{a['turnover']:.1f}振幅{a['amp']:.1f}，不适合做T")

            full_msg = "\n".join(lines)
            send_feishu(full_msg)

            if voice_lines:
                speak("。".join(voice_lines))

            last_feishu = time.time()

        # Real-time signal alerts
        for code, d in data.items():
            cfg = STOCKS[code]
            a = analyze_stock(code, cfg, d)
            name = cfg["name"]

            if code not in sent:
                sent[code] = set()

            sigs = []

            # Unsuitability warning
            if a["unsuitable"]:
                now_ts = time.time()
                if code not in last_unsuit_warn or (now_ts - last_unsuit_warn.get(code, 0)) > 600:
                    sigs.append(f"{name}不适合做T: 换手{a['turnover']:.1f}% 振幅{a['amp']:.1f}%")
                    last_unsuit_warn[code] = now_ts

            # Buy signal
            if a["in_buy_zone"] and cfg["t_hold"] == 0:
                sigs.append(f"BUY {name} {a['price']:.2f} 买入200股正T")
            elif a["in_buy_zone"] and cfg["t_hold"] > 0:
                # Already have T position
                pass

            # Sell signal
            if a["above_sell"] and cfg["t_hold"] > 0:
                sigs.append(f"SELL {name} {a['price']:.2f} T仓止盈 +{(a['price'] - cfg['cost']) / cfg['cost'] * 100:.1f}%")
            elif a["above_sell"] and cfg["base_hold"] > 0 and cfg["t_hold"] == 0:
                sigs.append(f"{name} {a['price']:.2f} 到止盈位，但无T仓可卖")

            # Flow warning
            if a["flow"] == "空头" and a["chg"] < -2:
                sigs.append(f"{name} 空头放量下跌 外内比{a['outer_ratio']:.2f}")

            for sig in sigs:
                if sig not in sent[code]:
                    print(f"  >>> {sig}")
                    for i in range(2):
                        send_feishu(f"!!!\n{sig}")
                        time.sleep(1)
                    speak(sig)
                    sent[code].add(sig)

        time.sleep(10)


if __name__ == "__main__":
    main()
