"""
全市场扫描引擎 v1.0
- 扫描全部A股 ~5000只 (主板，排除创业板/科创板/B股)
- 腾讯API分批拉取，多线程并发
- 筛选: 振幅>3% 换手>3% 价格<30 非涨停非跌停
- 评分排序，输出 candidates.json
- 每5分钟自动刷新 (盘中)
用法: python screener.py
"""
import json, os, sys, time, requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

sys.stdout.reconfigure(encoding="utf-8")

# === 路径 ===
DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(DIR, "candidates.json")
STATUS_PATH = os.path.join(DIR, "status.json")
TENCENT_API = "https://qt.gtimg.cn/q="

# === 筛选参数 ===
MIN_AMP = 3.0        # 最低振幅%
MIN_TURNOVER = 3.0   # 最低换手%
MAX_PRICE = 30       # 最高股价
EXCLUDE_LIMIT = 9.5  # 排除涨跌停(不可交易)
BATCH_SIZE = 50      # 每批查询数量
WORKERS = 8          # 并发线程
SCAN_INTERVAL = 300  # 扫描间隔(秒) = 5分钟

# === 股票代码生成 ===
def generate_codes() -> list[str]:
    """生成主板全部代码，排除300/688/8xx/9xx/2xx(B股)/1xx(债)/5xx(基)"""
    codes = []
    # 上海主板 600000-605999
    for i in range(600000, 606000):
        codes.append(f"sh{i}")
    # 深圳主板 000001-003999，排除300xxx(创业板)
    for i in range(1, 4000):
        if 300000 <= i <= 301999:
            continue
        codes.append(f"sz{i:06d}")
    return codes


def fetch_batch(codes: list[str]) -> list[dict]:
    """拉取一批股票行情"""
    results = []
    try:
        url = TENCENT_API + ",".join(codes)
        r = requests.get(url, timeout=15)
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
                name = fields[1]
                price = float(fields[3])
                prev = float(fields[4])
                if price <= 0 or prev <= 0:
                    continue
                open_p = float(fields[5])
                high = float(fields[33])
                low = float(fields[34])
                volume = int(fields[6])
                amount = float(fields[37])
                turnover = float(fields[38])
                outer = int(fields[7])
                inner = int(fields[8])

                chg = round((price - prev) / prev * 100, 2)
                amp = round((high - low) / prev * 100, 2)

                # 初筛
                if amp < MIN_AMP or turnover < MIN_TURNOVER:
                    continue
                if price > MAX_PRICE or price <= 0:
                    continue
                if chg >= EXCLUDE_LIMIT or chg <= -EXCLUDE_LIMIT:
                    continue  # 涨停/跌停不可交易

                results.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "prev": prev,
                    "chg_pct": chg,
                    "open": open_p,
                    "high": high,
                    "low": low,
                    "amplitude": amp,
                    "turnover": turnover,
                    "volume": volume,
                    "amount_wan": round(amount / 10000, 0),
                    "outer": outer,
                    "inner": inner,
                })
            except (ValueError, IndexError):
                continue
    except Exception:
        pass
    return results


def score_candidate(c: dict) -> float:
    """综合评分: 振幅×3 + 换手×1.5 + 可买手数加分"""
    hands = int(2000 / (c["price"] * 100))  # ¥2000能买几手
    hands_bonus = min(hands * 5, 15)  # 最多+15
    score = c["amplitude"] * 3 + c["turnover"] * 1.5 + hands_bonus
    return round(score, 1)


def scan_full_market() -> tuple[list[dict], float, int, int]:
    """全市场扫描，返回(候选人列表, 耗时秒, 总查询数, 有效数)"""
    all_codes = generate_codes()
    batches = [all_codes[i:i+BATCH_SIZE] for i in range(0, len(all_codes), BATCH_SIZE)]

    candidates = []
    valid_count = 0
    scanned_count = 0
    lock = Lock()

    t0 = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_batch, b): b for b in batches}
        for future in as_completed(futures):
            batch_results = future.result()
            with lock:
                scanned_count += len(futures[future])
                for r in batch_results:
                    valid_count += 1
                    r["score"] = score_candidate(r)
                    r["hands"] = int(2000 / (r["price"] * 100))
                    candidates.append(r)

    elapsed = round(time.time() - t0, 1)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates, elapsed, scanned_count, valid_count


def build_output(candidates: list[dict], elapsed: float, scanned: int, valid: int) -> dict:
    """构建输出JSON"""
    now = datetime.now()
    top = candidates[:50]

    # 分类标签
    for c in top:
        if c["chg_pct"] >= 3:
            c["trend"] = "强势"
        elif c["chg_pct"] >= 0:
            c["trend"] = "偏强"
        elif c["chg_pct"] >= -3:
            c["trend"] = "偏弱"
        else:
            c["trend"] = "弱势"

        ratio = round(c["outer"] / c["inner"], 2) if c["inner"] > 0 else 1.0
        if ratio > 1.2:
            c["flow"] = "净流入"
        elif ratio < 0.8:
            c["flow"] = "净流出"
        else:
            c["flow"] = "均衡"

        c["outer_inner_ratio"] = ratio

        # 买卖区
        c["buy_zone"] = [round(c["prev"] * 0.93, 2), round(c["prev"] * 0.97, 2)]
        c["sell_zone"] = [round(c["prev"] * 0.99, 2), round(c["prev"] * 1.05, 2)]

    return {
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "weekday": now.strftime("%A"),
        "scan_duration_sec": elapsed,
        "total_codes": len(generate_codes()),
        "scanned": scanned,
        "valid_stocks": valid,
        "candidates_found": len(candidates),
        "top_count": len(top),
        "filters": {
            "min_amplitude": MIN_AMP,
            "min_turnover": MIN_TURNOVER,
            "max_price": MAX_PRICE,
            "capital": 2000,
        },
        "candidates": top,
    }


def main():
    print("=" * 60)
    print("  全市场扫描引擎 v1.0")
    codes = generate_codes()
    print(f"  股票池: {len(codes)} 只 (主板)")
    print(f"  筛选: 振幅>{MIN_AMP}% 换手>{MIN_TURNOVER}% 价<{MAX_PRICE}")
    print(f"  并发: {WORKERS}线程 每批{BATCH_SIZE}只")
    print(f"  输出: candidates.json (每{SCAN_INTERVAL}秒刷新)")
    print("=" * 60)

    while True:
        now = datetime.now()
        h, m = now.hour, now.minute
        wd = now.weekday()

        # 休市
        if wd >= 5:
            print(f"[{now:%H:%M}] 周末休市")
            time.sleep(600)
            continue
        if h >= 15:
            print(f"[{now:%H:%M}] 已收盘，写最终快照")
            candidates, elapsed, scanned, valid = scan_full_market()
            output = build_output(candidates, elapsed, scanned, valid)
            output["market_status"] = "closed"
            with open(OUTPUT, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            print(f"  收盘快照: {len(candidates)} 候选 → {OUTPUT}")
            break
        if h < 9 or (h == 9 and m < 15):
            wait = max((9*3600+15*60) - (h*3600+m*60), 30)
            print(f"[{now:%H:%M}] 盘前等待 {wait//60}分...")
            time.sleep(min(wait, 300))
            continue

        # === 盘中: 全市场扫描 ===
        print(f"[{now:%H:%M:%S}] 开始全市场扫描...")
        candidates, elapsed, scanned, valid = scan_full_market()
        output = build_output(candidates, elapsed, scanned, valid)
        output["market_status"] = "open"

        with open(OUTPUT, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        # 摘要
        top5 = candidates[:5]
        lines = [f"  #{i+1} {c['code']} {c['name']} {c['price']:.2f} 振{c['amplitude']:.1f}% 换{c['turnover']:.1f}% 评分{c['score']}" for i, c in enumerate(top5)]
        print(f"  扫描完成: {elapsed}秒 | {scanned}查询 {valid}有效 → {len(candidates)}候选")
        for line in lines:
            print(line)
        print(f"  输出: {OUTPUT}")

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
