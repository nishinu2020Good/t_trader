"""T-Trader Stock Proxy — adata + Tencent API hybrid. Port 9051."""
import http.server, json, re, subprocess, sys, os
from urllib.parse import urlparse, parse_qs

PORT = 9051
TENCENT = "https://qt.gtimg.cn/q="

# --- adata-powered stock database (loaded once) ---
ALL_CODES = set()
TRYING_DAY = False
CONCEPT_MAP = {}   # code -> [concept names]

def _init_adata():
    global ALL_CODES, TRYING_DAY, CONCEPT_MAP
    try:
        import adata.stock.info as si
        df = si.all_code()
        if "stock_code" in df.columns:
            ALL_CODES = set(df["stock_code"].dropna().astype(str).tolist())
        elif "code" in df.columns:
            ALL_CODES = set(df["code"].dropna().astype(str).tolist())

        cal = si.trade_calendar()
        if not cal.empty:
            from datetime import date
            today_str = date.today().strftime("%Y-%m-%d")
            trade_dates = set()
            for col in cal.columns:
                trade_dates.update(cal[col].dropna().astype(str).tolist())
            TRYING_DAY = today_str in trade_dates

        # Load concepts for default watchlist via batch baidu API
        try:
            default_codes = [
                "002421","002031","002882","002506","601991","600726",
                "000539","002129","002579","002251","601678","002124",
                "601996","002406","002771","600635","000759","603363",
                "603995","600396","000725","000100","002081","600376",
                "600010","600022","600029","600115","600221",
                "600307","600383","600415","600606","600622",
                "600743","600748","600782","000001","000002",
                "000401","000425","000553","000625",
                "000651","000725","000768","002024","002050",
                "002065","002081","002092","002100","002130",
                "002131","002151","002152","002156","002157",
                "002158","002161","002166","002185","002190",
                "002191","002195","002197",
            ]
            concepts = si.get_concept_baidu(default_codes)
            if not concepts.empty and "name" in concepts.columns:
                for _, row in concepts.iterrows():
                    code_str = str(row.get("stock_code", ""))
                    name = row.get("name", "")
                    if name and code_str:
                        if code_str not in CONCEPT_MAP:
                            CONCEPT_MAP[code_str] = []
                        CONCEPT_MAP[code_str].append(name)
                # Convert lists to comma-separated strings
                for k in CONCEPT_MAP:
                    # Keep top 8 most relevant concepts
                    CONCEPT_MAP[k] = ",".join(CONCEPT_MAP[k][:8])
        except Exception:
            pass

        print(f"[Proxy] adata loaded: {len(ALL_CODES)} stocks, "
              f"trading={TRYING_DAY}, concepts={len(CONCEPT_MAP)}")
    except Exception as e:
        print(f"[Proxy] adata init warning: {e}")

_init_adata()

# --- Tencent API helpers ---
def _f(val):
    try: return float(val)
    except: return 0.0

def fetch_stocks(codes):
    qt = []
    for c in codes:
        prefix = "sh" if c.startswith("6") else "sz"
        qt.append(f"{prefix}{c}")
    url = TENCENT + ",".join(qt)
    r = subprocess.run(["curl", "-s", "--connect-timeout", "5", "--max-time", "10",
        "-H", "User-Agent: Mozilla/5.0", url],
        capture_output=True, text=True, timeout=15)
    raw = r.stdout

    rows = []
    for line in raw.strip().splitlines():
        if not line or "=" not in line: continue
        if re.search(r'="~{3,}"', line): continue
        m = re.search(r'="(.+)"', line)
        if not m: continue
        f = m.group(1).split("~")
        if len(f) < 44: continue
        try:
            code = f[2]
            price = _f(f[3])
            amp = _f(f[43])
            turnover = _f(f[38])
            amount = _f(f[37])
            rows.append({
                "code": code, "name": f[1],
                "price": price, "prev_close": _f(f[4]), "open": _f(f[5]),
                "high": _f(f[33]), "low": _f(f[34]),
                "change_pct": _f(f[32]), "change_amt": _f(f[31]),
                "volume": _f(f[6]), "amount": amount,
                "turnover": turnover, "amplitude": amp,
                "pe": _f(f[39]),
                "lots": int(2000 // (price * 100)) if price > 0 else 0,
                "concepts": CONCEPT_MAP.get(code, ""),
                "is_trading_day": TRYING_DAY,
                "score": round(amp * 3.0 + turnover * 1.5 + \
                    (__import__('math').log10(amount + 1)) * 0.5, 1)
            })
        except Exception: continue
    return rows

# --- HTTP handler ---
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        codes_str = qs.get("codes", [""])[0]
        codes = [c.strip() for c in codes_str.split(",") if c.strip()] if codes_str else []

        if not codes:
            # Default: build watchlist from common low-price active stocks
            # Top T-trading candidates from full market scan + key active stocks
            codes = [
                # Top 5 picks (scan verified)
                "002421","002388","000601","000759","002251",
                # High-score candidates from full scan
                "300410","300184","002585","002635","002771","002669",
                "605069","600360","600237","000600","300283","600186",
                "600744","605066","603458","000670","002012","600158",
                "300275","600151","300246","002639","600310","300162",
                # Original active watchlist
                "002031","002882","002506","601991","600726",
                "000539","002129","002579","601678","002124",
                "601996","002406","600635","603363","603995","600396",
                "000725","000100","002081","600376",
                "600010","600022","600029","600115","600221",
                "600307","600383","600415","600606","600622",
                "600743","600748","600782","000001","000002",
                "000401","000425","000553","000625",
                "000651","000768","002024","002050",
                "002065","002092","002100","002130",
                "002131","002151","002152","002156","002157",
                "002158","002161","002166","002185","002190",
                "002191","002195","002197",
            ]

        data = fetch_stocks(codes)
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, *a): pass

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"T-Trader Proxy (adata + Tencent): http://127.0.0.1:{PORT}/")
    http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
