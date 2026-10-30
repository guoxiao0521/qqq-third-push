"""从 Yahoo Finance 拉取 QQQ 1小时K线，合成为 4小时K线，写入 data.js。

用法：python fetch_data.py [代码] [范围]
例如：python fetch_data.py QQQ 3mo
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

symbol = sys.argv[1] if len(sys.argv) > 1 else "QQQ"
rng = sys.argv[2] if len(sys.argv) > 2 else "3mo"

url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
       f"?interval=1h&range={rng}&includePrePost=false")
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=20) as resp:
    result = json.load(resp)["chart"]["result"][0]

offset = result["meta"]["gmtoffset"]  # 交易所时区相对 UTC 的秒数
quote = result["indicators"]["quote"][0]

# 美股常规时段 9:30-16:00，按 9:30-13:30、13:30-16:00 切成两根 4 小时K线
buckets = {}
for i, ts in enumerate(result["timestamp"]):
    o, h, l, c, v = (quote[k][i] for k in ("open", "high", "low", "close", "volume"))
    if None in (o, h, l, c):
        continue
    t = datetime.fromtimestamp(ts + offset, tz=timezone.utc).replace(tzinfo=None)
    half = 0 if (t.hour, t.minute) < (13, 30) else 1
    start = t.replace(hour=9 if half == 0 else 13, minute=30, second=0)
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

with open("data.js", "w", encoding="utf-8") as f:
    f.write(f"// 由 fetch_data.py 生成于 {datetime.now():%Y-%m-%d %H:%M}，数据来源 Yahoo Finance\n")
    f.write(f"window.SYMBOL = {json.dumps(symbol)};\n")
    f.write("window.BARS = " + json.dumps(bars, separators=(",", ":")) + ";\n")

print(f"{symbol}: {len(bars)} 根 4小时K线，{bars[0]['t']} ~ {bars[-1]['t']}，已写入 data.js")
