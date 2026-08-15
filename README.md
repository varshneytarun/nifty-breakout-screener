# 📈 Breakout Screener & Pre-Breakout Detector (NSE Nifty 500)

A full-stack, data-driven technical analysis application for Indian stocks (NSE India Nifty 500). 
It features a **historical backtesting engine** to validate breakout strategies against 1 year of market data, and a **live market scanner & trade execution planner** to catch breakouts before or as they happen.

---

## 🧭 App Overview & The 2 Core Tabs

### 🧪 Tab 1: Backtest Tab (Historical Validation Engine)
Before risking capital on a breakout rule, the **Backtest Tab** proves whether the strategy actually worked over the past 12 months.

- **Historical Simulation**: Evaluates your exact filter settings against 252+ trading days of daily OHLCV data for all 500 stocks.
- **Forward Return Tracking**: Measures price performance at **5-day, 10-day, 20-day, and 30-day** horizons after every signal.
- **Performance Analytics**:
  - **Win Rates & Avg Gains**: Displays win rate % and average returns across different holding periods.
  - **Score Bucket Analysis**: Groups signals by their 1–100 Strength Score to show if higher-scored signals produce higher win rates.
  - **Monthly Signal Distribution**: Visualizes market breakout frequency month-by-month.
- **Sortable Signal Table**: Inspect all individual historical signals with 1-click links to Google Finance.

---

### ⚡ Tab 2: Live Scan Tab (Real-Time Trade Detector & Execution Planner)
The **Live Scan Tab** scans today's latest daily candles to discover current trading opportunities and builds actionable trade plans.

- **Actionable Trade Execution Cards**: For every flagged stock, it automatically computes:
  - 🎯 **Entry Trigger Price**: Resistance + 0.1% buffer (exact price to buy at).
  - 🛡️ **Suggested Stop Loss**: Based on 20-day swing lows or max risk %.
  - 🚀 **Targets 1 & 2**: Calculated at 1:2 and 1:3 Risk-to-Reward (R:R) ratios.
  - 🛒 **Position Sizing**: Calculates exact share quantity based on your custom **Max Risk Per Trade (₹)** budget.
- **📋 One-Click GTT Order Copy**: Copy pre-formatted order details for Zerodha Kite, Dhan, Groww, or AngelOne GTT orders.
- **🔍 "Why Selected?" Diagnostic Modal**: Clicking this button on any card opens a deep-dive popup explaining the exact 5 technical factors (Volume ratio, 200 DMA trend, Bollinger Band squeeze, RSI momentum, and Score points breakdown) that triggered the selection.
- **🌐 Direct Google Finance Links**: 1-click links (`SYMBOL ↗`) opening `https://www.google.com/finance/quote/SYMBOL:NSE`.

---

## ⚡ Confirmed Breakout vs. Near Breakout Radar

You can toggle between two scan targets in the configuration panel:

| Feature | Confirmed Breakout (`BROKEN_OUT`) | Near Breakout Radar (`NEAR_BREAKOUT`) |
|---|---|---|
| **Price Condition** | `Close > Resistance` | `Close <= Resistance` (Within 0.5% – 3% below) |
| **Timing** | Flagged **after** the stock has already broken out today. | Flagged **before** the breakout occurs while consolidating. |
| **Best For** | End-of-day momentum traders who require price confirmation. | Pre-market planning & setting **GTT Buy Trigger Orders**. |
| **Trader Action** | Market buy or wait for pullbacks. | Set GTT Buy Order at `Resistance + 0.1%` trigger price so your broker automatically buys when price crosses threshold during market hours. |

---

## 🛠️ Technical Filters & Scoring System

The screener evaluates breakouts using a 1–100 weighted **Strength Score**:

1. **Resistance Level (52-Week High / N-Day High / Swing High)**: Key structural ceiling.
2. **Volume Confirmation (30% weight)**: Compares today's volume against the 20-day average.
3. **Price Gap / Proximity (25% weight)**: Distance from resistance level.
4. **200 DMA Trend Alignment (20% weight)**: Ensures stock is in a long-term bull trend (`Close > 200 SMA`).
5. **Consolidation Squeeze (15% weight)**: Measures Bollinger Band width to catch volatility squeezes prior to explosive moves.
6. **RSI Momentum (10% weight)**: Confirms bullish 14-period RSI momentum.

---

## 🚀 Local Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the Server
```bash
python -m uvicorn backend.main:app --reload --port 8000
```

### 3. Open Application
Navigate to **`http://localhost:8000`** in your browser.

---

## 🌐 Cloud Deployment (Render.com)

- Environment: `Python 3`
- Build Command: `pip install -r requirements.txt`
- Start Command: `python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- *Note:* The app includes an automatic background keep-alive loop to prevent Render's free tier from sleeping after 15 minutes of inactivity.
