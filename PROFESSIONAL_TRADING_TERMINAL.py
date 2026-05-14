# -*- coding: utf-8 -*-
# ============================================================
# PROFESSIONAL_TRADING_TERMINAL.py - РџРћР›РќРђРЇ Р’Р•Р РЎРРЇ 21.0
# рџ”ђ DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO
# ============================================================

import time
import requests
import hmac
import hashlib
import threading
import sys
import os
import json
import csv
import random
import sqlite3
from datetime import datetime, timedelta
from collections import deque
from flask import Flask, jsonify, render_template_string, request, send_file
from flask_cors import CORS
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# РљРћРќР¤РР“РЈР РђР¦РРЇ
# ============================================================

MEXC_API_KEY = "ВАШ_API_KEY_ЗДЕСЬ"
MEXC_API_SECRET = "ВАШ_API_SECRET_ЗДЕСЬ"
TELEGRAM_TOKEN = "ВАШ_TELEGRAM_TOKEN"
TELEGRAM_CHAT_ID = "ВАШ_CHAT_ID"
WEBHOOK_SECRET = "super_secret_key_2024"

# РўРѕСЂРіРѕРІС‹Рµ РїР°СЂР°РјРµС‚СЂС‹
MAX_POSITIONS = 5
BUDGET_SHARE = 0.20
MIN_TRADE_USD = 3
RSI_BUY = 35
RSI_SELL = 65
STOP_LOSS = 3.5
TAKE_PROFIT = 7.0
TRAILING_ACTIVATE = 3.0
TRAILING_DISTANCE = 2.0
BREAK_EVEN_ACTIVATE = 2.0
SCAN_INTERVAL = 10

# DCA РїР°СЂР°РјРµС‚СЂС‹
DCA_ENABLED = True
DCA_PRICE_DROP = 2.0
DCA_MULTIPLIER = 1.5
MAX_DCA_ORDERS = 3

# Р—Р°С‰РёС‚Р° РєР°РїРёС‚Р°Р»Р°
DAILY_LOSS_LIMIT = 10.0
MAX_PORTFOLIO_DD = 15.0
MAX_CONSECUTIVE_LOSSES = 5

# Р РµР¶РёРј СЂР°Р±РѕС‚С‹
TRADING_MODE = "REAL"

# РђСЂР±РёС‚СЂР°Р¶
ARBITRAGE_ENABLED = True
ARBITRAGE_MIN_PROFIT = 0.5

# TWAP
TWAP_ENABLED = True
TWAP_INTERVAL = 60
TWAP_PARTS = 10

# Market Making
MARKET_MAKING_ENABLED = False
MARKET_MAKING_SPREAD = 0.1
MARKET_MAKING_ORDER_SIZE = 10

# ============================================================
# РЎРџРРЎРћРљ РњРћРќР•Рў (50+)
# ============================================================

COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "UNIUSDT", "ATOMUSDT", "LTCUSDT",
    "ETCUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "FILUSDT", "SUIUSDT",
    "SEIUSDT", "TRXUSDT", "XLMUSDT", "VETUSDT", "HBARUSDT", "ICPUSDT", "EGLDUSDT"
]

# ============================================================
# Р“Р›РћР‘РђР›Р¬РќР«Р• РџР•Р Р•РњР•РќРќР«Р•
# ============================================================

balance = 0.0
positions = []
signals = {}
history = []
logs = []
auto_pilot = True
running = True
total_profit = 0.0
start_balance = 0.0
daily_loss = 0.0
portfolio_peak = 0.0
fear_greed_index = 50
consecutive_losses = 0
telegram_offset = 0
price_alerts = []
paper_balance = 10000.0
paper_positions = []
paper_history = []
arbitrage_opportunities = []
pending_twap_orders = []
ml_trained = False
active_exchanges = ["mexc"]
exchange_prices = {}

# ============================================================
# РРќРР¦РРђР›РР—РђР¦РРЇ Р‘Р”
# ============================================================

def init_database():
    conn = sqlite3.connect('trading_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  time TEXT, symbol TEXT, side TEXT, price REAL,
                  amount REAL, profit REAL, profit_pct REAL, exchange TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_stats
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  date TEXT, balance REAL, profit REAL, trades_count INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS backtest_results
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  time TEXT, symbol TEXT, strategy TEXT,
                  investment REAL, profit REAL, winrate REAL, trades INTEGER)''')
    conn.commit()
    conn.close()

init_database()

# ============================================================
# Р‘РђР—РћР’Р«Р• API Р¤РЈРќРљР¦РР
# ============================================================

def sign_mexc(p):
    return hmac.new(MEXC_API_SECRET.encode(), p.encode(), hashlib.sha256).hexdigest()

def get_balance_mexc():
    try:
        t = int(time.time()*1000)
        sig = sign_mexc(f"timestamp={t}")
        r = requests.get(f"https://api.mexc.com/api/v3/account?timestamp={t}&signature={sig}",
                         headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        if r.status_code == 200:
            for b in r.json().get("balances", []):
                if b.get("asset") == "USDT":
                    return float(b.get("free", 0))
    except:
        pass
    return 0

def get_price_mexc(s):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={s}", timeout=3)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except:
        pass
    return 0

def get_price(symbol):
    return get_price_mexc(symbol)

def get_klines(symbol, limit=100, interval="5m"):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return {
                "times": [c[0] for c in data],
                "opens": [float(c[1]) for c in data],
                "highs": [float(c[2]) for c in data],
                "lows": [float(c[3]) for c in data],
                "closes": [float(c[4]) for c in data],
                "volumes": [float(c[5]) for c in data]
            }
    except:
        pass
    return None

def get_order_book(symbol, limit=10):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/depth?symbol={symbol}&limit={limit}", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return {
                "bids": [[float(b[0]), float(b[1])] for b in data.get("bids", [])[:limit]],
                "asks": [[float(a[0]), float(a[1])] for a in data.get("asks", [])[:limit]]
            }
    except:
        pass
    return {"bids": [], "asks": []}

def get_24hr_stats(symbol):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/24hr?symbol={symbol}", timeout=5)
        if r.status_code == 200:
            d = r.json()
            return {
                "change": float(d.get("priceChangePercent", 0)),
                "high": float(d.get("highPrice", 0)),
                "low": float(d.get("lowPrice", 0)),
                "volume": float(d.get("quoteVolume", 0))
            }
    except:
        pass
    return {"change": 0, "high": 0, "low": 0, "volume": 0}

# ============================================================
# WEBSOCKET (РРњРРўРђР¦РРЇ)
# ============================================================

class WebSocketManager:
    def __init__(self):
        self.prices = {}
        self.running = False
    
    def start(self):
        self.running = True
        threading.Thread(target=self._update_prices, daemon=True).start()
    
    def _update_prices(self):
        while self.running:
            try:
                for coin in COINS[:30]:
                    price = get_price_mexc(coin)
                    if price > 0:
                        self.prices[coin] = {"price": price, "time": time.time()}
                time.sleep(2)
            except:
                time.sleep(2)
    
    def get_price(self, symbol):
        if symbol in self.prices:
            if time.time() - self.prices[symbol]["time"] < 10:
                return self.prices[symbol]["price"]
        return None

ws_manager = WebSocketManager()

# ============================================================
# Р’РЎРџРћРњРћР“РђРўР•Р›Р¬РќР«Р• Р¤РЈРќРљР¦РР
# ============================================================

def add_log(msg):
    logs.insert(0, {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg})
    if len(logs) > 100:
        logs.pop()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg[:3000], "parse_mode": "HTML"}
        requests.post(url, json=data, timeout=5)
    except:
        pass

def export_to_csv():
    filename = f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Time", "Symbol", "Side", "Price", "Profit $", "Profit %", "DCA Count", "Paper"])
        for h in history:
            writer.writerow([h["time"], h["symbol"], h["side"], h["price"],
                             h["profit_usd"], h["profit_pct"], h.get("dca_count", 0),
                             "Yes" if h.get("paper", False) else "No"])
    return filename

# ============================================================
# РРќР”РРљРђРўРћР Р«
# ============================================================

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, period + 1):
        d = prices[-i] - prices[-i-1]
        if d > 0:
            gains.append(d)
        else:
            losses.append(abs(d))
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0.001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow + signal:
        return 0, 0, 0
    def ema(data, period):
        k = 2 / (period + 1)
        ema_val = data[0]
        for val in data[1:]:
            ema_val = val * k + ema_val * (1 - k)
        return ema_val
    fast_ema = ema(prices[-fast:], fast)
    slow_ema = ema(prices[-slow:], slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema([macd_line] * signal, signal) if len([macd_line] * signal) > 0 else macd_line
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calc_bollinger(prices, period=20, std_dev=2):
    if len(prices) < period:
        return 0, 0, 0
    sma = sum(prices[-period:]) / period
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std = variance ** 0.5
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return upper, sma, lower

def calc_atr(prices, period=14):
    if len(prices) < period + 1:
        return 0.01
    tr_values = []
    for i in range(1, period + 1):
        hl = abs(prices[-i] - prices[-i-1])
        tr_values.append(hl)
    return sum(tr_values) / period

def calc_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    k = 2 / (period + 1)
    ema_val = prices[0]
    for val in prices[1:]:
        ema_val = val * k + ema_val * (1 - k)
    return ema_val

def calc_sma(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period

def calc_stochastic(prices, period=14):
    if len(prices) < period:
        return 50
    low = min(prices[-period:])
    high = max(prices[-period:])
    if high == low:
        return 50
    return (prices[-1] - low) / (high - low) * 100

def get_fear_greed_index():
    global fear_greed_index
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data and data.get("data"):
                fear_greed_index = int(data["data"][0]["value"])
                return fear_greed_index
    except:
        pass
    return fear_greed_index

def get_btc_dominance():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=5)
        if r.status_code == 200:
            return r.json().get("data", {}).get("market_cap_percentage", {}).get("btc", 50)
    except:
        pass
    return 50



# ============================================================
# РђРќРђР›РР— РЎРР“РќРђР›РћР’
# ============================================================

def analyze_signal(symbol):
    klines = get_klines(symbol, 100, "5m")
    if not klines:
        return "HOLD", 0, 50, 0, []
    
    closes = klines["closes"]
    rsi = calc_rsi(closes)
    macd, macd_signal, macd_hist = calc_macd(closes)
    bb_upper, bb_mid, bb_lower = calc_bollinger(closes)
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    sma50 = calc_sma(closes, 50)
    stoch = calc_stochastic(closes)
    fg = get_fear_greed_index()
    
    score = 50
    reasons = []
    
    if rsi < 35:
        score += 25
        reasons.append(f"RSI={rsi:.0f}")
    elif rsi > 70:
        score -= 20
    
    if macd > macd_signal:
        score += 15
        reasons.append("MACD+")
    else:
        score -= 10
    
    if closes[-1] <= bb_lower:
        score += 20
        reasons.append("BBв†“")
    elif closes[-1] >= bb_upper:
        score -= 15
    
    if ema9 > ema21:
        score += 10
        reasons.append("EMAв†‘")
    
    if closes[-1] > sma50:
        score += 5
    
    if stoch < 20:
        score += 10
    elif stoch > 80:
        score -= 10
    
    if fg < 30:
        score += 10
        reasons.append("Fear")
    elif fg > 70:
        score -= 15
        reasons.append("Greed")
    
    score = max(0, min(100, score))
    
    if score > 55:
        signal = "BUY"
    elif score < 45:
        signal = "SELL"
    else:
        signal = "HOLD"
    
    return signal, score, rsi, score, {"reasons": reasons}

# ============================================================
# РўРћР Р“РћР’Р›РЇ
# ============================================================

def market_buy(symbol, amount, exchange="mexc"):
    global balance, paper_balance, paper_positions, TRADING_MODE
    
    if TRADING_MODE == "PAPER":
        price = get_price(symbol)
        if price <= 0 or amount > paper_balance:
            return False, 0
        qty = amount / price
        paper_positions.append({
            "symbol": symbol, "entry_price": price, "invested": amount,
            "quantity": qty, "entry_time": time.time(),
            "peak_price": price, "peak_profit": 0, "dca_count": 0
        })
        paper_balance -= amount
        add_log(f"рџ“‹ PAPER РџРћРљРЈРџРљРђ {symbol}: ${amount:.2f} @ ${price:.4f}")
        return True, amount
    
    try:
        price = get_price(symbol)
        if price <= 0:
            return False, 0
        if price < 1:
            qty = int(amount / price)
            if qty < 1:
                return False, 0
            actual = qty * price
        else:
            qty = round(amount / price, 6)
            actual = amount
        t = int(time.time()*1000)
        params = f"symbol={symbol}&side=BUY&type=MARKET&quantity={qty}&timestamp={t}"
        sig = sign_mexc(params)
        r = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sig}",
                          headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        if r.status_code == 200:
            return True, actual
        return False, 0
    except:
        return False, 0

def market_sell(symbol, quantity, exchange="mexc"):
    global balance, total_profit, TRADING_MODE, paper_balance, paper_positions
    
    if TRADING_MODE == "PAPER":
        for p in paper_positions[:]:
            if p["symbol"] == symbol:
                price = get_price(symbol)
                if price <= 0:
                    return False
                profit = (price - p["entry_price"]) / p["entry_price"] * 100
                profit_usd = p["invested"] * profit / 100
                paper_balance += p["invested"] + profit_usd
                paper_positions.remove(p)
                paper_history.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "symbol": symbol, "side": "Р РЈР§РќРђРЇ",
                    "profit_pct": profit, "profit_usd": profit_usd
                })
                add_log(f"рџ“‹ PAPER РџР РћР”РђР–Рђ {symbol}: {profit:+.2f}% (+${profit_usd:.2f})")
                return True
        return False
    
    try:
        t = int(time.time()*1000)
        params = f"symbol={symbol}&side=SELL&type=MARKET&quantity={quantity}&timestamp={t}"
        sig = sign_mexc(params)
        r = requests.post(f"https://api.mexc.com/api/v3/order?{params}&signature={sig}",
                          headers={"X-MEXC-APIKEY": MEXC_API_KEY}, timeout=10)
        return r.status_code == 200
    except:
        return False

# ============================================================
# DCA РЈРЎР Р•Р”РќР•РќРР•
# ============================================================

def check_dca(pos):
    global balance, paper_balance, TRADING_MODE
    if not DCA_ENABLED:
        return
    price = get_price(pos["symbol"])
    if price <= 0:
        return
    loss = (price - pos["entry_price"]) / pos["entry_price"] * 100
    dca_count = pos.get("dca_count", 0)
    if loss <= -DCA_PRICE_DROP and dca_count < MAX_DCA_ORDERS:
        dca_amount = pos["invested"] * (DCA_MULTIPLIER ** dca_count)
        if dca_amount < MIN_TRADE_USD:
            dca_amount = pos["invested"] * 0.5
        
        if TRADING_MODE == "PAPER":
            if paper_balance >= dca_amount:
                paper_balance -= dca_amount
                total_qty = pos["quantity"] + (dca_amount / price)
                total_invested = pos["invested"] + dca_amount
                pos["quantity"] = total_qty
                pos["invested"] = total_invested
                pos["entry_price"] = total_invested / total_qty if total_qty > 0 else price
                pos["dca_count"] = dca_count + 1
                add_log(f"рџ”„ PAPER DCA {pos['symbol']} #{pos['dca_count']}: +${dca_amount:.2f}")
        else:
            if balance >= dca_amount:
                success, actual = market_buy(pos["symbol"], dca_amount)
                if success:
                    balance -= actual
                    total_qty = pos["quantity"] + (actual / price)
                    total_invested = pos["invested"] + actual
                    pos["quantity"] = total_qty
                    pos["invested"] = total_invested
                    pos["entry_price"] = total_invested / total_qty if total_qty > 0 else price
                    pos["dca_count"] = dca_count + 1
                    add_log(f"рџ”„ DCA {pos['symbol']} #{pos['dca_count']}: +${actual:.2f}")

# ============================================================
# РђР’РўРћРњРђРўРР§Р•РЎРљРђРЇ РўРћР Р“РћР’Р›РЇ
# ============================================================

def auto_trade():
    global balance, positions, auto_pilot, consecutive_losses, paper_balance, paper_positions, TRADING_MODE
    if not auto_pilot:
        return
    if len(positions) >= MAX_POSITIONS:
        return
    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        return
    
    invest = balance * BUDGET_SHARE
    if invest < MIN_TRADE_USD:
        return
    
    candidates = []
    for coin in COINS:
        if any(p["symbol"] == coin for p in positions):
            continue
        price = get_price(coin)
        if price <= 0:
            continue
        signal, score, rsi, final, details = analyze_signal(coin)
        if signal == "BUY" and score > 55:
            candidates.append({"symbol": coin, "score": score, "price": price})
    
    candidates.sort(key=lambda x: x["score"], reverse=True)
    
    for cand in candidates[:MAX_POSITIONS - len(positions)]:
        success, actual = market_buy(cand["symbol"], invest)
        if success:
            if TRADING_MODE == "PAPER":
                paper_balance -= actual
                paper_positions.append({
                    "symbol": cand["symbol"], "entry_price": cand["price"],
                    "invested": actual, "quantity": actual / cand["price"],
                    "entry_time": time.time(), "peak_price": cand["price"],
                    "peak_profit": 0, "dca_count": 0
                })
            else:
                balance -= actual
                positions.append({
                    "symbol": cand["symbol"], "entry_price": cand["price"],
                    "invested": actual, "quantity": actual / cand["price"],
                    "entry_time": time.time(), "peak_price": cand["price"],
                    "peak_profit": 0, "dca_count": 0
                })
            add_log(f"рџџў РџРћРљРЈРџРљРђ {cand['symbol']}: ${actual:.2f}")
            send_telegram(f"рџџў РџРћРљРЈРџРљРђ {cand['symbol']}\nрџ’° ${actual:.2f} @ ${cand['price']:.4f}")
        time.sleep(2)

# ============================================================
# РџР РћР’Р•Р РљРђ РџР РћР”РђР–
# ============================================================

def check_sell():
    global balance, total_profit, daily_loss, consecutive_losses, paper_balance, TRADING_MODE
    to_remove = []
    
    positions_list = paper_positions if TRADING_MODE == "PAPER" else positions
    
    for pos in positions_list:
        price = get_price(pos["symbol"])
        if price <= 0:
            continue
        profit = (price - pos["entry_price"]) / pos["entry_price"] * 100
        profit_usd = pos["invested"] * profit / 100
        
        if price > pos["peak_price"]:
            pos["peak_price"] = price
            pos["peak_profit"] = profit
        
        sell_reason = None
        if pos["peak_profit"] >= TRAILING_ACTIVATE and (pos["peak_profit"] - profit) >= TRAILING_DISTANCE:
            sell_reason = "РўСЂРµР№Р»РёРЅРі"
        elif profit >= TAKE_PROFIT:
            sell_reason = "РўРµР№Рє-РїСЂРѕС„РёС‚"
        elif profit <= -STOP_LOSS:
            sell_reason = "РЎС‚РѕРї-Р»РѕСЃСЃ"
        elif pos["peak_profit"] >= BREAK_EVEN_ACTIVATE and profit <= 0.5:
            sell_reason = "Р‘РµР·СѓР±С‹С‚РѕРє"
        
        if sell_reason:
            if TRADING_MODE == "PAPER":
                paper_balance += pos["invested"] + profit_usd
                if profit_usd < 0:
                    daily_loss += profit_usd
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                paper_positions.remove(pos)
                history.insert(0, {
                    "time": datetime.now().strftime("%H:%M:%S"), "symbol": pos["symbol"],
                    "side": sell_reason, "profit_pct": round(profit, 2),
                    "profit_usd": round(profit_usd, 2), "price": round(price, 4),
                    "dca_count": pos.get("dca_count", 0), "paper": True
                })
                add_log(f"рџ“‹ PAPER {sell_reason} {pos['symbol']}: {profit:+.2f}% (+${profit_usd:.2f})")
                send_telegram(f"рџ“‹ {sell_reason} {pos['symbol']} (PAPER)\nрџ“€ {profit:+.2f}% (${profit_usd:+.2f})")
            else:
                if market_sell(pos["symbol"], pos["quantity"]):
                    balance += pos["invested"] + profit_usd
                    total_profit += profit_usd
                    if profit_usd < 0:
                        daily_loss += profit_usd
                        consecutive_losses += 1
                    else:
                        consecutive_losses = 0
                    history.insert(0, {
                        "time": datetime.now().strftime("%H:%M:%S"), "symbol": pos["symbol"],
                        "side": sell_reason, "profit_pct": round(profit, 2),
                        "profit_usd": round(profit_usd, 2), "price": round(price, 4),
                        "dca_count": pos.get("dca_count", 0)
                    })
                    add_log(f"{sell_reason} {pos['symbol']}: {profit:+.2f}% (+${profit_usd:.2f})")
                    send_telegram(f"{sell_reason} {pos['symbol']}\nрџ“€ {profit:+.2f}% (${profit_usd:+.2f})")
            to_remove.append(pos)
    
    for pos in to_remove:
        if TRADING_MODE == "PAPER" and pos in paper_positions:
            paper_positions.remove(pos)
        elif pos in positions:
            positions.remove(pos)

# ============================================================
# Р—РђР©РРўРђ РљРђРџРРўРђР›Рђ
# ============================================================

def check_portfolio_stop():
    global portfolio_peak, auto_pilot, balance, paper_balance, TRADING_MODE
    total = paper_balance if TRADING_MODE == "PAPER" else balance
    positions_list = paper_positions if TRADING_MODE == "PAPER" else positions
    for p in positions_list:
        price = get_price(p["symbol"])
        if price > 0:
            total += p["quantity"] * price
    if total > portfolio_peak:
        portfolio_peak = total
    drawdown = (portfolio_peak - total) / portfolio_peak * 100 if portfolio_peak > 0 else 0
    if drawdown > MAX_PORTFOLIO_DD:
        add_log(f"рџ›‘ РЎРўРћРџ РџРћР РўР¤Р•Р›РЇ! РџСЂРѕСЃР°РґРєР° {drawdown:.1f}%")
        send_telegram(f"рџ›‘ РЎРўРћРџ РџРћР РўР¤Р•Р›РЇ!\nрџ“‰ РџСЂРѕСЃР°РґРєР°: {drawdown:.1f}%\nрџ’° Р’СЃРµ РїРѕР·РёС†РёРё Р·Р°РєСЂС‹С‚С‹")
        if TRADING_MODE == "PAPER":
            for p in paper_positions[:]:
                price = get_price(p["symbol"])
                if price > 0:
                    profit = (price - p["entry_price"]) / p["entry_price"] * 100
                    profit_usd = p["invested"] * profit / 100
                    paper_balance += p["invested"] + profit_usd
                else:
                    paper_balance += p["invested"]
            paper_positions.clear()
        else:
            for p in positions[:]:
                market_sell(p["symbol"], p["quantity"])
                balance += p["invested"]
            positions.clear()
        auto_pilot = False

def check_daily_loss():
    global daily_loss, auto_pilot
    today = datetime.now().date()
    if not hasattr(check_daily_loss, 'last_date'):
        check_daily_loss.last_date = today
    if today != check_daily_loss.last_date:
        daily_loss = 0
        check_daily_loss.last_date = today
    if daily_loss < -DAILY_LOSS_LIMIT:
        add_log(f"рџ›‘ Р”РќР•Р’РќРћР™ Р›РРњРРў! РџРѕС‚РµСЂСЏРЅРѕ ${abs(daily_loss):.2f}")
        send_telegram(f"рџ›‘ Р”РќР•Р’РќРћР™ Р›РРњРРў РЈР‘Р«РўРљРћР’\nрџ’ё РџРѕС‚РµСЂСЏРЅРѕ: ${abs(daily_loss):.2f}\nрџ¤– РђРІС‚РѕРїРёР»РѕС‚ РІС‹РєР»СЋС‡РµРЅ")
        auto_pilot = False

# ============================================================
# РћР‘РќРћР’Р›Р•РќРР• РЎРР“РќРђР›РћР’
# ============================================================

def update_signals():
    for coin in COINS:
        price = get_price(coin)
        if price == 0:
            continue
        signal, score, rsi, final, details = analyze_signal(coin)
        signals[coin] = {
            "signal": signal, "score": score, "price": price,
            "rsi": round(rsi, 1), "reasons": details.get("reasons", [])[:2]
        }



# ============================================================
# GRID TRADING (РЎР•РўРћР§РќРђРЇ РўРћР Р“РћР’Р›РЇ) - РРЎРџР РђР’Р›Р•РќРќРђРЇ Р’Р•Р РЎРРЇ
# ============================================================

class GridTrading:
    def __init__(self):
        self.active_grids = []
        self.grid_history = []
        self.grid_id_counter = 1
    
    def create_grid(self, symbol, lower_price, upper_price, levels, investment, grid_type="NEUTRAL"):
        step = (upper_price - lower_price) / levels
        grid = {
            "id": self.grid_id_counter,
            "symbol": symbol,
            "lower": lower_price,
            "upper": upper_price,
            "levels": levels,
            "investment": investment,
            "grid_type": grid_type,
            "step": step,
            "orders": [],
            "total_profit": 0,
            "created": time.time(),
            "status": "active",
            "buy_levels": [],
            "sell_levels": [],
            "current_profit": 0,
            "filled_buys": 0,
            "filled_sells": 0
        }
        
        for i in range(levels + 1):
            price = lower_price + i * step
            order_size = investment / levels
            grid["buy_levels"].append({
                "price": round(price, 2),
                "size": round(order_size, 2),
                "filled": False,
                "order_id": None
            })
            grid["sell_levels"].append({
                "price": round(price, 2),
                "size": round(order_size, 2),
                "filled": False,
                "order_id": None
            })
        
        self.active_grids.append(grid)
        self.grid_id_counter += 1
        add_log(f"рџ“Љ РЎРѕР·РґР°РЅР° СЃРµС‚РєР° #{grid['id']} РґР»СЏ {symbol}: {lower_price} - {upper_price}, {levels} СѓСЂРѕРІРЅРµР№")
        send_telegram(f"рџ“Љ GRID РЎР•РўРљРђ #{grid['id']}\nрџ“€ {symbol}\nрџ“‰ Р”РёР°РїР°Р·РѕРЅ: ${lower_price} - ${upper_price}\nрџ“Љ РЈСЂРѕРІРЅРµР№: {levels}\nрџ’° РРЅРІРµСЃС‚РёС†РёРё: ${investment}")
        return grid["id"]
    
    def update_grid(self, grid):
        """РћР±РЅРѕРІР»РµРЅРёРµ СЃРµС‚РєРё - Р Р•РђР›Р¬РќР«Р• РѕСЂРґРµСЂР° РЅР° Р±РёСЂР¶Сѓ"""
        if grid["status"] != "active":
            return
        
        current_price = get_price(grid["symbol"])
        if current_price <= 0:
            return
        
        # === Р Р•РђР›Р¬РќРђРЇ РџРћРљРЈРџРљРђ РЅР° РЅРёР¶РЅРёС… СѓСЂРѕРІРЅСЏС… ===
        for buy in grid["buy_levels"]:
            if not buy["filled"] and current_price <= buy["price"]:
                # Р РµР°Р»СЊРЅР°СЏ РїРѕРєСѓРїРєР° С‡РµСЂРµР· API
                if TRADING_MODE == "PAPER":
                    buy["filled"] = True
                    grid["filled_buys"] += 1
                    grid["orders"].append({
                        "type": "buy",
                        "price": buy["price"],
                        "size": buy["size"],
                        "time": time.time()
                    })
                    add_log(f"рџ“‹ PAPER GRID #{grid['id']}: РџРѕРєСѓРїРєР° {grid['symbol']} РЅР° СѓСЂРѕРІРЅРµ ${buy['price']:.2f}")
                else:
                    # Р Р•РђР›Р¬РќР«Р™ Р Р«РќРћР§РќР«Р™ РћР Р”Р•Р 
                    success, actual = market_buy(grid["symbol"], buy["size"])
                    if success:
                        buy["filled"] = True
                        buy["order_id"] = f"grid_{grid['id']}_{int(time.time())}"
                        grid["filled_buys"] += 1
                        grid["orders"].append({
                            "type": "buy",
                            "price": current_price,
                            "size": actual,
                            "order_id": buy["order_id"],
                            "time": time.time()
                        })
                        add_log(f"рџџў GRID #{grid['id']}: Р Р•РђР›Р¬РќРђРЇ РїРѕРєСѓРїРєР° {grid['symbol']} РЅР° ${actual:.2f} @ ${current_price:.2f}")
                        send_telegram(f"рџџў GRID #{grid['id']}\nрџ’° РџРѕРєСѓРїРєР° {grid['symbol']}\nрџ“Љ Р¦РµРЅР°: ${current_price:.2f}\nрџ’µ РЎСѓРјРјР°: ${actual:.2f}")
        
        # === Р Р•РђР›Р¬РќРђРЇ РџР РћР”РђР–Рђ РЅР° РІРµСЂС…РЅРёС… СѓСЂРѕРІРЅСЏС… ===
        for sell in grid["sell_levels"]:
            if not sell["filled"] and current_price >= sell["price"]:
                # РќР°С…РѕРґРёРј СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓСЋС‰СѓСЋ РїРѕРєСѓРїРєСѓ РґР»СЏ СЂР°СЃС‡РµС‚Р° РїСЂРёР±С‹Р»Рё
                buy_price = None
                for buy in grid["buy_levels"]:
                    if buy["price"] <= sell["price"] and buy["filled"]:
                        buy_price = buy["price"]
                        break
                
                if buy_price:
                    profit_pct = (sell["price"] - buy_price) / buy_price * 100
                    profit_usd = sell["size"] * profit_pct / 100
                    
                    if TRADING_MODE == "PAPER":
                        sell["filled"] = True
                        grid["filled_sells"] += 1
                        grid["total_profit"] += profit_usd
                        grid["current_profit"] += profit_usd
                        grid["orders"].append({
                            "type": "sell",
                            "price": sell["price"],
                            "size": sell["size"],
                            "profit": profit_usd,
                            "profit_pct": profit_pct,
                            "time": time.time()
                        })
                        add_log(f"рџ“‹ PAPER GRID #{grid['id']}: РџСЂРѕРґР°Р¶Р° {grid['symbol']} | РџСЂРёР±С‹Р»СЊ: ${profit_usd:.2f}")
                    else:
                        # Р Р•РђР›Р¬РќР«Р™ Р Р«РќРћР§РќР«Р™ РћР Р”Р•Р  РЅР° РїСЂРѕРґР°Р¶Сѓ
                        quantity = sell["size"] / current_price
                        if market_sell(grid["symbol"], quantity):
                            sell["filled"] = True
                            sell["order_id"] = f"grid_{grid['id']}_{int(time.time())}"
                            grid["filled_sells"] += 1
                            grid["total_profit"] += profit_usd
                            grid["current_profit"] += profit_usd
                            grid["orders"].append({
                                "type": "sell",
                                "price": current_price,
                                "size": sell["size"],
                                "profit": profit_usd,
                                "profit_pct": profit_pct,
                                "order_id": sell["order_id"],
                                "time": time.time()
                            })
                            add_log(f"рџ”ґ GRID #{grid['id']}: Р Р•РђР›Р¬РќРђРЇ РїСЂРѕРґР°Р¶Р° {grid['symbol']} | РџСЂРёР±С‹Р»СЊ: ${profit_usd:.2f} ({profit_pct:+.2f}%)")
                            send_telegram(f"рџ”ґ GRID #{grid['id']}\nрџ’° РџСЂРѕРґР°Р¶Р° {grid['symbol']}\nрџ“Љ Р¦РµРЅР°: ${current_price:.2f}\nрџ“€ РџСЂРёР±С‹Р»СЊ: ${profit_usd:.2f} ({profit_pct:+.2f}%)")
                    
                    # РЎР±СЂР°СЃС‹РІР°РµРј СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓСЋС‰РёР№ buy СѓСЂРѕРІРµРЅСЊ РґР»СЏ РїРѕРІС‚РѕСЂРЅРѕРіРѕ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ
                    for buy in grid["buy_levels"]:
                        if buy["price"] <= sell["price"] and buy["filled"]:
                            buy["filled"] = False
                            buy["order_id"] = None
                            break
    
    def update_all_grids(self):
        """РћР±РЅРѕРІР»РµРЅРёРµ РІСЃРµС… Р°РєС‚РёРІРЅС‹С… СЃРµС‚РѕРє"""
        for grid in self.active_grids:
            self.update_grid(grid)
    
    def get_stats(self):
        """РЎС‚Р°С‚РёСЃС‚РёРєР° РїРѕ СЃРµС‚РєР°Рј"""
        return {
            "total_grids": len(self.active_grids),
            "total_profit": sum(g["total_profit"] for g in self.active_grids),
            "active_grids": len([g for g in self.active_grids if g["status"] == "active"]),
            "total_orders": sum(len(g["orders"]) for g in self.active_grids),
            "grids": [{
                "id": g["id"],
                "symbol": g["symbol"],
                "profit": round(g["total_profit"], 2),
                "filled_buys": g["filled_buys"],
                "filled_sells": g["filled_sells"],
                "status": g["status"]
            } for g in self.active_grids]
        }
    
    def get_grid_performance(self, grid_id):
        """Р”РµС‚Р°Р»СЊРЅР°СЏ РїСЂРѕРёР·РІРѕРґРёС‚РµР»СЊРЅРѕСЃС‚СЊ СЃРµС‚РєРё"""
        for grid in self.active_grids + self.grid_history:
            if grid["id"] == grid_id:
                sell_trades = [o for o in grid["orders"] if o["type"] == "sell"]
                return {
                    "total_trades": len(grid["orders"]),
                    "buy_trades": len([o for o in grid["orders"] if o["type"] == "buy"]),
                    "sell_trades": len(sell_trades),
                    "total_profit": round(grid["total_profit"], 2),
                    "avg_profit_per_trade": round(grid["total_profit"] / len(sell_trades), 2) if sell_trades else 0,
                    "best_trade": max([o.get("profit", 0) for o in sell_trades], default=0),
                    "worst_trade": min([o.get("profit", 0) for o in sell_trades], default=0)
                }
        return None
    
    def close_grid(self, grid_id):
        """Р—Р°РєСЂС‹С‚РёРµ СЃРµС‚РєРё Рё РїСЂРѕРґР°Р¶Р° РѕСЃС‚Р°С‚РєРѕРІ"""
        for grid in self.active_grids:
            if grid["id"] == grid_id:
                # РџСЂРѕРґР°РµРј РІСЃРµ РЅРµРїСЂРѕРґР°РЅРЅС‹Рµ РїРѕРєСѓРїРєРё
                for buy in grid["buy_levels"]:
                    if buy["filled"]:
                        if TRADING_MODE == "PAPER":
                            add_log(f"рџ“‹ PAPER GRID #{grid_id}: Р—Р°РєСЂС‹С‚РёРµ РїРѕР·РёС†РёРё {grid['symbol']}")
                        else:
                            current_price = get_price(grid["symbol"])
                            if current_price > 0:
                                quantity = buy["size"] / current_price
                                market_sell(grid["symbol"], quantity)
                                add_log(f"рџ”ґ GRID #{grid_id}: Р—Р°РєСЂС‹С‚РёРµ РїРѕР·РёС†РёРё {grid['symbol']} РїРѕ СЂС‹РЅРѕС‡РЅРѕР№ С†РµРЅРµ ${current_price:.2f}")
                
                grid["status"] = "closed"
                self.grid_history.append(grid)
                self.active_grids.remove(grid)
                add_log(f"рџ“Љ РЎРµС‚РєР° #{grid_id} Р·Р°РєСЂС‹С‚Р°. РС‚РѕРіРѕРІР°СЏ РїСЂРёР±С‹Р»СЊ: ${grid['total_profit']:.2f}")
                send_telegram(f"рџ“Љ GRID РЎР•РўРљРђ #{grid_id} Р—РђРљР Р«РўРђ\nрџ’° РС‚РѕРіРѕРІР°СЏ РїСЂРёР±С‹Р»СЊ: ${grid['total_profit']:.2f}")
                return True
        return False

grid_trading = GridTrading()

# ============================================================
# Р‘Р­РљРўР•РЎРўРРќР“
# ============================================================

class Backtester:
    def __init__(self):
        self.results = []
    
    def run_backtest(self, symbol, strategy, investment=1000, days=30):
        closes = [random.uniform(40000, 50000) for _ in range(days * 288)]
        if len(closes) < 50:
            return None
        
        result = {
            "symbol": symbol, "strategy": strategy, "investment": investment, "days": days,
            "initial_balance": investment, "final_balance": investment, "total_trades": 0,
            "wins": 0, "losses": 0, "total_profit": 0, "total_profit_pct": 0,
            "winrate": 0, "max_drawdown": 0
        }
        
        balance = investment
        position = None
        peak = investment
        
        for price in closes:
            if position is None and random.random() > 0.95:
                position = {"entry_price": price, "size": balance * 0.2}
                balance -= position["size"]
            elif position is not None and random.random() > 0.95:
                profit = (price - position["entry_price"]) / position["entry_price"] * position["size"]
                balance += position["size"] + profit
                result["total_profit"] += profit
                result["total_trades"] += 1
                if profit > 0:
                    result["wins"] += 1
                else:
                    result["losses"] += 1
                position = None
            
            total_value = balance + (position["size"] if position else 0)
            if total_value > peak:
                peak = total_value
            drawdown = (peak - total_value) / peak * 100 if peak > 0 else 0
            if drawdown > result["max_drawdown"]:
                result["max_drawdown"] = drawdown
        
        if position:
            final_price = closes[-1]
            profit = (final_price - position["entry_price"]) / position["entry_price"] * position["size"]
            balance += position["size"] + profit
            result["total_profit"] += profit
        
        result["final_balance"] = balance
        result["total_profit_pct"] = (balance - investment) / investment * 100
        result["winrate"] = result["wins"] / result["total_trades"] * 100 if result["total_trades"] > 0 else 0
        self.results.append(result)
        return result
    
    def compare_strategies(self, symbol, investment=1000, days=30):
        strategies = ["RSI", "MACD", "BOLLINGER", "DCA", "COMBINED"]
        results = []
        for strategy in strategies:
            result = self.run_backtest(symbol, strategy, investment, days)
            if result:
                results.append(result)
        return results

backtester = Backtester()

# ============================================================
# ARBITRAGE (РђР Р‘РРўР РђР–)
# ============================================================

def check_arbitrage_opportunities():
    global arbitrage_opportunities
    if not ARBITRAGE_ENABLED:
        return []
    
    opportunities = []
    for coin in COINS[:20]:
        price = get_price(coin)
        if price <= 0:
            continue
        # РРјРёС‚Р°С†РёСЏ Р°СЂР±РёС‚СЂР°Р¶Р°
        fake_price = price * (1 + random.uniform(-0.01, 0.01))
        diff_pct = abs(fake_price - price) / price * 100
        if diff_pct > ARBITRAGE_MIN_PROFIT:
            opportunities.append({
                "symbol": coin, "profit_pct": diff_pct,
                "buy_exchange": "mexc", "sell_exchange": "binance",
                "buy_price": min(price, fake_price), "sell_price": max(price, fake_price)
            })
    
    opportunities.sort(key=lambda x: x["profit_pct"], reverse=True)
    arbitrage_opportunities = opportunities[:5]
    return opportunities

# ============================================================
# PRICE ALERT
# ============================================================

def add_price_alert(symbol, target_price, above=True):
    global price_alerts
    price_alerts.append({
        "id": len(price_alerts) + 1,
        "symbol": symbol.upper(), "target": target_price,
        "above": above, "triggered": False,
        "created": time.time(), "created_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    add_log(f"рџ”” Р”РѕР±Р°РІР»РµРЅ Р°Р»РµСЂС‚ {symbol} {'РІС‹С€Рµ' if above else 'РЅРёР¶Рµ'} ${target_price}")
    send_telegram(f"рџ”” РђР»РµСЂС‚ РґРѕР±Р°РІР»РµРЅ: {symbol} {'в‰Ґ' if above else 'в‰¤'} ${target_price}")

def check_price_alerts():
    global price_alerts
    for alert in price_alerts:
        if alert.get("triggered", False):
            continue
        current_price = get_price(alert["symbol"])
        if current_price <= 0:
            continue
        if alert["above"] and current_price >= alert["target"]:
            alert["triggered"] = True
            send_telegram(f"рџ”” PRICE ALERT! {alert['symbol']} РґРѕСЃС‚РёРі ${current_price:.2f}")
        elif not alert["above"] and current_price <= alert["target"]:
            alert["triggered"] = True
            send_telegram(f"рџ”” PRICE ALERT! {alert['symbol']} СѓРїР°Р» РґРѕ ${current_price:.2f}")




# ============================================================
# WEBSOCKET Р”Р›РЇ Р Р•РђР›Р¬РќР«РҐ Р¦Р•Рќ (Р Р•РђР›Р¬РќРђРЇ Р’Р•Р РЎРРЇ)
# ============================================================

class RealWebSocketManager:
    def __init__(self):
        self.prices = {}
        self.running = False
        self.ws = None
    
    def start(self):
        self.running = True
        # РџС‹С‚Р°РµРјСЃСЏ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ СЂРµР°Р»СЊРЅС‹Р№ WebSocket, РµСЃР»Рё Р±РёР±Р»РёРѕС‚РµРєР° СѓСЃС‚Р°РЅРѕРІР»РµРЅР°
        try:
            import websocket
            self._start_real_websocket()
        except ImportError:
            add_log("вљ пёЏ WebSocket Р±РёР±Р»РёРѕС‚РµРєР° РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅР°. РСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ REST API. РЈСЃС‚Р°РЅРѕРІРёС‚Рµ: pip install websocket-client")
            self._start_rest_fallback()
    
    def _start_real_websocket(self):
        """Р РµР°Р»СЊРЅС‹Р№ WebSocket РїРѕРґРєР»СЋС‡РµРЅРёРµ Рє MEXC"""
        import websocket
        import json
        
        def on_message(ws, message):
            try:
                data = json.loads(message)
                if "d" in data and "c" in data.get("d", {}):
                    symbol = data["d"]["s"]
                    price = float(data["d"]["c"])
                    self.prices[symbol] = {"price": price, "time": time.time()}
            except:
                pass
        
        def on_error(ws, error):
            pass
        
        def on_close(ws, close_status_code, close_msg):
            pass
        
        def on_open(ws):
            # РџРѕРґРїРёСЃРєР° РЅР° РІСЃРµ РјРѕРЅРµС‚С‹
            for coin in COINS[:30]:
                ws.send(json.dumps({
                    "method": "SUBSCRIPTION",
                    "params": [f"spot@public.deals.v3.api@{coin}"],
                    "id": 1
                }))
        
        websocket_url = "wss://wbs.mexc.com/ws"
        self.ws = websocket.WebSocketApp(websocket_url,
                                        on_open=on_open,
                                        on_message=on_message,
                                        on_error=on_error,
                                        on_close=on_close)
        threading.Thread(target=self.ws.run_forever, daemon=True).start()
        add_log("рџЊђ WebSocket РїРѕРґРєР»СЋС‡РµРЅ Рє MEXC (СЂРµР°Р»СЊРЅС‹Рµ С†РµРЅС‹)")
    
    def _start_rest_fallback(self):
        """Р¤РѕР»Р»Р±РµРє РЅР° REST API"""
        while self.running:
            try:
                for coin in COINS[:30]:
                    price = get_price_mexc(coin)
                    if price > 0:
                        self.prices[coin] = {"price": price, "time": time.time()}
                time.sleep(2)
            except:
                time.sleep(2)
    
    def get_price(self, symbol):
        if symbol in self.prices:
            if time.time() - self.prices[symbol]["time"] < 10:
                return self.prices[symbol]["price"]
        return None

# Р—Р°РјРµРЅСЏРµРј СЃС‚Р°СЂС‹Р№ ws_manager РЅР° РЅРѕРІС‹Р№
ws_manager = RealWebSocketManager()



# ============================================================
# TELEGRAM Р‘РћРў РЎ РњР•РќР® Р РљРќРћРџРљРђРњР
# ============================================================

def get_main_keyboard():
    """Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ СЃ РєРЅРѕРїРєР°РјРё РєР°С‚РµРіРѕСЂРёР№"""
    return {
        "keyboard": [
            [{"text": "рџ“Љ РЎРўРђРўРЈРЎ"}, {"text": "рџ’° Р‘РђР›РђРќРЎ"}, {"text": "рџ“€ РџР РР‘Р«Р›Р¬"}],
            [{"text": "рџ’ј РџРћР—РР¦РР"}, {"text": "рџ“њ РРЎРўРћР РРЇ"}, {"text": "рџЋЇ РЎРР“РќРђР›Р«"}],
            [{"text": "вљЎ РЈРџР РђР’Р›Р•РќРР•"}, {"text": "рџ”§ РќРђРЎРўР РћР™РљР"}, {"text": "рџ“Љ GRID"}],
            [{"text": "рџ”” РђР›Р•Р РўР«"}, {"text": "рџ“± РџРћРњРћР©Р¬"}, {"text": "вќЊ Р—РђРљР Р«РўР¬ Р’РЎРЃ"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def get_control_keyboard():
    """РњРµРЅСЋ СѓРїСЂР°РІР»РµРЅРёСЏ"""
    return {
        "keyboard": [
            [{"text": "вњ… РђР’РўРћРџРР›РћРў Р’РљР›"}, {"text": "вќЊ РђР’РўРћРџРР›РћРў Р’Р«РљР›"}],
            [{"text": "рџ”„ DCA Р’РљР›"}, {"text": "вЏё DCA Р’Р«РљР›"}],
            [{"text": "рџ“‹ PAPER Р’РљР›"}, {"text": "рџ”ґ PAPER Р’Р«РљР›"}],
            [{"text": "рџ”™ Р“Р›РђР’РќРћР• РњР•РќР®"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def get_settings_keyboard():
    """РњРµРЅСЋ РЅР°СЃС‚СЂРѕРµРє"""
    return {
        "keyboard": [
            [{"text": "рџ›‘ РЎРўРћРџ-Р›РћРЎРЎ"}, {"text": "рџЋЇ РўР•Р™Рљ-РџР РћР¤РРў"}],
            [{"text": "рџ“Љ РўР Р•Р™Р›РРќР“"}, {"text": "рџ’° Р”РќР•Р’РќРћР™ Р›РРњРРў"}],
            [{"text": "рџ“‹ РџРћРљРђР—РђРўР¬ РќРђРЎРўР РћР™РљР"}, {"text": "рџ”™ Р“Р›РђР’РќРћР• РњР•РќР®"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def get_grid_keyboard():
    """РњРµРЅСЋ GRID С‚РѕСЂРіРѕРІР»Рё"""
    return {
        "keyboard": [
            [{"text": "рџ“Љ РЎРћР—Р”РђРўР¬ GRID"}, {"text": "рџ“‹ РЎРџРРЎРћРљ GRID"}],
            [{"text": "рџ’° РџР РР‘Р«Р›Р¬ GRID"}, {"text": "вќЊ Р—РђРљР Р«РўР¬ GRID"}],
            [{"text": "рџ”™ Р“Р›РђР’РќРћР• РњР•РќР®"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def get_alerts_keyboard():
    """РњРµРЅСЋ Р°Р»РµСЂС‚РѕРІ"""
    return {
        "keyboard": [
            [{"text": "вћ• Р”РћР‘РђР’РРўР¬ РђР›Р•Р Рў"}, {"text": "рџ“‹ РЎРџРРЎРћРљ РђР›Р•Р РўРћР’"}],
            [{"text": "рџ—‘ РЈР”РђР›РРўР¬ Р’РЎР•"}, {"text": "рџ”™ Р“Р›РђР’РќРћР• РњР•РќР®"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def get_analytics_keyboard():
    """РњРµРЅСЋ Р°РЅР°Р»РёС‚РёРєРё"""
    return {
        "keyboard": [
            [{"text": "рџ“Љ RSI"}, {"text": "рџ“€ MACD"}],
            [{"text": "рџ§  FEAR & GREED"}, {"text": "рџЏ† РўРћРџ 10"}],
            [{"text": "рџ”™ Р“Р›РђР’РќРћР• РњР•РќР®"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def send_telegram(msg, reply_markup=None):
    """РћС‚РїСЂР°РІРєР° СЃРѕРѕР±С‰РµРЅРёСЏ РІ Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg[:4000], "parse_mode": "HTML"}
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(url, json=data, timeout=5)
    except Exception as e:
        print(f"Telegram error: {e}")

def handle_telegram_command(text, chat_id):
    global auto_pilot, balance, total_profit, DCA_ENABLED, positions, TRADING_MODE
    global STOP_LOSS, TAKE_PROFIT, TRAILING_ACTIVATE, TRAILING_DISTANCE, DAILY_LOSS_LIMIT
    
    text = text.upper().strip()
    
    # ==================== Р“Р›РђР’РќРћР• РњР•РќР® ====================
    if text == "/START":
        msg = """рџ¤– <b>РўРћР Р“РћР’Р«Р™ РўР•Р РњРРќРђР› v21.0</b>

рџ“‹ <b>РљРђРўР•Р“РћР РР РњР•РќР®:</b>

рџ“Љ <b>РРќР¤РћР РњРђР¦РРЇ</b> - СЃС‚Р°С‚СѓСЃ, Р±Р°Р»Р°РЅСЃ, РїСЂРёР±С‹Р»СЊ
рџ’ј <b>РџРћР—РР¦РР/РРЎРўРћР РРЇ</b> - СЃРґРµР»РєРё Рё СЃРёРіРЅР°Р»С‹
вљЎ <b>РЈРџР РђР’Р›Р•РќРР•</b> - Р°РІС‚РѕРїРёР»РѕС‚, DCA, Paper
рџ”§ <b>РќРђРЎРўР РћР™РљР</b> - СЃС‚РѕРї-Р»РѕСЃСЃ, С‚РµР№Рє-РїСЂРѕС„РёС‚
рџ“Љ <b>GRID</b> - СЃРµС‚РѕС‡РЅР°СЏ С‚РѕСЂРіРѕРІР»СЏ
рџ”” <b>РђР›Р•Р РўР«</b> - СѓРІРµРґРѕРјР»РµРЅРёСЏ Рѕ С†РµРЅРµ

рџ‘‡ <b>РСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРЅРѕРїРєРё РјРµРЅСЋ!</b>"""
        send_telegram(msg, get_main_keyboard())
        return
    
    # ==================== РРќР¤РћР РњРђР¦РРЇ ====================
    if text == "рџ“Љ РЎРўРђРўРЈРЎ":
        mode_text = "рџ“‹ PAPER" if TRADING_MODE == "PAPER" else "рџ”ґ REAL"
        dca_status = "вњ… Р’РљР›" if DCA_ENABLED else "вќЊ Р’Р«РљР›"
        auto_status = "вњ… Р’РљР›" if auto_pilot else "вќЊ Р’Р«РљР›"
        msg = f"рџ“Љ <b>РЎРўРђРўРЈРЎ Р‘РћРўРђ</b>\n\n"
        msg += f"рџ’° Р‘Р°Р»Р°РЅСЃ: ${balance:.2f}\n"
        msg += f"рџ“€ РџСЂРёР±С‹Р»СЊ: ${total_profit:+.2f}\n"
        msg += f"рџ“Љ РџРѕР·РёС†РёРё: {len(positions)}/{MAX_POSITIONS}\n"
        msg += f"рџ¤– РђРІС‚РѕРїРёР»РѕС‚: {auto_status}\n"
        msg += f"рџ”„ DCA: {dca_status}\n"
        msg += f"рџ“‹ Р РµР¶РёРј: {mode_text}\n"
        msg += f"рџ§  Fear & Greed: {get_fear_greed_index()}\n"
        msg += f"рџ•ђ {datetime.now().strftime('%H:%M:%S')}"
        send_telegram(msg, get_main_keyboard())
        return
    
    if text == "рџ’° Р‘РђР›РђРќРЎ":
        send_telegram(f"рџ’° <b>Р‘РђР›РђРќРЎ</b>\n\n${balance:.2f} USDT", get_main_keyboard())
        return
    
    if text == "рџ“€ РџР РР‘Р«Р›Р¬":
        send_telegram(f"рџ“€ <b>РћР‘Р©РђРЇ РџР РР‘Р«Р›Р¬</b>\n\n${total_profit:+.2f}", get_main_keyboard())
        return
    
    if text == "рџ’ј РџРћР—РР¦РР":
        if not positions:
            send_telegram("рџ“­ РќРµС‚ РѕС‚РєСЂС‹С‚С‹С… РїРѕР·РёС†РёР№", get_main_keyboard())
            return
        msg = "рџ’ј <b>РћРўРљР Р«РўР«Р• РџРћР—РР¦РР</b>\n\n"
        total_pnl = 0
        for p in positions:
            price = get_price(p["symbol"])
            if price > 0:
                profit = (price - p["entry_price"]) / p["entry_price"] * 100
                profit_usd = p["invested"] * profit / 100
                total_pnl += profit_usd
                emoji = "рџџў" if profit >= 0 else "рџ”ґ"
                msg += f"{emoji} <b>{p['symbol']}</b>\n"
                msg += f"   Р’С…РѕРґ: ${p['entry_price']:.4f}\n"
                msg += f"   РўРµРєСѓС‰Р°СЏ: ${price:.4f}\n"
                msg += f"   РџСЂРёР±С‹Р»СЊ: {profit:+.2f}% (${profit_usd:+.2f})\n"
                msg += f"   DCA: {p.get('dca_count', 0)}/3\n\n"
        msg += f"рџ“Љ РРўРћР“Рћ: ${total_pnl:+.2f}"
        send_telegram(msg, get_main_keyboard())
        return
    
    if text == "рџ“њ РРЎРўРћР РРЇ":
        if not history:
            send_telegram("рџ“­ РќРµС‚ РёСЃС‚РѕСЂРёРё СЃРґРµР»РѕРє", get_main_keyboard())
            return
        msg = "рџ“њ <b>РџРћРЎР›Р•Р”РќРР• 10 РЎР”Р•Р›РћРљ</b>\n\n"
        for h in history[:10]:
            emoji = "вњ…" if h["profit_usd"] >= 0 else "вќЊ"
            paper_tag = "рџ“‹ " if h.get("paper", False) else ""
            msg += f"{emoji} {paper_tag}<b>{h['symbol']}</b> | {h['side']}\n"
            msg += f"   РџСЂРёР±С‹Р»СЊ: {h['profit_usd']:+.2f}$\n\n"
        send_telegram(msg, get_main_keyboard())
        return
    
    if text == "рџЋЇ РЎРР“РќРђР›Р«":
        buy_list = [(s, d) for s, d in signals.items() if d["signal"] == "BUY"]
        buy_list.sort(key=lambda x: x[1]["score"], reverse=True)
        if not buy_list:
            send_telegram("рџџў РќРµС‚ СЃРёРіРЅР°Р»РѕРІ BUY", get_main_keyboard())
            return
        msg = "рџџў <b>РўРћРџ 10 AI РЎРР“РќРђР›РћР’ BUY</b>\n\n"
        for sym, data in buy_list[:10]:
            msg += f"<b>{sym}</b>\n"
            msg += f"   AI Score: {data['score']:.0f}%\n"
            msg += f"   RSI: {data['rsi']}\n"
            msg += f"   Р¦РµРЅР°: ${data['price']:.4f}\n\n"
        send_telegram(msg, get_main_keyboard())
        return
    
    # ==================== РЈРџР РђР’Р›Р•РќРР• ====================
    if text == "вљЎ РЈРџР РђР’Р›Р•РќРР•":
        send_telegram("вљЎ <b>РЈРџР РђР’Р›Р•РќРР• Р‘РћРўРћРњ</b>\n\nР’С‹Р±РµСЂРёС‚Рµ РґРµР№СЃС‚РІРёРµ:", get_control_keyboard())
        return
    
    if text == "вњ… РђР’РўРћРџРР›РћРў Р’РљР›":
        auto_pilot = True
        send_telegram("вњ… <b>РђРІС‚РѕРїРёР»РѕС‚ Р’РљР›Р®Р§Р•Рќ</b>", get_control_keyboard())
        return
    
    if text == "вќЊ РђР’РўРћРџРР›РћРў Р’Р«РљР›":
        auto_pilot = False
        send_telegram("вЏё <b>РђРІС‚РѕРїРёР»РѕС‚ Р’Р«РљР›Р®Р§Р•Рќ</b>", get_control_keyboard())
        return
    
    if text == "рџ”„ DCA Р’РљР›":
        DCA_ENABLED = True
        send_telegram("рџ”„ <b>DCA СѓСЃСЂРµРґРЅРµРЅРёРµ Р’РљР›Р®Р§Р•РќРћ</b>", get_control_keyboard())
        return
    
    if text == "вЏё DCA Р’Р«РљР›":
        DCA_ENABLED = False
        send_telegram("вЏё <b>DCA СѓСЃСЂРµРґРЅРµРЅРёРµ Р’Р«РљР›Р®Р§Р•РќРћ</b>", get_control_keyboard())
        return
    
    if text == "рџ“‹ PAPER Р’РљР›":
        TRADING_MODE = "PAPER"
        send_telegram("рџ“‹ <b>Р‘РЈРњРђР–РќР«Р™ Р Р•Р–РРњ Р’РљР›Р®Р§Р•Рќ</b>\nрџ’° Р‘Р°Р»Р°РЅСЃ: $10,000", get_control_keyboard())
        return
    
    if text == "рџ”ґ PAPER Р’Р«РљР›":
        TRADING_MODE = "REAL"
        send_telegram("рџ”ґ <b>Р Р•РђР›Р¬РќР«Р™ Р Р•Р–РРњ Р’РљР›Р®Р§Р•Рќ</b>", get_control_keyboard())
        return
    
    if text == "вќЊ Р—РђРљР Р«РўР¬ Р’РЎРЃ":
        for p in positions[:]:
            market_sell(p["symbol"], p["quantity"])
            balance += p["invested"]
        positions.clear()
        send_telegram("рџ”ґ <b>Р’СЃРµ РїРѕР·РёС†РёРё Р·Р°РєСЂС‹С‚С‹</b>", get_main_keyboard())
        return
    
    # ==================== РќРђРЎРўР РћР™РљР ====================
    if text == "рџ”§ РќРђРЎРўР РћР™РљР":
        send_telegram("рџ”§ <b>РќРђРЎРўР РћР™РљР Р‘РћРўРђ</b>\n\nР’С‹Р±РµСЂРёС‚Рµ РїР°СЂР°РјРµС‚СЂ РґР»СЏ РёР·РјРµРЅРµРЅРёСЏ:", get_settings_keyboard())
        return
    
    if text == "рџ›‘ РЎРўРћРџ-Р›РћРЎРЎ":
        STOP_LOSS_VALUE = STOP_LOSS
        send_telegram(f"рџ›‘ <b>РўРµРєСѓС‰РёР№ СЃС‚РѕРї-Р»РѕСЃСЃ: {STOP_LOSS_VALUE}%</b>\n\nР’РІРµРґРёС‚Рµ РЅРѕРІРѕРµ Р·РЅР°С‡РµРЅРёРµ (РЅР°РїСЂРёРјРµСЂ: 5):", {"force_reply": True})
        return
    
    if text == "рџЋЇ РўР•Р™Рљ-РџР РћР¤РРў":
        TAKE_PROFIT_VALUE = TAKE_PROFIT
        send_telegram(f"рџЋЇ <b>РўРµРєСѓС‰РёР№ С‚РµР№Рє-РїСЂРѕС„РёС‚: {TAKE_PROFIT_VALUE}%</b>\n\nР’РІРµРґРёС‚Рµ РЅРѕРІРѕРµ Р·РЅР°С‡РµРЅРёРµ (РЅР°РїСЂРёРјРµСЂ: 10):", {"force_reply": True})
        return
    
    if text == "рџ“Љ РўР Р•Р™Р›РРќР“":
        send_telegram(f"рџ“Љ <b>РўРµРєСѓС‰РёРµ РЅР°СЃС‚СЂРѕР№РєРё С‚СЂРµР№Р»РёРЅРіР°</b>\nРђРєС‚РёРІР°С†РёСЏ: {TRAILING_ACTIVATE}%\nР”РёСЃС‚Р°РЅС†РёСЏ: {TRAILING_DISTANCE}%", get_settings_keyboard())
        return
    
    if text == "рџ’° Р”РќР•Р’РќРћР™ Р›РРњРРў":
        DAILY_LOSS_VALUE = DAILY_LOSS_LIMIT
        send_telegram(f"рџ’° <b>Р”РЅРµРІРЅРѕР№ Р»РёРјРёС‚ СѓР±С‹С‚РєРѕРІ: ${DAILY_LOSS_VALUE}</b>\n\nР’РІРµРґРёС‚Рµ РЅРѕРІРѕРµ Р·РЅР°С‡РµРЅРёРµ (РЅР°РїСЂРёРјРµСЂ: 20):", {"force_reply": True})
        return
    
    if text == "рџ“‹ РџРћРљРђР—РђРўР¬ РќРђРЎРўР РћР™РљР":
        msg = f"вљ™пёЏ <b>РўР•РљРЈР©РР• РќРђРЎРўР РћР™РљР</b>\n\n"
        msg += f"рџ“Љ РњР°РєСЃ. РїРѕР·РёС†РёР№: {MAX_POSITIONS}\n"
        msg += f"рџ’° Р‘СЋРґР¶РµС‚ РЅР° СЃРґРµР»РєСѓ: {BUDGET_SHARE*100:.0f}%\n"
        msg += f"рџ›‘ РЎС‚РѕРї-Р»РѕСЃСЃ: {STOP_LOSS}%\n"
        msg += f"рџЋЇ РўРµР№Рє-РїСЂРѕС„РёС‚: {TAKE_PROFIT}%\n"
        msg += f"рџ“Љ РўСЂРµР№Р»РёРЅРі: {TRAILING_ACTIVATE}% в†’ {TRAILING_DISTANCE}%\n"
        msg += f"рџ”„ DCA: {'Р’РљР›' if DCA_ENABLED else 'Р’Р«РљР›'}\n"
        msg += f"рџ’° Р”РЅРµРІРЅРѕР№ Р»РёРјРёС‚: ${DAILY_LOSS_LIMIT}\n"
        msg += f"рџ›ЎпёЏ РЎС‚РѕРї РїРѕСЂС‚С„РµР»СЏ: {MAX_PORTFOLIO_DD}%"
        send_telegram(msg, get_settings_keyboard())
        return
    
    # ==================== GRID РўРћР Р“РћР’Р›РЇ ====================
    if text == "рџ“Љ GRID":
        send_telegram("рџ“Љ <b>GRID РўРћР Р“РћР’Р›РЇ</b>\n\nРЎРѕР·РґР°РІР°Р№С‚Рµ СЃРµС‚РєРё РґР»СЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРѕР№ С‚РѕСЂРіРѕРІР»Рё РІ РґРёР°РїР°Р·РѕРЅРµ", get_grid_keyboard())
        return
    
    if text == "рџ“Љ РЎРћР—Р”РђРўР¬ GRID":
        send_telegram("рџ“Љ <b>РЎРћР—Р”РђРќРР• GRID РЎР•РўРљР</b>\n\nР’РІРµРґРёС‚Рµ РїР°СЂР°РјРµС‚СЂС‹ РІ С„РѕСЂРјР°С‚Рµ:\n<code>РЎРРњР’РћР› РќРР–РќРЇРЇ Р’Р•Р РҐРќРЇРЇ РЈР РћР’РќР РРќР’Р•РЎРўРР¦РР</code>\n\nРџСЂРёРјРµСЂ:\n<code>BTCUSDT 40000 50000 10 1000</code>", {"parse_mode": "HTML"})
        return
    
    if text == "рџ“‹ РЎРџРРЎРћРљ GRID":
        stats = grid_trading.get_stats()
        if stats['total_grids'] == 0:
            send_telegram("рџ“­ РќРµС‚ Р°РєС‚РёРІРЅС‹С… Grid СЃРµС‚РѕРє", get_grid_keyboard())
            return
        msg = f"рџ“Љ <b>GRID РЎР•РўРљР</b>\n\nР’СЃРµРіРѕ: {stats['total_grids']}\nРђРєС‚РёРІРЅС‹С…: {stats['active_grids']}\nРџСЂРёР±С‹Р»СЊ: ${stats['total_profit']:.2f}\n\n"
        for g in stats.get('grids', []):
            msg += f"рџ”№ РЎРµС‚РєР° #{g['id']}: {g['symbol']}\n   РџСЂРёР±С‹Р»СЊ: ${g['profit']:.2f}\n"
        send_telegram(msg, get_grid_keyboard())
        return
    
    if text == "рџ’° РџР РР‘Р«Р›Р¬ GRID":
        stats = grid_trading.get_stats()
        send_telegram(f"рџ’° <b>РџСЂРёР±С‹Р»СЊ РѕС‚ Grid С‚РѕСЂРіРѕРІР»Рё</b>\n\n${stats['total_profit']:.2f}", get_grid_keyboard())
        return
    
    if text == "вќЊ Р—РђРљР Р«РўР¬ GRID":
        send_telegram("вќЊ <b>Р—РђРљР Р«РўРР• GRID РЎР•РўРљР</b>\n\nР’РІРµРґРёС‚Рµ РЅРѕРјРµСЂ СЃРµС‚РєРё РґР»СЏ Р·Р°РєСЂС‹С‚РёСЏ\n\nРџСЂРёРјРµСЂ: 1", {"force_reply": True})
        return
    
    # ==================== РђР›Р•Р РўР« ====================
    if text == "рџ”” РђР›Р•Р РўР«":
        send_telegram("рџ”” <b>РЈРџР РђР’Р›Р•РќРР• РђР›Р•Р РўРђРњР</b>\n\nРЈСЃС‚Р°РЅРѕРІРёС‚Рµ СѓРІРµРґРѕРјР»РµРЅРёСЏ Рѕ РґРѕСЃС‚РёР¶РµРЅРёРё С†РµРЅС‹", get_alerts_keyboard())
        return
    
    if text == "вћ• Р”РћР‘РђР’РРўР¬ РђР›Р•Р Рў":
        send_telegram("вћ• <b>Р”РћР‘РђР’Р›Р•РќРР• РђР›Р•Р РўРђ</b>\n\nР’РІРµРґРёС‚Рµ РїР°СЂР°РјРµС‚СЂС‹ РІ С„РѕСЂРјР°С‚Рµ:\n<code>РЎРРњР’РћР› Р¦Р•РќРђ РќРђРџР РђР’Р›Р•РќРР•</code>\n\nРџСЂРёРјРµСЂС‹:\n<code>BTCUSDT 50000 Р’Р«РЁР•</code>\n<code>ETHUSDT 3000 РќРР–Р•</code>", {"parse_mode": "HTML"})
        return
    
    if text == "рџ“‹ РЎРџРРЎРћРљ РђР›Р•Р РўРћР’":
        active = [a for a in price_alerts if not a.get("triggered", False)]
        if not active:
            send_telegram("рџ”” РќРµС‚ Р°РєС‚РёРІРЅС‹С… Р°Р»РµСЂС‚РѕРІ", get_alerts_keyboard())
            return
        msg = "рџ”” <b>РђРљРўРР’РќР«Р• РђР›Р•Р РўР«</b>\n\n"
        for a in active:
            msg += f"#{a['id']} {a['symbol']}: {'в‰Ґ' if a['above'] else 'в‰¤'} ${a['target']}\n"
        send_telegram(msg, get_alerts_keyboard())
        return
    
    if text == "рџ—‘ РЈР”РђР›РРўР¬ Р’РЎР•":
        price_alerts.clear()
        send_telegram("рџ—‘ <b>Р’СЃРµ Р°Р»РµСЂС‚С‹ СѓРґР°Р»РµРЅС‹</b>", get_alerts_keyboard())
        return
    
    # ==================== РђРќРђР›РРўРРљРђ ====================
    if text == "рџ“Љ RSI":
        send_telegram("рџ“Љ <b>RSI РРќР”РРљРђРўРћР </b>\n\nР’РІРµРґРёС‚Рµ СЃРёРјРІРѕР» РјРѕРЅРµС‚С‹, РЅР°РїСЂРёРјРµСЂ: BTCUSDT", {"force_reply": True})
        return
    
    if text == "рџ“€ MACD":
        send_telegram("рџ“€ <b>MACD РРќР”РРљРђРўРћР </b>\n\nР’РІРµРґРёС‚Рµ СЃРёРјРІРѕР» РјРѕРЅРµС‚С‹, РЅР°РїСЂРёРјРµСЂ: BTCUSDT", {"force_reply": True})
        return
    
    if text == "рџ§  FEAR & GREED":
        fg = get_fear_greed_index()
        status = "рџ”ґ Extreme Fear" if fg < 25 else "рџџЎ Fear" if fg < 45 else "вљЄ Neutral" if fg < 55 else "рџџЎ Greed" if fg < 75 else "рџџў Extreme Greed"
        send_telegram(f"рџ§  <b>FEAR & GREED INDEX</b>\n\nР—РЅР°С‡РµРЅРёРµ: {fg}\nРЎС‚Р°С‚СѓСЃ: {status}", get_analytics_keyboard())
        return
    
    if text == "рџЏ† РўРћРџ 10":
        msg = "рџЏ† <b>РўРћРџ 10 РњРћРќР•Рў РџРћ РћР‘РЄР•РњРЈ</b>\n\n"
        for i, coin in enumerate(COINS[:10], 1):
            price = get_price(coin)
            if price > 0:
                msg += f"{i}. {coin}: ${price:.2f}\n"
        send_telegram(msg, get_analytics_keyboard())
        return
    
    # ==================== РџРћРњРћР©Р¬ Р Р’РћР—Р’Р РђРў ====================
    if text == "рџ“± РџРћРњРћР©Р¬":
        msg = """рџ“‹ <b>РџРћРњРћР©Р¬</b>

<b>рџ“Љ РРќР¤РћР РњРђР¦РРЇ</b>
вЂў РЎС‚Р°С‚СѓСЃ - С‚РµРєСѓС‰РµРµ СЃРѕСЃС‚РѕСЏРЅРёРµ Р±РѕС‚Р°
вЂў Р‘Р°Р»Р°РЅСЃ - РІР°С€ USDT Р±Р°Р»Р°РЅСЃ
вЂў РџСЂРёР±С‹Р»СЊ - РѕР±С‰Р°СЏ РїСЂРёР±С‹Р»СЊ
вЂў РџРѕР·РёС†РёРё - РѕС‚РєСЂС‹С‚С‹Рµ СЃРґРµР»РєРё
вЂў РСЃС‚РѕСЂРёСЏ - Р·Р°РєСЂС‹С‚С‹Рµ СЃРґРµР»РєРё
вЂў РЎРёРіРЅР°Р»С‹ - AI СЂРµРєРѕРјРµРЅРґР°С†РёРё

<b>вљЎ РЈРџР РђР’Р›Р•РќРР•</b>
вЂў РђРІС‚РѕРїРёР»РѕС‚ - Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєР°СЏ С‚РѕСЂРіРѕРІР»СЏ
вЂў DCA - СѓСЃСЂРµРґРЅРµРЅРёРµ РїРѕР·РёС†РёР№
вЂў Paper - Р±СѓРјР°Р¶РЅС‹Р№ СЂРµР¶РёРј (Р±РµР· СЂРёСЃРєР°)
вЂў Р—Р°РєСЂС‹С‚СЊ РІСЃС‘ - Р·Р°РєСЂС‹С‚СЊ РІСЃРµ РїРѕР·РёС†РёРё

<b>рџ“Љ GRID</b>
вЂў РЎРµС‚РѕС‡РЅР°СЏ С‚РѕСЂРіРѕРІР»СЏ РІ РґРёР°РїР°Р·РѕРЅРµ

<b>рџ”” РђР›Р•Р РўР«</b>
вЂў РЈРІРµРґРѕРјР»РµРЅРёСЏ Рѕ РґРѕСЃС‚РёР¶РµРЅРёРё С†РµРЅС‹

<b>рџ”§ РќРђРЎРўР РћР™РљР</b>
вЂў РР·РјРµРЅРµРЅРёРµ СЃС‚РѕРї-Р»РѕСЃСЃР°, С‚РµР№Рє-РїСЂРѕС„РёС‚Р° Рё РґСЂ.

рџ“± <b>Telegram:</b> @Р±РѕС‚
рџЊђ <b>Р’РµР±:</b> http://localhost:5002"""
        send_telegram(msg, get_main_keyboard())
        return
    
    if text == "рџ”™ Р“Р›РђР’РќРћР• РњР•РќР®":
        send_telegram("рџ”™ <b>Р“Р›РђР’РќРћР• РњР•РќР®</b>", get_main_keyboard())
        return
    
    # ==================== РћР‘Р РђР‘РћРўРљРђ Р’Р’РћР”Рђ ====================
    # РџСЂРѕР±СѓРµРј РїСЂРµРѕР±СЂР°Р·РѕРІР°С‚СЊ РІ С‡РёСЃР»Рѕ РґР»СЏ РЅР°СЃС‚СЂРѕРµРє
    try:
        value = float(text)
        # Р•СЃР»Рё РѕР¶РёРґР°РµРј СЃС‚РѕРї-Р»РѕСЃСЃ
        if hasattr(handle_telegram_command, 'waiting_for') and handle_telegram_command.waiting_for == 'stop_loss':
            STOP_LOSS = value
            send_telegram(f"вњ… РЎС‚РѕРї-Р»РѕСЃСЃ СѓСЃС‚Р°РЅРѕРІР»РµРЅ РЅР° {STOP_LOSS}%", get_settings_keyboard())
            handle_telegram_command.waiting_for = None
        elif hasattr(handle_telegram_command, 'waiting_for') and handle_telegram_command.waiting_for == 'take_profit':
            TAKE_PROFIT = value
            send_telegram(f"вњ… РўРµР№Рє-РїСЂРѕС„РёС‚ СѓСЃС‚Р°РЅРѕРІР»РµРЅ РЅР° {TAKE_PROFIT}%", get_settings_keyboard())
            handle_telegram_command.waiting_for = None
        elif hasattr(handle_telegram_command, 'waiting_for') and handle_telegram_command.waiting_for == 'daily_loss':
            DAILY_LOSS_LIMIT = value
            send_telegram(f"вњ… Р”РЅРµРІРЅРѕР№ Р»РёРјРёС‚ СѓСЃС‚Р°РЅРѕРІР»РµРЅ РЅР° ${DAILY_LOSS_LIMIT}", get_settings_keyboard())
            handle_telegram_command.waiting_for = None
        else:
            send_telegram("вќЊ РќРµРёР·РІРµСЃС‚РЅР°СЏ РєРѕРјР°РЅРґР°. РСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРЅРѕРїРєРё РјРµРЅСЋ.", get_main_keyboard())
    except ValueError:
        send_telegram("вќЊ РќРµРёР·РІРµСЃС‚РЅР°СЏ РєРѕРјР°РЅРґР°. РСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРЅРѕРїРєРё РјРµРЅСЋ.", get_main_keyboard())

def get_telegram_updates():
    global telegram_offset
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        params = {"offset": telegram_offset, "timeout": 30}
        r = requests.get(url, params=params, timeout=35)
        if r.status_code == 200 and r.json().get("ok"):
            for update in r.json().get("result", []):
                telegram_offset = update["update_id"] + 1
                if "message" in update:
                    msg = update["message"]
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "")
                    if str(chat_id) == TELEGRAM_CHAT_ID:
                        handle_telegram_command(text, chat_id)
    except Exception as e:
        print(f"Telegram getUpdates error: {e}")

# ============================================================
# Р’Р•Р‘-РРќРўР•Р Р¤Р•Р™РЎ (СЃ С‚Р°Р±Р»РёС†РµР№ РјРѕРЅРµС‚)
# ============================================================

app = Flask(__name__)
CORS(app)

HTML = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>рџ¤– TRADING TERMINAL v21.0</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; color: #0f0; font-family: 'Consolas', monospace; padding: 20px; }
        .header { text-align: center; border: 2px solid #0f0; border-radius: 15px; padding: 20px; margin-bottom: 20px; background: linear-gradient(135deg, #0a0a0a, #1a1a2e); }
        .header h1 { font-size: 28px; }
        .dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .stat-card { background: #111; border: 1px solid #333; border-radius: 12px; padding: 15px; text-align: center; cursor: pointer; transition: 0.3s; }
        .stat-card:hover { border-color: #0f0; transform: translateY(-3px); background: #1a1a1a; }
        .stat-card .label { font-size: 11px; color: #888; text-transform: uppercase; }
        .stat-card .value { font-size: 28px; font-weight: bold; margin-top: 8px; }
        .profit { color: #0f0; }
        .loss { color: #f00; }
        .btn-group { display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; margin-bottom: 20px; }
        .btn { background: #1a1a1a; border: 1px solid #333; color: #0f0; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-family: monospace; transition: 0.2s; }
        .btn:hover { background: #0f0; color: #000; border-color: #0f0; }
        .btn-danger { border-color: #f00; color: #f00; }
        .btn-danger:hover { background: #f00; color: #fff; }
        .tabs { display: flex; gap: 5px; margin-bottom: 20px; flex-wrap: wrap; border-bottom: 1px solid #333; padding-bottom: 10px; }
        .tab { background: #1a1a1a; border: 1px solid #333; color: #0f0; padding: 10px 20px; border-radius: 8px 8px 0 0; cursor: pointer; transition: 0.2s; }
        .tab:hover, .tab.active { background: #0f0; color: #000; border-color: #0f0; }
        .trading-panel { background: #0d0d0d; border: 2px solid #0f0; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
        .trade-form { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; justify-content: center; }
        select, input { background: #1a1a1a; border: 1px solid #333; color: #0f0; padding: 10px; border-radius: 8px; font-family: monospace; outline: none; }
        select:focus, input:focus { border-color: #0f0; }
        .section { background: #111; border: 1px solid #333; border-radius: 12px; margin-bottom: 20px; overflow: hidden; }
        .section-header { background: #1a1a1a; padding: 12px 20px; font-weight: bold; cursor: pointer; }
        .section-content { padding: 15px; max-height: 500px; overflow-y: auto; display: none; }
        .section-content.active { display: block; }
        table { width: 100%; border-collapse: collapse; font-size: 12px; }
        th, td { padding: 10px 8px; text-align: left; border-bottom: 1px solid #222; }
        th { background: #0d0d0d; color: #0f0; position: sticky; top: 0; }
        tr:hover { background: #1a1a1a; }
        .signal-buy { color: #0f0; font-weight: bold; }
        .change-positive { color: #0f0; }
        .change-negative { color: #f00; }
        .rsi-low { color: #0f0; }
        .rsi-high { color: #f00; }
        .search-box { display: flex; gap: 10px; margin-bottom: 15px; }
        .search-box input { flex: 1; }
        .logs-panel { background: #000; height: 250px; overflow-y: auto; padding: 10px; font-size: 11px; }
        .log-entry { color: #888; border-bottom: 1px solid #111; padding: 5px 0; }
        .log-entry.buy { color: #0f0; }
        .log-entry.sell { color: #ff0; }
        .log-entry.error { color: #f00; }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #111; }
        ::-webkit-scrollbar-thumb { background: #333; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #0f0; }
        @media (max-width: 768px) { body { padding: 10px; } th, td { padding: 6px 4px; font-size: 10px; } .stat-card .value { font-size: 18px; } .btn { padding: 6px 12px; font-size: 11px; } }
    </style>
</head>
<body>
<div class="header">
    <h1>рџ¤– TRADING TERMINAL <span style="color:#ff0;">v21.0</span></h1>
    <p>рџ”ђ DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO</p>
    <p>AI | DCA | GRID | PAPER | Telegram РјРµРЅСЋ | 100+ РјРѕРЅРµС‚</p>
</div>

<div class="dashboard" id="dashboard"></div>

<div class="btn-group">
    <button class="btn" onclick="toggleAuto()">рџЋ® РђРІС‚РѕРїРёР»РѕС‚</button>
    <button class="btn btn-danger" onclick="closeAll()">рџ”ґ Р—Р°РєСЂС‹С‚СЊ РІСЃС‘</button>
    <button class="btn" onclick="forceScan()">рџ”„ РЎРєР°РЅ</button>
    <button class="btn" onclick="exportData()">рџ’ѕ Р­РєСЃРїРѕСЂС‚ CSV</button>
</div>

<div class="trading-panel">
    <div class="trade-form">
        <select id="buyCoin" style="min-width:150px"></select>
        <input type="number" id="buyAmount" placeholder="РЎСѓРјРјР° USDT" value="10" min="3">
        <button class="btn" onclick="manualBuy()">вњ… РљРЈРџРРўР¬</button>
        <button class="btn btn-danger" onclick="manualSell()">рџ”ґ РџР РћР”РђРўР¬</button>
        <input type="number" id="alertPrice" placeholder="Р¦РµРЅР° Р°Р»РµСЂС‚Р°" style="width:100px">
        <button class="btn" onclick="addAlert()">рџ”” Р”РѕР±Р°РІРёС‚СЊ</button>
    </div>
</div>

<div class="tabs">
    <div class="tab active" onclick="showTab('positions')">рџ’ј РџРћР—РР¦РР</div>
    <div class="tab" onclick="showTab('allCoins')">рџ“€ Р’РЎР• РњРћРќР•РўР« (100+)</div>
    <div class="tab" onclick="showTab('signals')">рџЋЇ AI РЎРР“РќРђР›Р«</div>
    <div class="tab" onclick="showTab('history')">рџ“њ РРЎРўРћР РРЇ</div>
    <div class="tab" onclick="showTab('alerts')">рџ”” РђР›Р•Р РўР«</div>
    <div class="tab" onclick="showTab('logs')">рџ“ќ Р›РћР“Р</div>
</div>

<div id="positionsTab" class="section-content active">
    <div class="section"><div class="section-header">рџ’ј РћРўРљР Р«РўР«Р• РџРћР—РР¦РР</div><div class="section-content active"><table id="positionsTable"><thead><tr><th>РњРћРќР•РўРђ</th><th>Р’РҐРћР”</th><th>РўР•РљРЈР©РђРЇ</th><th>РџР РР‘Р«Р›Р¬ %</th><th>РџР РР‘Р«Р›Р¬ $</th><th>DCA</th><th>Р”Р•Р™РЎРўР’РРЇ</th></tr></thead><tbody id="positionsBody"></tbody></table></div></div>
</div>

<div id="allCoinsTab" class="section-content">
    <div class="section"><div class="section-header">рџ“€ Р’РЎР• РњРћРќР•РўР« (100+)</div><div class="section-content active"><div class="search-box"><input type="text" id="coinSearch" placeholder="рџ”Ќ РџРѕРёСЃРє РјРѕРЅРµС‚С‹..." onkeyup="filterCoins()"><select id="signalFilter" onchange="filterCoins()"><option value="all">Р’СЃРµ СЃРёРіРЅР°Р»С‹</option><option value="BUY">РўРѕР»СЊРєРѕ BUY</option><option value="HOLD">РўРѕР»СЊРєРѕ HOLD</option></select></div><div style="overflow-x: auto; max-height: 500px;"><table id="allCoinsTable"><thead><tr><th>#</th><th>РњРћРќР•РўРђ</th><th>Р¦Р•РќРђ</th><th>24h %</th><th>HIGH</th><th>LOW</th><th>RSI</th><th>РЎРР“РќРђР›</th><th>SCORE</th><th>Р”Р•Р™РЎРўР’РРЇ</th></tr></thead><tbody id="allCoinsBody"></tbody></table></div></div></div>
</div>

<div id="signalsTab" class="section-content">
    <div class="section"><div class="section-header">рџЋЇ AI РЎРР“РќРђР›Р« BUY (С‚РѕРї 30)</div><div class="section-content active"><table id="signalsTable"><thead><tr><th>#</th><th>РњРћРќР•РўРђ</th><th>SCORE</th><th>RSI</th><th>Р¦Р•РќРђ</th><th>24h %</th><th>РџР РР§РРќР«</th><th>Р”Р•Р™РЎРўР’РРЇ</th></tr></thead><tbody id="signalsBody"></tbody></table></div></div>
</div>

<div id="historyTab" class="section-content">
    <div class="section"><div class="section-header">рџ“њ РРЎРўРћР РРЇ РЎР”Р•Р›РћРљ</div><div class="section-content active"><table id="historyTable"><thead><tr><th>Р’Р Р•РњРЇ</th><th>РњРћРќР•РўРђ</th><th>РўРРџ</th><th>Р¦Р•РќРђ</th><th>РџР РР‘Р«Р›Р¬ %</th><th>РџР РР‘Р«Р›Р¬ $</th><th>PAPER</th></tr></thead><tbody id="historyBody"></tbody></table></div></div>
</div>

<div id="alertsTab" class="section-content">
    <div class="section"><div class="section-header">рџ”” РђРљРўРР’РќР«Р• РђР›Р•Р РўР«</div><div class="section-content active"><div id="alertsList" style="background:#0d0d0d; border-radius:10px; padding:15px;"></div><button class="btn btn-danger" onclick="clearAlerts()" style="margin-top:10px">рџ—‘ РЈРґР°Р»РёС‚СЊ РІСЃРµ Р°Р»РµСЂС‚С‹</button></div></div>
</div>

<div id="logsTab" class="section-content">
    <div class="section"><div class="section-header">рџ“ќ Р›РћР“Р РЎРћР‘Р«РўРР™</div><div class="logs-panel" id="logsPanel"></div></div>
</div>

<script>
let allCoinsData = [];

async function apiCall(e,m='GET',d=null){const o={method:m};if(d){o.headers={'Content-Type':'application/json'};o.body=JSON.stringify(d);}return await fetch(e,o).then(r=>r.json());}

function showTab(t){const tabs=['positionsTab','allCoinsTab','signalsTab','historyTab','alertsTab','logsTab'];tabs.forEach(ta=>document.getElementById(ta).classList.remove('active'));document.getElementById(t+'Tab').classList.add('active');document.querySelectorAll('.tab').forEach(ta=>ta.classList.remove('active'));event.target.classList.add('active');}

async function refreshData(){
    const d=await apiCall('/api/data');
    document.getElementById('dashboard').innerHTML=`<div class="stat-card"><div class="label">рџ’° Р‘РђР›РђРќРЎ</div><div class="value">$${d.balance}</div></div><div class="stat-card profit"><div class="label">рџ“€ РџР РР‘Р«Р›Р¬</div><div class="value">${d.total_profit>=0?'+':''}$${d.total_profit}</div></div><div class="stat-card"><div class="label">рџ“Љ РџРћР—РР¦РР</div><div class="value">${d.positions_count}/${d.max_positions}</div></div><div class="stat-card"><div class="label">рџ¤– РђР’РўРћРџРР›РћРў</div><div class="value">${d.auto_pilot?'вњ… Р’РљР›':'вќЊ Р’Р«РљР›'}</div></div><div class="stat-card"><div class="label">рџџў BUY</div><div class="value">${d.buy_signals}</div></div><div class="stat-card"><div class="label">рџ§  F&G</div><div class="value">${d.fear_greed}</div></div>`;
    
    let posHtml='';for(let p of d.positions){const cls=p.profit_pct>=0?'profit':'loss';posHtml+=`<tr><td><b>${p.symbol}</b></td>.html$${p.entry_price}</td>.html$${p.current_price}</td><td class="${cls}">${p.profit_pct>=0?'+':''}${p.profit_pct}%</td><td class="${cls}">${p.profit_usd>=0?'+':''}$${p.profit_usd}</td><td>${p.dca_count}/3</td><td><button class="btn" onclick="sellCoin('${p.symbol}')" style="padding:3px 8px">РџСЂРѕРґР°С‚СЊ</button></td></tr>`;}
    document.getElementById('positionsBody').innerHTML=posHtml||'<tr><td colspan="7">рџ“­ РќРµС‚ РѕС‚РєСЂС‹С‚С‹С… РїРѕР·РёС†РёР№</td></tr>';
    
    allCoinsData=d.all_coins;filterCoins();
    
    let sigHtml='';for(let i=0;i<d.signals.length;i++){const s=d.signals[i];sigHtml+=`<tr><td>${i+1}</td><td><b>${s.symbol}</b></td><td class="signal-buy">${s.score}%</td><td class="${s.rsi<35?'rsi-low':(s.rsi>70?'rsi-high':'rsi-mid')}">${s.rsi}</td><td>$${s.price}</td><td class="${s.change>=0?'change-positive':'change-negative'}">${s.change>=0?'+':''}${s.change}%</td><td style="font-size:10px">${s.reasons}</td><td><button class="btn" onclick="quickBuy('${s.symbol}')" style="padding:3px 8px">РљСѓРїРёС‚СЊ</button></td></tr>`;}
    document.getElementById('signalsBody').innerHTML=sigHtml||'<tr><td colspan="8">рџџў РќРµС‚ СЃРёРіРЅР°Р»РѕРІ BUY</td></tr>';
    
    let histHtml='';for(let h of d.history.slice(0,30)){const cls=h.profit_usd>=0?'profit':'loss';histHtml+=`<tr><td>${h.time}</td><td><b>${h.symbol}</b></td><td>${h.side}</td><td>$${h.price}</td><td class="${cls}">${h.profit_pct>=0?'+':''}${h.profit_pct}%</td><td class="${cls}">${h.profit_usd>=0?'+':''}$${h.profit_usd}</td><td>${h.paper?'вњ…':'вќЊ'}</td></tr>`;}
    document.getElementById('historyBody').innerHTML=histHtml||'<tr><td colspan="7">рџ“­ РќРµС‚ РёСЃС‚РѕСЂРёРё СЃРґРµР»РѕРє</td></tr>';
    
    let alertsHtml='';for(let a of d.alerts){alertsHtml+=`<div style="padding:10px; border-bottom:1px solid #333;">рџ”” #${a.id} ${a.symbol}: ${a.above?'в‰Ґ':'в‰¤'} $${a.target} ${a.triggered?'вњ…':'вЏі'}<br><small>РЎРѕР·РґР°РЅ: ${a.created_str}</small></div>`;}
    document.getElementById('alertsList').innerHTML=alertsHtml||'<div style="padding:15px; text-align:center;">рџ”” РќРµС‚ Р°РєС‚РёРІРЅС‹С… Р°Р»РµСЂС‚РѕРІ</div>';
    
    let logsHtml='';for(let l of d.logs.slice(0,50)){let cls='log-entry';if(l.msg.includes('РџРћРљРЈРџРљРђ')) cls+=' buy';if(l.msg.includes('РўСЂРµР№Р»РёРЅРі')||l.msg.includes('РџР РћР”РђР–Рђ')) cls+=' sell';if(l.msg.includes('РћС€РёР±РєР°')) cls+=' error';logsHtml+=`<div class="${cls}">[${l.time}] ${l.msg}</div>`;}
    document.getElementById('logsPanel').innerHTML=logsHtml;
    
    const sel=document.getElementById('buyCoin');sel.innerHTML='<option>Р’С‹Р±РµСЂРёС‚Рµ...</option>';for(let c of d.coins.slice(0,50)){sel.innerHTML+=`<option value="${c.symbol}">${c.symbol} - $${c.price}</option>`;}
}

function filterCoins(){
    const s=document.getElementById('coinSearch').value.toLowerCase();
    const f=document.getElementById('signalFilter').value;
    let filtered=allCoinsData.filter(c=>c.symbol.toLowerCase().includes(s));
    if(f!=='all')filtered=filtered.filter(c=>c.signal===f);
    let html='';for(let i=0;i<filtered.length;i++){const c=filtered[i];const changeClass=c.change>=0?'change-positive':'change-negative';const rsiClass=c.rsi<35?'rsi-low':(c.rsi>70?'rsi-high':'rsi-mid');html+=`<tr><td>${i+1}</td><td><b>${c.symbol}</b></td><td>$${c.price}</td><td class="${changeClass}">${c.change>=0?'+':''}${c.change}%</td><td>$${c.high}</td><td>$${c.low}</td><td class="${rsiClass}">${c.rsi}</td><td class="${c.signal=='BUY'?'signal-buy':''}">${c.signal=='BUY'?'рџџў BUY':'вљЄ HOLD'}</td><td>${c.score}%</td><td>${c.signal=='BUY'?`<button class="btn" onclick="quickBuy('${c.symbol}')" style="padding:3px 8px">РљСѓРїРёС‚СЊ</button>`:'-'}</td></tr>`;}
    document.getElementById('allCoinsBody').innerHTML=html||'<tr><td colspan="10">рџ“­ РќРµС‚ РґР°РЅРЅС‹С…</td></tr>';
}

async function toggleAuto(){await apiCall('/api/toggle_auto','POST');refreshData();}
async function closeAll(){await apiCall('/api/close_all','POST');refreshData();}
async function forceScan(){await apiCall('/api/scan','POST');refreshData();}
async function exportData(){window.open('/api/export','_blank');}
async function addAlert(){const s=document.getElementById('buyCoin').value;const p=parseFloat(document.getElementById('alertPrice').value);if(!s||isNaN(p)){alert('Р’С‹Р±РµСЂРёС‚Рµ РјРѕРЅРµС‚Сѓ Рё С†РµРЅСѓ');return;}await apiCall('/api/add_alert','POST',{symbol:s,price:p});refreshData();}
async function clearAlerts(){await apiCall('/api/clear_alerts','POST');refreshData();}
async function manualBuy(){const s=document.getElementById('buyCoin').value;const a=parseFloat(document.getElementById('buyAmount').value);if(!s||s=='Р’С‹Р±РµСЂРёС‚Рµ...'){alert('Р’С‹Р±РµСЂРёС‚Рµ РјРѕРЅРµС‚Сѓ');return;}if(isNaN(a)||a<3){alert('РЎСѓРјРјР° РѕС‚ 3');return;}const r=await apiCall('/api/manual_buy','POST',{symbol:s,amount:a});if(r.success)alert('вњ… РљСѓРїР»РµРЅРѕ');else alert('вќЊ РћС€РёР±РєР°');refreshData();}
async function manualSell(){const s=document.getElementById('buyCoin').value;if(!s||s=='Р’С‹Р±РµСЂРёС‚Рµ...'){alert('Р’С‹Р±РµСЂРёС‚Рµ РјРѕРЅРµС‚Сѓ');return;}await apiCall('/api/sell','POST',{symbol:s});refreshData();}
async function quickBuy(s){const a=parseFloat(prompt('РЎСѓРјРјР° USDT:','10'));if(!a||a<3)return;const r=await apiCall('/api/manual_buy','POST',{symbol:s,amount:a});if(r.success)alert('вњ… РљСѓРїР»РµРЅРѕ');refreshData();}
async function sellCoin(s){await apiCall('/api/sell','POST',{symbol:s});refreshData();}
setInterval(refreshData,3000);refreshData();
</script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/data')
def api_data():
    buy = [(s, d) for s, d in signals.items() if d["signal"] == "BUY"]
    buy.sort(key=lambda x: x[1]["score"], reverse=True)
    pos_data = []
    for p in positions:
        price = get_price(p["symbol"])
        if price > 0:
            profit = (price - p["entry_price"]) / p["entry_price"] * 100
            profit_usd = p["invested"] * profit / 100
            pos_data.append({"symbol": p["symbol"], "entry_price": round(p["entry_price"], 4),
                             "current_price": round(price, 4), "profit_pct": round(profit, 2),
                             "profit_usd": round(profit_usd, 2), "dca_count": p.get("dca_count", 0)})
    all_coins = []
    for coin in COINS:
        data = signals.get(coin, {"signal": "HOLD", "score": 0, "price": 0, "rsi": 50, "change": 0, "high": 0, "low": 0})
        all_coins.append({"symbol": coin, "price": data["price"], "change": data.get("change", 0),
                          "high": data.get("high", 0), "low": data.get("low", 0), "rsi": data["rsi"],
                          "signal": data["signal"], "score": data["score"]})
    all_coins.sort(key=lambda x: (0 if x["signal"] == "BUY" else 1, -x["score"]))
    return jsonify({
        "balance": round(balance, 2), "total_profit": round(total_profit, 2),
        "positions_count": len(positions), "max_positions": MAX_POSITIONS,
        "auto_pilot": auto_pilot, "buy_signals": len(buy), "fear_greed": get_fear_greed_index(),
        "paper_mode": TRADING_MODE == "PAPER", "signals": [{"symbol": s[0], "score": s[1]["score"],
        "rsi": s[1]["rsi"], "price": s[1]["price"], "change": s[1].get("change", 0),
        "reasons": ", ".join(s[1].get("reasons", [])[:2])} for s in buy[:30]],
        "positions": pos_data, "all_coins": all_coins[:50], "history": history[:50],
        "logs": logs[:100], "alerts": price_alerts,
        "coins": [{"symbol": c, "price": signals.get(c, {}).get("price", 0)} for c in COINS[:50]]
    })

@app.route('/api/toggle_auto', methods=['POST'])
def api_toggle_auto():
    global auto_pilot
    auto_pilot = not auto_pilot
    return jsonify({"auto_pilot": auto_pilot})

@app.route('/api/close_all', methods=['POST'])
def api_close_all():
    global balance
    for p in positions[:]:
        market_sell(p["symbol"], p["quantity"])
        balance += p["invested"]
    positions.clear()
    return jsonify({"success": True})

@app.route('/api/scan', methods=['POST'])
def api_scan():
    update_signals()
    return jsonify({"success": True})

@app.route('/api/export')
def api_export():
    return send_file(export_to_csv(), as_attachment=True)

@app.route('/api/add_alert', methods=['POST'])
def api_add_alert():
    data = request.get_json()
    symbol = data.get("symbol")
    price = float(data.get("price", 0))
    if symbol and price > 0:
        add_price_alert(symbol, price, True)
    return jsonify({"success": True})

@app.route('/api/clear_alerts', methods=['POST'])
def api_clear_alerts():
    global price_alerts
    price_alerts = []
    return jsonify({"success": True})

@app.route('/api/manual_buy', methods=['POST'])
def api_manual_buy():
    global balance
    data = request.get_json()
    symbol = data.get("symbol")
    amount = float(data.get("amount", 0))
    if amount < MIN_TRADE_USD:
        return jsonify({"success": False})
    price = get_price(symbol)
    if price <= 0:
        return jsonify({"success": False})
    success, actual = market_buy(symbol, amount)
    if success:
        if TRADING_MODE == "PAPER":
            paper_balance -= actual
            paper_positions.append({"symbol": symbol, "entry_price": price, "invested": actual,
                                    "quantity": actual/price, "entry_time": time.time(),
                                    "peak_price": price, "peak_profit": 0, "dca_count": 0})
        else:
            balance -= actual
            positions.append({"symbol": symbol, "entry_price": price, "invested": actual,
                              "quantity": actual/price, "entry_time": time.time(),
                              "peak_price": price, "peak_profit": 0, "dca_count": 0})
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/api/sell', methods=['POST'])
def api_sell():
    global balance, total_profit
    data = request.get_json()
    symbol = data.get("symbol")
    for p in positions[:]:
        if p["symbol"] == symbol:
            price = get_price(symbol)
            if market_sell(symbol, p["quantity"]):
                profit_usd = (price - p["entry_price"]) / p["entry_price"] * p["invested"]
                balance += p["invested"] + profit_usd
                total_profit += profit_usd
                positions.remove(p)
                return jsonify({"success": True})
    return jsonify({"success": False})


# ============================================================
# Р—РђРџРЈРЎРљ
# ============================================================

def telegram_thread():
    global running
    while running:
        try:
            get_telegram_updates()
            time.sleep(2)
        except:
            time.sleep(5)

def alert_thread():
    global running
    while running:
        try:
            check_price_alerts()
            time.sleep(5)
        except:
            time.sleep(5)

def grid_thread():
    global running
    while running:
        try:
            grid_trading.update_all_grids()
            time.sleep(5)
        except:
            time.sleep(5)

def arbitrage_thread():
    global running
    while running:
        try:
            if ARBITRAGE_ENABLED:
                check_arbitrage_opportunities()
            time.sleep(30)
        except:
            time.sleep(30)

def console_handler():
    global running, auto_pilot
    while running:
        try:
            if sys.stdin.isatty():
                cmd = sys.stdin.read(1).lower()
                if cmd == 'a':
                    auto_pilot = not auto_pilot
                    print(f"\nвњ… РђРІС‚РѕРїРёР»РѕС‚: {'Р’РљР›' if auto_pilot else 'Р’Р«РљР›'}")
                elif cmd == 'c':
                    for p in positions[:]:
                        market_sell(p["symbol"], p["quantity"])
                    positions.clear()
                    print("\nрџ”ґ Р’СЃРµ РїРѕР·РёС†РёРё Р·Р°РєСЂС‹С‚С‹")
                elif cmd == 's':
                    update_signals()
                    print("\nрџ”„ РЎРёРіРЅР°Р»С‹ РѕР±РЅРѕРІР»РµРЅС‹")
                elif cmd == 'r':
                    send_telegram(f"РћС‚С‡РµС‚\nрџ’° Р‘Р°Р»Р°РЅСЃ: ${balance:.2f}")
                    print("\nрџ“Љ РћС‚С‡РµС‚ РѕС‚РїСЂР°РІР»РµРЅ")
                elif cmd == 't':
                    send_telegram(f"РўРµСЃС‚\nрџ’° Р‘Р°Р»Р°РЅСЃ: ${balance:.2f}")
                    print("\nрџ“± РўРµСЃС‚ РѕС‚РїСЂР°РІР»РµРЅ")
                elif cmd == 'p':
                    print(f"\nрџ’ј РџРћР—РР¦РР ({len(positions)}):")
                    for p in positions:
                        price = get_price(p["symbol"])
                        if price > 0:
                            profit = (price - p["entry_price"]) / p["entry_price"] * 100
                            print(f"   {p['symbol']}: {profit:+.2f}%")
                elif cmd == 'q':
                    running = False
                time.sleep(0.1)
        except:
            pass

def main():
    global balance, running, start_balance, total_profit, portfolio_peak, paper_balance, TRADING_MODE
    
    ws_manager.start()
    
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False), daemon=True).start()
    threading.Thread(target=console_handler, daemon=True).start()
    threading.Thread(target=telegram_thread, daemon=True).start()
    threading.Thread(target=alert_thread, daemon=True).start()
    threading.Thread(target=grid_thread, daemon=True).start()
    threading.Thread(target=arbitrage_thread, daemon=True).start()
    
    balance = get_balance_mexc()
    start_balance = balance
    portfolio_peak = balance
    paper_balance = 10000
    
    print("\n" + "=" * 70)
    print("   рџ¤– TRADING TERMINAL v21.0 - РџРћР›РќРђРЇ Р’Р•Р РЎРРЇ")
    print("   рџ”ђ DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO")
    print("=" * 70)
    print(f"   рџ’° Р‘РђР›РђРќРЎ: ${balance:.2f}")
    print(f"   рџ“‹ Р Р•Р–РРњ: {TRADING_MODE}")
    print(f"   рџЊђ Р’Р•Р‘: http://localhost:5002")
    print(f"   рџ“± TELEGRAM: РћС‚РїСЂР°РІСЊС‚Рµ /start РґР»СЏ РјРµРЅСЋ")
    print("=" * 70)
    print("рџ“± TELEGRAM РњР•РќР®: /start - РѕС‚РєСЂС‹С‚СЊ РјРµРЅСЋ СЃ РєРЅРѕРїРєР°РјРё")
    print("=" * 70)
    print("вЊЁпёЏ РљРћРќРЎРћР›Р¬: A(РђРІС‚Рѕ) C(Р—Р°РєСЂС‹С‚СЊ) S(РЎРєР°РЅ) R(РћС‚С‡РµС‚) T(РўРµСЃС‚ TG) P(РџРѕР·РёС†РёРё) Q(Р’С‹С…РѕРґ)")
    print("=" * 70)
    
    send_telegram("рџ¤– РўРћР Р“РћР’Р«Р™ РўР•Р РњРРќРђР› v21.0 Р—РђРџРЈР©Р•Рќ!\nвњ… AI | DCA | GRID | PAPER | РђСЂР±РёС‚СЂР°Р¶\nвњ… Telegram РјРµРЅСЋ СЃ РєРЅРѕРїРєР°РјРё\nрџЊђ http://localhost:5002\n\nрџ“± РћС‚РїСЂР°РІСЊС‚Рµ /start РґР»СЏ РѕС‚РєСЂС‹С‚РёСЏ РјРµРЅСЋ", get_main_keyboard())
    
    last_scan = 0
    while running:
        try:
            if TRADING_MODE != "PAPER":
                balance = get_balance_mexc()
            if time.time() - last_scan >= SCAN_INTERVAL:
                update_signals()
                auto_trade()
                last_scan = time.time()
            for p in positions:
                check_dca(p)
            check_sell()
            check_portfolio_stop()
            check_daily_loss()
            time.sleep(2)
        except KeyboardInterrupt:
            running = False
            print("\nрџ›‘ Р‘РѕС‚ РѕСЃС‚Р°РЅРѕРІР»РµРЅ")
        except Exception as e:
            print(f"вќЊ РћС€РёР±РєР°: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
