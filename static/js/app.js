/* ================================================================
   Portfolio Analyzer – Frontend Logic
   ================================================================ */

let currentData = null;  // stores the latest analysis response

// ── Data Source Toggle ─────────────────────────────────────────
function setDataSource(source) {
    document.querySelectorAll("#dataSourceTabs .nav-link").forEach(a => a.classList.remove("active"));
    event.target.classList.add("active");
    document.getElementById("yahoo-inputs").style.display = source === "yahoo" ? "" : "none";
    document.getElementById("csv-inputs").style.display   = source === "csv"   ? "" : "none";
}

// ── Holdings Management ────────────────────────────────────────
function addHolding() {
    const container = document.getElementById("holdings-rows");
    const row = document.createElement("div");
    row.className = "row g-2 mb-2 holding-row";
    row.innerHTML = `
        <div class="col-5"><input type="text" class="form-control ticker-input" placeholder="Ticker"></div>
        <div class="col-4"><input type="number" class="form-control weight-input" placeholder="Weight" step="0.01" min="0" max="1"></div>
        <div class="col-3"><button class="btn btn-outline-danger btn-sm remove-row-btn" onclick="removeHolding(this)"><i class="bi bi-x-lg"></i></button></div>`;
    container.appendChild(row);
    updateWeightSum();
    updateRemoveButtons();
}

function removeHolding(btn) {
    btn.closest(".holding-row").remove();
    updateWeightSum();
    updateRemoveButtons();
}

function updateRemoveButtons() {
    const rows = document.querySelectorAll(".holding-row");
    rows.forEach((row, i) => {
        const btn = row.querySelector(".remove-row-btn");
        btn.disabled = rows.length <= 1;
    });
}

function updateWeightSum() {
    const inputs = document.querySelectorAll(".weight-input");
    let sum = 0;
    inputs.forEach(inp => { sum += parseFloat(inp.value) || 0; });
    const el = document.getElementById("weight-sum");
    el.textContent = sum.toFixed(2);
    el.style.color = Math.abs(sum - 1.0) < 0.001 ? "#16a34a" : "#dc2626";
}

// Live-update weight sum on input
document.getElementById("holdings-rows").addEventListener("input", updateWeightSum);

// ── CSV Upload ─────────────────────────────────────────────────
async function uploadCSV() {
    const fileInput = document.getElementById("csv-file");
    const dataType = document.getElementById("csv-data-type").value;
    if (!fileInput.files.length) return showError("Please select a CSV file.");

    const reader = new FileReader();
    reader.onload = async function(e) {
        try {
            const res = await fetch("/api/upload-csv", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ csv: e.target.result, dataType }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error);

            const status = document.getElementById("csv-status");
            status.classList.remove("d-none");
            status.innerHTML = `Loaded <strong>${data.tickers.join(", ")}</strong> &mdash; ${data.rows} observations (${data.startDate} to ${data.endDate})`;
        } catch (e) {
            showError(e.message);
        }
    };
    reader.readAsText(fileInput.files[0]);
}

// ── Main Analysis ──────────────────────────────────────────────
async function analyzePortfolio() {
    hideError();

    const tickers = [], weights = [];
    document.querySelectorAll(".holding-row").forEach(row => {
        const t = row.querySelector(".ticker-input").value.trim().toUpperCase();
        const w = parseFloat(row.querySelector(".weight-input").value);
        if (t && !isNaN(w)) { tickers.push(t); weights.push(w); }
    });

    if (tickers.length === 0) return showError("Add at least one holding with a weight.");
    if (Math.abs(weights.reduce((a, b) => a + b, 0) - 1.0) > 0.02)
        return showError("Weights should sum to approximately 1.0.");

    const apiKey = document.getElementById("fmp-api-key").value.trim();
    const payload = {
        tickers,
        weights,
        benchmark: document.getElementById("benchmark").value.trim().toUpperCase() || "SPY",
        startDate: document.getElementById("start-date").value,
        endDate:   document.getElementById("end-date").value,
        riskFreeRate:    parseFloat(document.getElementById("risk-free-rate").value) / 100,
        confidenceLevel: parseFloat(document.getElementById("confidence-level").value) / 100,
        apiKey,
    };

    setLoading(true);

    try {
        const res = await fetch("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);

        currentData = data;
        renderDashboard(data);
        renderCorrelation(data.correlation);
        renderRisk(data);
        renderAdvanced(data);
        document.getElementById("results-area").style.display = "";
    } catch (e) {
        showError(e.message);
    } finally {
        setLoading(false);
    }
}

// ── Render Dashboard ───────────────────────────────────────────
function renderDashboard(data) {
    const s = data.summary;
    const b = data.benchmark;

    statCard("stat-return",       "Annualized Return",    s.annualReturn + "%",      `Benchmark: ${b.annualReturn}%`, s.annualReturn);
    statCard("stat-vol",          "Annualized Volatility", s.annualVolatility + "%",  `Benchmark: ${b.annualVolatility}%`);
    statCard("stat-sharpe",       "Sharpe Ratio",          fmt(s.sharpeRatio),        `Risk-adjusted return`, s.sharpeRatio);
    statCard("stat-sortino",      "Sortino Ratio",         fmt(s.sortinoRatio),       `Downside risk only`, s.sortinoRatio);
    statCard("stat-info-ratio",   "Information Ratio",     fmt(s.informationRatio),   `Active return / tracking error`, s.informationRatio);
    statCard("stat-max-dd",       "Max Drawdown",          s.maxDrawdown + "%",       `Peak-to-trough loss`, s.maxDrawdown, true);
    statCard("stat-tracking",     "Tracking Error",        s.trackingError + "%",     `vs ${b.ticker}`);
    statCard("stat-bench-sharpe", `Benchmark Sharpe (${b.ticker})`, fmt(b.sharpeRatio), `${b.annualReturn}% return`, b.sharpeRatio);

    // Cumulative returns chart
    const ts = data.timeSeries;
    Plotly.newPlot("chart-cumulative", [
        { x: ts.dates, y: ts.portfolio,  name: "Portfolio",  line: { color: "#2563eb", width: 2 } },
        { x: ts.dates, y: ts.benchmark,  name: b.ticker,     line: { color: "#9ca3af", width: 1.5, dash: "dot" } },
    ], {
        margin: { t: 20, b: 50, l: 60, r: 20 },
        xaxis: { title: "Date" },
        yaxis: { title: "Growth of $1", tickformat: "$.2f" },
        legend: { x: 0.02, y: 0.98 },
        hovermode: "x unified",
    }, { responsive: true });

    // Asset stats table
    const tbody = document.getElementById("asset-stats-body");
    tbody.innerHTML = data.assetStats.map(a => `
        <tr>
            <td><strong>${a.ticker}</strong></td>
            <td class="${a.annualReturn >= 0 ? 'text-success' : 'text-danger'}">${a.annualReturn}%</td>
            <td>${a.annualVol}%</td>
            <td>${a.sharpe.toFixed(4)}</td>
        </tr>`).join("");
}

// ── Render Correlation ─────────────────────────────────────────
function renderCorrelation(corr) {
    // Heatmap
    const colorscale = [
        [0, "#dc2626"], [0.25, "#fca5a5"], [0.5, "#fefce8"],
        [0.75, "#86efac"], [1, "#16a34a"]
    ];

    Plotly.newPlot("chart-correlation", [{
        z: corr.matrix,
        x: corr.labels,
        y: corr.labels,
        type: "heatmap",
        colorscale: colorscale,
        zmin: -1, zmax: 1,
        text: corr.matrix.map(row => row.map(v => v.toFixed(3))),
        texttemplate: "%{text}",
        hovertemplate: "%{x} / %{y}: %{z:.4f}<extra></extra>",
    }], {
        margin: { t: 30, b: 80, l: 80, r: 30 },
        xaxis: { side: "bottom" },
    }, { responsive: true });

    // Numeric table
    const table = document.getElementById("corr-table");
    let html = "<thead class='table-dark'><tr><th></th>" +
        corr.labels.map(l => `<th>${l}</th>`).join("") + "</tr></thead><tbody>";
    corr.matrix.forEach((row, i) => {
        html += `<tr><th class="table-dark">${corr.labels[i]}</th>`;
        row.forEach(v => {
            const bg = corrColor(v);
            html += `<td style="background:${bg}">${v.toFixed(4)}</td>`;
        });
        html += "</tr>";
    });
    html += "</tbody>";
    table.innerHTML = html;
}

function corrColor(v) {
    if (v > 0.7)  return "#bbf7d0";
    if (v > 0.3)  return "#dcfce7";
    if (v > -0.3) return "#fefce8";
    if (v > -0.7) return "#fecaca";
    return "#fca5a5";
}

// ── Render Risk / VaR ──────────────────────────────────────────
function renderRisk(data) {
    const v = data.var;
    const cl = (v.confidenceLevel * 100).toFixed(0);

    statCard("var-parametric",  `Parametric VaR (${cl}%)`,  fmt(v.parametric) + "%",  "Daily, normal assumption", v.parametric, true);
    statCard("var-historical",  `Historical VaR (${cl}%)`,  fmt(v.historical) + "%",  "Daily, empirical percentile", v.historical, true);
    statCard("var-montecarlo",  `Monte Carlo VaR (${cl}%)`, fmt(v.monteCarlo) + "%",  "Daily, 10k simulations", v.monteCarlo, true);

    // Drawdown chart
    const ts = data.timeSeries;
    Plotly.newPlot("chart-drawdown", [{
        x: ts.dates,
        y: ts.drawdown.map(d => d * 100),
        type: "scatter",
        fill: "tozeroy",
        line: { color: "#dc2626", width: 1 },
        fillcolor: "rgba(220,38,38,0.15)",
        hovertemplate: "%{x}<br>Drawdown: %{y:.2f}%<extra></extra>",
    }], {
        margin: { t: 20, b: 50, l: 60, r: 20 },
        xaxis: { title: "Date" },
        yaxis: { title: "Drawdown (%)", ticksuffix: "%" },
        hovermode: "x unified",
    }, { responsive: true });
}

// ── Regression ─────────────────────────────────────────────────
async function runRegression() {
    hideError();
    const input = document.getElementById("factor-tickers").value.trim();
    const factors = input ? input.split(",").map(s => s.trim().toUpperCase()).filter(Boolean) : [];

    document.getElementById("regression-loading").classList.remove("d-none");
    document.getElementById("regression-results").style.display = "none";

    try {
        const res = await fetch("/api/regression", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ factors }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);

        renderRegression(data);
    } catch (e) {
        showError(e.message);
    } finally {
        document.getElementById("regression-loading").classList.add("d-none");
    }
}

function renderRegression(data) {
    statCard("reg-alpha", "Alpha (annualized)",
        fmt(data.alphaAnnualized) + "%",
        `p-value: ${fmt(data.alphaPValue)}`, data.alphaAnnualized);
    statCard("reg-r2", "R-Squared",
        fmt(data.rSquared),
        `Adj R\u00B2: ${fmt(data.adjRSquared)}`);
    statCard("reg-f", "F-Statistic",
        fmt(data.fStatistic, 2),
        `p-value: ${fmt(data.fPValue, 6)}`);
    statCard("reg-dw", "Durbin-Watson",
        fmt(data.durbinWatson),
        `${data.observations} observations`);

    // Factor table
    const tbody = document.getElementById("factor-table-body");
    tbody.innerHTML = data.factors.map(f => {
        let sig, cls;
        if (f.pValue < 0.01)      { sig = "***"; cls = "sig-high"; }
        else if (f.pValue < 0.05) { sig = "**";  cls = "sig-medium"; }
        else if (f.pValue < 0.10) { sig = "*";   cls = "sig-medium"; }
        else                      { sig = "n.s."; cls = "sig-low"; }

        return `<tr>
            <td><strong>${f.name}</strong></td>
            <td>${f.coefficient.toFixed(4)}</td>
            <td>${f.stdError.toFixed(4)}</td>
            <td>${f.tStat.toFixed(4)}</td>
            <td>${f.pValue.toFixed(6)}</td>
            <td><span class="sig-badge ${cls}">${sig}</span></td>
        </tr>`;
    }).join("");

    // Residuals chart
    Plotly.newPlot("chart-residuals", [{
        x: data.residuals.dates,
        y: data.residuals.values,
        type: "scatter",
        mode: "lines",
        line: { color: "#6366f1", width: 1 },
        hovertemplate: "%{x}<br>Residual: %{y:.6f}<extra></extra>",
    }], {
        margin: { t: 20, b: 50, l: 60, r: 20 },
        xaxis: { title: "Date" },
        yaxis: { title: "Residual" },
        shapes: [{ type: "line", x0: data.residuals.dates[0], x1: data.residuals.dates.at(-1),
                    y0: 0, y1: 0, line: { color: "#94a3b8", dash: "dash" } }],
        hovermode: "x unified",
    }, { responsive: true });

    document.getElementById("regression-results").style.display = "";
}

// ── Helpers ────────────────────────────────────────────────────
function fmt(v, digits = 4) {
    if (v === null || v === undefined || (typeof v === "number" && isNaN(v))) return "N/A";
    return v.toFixed(digits);
}

function statCard(id, label, value, sub, numericVal, invertColor) {
    let cls = "";
    if (numericVal !== undefined && numericVal !== null) {
        if (invertColor) {
            cls = numericVal < 0 ? "negative" : "";
        } else {
            cls = numericVal > 0 ? "positive" : numericVal < 0 ? "negative" : "";
        }
    }
    document.getElementById(id).innerHTML = `
        <div class="label">${label}</div>
        <div class="value ${cls}">${value}</div>
        <div class="sub">${sub || ""}</div>`;
}

function showError(msg) {
    const el = document.getElementById("error-alert");
    el.textContent = msg;
    el.classList.remove("d-none");
}

function hideError() {
    document.getElementById("error-alert").classList.add("d-none");
}

function setLoading(on) {
    document.getElementById("loading-spinner").classList.toggle("d-none", !on);
    document.getElementById("analyze-btn").disabled = on;
}

// ── Render Advanced Tab ─────────────────────────────────────────
const PALETTE = ["#2563eb","#dc2626","#16a34a","#f59e0b","#8b5cf6","#ec4899","#06b6d4","#84cc16","#f97316","#6366f1"];

function renderAdvanced(data) {
    // ── Risk Decomposition ──────────────────────────────────────
    const rd = data.riskDecomp;
    if (rd && rd.length > 0) {
        Plotly.newPlot("chart-risk-pie", [{
            values: rd.map(r => Math.abs(r.pctContrib)),
            labels: rd.map(r => r.ticker),
            type: "pie",
            textinfo: "label+percent",
            hovertemplate: "%{label}<br>Risk: %{value:.1f}%<extra></extra>",
            marker: { colors: PALETTE.slice(0, rd.length) },
        }], {
            margin: { t: 10, b: 10, l: 10, r: 10 },
            showlegend: false,
        }, { responsive: true });

        const tbody = document.getElementById("risk-decomp-body");
        tbody.innerHTML = rd.map(r => `
            <tr>
                <td><strong>${r.ticker}</strong></td>
                <td>${r.weight}%</td>
                <td>${r.mcr}%</td>
                <td>${r.ccr}%</td>
                <td>
                    <div class="d-flex align-items-center">
                        <div class="progress flex-grow-1 me-2" style="height:8px;">
                            <div class="progress-bar" style="width:${Math.min(Math.abs(r.pctContrib), 100)}%;background:${r.pctContrib >= 0 ? '#2563eb' : '#dc2626'}"></div>
                        </div>
                        <span class="text-nowrap">${r.pctContrib}%</span>
                    </div>
                </td>
            </tr>`).join("");
    }

    // ── Rolling Statistics ───────────────────────────────────────
    const roll = data.rolling;
    if (roll && roll.dates && roll.dates.length > 0) {
        Plotly.newPlot("chart-rolling-sharpe", [{
            x: roll.dates, y: roll.sharpe,
            type: "scatter", mode: "lines",
            line: { color: "#2563eb", width: 1.5 },
            hovertemplate: "%{x}<br>Sharpe: %{y:.3f}<extra></extra>",
        }, {
            x: [roll.dates[0], roll.dates.at(-1)], y: [0, 0],
            type: "scatter", mode: "lines",
            line: { color: "#94a3b8", dash: "dash", width: 1 },
            showlegend: false, hoverinfo: "skip",
        }], {
            margin: { t: 30, b: 30, l: 60, r: 20 },
            yaxis: { title: "Sharpe Ratio" },
            showlegend: false,
            hovermode: "x unified",
            annotations: [{ text: "Rolling Sharpe Ratio (60-day)", xref: "paper", yref: "paper",
                x: 0.01, y: 0.97, showarrow: false, font: { size: 12, color: "#475569" } }],
        }, { responsive: true });

        Plotly.newPlot("chart-rolling-beta", [{
            x: roll.dates, y: roll.beta,
            type: "scatter", mode: "lines",
            line: { color: "#dc2626", width: 1.5 },
            hovertemplate: "%{x}<br>Beta: %{y:.3f}<extra></extra>",
        }, {
            x: [roll.dates[0], roll.dates.at(-1)], y: [1, 1],
            type: "scatter", mode: "lines",
            line: { color: "#94a3b8", dash: "dash", width: 1 },
            showlegend: false, hoverinfo: "skip",
        }], {
            margin: { t: 10, b: 50, l: 60, r: 20 },
            xaxis: { title: "Date" },
            yaxis: { title: "Beta" },
            showlegend: false,
            hovermode: "x unified",
            annotations: [{ text: "Rolling Beta vs Benchmark (60-day)", xref: "paper", yref: "paper",
                x: 0.01, y: 0.97, showarrow: false, font: { size: 12, color: "#475569" } }],
        }, { responsive: true });
    }
}

// ── Efficient Frontier ──────────────────────────────────────────
async function runFrontier() {
    hideError();
    document.getElementById("frontier-loading").classList.remove("d-none");
    document.getElementById("frontier-btn").disabled = true;

    try {
        const res = await fetch("/api/frontier", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);
        renderFrontier(data);
    } catch (e) {
        showError(e.message);
    } finally {
        document.getElementById("frontier-loading").classList.add("d-none");
        document.getElementById("frontier-btn").disabled = false;
    }
}

function renderFrontier(data) {
    const pts = data.portfolios;
    const ms = data.maxSharpe;
    const mv = data.minVol;

    const traces = [{
        x: pts.map(p => p.vol),
        y: pts.map(p => p.ret),
        mode: "markers",
        type: "scatter",
        marker: {
            size: 4,
            color: pts.map(p => p.sharpe),
            colorscale: "Viridis",
            colorbar: { title: "Sharpe", thickness: 15 },
            opacity: 0.5,
        },
        name: "Random Portfolios",
        hovertemplate: "Vol: %{x:.1f}%<br>Return: %{y:.1f}%<extra></extra>",
    }, {
        x: [ms.vol], y: [ms.ret],
        mode: "markers", type: "scatter",
        marker: { size: 16, color: "#f59e0b", symbol: "star", line: { width: 2, color: "#fff" } },
        name: `Max Sharpe (${ms.sharpe.toFixed(2)})`,
        hovertemplate: `<b>Max Sharpe</b><br>Return: ${ms.ret}%<br>Vol: ${ms.vol}%<br>Sharpe: ${ms.sharpe}<extra></extra>`,
    }, {
        x: [mv.vol], y: [mv.ret],
        mode: "markers", type: "scatter",
        marker: { size: 16, color: "#16a34a", symbol: "diamond", line: { width: 2, color: "#fff" } },
        name: "Min Volatility",
        hovertemplate: `<b>Min Vol</b><br>Return: ${mv.ret}%<br>Vol: ${mv.vol}%<extra></extra>`,
    }];

    // Show current portfolio position
    if (currentData) {
        const s = currentData.summary;
        traces.push({
            x: [s.annualVolatility], y: [s.annualReturn],
            mode: "markers", type: "scatter",
            marker: { size: 16, color: "#dc2626", symbol: "cross", line: { width: 3, color: "#fff" } },
            name: "Your Portfolio",
            hovertemplate: `<b>Your Portfolio</b><br>Return: ${s.annualReturn}%<br>Vol: ${s.annualVolatility}%<extra></extra>`,
        });
    }

    Plotly.newPlot("chart-frontier", traces, {
        margin: { t: 20, b: 60, l: 70, r: 20 },
        xaxis: { title: "Annualized Volatility (%)" },
        yaxis: { title: "Annualized Return (%)" },
        legend: { x: 0.02, y: 0.98 },
        hovermode: "closest",
    }, { responsive: true });

    // Stat cards for optimal portfolios
    const tickers = data.tickers;
    statCard("frontier-max-sharpe", "Max Sharpe Portfolio",
        `Sharpe: ${ms.sharpe} | Return: ${ms.ret}% | Vol: ${ms.vol}%`,
        tickers.map((t, i) => `${t}: ${(ms.weights[i] * 100).toFixed(1)}%`).join("  ·  "),
        ms.sharpe);
    statCard("frontier-min-vol", "Min Volatility Portfolio",
        `Vol: ${mv.vol}% | Return: ${mv.ret}% | Sharpe: ${mv.sharpe}`,
        tickers.map((t, i) => `${t}: ${(mv.weights[i] * 100).toFixed(1)}%`).join("  ·  "));

    document.getElementById("frontier-stats").style.display = "";
}

// ── Leverage Simulation ─────────────────────────────────────────
const LEV_COLORS = ["#94a3b8","#64748b","#2563eb","#0ea5e9","#16a34a","#f59e0b","#dc2626","#9333ea"];

async function runLeverage() {
    hideError();
    document.getElementById("leverage-loading").classList.remove("d-none");
    document.getElementById("leverage-btn").disabled = true;
    document.getElementById("leverage-results").style.display = "none";

    const levInput = document.getElementById("leverage-levels").value;
    const levels = levInput.split(",").map(s => parseFloat(s.trim())).filter(v => !isNaN(v));
    const borrowRate = parseFloat(document.getElementById("leverage-borrow-rate").value) / 100;

    try {
        const res = await fetch("/api/leverage", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ levels, borrowRate }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);
        renderLeverage(data);
    } catch (e) {
        showError(e.message);
    } finally {
        document.getElementById("leverage-loading").classList.add("d-none");
        document.getElementById("leverage-btn").disabled = false;
    }
}

function renderLeverage(data) {
    const lvls = data.levels;
    const dates = data.dates;
    const unlev = data.unleveragedIdx;

    // ── Metrics Table ────────────────────────────────────────────
    const tbody = document.getElementById("leverage-table-body");
    tbody.innerHTML = lvls.map((lv, i) => {
        const isBase = (i === unlev);
        const rowCls = isBase ? 'class="table-primary fw-bold"' : '';
        const badge = isBase ? ' <span class="badge bg-primary ms-1">baseline</span>' : '';
        const retCls = lv.annReturn >= 0 ? "text-success" : "text-danger";
        const ddCls = "text-danger";
        return `<tr ${rowCls}>
            <td>${lv.leverage.toFixed(2)}&times;${badge}</td>
            <td class="${retCls}">${lv.annReturn.toFixed(2)}%</td>
            <td>${lv.annVol.toFixed(2)}%</td>
            <td>${lv.sharpe.toFixed(4)}</td>
            <td>${lv.sortino !== null ? lv.sortino.toFixed(4) : "N/A"}</td>
            <td class="${ddCls}">${lv.maxDrawdown.toFixed(2)}%</td>
            <td>${lv.var95.toFixed(4)}%</td>
        </tr>`;
    }).join("");

    // ── Capital Market Line Chart ────────────────────────────────
    const cmlTraces = [{
        x: lvls.map(l => l.annVol),
        y: lvls.map(l => l.annReturn),
        mode: "lines+markers+text",
        type: "scatter",
        text: lvls.map(l => l.leverage.toFixed(2) + "×"),
        textposition: "top center",
        textfont: { size: 10, color: "#475569" },
        marker: {
            size: lvls.map((l, i) => i === unlev ? 14 : 10),
            color: lvls.map((l, i) => i === unlev ? "#2563eb" : "#64748b"),
            symbol: lvls.map((l, i) => i === unlev ? "star" : "circle"),
            line: { width: 2, color: "#fff" },
        },
        line: { color: "#2563eb", width: 2, dash: "dot" },
        name: "Leveraged Portfolios",
        hovertemplate: "%{text}<br>Return: %{y:.2f}%<br>Vol: %{x:.2f}%<extra></extra>",
    }];

    Plotly.newPlot("chart-leverage-cml", cmlTraces, {
        margin: { t: 20, b: 60, l: 70, r: 20 },
        xaxis: { title: "Annualized Volatility (%)" },
        yaxis: { title: "Annualized Return (%)" },
        showlegend: false,
        hovermode: "closest",
        annotations: [{
            text: `Borrowing rate: ${data.borrowRate}%`,
            xref: "paper", yref: "paper", x: 0.98, y: 0.02,
            showarrow: false, font: { size: 11, color: "#64748b" },
            xanchor: "right",
        }],
    }, { responsive: true });

    // ── Cumulative Returns Chart ─────────────────────────────────
    const cumTraces = lvls.map((lv, i) => ({
        x: dates,
        y: lv.cumulative,
        type: "scatter",
        mode: "lines",
        name: lv.leverage.toFixed(2) + "×",
        line: {
            color: LEV_COLORS[i % LEV_COLORS.length],
            width: (i === unlev) ? 3 : 1.5,
            dash: (i === unlev) ? "solid" : undefined,
        },
        opacity: (i === unlev) ? 1 : 0.7,
        hovertemplate: `${lv.leverage.toFixed(2)}×: $%{y:.3f}<extra></extra>`,
    }));

    Plotly.newPlot("chart-leverage-cum", cumTraces, {
        margin: { t: 20, b: 50, l: 60, r: 20 },
        xaxis: { title: "Date" },
        yaxis: { title: "Growth of $1", tickprefix: "$" },
        legend: { x: 0.02, y: 0.98 },
        hovermode: "x unified",
    }, { responsive: true });

    // ── Drawdown Chart ───────────────────────────────────────────
    const ddTraces = lvls.map((lv, i) => ({
        x: dates,
        y: lv.drawdown.map(d => d * 100),
        type: "scatter",
        mode: "lines",
        name: lv.leverage.toFixed(2) + "×",
        line: {
            color: LEV_COLORS[i % LEV_COLORS.length],
            width: (i === unlev) ? 2.5 : 1.2,
        },
        opacity: (i === unlev) ? 1 : 0.6,
        hovertemplate: `${lv.leverage.toFixed(2)}×: %{y:.2f}%<extra></extra>`,
    }));

    Plotly.newPlot("chart-leverage-dd", ddTraces, {
        margin: { t: 20, b: 50, l: 60, r: 20 },
        xaxis: { title: "Date" },
        yaxis: { title: "Drawdown (%)", ticksuffix: "%" },
        legend: { x: 0.02, y: -0.15, orientation: "h" },
        hovermode: "x unified",
    }, { responsive: true });

    document.getElementById("leverage-results").style.display = "";
}
