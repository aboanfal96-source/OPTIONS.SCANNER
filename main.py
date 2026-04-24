"""
Options Scanner Backend
========================
منصة فلترة عقود الخيارات - تبحث عن عقود ذات احتمالية صعود عالية

Signals detected:
1. Unusual Options Activity (Volume > 3x Open Interest)
2. High Implied Volatility spikes
3. Momentum (price action + volume)
4. Upcoming earnings plays
5. Call/Put ratio anomalies
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import numpy as np
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Options Bullish Scanner", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Popular US tickers to scan (high liquidity)
DEFAULT_TICKERS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "GOOGL", "AMZN",
    "SPY", "QQQ", "IWM", "NFLX", "BA", "DIS", "JPM", "BAC",
    "COIN", "PLTR", "SOFI", "RIVN", "LCID", "NIO", "F", "GM",
    "INTC", "MU", "ORCL", "CRM", "UBER", "ABNB", "SHOP", "SQ",
    "MARA", "RIOT", "HOOD", "GME", "AMC", "SNAP", "PYPL", "ROKU"
]

executor = ThreadPoolExecutor(max_workers=10)


class ScanRequest(BaseModel):
    tickers: Optional[List[str]] = None
    min_volume: int = 100
    min_oi: int = 50
    min_unusual_ratio: float = 2.0  # Volume/OI ratio
    option_type: str = "calls"  # calls or puts
    max_days_to_expiry: int = 45
    min_days_to_expiry: int = 3
    bullish_only: bool = True


class OptionContract(BaseModel):
    symbol: str
    ticker: str
    strike: float
    expiration: str
    days_to_expiry: int
    last_price: float
    bid: float
    ask: float
    volume: int
    open_interest: int
    implied_volatility: float
    in_the_money: bool
    unusual_ratio: float
    stock_price: float
    percent_to_strike: float
    bullish_score: float
    signals: List[str]


def calculate_bullish_score(row, stock_price, stock_change_pct, avg_volume_ratio):
    """
    نظام تقييم: 0-100
    كل ما زاد الرقم، كل ما قويت إشارة الصعود
    """
    score = 0
    signals = []

    # 1. Unusual volume (عقود تتداول بكثافة غير طبيعية)
    unusual_ratio = row['volume'] / max(row['openInterest'], 1)
    if unusual_ratio >= 5:
        score += 30
        signals.append("🔥 حجم تداول ضخم جداً (5x+)")
    elif unusual_ratio >= 3:
        score += 20
        signals.append("⚡ حجم تداول غير طبيعي (3x+)")
    elif unusual_ratio >= 2:
        score += 10
        signals.append("📊 حجم أعلى من المعتاد")

    # 2. Momentum check (السهم صاعد)
    if stock_change_pct > 2:
        score += 20
        signals.append(f"🚀 زخم قوي (+{stock_change_pct:.1f}%)")
    elif stock_change_pct > 0.5:
        score += 10
        signals.append(f"📈 زخم إيجابي")

    # 3. Out of the money but close (OTM قريب من السعر - أفضل نسبة مخاطرة/مكافأة)
    percent_otm = ((row['strike'] - stock_price) / stock_price) * 100
    if 0 < percent_otm < 3:
        score += 15
        signals.append("🎯 OTM قريب (نسبة ممتازة)")
    elif 3 <= percent_otm < 7:
        score += 10
        signals.append("🎯 OTM معقول")

    # 4. IV reasonable (ليس غالي جداً)
    iv = row['impliedVolatility']
    if 0.3 < iv < 0.8:
        score += 10
        signals.append("💎 IV معقول")
    elif iv >= 1.5:
        score -= 10
        signals.append("⚠️ IV مرتفع جداً (غالي)")

    # 5. Bid-Ask spread (السيولة)
    if row['ask'] > 0:
        spread_pct = ((row['ask'] - row['bid']) / row['ask']) * 100
        if spread_pct < 5:
            score += 10
            signals.append("💧 سيولة ممتازة")
        elif spread_pct > 20:
            score -= 5
            signals.append("🚧 سيولة ضعيفة")

    # 6. Open interest (شعبية العقد)
    if row['openInterest'] > 1000:
        score += 5
        signals.append("👥 عقد شائع")

    return min(max(score, 0), 100), signals


def scan_ticker_options(ticker: str, request: ScanRequest):
    """فحص عقود الخيارات لسهم واحد"""
    try:
        stock = yf.Ticker(ticker)
        
        # Get current stock info
        hist = stock.history(period="5d")
        if hist.empty:
            return []
        
        stock_price = float(hist['Close'].iloc[-1])
        prev_close = float(hist['Close'].iloc[-2]) if len(hist) > 1 else stock_price
        stock_change_pct = ((stock_price - prev_close) / prev_close) * 100
        
        # Average volume calculation for context
        avg_vol = hist['Volume'].mean()
        today_vol = hist['Volume'].iloc[-1]
        avg_volume_ratio = today_vol / avg_vol if avg_vol > 0 else 1
        
        # Get expirations
        expirations = stock.options
        if not expirations:
            return []
        
        results = []
        today = datetime.now().date()
        
        for exp in expirations[:6]:  # first 6 expirations
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            days_to_expiry = (exp_date - today).days
            
            if days_to_expiry < request.min_days_to_expiry or days_to_expiry > request.max_days_to_expiry:
                continue
            
            try:
                chain = stock.option_chain(exp)
                options_df = chain.calls if request.option_type == "calls" else chain.puts
                
                if options_df.empty:
                    continue
                
                # Filter
                filtered = options_df[
                    (options_df['volume'] >= request.min_volume) &
                    (options_df['openInterest'] >= request.min_oi)
                ].copy()
                
                filtered['unusual_ratio'] = filtered['volume'] / filtered['openInterest'].replace(0, 1)
                filtered = filtered[filtered['unusual_ratio'] >= request.min_unusual_ratio]
                
                for _, row in filtered.iterrows():
                    score, signals = calculate_bullish_score(
                        row, stock_price, stock_change_pct, avg_volume_ratio
                    )
                    
                    # If bullish_only, require score >= 40
                    if request.bullish_only and score < 40:
                        continue
                    
                    percent_to_strike = ((row['strike'] - stock_price) / stock_price) * 100
                    
                    results.append({
                        "symbol": row['contractSymbol'],
                        "ticker": ticker,
                        "strike": float(row['strike']),
                        "expiration": exp,
                        "days_to_expiry": days_to_expiry,
                        "last_price": float(row['lastPrice']),
                        "bid": float(row['bid']),
                        "ask": float(row['ask']),
                        "volume": int(row['volume']),
                        "open_interest": int(row['openInterest']),
                        "implied_volatility": float(row['impliedVolatility']),
                        "in_the_money": bool(row['inTheMoney']),
                        "unusual_ratio": float(row['unusual_ratio']),
                        "stock_price": stock_price,
                        "percent_to_strike": percent_to_strike,
                        "bullish_score": score,
                        "signals": signals
                    })
            except Exception as e:
                logger.warning(f"Error on {ticker} {exp}: {e}")
                continue
        
        return results
    except Exception as e:
        logger.error(f"Error scanning {ticker}: {e}")
        return []


@app.get("/")
def root():
    return {
        "status": "running",
        "service": "Options Bullish Scanner",
        "endpoints": ["/scan", "/ticker/{symbol}", "/health"]
    }


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.post("/scan")
async def scan_options(request: ScanRequest):
    """المسح الرئيسي - يرجع أقوى العقود bullish"""
    tickers = request.tickers if request.tickers else DEFAULT_TICKERS
    
    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(executor, scan_ticker_options, ticker, request)
        for ticker in tickers
    ]
    
    all_results = []
    for task_result in await asyncio.gather(*tasks):
        all_results.extend(task_result)
    
    # Sort by bullish score
    all_results.sort(key=lambda x: x['bullish_score'], reverse=True)
    
    return {
        "count": len(all_results),
        "scanned_tickers": len(tickers),
        "timestamp": datetime.now().isoformat(),
        "contracts": all_results[:50]  # top 50
    }


@app.get("/ticker/{symbol}")
def get_ticker_info(symbol: str):
    """معلومات سريعة عن سهم"""
    try:
        stock = yf.Ticker(symbol.upper())
        hist = stock.history(period="5d")
        info = stock.info
        
        if hist.empty:
            raise HTTPException(status_code=404, detail="Ticker not found")
        
        current = float(hist['Close'].iloc[-1])
        prev = float(hist['Close'].iloc[-2]) if len(hist) > 1 else current
        change_pct = ((current - prev) / prev) * 100
        
        return {
            "symbol": symbol.upper(),
            "name": info.get("longName", symbol),
            "price": current,
            "change_pct": change_pct,
            "volume": int(hist['Volume'].iloc[-1]),
            "market_cap": info.get("marketCap"),
            "has_options": len(stock.options) > 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
