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
ALERTS_PATH = os.path.join(DIR, "alerts.json")
VOICE_SCRIPT = r"C:\Users\Administrator\Desktop\jarvis_say.py"
TENCENT_API = "https://qt.gtimg.cn/q="

# === 飞书 ===
try:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        WEBHOOK = json.load(f)["webhook"]
except Exception:
    WEBHOOK = None

# === 持仓 (仅实际持股，观察池由screener全市场扫描动态生成) ===
POSITIONS = {
    "sz000509": {
        "name": "华塑",
        "base_shares": 500,   # 6/3:200@4.60 + 6/10:300(200@4.54+100@4.32)→T+1过夜变base
        "base_cost": 4.52,
        "t_shares": 0,
        "t_cost": 0,
        "total_assets": 2091,
    },
}

# === 持仓关键价位 (观察池由screener自动生成) ===
LEVELS = {
    "sz000509": {
        "strong_support": 4.22,
        "support": 4.36,
        "resistance": 4.80,
        "strong_resistance": 5.02,
        "stop_loss": 4.15,
    },
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


def build_cockpit(data: dict, extra_positions: dict = None) -> dict:
    """构建完整驾驶舱数据"""
    # 合并固定持仓 + 动态观察池
    all_positions = dict(POSITIONS)
    if extra_positions:
        all_positions.update(extra_positions)
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

        # 持仓/观察
        pos = all_positions.get(code, {})
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
                "watch_only": pos.get("watch_only", False),
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


CANDIDATES_PATH = os.path.join(DIR, "candidates.json")
DYNAMIC_TOP_N = 15          # 从全市场扫描中取前N只加入监控
WATCHLIST_REFRESH = 300     # 每5分钟刷新观察池


def load_dynamic_watchlist() -> dict:
    """从 candidates.json 读取全市场扫描结果，返回动态观察池"""
    dyn = {}
    try:
        if os.path.exists(CANDIDATES_PATH):
            with open(CANDIDATES_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for c in data.get("candidates", [])[:DYNAMIC_TOP_N]:
                code = c["code"]
                # 跳过已有持仓的
                if code in POSITIONS:
                    continue
                name = c["name"]
                # 自动计算技术价位
                prev = c["prev"]
                price = c["price"]
                dyn[code] = {
                    "name": name,
                    "base_shares": 0, "base_cost": 0,
                    "t_shares": 0, "t_cost": 0,
                    "total_assets": 0, "watch_only": True,
                    "from_screener": True,
                }
                # 动态生成 LEVELS
                if code not in LEVELS:
                    LEVELS[code] = {
                        "strong_support": round(prev * 0.88, 2),
                        "support": round(prev * 0.93, 2),
                        "resistance": round(prev * 1.05, 2),
                        "strong_resistance": round(prev * 1.10, 2),
                        "stop_loss": round(prev * 0.85, 2),
                    }
    except Exception:
        pass
    return dyn


# === 告警系统 ===
def build_alert(p: dict) -> dict | None:
    """为一只股票生成告警分析"""
    signals = p.get("signals", [])
    if not signals:
        return None

    pos = p.get("position", {})
    watch_only = pos.get("watch_only", False)
    name = p.get("name", "")
    price = p.get("price", 0)
    chg = p.get("chg_pct", 0)
    amp = p.get("amplitude", 0)
    levels = p.get("technical_levels", {})
    buy_zone = p.get("today_buy_zone", [0, 0])
    sell_zone = p.get("today_sell_zone", [0, 0])

    alert = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "code": p.get("code"),
        "name": name,
        "price": price,
        "chg_pct": chg,
        "amplitude": amp,
        "watch_only": watch_only,
        "signals": signals,
        "advice": [],
    }

    # 持仓告警
    if not watch_only:
        base_cost = pos.get("base_cost", 0)
        base_shares = pos.get("base_shares", 0)
        base_pnl = pos.get("base_pnl", 0)
        base_pnl_pct = pos.get("base_pnl_pct", 0)

        alert["position"] = {
            "shares": base_shares,
            "cost": base_cost,
            "pnl": base_pnl,
            "pnl_pct": base_pnl_pct,
        }

        for sig in signals:
            if sig["type"] == "BUY_ZONE":
                if base_pnl < 0 and base_shares >= 200:
                    alert["advice"].append(f"买区+浮亏{abs(base_pnl):.0f}元→补仓摊薄成本机会，建议买入200股")
                elif len(alert["advice"]) == 0:
                    alert["advice"].append(f"进入买区，关注反弹力度再决定")
            elif sig["type"] == "SELL_ZONE":
                if base_pnl > 0:
                    alert["advice"].append(f"卖区+浮盈{base_pnl:.0f}元→可卖200股锁利")
                elif base_shares >= 200:
                    alert["advice"].append(f"进入卖区，可卖200股减仓观望")
            elif sig["type"] == "STOP_LOSS":
                alert["advice"].append(f"触及止损{levels.get('stop_loss')}，建议立即清仓")
            elif sig["type"] == "DEEP_SUPPORT":
                alert["advice"].append(f"逼近强支撑{levels.get('strong_support')}，观望不割肉")

    # 观察池告警 (仅提示，不建议操作)
    else:
        for sig in signals:
            if sig["type"] == "BUY_ZONE":
                alert["advice"].append(f"观察池买区信号，值得关注")
            elif sig["type"] == "DEEP_SUPPORT":
                alert["advice"].append(f"逼近强支撑，潜在抄底候选")

    if not alert["advice"]:
        return None
    return alert


def write_alerts(alerts: list[dict]) -> None:
    """追加告警到 alerts.json (保留最近200条)"""
    try:
        existing = []
        if os.path.exists(ALERTS_PATH):
            with open(ALERTS_PATH, encoding="utf-8") as f:
                data = json.load(f)
                existing = data.get("events", [])
        existing = (existing + alerts)[-200:]
        with open(ALERTS_PATH, "w", encoding="utf-8") as f:
            json.dump({"updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "events": existing}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def speak_alert(alert: dict) -> None:
    """生成并播报智能语音告警"""
    name = alert.get("name", "")
    price = alert.get("price", 0)
    advice = alert.get("advice", [])
    watch = alert.get("watch_only", False)

    if not advice:
        return

    prefix = "观察池" if watch else ""
    msg = f"{prefix}{name} {price:.2f}。{'。'.join(advice)}"
    speak(msg)


def build_market_summary(positions: list[dict], market: dict) -> str:
    """生成大盘+持仓综合摘要"""
    lines = []

    # 大盘
    idx_str = " ".join(f"{v['name']}{v['chg_pct']:+.1f}%" for v in market.values())
    lines.append(f"大盘：{idx_str}")

    # 持仓
    for p in positions:
        pos = p.get("position", {})
        if pos.get("watch_only"):
            continue
        name = p.get("name", "")
        price = p.get("price", 0)
        chg = p.get("chg_pct", 0)
        pnl = pos.get("base_pnl", 0)
        pnl_pct = pos.get("base_pnl_pct", 0)
        sigs = " ".join(s["type"] for s in p.get("signals", [])) or "无信号"
        lines.append(f"{name} {price:.2f} {chg:+.1f}% 浮{'盈' if pnl>=0 else '亏'}{abs(pnl):.0f}元 {pnl_pct:+.1f}% {sigs}")

    # 观察池亮点
    hotspots = []
    for p in positions:
        pos = p.get("position", {})
        if not pos.get("watch_only"):
            continue
        amp = p.get("amplitude", 0)
        if amp >= 8:
            hotspots.append(f"{p['name']}振{amp:.1f}%")
    if hotspots:
        lines.append(f"活跃：{' '.join(hotspots[:5])}")

    return "。".join(lines)


def main() -> None:
    print("=" * 60)
    print("  小T 实时数据驾驶舱 v2.2 (智能告警)")
    print(f"  固定持仓: {len(POSITIONS)} 只")
    print(f"  动态观察: 全市场扫描TOP{DYNAMIC_TOP_N} (每{WATCHLIST_REFRESH}秒刷新)")
    print(f"  数据源: 腾讯API | 输出: status.json")
    print(f"  飞书: {'已连接' if WEBHOOK else '未配置'}")
    print("=" * 60)

    # 初始加载
    dynamic_watchlist = load_dynamic_watchlist()
    print(f"  初始观察池: {len(dynamic_watchlist)} 只")

    last_feishu = 0
    last_signal = {}
    last_summary = 0   # 定期大盘摘要
    last_watchlist_refresh = 0

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
            all_codes = list(POSITIONS.keys()) + list(dynamic_watchlist.keys()) + INDICES
            data = fetch(all_codes)
            if data:
                cockpit = build_cockpit(data, dynamic_watchlist)
                cockpit["market_status"] = "closed"
                cockpit["watchlist_source"] = "screener_full_market"
                with open(STATUS_PATH, "w", encoding="utf-8") as f:
                    json.dump(cockpit, f, ensure_ascii=False, indent=2)
            break
        if h < 9 or (h == 9 and m < 15):
            wait = max((9 * 3600 + 15 * 60) - (h * 3600 + m * 60), 30)
            print(f"[{now:%H:%M}] 盘前等待 {wait//60}分...")
            time.sleep(min(wait, 300))
            continue

        # === 定期刷新观察池 (从screener结果) ===
        if time.time() - last_watchlist_refresh >= WATCHLIST_REFRESH:
            new_watchlist = load_dynamic_watchlist()
            if len(new_watchlist) != len(dynamic_watchlist):
                print(f"[{now:%H:%M:%S}] 观察池更新: {len(dynamic_watchlist)} → {len(new_watchlist)} 只")
            dynamic_watchlist = new_watchlist
            last_watchlist_refresh = time.time()

        # === 合并: 固定持仓 + 动态观察池 ===
        all_codes = list(POSITIONS.keys()) + list(dynamic_watchlist.keys()) + INDICES

        # 盘中: 拉数据 → 写status.json → 推送
        data = fetch(all_codes)
        if not data:
            time.sleep(5)
            continue

        cockpit = build_cockpit(data, dynamic_watchlist)
        cockpit["market_status"] = "open"
        cockpit["watchlist_source"] = "screener_full_market"
        cockpit["watchlist_updated"] = datetime.fromtimestamp(last_watchlist_refresh).strftime("%H:%M:%S") if last_watchlist_refresh > 0 else "initial"

        # 写 status.json (贾维斯随时 Read)
        try:
            with open(STATUS_PATH, "w", encoding="utf-8") as f:
                json.dump(cockpit, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # 打印摘要 (只显示持仓+前5观察)
        for p in cockpit["positions"]:
            sig_str = " ".join(s["type"] for s in p["signals"]) or "-"
            tag = "📦" if not p["position"].get("watch_only") else "👁️"
            print(f"[{now:%H:%M:%S}] {tag} {p['name']} {p['price']:.2f} ({p['chg_pct']:+.2f}%) "
                  f"振{p['amplitude']:.1f}% 换{p['turnover']:.1f}% "
                  f"{p['trend']}/{p['flow']} | {sig_str}")

        # 飞书推送 (每5分钟，仅持仓)
        if time.time() - last_feishu >= 300 and WEBHOOK:
            lines = []
            for p in cockpit["positions"]:
                if p["position"].get("watch_only"):
                    continue  # 观察池不推飞书，太吵
                lines.append(
                    f"{p['name']} {p['price']:.2f} {p['chg_pct']:+.2f}% "
                    f"振{p['amplitude']:.1f}% 换{p['turnover']:.1f}% "
                    f"{p['trend']}/{p['flow']}"
                )
                if p["signals"]:
                    for s in p["signals"]:
                        lines.append(f"  ⚡ {s['type']}: {s['msg']}")

            if lines:
                market_info = " | ".join(
                    f"{v['name']} {v['chg_pct']:+.2f}%"
                    for v in cockpit["market"].values()
                )
                lines.insert(0, f"大盘: {market_info}")
                send_feishu("\n".join(lines))
            last_feishu = time.time()

        # === 智能告警 (贾维斯分析引擎) ===
        new_alerts = []
        for p in cockpit["positions"]:
            alert = build_alert(p)
            if not alert:
                continue
            sig_key = f"{alert['name']}_{alert['signals'][0]['type']}"
            # 去重: 同股票同信号5分钟内不重复播
            if sig_key in last_signal and time.time() - last_signal[sig_key] < 300:
                continue
            new_alerts.append(alert)
            last_signal[sig_key] = time.time()

        # 写告警文件 (贾维斯随时 Read)
        if new_alerts:
            write_alerts(new_alerts)

        # 播报: 持仓优先于观察池
        hold_alerts = [a for a in new_alerts if not a["watch_only"]]
        watch_alerts = [a for a in new_alerts if a["watch_only"]]

        for a in hold_alerts:
            print(f"  >>> [告警] {a['name']} {' '.join(s['type'] for s in a['signals'])}: {' '.join(a['advice'])}")
            send_feishu(f"!!! {a['name']} {' '.join(s['type'] for s in a['signals'])}: {' '.join(a['advice'])}")
            speak_alert(a)
            time.sleep(1)

        # 观察池告警只写文件不语音 (不吵)
        for a in watch_alerts:
            print(f"  >>> [观察] {a['name']} {' '.join(s['type'] for s in a['signals'])}")

        # === 定期大盘摘要 (每15分钟语音) ===
        if time.time() - last_summary >= 900:
            summary = build_market_summary(cockpit["positions"], cockpit["market"])
            print(f"  >>> [摘要] {summary}")
            speak(f"市场摘要。{summary}")
            last_summary = time.time()

        time.sleep(10)


if __name__ == "__main__":
    main()
