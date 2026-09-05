/**
 * Breakout Screener — Frontend Application
 * Handles tab switching, config management, API calls, and result rendering.
 */

const API_BASE = window.location.origin;

// ─── State ─────────────────────────────────────────────────────────────────
let currentTab = 'backtest';
let backtestStats = null;
let scanResults = null;
let signalSortCol = 'strength_score';
let signalSortDir = 'DESC';
let tableSortInitialized = false;

// ─── Initialization ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initConfigListeners();
    loadSavedConfig();
    checkDataStatus();
    checkMarketRegime();
    loadCachedBacktestResults();
});

// ─── Tab Switching ─────────────────────────────────────────────────────────
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            switchTab(tab);
        });
    });
}

function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
    document.getElementById(`tab-${tab}`).classList.add('active');
}

// ─── Market Regime ─────────────────────────────────────────────────────────
async function checkMarketRegime() {
    try {
        const res = await fetch(`${API_BASE}/api/market-regime`);
        const data = await res.json();
        const badge = document.getElementById('regime-badge');
        const nifty = document.getElementById('regime-nifty');
        const advice = document.getElementById('regime-advice');

        if (badge && data) {
            badge.textContent = data.badge || '🟢 Bull Market';
            if (nifty) nifty.textContent = `Nifty 50: ₹${data.nifty_close?.toLocaleString('en-IN') || '—'}`;
            if (advice) advice.textContent = data.advice || '';
        }
    } catch (e) {
        console.error('Error loading market regime:', e);
    }
}

// ─── Config ────────────────────────────────────────────────────────────────
function initConfigListeners() {
    // Show/hide N-day lookback based on resistance mode
    document.getElementById('resistance-mode').addEventListener('change', (e) => {
        document.getElementById('n-day-group').style.display =
            e.target.value === 'N_DAY_HIGH' ? '' : 'none';
        saveConfig();
    });

    // Show/hide Near Breakout threshold input
    document.getElementById('scan-type').addEventListener('change', (e) => {
        document.getElementById('near-pct-group').style.display =
            e.target.value === 'NEAR_BREAKOUT' ? '' : 'none';
        saveConfig();
    });

    // Show/hide RSI threshold based on RSI filter toggle
    document.getElementById('rsi-filter').addEventListener('change', (e) => {
        document.getElementById('rsi-threshold-group').style.display =
            e.target.checked ? '' : 'none';
        saveConfig();
    });

    // Save config on any change
    document.querySelectorAll('.config-group input, .config-group select').forEach(el => {
        el.addEventListener('change', saveConfig);
    });
}

function getConfig() {
    return {
        scan_type: document.getElementById('scan-type').value,
        near_breakout_pct: parseFloat(document.getElementById('near-breakout-pct').value),
        risk_per_trade_inr: parseFloat(document.getElementById('risk-per-trade').value),
        resistance_mode: document.getElementById('resistance-mode').value,
        n_day_lookback: parseInt(document.getElementById('n-day-lookback').value),
        volume_multiplier: parseFloat(document.getElementById('volume-multiplier').value),
        volume_lookback: parseInt(document.getElementById('volume-lookback').value),
        min_price: parseFloat(document.getElementById('min-price').value),
        min_turnover_cr: parseFloat(document.getElementById('min-turnover').value),
        require_above_200dma: document.getElementById('require-200dma').checked,
        rsi_filter_enabled: document.getElementById('rsi-filter').checked,
        rsi_threshold: parseFloat(document.getElementById('rsi-threshold').value),
        min_rs_rating: parseFloat(document.getElementById('min-rs-rating').value),
        require_vcp: document.getElementById('require-vcp').checked,
        min_ai_prob: parseInt(document.getElementById('min-ai-prob').value) || 0,
    };
}

function configToQueryParams(config) {
    const params = new URLSearchParams();
    for (const [key, val] of Object.entries(config)) {
        if (val !== null && val !== undefined) {
            params.set(key, val);
        }
    }
    return params.toString();
}

function saveConfig() {
    localStorage.setItem('screener_config', JSON.stringify(getConfig()));
}

function loadSavedConfig() {
    const saved = localStorage.getItem('screener_config');
    if (!saved) return;

    try {
        const config = JSON.parse(saved);
        if (config.scan_type) document.getElementById('scan-type').value = config.scan_type;
        if (config.near_breakout_pct) document.getElementById('near-breakout-pct').value = config.near_breakout_pct;
        if (config.risk_per_trade_inr) document.getElementById('risk-per-trade').value = config.risk_per_trade_inr;
        if (config.resistance_mode) document.getElementById('resistance-mode').value = config.resistance_mode;
        if (config.n_day_lookback) document.getElementById('n-day-lookback').value = config.n_day_lookback;
        if (config.volume_multiplier) document.getElementById('volume-multiplier').value = config.volume_multiplier;
        if (config.volume_lookback) document.getElementById('volume-lookback').value = config.volume_lookback;
        if (config.min_price !== undefined) document.getElementById('min-price').value = config.min_price;
        if (config.min_turnover_cr !== undefined) document.getElementById('min-turnover').value = config.min_turnover_cr;
        if (config.require_above_200dma !== undefined) document.getElementById('require-200dma').checked = config.require_above_200dma;
        if (config.rsi_filter_enabled !== undefined) document.getElementById('rsi-filter').checked = config.rsi_filter_enabled;
        if (config.rsi_threshold) document.getElementById('rsi-threshold').value = config.rsi_threshold;
        if (config.min_rs_rating !== undefined) document.getElementById('min-rs-rating').value = config.min_rs_rating;
        if (config.require_vcp !== undefined) document.getElementById('require-vcp').checked = config.require_vcp;
        if (config.min_ai_prob !== undefined) document.getElementById('min-ai-prob').value = config.min_ai_prob;

        // Trigger visibility updates
        document.getElementById('near-pct-group').style.display =
            config.scan_type === 'NEAR_BREAKOUT' ? '' : 'none';
        document.getElementById('n-day-group').style.display =
            config.resistance_mode === 'N_DAY_HIGH' ? '' : 'none';
        document.getElementById('rsi-threshold-group').style.display =
            config.rsi_filter_enabled ? '' : 'none';
    } catch (e) {
        console.error('Error loading saved config:', e);
    }
}

// ─── Data Status ───────────────────────────────────────────────────────────
async function checkDataStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/data/status`);
        const data = await res.json();
        updateDataStatus(data);
    } catch (e) {
        console.error('Error checking data status:', e);
        updateDataStatus(null);
    }
}

function updateDataStatus(data) {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');

    if (!data || data.cached_stocks === 0) {
        dot.className = 'status-dot empty';
        text.textContent = 'No data — sync required';
        return;
    }

    if (data.auto_sync && data.auto_sync.is_syncing) {
        dot.className = 'status-dot syncing';
        const cur = data.auto_sync.current || 0;
        const tot = data.auto_sync.total || data.total_stocks || 500;
        text.textContent = `Auto-refreshing: ${cur}/${tot} stocks...`;
        setTimeout(checkDataStatus, 2000);
        return;
    }

    const isRecent = data.latest_date &&
        (new Date() - new Date(data.latest_date)) < 4 * 24 * 60 * 60 * 1000;

    dot.className = `status-dot ${isRecent ? '' : 'stale'}`;
    text.textContent = `${data.cached_stocks} stocks · ${data.latest_date || 'N/A'}`;
}

// ─── Data Sync ─────────────────────────────────────────────────────────────
async function syncData() {
    const btn = document.getElementById('btn-sync');
    const progress = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');

    btn.classList.add('loading');
    btn.disabled = true;
    progress.classList.add('active');

    try {
        const res = await fetch(`${API_BASE}/api/data/sync`, { method: 'POST' });
        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const lines = text.split('\n').filter(l => l.startsWith('data: '));

            for (const line of lines) {
                try {
                    const data = JSON.parse(line.slice(6));
                    const pct = data.total > 0 ? (data.current / data.total * 100) : 0;
                    progressBar.style.width = `${pct}%`;
                    progressText.textContent = data.message || 'Syncing...';

                    if (data.done) {
                        progressText.textContent = `✅ ${data.message}`;
                        checkDataStatus();
                    }
                } catch (e) { /* skip malformed lines */ }
            }
        }
    } catch (e) {
        console.error('Sync error:', e);
        progressText.textContent = '❌ Sync failed. Check console.';
    } finally {
        btn.classList.remove('loading');
        btn.disabled = false;
        setTimeout(() => progress.classList.remove('active'), 3000);
    }
}

// ─── Backtest ──────────────────────────────────────────────────────────────
async function runBacktest() {
    switchTab('backtest');
    const btn = document.getElementById('btn-backtest');
    const progress = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');

    btn.classList.add('loading');
    btn.disabled = true;
    progress.classList.add('active');

    const config = getConfig();
    const params = configToQueryParams(config);

    try {
        const res = await fetch(`${API_BASE}/api/backtest/run?${params}`, { method: 'POST' });
        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const lines = text.split('\n').filter(l => l.startsWith('data: '));

            for (const line of lines) {
                try {
                    const data = JSON.parse(line.slice(6));
                    const pct = data.total > 0 ? (data.current / data.total * 100) : 0;
                    progressBar.style.width = `${pct}%`;
                    progressText.textContent = data.message || 'Running backtest...';

                    if (data.done && data.stats) {
                        backtestStats = data.stats;
                        renderBacktestResults(data.stats);
                        progressText.textContent = `✅ ${data.message}`;
                        loadBacktestSignals();
                    }
                } catch (e) { /* skip */ }
            }
        }
    } catch (e) {
        console.error('Backtest error:', e);
        progressText.textContent = '❌ Backtest failed. Check console.';
    } finally {
        btn.classList.remove('loading');
        btn.disabled = false;
        setTimeout(() => progress.classList.remove('active'), 3000);
    }
}

async function loadCachedBacktestResults() {
    try {
        const res = await fetch(`${API_BASE}/api/backtest/results`);
        const stats = await res.json();
        if (stats && stats.total_signals > 0) {
            backtestStats = stats;
            renderBacktestResults(stats);
            loadBacktestSignals();
        }
    } catch (e) {
        console.log('No cached backtest results');
    }
}

function renderBacktestResults(stats) {
    document.getElementById('backtest-empty').style.display = 'none';
    document.getElementById('backtest-results').style.display = 'block';

    // Stats cards
    const cardsHtml = buildStatsCards(stats);
    document.getElementById('stats-cards').innerHTML = cardsHtml;

    // Score bucket chart
    if (stats.score_buckets) {
        renderBucketChart(stats.score_buckets);
    }

    // Monthly distribution
    if (stats.monthly_distribution) {
        renderMonthlyChart(stats.monthly_distribution);
    }
}

function buildStatsCards(stats) {
    const cards = [];

    cards.push(cardHtml('Total Signals', stats.total_signals, 'neutral'));
    cards.push(cardHtml('Avg Score', stats.avg_strength_score, 'neutral'));

    for (const days of [5, 10, 20, 30]) {
        const key = `stats_${days}d`;
        if (stats[key]) {
            const s = stats[key];
            const cls = s.win_rate >= 50 ? 'positive' : 'negative';
            cards.push(cardHtml(
                `${days}D Win Rate`,
                `${s.win_rate}%`,
                cls,
                `Avg: ${s.avg_return > 0 ? '+' : ''}${s.avg_return}%`
            ));
        }
    }

    if (stats.date_range) {
        cards.push(cardHtml('Period', `${formatDate(stats.date_range.start)}`, 'neutral',
            `to ${formatDate(stats.date_range.end)}`));
    }

    return cards.join('');
}

function cardHtml(label, value, cls = 'neutral', sub = '') {
    return `
        <div class="stat-card">
            <div class="stat-label">${label}</div>
            <div class="stat-value ${cls}">${value}</div>
            ${sub ? `<div class="stat-sub">${sub}</div>` : ''}
        </div>
    `;
}

// ─── Score Bucket Chart ────────────────────────────────────────────────────
function renderBucketChart(buckets) {
    const container = document.getElementById('bucket-chart');

    // Header
    let html = `
        <div class="bucket-row" style="font-weight:600; color:var(--text-muted); font-size:0.7rem; text-transform:uppercase; letter-spacing:0.04em">
            <span>Score</span>
            <span>Signals</span>
            <span style="text-align:right">10D Win%</span>
            <span style="text-align:right">10D Avg</span>
        </div>
    `;

    const maxCount = Math.max(...buckets.map(b => b.count));

    const colorMap = {
        '80-100': 'green',
        '60-79': 'blue',
        '40-59': 'blue',
        '20-39': 'amber',
        '1-19': 'red',
    };

    for (const bucket of buckets) {
        const barWidth = (bucket.count / maxCount * 100).toFixed(0);
        const color = colorMap[bucket.bucket] || 'blue';
        const winRate = bucket.win_rate_10d ?? bucket.win_rate_5d ?? '—';
        const avgReturn = bucket.avg_return_10d ?? bucket.avg_return_5d ?? '—';
        const returnCls = typeof avgReturn === 'number'
            ? (avgReturn > 0 ? 'return-positive' : 'return-negative')
            : 'return-neutral';
        const winCls = typeof winRate === 'number'
            ? (winRate >= 50 ? 'return-positive' : 'return-negative')
            : 'return-neutral';

        html += `
            <div class="bucket-row">
                <span class="bucket-label">${bucket.bucket}</span>
                <div class="bucket-bar-container">
                    <div class="bucket-bar ${color}" style="width: ${barWidth}%">${bucket.count}</div>
                </div>
                <span class="bucket-win-rate ${winCls}">${typeof winRate === 'number' ? winRate + '%' : winRate}</span>
                <span class="bucket-avg-return ${returnCls}">${typeof avgReturn === 'number' ? (avgReturn > 0 ? '+' : '') + avgReturn + '%' : avgReturn}</span>
            </div>
        `;
    }

    container.innerHTML = html;
}

// ─── Monthly Chart ─────────────────────────────────────────────────────────
function renderMonthlyChart(monthly) {
    const container = document.getElementById('monthly-chart');
    const maxCount = Math.max(...monthly.map(m => m.count));

    let html = '';
    for (const m of monthly) {
        const height = (m.count / maxCount * 100).toFixed(0);
        const label = m.month.length > 7 ? m.month.slice(2) : m.month; // Shorten year
        html += `
            <div class="monthly-bar-wrapper">
                <span class="monthly-bar-count">${m.count}</span>
                <div class="monthly-bar" style="height: ${height}%" title="${m.month}: ${m.count} signals, avg score ${m.avg_score}"></div>
                <span class="monthly-bar-label">${label}</span>
            </div>
        `;
    }

    container.innerHTML = html;
}

// ─── Signal Table ──────────────────────────────────────────────────────────
async function loadBacktestSignals() {
    try {
        const params = new URLSearchParams({
            limit: '200',
            offset: '0',
            sort_by: signalSortCol,
            sort_dir: signalSortDir,
        });

        const res = await fetch(`${API_BASE}/api/backtest/signals?${params}`);
        const data = await res.json();

        document.getElementById('signal-count').textContent = `${data.total} signals`;
        renderSignalTable(data.signals);
        initTableSort();
    } catch (e) {
        console.error('Error loading signals:', e);
    }
}

function renderSignalTable(signals) {
    const tbody = document.getElementById('signals-tbody');

    if (!signals || signals.length === 0) {
        tbody.innerHTML = `
            <tr><td colspan="11" style="text-align:center; padding:2rem; color:var(--text-muted)">
                No signals to display
            </td></tr>
        `;
        return;
    }

    let html = '';
    for (const s of signals) {
        html += `
            <tr>
                <td>${formatDate(s.signal_date)}</td>
                <td style="font-weight:600">
                    <a href="https://www.google.com/finance/quote/${s.symbol}:NSE" target="_blank" rel="noopener noreferrer" class="stock-link" title="View ${s.symbol} on Google Finance">
                        ${s.symbol} <span class="ext-icon">↗</span>
                    </a>
                </td>
                <td style="color:var(--text-secondary)">${s.company || ''}</td>
                <td>${scoreBadge(s.strength_score)}</td>
                <td>${s.pct_above?.toFixed(2)}%</td>
                <td>${s.volume_ratio?.toFixed(1)}×</td>
                <td style="color:var(--text-secondary)">${s.rsi?.toFixed(0) ?? '—'}</td>
                <td class="${returnClass(s.return_5d)}">${formatReturn(s.return_5d)}</td>
                <td class="${returnClass(s.return_10d)}">${formatReturn(s.return_10d)}</td>
                <td class="${returnClass(s.return_20d)}">${formatReturn(s.return_20d)}</td>
                <td class="${returnClass(s.return_30d)}">${formatReturn(s.return_30d)}</td>
            </tr>
        `;
    }

    tbody.innerHTML = html;
}

function initTableSort() {
    if (tableSortInitialized) return;
    tableSortInitialized = true;

    document.querySelectorAll('#signals-table th[data-sort]').forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (signalSortCol === col) {
                signalSortDir = signalSortDir === 'DESC' ? 'ASC' : 'DESC';
            } else {
                signalSortCol = col;
                signalSortDir = 'DESC';
            }

            // Update visual indicator
            document.querySelectorAll('#signals-table th').forEach(h => h.classList.remove('sorted'));
            th.classList.add('sorted');

            loadBacktestSignals();
        });
    });
}

// ─── Live Scan ─────────────────────────────────────────────────────────────
async function runLiveScan() {
    switchTab('scan');
    const btn = document.getElementById('btn-scan');
    const progress = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');

    btn.classList.add('loading');
    btn.disabled = true;
    progress.classList.add('active');
    progressBar.style.width = '0%';
    progressText.textContent = 'Initializing live scan across Nifty 500...';

    const config = getConfig();
    const params = configToQueryParams(config);

    try {
        const res = await fetch(`${API_BASE}/api/scan?${params}`, { method: 'POST' });
        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const lines = text.split('\n').filter(l => l.startsWith('data: '));

            for (const line of lines) {
                try {
                    const data = JSON.parse(line.slice(6));
                    const pct = data.total > 0 ? (data.current / data.total * 100) : 0;
                    progressBar.style.width = `${pct}%`;
                    progressText.textContent = data.message || 'Scanning stocks...';

                    if (data.done && data.data) {
                        scanResults = data.data;
                        renderScanResults(data.data);
                        progressText.textContent = `✅ ${data.message}`;
                    }
                } catch (e) { /* skip */ }
            }
        }

    } catch (e) {
        console.error('Scan error:', e);
        progressText.textContent = '❌ Scan failed. Check console.';
    } finally {
        btn.classList.remove('loading');
        btn.disabled = false;
        setTimeout(() => progress.classList.remove('active'), 3000);
    }
}

function renderScanResults(data) {
    const grid = document.getElementById('scan-results');
    const empty = document.getElementById('scan-empty');
    const statsContainer = document.getElementById('scan-stats');

    if (!data.breakouts || data.breakouts.length === 0) {
        grid.innerHTML = '';
        statsContainer.style.display = 'none';
        empty.style.display = 'block';
        empty.querySelector('h3').textContent = 'No Breakouts Today';
        empty.querySelector('p').textContent = 'No stocks matched the breakout criteria. Try relaxing filters or check back after market close.';
        return;
    }

    empty.style.display = 'none';

    // Stats
    statsContainer.style.display = 'grid';
    statsContainer.innerHTML = `
        ${cardHtml('Breakouts Found', data.total, 'positive')}
        ${cardHtml('Stocks Scanned', data.scanned, 'neutral')}
        ${cardHtml('Hit Rate', `${(data.total / data.scanned * 100).toFixed(1)}%`, 'neutral')}
        ${cardHtml('Top Score', data.breakouts[0]?.strength_score || '—', 'positive',
            data.breakouts[0]?.symbol || '')}
    `;

    // Result cards
    let html = '';
    for (let i = 0; i < data.breakouts.length; i++) {
        const b = data.breakouts[i];
        const tp = b.trade_plan || {};
        const isNear = b.scan_type === 'NEAR_BREAKOUT';

        // AI Confidence level styling
        let aiClass = 'high';
        if (b.ai_probability < 50) aiClass = 'low';
        else if (b.ai_probability < 70) aiClass = 'medium';

        html += `
            <div class="result-card" style="animation-delay: ${i * 0.05}s">
                <div class="result-card-header">
                    <div>
                        <div class="result-symbol">
                            <a href="https://www.google.com/finance/quote/${b.symbol}:NSE" target="_blank" rel="noopener noreferrer" class="stock-link" title="Open ${b.symbol} on Google Finance">
                                ${b.symbol} <span class="ext-icon">↗</span>
                            </a>
                            ${isNear ? `<span style="font-size:0.7rem; color:var(--accent-amber); margin-left:0.4rem; font-weight:600">⚡ Pre-Breakout</span>` : ''}
                        </div>
                        <div class="result-company">${b.company || ''}</div>
                        ${b.industry ? `<div class="result-industry">${b.industry}</div>` : ''}
                        
                        <!-- AI & Setup Tags -->
                        <div class="setup-tags-row">
                            ${b.ai_probability ? `<span class="ai-prob-badge ${aiClass}">🤖 AI Win: ${b.ai_probability}%</span>` : ''}
                            ${b.mansfield_rs !== undefined && b.mansfield_rs > 0 ? `<span class="tag-badge rs-leader">📈 RS +${b.mansfield_rs}%</span>` : ''}
                            ${b.is_vcp ? `<span class="tag-badge vcp-squeeze">🎯 VCP Squeeze (${b.vcp_compression_pct}%)</span>` : ''}
                        </div>
                    </div>
                    ${scoreBadge(b.strength_score)}
                </div>

                <div class="result-metrics">
                    <div class="result-metric">
                        <span class="result-metric-label">Close</span>
                        <span class="result-metric-value">₹${b.close_price?.toLocaleString('en-IN')}</span>
                    </div>
                    <div class="result-metric">
                        <span class="result-metric-label">Resistance</span>
                        <span class="result-metric-value">₹${b.resistance_level?.toLocaleString('en-IN')}</span>
                    </div>
                    <div class="result-metric">
                        <span class="result-metric-label">${isNear ? '% Below' : '% Above'}</span>
                        <span class="result-metric-value ${isNear ? 'return-neutral' : 'return-positive'}">
                            ${b.pct_above > 0 ? '+' : ''}${b.pct_above?.toFixed(2)}%
                        </span>
                    </div>
                    <div class="result-metric">
                        <span class="result-metric-label">Volume</span>
                        <span class="result-metric-value">${b.volume_ratio?.toFixed(1)}× avg</span>
                    </div>
                </div>

                <!-- Trade Execution Plan -->
                <div style="margin-top:0.8rem; padding-top:0.8rem; border-top:1px dashed var(--border-medium);">
                    <div style="font-size:0.75rem; font-weight:700; color:var(--accent-blue); text-transform:uppercase; letter-spacing:0.04em; margin-bottom:0.5rem; display:flex; justify-content:space-between; align-items:center;">
                        <span>🎯 Trade Plan (GTT Order)</span>
                        <span style="font-size:0.65rem; color:var(--text-muted); font-weight:500">Risk: ₹${tp.risk_budget_inr?.toLocaleString('en-IN')}</span>
                    </div>

                    <div style="display:grid; grid-template-columns: repeat(2, 1fr); gap:0.5rem; font-size:0.8rem;">
                        <div style="background:var(--bg-glass); padding:0.4rem 0.6rem; border-radius:var(--radius-sm); border:1px solid rgba(59,130,246,0.2);">
                            <div style="font-size:0.65rem; color:var(--text-muted)">ENTRY TRIGGER</div>
                            <div style="font-weight:700; color:var(--accent-blue)">₹${tp.entry_trigger?.toLocaleString('en-IN')}</div>
                        </div>

                        <div style="background:var(--bg-glass); padding:0.4rem 0.6rem; border-radius:var(--radius-sm); border:1px solid rgba(244,63,94,0.2);">
                            <div style="font-size:0.65rem; color:var(--text-muted)">STOP LOSS</div>
                            <div style="font-weight:700; color:var(--accent-red)">₹${tp.stop_loss?.toLocaleString('en-IN')} <span style="font-size:0.65rem; font-weight:400">(-${tp.risk_pct}%)</span></div>
                        </div>

                        <div style="background:var(--bg-glass); padding:0.4rem 0.6rem; border-radius:var(--radius-sm); border:1px solid rgba(16,185,129,0.2);">
                            <div style="font-size:0.65rem; color:var(--text-muted)">TARGET 1 (1:${data.config?.risk_reward_ratio || 2})</div>
                            <div style="font-weight:700; color:var(--accent-green)">₹${tp.target_1?.toLocaleString('en-IN')} <span style="font-size:0.65rem; font-weight:400">(+${tp.target_1_pct}%)</span></div>
                        </div>

                        <div style="background:var(--bg-glass); padding:0.4rem 0.6rem; border-radius:var(--radius-sm);">
                            <div style="font-size:0.65rem; color:var(--text-muted)">BUY SHARES</div>
                            <div style="font-weight:700; color:var(--text-primary)">${tp.suggested_shares} <span style="font-size:0.65rem; color:var(--text-muted); font-weight:400">(₹${tp.position_capital?.toLocaleString('en-IN')})</span></div>
                        </div>
                    </div>

                    <div style="display:flex; gap:0.5rem; margin-top:0.6rem;">
                        <button class="btn btn-secondary" style="flex:1; padding:0.4rem; font-size:0.75rem; justify-content:center;" onclick="openDiagModal(${i})">
                            🔍 Why Selected?
                        </button>
                        <button class="btn btn-secondary" style="flex:1; padding:0.4rem; font-size:0.75rem; justify-content:center;" onclick="copyGTTOrder('${b.symbol}', ${tp.entry_trigger}, ${tp.stop_loss}, ${tp.target_1}, ${tp.suggested_shares}, this)">
                            📋 Copy GTT
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    grid.innerHTML = html;
}

function copyGTTOrder(symbol, trigger, sl, target, qty, btnEl) {
    const text = `GTT ORDER FOR ${symbol}.NS\nAction: BUY\nTrigger Price: ₹${trigger}\nOrder Price: ₹${trigger}\nQty: ${qty} shares\nStop Loss: ₹${sl}\nTarget: ₹${target}`;
    navigator.clipboard.writeText(text).then(() => {
        const origText = btnEl.innerText;
        btnEl.innerText = '✓ Copied!';
        btnEl.style.borderColor = 'var(--accent-green)';
        setTimeout(() => {
            btnEl.innerText = origText;
            btnEl.style.borderColor = '';
        }, 2000);
    });
}

// ─── Selection Diagnosis Modal Logic ────────────────────────────────────────
function openDiagModal(idx) {
    if (!scanResults || !scanResults.breakouts || !scanResults.breakouts[idx]) return;
    const b = scanResults.breakouts[idx];
    const sf = b.selection_factors || {};
    const sb = sf.score_breakdown || {};

    document.getElementById('modal-symbol').innerText = b.symbol;
    document.getElementById('modal-company').innerText = b.company || 'Nifty 500 Stock';
    document.getElementById('modal-gfinance-link').href = `https://www.google.com/finance/quote/${b.symbol}:NSE`;
    document.getElementById('modal-score-circle').innerText = b.strength_score;
    document.getElementById('modal-score-label').innerText = `${b.strength_score >= 70 ? '🔥 High Confidence' : '⚡ Promising'} ${b.scan_type === 'NEAR_BREAKOUT' ? 'Pre-Breakout Setup' : 'Breakout Signal'}`;
    document.getElementById('modal-type-summary').innerText = sf.resistance?.summary || `${b.pct_above}% vs resistance`;

    // Render Factor Grid
    const factorsGrid = document.getElementById('modal-factors-grid');
    factorsGrid.innerHTML = `
        <div class="factor-item">
            <div class="factor-icon">🤖</div>
            <div class="factor-details">
                <div class="factor-title-row">
                    <span class="factor-title">AI Breakout Probability & ML Verdict</span>
                    <span class="factor-badge pass">${b.ai_probability ? `${b.ai_probability}% Win Prob` : 'AI SCORING'}</span>
                </div>
                <div class="factor-desc">${sf.ai_prediction?.summary || 'Scikit-Learn Random Forest evaluated pattern features.'}</div>
            </div>
        </div>

        <div class="factor-item">
            <div class="factor-icon">📈</div>
            <div class="factor-details">
                <div class="factor-title-row">
                    <span class="factor-title">Mansfield Relative Strength vs Nifty 50</span>
                    <span class="factor-badge ${b.mansfield_rs > 0 ? 'pass' : 'warning'}">${b.mansfield_rs > 0 ? `LEADER (+${b.mansfield_rs}%)` : `LAGGARD (${b.mansfield_rs}%)`}</span>
                </div>
                <div class="factor-desc">${sf.relative_strength?.summary || 'Calculated vs ^NSEI benchmark.'}</div>
            </div>
        </div>

        <div class="factor-item">
            <div class="factor-icon">🎯</div>
            <div class="factor-details">
                <div class="factor-title-row">
                    <span class="factor-title">VCP (Volatility Contraction Pattern)</span>
                    <span class="factor-badge ${b.is_vcp ? 'pass' : 'neutral'}">${b.is_vcp ? `VCP BASE (${b.vcp_compression_pct}% ATR SQUEEZE)` : 'NORMAL BASE'}</span>
                </div>
                <div class="factor-desc">${sf.vcp_pattern?.summary || 'ATR compression analysis.'}</div>
            </div>
        </div>

        <div class="factor-item">
            <div class="factor-icon">🎯</div>
            <div class="factor-details">
                <div class="factor-title-row">
                    <span class="factor-title">Resistance Proximity (${sf.resistance?.mode || 'Resistance'})</span>
                    <span class="factor-badge pass">PASS</span>
                </div>
                <div class="factor-desc">${sf.resistance?.summary || ''}</div>
            </div>
        </div>

        <div class="factor-item">
            <div class="factor-icon">📊</div>
            <div class="factor-details">
                <div class="factor-title-row">
                    <span class="factor-title">Volume Confirmation & Turnover</span>
                    <span class="factor-badge pass">PASS (${b.volume_ratio}× Avg)</span>
                </div>
                <div class="factor-desc">${sf.volume?.summary || ''} ${sf.volume?.avg_turnover_cr ? `· Daily Turnover: ₹${sf.volume.avg_turnover_cr} Cr` : ''}</div>
            </div>
        </div>

        <div class="factor-item">
            <div class="factor-icon">🛡️</div>
            <div class="factor-details">
                <div class="factor-title-row">
                    <span class="factor-title">200 DMA Long-Term Trend</span>
                    <span class="factor-badge ${b.above_200dma ? 'pass' : 'warning'}">${b.above_200dma ? 'PASS (Uptrend)' : 'WARNING (Below 200 DMA)'}</span>
                </div>
                <div class="factor-desc">${sf.trend?.summary || ''}</div>
            </div>
        </div>
    `;

    // Render Score Breakdown
    const scoreBreakdown = document.getElementById('modal-score-breakdown');
    scoreBreakdown.innerHTML = `
        ${scoreBreakdownRow('Volume Surge (30%)', sb.volume_points || 0, sb.volume_max || 30)}
        ${scoreBreakdownRow('Price Proximity (25%)', sb.gap_points || 0, sb.gap_max || 25)}
        ${scoreBreakdownRow('200 DMA Trend (20%)', sb.trend_points || 0, sb.trend_max || 20)}
        ${scoreBreakdownRow('BB Squeeze (15%)', sb.consol_points || 0, sb.consol_max || 15)}
        ${scoreBreakdownRow('RSI Momentum (10%)', sb.rsi_points || 0, sb.rsi_max || 10)}
    `;

    document.getElementById('diag-modal-overlay').classList.add('active');
}

function scoreBreakdownRow(label, pts, max) {
    const pct = Math.min(100, Math.round((pts / max) * 100));
    return `
        <div class="score-breakdown-item">
            <span class="score-breakdown-label">${label}</span>
            <div class="score-breakdown-track">
                <div class="score-breakdown-fill" style="width:${pct}%"></div>
            </div>
            <span class="score-breakdown-pts">${pts} / ${max}</span>
        </div>
    `;
}

function closeDiagModal(event) {
    if (event.target.id === 'diag-modal-overlay') {
        document.getElementById('diag-modal-overlay').classList.remove('active');
    }
}

function closeDiagModalDirect() {
    document.getElementById('diag-modal-overlay').classList.remove('active');
}

// ─── Helpers ───────────────────────────────────────────────────────────────
function scoreBadge(score) {
    let cls = 'very-low';
    if (score >= 80) cls = 'high';
    else if (score >= 60) cls = 'medium';
    else if (score >= 40) cls = 'low';

    return `<span class="score-badge ${cls}">${score}</span>`;
}

function formatReturn(val) {
    if (val === null || val === undefined) return '—';
    const sign = val > 0 ? '+' : '';
    return `${sign}${val.toFixed(2)}%`;
}

function returnClass(val) {
    if (val === null || val === undefined) return 'return-neutral';
    return val > 0 ? 'return-positive' : 'return-negative';
}

function formatDate(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear().toString().slice(2)}`;
}

// ─── Interactive Help Modal Logic ──────────────────────────────────────────
function openHelpModal() {
    document.getElementById('help-modal-overlay').classList.add('active');
}

function closeHelpModal(event) {
    if (event.target.id === 'help-modal-overlay') {
        document.getElementById('help-modal-overlay').classList.remove('active');
    }
}

function closeHelpModalDirect() {
    document.getElementById('help-modal-overlay').classList.remove('active');
}

function switchHelpTab(tabId, btnEl) {
    document.querySelectorAll('.help-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.help-section').forEach(s => s.classList.remove('active'));

    btnEl.classList.add('active');
    document.getElementById(`help-sec-${tabId}`).classList.add('active');
}
