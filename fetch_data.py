"""从 Yahoo Finance 拉取K线，每个交易日合成两根，写入 data/<代码>.js。

美股：1小时线 → 9:30-13:30、13:30-16:00 两根 4 小时K线；
A 股（.SS/.SZ）：30分钟线 → 上午、下午两根 2 小时K线（Yahoo 的 A 股 1 小时线成交量不准）。

用法：python fetch_data.py [代码] [范围]
例如：python fetch_data.py QQQ 3mo
      python fetch_data.py 515880        # 6 位数字自动补 .SS/.SZ，范围默认 60d
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

MARKETS = {
    "us": {"interval": "1h", "label": "4小时", "split": (13, 30), "starts": ((9, 30), (13, 30)), "range": "3mo"},
    # Yahoo 的 30 分钟线最多回看 60 天
    "cn": {"interval": "30m", "label": "2小时", "split": (12, 0), "starts": ((9, 30), (13, 0)), "range": "60d",
           "ranges": ("5d", "1mo", "60d")},
}


def normalize(symbol):
    symbol = symbol.upper()
    if symbol.isdigit() and len(symbol) == 6:
        symbol += ".SS" if symbol[0] in "569" else ".SZ"  # 沪市 5/6/9 开头，其余深市
    return symbol


symbol = normalize(sys.argv[1] if len(sys.argv) > 1 else "QQQ")
market = MARKETS["cn" if symbol.endswith((".SS", ".SZ")) else "us"]
rng = sys.argv[2] if len(sys.argv) > 2 else market["range"]
if "ranges" in market and rng not in market["ranges"]:
    print(f"{symbol} 的 {market['interval']} 数据最多回看 60 天，范围改用 {market['range']}")
    rng = market["range"]

url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
       f"?interval={market['interval']}&range={rng}&includePrePost=false")
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=20) as resp:
    result = json.load(resp)["chart"]["result"][0]

offset = result["meta"]["gmtoffset"]  # 交易所时区相对 UTC 的秒数
quote = result["indicators"]["quote"][0]

# 在 market["split"] 处把一天切成两根
buckets = {}
for i, ts in enumerate(result["timestamp"]):
    o, h, l, c, v = (quote[k][i] for k in ("open", "high", "low", "close", "volume"))
    if None in (o, h, l, c):
        continue
    t = datetime.fromtimestamp(ts + offset, tz=timezone.utc).replace(tzinfo=None)
    half = 0 if (t.hour, t.minute) < market["split"] else 1
    sh, sm = market["starts"][half]
    start = t.replace(hour=sh, minute=sm, second=0)
    key = start.strftime("%Y-%m-%d %H:%M")
    b = buckets.get(key)
    if b is None:
        buckets[key] = {"t": key, "o": o, "h": h, "l": l, "c": c, "v": v or 0}
    else:
        b["h"] = max(b["h"], h)
        b["l"] = min(b["l"], l)
        b["c"] = c
        b["v"] += v or 0

bars = [buckets[k] for k in sorted(buckets)]
for b in bars:
    for k in ("o", "h", "l", "c"):
        b[k] = round(b[k], 3)

os.makedirs("data", exist_ok=True)
out = os.path.join("data", f"{symbol}.js")
with open(out, "w", encoding="utf-8") as f:
    f.write(f"// 由 fetch_data.py 生成于 {datetime.now():%Y-%m-%d %H:%M}，数据来源 Yahoo Finance\n")
    f.write(f"window.SYMBOL = {json.dumps(symbol)};\n")
    f.write(f"window.INTERVAL = {json.dumps(market['label'])};\n")
    f.write("window.BARS = " + json.dumps(bars, separators=(",", ":")) + ";\n")

print(f"{symbol}: {len(bars)} 根{market['label']}K线，{bars[0]['t']} ~ {bars[-1]['t']}，已写入 {out}")
