# 📈 Breakout Screener & Pre-Breakout Detector (India Stocks)

A technical breakout screener and pre-breakout radar for Nifty 500 stocks (NSE India).

---

## 🔥 Key Features

- **⚡ Pre-Breakout Radar**: Detects stocks consolidating **0.5% – 3% below resistance** before they break out.
- **🎯 Trade Execution Planner**: Calculates exact **Entry Trigger**, **Stop Loss**, **Target 1 (1:2 R:R)**, and **Share Quantity** based on your risk budget.
- **📋 One-Click GTT Copy**: Copies GTT order details formatted for Zerodha, Dhan, Groww, or AngelOne.
- **🔍 Selection Factors Diagnosis**: Interactive modal explaining why each stock was selected (Volume Surge, 200 DMA trend, Bollinger Band squeeze, RSI).
- **🧪 Backtest Engine**: Validates your breakout rules against 1 year of historical data with forward return tracking (5, 10, 20, 30 days).
- **🌐 Direct Google Finance Links**: Every ticker links to `https://www.google.com/finance/quote/SYMBOL:NSE`.

---

## 🚀 Local Usage

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the Server
```bash
python -m uvicorn backend.main:app --reload --port 8000
```

### 3. Open in Browser
Navigate to **`http://localhost:8000`**.

---

## 🤗 Deploying to Hugging Face Spaces (100% Free)

1. Go to **[huggingface.co/spaces](https://huggingface.co/spaces)** and click **Create new Space**.
2. Set **Space SDK** to **Gradio** (100% Free, no credit card required).
3. Push this repository to your Hugging Face Space:
   ```bash
   git remote add hf https://huggingface.co/spaces/YOUR_USERNAME/YOUR_SPACE_NAME
   git push hf main
   ```
4. Hugging Face automatically runs `app.py` and hosts your Breakout Screener live for free!
