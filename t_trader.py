"""T-Trader - A-share T+0 day trading quant tool (2000 RMB account)"""
import csv
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Any

import pandas as pd

# --- Config ---
MAX_PRICE = 18
MIN_PRICE = 3
MIN_AMPLITUDE = 3.0
MIN_TURNOVER = 5.0
STOP_LOSS = 0.02
TAKE_PROFIT = 0.015
MONITOR_INTERVAL = 30

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.csv")
TENCENT_API = "https://qt.gtimg.cn/q="

# Tencent format field indices (split by ~)
# 1=name, 2=code, 3=price, 4=prev_close, 5=open, 6=volume_hands,
# 31=change_pct, 32=high, 33=low, 36=amount_wan, 37=turnover, 38=PE, 43=amplitude


def _curl_get(url: str) -> str:
    """GET raw text via curl."""
    result = subprocess.run(
        ["curl", "-s", "--connect-timeout", "10", "--max-time", "15",
         "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
         url],
        capture_output=True, text=True, timeout=20
    )
    return result.stdout if result.returncode == 0 else ""


def _ensure_csv() -> None:
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["date", "symbol", "name", "direction", "entry_price",
                        "exit_price", "shares", "pnl_yuan", "pnl_pct"])


def _parse_tencent(raw: str) -> pd.DataFrame:
    """Parse Tencent stock API response into DataFrame."""
    rows = []
    for line in raw.strip().splitlines():
        if not line or "=" not in line:
            continue
        # Skip invalid stocks: response is all-empty fields like v_xxx="~~~~"
        if re.search(r'="~{3,}"', line):
            continue
        # Extract the quote string between quotes
        m = re.search(r'="(.+)"', line)
        if not m:
            continue
        fields = m.group(1).split("~")
        if len(fields) < 44:
            continue
        try:
            rows.append({
                "代码": fields[2],
                "名称": fields[1],
                "最新价": _f(fields[3]),
                "昨收": _f(fields[4]),
                "今开": _f(fields[5]),
                "最高": _f(fields[33]),
                "最低": _f(fields[34]),
                "涨跌幅": _f(fields[32]),
                "涨跌额": _f(fields[31]),
                "成交量": _f(fields[6]),
                "成交额": _f(fields[37]),
                "换手率": _f(fields[38]),
                "振幅": _f(fields[43]),
                "市盈率": _f(fields[39]),
            })
        except (IndexError, ValueError):
            continue
    return pd.DataFrame(rows)


def _f(val: str) -> float:
    """Safe float parse."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _fetch_stocks(codes: list[str]) -> pd.DataFrame:
    """Fetch real-time data for a list of stock codes via Tencent API."""
    # Tencent format: sz002421,sh600519
    qt_codes = []
    for c in codes:
        prefix = "sh" if c.startswith("6") else "sz"
        qt_codes.append(f"{prefix}{c}")

    # Batch by 50 codes per request
    all_rows = []
    for i in range(0, len(qt_codes), 50):
        batch = qt_codes[i:i + 50]
        url = TENCENT_API + ",".join(batch)
        raw = _curl_get(url)
        df = _parse_tencent(raw)
        if not df.empty:
            all_rows.append(df)
        time.sleep(0.3)  # rate limit

    if not all_rows:
        return pd.DataFrame()
    return pd.concat(all_rows, ignore_index=True)


def screen_candidates() -> pd.DataFrame:
    """Screen A-shares for T-trading candidates."""
    print("\n" + "=" * 70)
    print("  T-Trader - 做T候选股筛选")
    print("=" * 70)
    print(f"  条件: 价格 {MIN_PRICE}-{MAX_PRICE}元 | 振幅 >= {MIN_AMPLITUDE}% | "
          f"换手 >= {MIN_TURNOVER}% | 排除ST")
    print("-" * 70)

    # Load stock list from file or use default watchlist
    watchlist_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "watchlist.txt")
    if os.path.exists(watchlist_file):
        with open(watchlist_file, encoding="utf-8") as f:
            codes = [line.strip() for line in f if line.strip()]
    else:
        # Default: common low-price active stocks + recent hot stocks
        codes = [
            # 之前的候选 + 近期热门低价股
            "002421", "002031", "002882", "002506", "601991",
            "600726", "000539", "002129", "002579", "002251",
            "601678", "002124", "601996", "002406", "002771",
            "600635", "000759", "603363", "603995", "600396",
            # 更多活跃低价股
            "600010", "600022", "600029", "600115", "600221",
            "600307", "600376", "600383", "600410", "600415",
            "600606", "600622", "600743", "600748", "600782",
            "000001", "000002", "000100", "000401", "000425",
            "000553", "000625", "000651", "000725", "000768",
            "002024", "002050", "002065", "002081", "002092",
            "002100", "002130", "002131", "002151", "002152",
            "002156", "002157", "002158", "002161", "002166",
            "002185", "002190", "002191", "002195", "002197",
        ]

    print(f"  正在获取 {len(codes)} 只股票实时数据...")
    try:
        df = _fetch_stocks(codes)
    except Exception as e:
        print(f"  [ERROR] 数据获取失败: {e}")
        return pd.DataFrame()

    if df.empty:
        print("  [ERROR] 未获取到数据。")
        return df

    # Filter
    mask = (
        (df["最新价"] >= MIN_PRICE) & (df["最新价"] <= MAX_PRICE) &
        (df["振幅"] >= MIN_AMPLITUDE) &
        (df["换手率"] >= MIN_TURNOVER) &
        (~df["名称"].str.contains("ST|退|N", na=False))
    )
    result = df[mask].copy()

    if result.empty:
        print("  [INFO] 当前没有符合条件的股票。")
        return result

    # Score
    result["得分"] = (result["振幅"] * 3.0 +
                      result["换手率"] * 1.5 +
                      result["成交额"].apply(lambda x: math.log10(x + 1)) * 0.5)
    result["得分"] = (result["得分"] / result["得分"].max() * 100).round(1)
    result = result.sort_values("得分", ascending=False).head(20)
    result["可买手数"] = (2000 // (result["最新价"] * 100)).astype(int)

    display = ["代码", "名称", "最新价", "振幅", "换手率", "涨跌幅",
               "可买手数", "得分"]
    print(result[display].to_string(index=False))
    print("-" * 70)
    print(f"  共 {len(result)} 只候选 | {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 70 + "\n")
    return result


def _calc_signals(df_min: pd.DataFrame, open_price: float) -> list[dict]:
    """Detect T-trading signals from intraday data."""
    if df_min.empty or len(df_min) < 6:
        return []

    high = df_min["最高"].max()
    low = df_min["最低"].min()
    price_range = high - low
    if price_range <= 0:
        return []

    recent = df_min.tail(10)
    avg_vol = recent["成交量"].mean()
    last = recent.iloc[-1]
    price = last["收盘"]
    vol = last["成交量"]
    pos = (price - low) / price_range if price_range > 0 else 0.5
    pct_open = (price - open_price) / open_price * 100

    signals = []
    if pos < 0.35 and vol > avg_vol * 1.3 and pct_open < -1.5:
        signals.append({
            "type": "BUY (正T)",
            "price": price,
            "reason": f"低区{pos:.0%} 量>{1.3:.1f}x均量 距开{pct_open:+.1f}%"
        })
    if pos > 0.70 and vol > avg_vol * 1.3 and pct_open > 1.5:
        signals.append({
            "type": "SELL (反T)",
            "price": price,
            "reason": f"高区{pos:.0%} 量>{1.3:.1f}x均量 距开{pct_open:+.1f}%"
        })
    return signals


def monitor_stock(symbol: str) -> None:
    """Real-time monitor for a single stock."""
    try:
        df = _fetch_stocks([symbol])
        name = df["名称"].values[0] if not df.empty else symbol
    except Exception:
        name = symbol

    print(f"\n{'=' * 60}")
    print(f"  实时监控: {name} ({symbol})")
    print(f"  刷新: {MONITOR_INTERVAL}s | 止损:{STOP_LOSS:.0%} | 止盈:{TAKE_PROFIT:.0%}")
    print(f"  Ctrl+C 退出")
    print(f"{'=' * 60}")

    entry_price = 0.0

    try:
        while True:
            try:
                df = _fetch_stocks([symbol])
                if df.empty:
                    print(f"  [{datetime.now():%H:%M:%S}] 等待数据...")
                    time.sleep(MONITOR_INTERVAL)
                    continue

                s = df.iloc[0]
                price = s["最新价"]
                open_price = s["今开"]
                high = s["最高"]
                low = s["最低"]
                change = s["涨跌幅"]
                vol = s["成交量"]
                amp = s["振幅"]
                turnover = s["换手率"]

            except Exception as e:
                print(f"  [{datetime.now():%H:%M:%S}] 网络错误: {e}")
                time.sleep(MONITOR_INTERVAL)
                continue

            status = (f"[{datetime.now():%H:%M:%S}] {price:.2f} ({change:+.2f}%) "
                      f"H:{high:.2f} L:{low:.2f} 振:{amp:.2f}% 换:{turnover:.2f}%")

            if entry_price > 0:
                pnl = (price - entry_price) / entry_price * 100
                status += f" | 成本:{entry_price:.2f} 浮:{pnl:+.2f}%"
                if pnl >= TAKE_PROFIT * 100:
                    status += "  <<< 止盈!"
                elif pnl <= -STOP_LOSS * 100:
                    status += "  <<< 止损!"

            print(status)
            time.sleep(MONITOR_INTERVAL)

    except KeyboardInterrupt:
        print("\n  监控已停止。")


def record_trade(symbol: str, name: str, direction: str,
                 entry: float, exit_price: float, shares: int) -> None:
    """Record a completed T-trade to CSV."""
    _ensure_csv()
    fee_rate = 0.0003
    gross = (exit_price - entry) * shares
    fees = (entry + exit_price) * shares * fee_rate
    pnl = gross - fees
    pnl_pct = (exit_price / entry - 1) * 100

    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M"), symbol, name, direction,
            f"{entry:.2f}", f"{exit_price:.2f}", shares,
            f"{pnl:.2f}", f"{pnl_pct:.2f}"
        ])

    print(f"  [TRADE] {direction} {name} {shares}股 "
          f"{entry:.2f}->{exit_price:.2f} PnL: {pnl:.2f} ({pnl_pct:+.2f}%)")


def show_pnl() -> None:
    """Display trade history and P&L summary."""
    _ensure_csv()

    print("\n" + "=" * 60)
    print("  交易记录 & 盈亏统计")
    print("=" * 60)

    try:
        df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        df = pd.DataFrame()

    if df.empty:
        print("  暂无交易记录。")
        print("=" * 60 + "\n")
        return

    print(df.to_string(index=False))
    print("-" * 60)

    pnl_vals = pd.to_numeric(df["pnl_yuan"], errors="coerce")
    wins = (pnl_vals > 0).sum()
    total = len(pnl_vals)
    win_rate = wins / total * 100 if total > 0 else 0
    total_pnl = pnl_vals.sum()

    print(f"  总交易: {total} | 胜率: {win_rate:.1f}% | 总盈亏: {total_pnl:+.2f}")
    if total > 0:
        print(f"  平均: {pnl_vals.mean():+.2f} | 最大盈: {pnl_vals.max():.2f} | "
              f"最大亏: {pnl_vals.min():.2f}")
    print("=" * 60 + "\n")


def analyze_stock(symbol: str) -> None:
    """Quick analysis of a stock's T-trading suitability."""
    print(f"\n  获取 {symbol} 实时数据...")

    try:
        df = _fetch_stocks([symbol])
        if df.empty:
            print(f"  [ERROR] 找不到股票 {symbol}")
            return

        s = df.iloc[0]
        name = s["名称"]
        price = s["最新价"]
        amplitude = s["振幅"]
        turnover = s["换手率"]
        change = s["涨跌幅"]
        volume = s["成交额"]
        high = s["最高"]
        low = s["最低"]
        o = s["今开"]

        print(f"\n  {'='*50}")
        print(f"  {name} ({symbol}) 做T分析")
        print(f"  {'='*50}")
        print(f"  现价: {price:.2f} | 涨跌: {change:+.2f}%")
        print(f"  今开: {o:.2f} | 最高: {high:.2f} | 最低: {low:.2f}")
        print(f"  振幅: {amplitude:.2f}% | 换手: {turnover:.2f}% | 成交额: {volume/1e4:.0f}万")

        score = 0
        checks = []
        if MIN_PRICE <= price <= MAX_PRICE:
            score += 1; checks.append("[OK] 价格合适")
        else:
            checks.append("[!!] 价格超出做T范围")
        if amplitude >= MIN_AMPLITUDE:
            score += 1; checks.append("[OK] 振幅充足")
        else:
            checks.append("[!!] 振幅不足")
        if turnover >= MIN_TURNOVER:
            score += 1; checks.append("[OK] 流动性好")
        else:
            checks.append("[!!] 流动性偏弱")

        for c in checks:
            print(f"  {c}")
        print(f"  做T适合度: {'*' * score}{' ' * (3 - score)} ({score}/3)")
        print(f"  2000元可买: {int(2000 // (price * 100))}手")
        print(f"  {'='*50}\n")

    except Exception as e:
        print(f"  [ERROR] {e}")


def main() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    _ensure_csv()

    while True:
        print("+" + "-" * 40 + "+")
        print("|  T-Trader 做T量化助手              |")
        print("|" + "-" * 40 + "|")
        print("|  [1] 筛选做T候选股                 |")
        print("|  [2] 实时监控个股                   |")
        print("|  [3] 快速分析个股                   |")
        print("|  [4] 交易记录 & 盈亏                |")
        print("|  [5] 退出                          |")
        print("+" + "-" * 40 + "+")
        choice = input("  选择 > ").strip()

        if choice == "1":
            screen_candidates()
        elif choice == "2":
            sym = input("  股票代码 (如 002421): ").strip()
            if sym:
                monitor_stock(sym)
        elif choice == "3":
            sym = input("  股票代码 (如 002421): ").strip()
            if sym:
                analyze_stock(sym)
        elif choice == "4":
            show_pnl()
        elif choice == "5":
            print("  Bye, Sir.\n")
            sys.exit(0)
        else:
            print("  无效选择，重试。")


if __name__ == "__main__":
    main()
