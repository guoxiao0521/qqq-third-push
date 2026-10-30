// 线上版 fetch_data.py：/data/<代码>.js 现拉 Yahoo 行情，每个交易日合成两根 K 线。
// 美股：1 小时线 → 9:30-13:30、13:30-16:00 两根 4 小时；
// A 股（.SS/.SZ）：30 分钟线 → 上午、下午两根 2 小时（Yahoo 的 A 股 1 小时线成交量不准）。

const RANGES = new Set(["5d", "1mo", "60d", "3mo", "6mo", "1y", "2y", "5y", "ytd", "max"]);
const PATH_RE = /^\/data\/([A-Za-z0-9.^=-]{1,12})\.js$/;
const CACHE_SECONDS = 600;

const MARKETS = {
  us: { interval: "1h", label: "4小时", split: [13, 30], starts: [[9, 30], [13, 30]], defaultRange: "3mo" },
  // Yahoo 的 30 分钟线最多回看 60 天
  cn: { interval: "30m", label: "2小时", split: [12, 0], starts: [[9, 30], [13, 0]], defaultRange: "60d", ranges: ["5d", "1mo", "60d"] },
};

function marketOf(symbol) {
  return /\.(SS|SZ)$/.test(symbol) ? MARKETS.cn : MARKETS.us;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const m = url.pathname.match(PATH_RE);
    if (m) return dataJs(url, m[1].toUpperCase(), ctx);
    return env.ASSETS.fetch(request);
  },
};

async function dataJs(url, symbol, ctx) {
  const market = marketOf(symbol);
  let range = url.searchParams.get("range") || market.defaultRange;
  if (!RANGES.has(range)) {
    return js(`window.BARS=[];window.DATA_ERROR=${JSON.stringify("参数不合法")};`, 400, false);
  }
  if (market.ranges && !market.ranges.includes(range)) range = market.defaultRange;

  const cacheKey = new Request(`${url.origin}/data/${symbol}.js?range=${range}`, { method: "GET" });
  const cache = caches.default;
  const hit = await cache.match(cacheKey);
  if (hit) return hit;

  try {
    const result = await fetchYahoo(symbol, range, market.interval);
    const bars = toSessionBars(result, market);
    if (!bars.length) throw new Error("Yahoo 没有返回可用的 K 线");
    const body =
      `// ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC，数据来源 Yahoo Finance\n` +
      `window.SYMBOL=${JSON.stringify(symbol)};\n` +
      `window.INTERVAL=${JSON.stringify(market.label)};\n` +
      `window.BARS=${JSON.stringify(bars)};\n`;
    const response = js(body, 200, true);
    ctx.waitUntil(cache.put(cacheKey, response.clone()));
    return response;
  } catch (err) {
    const message = err instanceof Error ? err.message : "行情暂时拉不到";
    return js(`window.BARS=[];window.DATA_ERROR=${JSON.stringify(message)};`, 200, false);
  }
}

async function fetchYahoo(symbol, range, interval) {
  const path = `/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}&includePrePost=false`;
  let lastError = "Yahoo Finance 请求失败";
  for (const host of ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]) {
    const resp = await fetch(`https://${host}${path}`, {
      headers: { "User-Agent": "Mozilla/5.0", Accept: "application/json" },
      signal: AbortSignal.timeout(15000),
    });
    if (!resp.ok) {
      lastError = `Yahoo Finance 返回 ${resp.status}`;
      continue;
    }
    const data = await resp.json();
    const result = data?.chart?.result?.[0];
    if (!result?.timestamp || !result?.indicators?.quote?.[0]) {
      lastError = data?.chart?.error?.description || "Yahoo Finance 没有返回行情";
      continue;
    }
    return result;
  }
  throw new Error(lastError);
}

// 与 fetch_data.py 相同：按交易所时区在 market.split 处把一天切成两根。
function toSessionBars(result, market) {
  const offset = result.meta?.gmtoffset || 0;
  const quote = result.indicators.quote[0];
  const buckets = new Map();

  for (let i = 0; i < result.timestamp.length; i++) {
    const o = quote.open[i];
    const h = quote.high[i];
    const l = quote.low[i];
    const c = quote.close[i];
    const v = quote.volume[i];
    if (o == null || h == null || l == null || c == null) continue;

    const t = new Date((result.timestamp[i] + offset) * 1000);
    const hour = t.getUTCHours();
    const minute = t.getUTCMinutes();
    const [sh, sm] = market.split;
    const half = hour < sh || (hour === sh && minute < sm) ? 0 : 1;
    const [h0, m0] = market.starts[half];
    const start = new Date(t);
    start.setUTCHours(h0, m0, 0, 0);
    const key = stamp(start);

    const bar = buckets.get(key);
    if (!bar) {
      buckets.set(key, { t: key, o, h, l, c, v: v || 0 });
    } else {
      bar.h = Math.max(bar.h, h);
      bar.l = Math.min(bar.l, l);
      bar.c = c;
      bar.v += v || 0;
    }
  }

  return [...buckets.values()]
    .sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0))
    .map((b) => ({
      t: b.t,
      o: round3(b.o),
      h: round3(b.h),
      l: round3(b.l),
      c: round3(b.c),
      v: b.v,
    }));
}

function stamp(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}

function round3(n) {
  return Math.round(n * 1000) / 1000;
}

function js(body, status, cacheable) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "application/javascript; charset=utf-8",
      "cache-control": cacheable ? `public, max-age=${CACHE_SECONDS}` : "no-store",
    },
  });
}
