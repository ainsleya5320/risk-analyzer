"""
Portfolio Analyzer — Zero-dependency edition
Uses only Python standard library. Run with: python app.py
"""

import http.server
from socketserver import ThreadingMixIn
import json
import urllib.request
import urllib.error
import math
import random
import csv
import os
import ssl
from statistics import NormalDist
from datetime import datetime, timezone
from io import StringIO

PORT = 5000
NORM = NormalDist()
FMP_KEY = os.environ.get("FMP_API_KEY", "")

# ═══════════════════════════════════════════════════════════════════
#  MATH / STATS UTILITIES
# ═══════════════════════════════════════════════════════════════════

def mean(v):
    return sum(v) / len(v)

def var(v, ddof=1):
    m = mean(v)
    return sum((x - m) ** 2 for x in v) / (len(v) - ddof)

def sd(v, ddof=1):
    return math.sqrt(var(v, ddof))

def cov(x, y, ddof=1):
    mx, my = mean(x), mean(y)
    return sum((x[i] - mx) * (y[i] - my) for i in range(len(x))) / (len(x) - ddof)

def corr(x, y):
    sx, sy = sd(x), sd(y)
    return cov(x, y) / (sx * sy) if sx > 0 and sy > 0 else 0.0

def pct_change(prices):
    return [(prices[i] / prices[i - 1]) - 1 for i in range(1, len(prices))]


# ── Matrix ops (for OLS) ──────────────────────────────────────────

def mat_T(A):
    return [[A[j][i] for j in range(len(A))] for i in range(len(A[0]))]

def mat_mul(A, B):
    rA, cA, cB = len(A), len(A[0]), len(B[0])
    C = [[0.0] * cB for _ in range(rA)]
    for i in range(rA):
        for j in range(cB):
            s = 0.0
            for k in range(cA):
                s += A[i][k] * B[k][j]
            C[i][j] = s
    return C

def mat_vec(A, v):
    return [sum(A[i][j] * v[j] for j in range(len(v))) for i in range(len(A))]

def mat_inv(A):
    n = len(A)
    aug = [A[i][:] + [float(i == j) for j in range(n)] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[piv] = aug[piv], aug[col]
        d = aug[col][col]
        if abs(d) < 1e-14:
            raise ValueError("Singular matrix – check for multicollinearity")
        for j in range(2 * n):
            aug[col][j] /= d
        for row in range(n):
            if row != col:
                f = aug[row][col]
                for j in range(2 * n):
                    aug[row][j] -= f * aug[col][j]
    return [row[n:] for row in aug]


# ── Incomplete beta / t-dist / F-dist (Numerical Recipes) ────────

def _betacf(a, b, x):
    FPMIN = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN: d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN: d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN: c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN: d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN: c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h

def betai(a, b, x):
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    bt = math.exp(a * math.log(x) + b * math.log(1 - x)
                  - (math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1 - x) / b

def t_pvalue(t_val, df):
    x = df / (df + t_val * t_val)
    p = betai(df / 2.0, 0.5, x)
    return p  # two-tailed

def f_pvalue(f_val, df1, df2):
    if f_val <= 0: return 1.0
    x = df2 / (df2 + df1 * f_val)
    return betai(df2 / 2.0, df1 / 2.0, x)


# ── OLS Regression ────────────────────────────────────────────────

def ols(Y, X_cols, col_names):
    """
    Ordinary Least Squares with intercept.
    Y        – list[float]
    X_cols   – list[list[float]], each inner list is one factor
    col_names – list[str]
    """
    n = len(Y)
    k = len(X_cols)
    X = [[1.0] + [X_cols[j][i] for j in range(k)] for i in range(n)]
    p = k + 1

    Xt = mat_T(X)
    XtX_inv = mat_inv(mat_mul(Xt, X))
    beta = mat_vec(XtX_inv, mat_vec(Xt, Y))

    Y_hat = mat_vec(X, beta)
    resid = [Y[i] - Y_hat[i] for i in range(n)]
    Ym = mean(Y)
    SSE = sum(r * r for r in resid)
    SST = sum((y - Ym) ** 2 for y in Y)
    SSR = SST - SSE
    df_resid = n - p

    R2 = 1 - SSE / SST if SST > 0 else 0
    adjR2 = 1 - (1 - R2) * (n - 1) / df_resid if df_resid > 0 else 0
    MSE = SSE / df_resid if df_resid > 0 else 0

    se = [math.sqrt(max(MSE * XtX_inv[j][j], 0)) for j in range(p)]
    t_stats = [beta[j] / se[j] if se[j] > 1e-15 else 0 for j in range(p)]
    pvals = [t_pvalue(abs(t), df_resid) for t in t_stats]

    MSR = SSR / k if k > 0 else 0
    F = MSR / MSE if MSE > 0 else 0
    Fp = f_pvalue(F, k, df_resid)

    dw = sum((resid[i] - resid[i - 1]) ** 2 for i in range(1, n)) / SSE if SSE > 0 else 0

    names = ["const"] + col_names
    return {
        "beta": beta, "se": se, "t": t_stats, "p": pvals,
        "names": names, "R2": R2, "adjR2": adjR2,
        "F": F, "Fp": Fp, "dw": dw, "resid": resid, "n": n, "k": k,
    }


# ═══════════════════════════════════════════════════════════════════
#  DATA FETCHERS  (FMP preferred, Yahoo fallback)
# ═══════════════════════════════════════════════════════════════════

def fetch_fmp(ticker, start, end, api_key):
    """Return (dates[], prices[]) from Financial Modeling Prep API."""
    url = (f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}"
           f"?from={start}&to={end}&apikey={api_key}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    ctx = ssl.create_default_context()

    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=30)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise ValueError(f"FMP HTTP {e.code} for {ticker}: {body[:200]}")

    raw = json.loads(resp.read().decode())

    # FMP returns errors in various formats
    if "Error Message" in raw:
        raise ValueError(f"FMP error for {ticker}: {raw['Error Message']}")
    if isinstance(raw, dict) and raw.get("error"):
        raise ValueError(f"FMP error for {ticker}: {raw['error']}")

    hist = raw.get("historical", [])
    if not hist:
        raise ValueError(f"FMP returned no data for {ticker}. Check ticker symbol and date range.")

    # FMP returns newest-first; reverse to chronological
    hist.sort(key=lambda x: x["date"])
    dates  = [row["date"] for row in hist]
    prices = [float(row.get("adjClose", row["close"])) for row in hist]
    return dates, prices


def fetch_yahoo(ticker, start, end):
    """Return (dates[], prices[]) from Yahoo Finance v8 chart API (fallback)."""
    s_ts = int(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    e_ts = int(datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={s_ts}&period2={e_ts}&interval=1d&includeAdjustedClose=true")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    ctx = ssl.create_default_context()
    resp = urllib.request.urlopen(req, context=ctx, timeout=30)
    raw = json.loads(resp.read().decode())

    res = raw["chart"]["result"][0]
    ts_list = res["timestamp"]
    try:
        closes = res["indicators"]["adjclose"][0]["adjclose"]
    except (KeyError, IndexError):
        closes = res["indicators"]["quote"][0]["close"]

    dates, prices = [], []
    for t, p in zip(ts_list, closes):
        if p is not None:
            dates.append(datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"))
            prices.append(float(p))
    return dates, prices


def fetch_prices(ticker, start, end, api_key=""):
    """Fetch prices: try FMP first, fall back to Yahoo on failure."""
    key = api_key or FMP_KEY
    if key:
        try:
            return fetch_fmp(ticker, start, end, key)
        except Exception as fmp_err:
            print(f"  FMP failed for {ticker}: {fmp_err}")
            print(f"  Falling back to Yahoo Finance...")
            try:
                return fetch_yahoo(ticker, start, end)
            except Exception as yf_err:
                raise ValueError(
                    f"Both sources failed for {ticker}.\n"
                    f"  FMP: {fmp_err}\n"
                    f"  Yahoo: {yf_err}"
                )
    return fetch_yahoo(ticker, start, end)


# ═══════════════════════════════════════════════════════════════════
#  SESSION STORE  (single-user, in-memory)
# ═══════════════════════════════════════════════════════════════════

SESSION = {}


# ═══════════════════════════════════════════════════════════════════
#  API HANDLERS
# ═══════════════════════════════════════════════════════════════════

def handle_analyze(p):
    tickers = p["tickers"]
    weights = [float(w) for w in p["weights"]]
    bench   = p.get("benchmark", "SPY")
    start   = p["startDate"]
    end     = p["endDate"]
    rf_ann  = p.get("riskFreeRate", 0.05)
    cl      = p.get("confidenceLevel", 0.95)
    api_key = p.get("apiKey", "")

    if len(tickers) != len(weights):
        raise ValueError("Tickers and weights length mismatch")

    # ── Fetch prices (FMP if key provided, else Yahoo) ─────────────
    all_tickers = list(dict.fromkeys(tickers + [bench]))
    price_map = {}
    source = "FMP" if (api_key or FMP_KEY) else "Yahoo"
    for tk in all_tickers:
        try:
            d, pr = fetch_prices(tk, start, end, api_key)
        except Exception as e:
            raise ValueError(f"Failed to fetch {tk}: {e}")
        price_map[tk] = dict(zip(d, pr))

    # ── Align dates ───────────────────────────────────────────────
    common_dates = sorted(set.intersection(*(set(price_map[t]) for t in all_tickers)))
    if len(common_dates) < 3:
        raise ValueError("Not enough overlapping data. Check tickers/dates.")

    aligned = {t: [price_map[t][d] for d in common_dates] for t in all_tickers}

    # ── Returns ───────────────────────────────────────────────────
    ret = {t: pct_change(aligned[t]) for t in all_tickers}
    ret_dates = common_dates[1:]
    n = len(ret_dates)

    port_ret = [sum(weights[j] * ret[tickers[j]][i] for j in range(len(tickers))) for i in range(n)]
    bench_ret = ret[bench]
    daily_rf = (1 + rf_ann) ** (1 / 252) - 1

    # ── Annualized stats ──────────────────────────────────────────
    ann_ret = (1 + mean(port_ret)) ** 252 - 1
    ann_vol = sd(port_ret) * math.sqrt(252)
    sharpe  = (ann_ret - rf_ann) / ann_vol if ann_vol > 0 else 0

    down = [r - daily_rf for r in port_ret if r < daily_rf]
    down_std = sd(down, ddof=0) * math.sqrt(252) if len(down) > 1 else 0
    sortino  = (ann_ret - rf_ann) / down_std if down_std > 0 else float("nan")

    active = [port_ret[i] - bench_ret[i] for i in range(n)]
    te = sd(active) * math.sqrt(252) if len(active) > 1 else 0
    info_ratio = (mean(active) * 252) / te if te > 0 else float("nan")

    # ── VaR ───────────────────────────────────────────────────────
    z = NORM.inv_cdf(1 - cl)
    par_var = mean(port_ret) + z * sd(port_ret, ddof=0)
    sorted_ret = sorted(port_ret)
    idx = max(0, int(math.floor((1 - cl) * n)) - 1)
    hist_var = sorted_ret[idx]
    random.seed(42)
    sims = [random.gauss(mean(port_ret), sd(port_ret, ddof=0)) for _ in range(10_000)]
    sims.sort()
    mc_var = sims[int((1 - cl) * 10_000)]

    # ── Cumulative returns / drawdown ─────────────────────────────
    cum_p = [1.0]
    for r in port_ret:
        cum_p.append(cum_p[-1] * (1 + r))
    cum_p = cum_p[1:]

    cum_b = [1.0]
    for r in bench_ret:
        cum_b.append(cum_b[-1] * (1 + r))
    cum_b = cum_b[1:]

    peak = cum_p[0]
    dd = []
    for v in cum_p:
        if v > peak: peak = v
        dd.append((v - peak) / peak)
    max_dd = min(dd)

    # ── Correlation ───────────────────────────────────────────────
    corr_mat = [[round(corr(ret[tickers[i]], ret[tickers[j]]), 4)
                 for j in range(len(tickers))] for i in range(len(tickers))]

    # ── Per-asset ─────────────────────────────────────────────────
    asset_stats = []
    for t in tickers:
        ar = (1 + mean(ret[t])) ** 252 - 1
        av = sd(ret[t]) * math.sqrt(252)
        asset_stats.append({
            "ticker": t,
            "annualReturn": round(ar * 100, 2),
            "annualVol": round(av * 100, 2),
            "sharpe": round((ar - rf_ann) / av, 4) if av > 0 else 0,
        })

    b_ar = (1 + mean(bench_ret)) ** 252 - 1
    b_av = sd(bench_ret) * math.sqrt(252)
    b_sr = (b_ar - rf_ann) / b_av if b_av > 0 else 0

    # ── Risk decomposition ─────────────────────────────────────────
    cov_mat = [[cov(ret[tickers[i]], ret[tickers[j]])
                for j in range(len(tickers))] for i in range(len(tickers))]
    port_var_d = sum(weights[i] * sum(cov_mat[i][j] * weights[j]
                 for j in range(len(tickers))) for i in range(len(tickers)))
    port_vol_d = math.sqrt(max(port_var_d, 1e-20))

    sigma_w = [sum(cov_mat[i][j] * weights[j] for j in range(len(tickers)))
               for i in range(len(tickers))]
    mcr = [sigma_w[i] / port_vol_d for i in range(len(tickers))]
    ccr = [weights[i] * mcr[i] for i in range(len(tickers))]
    pct_cr = [ccr[i] / port_vol_d * 100 for i in range(len(tickers))]

    risk_decomp = []
    for idx_rd, t in enumerate(tickers):
        risk_decomp.append({
            "ticker": t,
            "weight": round(weights[idx_rd] * 100, 2),
            "mcr": round(mcr[idx_rd] * math.sqrt(252) * 100, 4),
            "ccr": round(ccr[idx_rd] * math.sqrt(252) * 100, 4),
            "pctContrib": round(pct_cr[idx_rd], 2),
        })

    # ── Rolling statistics (60-day window) ─────────────────────────
    window = min(60, max(20, n // 3))
    rolling_data = {"dates": [], "sharpe": [], "beta": [], "vol": []}
    if n > window:
        for i in range(window, n):
            w_ret = port_ret[i - window:i]
            w_bench = bench_ret[i - window:i]
            wm = mean(w_ret)
            ws = sd(w_ret) if len(w_ret) > 1 else 0
            r_sharpe = ((wm - daily_rf) / ws * math.sqrt(252)) if ws > 0 else 0

            bc = cov(w_ret, w_bench) if len(w_ret) > 1 else 0
            bv = var(w_bench) if len(w_bench) > 1 else 0
            r_beta = bc / bv if bv > 0 else 0
            r_vol = ws * math.sqrt(252) * 100

            rolling_data["dates"].append(ret_dates[i])
            rolling_data["sharpe"].append(round(r_sharpe, 4))
            rolling_data["beta"].append(round(r_beta, 4))
            rolling_data["vol"].append(round(r_vol, 2))

    # ── Store for regression ──────────────────────────────────────
    SESSION["ret"]       = ret
    SESSION["port_ret"]  = port_ret
    SESSION["bench_ret"] = bench_ret
    SESSION["ret_dates"] = ret_dates
    SESSION["tickers"]   = tickers
    SESSION["daily_rf"]  = daily_rf
    SESSION["start"]     = start
    SESSION["end"]       = end
    SESSION["rf_ann"]    = rf_ann
    SESSION["api_key"]   = api_key

    return {
        "summary": {
            "annualReturn": round(ann_ret * 100, 2),
            "annualVolatility": round(ann_vol * 100, 2),
            "sharpeRatio": round(sharpe, 4),
            "sortinoRatio": round(sortino, 4) if not math.isnan(sortino) else None,
            "informationRatio": round(info_ratio, 4) if not math.isnan(info_ratio) else None,
            "maxDrawdown": round(max_dd * 100, 2),
            "trackingError": round(te * 100, 2),
        },
        "var": {
            "parametric": round(par_var * 100, 4),
            "historical": round(hist_var * 100, 4),
            "monteCarlo": round(mc_var * 100, 4),
            "confidenceLevel": cl,
        },
        "benchmark": {
            "ticker": bench,
            "annualReturn": round(b_ar * 100, 2),
            "annualVolatility": round(b_av * 100, 2),
            "sharpeRatio": round(b_sr, 4),
        },
        "assetStats": asset_stats,
        "correlation": {"labels": tickers, "matrix": corr_mat},
        "timeSeries": {
            "dates": ret_dates,
            "portfolio": [round(v, 6) for v in cum_p],
            "benchmark": [round(v, 6) for v in cum_b],
            "drawdown": [round(v, 6) for v in dd],
        },
        "riskDecomp": risk_decomp,
        "rolling": rolling_data,
        "dataSource": source,
    }


def handle_regression(p):
    if "port_ret" not in SESSION:
        raise ValueError("Run portfolio analysis first.")

    factors = p.get("factors", [])
    port_ret  = SESSION["port_ret"]
    daily_rf  = SESSION["daily_rf"]
    ret       = SESSION["ret"]
    ret_dates = SESSION["ret_dates"]
    n = len(port_ret)

    Y = [port_ret[i] - daily_rf for i in range(n)]

    if factors:
        # Fetch any factors we don't have yet
        for ft in factors:
            if ft not in ret:
                try:
                    d, pr = fetch_prices(ft, SESSION["start"], SESSION["end"],
                                         SESSION.get("api_key", ""))
                    pm = dict(zip(d, pr))
                    ret[ft] = []
                    prev = None
                    for dt in SESSION["ret_dates"]:
                        if dt in pm and prev is not None:
                            ret[ft].append(pm[dt] / prev - 1)
                        elif dt in pm:
                            ret[ft].append(0)
                        else:
                            ret[ft].append(0)
                        if dt in pm:
                            prev = pm[dt]
                except Exception as e:
                    raise ValueError(f"Cannot fetch factor {ft}: {e}")
        X_cols = [ret[ft][:n] for ft in factors]
        names = factors
    else:
        bench_ret = SESSION["bench_ret"]
        X_cols = [[bench_ret[i] - daily_rf for i in range(n)]]
        names = ["Market"]

    res = ols(Y, X_cols, names)

    factors_out = []
    for idx, name in enumerate(names):
        j = idx + 1  # skip intercept
        factors_out.append({
            "name": name,
            "coefficient": round(res["beta"][j], 6),
            "stdError": round(res["se"][j], 6),
            "tStat": round(res["t"][j], 4),
            "pValue": round(res["p"][j], 6),
        })

    return {
        "alpha": round(res["beta"][0], 8),
        "alphaAnnualized": round(res["beta"][0] * 252 * 100, 4),
        "alphaPValue": round(res["p"][0], 6),
        "rSquared": round(res["R2"], 4),
        "adjRSquared": round(res["adjR2"], 4),
        "fStatistic": round(res["F"], 4),
        "fPValue": round(res["Fp"], 8),
        "durbinWatson": round(res["dw"], 4),
        "observations": res["n"],
        "factors": factors_out,
        "residuals": {
            "dates": ret_dates,
            "values": [round(r, 8) for r in res["resid"]],
        },
    }


def handle_upload_csv(p):
    csv_text  = p["csv"]
    data_type = p.get("dataType", "prices")

    reader = csv.reader(StringIO(csv_text))
    rows = list(reader)
    if len(rows) < 3:
        raise ValueError("CSV too short – need a header row and at least 2 data rows.")

    header = rows[0]
    tickers = [h.strip() for h in header[1:] if h.strip()]

    dates, columns = [], {t: [] for t in tickers}
    for row in rows[1:]:
        if len(row) < len(header):
            continue
        try:
            dates.append(row[0].strip())
            for j, t in enumerate(tickers):
                columns[t].append(float(row[j + 1]))
        except (ValueError, IndexError):
            continue

    if data_type == "prices":
        ret = {t: pct_change(columns[t]) for t in tickers}
        ret_dates = dates[1:]
    else:
        ret = columns
        ret_dates = dates

    n = len(ret_dates)
    SESSION["ret"]       = ret
    SESSION["ret_dates"] = ret_dates
    SESSION["tickers"]   = tickers

    return {
        "tickers": tickers,
        "rows": n,
        "startDate": ret_dates[0],
        "endDate": ret_dates[-1],
    }


def handle_frontier(p):
    """Generate random portfolios for efficient frontier visualization."""
    if "ret" not in SESSION:
        raise ValueError("Run portfolio analysis first.")

    tickers  = SESSION["tickers"]
    ret_data = SESSION["ret"]
    rf_ann   = SESSION.get("rf_ann", 0.05)
    n_assets = len(tickers)

    mu = [mean(ret_data[t]) for t in tickers]
    cm = [[cov(ret_data[tickers[i]], ret_data[tickers[j]])
           for j in range(n_assets)] for i in range(n_assets)]

    random.seed(0)
    n_port = 2500
    portfolios = []

    for _ in range(n_port):
        w = [random.random() for _ in range(n_assets)]
        ws = sum(w)
        w = [x / ws for x in w]

        p_ret = sum(w[i] * mu[i] for i in range(n_assets))
        p_var = sum(w[i] * sum(cm[i][j] * w[j]
                for j in range(n_assets)) for i in range(n_assets))
        p_vol = math.sqrt(max(p_var, 0))

        a_ret = ((1 + p_ret) ** 252 - 1) * 100
        a_vol = p_vol * math.sqrt(252) * 100
        sh = (a_ret / 100 - rf_ann) / (a_vol / 100) if a_vol > 0 else 0

        portfolios.append({
            "ret": round(a_ret, 2),
            "vol": round(a_vol, 2),
            "sharpe": round(sh, 4),
            "weights": [round(x, 4) for x in w],
        })

    max_sh = max(portfolios, key=lambda x: x["sharpe"])
    min_v  = min(portfolios, key=lambda x: x["vol"])

    return {
        "portfolios": portfolios,
        "maxSharpe": max_sh,
        "minVol": min_v,
        "tickers": tickers,
    }


def handle_leverage(p):
    """Simulate the effect of leverage on portfolio risk-return metrics."""
    if "port_ret" not in SESSION:
        raise ValueError("Run portfolio analysis first.")

    port_ret  = SESSION["port_ret"]
    ret_dates = SESSION["ret_dates"]
    rf_ann    = SESSION.get("rf_ann", 0.05)
    n = len(port_ret)

    levels     = p.get("levels", [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0])
    borrow_ann = p.get("borrowRate", rf_ann + 0.015)  # default: Rf + 150 bps
    cl         = p.get("confidenceLevel", 0.95)

    daily_borrow = (1 + borrow_ann) ** (1 / 252) - 1
    daily_rf     = (1 + rf_ann) ** (1 / 252) - 1
    z = NORM.inv_cdf(1 - cl)

    results = []
    unlev_idx = None

    for li, lev in enumerate(levels):
        # Leveraged daily returns: L * r_p - (L-1) * borrow_cost
        lev_ret = [lev * port_ret[i] - (lev - 1) * daily_borrow
                   for i in range(n)]

        # Annualized stats
        mu_d = mean(lev_ret)
        sd_d = sd(lev_ret) if n > 1 else 0
        ann_ret = ((1 + mu_d) ** 252 - 1) * 100
        ann_vol = sd_d * math.sqrt(252) * 100

        sharpe = (ann_ret / 100 - rf_ann) / (ann_vol / 100) if ann_vol > 0 else 0

        # Sortino
        down = [r - daily_rf for r in lev_ret if r < daily_rf]
        down_std = sd(down, ddof=0) * math.sqrt(252) if len(down) > 1 else 0
        sortino = ((ann_ret / 100 - rf_ann) / down_std) if down_std > 0 else float("nan")

        # VaR (parametric)
        par_var = mu_d + z * (sd_d if sd_d > 0 else 1e-10)

        # Cumulative returns & drawdown
        cum = [1.0]
        for r in lev_ret:
            cum.append(cum[-1] * (1 + r))
        cum = cum[1:]

        peak = cum[0]
        dd = []
        for v in cum:
            if v > peak:
                peak = v
            dd.append((v - peak) / peak)
        max_dd = min(dd)

        if abs(lev - 1.0) < 1e-9:
            unlev_idx = li

        results.append({
            "leverage":    lev,
            "annReturn":   round(ann_ret, 2),
            "annVol":      round(ann_vol, 2),
            "sharpe":      round(sharpe, 4),
            "sortino":     round(sortino, 4) if not math.isnan(sortino) else None,
            "maxDrawdown": round(max_dd * 100, 2),
            "var95":       round(par_var * 100, 4),
            "cumulative":  [round(v, 6) for v in cum],
            "drawdown":    [round(v, 6) for v in dd],
        })

    return {
        "borrowRate":     round(borrow_ann * 100, 2),
        "levels":         results,
        "dates":          ret_dates,
        "unleveragedIdx": unlev_idx,
    }


# ═══════════════════════════════════════════════════════════════════
#  HTTP SERVER
# ═══════════════════════════════════════════════════════════════════

ROUTES = {
    "/api/analyze":    handle_analyze,
    "/api/regression": handle_regression,
    "/api/upload-csv": handle_upload_csv,
    "/api/frontier":   handle_frontier,
    "/api/leverage":   handle_leverage,
}

class Handler(http.server.SimpleHTTPRequestHandler):

    def end_headers(self):
        # Prevent browser from caching static files (HTML/JS/CSS)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return self._json(400, {"error": "Invalid JSON"})

        handler = ROUTES.get(self.path)
        if not handler:
            return self._json(404, {"error": "Not found"})
        try:
            result = handler(payload)
            self._json(200, result)
        except Exception as e:
            self._json(400, {"error": str(e)})

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Quieter logging
        if "/api/" in (args[0] if args else ""):
            print(f"  API  {args[0]}")


class ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\n  Portfolio Analyzer running at  http://localhost:{PORT}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
