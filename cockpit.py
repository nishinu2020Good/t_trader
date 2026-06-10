"""
小T 实时数据驾驶舱 v2.0
- 腾讯API实时拉数据
- 自动计算支撑/压力/买卖区
- 持仓盈亏追踪
- status.json 结构化输出 (给贾维斯读)
- 飞书+语音推送
用法: python cockpit.py
"""
import json, os, requests, subprocess, sys, time, math
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

# === 路径配置 ===
DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(DIR, "feishu_config.json")
STATUS_PATH = os.path.join(DIR, "status.json")
VOICE_SCRIPT = r"C:\Users\Administrator\Desktop\jarvis_say.py"
TENCENT_API = "https://qt.gtimg.cn/q="

# === 飞书 ===
try:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        WEBHOOK = json.load(f)["webhook"]
except Exception:
    WEBHOOK = None

# === 持仓 ===
POSITIONS = {
    "sz000509": {
        "name": "华塑",
        "base_shares": 200,
        "base_cost": 4.60,
        "t_shares": 0,
        "t_cost": 0,
        "total_assets": 2091,
    }
}

# === 华塑关键价位 (根据近期走势人工标注) ===
LEVELS = {
    "sz000509": {
        "strong_support": 4.31,
        "support": 4.36,
        "resistance": 5.00,
        "strong_resistance": 5.28,
        "stop_loss": 4.25,
    }
}

# === 昨收 (每日盘前更新) ===
PREV_CLOSE = {"sz000509": 4.80}

# === 市场指数 ===
INDICES = ["sh000001", "sz399001", "sz399006"]  # 上证, 深证, 创业板

def speak(text: str) -> None:
    try:
        subprocess.run(["python", VOICE_SCRIPT, text], capture_output=True, timeout=12)
    except Exception:
        pass

def send_feishu(text: str) -> bool:
    if not WEBHOOK:
        return False
    try:
        r = requests.post(WEBHOOK, json={"msg_type": "text", "content": {"text": text}}, timeout=10)
        return r.status_code == 200
    except Exception:
        return False

def fetch(codes: list[str]) -> dict:
    """拉取腾讯实时行情"""
    result = {}
    try:
        url = TENCENT_API + ",".join(codes)
        r = requests.get(url, timeout=10)
        for line in r.text.strip().splitlines():
            if "=" not in line:
                continue
            m = line.split('="')
            if len(m) < 2:
                continue
            code = line.split("=")[0].replace("v_", "")
            fields = m[1].rstrip('";').split("~")
            if len(fields) < 50:
                continue
            try:
                result[code] = {
                    "price": float(fields[3]),
                    "prev": float(fields[4]),
                    "open": float(fields[5]),
                    "high": float(fields[33]),
                    "low": float(fields[34]),
                    "volume": int(fields[6]),
                    "amount": float(fields[37]),
                    "turnover": float(fields[38]),
                    "outer": int(fields[7]),
                    "inner": int(fields[8]),
                }
            except (ValueError, IndexError):
                continue
    except Exception as e:
        pass
    return result


def build_cockpit(data: dict) -> dict:
    """构建完整驾驶舱数据"""
    now = datetime.now()
    cockpit = {
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "weekday": now.strftime("%A"),
        "market": {},
        "positions": [],
        "signals": [],
    }

    # === 市场指数 ===
    for code, d in data.items():
        if code.startswith("sh00") or code.startswith("sz39"):
            cockpit["market"][code] = {
                "name": "上证" if "000001" in code else "深证" if "399001" in code else "创业板",
                "price": d["price"],
                "chg_pct": round((d["price"] - d["prev"]) / d["prev"] * 100, 2),
            }

    # === 个股分析 ===
    for code, d in data.items():
        if code in INDICES or code.startswith("sh00") or code.startswith("sz39"):
            continue

        prev = d["prev"]
        price = d["price"]
        chg = round((price - prev) / prev * 100, 2)
        amp = round((d["high"] - d["low"]) / prev * 100, 2) if d["high"] > 0 else 0
        turnover = d["turnover"]
        outer_ratio = round(d["outer"] / d["inner"], 2) if d["inner"] > 0 else 1.0
        vol_wan = round(d["amount"] / 10000, 0)

        # 今日买卖区
        buy_lo = round(prev * 0.93, 2)
        buy_hi = round(prev * 0.97, 2)
        sell_lo = round(prev * 0.99, 2)
        sell_hi = round(prev * 1.05, 2)

        # 持仓
        pos = POSITIONS.get(code, {})
        base_val = pos.get("base_shares", 0) * price
        t_val = pos.get("t_shares", 0) * price
        base_pnl = (price - pos.get("base_cost", 0)) * pos.get("base_shares", 0)
        t_pnl = (price - pos.get("t_cost", 0)) * pos.get("t_shares", 0) if pos.get("t_shares", 0) > 0 else 0

        # 信号判定
        lv = LEVELS.get(code, {})
        signals = []
        if price <= buy_hi:
            signals.append({"type": "BUY_ZONE", "msg": f"进入买区 {buy_lo}-{buy_hi}"})
        if price >= sell_lo:
            signals.append({"type": "SELL_ZONE", "msg": f"进入卖区 {sell_lo}-{sell_hi}"})
        if lv.get("stop_loss") and price <= lv["stop_loss"]:
            signals.append({"type": "STOP_LOSS", "msg": f"触及止损 {lv['stop_loss']}"})
        if lv.get("strong_support") and price <= lv["strong_support"] * 1.02:
            signals.append({"type": "DEEP_SUPPORT", "msg": f"接近强支撑 {lv['strong_support']}"})

        # 趋势判断
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

        # 资金流向
        if outer_ratio > 1.2:
            flow = "净流入"
        elif outer_ratio < 0.8:
            flow = "净流出"
        else:
            flow = "均衡"

        entry = {
            "code": code,
            "name": pos.get("name", code),
            "price": price,
            "prev_close": prev,
            "chg_pct": chg,
            "open": d["open"],
            "high": d["high"],
            "low": d["low"],
            "amplitude": amp,
            "turnover": turnover,
            "volume_wan": vol_wan,
            "outer_inner_ratio": outer_ratio,
            "trend": trend,
            "flow": flow,
            "today_buy_zone": [buy_lo, buy_hi],
            "today_sell_zone": [sell_lo, sell_hi],
            "technical_levels": lv,
            "position": {
                "base_shares": pos.get("base_shares", 0),
                "base_cost": pos.get("base_cost", 0),
                "base_value": round(base_val, 2),
                "base_pnl": round(base_pnl, 2),
                "base_pnl_pct": round(base_pnl / (pos.get("base_cost", 1) * pos.get("base_shares", 1)) * 100, 2) if pos.get("base_shares", 0) > 0 else 0,
                "t_shares": pos.get("t_shares", 0),
                "t_cost": pos.get("t_cost", 0),
                "t_pnl": round(t_pnl, 2),
                "total_assets": pos.get("total_assets", 2091),
                "estimated_total": round(pos.get("total_assets", 2091) + base_pnl + t_pnl, 2),
            },
            "signals": signals,
        }
        cockpit["positions"].append(entry)
        cockpit["signals"].extend([{**s, "stock": pos.get("name", code)} for s in signals])

    return cockpit


def main() -> None:
    print("=" * 60)
    print("  小T 实时数据驾驶舱 v2.0")
    names = ", ".join(v["name"] for v in POSITIONS.values())
    print(f"  监控: {names}")
    print(f"  数据源: 腾讯API | 输出: status.json")
    print(f"  飞书: {'已连接' if WEBHOOK else '未配置'}")
    print("=" * 60)

    all_codes = list(POSITIONS.keys()) + INDICES
    last_feishu = 0
    last_signal = {}  # dedup signals

    while True:
        now = datetime.now()
        h, m = now.hour, now.minute
        wd = now.weekday()

        # 休市判断
        if wd >= 5:
            print(f"[{now:%H:%M}] 周末休市")
            time.sleep(300)
            continue
        if h >= 15:
            print(f"[{now:%H:%M}] 已收盘")
            # 写收盘快照
            data = fetch(all_codes)
            if data:
                cockpit = build_cockpit(data)
                cockpit["market_status"] = "closed"
                with open(STATUS_PATH, "w", encoding="utf-8") as f:
                    json.dump(cockpit, f, ensure_ascii=False, indent=2)
            break
        if h < 9 or (h == 9 and m < 15):
            wait = max((9 * 3600 + 15 * 60) - (h * 3600 + m * 60), 30)
            print(f"[{now:%H:%M}] 盘前等待 {wait//60}分...")
            time.sleep(min(wait, 300))
            continue

        # 盘中: 拉数据 → 写status.json → 推送
        data = fetch(all_codes)
        if not data:
            time.sleep(5)
            continue

        cockpit = build_cockpit(data)
        cockpit["market_status"] = "open"

        # 写 status.json (贾维斯随时 Read)
        try:
            with open(STATUS_PATH, "w", encoding="utf-8") as f:
                json.dump(cockpit, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # 打印摘要
        for p in cockpit["positions"]:
            sig_str = " ".join(s["type"] for s in p["signals"]) or "-"
            print(f"[{now:%H:%M:%S}] {p['name']} {p['price']:.2f} ({p['chg_pct']:+.2f}%) "
                  f"振{p['amplitude']:.1f}% 换{p['turnover']:.1f}% "
                  f"{p['trend']}/{p['flow']} | {sig_str} "
                  f"底仓{p['position']['base_pnl']:+.0f}")

        # 飞书推送 (每5分钟)
        if time.time() - last_feishu >= 300 and WEBHOOK:
            lines = []
            for p in cockpit["positions"]:
                lines.append(
                    f"{p['name']} {p['price']:.2f} {p['chg_pct']:+.2f}% "
                    f"振{p['amplitude']:.1f}% 换{p['turnover']:.1f}% "
                    f"{p['trend']}/{p['flow']}"
                )
                if p["signals"]:
                    for s in p["signals"]:
                        lines.append(f"  ⚡ {s['type']}: {s['msg']}")

            market_info = " | ".join(
                f"{v['name']} {v['chg_pct']:+.2f}%"
                for v in cockpit["market"].values()
            )
            lines.insert(0, f"大盘: {market_info}")

            send_feishu("\n".join(lines))
            last_feishu = time.time()

        # 实时信号推送 (秒级)
        for p in cockpit["positions"]:
            for s in p["signals"]:
                sig_key = f"{p['name']}_{s['type']}"
                if sig_key not in last_signal or time.time() - last_signal[sig_key] > 300:
                    alert = f"!!! {p['name']} {s['type']}: {s['msg']} @ {p['price']:.2f}"
                    print(f"  >>> {alert}")
                    for _ in range(2):
                        send_feishu(alert)
                        time.sleep(1)
                    speak(f"{p['name']} {s['msg']}，当前价格{p['price']:.2f}")
                    last_signal[sig_key] = time.time()

        time.sleep(10)


if __name__ == "__main__":
    main()
