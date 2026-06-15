# OM Ganeshaya Namah 🙏
# OM Krushnaya Namah 🙏
# OM Lakshmyai Namah 🙏
# OM Saraswatyai Namah 🙏

# python -m PyInstaller --hidden-import=plyer.platforms.win.notification --onefile --icon '.\gann_COI.ico' --add-data "gann_COI.ico;." 

import sys
import os
import csv
import json
import requests
import glob
import logging
import subprocess
import pandas as pd
from datetime import date, datetime, timedelta
from PyQt6.QtWidgets import QInputDialog, QSizePolicy, QApplication, QFrame, QWidget, QComboBox, QVBoxLayout,QTextEdit, QPushButton, QMessageBox,QCheckBox, QScrollArea, QLabel, QLineEdit, QHBoxLayout
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, QDateTime, QTime, Qt, QDate, QRunnable, pyqtSignal, QObject, QThreadPool
import traceback
from PyQt6.QtGui import QFont, QIcon, QPalette
import time
import datetime
import math
import yaml
from pkg_resources import resource_filename
from cryptography.fernet import Fernet
from threading import Thread, Lock
import threading
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws, order_ws

# Patch FYERS websocket symbol conversion to handle auth header changes.
# Some FYERS data endpoints accept raw JWT only, while others may require Bearer prefix.
# This workaround retries both forms and logs the failing response for debugging.

def _fyers_symbol_to_hsmtoken(self, symbols: list):
    data = {"symbols": symbols}
    headers_list = [
        {"Authorization": self.access_token, "Content-Type": "application/json", "Accept": "application/json", "version": "3"},
        {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json", "Accept": "application/json", "version": "3"},
    ]
    last_error = ""
    for headers in headers_list:
        try:
            # Log which Authorization header form we're trying (masking token body)
            try:
                auth_val = headers.get("Authorization", "")
                if isinstance(auth_val, str) and len(auth_val) > 12:
                    auth_masked = f"{auth_val[:6]}...{auth_val[-6:]}"
                else:
                    auth_masked = auth_val or "<empty>"
            except Exception:
                auth_masked = "<error>"
            try:
                log_message(f"[FYERS] SymbolConversion trying Authorization header: {auth_masked}")
            except Exception:
                pass
            response = requests.post(
                url=self.symbols_token_api,
                headers=headers,
                json=data,
                timeout=15,
            )
            status = response.status_code
            response_data = response.json()
            if status == 200 and isinstance(response_data, dict):
                if response_data.get("s") == "ok":
                    datadict = {}
                    file_path = resource_filename('fyers_apiv3.FyersWebsocket', 'map.json')
                    with open(file_path, "r") as file:
                        mapper = json.load(file)
                    index_dict = mapper["index_dict"]
                    exch_seg_dict = mapper["exch_seg_dict"]
                    wrong_symbol = []
                    dp_index_flag = False

                    for symbol, fytoken in response_data.get("validSymbol", {}).items():
                        ex_sg = fytoken[:4]
                        if ex_sg not in exch_seg_dict:
                            continue
                        segment = exch_seg_dict[ex_sg]
                        symbol_split = symbol.split("-")
                        update_dict = True
                        if len(symbol_split) > 1 and symbol_split[-1] == "INDEX" and self.data_type != "DepthUpdate":
                            if symbol in index_dict:
                                exch_token = index_dict[symbol]
                            else:
                                exch_token = symbol.split(":")[1].split("-")[0]
                            hsm_symbol = "if" + "|" + segment + "|" + exch_token
                        elif self.data_type == "DepthUpdate" and symbol_split[-1] != "INDEX":
                            exch_token = fytoken[10:]
                            hsm_symbol = "dp" + "|" + segment + "|" + exch_token
                        elif self.data_type == "SymbolUpdate":
                            exch_token = fytoken[10:]
                            hsm_symbol = "sf" + "|" + segment + "|" + exch_token
                        elif self.data_type == "DepthUpdate" and symbol_split[-1] == "INDEX":
                            update_dict = False
                            dp_index_flag = True

                        if update_dict:
                            datadict[hsm_symbol] = symbol

                    if response_data.get("invalidSymbol"):
                        wrong_symbol = response_data.get("invalidSymbol")
                    return (datadict, wrong_symbol, dp_index_flag, "")

                if response_data.get("s") == "error":
                    last_error = response_data.get("message", str(response_data))
                    continue

            last_error = f"HTTP {status}: {response.text}"
        except Exception as exc:
            last_error = str(exc)

    self.data_logger.error(
        f"SymbolConversion.symbol_to_hsmtoken auth failed for headers {headers_list}: {last_error}"
    )
    # Fallback: try to build mapping from local symbol CSVs present in the adapter
    try:
        datadict = {}
        wrong_symbol = []
        dp_index_flag = False
        try:
            from __main__ import FyersApiAdapter
        except Exception:
            FyersApiAdapter = globals().get('FyersApiAdapter')

        symbol_map = {}
        if FyersApiAdapter and hasattr(FyersApiAdapter, '_symbol_to_token'):
            symbol_map = getattr(FyersApiAdapter, '_symbol_to_token') or {}

        file_path = resource_filename('fyers_apiv3.FyersWebsocket', 'map.json')
        with open(file_path, "r") as file:
            mapper = json.load(file)
        exch_seg_dict = mapper.get("exch_seg_dict", {})

        for symbol in symbols:
            token = symbol_map.get(symbol) or symbol_map.get(symbol.upper()) or symbol_map.get(symbol.replace('NSE:', ''))
            symbol_split = symbol.split("-")
            if token:
                # determine segment from prefix
                seg = "NSE"
                if ":" in symbol:
                    seg = symbol.split(":", 1)[0]
                segment = exch_seg_dict.get(seg, seg)
                if len(symbol_split) > 1 and symbol_split[-1] == "INDEX" and self.data_type != "DepthUpdate":
                    exch_token = token
                    hsm_symbol = "if|" + segment + "|" + exch_token
                elif self.data_type == "DepthUpdate" and symbol_split[-1] != "INDEX":
                    exch_token = token
                    hsm_symbol = "dp|" + segment + "|" + exch_token
                elif self.data_type == "SymbolUpdate":
                    exch_token = token
                    hsm_symbol = "sf|" + segment + "|" + exch_token
                else:
                    exch_token = token
                    hsm_symbol = "sf|" + segment + "|" + exch_token

                datadict[hsm_symbol] = symbol
            else:
                wrong_symbol.append(symbol)

        if datadict:
            return (datadict, wrong_symbol, dp_index_flag, "")
    except Exception as exc:
        # swallow and return original error
        pass

    return ({}, symbols, False, f"Symbol conversion auth failed: {last_error}")


data_ws.SymbolConversion.symbol_to_hsmtoken = _fyers_symbol_to_hsmtoken

import pyqtgraph as pg
from flask import Flask, request
import webbrowser
import queue
from collections import deque
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import nest_asyncio
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from plyer import notification
from typing import Optional, Tuple, Dict, Any, overload, Literal


def get_auth_code_automated(app_id: str, secret_key: str, user: str) -> Optional[str]:
    """
    Automatically get auth code using Flask callback server.
    """
    auth_code_queue = queue.Queue()

    app = Flask(__name__)

    @app.route('/callback')
    def callback():
        auth_code = request.args.get('auth_code')
        if auth_code:
            auth_code_queue.put(auth_code)
            return "Authorization successful! You can close this window."
        else:
            return "Authorization failed: No auth_code received."

    def run_server():
        app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

    # Start Flask server in a thread
    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()

    # Give server time to start
    time.sleep(1)

    # Generate auth URL with correct redirect URI
    session = fyersModel.SessionModel(
        client_id=app_id,
        secret_key=secret_key,
        redirect_uri="http://127.0.0.1:5000/callback",
        response_type="code",
        grant_type="authorization_code"
    )
    auth_url = session.generate_authcode()

    # Open URL in browser
    webbrowser.open(auth_url)

    log_message(f"[FYERS] Opened auth URL for {user}. Waiting for callback...")

    # Wait for auth code with timeout
    try:
        auth_code = auth_code_queue.get(timeout=300)  # 5 minutes timeout
        log_message(f"[FYERS] Received auth code for {user}")
        return auth_code
    except queue.Empty:
        log_message(f"[FYERS] Timeout waiting for auth code for {user}")
        return None


class FyersApiAdapter:
    """
    Compatibility adapter that maps the legacy API calls used in this file
    to FYERS API v3 (REST + WebSocket).
    """
    _symbol_map_loaded = False
    _symbol_to_token: Dict[str, str] = {}
    _token_to_symbol: Dict[str, str] = {}
    _map_lock = Lock()

    def __init__(self, app_id: Optional[str] = None, access_token: Optional[str] = None, log_path: str = ""):
        self.app_id = (app_id or "").strip()
        self.access_token = (access_token or "").strip()
        self.log_path = log_path or ""
        self.client = None
        self.ws_access_token = ""
        self._data_socket = None
        self._order_socket = None
        self._data_thread = None
        self._order_thread = None
        self._subscribe_callback = None
        self._order_update_callback = None
        self._socket_open_callback = None
        self._socket_close_callback = None
        self._socket_error_callback = None
        self._ws_subscribed_symbols = set()
        self._data_type = "SymbolUpdate"
        self._NorenApi__websocket_connected = False  # keep compatibility with existing checks
        self._load_symbol_maps()
        if self.app_id and self.access_token:
            self._build_client()

    # ---------- Symbol Map Helpers ----------
    @classmethod
    def _load_symbol_maps(cls):
        with cls._map_lock:
            if cls._symbol_map_loaded:
                return
            csv_files = [
                "fyers_nse_fno.csv",
                "fyers_nse_equities.csv",
            ]
            for csv_path in csv_files:
                if not os.path.exists(csv_path):
                    continue
                try:
                    with open(csv_path, newline="", encoding="utf-8") as f:
                        reader = csv.reader(f)
                        for row in reader:
                            if len(row) < 10:
                                continue
                            token = str(row[0]).strip()
                            symbol = str(row[9]).strip()
                            if not token or not symbol:
                                continue
                            cls._token_to_symbol[token] = symbol
                            cls._symbol_to_token[symbol] = token
                            if symbol.startswith("NSE:"):
                                cls._symbol_to_token[symbol.replace("NSE:", "")] = token
                            cls._symbol_to_token[symbol.upper()] = token
                except Exception as e:
                    log_message(f"[FYERS] Failed to load symbol map from {csv_path}: {e}")
            cls._symbol_map_loaded = True

    def _normalize_symbol(self, tradingsymbol: str, exchange: Optional[str] = None) -> str:
        if not tradingsymbol:
            return ""
        if ":" in tradingsymbol:
            return tradingsymbol
        # FYERS uses NSE: prefix for NSE/FNO symbols
        return f"NSE:{tradingsymbol}"

    def _strip_exchange(self, symbol: str) -> str:
        if not symbol:
            return ""
        if ":" in symbol:
            return symbol.split(":", 1)[1]
        return symbol

    def _exchange_from_symbol(self, symbol: str) -> str:
        if not symbol or ":" not in symbol:
            return "NSE"
        return symbol.split(":", 1)[0]

    def _token_to_sym(self, token: str) -> Optional[str]:
        if token is None:
            return None
        token = str(token).strip()
        if not token:
            return None
        return self._token_to_symbol.get(token)

    def _sym_to_token(self, symbol: str) -> Optional[str]:
        if not symbol:
            return None
        key = symbol.strip()
        return self._symbol_to_token.get(key) or self._symbol_to_token.get(key.upper())

    # ---------- Client Setup ----------
    def _build_client(self):
        self.client = fyersModel.FyersModel(
            client_id=self.app_id,
            token=self.access_token,
            is_async=False,
            log_path=self.log_path or ""
        )

        # FYERS websocket expects the access token in the format "<app_id>:<access_token>".
        token = str(self.access_token or "").strip()
        if token and ":" not in token:
            token = f"{self.app_id}:{token}"
        self.ws_access_token = token

    def set_credentials(self, app_id: str, access_token: str):
        self.app_id = (app_id or "").strip()
        self.access_token = (access_token or "").strip()
        if self.app_id and self.access_token:
            self._build_client()

    def login(self, **kwargs):
        """
        FYERS uses access_token; accept app_id/access_token via kwargs.
        Returns legacy-style login response dict with stat key.
        """
        app_id = kwargs.get("app_id") or kwargs.get("client_id") or kwargs.get("fyers_app_id") or self.app_id
        access_token = kwargs.get("access_token") or kwargs.get("fyers_access_token") or self.access_token
        if app_id and access_token:
            self.set_credentials(app_id, access_token)

        if not self.client:
            return {"stat": "Not_Ok", "emsg": "Missing FYERS credentials"}

        try:
            prof = self.client.get_profile()
            if prof and prof.get("s") == "ok":
                return {"stat": "Ok", "data": prof.get("data", {})}
            return {"stat": "Not_Ok", "emsg": str(prof)}
        except Exception as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    def logout(self):
        if not self.client:
            return {"stat": "Not_Ok", "emsg": "Not logged in"}
        try:
            return self.client.logout()
        except Exception as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    # ---------- REST API Wrappers ----------
    def get_profile(self):
        return self.client.get_profile() if self.client else None

    def get_limits(self):
        """Map FYERS funds response to legacy limits dict."""
        if not self.client:
            return {}
        try:
            resp = self.client.funds() or {}
            funds = resp.get("fund_limit") or []
            lookup = {str(f.get("title", "")).strip().lower(): f for f in funds if isinstance(f, dict)}

            def _amt(key):
                item = lookup.get(key)
                if not item:
                    return 0.0
                return float(item.get("equityAmount") or 0.0)

            opening = _amt("limit at start of the day") or _amt("limit at start of day")
            cash = _amt("available balance") or _amt("clear balance")
            margin_used = _amt("utilized amount")
            rpnl = _amt("realized profit and loss")

            return {
                "openingbalance": opening,
                "cash": cash,
                "marginused": margin_used,
                "payin": 0.0,
                "payout": 0.0,
                "withdrawreq": 0.0,
                "payoutamt": 0.0,
                "brokerage": 0.0,
                "rpnl": rpnl,
            }
        except Exception as e:
            log_message(f"[FYERS] get_limits error: {e}")
            return {}

    def get_holdings(self, product_type: Optional[str] = None):
        """Map FYERS holdings to legacy holdings used in cashflow logic."""
        if not self.client:
            return []
        try:
            resp = self.client.holdings() or {}
            holdings = resp.get("holdings") or []
            mapped = []
            for h in holdings:
                symbol_full = h.get("symbol") or ""
                tsym = self._strip_exchange(symbol_full)
                qty = int(h.get("remainingQuantity") or h.get("quantity") or 0)
                mapped.append({
                    "holdqty": qty,
                    "btstqty": 0,
                    "brkcolqty": 0,
                    "unplgdqty": 0,
                    "benqty": 0,
                    "dpqty": qty,
                    "npoadqty": 0,
                    "usedqty": 0,
                    "exch_tsym": [{"exch": self._exchange_from_symbol(symbol_full), "tsym": tsym}],
                    "upldprc": float(h.get("costPrice") or 0.0),
                    "ltp": float(h.get("ltp") or 0.0),
                    "symbol": symbol_full,
                })
            return mapped
        except Exception as e:
            log_message(f"[FYERS] get_holdings error: {e}")
            return []

    def get_positions(self):
        if not self.client:
            return []
        try:
            resp = self.client.positions() or {}
            positions = resp.get("positions") or []
            mapped = []
            for p in positions:
                symbol_full = p.get("symbol") or ""
                tsym = self._strip_exchange(symbol_full)
                netqty = int(p.get("netQty") or 0)
                netavg = float(p.get("netAvg") or 0.0)
                ltp = float(p.get("ltp") or 0.0)
                pl = float(p.get("pl") or 0.0)
                rpnl = float(p.get("realized_profit") or p.get("pl_realized") or 0.0)
                urmtom = float(pl - rpnl)
                mapped.append({
                    "tsym": tsym,
                    "netqty": netqty,
                    "netavgprc": netavg,
                    "lp": ltp,
                    "urmtom": urmtom,
                    "rpnl": rpnl,
                    "exch": self._exchange_from_symbol(symbol_full) or "NSE",
                    "side": "BUY" if netqty > 0 else "SELL" if netqty < 0 else "",
                })
            return mapped
        except Exception as e:
            log_message(f"[FYERS] get_positions error: {e}")
            return []

    def get_trade_book(self):
        if not self.client:
            return []
        try:
            resp = self.client.tradebook() or {}
            trades = resp.get("tradeBook") or []
            mapped = []
            for t in trades:
                symbol_full = t.get("symbol") or ""
                tsym = self._strip_exchange(symbol_full)
                side = t.get("side")
                trantype = "B" if str(side) == "1" else "S" if str(side) == "-1" else ""
                order_time = t.get("orderDateTime") or ""
                time_only = ""
                if " " in order_time:
                    time_only = order_time.split(" ", 1)[1]
                mapped.append({
                    "tsym": tsym,
                    "trantype": trantype,
                    "qty": int(t.get("tradedQty") or 0),
                    "price": float(t.get("tradePrice") or 0.0),
                    "norenordno": t.get("orderNumber"),
                    "exch_tm": time_only,
                })
            return mapped
        except Exception as e:
            log_message(f"[FYERS] get_trade_book error: {e}")
            return []

    def get_order_book(self):
        if not self.client:
            return []
        try:
            resp = self.client.orderbook() or {}
            orders = resp.get("orderBook") or []
            mapped = []
            for o in orders:
                status_int = o.get("status")
                status = self._map_order_status(status_int)
                symbol_full = o.get("symbol") or ""
                tsym = self._strip_exchange(symbol_full)
                order_time = o.get("orderDateTime") or ""
                time_only = ""
                if " " in order_time:
                    time_only = order_time.split(" ", 1)[1]
                mapped.append({
                    "norenordno": o.get("id"),
                    "ordstatus": status,
                    "status": status,
                    "qty": int(o.get("qty") or 0),
                    "avgprc": float(o.get("tradedPrice") or 0.0),
                    "prc": float(o.get("limitPrice") or 0.0),
                    "trantype": "B" if str(o.get("side")) == "1" else "S" if str(o.get("side")) == "-1" else "",
                    "tsym": tsym,
                    "exch": self._exchange_from_symbol(symbol_full) or "NSE",
                    "ordtime": time_only,
                })
            return mapped
        except Exception as e:
            log_message(f"[FYERS] get_order_book error: {e}")
            return []

    def get_quotes(self, exchange: str, token: str):
        if not self.client:
            return {}
        try:
            symbol = self._token_to_sym(token) or self._normalize_symbol(str(token), exchange)
            data = {"symbols": symbol}
            resp = self.client.quotes(data=data) or {}
            if resp.get("s") != "ok":
                return {}
            items = resp.get("d") or []
            if not items:
                return {}
            item = items[0]
            v = item.get("v", item)
            ltp = v.get("lp") or v.get("ltp")
            return {
                "lp": float(ltp) if ltp is not None else None,
                "symbol": symbol,
                "tsym": self._strip_exchange(symbol),
                "token": v.get("fyToken") or v.get("fytoken") or self._sym_to_token(symbol),
            }
        except Exception as e:
            log_message(f"[FYERS] get_quotes error: {e}")
            return {}

    def searchscrip(self, exchange: str, searchtext: str):
        """Return a legacy-style search response with token mapping."""
        try:
            symbol = self._normalize_symbol(searchtext, exchange)
            token = self._sym_to_token(symbol) or self._sym_to_token(searchtext)
            if not token:
                return {"stat": "Not_Ok", "values": []}
            return {"stat": "Ok", "values": [{"token": token, "tsym": self._strip_exchange(symbol), "symbol": symbol}]}
        except Exception as e:
            log_message(f"[FYERS] searchscrip error: {e}")
            return {"stat": "Not_Ok", "values": []}

    def get_time_price_series(self, exchange: str, token: str, starttime: Optional[float] = None, interval: int = 1, **kwargs):
        """Map FYERS history API to legacy time_price_series response."""
        if not self.client:
            return []
        try:
            symbol = self._token_to_sym(token) or self._normalize_symbol(str(token), exchange)
            range_from = int(starttime or (time.time() - 86400))
            endtime = kwargs.get("endtime")
            range_to = int(endtime) if endtime is not None else int(time.time())
            data = {
                "symbol": symbol,
                "resolution": str(interval),
                "date_format": 0,
                "range_from": str(range_from),
                "range_to": str(range_to),
                "cont_flag": "0",
                "oi_flag": "0",
            }
            resp = self.client.history(data=data) or {}
            candles = resp.get("candles") or []
            mapped = []
            for c in candles:
                try:
                    ts = int(c[0])
                    dt = datetime.datetime.fromtimestamp(ts)
                    mapped.append({
                        "time": dt.strftime("%d-%m-%Y %H:%M:%S"),
                        "into": float(c[1]),
                        "inth": float(c[2]),
                        "intl": float(c[3]),
                        "intc": float(c[4]),
                        "vol": float(c[5]) if len(c) > 5 else 0.0,
                    })
                except Exception:
                    continue
            return mapped
        except Exception as e:
            log_message(f"[FYERS] get_time_price_series error: {e}")
            return []

    def place_order(self, **kwargs):
        if not self.client:
            return {"stat": "Not_Ok", "emsg": "Not logged in"}
        try:
            buy_or_sell = kwargs.get("buy_or_sell")
            product_type = kwargs.get("product_type")
            exchange = kwargs.get("exchange")
            tradingsymbol = kwargs.get("tradingsymbol")
            quantity = int(kwargs.get("quantity") or 0)
            price_type = kwargs.get("price_type")
            price = float(kwargs.get("price") or 0.0)
            trigger_price = kwargs.get("trigger_price")

            side = 1 if str(buy_or_sell).upper() == "B" else -1
            product = "INTRADAY" if str(product_type).upper() in ("M", "MIS", "INTRADAY") else "CNC"
            order_type = self._map_order_type(price_type)

            limit_price = price if order_type in (1, 4) else 0
            stop_price = float(trigger_price or 0.0) if order_type in (3, 4) else 0

            symbol = self._normalize_symbol(str(tradingsymbol), exchange)
            payload = {
                "symbol": symbol,
                "qty": quantity,
                "type": order_type,
                "side": side,
                "productType": product,
                "limitPrice": limit_price,
                "stopPrice": stop_price,
                "disclosedQty": int(kwargs.get("discloseqty") or 0),
                "validity": "DAY",
                "offlineOrder": False,
                "stopLoss": 0,
                "takeProfit": 0,
            }

            resp = self.client.place_order(data=payload) or {}
            
            # Check for API errors first
            if resp.get("s") == "error" or resp.get("code") == -1:
                error_msg = resp.get("m") or resp.get("message") or resp.get("emsg") or str(resp)
                log_message(f"[ORDER] ❌ Fyers API error: {error_msg}")
                return {"stat": "Not_Ok", "emsg": error_msg, "raw": resp}
            
            # Check for successful response
            if resp.get("s") == "ok":
                order_id = resp.get("id") or resp.get("orderId") or resp.get("order_id")
                if order_id:
                    log_message(f"[ORDER] ✅ Order placed: {symbol} qty={quantity} type={price_type} id={order_id}")
                    return {"stat": "Ok", "norenordno": order_id, "orderno": order_id, "raw": resp}
            
            # Fallback: check for order_id even if status not explicitly ok
            order_id = resp.get("id") or resp.get("orderId") or resp.get("order_id")
            if order_id:
                log_message(f"[ORDER] ⚠️ Order placed (status unclear): {symbol} qty={quantity} type={price_type} id={order_id}")
                return {"stat": "Ok", "norenordno": order_id, "orderno": order_id, "raw": resp}
            
            # No order ID found
            error_msg = resp.get("m") or resp.get("message") or str(resp)
            log_message(f"[ORDER] ❌ No order ID in response: {error_msg}")
            return {"stat": "Not_Ok", "emsg": error_msg, "raw": resp}
        except Exception as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    def modify_order(self, **kwargs):
        if not self.client:
            return {"stat": "Not_Ok", "emsg": "Not logged in"}
        try:
            orderno = kwargs.get("orderno") or kwargs.get("norenordno") or kwargs.get("id")
            newqty = int(kwargs.get("newquantity") or 0)
            price_type = kwargs.get("newprice_type")
            newprice = float(kwargs.get("newprice") or 0.0)
            newtrigger = kwargs.get("newtrigger_price")

            order_type = self._map_order_type(price_type)
            payload = {
                "id": orderno,
                "type": order_type,
                "qty": newqty,
                "limitPrice": newprice if order_type in (1, 4) else 0,
                "stopPrice": float(newtrigger or 0.0) if order_type in (3, 4) else 0,
            }
            resp = self.client.modify_order(data=payload) or {}
            return {"stat": "Ok", "raw": resp}
        except Exception as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    def cancel_order(self, **kwargs):
        if not self.client:
            return {"stat": "Not_Ok", "emsg": "Not logged in"}
        try:
            orderno = kwargs.get("orderno") or kwargs.get("norenordno") or kwargs.get("id")
            resp = self.client.cancel_order(data={"id": orderno}) or {}
            return {"stat": "Ok", "raw": resp}
        except Exception as e:
            return {"stat": "Not_Ok", "emsg": str(e)}

    # ---------- WebSocket Wrappers ----------
    def start_websocket(self, subscribe_callback=None, socket_open_callback=None, socket_close_callback=None,
                        socket_error_callback=None, order_update_callback=None):
        if not self.client or not self.ws_access_token:
            raise RuntimeError("FYERS WebSocket requires app_id and access_token")

        # Help debug 403 handlers: log a masked version of the access token.
        def _mask_token(token: str) -> str:
            if not token:
                return "<empty>"
            t = str(token)
            if len(t) <= 12:
                return t
            return f"{t[:6]}...{t[-6:]}"

        log_message(f"[FYERS] WebSocket token={_mask_token(self.ws_access_token)} (len={len(str(self.ws_access_token))})")

        self._subscribe_callback = subscribe_callback
        self._order_update_callback = order_update_callback
        self._socket_open_callback = socket_open_callback
        self._socket_close_callback = socket_close_callback
        self._socket_error_callback = socket_error_callback

        def _on_data_message(message):
            try:
                symbol = message.get("symbol") or message.get("s")
                ltp = message.get("ltp") or message.get("lp")
                token = message.get("fyToken") or message.get("fytoken")
                if not token and symbol:
                    token = self._sym_to_token(symbol)
                if token is None:
                    return
                if ltp is None:
                    return
                
                # Debug: Log all websocket messages
                #log_message(f"[WS_MSG] Symbol: {symbol}, Token: {token}, LTP: {ltp}")
                
                tick = {"tk": str(token), "lp": float(ltp), "symbol": symbol}
                if self._subscribe_callback:
                    self._subscribe_callback(tick)
            except Exception as e:
                log_message(f"[FYERS] Data WS message error: {e}")

        def _on_data_open():
            self._NorenApi__websocket_connected = True
            if self._socket_open_callback:
                self._socket_open_callback()

        def _on_data_close(message=None):
            self._NorenApi__websocket_connected = False
            if self._socket_close_callback:
                self._socket_close_callback()

        def _on_data_error(message=None):
            if self._socket_error_callback:
                self._socket_error_callback(message)

        self._data_socket = data_ws.FyersDataSocket(
            access_token=self.ws_access_token,
            log_path=self.log_path or "",
            litemode=True,  # Enable lite mode for faster updates
            write_to_file=False,
            reconnect=False,
            on_connect=_on_data_open,
            on_close=_on_data_close,
            on_error=_on_data_error,
            on_message=_on_data_message,
        )

        def _on_order_message(message):
            try:
                msgs = []
                if isinstance(message, list):
                    msgs = message
                elif isinstance(message, dict) and "data" in message and isinstance(message["data"], list):
                    msgs = message["data"]
                else:
                    msgs = [message]

                for m in msgs:
                    if not isinstance(m, dict):
                        continue
                    order_id = m.get("id") or m.get("orderNumber") or m.get("order_id")
                    status = self._map_order_status(m.get("status"))
                    rej = m.get("message", "")
                    payload = {
                        "t": "om",
                        "norenordno": order_id,
                        "status": status,
                        "rejreason": rej,
                    }
                    if self._order_update_callback:
                        self._order_update_callback(payload)
            except Exception as e:
                log_message(f"[FYERS] Order WS message error: {e}")

        def _on_order_open():
            try:
                self._order_socket.subscribe(data_type="OnOrders,OnTrades,OnPositions,OnGeneral")
            except Exception:
                pass

        self._order_socket = order_ws.FyersOrderSocket(
            access_token=self.ws_access_token,
            write_to_file=False,
            log_path=self.log_path or "",
            on_connect=_on_order_open,
            on_close=_on_data_close,
            on_error=_on_data_error,
            on_orders=_on_order_message,
            reconnect=False,
        )

        self._data_socket.connect()
        self._order_socket.connect()

        self._data_thread = threading.Thread(target=self._data_socket.keep_running, daemon=True, name="FyersDataWS")
        self._order_thread = threading.Thread(target=self._order_socket.keep_running, daemon=True, name="FyersOrderWS")
        self._data_thread.start()
        self._order_thread.start()
        return True

    def subscribe(self, tokens, data_type: str = "SymbolUpdate"):
        if not self._data_socket:
            return
        if not isinstance(tokens, (list, tuple, set)):
            tokens = [tokens]
        symbols = []
        for item in tokens:
            token = item
            if isinstance(token, str) and "|" in token:
                token = token.split("|", 1)[1]
            symbol = self._token_to_sym(str(token)) or (str(token) if ":" in str(token) else None)
            if not symbol:
                continue
            symbols.append(symbol)
            self._ws_subscribed_symbols.add(symbol)
        if symbols:
            self._data_socket.subscribe(symbols=symbols, data_type=data_type)

    def unsubscribe(self, tokens, data_type: str = "SymbolUpdate"):
        if not self._data_socket:
            return
        if not isinstance(tokens, (list, tuple, set)):
            tokens = [tokens]
        symbols = []
        for item in tokens:
            token = item
            if isinstance(token, str) and "|" in token:
                token = token.split("|", 1)[1]
            symbol = self._token_to_sym(str(token)) or (str(token) if ":" in str(token) else None)
            if not symbol:
                continue
            symbols.append(symbol)
            if symbol in self._ws_subscribed_symbols:
                self._ws_subscribed_symbols.discard(symbol)
        if symbols:
            self._data_socket.unsubscribe(symbols=symbols, data_type=data_type)

    def close_websocket(self):
        try:
            if self._data_socket:
                self._data_socket.close_connection()
        except Exception:
            pass
        try:
            if self._order_socket:
                self._order_socket.close_connection()
        except Exception:
            pass
        self._NorenApi__websocket_connected = False

    # ---------- Mappings ----------
    def _map_order_type(self, price_type: Optional[str]) -> int:
        pt = str(price_type or "").upper()
        if pt in ("LMT", "LIMIT"):
            return 1
        if pt in ("MKT", "MARKET"):
            return 2
        if pt in ("SL-MKT", "SLM", "STOP"):
            return 3
        if pt in ("SL-LMT", "SLL", "STOPLIMIT", "STOP-LIMIT"):
            return 4
        return 2

    def _map_order_status(self, status):
        # FYERS: 1 canceled, 2 filled, 4 transit, 5 rejected, 6 pending, 7 expired
        try:
            s = int(status)
        except Exception:
            return str(status) if status else "UNKNOWN"
        if s == 2:
            return "COMPLETE"
        if s == 1:
            return "CANCELLED"
        if s == 5:
            return "REJECTED"
        if s == 6:
            return "PENDING"
        if s == 4:
            return "OPEN"
        if s == 7:
            return "CANCELLED"
        return "UNKNOWN"

api = FyersApiAdapter()

# ============================================================================
# CONSTANTS - Centralized configuration
# ============================================================================

class Config:
    NiftyToken = '101000000026000'
    BankNiftyToken = '101000000026009'
    capital = 50000
    capPerLoss = 0.02  # 2% of capital per trade
    manual_override = False
    version = "1.0.0"
    name = None
    # Trading Parameters
    PAPER_MODE = False
    NSE_error = False
    RSI_signal_time = 1

    RSI_GLOBAL = None
    # Tuesday = 1 (Mon=0, Tue=1, ...)
    ExpiryDay = 0  # Tuesday    should be change if weekly expiry day change by NSE.
    LOT_SIZE = 65
    INDEX_STRIKE_DIFF = 100
    TICK_SIZE = 0.05
    MAX_FINALIZE_RETRIES = 5

    # Auto-exit / stoploss tuning
    AUTO_SL_PERCENT = 15         # percent below premium to place SL (e.g., 15 means 15%)
    AUTO_EXIT_UNDERLYING_DROP_PTS = 40  # underlying drop in points to consider forced exit
    AUTO_EXIT_RSI_FALL = 2        # minimum 5m RSI fall since entry to consider momentum
   
    # Timing
    MARKET_OPEN = QTime(00, 0)
    AUTO_SQUARE_OFF = QTime(15, 00)
    LOGIN_TIME = QTime(00, 0)
    MSG_LOG_ON = QTime(00, 0)
    MARKET_CLOSE =  QTime(22, 30) #QTime(15, 30)
    LOGOUT_TIME =  QTime(22, 31)  #QTime(15, 31)
    MSG_LOG_OFF = QTime(22, 40)   #QTime(15, 40)

    trend_day = False
    range_day = False
    Re_entry = "No Re-entry"
        
    # File Pathss
    CREDS_DIR = 'creds'
    PNL_DIR = 'Fyers_PnL'
    LOG_DIR = 'logs'
    # FYERS token auto-refresh
    FYERS_TOKEN_AUTO_REFRESH = True
    FYERS_TOKEN_RENEW_WITHIN = 300  # seconds
    FYERS_TOKEN_TOOL_PATH = os.path.join("scripts", "fyers_token_tool.py")
    
    # Telegram
    TELEGRAM_BOT_TOKEN = "8404261981:AAEdUefaP7cDahVGIhukpyrrSW5KKaQ2nls"
    TELEGRAM_ADMIN_CHAT = "1280328873"
    
    # License
    LICENSE_KEY = "sG4qmydZ7u6AWPh9LjlUJmuSbgSgZN2j2LbTdCOstH4="

def log_message(message):
    now = QTime.currentTime()
    on_time = Config.MSG_LOG_ON
    off_time = Config.MSG_LOG_OFF
    if off_time.msecsSinceStartOfDay() > now.msecsSinceStartOfDay() >= on_time.msecsSinceStartOfDay():
        file_datetime = datetime.datetime.now()
        time_str = file_datetime.strftime('%H:%M:%S')
        file_date_str = file_datetime.strftime("%d%b%y")
        log_file = f'{Config.LOG_DIR}/AlgoFyers_log-{file_date_str}.txt'
        try:
            print(f'{time_str}:- {message}')
        except UnicodeEncodeError:
            # Fallback: print without emoji on Windows console
            clean_message = message.encode('ascii', 'replace').decode('ascii')
            print(f'{time_str}:- {clean_message}')
        
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(time_str + " = " + message + '\n')
        except Exception as e:
            pass  # Silently fail on encoding issues

def check_license():
    cipher_suite = Fernet(Config.LICENSE_KEY)
    current_user_id = None
    cred_dir = "creds"
    
    for cred_file in os.listdir(cred_dir):
        if not (cred_file.startswith("cred_1") and cred_file.endswith(".yml")):
            continue
        yaml_file = os.path.join(cred_dir, cred_file)
        try:
            with open(yaml_file) as f:
                cred = yaml.load(f, Loader=yaml.FullLoader)
                current_user_id = cred['user']
                Config.LOT_SIZE = (cred['lotSize'] if cred['lotSize'] else Config.LOT_SIZE)
                Config.ExpiryDay = (cred['FUT_expiryDay'] if cred['FUT_expiryDay'] else Config.ExpiryDay)   
                print(f"expiry day - {Config.ExpiryDay}")
                Config.capital = (cred['Current_capital'] if cred['Current_capital'] else Config.capital)   
                print(f"capital - {Config.capital}")
                # Tolerate older/typo keys in creds (capperLoss) and missing fields.
                cap_per_loss = cred.get('capPerLoss', cred.get('capperLoss', None))
                if cap_per_loss is not None:
                    Config.capPerLoss = cap_per_loss

                if 'manual_override' in cred:
                    Config.manual_override = cred.get('manual_override')

                if cred.get('name'):
                    Config.name = cred.get('name')
                if cred.get('NiftyToken'):
                    nt = str(cred.get('NiftyToken'))
                    if nt in ("26000", "NIFTY"):
                        Config.NiftyToken = "101000000026000"
                    else:
                        Config.NiftyToken = nt
                if cred.get('BankNiftyToken'):
                    bt = str(cred.get('BankNiftyToken'))
                    if bt in ("26009", "BANKNIFTY"):
                        Config.BankNiftyToken = "101000000026009"
                    else:
                        Config.BankNiftyToken = bt

        except Exception as e:
            log_message(f"[ERROR] Loading credentials from {yaml_file}: {e}")
            return
    
    with open(f'license_{current_user_id}.lic', 'rb') as f:
        encrypted_license_data = f.read()
    
    try:
        decrypted_license_data = cipher_suite.decrypt(encrypted_license_data).decode()
        user_id, start_date, end_date = decrypted_license_data.split(',')
        if user_id != current_user_id:
            raise ValueError("User ID does not match the license file.")
        
        current_date = datetime.datetime.now().date()
        end_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
        start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        
        if current_date < start_date:
            raise ValueError("License is not valid yet.")
        elif current_date > end_date:
            raise ValueError("License has expired.")
        elif (end_date - current_date).days <= 8:
            days_remaining = (end_date - current_date).days
            return f"License will expire in {days_remaining} day(s)."
    except Exception as e:
        return str(e)
    return None

def start_reporter():
    nest_asyncio.apply()
    # Suppress noisy traceback spam from telegram/httpx during internet outages.
    logging.getLogger("telegram.ext._updater").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)

    reporter = AlgoNiftyTelegramReporter(
        bot_token=Config.TELEGRAM_BOT_TOKEN,
        admin_chat_id=Config.TELEGRAM_ADMIN_CHAT
    )
    while True:
        now = QTime.currentTime().msecsSinceStartOfDay()
        start1 = QTime(15, 40)
        end1   = QTime(23, 59)
        start2 = QTime(0, 0)
        end2   = QTime(8, 50)

        if (start1.msecsSinceStartOfDay() <= now <= end1.msecsSinceStartOfDay()) or \
        (start2.msecsSinceStartOfDay() <= now <= end2.msecsSinceStartOfDay()):
            try:
                print("🤖 Starting Telegram Reporter...")
                asyncio.run(reporter.run())
            except Exception as e:
                print(f"[Reporter Error] {e}")
            time.sleep(60)
        else:
            time.sleep(30)

# ============================================
class WorkerSignals(QObject):
    """
    Defines the signals available from a running worker thread.
    Supported signals:
    - result: Returns data from successful execution
    - error: Returns exception that occurred
    - finished: Emitted when worker completes

    """
    result = pyqtSignal(object)
    error = pyqtSignal(tuple)  # (exception, traceback)
    finished = pyqtSignal()

class APIWorker(QRunnable):
    """
    Worker thread for executing API calls without blocking the GUI.
    Usage:
        worker = APIWorker(api.get_quotes, 'NFO', '12345')
        worker.signals.result.connect(on_success_callback)
        worker.signals.error.connect(on_error_callback)
        threadpool.start(worker)
    """
    
    def __init__(self, fn, *args, **kwargs):
        """
        Initialize the worker.
        Args:
            fn: The function to execute (e.g., api.get_quotes)
            *args: Positional arguments for fn
            **kwargs: Keyword arguments for fn
        """
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)  # Automatically cleanup after execution
    
    def run(self):
        """
        Execute the function with provided arguments.
        Emits result on success, error on failure, finished always.
        """
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as e:
            # Capture full traceback for debugging
            tb = traceback.format_exc()
            self.signals.error.emit((e, tb))
        finally:
            self.signals.finished.emit()

class DataCache:
    """
    Thread-safe cache manager with TTL (Time To Live).
    Usage:
        cache = DataCache()
        cache.set('option_chain', data, ttl=5)  # Cache for 5 seconds
        data = cache.get('option_chain')  # Returns None if expired
    """
    
    def __init__(self):
        self._cache = {}
        self._lock = Lock()
    
    def set(self, key, value, ttl=None):
        """
        Set cache entry with optional TTL in seconds.
        Args:
            key: Cache key
            value: Data to cache
            ttl: Time to live in seconds (None = no expiry)
        """
        with self._lock:
            expiry = time.time() + ttl if ttl else None
            self._cache[key] = {
                'value': value,
                'expiry': expiry,
                'created': time.time()
            }
    
    def get(self, key):
        """
        Get cache entry if not expired.
        Args:
            key: Cache key
        Returns:
            Cached value or None if expired/not found
        """
        with self._lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            
            # Check expiry
            if entry['expiry'] and time.time() > entry['expiry']:
                del self._cache[key]
                return None
            
            return entry['value']
    
    def clear(self, key=None):
        """Clear specific key or entire cache."""
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()
    
    def get_stats(self):
        """Get cache statistics."""
        with self._lock:
            active = 0
            expired = 0
            now = time.time()
            
            for entry in self._cache.values():
                if entry['expiry'] and now > entry['expiry']:
                    expired += 1
                else:
                    active += 1
            
            return {
                'total': len(self._cache),
                'active': active,
                'expired': expired
            }

class UIUpdateThrottler:
    """
    Throttle UI updates to prevent excessive GUI refreshes.
    Usage:
        throttler = UIUpdateThrottler(min_interval_ms=100)
        if throttler.should_update('ltp'):
            # Update GUI
    """
    
    def __init__(self, min_interval_ms=100):
        self.min_interval_ms = min_interval_ms
        self.last_update_ts = {}
    
    def should_update(self, key):
        now = time.time() * 1000
        last = self.last_update_ts.get(key, 0)
        if now - last > self.min_interval_ms:
            self.last_update_ts[key] = now
            return True
        return False

class MultiAccountManager:
    """
    Loads all creds from creds/cred_*.yml, logs into each account,
    and keeps per-account FYERS API instances + state.
    """
    def __init__(self, creds_dir='creds'):
        self.creds_dir = creds_dir
        self.accounts = {}
        self.master_user = None
        self._refresh_fyers_tokens_if_needed()
        self.load_and_login_all()

    def _refresh_fyers_tokens_if_needed(self):
        """Run FYERS token refresh tool before login (non-fatal)."""
        try:
            if not getattr(Config, "FYERS_TOKEN_AUTO_REFRESH", False):
                return

            tool_path = getattr(Config, "FYERS_TOKEN_TOOL_PATH", "")
            if not tool_path or not os.path.exists(tool_path):
                log_message(f"[FYERS] Token tool not found at {tool_path}; skipping refresh")
                return

            renew_within = int(getattr(Config, "FYERS_TOKEN_RENEW_WITHIN", 300) or 300)
            cmd = [
                sys.executable,
                tool_path,
                "--creds-dir",
                self.creds_dir,
                "--refresh",
                "--renew-within",
                str(renew_within),
                "--include-fyers-credits",
            ]
            log_message("[FYERS] Pre-login token refresh: starting")
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                log_message("[FYERS] Token refresh completed")
            else:
                log_message(f"[FYERS] Token refresh tool returned {proc.returncode}")
            if proc.stdout:
                log_message(proc.stdout.strip())
            if proc.stderr:
                log_message(proc.stderr.strip())
        except Exception as e:
            log_message(f"[FYERS] Token refresh failed: {e}")

    def find_cred_files(self):
        pattern = os.path.join(self.creds_dir, "cred_*.yml")
        files = sorted(glob.glob(pattern))
        if os.path.exists("FyersCredits.yml"):
            files.append("FyersCredits.yml")
        return files

    def load_cred(self, path):
        with open(path) as f:
            return yaml.load(f, Loader=yaml.FullLoader)

    def _extract_cred_dict(self, cred):
        """Return the actual FYERS credential dict and whether it was nested under 'fyers'."""
        if isinstance(cred, dict) and isinstance(cred.get('fyers'), dict):
            return cred['fyers'], True
        return cred, False

    def _refresh_access_token(self, cred, cred_path, app_id, secret_key, user):
        """Try to generate a new access_token using the refresh token (no UI required)."""
        cred_dict, nested = self._extract_cred_dict(cred)
        refresh_token = str(cred_dict.get('refresh_token') or cred_dict.get('token') or '').strip()
        pin = str(cred_dict.get('pin') or cred_dict.get('pwd') or '').strip()
        if not refresh_token or not pin:
            return None

        try:
            log_message(f"[FYERS] Attempting token refresh for {user} using {cred_path}")
            import hashlib
            appIdHash = hashlib.sha256(f"{app_id}:{secret_key}".encode()).hexdigest()
            url = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
            payload = {
                "grant_type": "refresh_token",
                "appIdHash": appIdHash,
                "refresh_token": refresh_token,
                "pin": pin,
            }
            resp = requests.post(url, json=payload, timeout=15)
            data = resp.json() if resp is not None else {}

            if data.get("s") != "ok":
                log_message(f"[FYERS] Refresh token invalid for {user}: {data}")
                return None

            access_token = data.get("access_token")
            new_refresh = data.get("refresh_token")
            if access_token:
                # Persist updated tokens so future logins can use them.
                if cred_path:
                    save_cred = cred if not nested else cred
                    if nested:
                        save_cred['fyers']['fyers_access_token'] = access_token
                        if new_refresh:
                            save_cred['fyers']['refresh_token'] = new_refresh
                    else:
                        save_cred['fyers_access_token'] = access_token
                        if new_refresh:
                            save_cred['refresh_token'] = new_refresh
                    with open(cred_path, 'w') as f:
                        yaml.dump(save_cred, f, default_flow_style=False)
                    log_message(f"[FYERS] Refreshed access token saved to {cred_path} for {user}")
                return access_token
        except Exception as e:
            log_message(f"[FYERS] Refresh token request failed for {user}: {e}")
        return None

    def login_account(self, cred, cred_path=None):
        api = FyersApiAdapter()

        try:
            raw_cred = cred
            cred, nested = self._extract_cred_dict(raw_cred)

            # Sanitize credential fields to avoid hidden whitespace issues.
            user = str(cred.get('name', '')).strip()
            app_id = str(cred.get('fyers_app_id', cred.get('app_id', ''))).strip()
            access_token = str(cred.get('fyers_access_token', cred.get('access_token', ''))).strip()
            secret_key = str(cred.get('fyers_secret_key', cred.get('secret_key', ''))).strip()

            if not app_id:
                log_message(f"[LOGIN FAIL] {user} - Missing FYERS app_id")
                return None

            # If access_token is missing, try refreshing it (using stored refresh token + pin)
            if not access_token:
                if not secret_key:
                    log_message(f"[LOGIN FAIL] {user} - Missing FYERS secret_key (needed to generate/access token)")
                    return None

                access_token = self._refresh_access_token(cred, cred_path, app_id, secret_key, user)
                if access_token:
                    log_message(f"[FYERS] Access token refreshed for {user}")
                else:
                    # Fall back to manual auth flow if refresh fails
                    log_message(f"[FYERS] Access token missing for {user}, generating new one...")

                    try:
                        # Step 1: Get auth code automatically
                        auth_code = get_auth_code_automated(app_id, secret_key, user)
                        if not auth_code:
                            log_message(f"[FYERS] Failed to get auth code for {user}")
                            return None

                        # Step 2: Generate access token
                        session = fyersModel.SessionModel(
                            client_id=app_id,
                            secret_key=secret_key,
                            grant_type="authorization_code"
                        )
                        session.set_token(auth_code)
                        token_response = session.generate_token()

                        if not token_response or token_response.get("s") != "ok":
                            log_message(f"[FYERS] Token generation failed for {user}: {token_response}")
                            return None

                        access_token = token_response.get("access_token")
                        if not access_token:
                            log_message(f"[FYERS] No access_token in response for {user}")
                            return None

                        # Step 5: Save the new token to the YAML file
                        if cred_path:
                            save_cred = raw_cred if nested else cred
                            if nested:
                                save_cred['fyers']['fyers_access_token'] = access_token
                                save_cred['fyers']['refresh_token'] = token_response.get('refresh_token', save_cred['fyers'].get('refresh_token'))
                            else:
                                save_cred['fyers_access_token'] = access_token
                                save_cred['refresh_token'] = token_response.get('refresh_token', save_cred.get('refresh_token'))
                            with open(cred_path, 'w') as f:
                                yaml.dump(save_cred, f, default_flow_style=False)
                            log_message(f"[FYERS] New access token saved to {cred_path} for {user}")
                        else:
                            log_message(f"[FYERS] Could not find cred file to save token for {user}")

                    except Exception as e:
                        log_message(f"[FYERS] Token generation error for {user}: {e}")
                        return None

            try:
                ret = api.login(app_id=app_id, access_token=access_token)

                if ret and ret.get('stat') == 'Ok':
                    log_message(f"[LOGIN OK] {user}")
                    return api
            except Exception as e:
                log_message(f"[LOGIN EXCEPTION INITIAL] {user}: {e}")
                ret = None

            # If token is invalid/expired, try refreshing using stored refresh token + pin.
            if secret_key:
                refreshed = self._refresh_access_token(cred, cred_path, app_id, secret_key, user)
                if refreshed:
                    access_token = refreshed
                    try:
                        ret = api.login(app_id=app_id, access_token=access_token)
                        if ret and ret.get('stat') == 'Ok':
                            log_message(f"[LOGIN OK] {user} (after token refresh)")
                            return api
                    except Exception as e:
                        log_message(f"[LOGIN EXCEPTION AFTER REFRESH] {user}: {e}")

            # If refresh failed or no secret_key, try manual token generation
            if secret_key:
                log_message(f"[FYERS] Access token invalid for {user}, generating new one...")

                try:
                    # Step 1: Get auth code automatically
                    auth_code = get_auth_code_automated(app_id, secret_key, user)
                    if not auth_code:
                        log_message(f"[FYERS] Failed to get auth code for {user}")
                        return None

                    # Step 2: Generate access token
                    session = fyersModel.SessionModel(
                        client_id=app_id,
                        secret_key=secret_key,
                        grant_type="authorization_code"
                    )
                    session.set_token(auth_code)
                    token_response = session.generate_token()

                    if not token_response or token_response.get("s") != "ok":
                        log_message(f"[FYERS] Token generation failed for {user}: {token_response}")
                        return None

                    access_token = token_response.get("access_token")
                    if not access_token:
                        log_message(f"[FYERS] No access_token in response for {user}")
                        return None

                    # Step 5: Save the new token to the YAML file
                    if cred_path:
                        save_cred = raw_cred if nested else cred
                        if nested:
                            save_cred['fyers']['fyers_access_token'] = access_token
                            refresh_token = token_response.get("refresh_token")
                            if refresh_token:
                                save_cred['fyers']['refresh_token'] = refresh_token
                        else:
                            save_cred['fyers_access_token'] = access_token
                            refresh_token = token_response.get("refresh_token")
                            if refresh_token:
                                save_cred['refresh_token'] = refresh_token
                        with open(cred_path, 'w') as f:
                            yaml.dump(save_cred, f, default_flow_style=False)
                        log_message(f"[FYERS] New access token saved to {cred_path} for {user}")
                    else:
                        log_message(f"[FYERS] Could not find cred file to save token for {user}")

                    # Try login with new token
                    try:
                        ret = api.login(app_id=app_id, access_token=access_token)
                        if ret and ret.get('stat') == 'Ok':
                            log_message(f"[LOGIN OK] {user} (after manual token generation)")
                            return api
                    except Exception as e:
                        log_message(f"[LOGIN EXCEPTION AFTER MANUAL] {user}: {e}")

            log_message(f"[LOGIN FAIL] {user} - {ret}")
            return None

        except Exception as e:
            log_message(f"[LOGIN EXCEPTION] {cred.get('user')}: {e}")
            return None

    def load_and_login_all(self):
        files = self.find_cred_files()
        if not files:
            raise FileNotFoundError("No cred_*.yml files found in creds/ directory.")
        for i, fpath in enumerate(files):
            cred = self.load_cred(fpath)
            user = cred.get('user') or os.path.splitext(os.path.basename(fpath))[0]
            api = self.login_account(cred, fpath)

            if not api:
                log_message(f"[ERROR] Skipping account {user} due to login failure.")
                continue
            self.accounts[user] = {
                'cred': cred,
                'api': api,
                'orders': {},
                'positions': {},
                'state': {}
            }
            if self.master_user is None:
                self.master_user = user
        if self.master_user is None:
            raise RuntimeError("No successful login among creds/ files.")

    def get_master_api(self):
        return self.accounts[self.master_user]['api']

    def iterate_accounts(self):
        for uid, acc in self.accounts.items():
            yield uid, acc

    def place_order(self, user, **kwargs):
        acc = self.accounts.get(user)
        if not acc:
            return None
        api = acc['api']
        try:
            resp = api.place_order(**kwargs)
            return resp
        except Exception as e:
            log_message(f"[ORDER_ERR] user={user}, err={e}")
            return None

    def modify_order(self, user, **kwargs):
        acc = self.accounts.get(user)
        if not acc:
            return None
        api = acc['api']
        try:
            resp = api.modify_order(**kwargs)
            return resp
        except Exception as e:
            log_message(f"[MODIFY_ERR] user={user}, err={e}")
            return None

    def cancel_order(self, user, **kwargs):
        """
        Cancel an order for the given `user`.
        Accepts either:
        - `orderno` keyword (preferred), or
        - `norenordno` keyword, or
        - `ret` keyword containing the place_order return dict with `norenordno`.
        Falls back to passing all kwargs to `api.cancel_order` if none of the above provided.
        """
        acc = self.accounts.get(user)
        if not acc:
            return None
        api = acc['api']
        try:
            # If caller passed the full place_order return dict, extract orderno
            if 'ret' in kwargs and isinstance(kwargs['ret'], dict):
                orderno = kwargs['ret'].get('norenordno') or kwargs['ret'].get('orderno')
                if orderno:
                    return api.cancel_order(orderno=orderno)

            # Common alternate keys
            if 'orderno' in kwargs:
                return api.cancel_order(orderno=kwargs['orderno'])
            if 'norenordno' in kwargs:
                return api.cancel_order(orderno=kwargs['norenordno'])

            # Fallback: forward kwargs to API
            resp = api.cancel_order(**kwargs)
            return resp
        except Exception as e:
            log_message(f"[CANCEL_ERR] user={user}, err={e}")
            return None

    def get_positions(self, user):
        acc = self.accounts.get(user)
        if not acc:
            return None
        api = acc['api']
        try:
            return api.get_positions()
        except Exception as e:
            log_message(f"[POSITIONS_ERR] user={user}, err={e}")
            return None

class GannLevelsManager:
    def __init__(self):
        self.gann_levels = []

    def read_gann_levels(self):
        file_path = "GannLevels.txt"

        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as file:
                    lines = file.readlines()
                    if len(lines) < 20:
                        raise ValueError("Incomplete Gann levels data in file.")

                    for i in range(10):
                        resistance_level = lines[i].strip()
                        self.gann_levels.append((int(resistance_level)))

                    for i in range(10):
                        support_level = lines[i + 10].strip()
                        self.gann_levels.append((int(support_level)))
            except Exception as e:
                log_message(f"Error reading Gann levels: {e}")
                QMessageBox.warning(
                    None,
                    "Gann Levels Missing",
                    "GannLevels.txt file is incomplete or corrupted. Please input levels manually."
                )
        else:
            QMessageBox.information(
                None,
                "Gann Levels Missing",
                "GannLevels.txt not found. Please input Gann levels manually."
            )

# ============================================
class GannLevelCalculator:
    def __init__(self):
        self.nse = NseSession()

        nifty_price = self.get_nifty50_price()
        if nifty_price is not None:
            aligned_price = self.find_closest_major_axis_price(nifty_price)
            levels = self.get_gann_square_levels(aligned_price, num_steps=10)
            self.save_levels_to_file(levels)
            log_message(f"Gann levels saved to 'GannLevels.txt' based on aligned price {aligned_price}")

    def reverse_gann_price(self, angle, layer):
        sqrt_val = 1 + (angle + 360 * layer) / 360
        return round(sqrt_val ** 2, 2)

    def find_closest_major_axis_price(self, target_price, search_range=100):
        MAJOR_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315]
        layer_estimate = int(math.sqrt(target_price)) - 1
        min_diff = float("inf")
        best_price = None

        for angle in MAJOR_ANGLES:
            for layer in range(layer_estimate - search_range, layer_estimate + search_range + 1):
                if layer < 0:
                    continue
                price = self.reverse_gann_price(angle, layer)
                diff = abs(price - target_price)
                if diff < min_diff:
                    min_diff = diff
                    best_price = price

        print(f"✅ Closest aligned price on major axis: {best_price} (diff: {min_diff:.2f})")
        return best_price

    def get_gann_square_levels(self, price, num_steps=10):
        sqrt_price = math.sqrt(price)
        base_angle = (sqrt_price - 1) * 360
        levels = []

        for step in range(-num_steps, num_steps + 1):
            sqrt_level = 1 + (base_angle + step * 45) / 360
            level = round(sqrt_level ** 2, 2)
            levels.append(round(level))

        return levels

    def save_levels_to_file(self, levels, filename="GannLevels.txt"):
        with open(filename, "w") as f:
            for level in levels:
                f.write(f"{level}\n")

    def get_nifty50_price(self):
        try:
            oc = OptionChainFetcher(self.nse)
            ef = ExpiryFetcher(self.nse)
            expiries = ef.fetch_expiries("NIFTY")
            df, spot, ex = oc.fetch_option_chain("NIFTY", expiries[0])
            return (float(spot) if spot is not None else None)
        except Exception as e:
            log_message(f"Error fetching Nifty spot price: {e}")
            return None

# ============================================
class UnifiedTimerThread(QThread):
    second_signal = pyqtSignal(str)
    rsi_signal = pyqtSignal(str)
    risDivergence_signal = pyqtSignal(str)
    suggest_entry_signal = pyqtSignal(object)
    ce_exit_signal = pyqtSignal(str)
    pe_exit_signal = pyqtSignal(str) 

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent: Any = parent
        self.running = True
        self.last_minute = None

    def run(self):
        while self.running:
            try:
                current_time = QDateTime.currentDateTime()
                self.second_signal.emit(current_time.toString("HH:mm:ss"))

                now= datetime.datetime.now()

                if current_time.time().second() == 0 and now.minute % Config.RSI_signal_time == 0 and now.minute != self.last_minute:
                    self.fetch_real_time_data_UnifiedClass()
                    self.last_minute = now.minute
                time.sleep(1)
            except Exception as e:
                log_message(f"[ERROR] UnifiedTimerThread: {e}")

    def fetch_real_time_data_UnifiedClass(self):
        """Fetch real-time 'intc' data and emit the RSI value."""
        try:

            if not self._parent:
                return
            df_5m = self._parent.fetch_Nifty_FUT_candles(days=5, interval=5)
            df_5m = df_5m.iloc[:-1]  # drop running candle
            numeric_cols = ['into', 'inth', 'intl', 'close', 'vol']

            df_5m[numeric_cols] = df_5m[numeric_cols].apply(
                pd.to_numeric, errors='coerce'
            )
            #for testing
            #print("df_5m columns:", df_5m.columns.tolist())
            #print("df values:\n", df_5m.tail())

            # 5-min RSI
            rsi_5m = self.calculate_rsi(df_5m['close']).dropna()
            rsi_5m_latest = round(rsi_5m.iloc[-1], 2)
            rsi_5m_prev   = round(rsi_5m.iloc[-2], 2)

            #----------------------------------------
            # 30-min RSI
            close_30m = self.build_30min(df_5m)
            rsi_30m = self.calculate_rsi(close_30m).dropna()
            rsi_30m_latest = round(rsi_30m.iloc[-1], 2)

            emitRSI = f"{rsi_30m_latest:.2f}/{rsi_5m_latest:.2f}/{rsi_5m_prev:.2f}"
            self.rsi_signal.emit(emitRSI)

            # Divergence
            divergence = self.detect_divergence(close_30m, rsi_30m)
            # Entry suggestion (returns tuple: suggestion, strength, quality)
            entry_suggestion, strength, quality  = self.suggest_entry(rsi_30m_latest, rsi_5m_latest, rsi_5m_prev)

            current_position = getattr(self._parent, 'active_order_side', None)

            # Generate exit signal only for the position we're holding
            ce_exit = None
            pe_exit = None
            
            if current_position == 'CE':
                ce_exit = self.suggest_exit(
                    position_type='CE',
                    rsi_30m_latest=rsi_30m_latest,
                    rsi_5m_latest=rsi_5m_latest,
                    divergence=divergence
                )
            elif current_position == 'PE':
                pe_exit = self.suggest_exit(
                    position_type='PE',
                    rsi_30m_latest=rsi_30m_latest,
                    rsi_5m_latest=rsi_5m_latest,
                    divergence=divergence
                )

            self.risDivergence_signal.emit(divergence)
            # Emit structured entry suggestion so consumers receive full context
            entry_payload = {
                "entry_signal": entry_suggestion,
                "strength": strength,
                "quality_score": quality,
            }
            self.suggest_entry_signal.emit(entry_payload)
            self.ce_exit_signal.emit(ce_exit)
            self.pe_exit_signal.emit(pe_exit)

            self.evaluate_reentry_conditions(df_5m, rsi_5m)

            # ATR-based day type determination           
            atr_series = self.calculate_atr_close_only(df_5m['close'])
            atr_5m = atr_series.iloc[-1]
            atr_avg = atr_series.rolling(50).mean().iloc[-1]
            Config.trend_day = atr_5m > atr_avg * 1.15
            Config.range_day = atr_5m < atr_avg * 0.9

        except Exception as e:
            log_message(f"[ERROR] [RSI] fetch_real_time_data: {e}")

    def evaluate_reentry_conditions(self, df, rsi_5m_series):
        if not hasattr(self, "_last_reentry_state"):
            self._last_reentry_state = None

        now = datetime.datetime.now()
        df = df[df.index.date == now.date()].copy()

        pe_ok, pe_reason = self.check_ce_fade_mandatory_conditions(df, rsi_5m_series)
        if pe_ok:
            log_message(f"✅ [Re-Entry] {pe_reason}")
        ce_ok, ce_reason = self.check_pe_fade_mandatory_conditions(df, rsi_5m_series)
        if ce_ok:
            log_message(f"✅ [Re-Entry] {ce_reason}")  

        # Default (black)
        ce_text = f"CE_fade- {pe_reason}"
        pe_text = f"PE_fade- {ce_reason}"

        # Color logic
        if pe_ok:
            ce_text = f'<span style="color:red;">CE_fade- {pe_reason}</span>'

        elif ce_ok:
            pe_text = f'<span style="color:green;">PE_fade- {ce_reason}</span>'

        # Final UI string
        new_reentry = f"|| {ce_text} || {pe_text} ||"
        if new_reentry != self._last_reentry_state:
            Config.Re_entry = new_reentry
            self._last_reentry_state = new_reentry
            log_message(f"[RE-ENTRY UPDATE] {new_reentry}")

    def check_ce_fade_mandatory_conditions(self,
        df_5m: pd.DataFrame,
        rsi_5m_series: pd.Series
    ):
        """
        CE Fade → PE Entry
        Uses SESSION VWAP + RSI Regime + Market Bias
        Returns (bool, reason_string)
        """

        # ─────────────────────────────────────────────
        # 0️⃣ MARKET BIAS ALIGNMENT (OPTIONAL — VERY RECOMMENDED)
        # ─────────────────────────────────────────────
        parent_mm = getattr(self._parent, 'market_memory', {}) if self._parent else {}
        bias_score = parent_mm.get("bias_score", 0)

        if bias_score > -2:
            return False, "MB not bearish enough for CE fade"

        # ─────────────────────────────────────────────
        # BASIC SAFETY
        # ─────────────────────────────────────────────
        if len(df_5m) < 5 or len(rsi_5m_series) < 5:
            return False, "Not enough data"

        df_5m = df_5m.copy()

        numeric_cols = ['into', 'inth', 'intl', 'close', 'v']
        for col in numeric_cols:
            df_5m[col] = pd.to_numeric(df_5m[col], errors='coerce')

        rsi_5m_series = pd.to_numeric(rsi_5m_series, errors='coerce')

        if df_5m[numeric_cols].isna().any().any() or rsi_5m_series.isna().any():
            return False, "Invalid numeric data"

        # ─────────────────────────────────────────────
        # 1️⃣ SESSION VWAP (INSTITUTIONAL)
        # ─────────────────────────────────────────────
        df_5m['tp'] = (df_5m['inth'] + df_5m['intl'] + df_5m['close']) / 3
        df_5m['pv'] = df_5m['tp'] * df_5m['v']
        df_5m['cum_pv'] = df_5m['pv'].cumsum()
        df_5m['cum_v'] = df_5m['v'].cumsum()
        df_5m['session_vwap'] = df_5m['cum_pv'] / df_5m['cum_v']

        # ─────────────────────────────────────────────
        # LATEST CANDLES
        # ─────────────────────────────────────────────
        c0 = df_5m.iloc[-1]
        c1 = df_5m.iloc[-2]
        c2 = df_5m.iloc[-3]

        price = c0['close']
        vwap0 = c0['session_vwap']
        vwap1 = c1['session_vwap']
        vwap2 = c2['session_vwap']

        # ─────────────────────────────────────────────
        # 2️⃣ PRICE ACCEPTANCE BELOW VWAP
        # ─────────────────────────────────────────────
        if price >= vwap0 * 0.999:
            return False, "Price clearly above VWAP"

        # ─────────────────────────────────────────────
        # 3️⃣ VWAP SLOPE (NO ACCUMULATION)
        # ─────────────────────────────────────────────
        if not (vwap0 <= vwap1 <= vwap2 or vwap0 <= vwap1):
            return False, "Session VWAP still rising"

        # ─────────────────────────────────────────────
        # 4️⃣ RSI REGIME + DISTRIBUTION
        # ─────────────────────────────────────────────
        rsi_regime, rsi_slope = self.detect_rsi_regime(rsi_5m_series)

        r0 = rsi_5m_series.iloc[-1]
        r1 = rsi_5m_series.iloc[-2]
        r2 = rsi_5m_series.iloc[-3]

        lower_high = r1 > r0 and r2 >= r1

        rsi_bearish_pressure = (
            (rsi_regime == "BEAR") or
            (lower_high and rsi_slope < -0.8)
        )

        if not rsi_bearish_pressure:
            return False, "No bearish distribution regime" #"RSI not showing bearish distribution regime"

        # ─────────────────────────────────────────────
        # 5️⃣ BEARISH CANDLE STRUCTURE
        # ─────────────────────────────────────────────
        body_down = c0['close'] < c0['into']
        candle_range = c0['inth'] - c0['intl']

        close_near_low = (
            (c0['close'] - c0['intl']) / max(candle_range, 1e-6)
        ) < 0.3

        if not (body_down and close_near_low):
            return False, "No bearish candle acceptance"

        # ─────────────────────────────────────────────
        # ✅ ALL CONDITIONS MET
        # ─────────────────────────────────────────────
        return True, "CE FADE → PE ENTRY CONDITIONS MET"

    def check_pe_fade_mandatory_conditions(self, 
        df_5m: pd.DataFrame,
        rsi_5m_series: pd.Series
    ):
        """
        PE Fade → CE Entry
        Uses SESSION VWAP + RSI Regime + Market Bias
        Returns (bool, reason_string)
        """
        # ─────────────────────────────────────────────
        # 0️⃣ MARKET BIAS ALIGNMENT (OPTIONAL — VERY RECOMMENDED)
        # ─────────────────────────────────────────────
        parent_mm = getattr(self._parent, 'market_memory', {}) if self._parent else {}
        bias_score = parent_mm.get("bias_score", 0)

        if bias_score < 2:
            return False, "MB not bullish enough for PE fade"

        # ─────────────────────────────────────────────
        # BASIC SAFETY
        # ─────────────────────────────────────────────

        if len(df_5m) < 5 or len(rsi_5m_series) < 5:
            return False, "Not enough data"

        df_5m = df_5m.copy()

        numeric_cols = ['into', 'inth', 'intl', 'close', 'v']
        for col in numeric_cols:
            df_5m[col] = pd.to_numeric(df_5m[col], errors='coerce')

        rsi_5m_series = pd.to_numeric(rsi_5m_series, errors='coerce')

        if df_5m[numeric_cols].isna().any().any() or rsi_5m_series.isna().any():
            return False, "Invalid numeric data"

        # ─────────────────────────────────────────────
        # 1️⃣ SESSION VWAP (INSTITUTIONAL)
        # ─────────────────────────────────────────────
        df_5m['tp'] = (df_5m['inth'] + df_5m['intl'] + df_5m['close']) / 3
        df_5m['pv'] = df_5m['tp'] * df_5m['v']
        df_5m['cum_pv'] = df_5m['pv'].cumsum()
        df_5m['cum_v'] = df_5m['v'].cumsum()
        df_5m['session_vwap'] = df_5m['cum_pv'] / df_5m['cum_v']

        # ─────────────────────────────────────────────
        # LATEST CANDLES
        # ─────────────────────────────────────────────
        c0 = df_5m.iloc[-1]
        c1 = df_5m.iloc[-2]
        c2 = df_5m.iloc[-3]

        price = c0['close']
        vwap0 = c0['session_vwap']
        vwap1 = c1['session_vwap']
        vwap2 = c2['session_vwap']

        # ─────────────────────────────────────────────
        # 2️⃣ PRICE ACCEPTANCE ABOVE VWAP
        # ─────────────────────────────────────────────
        if price <= vwap0 * 1.001:
            return False, "Price clearly below VWAP"

        # ─────────────────────────────────────────────
        # 3️⃣ VWAP SLOPE (NO DISTRIBUTION)
        # ─────────────────────────────────────────────
        if not (vwap0 >= vwap1 >= vwap2 or vwap0 >= vwap1):
            return False, "Session VWAP still falling"

        # ─────────────────────────────────────────────
        # 4️⃣ RSI REGIME + MOMENTUM
        # ─────────────────────────────────────────────
        rsi_regime, rsi_slope = self.detect_rsi_regime(rsi_5m_series)

        r0 = rsi_5m_series.iloc[-1]
        r1 = rsi_5m_series.iloc[-2]
        r2 = rsi_5m_series.iloc[-3]

        higher_low = r1 < r0 and r2 <= r1

        rsi_bullish_pressure = (
            (rsi_regime == "BULL") or
            (higher_low and rsi_slope > 0.8)
        )

        if not rsi_bullish_pressure:
            return False, "No bullish accumulon regime"#"RSI not showing bullish accumulation regime"

        # ─────────────────────────────────────────────
        # 5️⃣ BULLISH CANDLE STRUCTURE
        # ─────────────────────────────────────────────
        body_up = c0['close'] > c0['into']
        candle_range = c0['inth'] - c0['intl']

        close_near_high = (
            (c0['inth'] - c0['close']) / max(candle_range, 1e-6)
        ) < 0.3

        if not (body_up and close_near_high):
            return False, "No bullish candle acceptance"

        # ─────────────────────────────────────────────
        # ✅ ALL CONDITIONS MET
        # ─────────────────────────────────────────────
        return True, "PE FADE → CE ENTRY CONDITIONS MET"

    def detect_rsi_regime(self, rsi_series: pd.Series):
        """
        Detects RSI regime using slope + balance zone
        Returns: (regime: str, rsi_slope: float)
        """

        r0 = rsi_series.iloc[-1]
        r1 = rsi_series.iloc[-2]
        r2 = rsi_series.iloc[-3]

        rsi_slope = (r0 - r2) / 2

        if r0 > 55 and rsi_slope > 0.4:
            return "BULL", rsi_slope

        if r0 < 45 and rsi_slope < -0.4:
            return "BEAR", rsi_slope

        return "RANGE", rsi_slope

    # --- RSI calculation (TradingView / FYERS style) ---
    @staticmethod
    def calculate_rsi(close: pd.Series, period=14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()

        avg_gain = avg_gain.combine_first(gain.ewm(alpha=1/period, adjust=False).mean())
        avg_loss = avg_loss.combine_first(loss.ewm(alpha=1/period, adjust=False).mean())

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    # --- Build 30-min candles for bias ---
    @staticmethod
    def build_30min(df: pd.DataFrame):
        close_30m = (
            df['close']
            .resample(
                '30min',
                label='right',
                closed='right',
                origin='start_day',
                offset='15min'
            )
            .last()
            .dropna()
        )
        return close_30m.iloc[:-1]  # drop running candle

    # --- Detect 30-min RSI divergence ---
    @staticmethod
    def detect_divergence(price: pd.Series, rsi: pd.Series):
        if len(price) < 20:
            return None
        p1, p2 = price.iloc[-3], price.iloc[-1]
        r1, r2 = rsi.iloc[-3], rsi.iloc[-1]

        # Bullish divergence
        if p2 < p1 and r2 > r1 and r2 < 40:
            return "🟢 BULLISH RSI DIVERGENCE (30m)"
        # Bearish divergence
        if p2 > p1 and r2 < r1 and r2 > 60:
            return "🔴 BEARISH RSI DIVERGENCE (30m)"
        return None

    # --- Suggest entry ---
    @staticmethod
    def suggest_entry(rsi_30m_latest, rsi_5m_latest, rsi_5m_prev, rsi_30m_prev=None):
        """
        Enhanced entry suggestion with quality tiers
        Returns: tuple (signal, strength, quality_score)
        """
        rsi_5m_change = rsi_5m_latest - rsi_5m_prev
        rsi_30m_change = rsi_30m_latest - rsi_30m_prev if rsi_30m_prev else 0
        
        # Quality scoring system
        quality_score = 0
        
        # ═══════════════════════════════════════════════
        # CE (CALL) ENTRY LOGIC
        # ═══════════════════════════════════════════════
        
        # TIER 1: EXPLOSIVE CE (Best Quality)
        if (rsi_30m_latest <= 40 and              # Deep oversold on 30m
            48 <= rsi_5m_latest < 55 and          # Tighter sweet spot
            rsi_5m_change > 3 and                 # Strong momentum surge
            rsi_30m_change >= 0):                 # 30m also turning up
            quality_score = 95
            print(f"🔥 EXPLOSIVE CE - RSI30m: {rsi_30m_latest:.1f}, RSI5m: {rsi_5m_latest:.1f}, Δ5m: {rsi_5m_change:.2f}")
            return ("CE Entry Potential", "EXPLOSIVE", quality_score)
        
        # TIER 2: STRONG CE (High Quality)
        if (rsi_30m_latest <= 45 and              # Oversold zone
            45 <= rsi_5m_latest < 58 and          # Setup zone
            rsi_5m_change > 2):                   # Strong momentum
            
            # Bonus: 30m confirming
            if rsi_30m_change > 0:
                quality_score = 85
                print(f"💪 STRONG CE (30m confirmed) - RSI30m: {rsi_30m_latest:.1f}, RSI5m: {rsi_5m_latest:.1f}")
                return ("CE Entry Potential", "STRONG", quality_score)
            else:
                quality_score = 70
                print(f"⚠️ STRONG CE (30m lagging) - RSI30m: {rsi_30m_latest:.1f}, RSI5m: {rsi_5m_latest:.1f}")
                return ("CE Entry Potential", "STRONG_UNCONFIRMED", quality_score)
        
        # TIER 3: MODERATE CE (Medium Quality - Use Smaller Size)
        if (rsi_30m_latest <= 45 and
            45 <= rsi_5m_latest < 58 and
            0 < rsi_5m_change <= 2):              # Weak momentum
            quality_score = 55
            print(f"📊 MODERATE CE - RSI30m: {rsi_30m_latest:.1f}, RSI5m: {rsi_5m_latest:.1f}, Δ5m: {rsi_5m_change:.2f}")
            return ("CE Entry Potential", "MODERATE", quality_score)
        
        # TIER 4: WEAK CE (Low Quality - Skip or Paper Trade)
        if (rsi_30m_latest <= 48 and              # Slightly relaxed
            45 <= rsi_5m_latest < 60 and
            rsi_5m_change > 0 and
            rsi_30m_change < 0):                  # 30m still falling (risky)
            quality_score = 35
            print(f"⚡ WEAK CE (diverging timeframes) - Consider SKIP")
            return ("CE Entry Potential", "WEAK", quality_score)
        
        # ═══════════════════════════════════════════════
        # PE (PUT) ENTRY LOGIC
        # ═══════════════════════════════════════════════
        
        # TIER 1: EXPLOSIVE PE (Best Quality)
        if (rsi_30m_latest >= 60 and              # Deep overbought on 30m
            55 < rsi_5m_latest <= 62 and          # Tighter sweet spot
            rsi_5m_change < -3 and                # Strong momentum drop
            rsi_30m_change <= 0):                 # 30m also turning down
            quality_score = 95
            print(f"🔥 EXPLOSIVE PE - RSI30m: {rsi_30m_latest:.1f}, RSI5m: {rsi_5m_latest:.1f}, Δ5m: {rsi_5m_change:.2f}")
            return ("PE Entry Potential", "EXPLOSIVE", quality_score)
        
        # TIER 2: STRONG PE (High Quality)
        if (rsi_30m_latest >= 55 and              # Overbought zone
            52 < rsi_5m_latest < 65 and           # Setup zone
            rsi_5m_change < -2):                  # Strong momentum
            
            # Bonus: 30m confirming
            if rsi_30m_change < 0:
                quality_score = 85
                print(f"💪 STRONG PE (30m confirmed) - RSI30m: {rsi_30m_latest:.1f}, RSI5m: {rsi_5m_latest:.1f}")
                return ("PE Entry Potential", "STRONG", quality_score)
            else:
                quality_score = 70
                print(f"⚠️ STRONG PE (30m lagging) - RSI30m: {rsi_30m_latest:.1f}, RSI5m: {rsi_5m_latest:.1f}")
                return ("PE Entry Potential", "STRONG_UNCONFIRMED", quality_score)
        
        # TIER 3: MODERATE PE (Medium Quality - Use Smaller Size)
        if (rsi_30m_latest >= 55 and
            52 < rsi_5m_latest < 65 and
            -2 < rsi_5m_change < 0):              # Weak momentum
            quality_score = 55
            print(f"📊 MODERATE PE - RSI30m: {rsi_30m_latest:.1f}, RSI5m: {rsi_5m_latest:.1f}, Δ5m: {rsi_5m_change:.2f}")
            return ("PE Entry Potential", "MODERATE", quality_score)
        
        # TIER 4: WEAK PE (Low Quality - Skip or Paper Trade)
        if (rsi_30m_latest >= 52 and              # Slightly relaxed
            50 < rsi_5m_latest < 65 and
            rsi_5m_change < 0 and
            rsi_30m_change > 0):                  # 30m still rising (risky)
            quality_score = 35
            print(f"⚡ WEAK PE (diverging timeframes) - Consider SKIP")
            return ("PE Entry Potential", "WEAK", quality_score)
        
        # NO VALID ENTRY
        return (None, None, 0)

    # --- Suggest exit for existing position ---
    @staticmethod
    def suggest_exit(position_type, rsi_30m_latest, rsi_5m_latest, divergence):
        suggestion = None

        if position_type == 'CE':
            if rsi_30m_latest > 65 and rsi_5m_latest > 70:
                suggestion = "Exit CE: Overbought"
            elif divergence == "🔴 BEARISH RSI DIVERGENCE (30m)":
                suggestion = "Exit CE: Bearish divergence"
            elif rsi_5m_latest < 40:
                suggestion = "Exit CE: Short-term exhaustion"

        elif position_type == 'PE':
            if rsi_30m_latest < 35 and rsi_5m_latest < 30:
                suggestion = "Exit PE: Oversold / Bounce likely"
            elif divergence == "🟢 BULLISH RSI DIVERGENCE (30m)":
                suggestion = "Exit PE: Bullish divergence"
            elif rsi_5m_latest > 60:
                suggestion = "Exit PE: Short-term exhaustion"

        return suggestion

    @staticmethod
    def calculate_atr_close_only(close, period=14):
        tr = close.diff().abs()
        return tr.rolling(period).mean()

    def stop(self):
        """Stop the thread gracefully."""
        self.running = False
        self.wait()

# ============================================
class NiftySignalGenerator:
    def __init__(self):
        self.symbol = "NIFTY"
        self.strike_step = 50
        self.core_lower = None
        self.core_upper = None
        self.range_initialized = False
        self.last_close_price = None
        self.other_initialized = True
        self.last_logged_state = {
            "core": None,
            "upper": None,
            "lower": None,
            "near_upper": None,
            "near_lower": None,
            "final_signal": None
        }
        self.nse = NseSession()
        self.oc = OptionChainFetcher(self.nse)

    def fetch_option_chain(self):
        """
        Fetch option chain with 5-second cache.
        Returns:
            (filtered_data, spot_price, expiry) or (None, None, None)
        """
        
        # ✅ CHANGED: Check cache first
        cache_key = f"option_chain_{self.symbol}"
        
        # Initialize cache store if needed
        if not hasattr(self, '_oc_cache_store'):
            self._oc_cache_store = DataCache()
        
        cached = self._oc_cache_store.get(cache_key)
        
        if cached:
            #log_message(f"[OC] ✅ Using cached data (age: {time.time() - cached['timestamp']:.1f}s)")
            return cached['data'], cached['spot'], cached['expiry']
        
        # Cache miss - fetch fresh data
        max_attempts = 3
        delay = 2
        #Config.NSE_error = False        
        for attempt in range(max_attempts):
            try:
                # STEP 1: Get nearest valid expiry
                expiry_fetcher = ExpiryFetcher(self.nse)
                expiries = expiry_fetcher.fetch_expiries(self.symbol)

                if not expiries:
                    raise ValueError("No valid expiries available from NSE.")

                expiry = expiries[0]

                # STEP 2: Fetch option chain
                merged_df, spot_price, expiry_norm = self.oc.fetch_option_chain(self.symbol, expiry)

                if merged_df is None:
                    raise ValueError(f"OC empty for expiry {expiry_norm}")

                # ✅ FIX: Keep original data structure for parse_data()
                # The parse_data() expects the original NSE format with 'CE' and 'PE' keys
                # So we need to reconstruct that format from the merged DataFrame
                
                filtered_data = []
                for _, row in merged_df.iterrows():
                    strike = row['strikePrice']
                    
                    # Reconstruct the original nested structure
                    item = {
                        'strikePrice': strike,
                        'expiryDate': expiry_norm,
                        'CE': {},
                        'PE': {}
                    }
                    
                    # Add CE data (columns ending with _CE)
                    for col in merged_df.columns:
                        if col.endswith('_CE') and pd.notna(row[col]):
                            key = col.replace('_CE', '')
                            item['CE'][key] = row[col]
                    
                    # Add PE data (columns ending with _PE)
                    for col in merged_df.columns:
                        if col.endswith('_PE') and pd.notna(row[col]):
                            key = col.replace('_PE', '')
                            item['PE'][key] = row[col]
                    
                    filtered_data.append(item)
                
                # ✅ CHANGED: Cache the result for 5 seconds
                self._oc_cache_store.set(cache_key, {
                    'data': filtered_data,
                    'spot': spot_price,
                    'expiry': expiry_norm,
                    'timestamp': time.time()
                }, ttl=5)
                
                #log_message(f"[OC] ✅ Fresh data fetched and cached ({len(filtered_data)} strikes)")
                Config.NSE_error = False
                return filtered_data, spot_price, expiry_norm

            except Exception as e:
                log_message(f"[OC] ⚠️ Attempt {attempt+1}/{max_attempts} failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(delay)
        
        Config.NSE_error = True
        return None, None, None

    def parse_data(self, data):
        rows = []
        for item in data:
            strike = item['strikePrice']
            ce_coi = item['CE'].get('changeinOpenInterest', 0)
            pe_coi = item['PE'].get('changeinOpenInterest', 0)
            rows.append({"Strike Price": strike, "CE COI": ce_coi, "PE COI": pe_coi})
        return pd.DataFrame(rows)
    
    def get_strike_coi(self, df, strike):
        row = df[df['Strike Price'] == strike]
        if row.empty:
            return 0, 0
        return int(row['CE COI'].values[0]), int(row['PE COI'].values[0])

    def calculate_range_oi(self, df, low, high):
        r = df[(df['Strike Price'] >= low) & (df['Strike Price'] <= high)]
        return r['CE COI'].sum(), r['PE COI'].sum()
        
    def get_signal(self, core_update_allowed=False, core_reset_value=0, intc_value=0):
        try:
            # Signal Decision
            final_signal = "Wait"
            report = ""
            
            now = QTime.currentTime()
            if not (Config.MARKET_CLOSE.msecsSinceStartOfDay() > now.msecsSinceStartOfDay() > Config.MARKET_OPEN.msecsSinceStartOfDay()):
                return "wait", f"Core Range: {self.core_lower} - {self.core_upper}\nTime- {datetime.datetime.now().strftime('%H:%M:%S')} - Market is closed.", 0, 0, 0, 0
            
            option_data, spot_price, _ = self.fetch_option_chain()
            if option_data is None or spot_price is None:
                return "wait", f"Core Range: {self.core_lower} - {self.core_upper}\nFailed to fetch option chain data", 0, 0, 0, 0
                
            df = self.parse_data(option_data)

            # Core range initialization
            if not self.range_initialized:
                if spot_price is None:
                    raise ValueError("Spot price is None during first core initialization.")
                base_strike = int(math.floor(spot_price / 100) * 100)
                self.core_lower = base_strike
                self.core_upper = base_strike + 100
                self.last_close_price = spot_price
                self.range_initialized = True

            # Core range update if allowed
            if core_update_allowed and (spot_price < self.core_lower or spot_price > self.core_upper):
                base_price = spot_price
                base_strike = int(math.floor(base_price / 100) * 100)
                self.core_lower = base_strike
                self.core_upper = base_strike + 100
                self.last_close_price = spot_price
                self.range_initialized = True

            # Core range reset if allowed
            if core_reset_value != 0 and core_update_allowed:
                base_price = core_reset_value
                base_strike = int(math.floor(base_price / 100) * 100)
                self.core_lower = base_strike
                self.core_upper = base_strike + 100
                self.last_close_price = core_reset_value
                self.range_initialized = True

            # Get COI values
            lower_ce, lower_pe = self.get_strike_coi(df, self.core_lower)
            upper_ce, upper_pe = self.get_strike_coi(df, self.core_upper)
            core_ce, core_pe = self.calculate_range_oi(df, self.core_lower, self.core_upper)
            
            # Sentiment Calculation
            core_sentiment = "Bullish" if core_ce < core_pe else "Bearish" if core_pe < core_ce else "Not Confirm"
            upper_sentiment = "Bullish" if upper_ce < upper_pe else "Bearish" if upper_pe < upper_ce else "Not Confirm"
            lower_sentiment = "Bullish" if lower_ce < lower_pe else "Bearish" if lower_pe < lower_ce else "Not Confirm"
            
            if self.core_lower is not None  and self.core_upper is not None:
                upper_core_ce, upper_core_pe = self.calculate_range_oi(df, self.core_upper, self.core_upper + 100)
                lower_core_ce, lower_core_pe = self.calculate_range_oi(df, self.core_lower - 100, self.core_lower)
                upper_core_sentiment = "Bullish" if upper_core_ce < upper_core_pe else "Bearish" if upper_core_pe < upper_core_ce else "Not Confirm"
                lower_core_sentiment = "Bullish" if lower_core_ce < lower_core_pe else "Bearish" if lower_core_pe < lower_core_ce else "Not Confirm"
           
                # Proximity Check
                near_upper = False
                near_lower = False
                if intc_value != 0:
                    price = intc_value
                    proximity_threshold = 5
                    near_upper = abs(price - self.core_upper) <= proximity_threshold
                    near_lower = abs(price - self.core_lower) <= proximity_threshold


                # Buy PE logic
                if core_sentiment == "Bearish":
                    if upper_sentiment == "Bearish" and lower_sentiment == "Bearish" and (near_upper or near_lower or self.core_lower < spot_price < self.core_upper):
                        final_signal = "Buy PE"
                    elif upper_sentiment == "Bearish" and lower_sentiment == "Bullish":
                        if near_upper:
                            final_signal = "Buy PE"
                        elif near_lower:
                            final_signal = "Wait"
                    elif upper_sentiment == "Bullish" and lower_sentiment == "Bearish":
                        if near_lower:
                            final_signal = "Buy PE"
                        elif near_upper:
                            final_signal = "Wait"
                            
                # Buy CE logic
                elif core_sentiment == "Bullish":
                    if upper_sentiment == "Bullish" and lower_sentiment == "Bullish" and (near_upper or near_lower or self.core_lower < spot_price < self.core_upper):
                        final_signal = "Buy CE"
                    elif upper_sentiment == "Bearish" and lower_sentiment == "Bullish":
                        if near_lower:
                            final_signal = "Buy CE"
                        elif near_upper:
                            final_signal = "Wait"
                    elif upper_sentiment == "Bullish" and lower_sentiment == "Bearish":
                        if near_upper:
                            final_signal = "Buy CE"
                        elif near_lower:
                            final_signal = "Wait"

            
                current_state = {
                    "core": core_sentiment,
                    "upper": upper_sentiment,
                    "lower": lower_sentiment,
                    "near_upper": near_upper,
                    "near_lower": near_lower,
                    "final_signal": final_signal
                }

                if current_state != self.last_logged_state:
                    self.last_logged_state = current_state.copy()
                    msg = "+++++++++++++++++++++++++++++++++++++++ \n"
                    msg += f"Core Range: {self.core_lower} - {self.core_upper} \n"
                    msg += f"Upper Boundary: {self.core_upper} {upper_sentiment} ({near_upper})\n"
                    msg += f"Range COI: {core_sentiment} \n"
                    msg += f"Lower Boundary: {self.core_lower} {lower_sentiment} ({near_lower}) \n"
                    msg += f"Final Signal: {final_signal} \n"
                    #msg += f"30 min RSI = {Config.RSI_GLOBAL} \n"
                    log_message(msg)

                    # Prepare detailed COI report
                report = f"""
    🧠 Signal Time: {datetime.datetime.now().strftime('%H:%M:%S')} , 📲📲📲 Core Range: {self.core_lower} - {self.core_upper}
    Upper Core → {upper_core_sentiment} {"✅" if spot_price > self.core_upper else ""}
    🔺Upper Boundary: {self.core_upper} PE COI: {upper_pe:,}, CE COI: {upper_ce:,} → {upper_sentiment} {"✅" if near_upper else ""}
    Core Range COI = PE COI: {core_pe:,.2f}, CE COI: {core_ce:,.2f} → {core_sentiment}
    🔻Lower Boundary: {self.core_lower} PE COI: {lower_pe:,}, CE COI: {lower_ce:,} → {lower_sentiment}  {"✅" if near_lower else ""}
    Lower Core → {lower_core_sentiment} {"✅" if spot_price < self.core_lower else ""}
    📲📲📲📲📲📲📲📲📲 ➡️ Final Signal: {final_signal}
    """.strip()
            
                if final_signal == "Buy CE" and core_sentiment != "Bullish":
                    #log_message("Invalid Signal: Buy CE generated when core is not Bullish – Overriding to Wait")
                    final_signal = "Wait"

                if final_signal == "Buy PE" and core_sentiment != "Bearish":
                    #log_message("Invalid Signal: Buy PE generated when core is not Bearish – Overriding to Wait")
                    final_signal = "Wait"

            return final_signal, report, upper_ce, upper_pe, lower_ce, lower_pe

        except Exception as e:
            log_message(f"[ERROR] get_signal: {e}")
            return "Wait", f"Error fetching signal: {e}", 0, 0, 0, 0

# ============================================
class SignalThread(QThread):
    signal_result = pyqtSignal(tuple)
    core_update_signal = pyqtSignal(bool)
    core_reset_signal = pyqtSignal(int)
    core_intc_signal = pyqtSignal(int) 

    def __init__(self, signal_generator, parent=None):
        super().__init__(parent)
        self.signal_generator = signal_generator
        self.running = True
        self.core_reset_value = 0
        self.core_intc_value = 0
        self.core_update_allowed_Qthread = False
        self.core_update_signal.connect(self.set_core_update_flag)
        self.core_reset_signal.connect(self.set_core_reset_spot)
        self.core_intc_signal.connect(self.set_core_intc)

    def set_core_update_flag(self, value):
        self.core_update_allowed_Qthread = value
        log_message(f"[THREAD] core_update_allowed set to {value}")
    
    def set_core_reset_spot(self, value):
        self.core_reset_value = value
        log_message(f"[THREAD] core reset to {value}")
    
    def set_core_intc(self, value):
        self.core_intc_value = value

    def run(self):
        while self.running:
            try:
                reset_value = self.core_reset_value
                signal = self.signal_generator.get_signal(
                    self.core_update_allowed_Qthread,
                    reset_value,
                    self.core_intc_value
                )
                if isinstance(signal, tuple):
                    self.signal_result.emit(signal)
                else:
                    self.signal_result.emit((signal, "", 0, 0, 0, 0))

                if reset_value != 0 and self.core_update_allowed_Qthread:
                    self.core_reset_value = 0
                    self.core_update_allowed_Qthread = False
                    self.core_update_signal.emit(False)

                time.sleep(1)
            except Exception as e:
                log_message(f"[ERROR] SignalThread: {e}")

    def stop(self):
        self.running = False
        self.quit()
        self.wait()

# ============================================
class ATMStrikePriceFinder(QWidget):
    
    # Signal for thread-safe NIFTY updates
    nifty_update_signal = pyqtSignal(float)
    
    def __init__(self):
        super().__init__()
        # Core members
        self.multimgr = MultiAccountManager(creds_dir='creds')
        self.api_master = self.multimgr.get_master_api()
        self.accounts = self.multimgr.accounts
        self.master_user = self.multimgr.master_user
        print("Initializing NSE session...")
        self.nse = NseSession()
        self.ef = ExpiryFetcher(self.nse)
        self.sf = SymbolFetcher(self.nse)

        # ✅ ADD THIS: Create thread pool for API calls
        self.api_threadpool = QThreadPool()
        self.api_threadpool.setMaxThreadCount(15)  # Allow up to 10 concurrent API calls
        log_message(f"[INIT] API ThreadPool initialized with {self.api_threadpool.maxThreadCount()} threads")
        
        # UI Update Throttler to prevent excessive GUI updates
        self.ui_throttler = UIUpdateThrottler(min_interval_ms=100)
        
        # ✅ ADD THIS: Dictionary to track pending LTP requests (prevent duplicates)
        self.pending_ltp_requests = {}

        # ✅ ADD: Initialize data cache
        self.data_cache = DataCache()
        log_message("[INIT] Data cache initialized")
        
        # ✅ ADD: Thread executor for parallel operations
        self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="MultiAccount")
        log_message("[INIT] Thread executor initialized with 10 workers")
        
        # ✅ ADD: Cache statistics timer (log stats every 5 minutes)
        self.cache_stats_timer = QTimer(self)
        self.cache_stats_timer.timeout.connect(self._log_cache_stats)
        self.cache_stats_timer.start(300000)  # 5 minutes

        # ✅ ADD: Initialize market memory for bias tracking
        now = datetime.datetime.now()
        self.market_memory = {
            "bias_score": 0,
            "start_time": now.replace(hour=9, minute=0, second=0),
            "last_update": None
        }
        self._last_30m_rsi_len = 0
        log_message("[INIT] Market memory initialized")

        self.lot_size = int(Config.LOT_SIZE)
        self.indexStrikeDiff = Config.INDEX_STRIKE_DIFF

        self.prev_candle = None
        self.structure_break_up = False
        self.structure_break_down = False
        self.in_whipsaw_zone = False
        self.valid_breakout = False
        self.structure_strength = 0
        self.bullish_setup_armed = False
        self.bearish_setup_armed = False
        self.bullish_setup_time = None
        self.bearish_setup_time = None

        # Trading state variables
        self.netQty = 0
        self.netavgprc = 0.0
        self.tysm_list = []
        self.sell_stat = None
        self.ltp_ready = False

        self.PE_buy_flag = False
        self.CE_buy_flag = False
        self.PE_buy_avgltp = 0.0
        self.CE_buy_avgltp = 0.0
        self.PE_order_flag = False
        self.CE_order_flag = False
        self.bigProfit_flag = True
        self.gann_levels = []
        self.closest_Gann_level = 0
        self.timer_thread_started = False

        # Common variables
        self.common_symbol = None
        self.common_orderID = None
        self.common_avgLTP = 0.0
        self.common_token = None
        self.common_sellLTP = None
        self.common_currLTP = 0.0

        # ✅ NEW: Order Mapping System
        self.position_orders = {}  # {symbol: {'entry': {...}, 'target': {...}, 'stoploss': {...}, 'exit': {...}}}
        self.position_state = 'IDLE'  # IDLE, OPEN_UNPROTECTED, OPEN_WITH_TARGET, OPEN_WITH_STOPLOSS, FILLING_MANUALLY, CLOSED
        self.target_info = {
            'target_set': False
        }
        self.stoploss_info ={
            'stoploss_set': False
        }

        self.act_divergence = None
        self.act_entry = None
        self.act_ce_exit = None
        self.act_pe_exit = None
        self.act_option_action = None
        self.last_logged_act_state = {}
        self.position_lots = 0
        self.rsi_30min = 0.0
        self.rsi_5min = 0.0
        self.prev_rsi_5m = 0.0
        self.prev_rsi_30m = 0.0
        self.entry_rsi_5m = 0.0
        self.entry_rsi_30m = 0.0
        self.repeatRSIautoTrade = False
        self._last_market_status = None

        # PnL tracking
        self.PnL = 0.0
        self.PnL2 = 0.0
        self.PnlPer = 0.0
        self.PnlPer_Deli = 0.0
        self.Total_mtm = 0.0
        self.rpnl = 0.0

        # Delivery variables
        self.Deli_common_currLTP = 0.0
        self.CE_Deli_Buy_symbol = None
        self.PE_Deli_Buy_symbol = None
        self.CE_Deli_lot_number = 0
        self.PE_Deli_lot_number = 0
        self.CE_Deli_buy_avgltp = 0
        self.PE_Deli_buy_avgltp = 0
        self.Deli_common_orderID = None
        self.Deli_common_symbol = None
        self.Deli_common_token = None 
        self.Deli_common_avgLTP = 0.0
        self.Deli_netQty = 0
        self.fut_token = None
        self.last_divergence = None
        self.divergence_change_time = None
        self.last_entry = None
        self.entry_change_time = None
        self.last_ce_exit = None
        self.ce_exit_change_time = None
        self.last_pe_exit = None
        self.pe_exit_change_time = None
        self.entry_underlying_at_buy = 0.0

        self.session = requests.Session()
        
        # Window setup
        self.setWindowTitle(f"AlgoNIFTY Advance V-{Config.version} - {Config.name}")   
        self.setWindowIcon(QIcon("gann_COI.ico"))

        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        w, h = screen_geometry.width(), screen_geometry.height()
        self.setGeometry(int(w * 0.05), int(h * 0.05), int(w * 0.9), int(h * 0.9))

        # DPI-based font scaling
        def font_scaled(pt=12):
            return QFont("Arial", int(self.logicalDpiX() / (96 / pt)))

        def make_expanding(widget, pt=12):
            widget.setFont(font_scaled(pt))
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # Main layout with scroll
        layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

        main_layout = QVBoxLayout(scroll_widget)

        # Decide colors independently - set to system default with fallback
        '''try:
            palette = self.palette()
            default_text_color = palette.color(QPalette.ColorRole.WindowText).name()
        except Exception:
            default_text_color = "white"  # Fallback to white if palette access fails
        '''
        default_text_color = "white"
        self.color_30 = default_text_color
        self.color_5 = default_text_color
        self.color_intc = default_text_color
        # Header layout
        self.header_layout = QHBoxLayout()
        self.time_label = QLabel("Time: ")
        self.currNifty = QLabel("Nifty: ")
        self.RSI_label = QLabel("RSI:")
        self.divergence_label = QLabel("")        
        self.entery_suggestion_label = QLabel("")
        self.CE_exit_signal_label = QLabel("")
        self.PE_exit_signal_label = QLabel("")
        self.divergence_label.setStyleSheet("color: Blue")
        #self.entery_suggestion_label.setStyleSheet("color: blue")
        self.CE_exit_signal_label.setStyleSheet("color: Red")
        self.PE_exit_signal_label.setStyleSheet("color: blue")
        self.market_mindset_label = QLabel("Market Mindset")

        for label in [self.time_label, self.currNifty,  
                      self.divergence_label, self.entery_suggestion_label, 
                      self.CE_exit_signal_label, self.PE_exit_signal_label,
                      self.RSI_label, self.market_mindset_label
                      ]:
            
            make_expanding(label, 11)
            self.header_layout.addWidget(label)

        main_layout.addLayout(self.header_layout)

        # Checkbox layout
        h1_layout = QHBoxLayout()
        self.index_label = QLabel("Index : ")
        self.symbol_input = QComboBox(self)
        self.symbol_input.addItems(["NIFTY"])
        self.symbol_input.currentIndexChanged.connect(self.symbol_changed)
        
        # Initialize expiry dates immediately after adding symbol
        try:
            log_message("[INIT] Initializing expiry dates on startup...")
            print("[INIT_DEBUG] Checking if self.ef exists...")
            if not hasattr(self, 'ef'):
                log_message("[INIT] ⚠️ self.ef does not exist yet, skipping early expiry fetch")
                print("[INIT_DEBUG] self.ef does not exist")
            else:
                print("[INIT_DEBUG] self.ef exists, fetching expiry dates...")
                self.fetch_expiry_dates("NIFTY")
                print("[INIT_DEBUG] Expiry fetch completed")
        except Exception as e:
            log_message(f"[INIT] ❌ Failed to initialize expiry dates: {e}")
            print(f"[INIT_DEBUG] Exception: {e}")
            import traceback
            traceback.print_exc()
        
        self.expiry_label = QLabel("Expiry :-")
        self.expiry_input = QComboBox(self)
        
        # Populate expiry dates if they were cached during early fetch
        if hasattr(self, '_cached_expiry_dates') and self._cached_expiry_dates:
            log_message("[INIT] Populating cached expiry dates")
            self.expiry_input.addItems(self._cached_expiry_dates)

        self.Re_entry_label = QLabel("Re-entry :-")

        self.lotNo_label = QLabel("Lot Number :-")
        self.lot_number = QComboBox(self)
        self.lot_number.addItems(["1","2","3","4","5","6","7","8","9","10"])
        self.lot_number.setCurrentText("4")

        self.autoTrade_checkbox = QCheckBox('Auto Trade')
        self.autoTrade_checkbox.setToolTip("If *autoTrade* in yml file was set to *True*.\n " \
                                           "Auto Trade is activated between 9:20 to 9:30 hrs.\n" \
                                            "Trade will be placed as per GANN levels and COI.")
        self.autoTrade_checkbox.setChecked(False)
        self.RSI_autoTrade_checkbox = QCheckBox('AutoTrade (RSI)')
        self.RSI_autoTrade_checkbox.setToolTip("Trade will be placed automatically as per Nifty-Future RSI.\n" \
                                               "Trade will manage as per RSI action.")
        self.RSI_autoTrade_checkbox.setChecked(False)
        self.PaperTrade_checkbox = QCheckBox('Paper Trade')
        self.PaperTrade_checkbox.setChecked(True)

        for label in [self.index_label, self.symbol_input, self.expiry_label, self.expiry_input, self.Re_entry_label,
                      #self.default_SL_lable, self.TSL_checkbox, self.FirstOTM_checkbox, self.FirstITM_checkbox, self.ThirdOTM_checkbox,
                      self.lotNo_label, self.lot_number, 
                      self.autoTrade_checkbox,self.RSI_autoTrade_checkbox, self.PaperTrade_checkbox]:
            make_expanding(label, 9)
            h1_layout.addWidget(label)

        main_layout.addLayout(h1_layout)

        # Level and lot layout
        self.level_lot_layout = QHBoxLayout()

        self.default_SL_lable = QLabel("SL @ buy after T1 (default)")
        self.TSL_checkbox = QCheckBox('TSL ')
        self.TSL_checkbox.setToolTip("Gann Level Trailing Stoploss")
        self.TSL_checkbox.setChecked(False)
        self.FirstOTM_checkbox = QCheckBox("1-OTM")
        self.FirstOTM_checkbox.setChecked(False)
        self.FirstITM_checkbox = QCheckBox("1-ITM")
        self.FirstITM_checkbox.setChecked(False)
        self.ThirdOTM_checkbox = QCheckBox("Delivery, ") #next week 3 OTM
        self.ThirdOTM_checkbox.setToolTip("Next week 3rd OTM for CNC.")
        self.ThirdOTM_checkbox.setChecked(False)
        self.level_lot_layout.addWidget(self.default_SL_lable)
        self.level_lot_layout.addWidget(self.TSL_checkbox)
        self.level_lot_layout.addWidget(self.FirstOTM_checkbox)
        self.level_lot_layout.addWidget(self.FirstITM_checkbox)
        self.level_lot_layout.addWidget(self.ThirdOTM_checkbox)

        self.CL_lable = QLabel("Closest Level: ")
        #self.CL_lable.setFont(QFont("Arial", 13))
        self.level_lot_layout.addWidget(self.CL_lable)

        self.T1level_label = QLabel("T1 Level: -")
        self.T1level_label.setStyleSheet("color: Red")
        self.T1level_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.level_lot_layout.addWidget(self.T1level_label)

        self.rev_label = QLabel("Reversal Level: -")
        #self.rev_label.setFont(QFont("Arial", 13))
        self.level_lot_layout.addWidget(self.rev_label)

        # Override frame
        self.override_frame = QFrame()
        self.override_frame.setStyleSheet("""
            QFrame {
                border: 2px solid red;
                border-radius: 6px;
                padding: 4px;
            }
        """)

        override_layout = QHBoxLayout()
        override_layout.setContentsMargins(5, 5, 5, 5)
        override_layout.setSpacing(5)

        self.dir_label = QLabel("Direction - ")
        #make_expanding(self.dir_label, 10)
        self.direction_box = QComboBox()
        self.direction_box.addItems(["up", "down"])
        make_expanding(self.direction_box, 10)
        self.level_box = QComboBox()
        self.level_box.setFixedWidth(100)
        make_expanding(self.level_box, 10)
        self.override_btn = QPushButton("Override")
        self.override_btn.setToolTip("Manually override the Reversal GANN level.")
        make_expanding(self.override_btn, 10)
        self.override_btn.clicked.connect(self.manual_override)

        override_layout.addWidget(self.dir_label)
        override_layout.addWidget(self.direction_box)
        override_layout.addWidget(self.level_box)
        override_layout.addWidget(self.override_btn)

        self.coreReset_button = QPushButton("Reset Core")
        self.coreReset_button.setToolTip("Correct the market opening core range, if not properly detected.")
        self.coreReset_button.clicked.connect(self.reset_core)
        make_expanding(self.coreReset_button, 10)
        override_layout.addWidget(self.coreReset_button)

        self.override_frame.setLayout(override_layout)
        self.level_lot_layout.addWidget(self.override_frame)

        # Button to force-refresh NSE session & caches without restarting the app
        self.refresh_nse_button = QPushButton('Refresh NSE')
        self.refresh_nse_button.setToolTip('Reinitialize NSE session and clear NSE caches')
        self.refresh_nse_button.clicked.connect(self.refresh_nse)
        override_layout.addWidget(self.refresh_nse_button)

        main_layout.addLayout(self.level_lot_layout)

        self.login_button = QPushButton('Login to FYERS')
        self.login_button.clicked.connect(self.execute_login_at_9am)
        self.level_lot_layout.addWidget(self.login_button)

        # Exit buttons layout
        self.Exit_CE_PE_layout = QHBoxLayout()
        self.lmtbuy_lable = QLabel("LMT buy= ")
        self.lmtbuy_lable.setFixedWidth(100)
        self.entry_price = QLineEdit()
        self.entry_price.setFixedWidth(100)
        self.entry_price.setText('')

        self.MY_PE_buy_button = QPushButton('&PE Buy')
        self.MY_PE_buy_button.setStyleSheet("border: 2px solid red;")
        self.MY_PE_buy_button.setEnabled(False)
        self.MY_PE_buy_button.clicked.connect(self.PE_buy_manual)

        self.MY_CE_buy_button = QPushButton('&CE Buy')
        self.MY_CE_buy_button.setEnabled(False)
        self.MY_CE_buy_button.setStyleSheet("border: 2px solid red;")
        self.MY_CE_buy_button.clicked.connect(self.CE_buy_manual)

        self.squareoff_lots = QLineEdit()
        self.squareoff_lots.setToolTip("Enter lot number to be squared off (MIS Exit/Target/Stoploss).")
        self.squareoff_lots.setFixedWidth(75)
        self.squareoff_lots.setText('')

        self.MIS_exit_button = QPushButton('&MIS Exit')
        self.MIS_exit_button.setEnabled(False)
        self.MIS_exit_button.setStyleSheet("border: 2px solid red;")
        self.MIS_exit_button.clicked.connect(self.manual_exit)
    
        self.exitCNC_button = QPushButton('Exit &CNC')
        self.exitCNC_button.setEnabled(False)
        self.exitCNC_button.setStyleSheet("border: 2px solid red;")
        self.exitCNC_button.clicked.connect(self.exitCNC)
             
        self.reset_button = QPushButton('&Reset')
        self.reset_button.setStyleSheet("border: 2px solid red;")
        if not Config.manual_override:
            self.reset_button.setEnabled(False)
        self.reset_button.clicked.connect(self.reset_all)

        self.target_lable = QLabel("Target price= ")
        self.target_entry = QLineEdit()
        self.target_entry.setFixedWidth(100)
        self.target_entry.setToolTip("Enter target price for the open position in value or %.")
        self.target_button = QPushButton('Set &Target')
        self.target_button.setEnabled(False)
        self.target_button.setStyleSheet("border: 2px solid red;")
        self.target_button.clicked.connect(self.manual_set_target)
        self.Target_order_flag = False
        
        self.stoploss_lable = QLabel("Stoploss price= ")
        self.stoploss_entry = QLineEdit()
        self.stoploss_entry.setFixedWidth(100)
        self.stoploss_entry.setToolTip("Enter stoploss price for the open position in value or %.")
        self.stoploss_button = QPushButton('&Set SL')
        self.stoploss_button.setEnabled(False)
        self.stoploss_button.setStyleSheet("border: 2px solid red;")
        self.stoploss_button.clicked.connect(self.manual_set_stoploss)
        self.SL_order_flag = False

        for label in [self.exitCNC_button, self.lmtbuy_lable, self.entry_price, self.MY_PE_buy_button, 
                      self.MY_CE_buy_button, self.squareoff_lots, self.MIS_exit_button,  
                      self.reset_button, self.target_lable, self.target_entry, self.target_button, 
                      self.stoploss_lable, self.stoploss_entry, self.stoploss_button]:
            make_expanding(label, 11)
            self.Exit_CE_PE_layout.addWidget(label)

        main_layout.addLayout(self.Exit_CE_PE_layout)

        # Analysis output and order labels
        self.analysis_output = QTextEdit()
        self.analysis_output.setReadOnly(True)
        self.analysis_output.setFont(QFont("Courier", 10))

        self.V1_layout = QVBoxLayout()
        self.order_label = QLabel()
        self.order_label.setFont(QFont("Arial", 14))
        self.order_label.setText("MIS Trade -")
        self.order_label.setToolTip("Blue color text indicates partial profit was booked.\n" \
                                    "and stoploss order is placed at buy price, trade is left free till 15 hrs.")
        self.V1_layout.addWidget(self.order_label)

        self.Deli_order_label = QLabel()
        self.Deli_order_label.setFont(QFont("Arial", 14))
        self.Deli_order_label.setText("CNC Trade -")
        self.V1_layout.addWidget(self.Deli_order_label)

        self.RSI_action_label = QLabel()
        self.RSI_action_label.setFont(QFont("Arial", 12))
        self.RSI_action_label.setText("")
        self.RSI_action_label.setToolTip("CE Entry Potential - 30min RSI <= 45 and 45 <= 5min RSI < 58 and 5min RSI is increasing.\n"
                                         "PE Entry Potential - 30min RSI >= 55 and 52 < 5min RSI < 65 and 5min RSI is decreasing.\n"
                                        )
        
        self.V1_layout.addWidget(self.RSI_action_label)

        # COI checkboxes
        self.coi_checkbox_1min = QCheckBox("1-min")
        self.coi_checkbox_3min = QCheckBox("3-min")
        self.coi_checkbox_5min = QCheckBox("5-min")

        self.coi_checkbox_1min.setChecked(True)
        self.coi_checkbox_3min.setChecked(False)
        self.coi_checkbox_5min.setChecked(False)

        self.coi_checkbox_1min.stateChanged.connect(self.refresh_coi_plot)
        self.coi_checkbox_3min.stateChanged.connect(self.refresh_coi_plot)
        self.coi_checkbox_5min.stateChanged.connect(self.refresh_coi_plot)

        self.autoSquareOff_checkbox = QCheckBox('Auto Square-Off @ 15:00 hr')
        self.autoSquareOff_checkbox.setFont(QFont("Arial", 11))
        self.autoSquareOff_checkbox.setChecked(True)

        self.oneHourRule_checkbox = QCheckBox('1 hour square-off')
        self.oneHourRule_checkbox.setToolTip("All position will square-off if T1 level is not reached within one hour.")
        self.oneHourRule_checkbox.setFont(QFont("Arial", 11))
        self.oneHourRule_checkbox.setChecked(True)
        
        checkbox_layout = QHBoxLayout()
        checkbox_layout.addWidget(QLabel("Graph Time:"))
        checkbox_layout.addWidget(self.coi_checkbox_1min)
        checkbox_layout.addWidget(self.coi_checkbox_3min)
        checkbox_layout.addWidget(self.coi_checkbox_5min)
        checkbox_layout.addWidget(self.autoSquareOff_checkbox)
        checkbox_layout.addWidget(self.oneHourRule_checkbox)
        #checkbox_layout.addWidget(self.MTM_lable)

        self.V1_layout.addLayout(checkbox_layout)
        
        output_layout = QHBoxLayout()
        make_expanding(self.analysis_output, 9)
        output_layout.addWidget(self.analysis_output, stretch=2)
        output_layout.addLayout(self.V1_layout, stretch=4)

        main_layout.addLayout(output_layout)

        # COI plots (side-by-side)
        self.upper_plot = pg.PlotWidget(title="Upper Boundary COI")
        self.upper_plot.addLegend()
        self.upper_plot.setLabel('left', 'COI')
        self.upper_plot.setLabel('bottom', 'Time')
        self.upper_plot.showGrid(x=True, y=True)

        self.lower_plot = pg.PlotWidget(title="Lower Boundary COI")
        self.lower_plot.addLegend()
        self.lower_plot.setLabel('left', 'COI')
        self.lower_plot.setLabel('bottom', 'Time')
        self.lower_plot.showGrid(x=True, y=True)

        self.upper_ce_line = self.upper_plot.plot(pen='g', name='Upper CE')
        self.upper_pe_line = self.upper_plot.plot(pen='r', name='Upper PE')
        self.lower_ce_line = self.lower_plot.plot(pen='g', name='Lower CE')
        self.lower_pe_line = self.lower_plot.plot(pen='r', name='Lower PE')

        plot_layout = QHBoxLayout()
        plot_layout.addWidget(self.upper_plot)
        plot_layout.addWidget(self.lower_plot)

        main_layout.addLayout(plot_layout)

        # Initialize data holders
        self.time_points = []
        self.upper_ce_data = []
        self.upper_pe_data = []
        self.lower_ce_data = []
        self.lower_pe_data = []

        self.coi_data_points = deque(maxlen=400)
        self.last_coi_plot_time = None

        self.logout_flag = False
        self.login_flag = False
        self._login_in_progress = False
        self._last_login_completed_ts = 0.0

        self.intc_value = 0
        self.intc_thread = None
        self.T1Level = 0
        self.targetLTP = 0
        self.stoplossLTP = 0
        self.core_update_allowed = False
        self.last_rsi_impulse_direction = None
        # "UP", "DOWN", or None

        self.open_915 = 0.0
        self.high_915 = 0.0
        self.low_915 = 0.0
        self.close_915 = 0.0

        self.ltp_data = {}
        self.token_map = {}
        self.lock = threading.Lock()
        self.subscribe_symbols = set()
        self.token_to_symbol = {}
        self.symbol_to_strike = {}
        # track whether we've successfully opened a websocket
        self.websocket_connected = False
        # Guard websocket startup so FYERS socket is started only once per session.
        self._ws_start_lock = threading.Lock()
        self._ws_started = False
        self._ws_recovering = False
        self._ws_disconnected_since = None
        self._ws_last_reset_ts = 0.0
        self._atm_cache = {'NIFTY': (0, 0.0), 'BANKNIFTY': (0, 0.0)}
        self._atm_last_error_ts = 0.0

        self.symbol_qty_map = {}
        self.symbol_avg_map = {}

        self.PE_order_time = None
        self.CE_order_time = None
        self.core_lower = 0
        self.core_upper = 0

        # ✅ store active order context
        self.active_order_id = None
        self.active_order_side = None   # or "CE"
        self.active_order_symbol = None
        self.waiting_for_fill = False

        # Guard to avoid scheduling multiple concurrent exits
        self._exit_scheduled = False

        self.range_initialized = False
        self.last_close_price = None
        self.last_logged_act_state
        self.current_direction = None
        self.reversal_gann_level = None
        self.last_gann_broken = None
        self.last_price = None
        self.reversal_initialized = False
        self.zone = None
        self.final_signal = "Wait"
        self.last_plot_update_time: Dict[int, Optional[datetime.datetime]] = {1: None, 3: None, 5: None}

        self.curr_candle = {"o": None, "h": -float('inf'), "l": float('inf'), "c": None}
        self.last_candle_time = None

        # Initialize timer (FIXED - only once)
        self.timer_CL = QTimer(self)
        self.timer_CL.timeout.connect(self.show_closest_level)
        self.ws_watchdog_timer = QTimer(self)
        self.ws_watchdog_timer.timeout.connect(self.websocket_health_check)
        self.ws_watchdog_timer.start(5000)
        
        # Connect signal for thread-safe NIFTY updates
        self.nifty_update_signal.connect(self.update_nifty_display)
        
        self.execute_login_at_9am()
        
        self.signal_generator = NiftySignalGenerator()
        self.signal_thread = SignalThread(self.signal_generator)
        self.signal_thread.signal_result.connect(self.handle_signal_result)
        self.signal_thread.start()

        # Connect toggle functionality
        self.autoTrade_checkbox.stateChanged.connect(self.on_autoTrade_changed)
        self.RSI_autoTrade_checkbox.stateChanged.connect(self.on_RSI_autoTrade_changed)

    def update_nifty_display(self, intc_value):
        """Thread-safe NIFTY display update"""
        try:
            # Update intc_value
            self.intc_value = intc_value
            
            # Determine color based on change
            if not hasattr(self, '_last_intc_value'):
                self._last_intc_value = intc_value
                self.color_intc = "white"
            elif intc_value > self._last_intc_value:
                self.color_intc = "green"
            elif intc_value < self._last_intc_value:
                self.color_intc = "red"
            # If equal, keep previous color
            
            self._last_intc_value = intc_value
            
            # Update GUI
            self.currNifty.setText(
                f'Nifty: '
                f'<span style="color:{self.color_intc}">{intc_value}</span>'
            )
            #log_message(f"[NIFTY_UPDATE] GUI updated to: {intc_value}")
        except Exception as e:
            log_message(f"[ERROR] update_nifty_display: {e}")

    # Method 1: Toggle handler for Auto Trade checkbox
    def on_autoTrade_changed(self, state):
        """Handle Auto Trade checkbox state change"""
        if state == Qt.CheckState.Checked:
            # If Auto Trade is checked, uncheck RSI AutoTrade
            if self.RSI_autoTrade_checkbox.isChecked():
                self.RSI_autoTrade_checkbox.blockSignals(True)  # Prevent signal loop
                self.RSI_autoTrade_checkbox.setChecked(False)
                self.RSI_autoTrade_checkbox.blockSignals(False)
            log_message("Auto Trade enabled")
        else:
            log_message("Auto Trade disabled")

    # Method 2: Toggle handler for RSI AutoTrade checkbox
    def on_RSI_autoTrade_changed(self, state):
        """Handle RSI AutoTrade checkbox state change"""
        if state == Qt.CheckState.Checked:
            # If RSI AutoTrade is checked, uncheck Auto Trade
            if self.autoTrade_checkbox.isChecked():
                self.autoTrade_checkbox.blockSignals(True)  # Prevent signal loop
                self.autoTrade_checkbox.setChecked(False)
                self.autoTrade_checkbox.blockSignals(False)
            log_message("AutoTrade (RSI) enabled")
        else:
            log_message("AutoTrade (RSI) disabled")

    def set_position_lots(self, lots):
        """Helper to set integer lots and derived netQty consistently.

        The application tracks quantity in multiple places: ``position_lots``
        and ``netQty`` for internal logic, and ``symbol_qty_map`` for broker
        reconciliation.  Historically the map was only updated when fills were
        confirmed via ``place_and_confirm`` which meant any manual adjustments
        (e.g. half exits) could desync and lead to downstream routines such as
        ``CE_PE_exit`` using stale values.  To avoid that we synchronise the
        map here whenever a symbol is known.
        """
        try:
            lots_int = int(lots)
        except Exception:
            lots_int = 0
        if lots_int < 0:            
            lots_int = 0
        self.position_lots = lots_int
        self.netQty = lots_int * int(self.lot_size)
        # ensure types are ints
        self.position_lots = int(self.position_lots)
        self.netQty = int(self.netQty)

        # keep quantity map in sync if we have a current trading symbol
        try:
            sym = getattr(self, 'common_symbol', None)
            if sym:
                self.symbol_qty_map[sym] = self.netQty
        except Exception:
            # best effort only, don't crash UI
            pass
        self.position_lots = int(self.position_lots)
        self.netQty = int(self.netQty)
        return self.position_lots

    def _clear_mis_state(self, reason: str = ""):
        """Clear MIS (non-delivery) position state when broker shows flat."""
        try:
            if reason:
                log_message(f"[STATE] Clearing MIS state: {reason}")

            # Clear tracking maps for current symbol if any
            try:
                sym = getattr(self, 'common_symbol', None)
                if sym:
                    if hasattr(self, 'symbol_qty_map'):
                        self.symbol_qty_map[sym] = 0
                    if hasattr(self, 'symbol_avg_map'):
                        self.symbol_avg_map[sym] = 0.0
                    self._clear_entry_underlying(sym)
            except Exception:
                pass

            # Reset MIS position flags/state (keep delivery intact)
            self.CE_buy_flag = False
            self.PE_buy_flag = False
            self.CE_order_flag = False
            self.PE_order_flag = False
            self.SL_order_flag = False
            self.Target_order_flag = False
            self.bigProfit_flag = True
            self.common_orderID = None
            self.common_avgLTP = 0.0
            self.common_currLTP = 0.0
            self.common_token = None
            self.common_symbol = None
            self.position_lots = 0
            self.netQty = 0
            self.PnL = 0.0
            self.PnlPer = 0.0
            self.active_order_side = None

            # Reset MIS UI elements
            try:
                if self.target_entry is not None:
                    self.target_entry.setText("")
                if self.stoploss_entry is not None:
                    self.stoploss_entry.setText("")
                if self.order_label is not None:
                    self.order_label.setStyleSheet("color: Black")
                    self.order_label.setText("MIS Trade - ")
                if self.MIS_exit_button is not None:
                    self.MIS_exit_button.setEnabled(False)
                if self.target_button is not None:
                    self.target_button.setEnabled(False)
                if self.stoploss_button is not None:
                    self.stoploss_button.setEnabled(False)
                if self.MY_PE_buy_button is not None and Config.manual_override:
                    self.MY_PE_buy_button.setEnabled(True)
                if self.MY_CE_buy_button is not None and Config.manual_override:
                    self.MY_CE_buy_button.setEnabled(True)
            except Exception:
                pass
        except Exception as e:
            log_message(f"[ERROR] _clear_mis_state: {e}")

    def _is_addon_trade(self, side: str) -> bool:
        """Return True if an add-on trade is valid for the current MIS position."""
        try:
            if getattr(self, "waiting_for_fill", False):
                return False
            if side == "PE" and not getattr(self, "PE_buy_flag", False):
                return False
            if side == "CE" and not getattr(self, "CE_buy_flag", False):
                return False
            if not getattr(self, "common_symbol", None):
                return False
            if int(getattr(self, "position_lots", 0)) <= 0 or int(getattr(self, "netQty", 0)) <= 0:
                return False
            try:
                if getattr(self, "symbol_qty_map", {}).get(self.common_symbol, 0) <= 0:
                    return False
            except Exception:
                pass
            return True
        except Exception:
            return False

    # ---- Lot/Qty helpers ----
    def lots_to_qty(self, lots: int) -> int:
        try:
            return int(lots) * int(self.lot_size)
        except Exception:
            return int(lots)

    def qty_to_lots(self, qty: int) -> int:
        try:
            ls = int(self.lot_size) if self.lot_size else 1
            return int(qty) // ls
        except Exception:
            return int(qty)

    # -------- Capital-Based Lot Size Validation --------
    def validate_and_adjust_lot_size_by_capital(self, entry_price: float, position_lots: int) -> int:
        """
        Validate and adjust lot size based on capital risk management.
        Formula: risk_amount = (entry_price * AUTO_SL_PERCENT/100) * lot_size * position_lots
        If risk_amount > capital * 0.01 (1% of capital), reduce lot size.
        Args:
            entry_price: Entry price of the option
            position_lots: Number of lots to buy 
        Returns:
            Adjusted lot size (reduced if capital constraint exceeded, original if within limits)
        """
        try:
            if not entry_price or entry_price <= 0 or position_lots <= 0:
                return position_lots

            # Determine requested lots (do not double here)
            requested_lots = int(position_lots)

            # Read suggestion quality if available
            quality_score = None
            try:
                if hasattr(self, 'act_entry_data') and isinstance(self.act_entry_data, dict):
                    quality_score = self.act_entry_data.get('quality_score')
                else:
                    quality_score = getattr(self, 'quality_score', None)
            except Exception:
                quality_score = getattr(self, 'quality_score', None)

            # Calculate risk per lot
            risk_per_lot = entry_price * (Config.AUTO_SL_PERCENT / 100) * int(self.lot_size)

            # Calculate capital-based limit
            capital_risk_limit = Config.capital * getattr(Config, 'capPerLoss', 0.01)

            # Avoid division by zero
            if risk_per_lot <= 0:
                adjusted_lots = requested_lots
            else:
                max_lots_cap = max(1, int(capital_risk_limit / risk_per_lot))
                adjusted_lots = min(requested_lots, max_lots_cap)

            # Log if reduction happened due to capital
            if adjusted_lots < requested_lots:
                log_message(
                    f"[CAPITAL RISK CHECK] ⚠️ Reduced lots {requested_lots}→{adjusted_lots} due to capital limit:\n"
                    f"   Entry Price: {entry_price}, AUTO_SL%: {Config.AUTO_SL_PERCENT}%\n"
                    f"   Lot Size: {self.lot_size}\n"
                    f"   Risk per lot: ₹{risk_per_lot:.2f}\n"
                    f"   Capital limit: ₹{capital_risk_limit:.2f}"
                )
            else:
                log_message(
                    f"[CAPITAL RISK CHECK] ✅ Within limits: requested={requested_lots}, allowed={adjusted_lots}\n"
                    f"   Risk per lot: ₹{risk_per_lot:.2f}, Capital limit: ₹{capital_risk_limit:.2f}"
                )

            # Now apply quality-based doubling AFTER capital adjustment (per user request)
            if quality_score and isinstance(quality_score, (int, float)) and quality_score > 90:
                doubled = int(adjusted_lots) * 2
                log_message(f"[QUALITY DOUBLING] quality={quality_score} > 90: doubling adjusted lots {adjusted_lots}→{doubled}")
                # As requested: doubling occurs after capital adjustment (do not re-apply cap here)
                return max(1, int(doubled))

            return max(1, int(adjusted_lots))

        except Exception as e:
            log_message(f"[ERROR] validate_and_adjust_lot_size_by_capital: {e}")
            return position_lots

    def _finalize_currentLTP_for_captal_sizing(self):
        '''Fetch current LTP for the common symbol to be used in capital-based lot size validation.'''
        try:
            log_message(f"[CAP_SIZING] Requesting token/LTP for {getattr(self, 'common_symbol', None)}")
            def on_token_received(token):
                if not token:
                    log_message(f"[CAP_SIZING] Token not found for {getattr(self, 'common_symbol', None)}; aborting LTP fetch")
                    return
                
                log_message(f"[CAP_SIZING] Token received for {getattr(self, 'common_symbol', None)}: {token}")
                self.common_token = token

                def on_ltp_received(ltp):
                    if not ltp or ltp <= 0:
                        log_message(f"[CAP_SIZING] LTP not available/invalid for {getattr(self, 'common_symbol', None)} (ltp={ltp})")
                        return
                    
                    self.common_currLTP = ltp
                    log_message(f"[CAP_SIZING] LTP received for {getattr(self, 'common_symbol', None)}: {ltp}")

                self.GetLTP('NFO', token, callback=on_ltp_received)

            self.GetToken('NFO', self.common_symbol, callback=on_token_received)

        except Exception as e:
            log_message(f"[CAP_SIZING] _finalize_PE_buy_paper: {e}")

    def capital_sizing(self, requested_lots):
        """Calculate position size based on capital risk parameters"""
        log_message(f"[CAP_SIZING] Validating lot size for {requested_lots} requested lots...")
        self._finalize_currentLTP_for_captal_sizing()
        start = time.time()
        while time.time() - start < 4 and (not hasattr(self, 'common_currLTP') or self.common_currLTP <= 0):
            time.sleep(0.05)
        current_ltp = float(self.common_currLTP) if hasattr(self, 'common_currLTP') and self.common_currLTP else 0
        if current_ltp <= 0:
            log_message("[CAP_SIZING] Timeout waiting for LTP; defaulting to 1 lot")
            log_message("[WARN] Current LTP unavailable for capital check; defaulting to 1 lot")
            max_allowed_lots = 1
        else:
            max_allowed_lots = self.validate_and_adjust_lot_size_by_capital(current_ltp, self.position_lots)
        self.position_lots = min(requested_lots, max_allowed_lots)

    # -------- Entry Tracking: Persist entry_underlying_at_buy to disk for crash recovery --------
    def _store_entry_underlying(self, symbol: str, underlying_value: float, order_time: str):
        """Store entry underlying value to disk for recovery after crash.
        
        Args:
            symbol: Trading symbol (e.g., "NIFTY20MAR26C21500")
            underlying_value: Nifty intc value at entry
            order_time: Order time from broker (DDMMYYHHmmss format)
        """
        import os
        import json
        try:
            entry_tracker_file = os.path.join(os.path.dirname(__file__), ".entry_tracker.json")
            
            # Load existing entries
            entries = {}
            if os.path.exists(entry_tracker_file):
                try:
                    with open(entry_tracker_file, 'r') as f:
                        entries = json.load(f)
                except Exception as load_err:
                    log_message(f"[ENTRY_TRACK] Could not load existing entries: {load_err}")
            
            # Store entry
            entries[symbol] = {
                'underlying': underlying_value,
                'order_time': order_time,
                'stored_at': datetime.datetime.now().isoformat()
            }
            
            # Save to disk
            with open(entry_tracker_file, 'w') as f:
                json.dump(entries, f, indent=2)
            
            log_message(f"[ENTRY_TRACK] Stored entry for {symbol}: underlying={underlying_value}")
        except Exception as e:
            log_message(f"[ENTRY_TRACK] Error storing entry: {e}")

    def _retrieve_entry_underlying(self, symbol: str) -> float:
        """Retrieve entry underlying value from disk for recovery.
        
        Returns:
            float: Entry underlying value if found, 0.0 otherwise
        """
        import os
        import json
        try:
            entry_tracker_file = os.path.join(os.path.dirname(__file__), ".entry_tracker.json")
            
            if not os.path.exists(entry_tracker_file):
                return 0.0
            
            with open(entry_tracker_file, 'r') as f:
                entries = json.load(f)
            
            if symbol in entries:
                underlying = entries[symbol].get('underlying', 0.0)
                log_message(f"[ENTRY_TRACK] Retrieved entry for {symbol}: underlying={underlying}")
                return float(underlying)
            
            return 0.0
        except Exception as e:
            log_message(f"[ENTRY_TRACK] Error retrieving entry: {e}")
            return 0.0

    def _clear_entry_underlying(self, symbol: str):
        """Clear entry tracking data for a symbol (called after exit).
        
        Args:
            symbol: Trading symbol to clear
        """
        import os
        import json
        try:
            entry_tracker_file = os.path.join(os.path.dirname(__file__), ".entry_tracker.json")
            
            if not os.path.exists(entry_tracker_file):
                return
            
            with open(entry_tracker_file, 'r') as f:
                entries = json.load(f)
            
            if symbol in entries:
                del entries[symbol]
                with open(entry_tracker_file, 'w') as f:
                    json.dump(entries, f, indent=2)
                log_message(f"[ENTRY_TRACK] Cleared entry for {symbol}")
        except Exception as e:
            log_message(f"[ENTRY_TRACK] Error clearing entry: {e}")

    # -------- Broker Reconciliation --------
    def _reconcile_position_with_broker(self, symbol: str) -> bool:
        """Fetch positions from broker (master) and sync local tracked qty for `symbol`.

        Returns True if local tracked qty matched broker (or was already zero),
        False if mismatch detected (local state adjusted to broker value).
        
        On mismatch:
        - Syncs local position to broker value (broker is source of truth)
        - Cancels stale pending orders that no longer match the position
        - Logs detailed mismatch info for debugging
        """
        import traceback
        # Make reconciliation resilient: retry short-lived network flakiness
        if not symbol:
            return True

        attempts = 3
        delay = 0.8
        broker_qty = None

        for attempt in range(attempts):
            try:
                positions = self.api_master.get_positions() or []
                broker_qty = 0
                for pos in positions:
                    if pos.get('tsym') == symbol:
                        broker_qty = abs(int(pos.get('netqty', 0)))
                        break
                break
            except Exception as e:
                log_message(f"[WARN] _reconcile attempt {attempt+1} failed: {e}\n{traceback.format_exc()}")
                time.sleep(delay)
                delay = min(delay * 1.8, 2.5)

        if broker_qty is None:
            log_message(f"[ERROR] _reconcile_position_with_broker: could not fetch broker positions for {symbol}")
            # Do not aggressively block trading UI; return False to indicate we couldn't confirm
            return False

        try:
            tracked_qty = int(self.symbol_qty_map.get(symbol, 0))
            # If broker is flat for the active MIS symbol, clear stale local state
            if broker_qty == 0 and symbol == getattr(self, 'common_symbol', None):
                if not getattr(self, "waiting_for_fill", False):
                    if tracked_qty != 0 or self.PE_buy_flag or self.CE_buy_flag or self.common_avgLTP:
                        self._clear_mis_state("Broker shows flat position")
            if broker_qty != tracked_qty:
                stack = traceback.format_stack(limit=4)
                
                # Categorize the mismatch type
                if broker_qty > tracked_qty:
                    mismatch_type = "LOSING_CONTROL"
                    qty_diff = broker_qty - tracked_qty
                    reason = f"Position is LARGER than expected (+{qty_diff} qty more at broker than tracked)"
                    impact = "⚠️ More exposure than anticipated. Exit orders may only partially execute."
                else:
                    mismatch_type = "DEFENSIVE"
                    qty_diff = tracked_qty - broker_qty
                    reason = f"Position is SMALLER than expected (-{qty_diff} qty less at broker than tracked)"
                    impact = "⚠️ Less exposure than planned. Previous exit may have succeeded unexpectedly."
                
                log_message(f"[RECONCILE] {mismatch_type} Mismatch for {symbol}: broker={broker_qty}, tracked={tracked_qty}")
                log_message(f"[RECONCILE] {reason}")
                log_message(f"[RECONCILE] {impact}")
                
                # ✅ Step 1: Cancel any stale pending orders that don't match new position
                pending_orders_cancelled = 0
                try:
                    if self.SL_order_flag and hasattr(self, 'position_orders'):
                        sl_orders = self.position_orders.get(symbol, {}).get('SL', {})
                        sl_qty = int(sl_orders.get('qty', 0))
                        if sl_qty != broker_qty and sl_qty > 0:
                            log_message(f"[RECONCILE] Stale SL: Expected {broker_qty}, found {sl_qty}. Marking for cancellation.")
                            # Note: Don't actually cancel here to avoid racing with other threads
                            # Just log so user can investigate
                            pending_orders_cancelled += 1
                    
                    if self.Target_order_flag and hasattr(self, 'position_orders'):
                        target_orders = self.position_orders.get(symbol, {}).get('target', {})
                        target_qty = int(target_orders.get('qty', 0))
                        if target_qty != broker_qty and target_qty > 0:
                            log_message(f"[RECONCILE] Stale Target: Expected {broker_qty}, found {target_qty}. Marking for cancellation.")
                            pending_orders_cancelled += 1
                except Exception as e:
                    log_message(f"[RECONCILE] Warning: Could not check pending orders: {e}")
                
                # ✅ Step 2: Sync local maps to broker value
                self.symbol_qty_map[symbol] = broker_qty
                lots = broker_qty // int(self.lot_size) if self.lot_size else 0
                self.set_position_lots(lots)
                
                # ✅ Step 3: Log full callstack for debugging
                log_message(f"[CALLSTACK]\n{''.join(stack)}")
                
                # ✅ Step 4: Set warning flag for UI (optional)
                if not hasattr(self, '_mismatch_warnings'):
                    self._mismatch_warnings = {}
                self._mismatch_warnings[symbol] = {
                    'type': mismatch_type,
                    'broker': broker_qty,
                    'tracked': tracked_qty,
                    'timestamp': datetime.datetime.now()
                }
                
                return False
            return True
        except Exception as e:
            log_message(f"[ERROR] _reconcile_position_with_broker: {e}\n{traceback.format_exc()}")
            return False

    def _wait_for_fills(self, uid_orderno_map: dict, timeout: int = 30) -> dict:
        """Poll each account's order-book for the given ordernos until COMPLETE/REJECTED/CANCELLED.

        Args:
            uid_orderno_map: {uid: orderno}
            timeout: seconds to wait before returning current status

        Returns:
            dict {uid: {'status': str, 'filled_qty': int, 'avgprc': float, 'resp': dict}}
        """
        # Poll per-account orderbook with a gentle backoff; allow websocket-driven early exit
        end_t = time.time() + timeout
        statuses = {uid: {'status': 'PENDING', 'filled_qty': 0, 'avgprc': 0.0, 'resp': None, 'last_checked': 0} for uid in uid_orderno_map}

        base_sleep = 0.5
        max_sleep = 2.0

        while time.time() < end_t:
            # If websocket already marked overall waiting flag False and we track active_order ids,
            # allow early exit to avoid unnecessary polling
            if getattr(self, 'waiting_for_fill', False) is False:
                log_message("[WAIT] WebSocket indicated order update; exiting poll early.")
                break

            all_done = True
            now = time.time()
            for uid, ordno in uid_orderno_map.items():
                st = statuses[uid]['status']
                if st in ('COMPLETE', 'REJECTED', 'CANCELLED'):
                    continue
                all_done = False

                # backoff per-account
                last = statuses[uid].get('last_checked', 0)
                sleep_for = min(max_sleep, base_sleep * (1 + (now - last) / 3)) if last else base_sleep
                if now - last < sleep_for:
                    continue

                try:
                    api = self.multimgr.accounts[uid]['api']
                    ob = api.get_order_book() or []
                    found = False
                    for o in ob:
                        if str(o.get('norenordno')) == str(ordno):
                            found = True
                            st = o.get('ordstatus') or o.get('status')
                            statuses[uid]['status'] = st
                            statuses[uid]['resp'] = o
                            if st == 'COMPLETE':
                                statuses[uid]['filled_qty'] = int(o.get('qty', 0))
                                statuses[uid]['avgprc'] = float(o.get('avgprc', 0.0) or 0.0)
                            break

                    if not found:
                        # If order not present in orderbook after some checks, mark as UNKNOWN (not yet confirmed)
                        statuses[uid]['status'] = statuses[uid].get('status', 'PENDING')
                        statuses[uid]['resp'] = statuses[uid].get('resp')

                except Exception as e:
                    log_message(f"[WARN] _wait_for_fills uid={uid} ordno={ordno} error: {e}")

                statuses[uid]['last_checked'] = now

            if all_done:
                break

            # small sleep to yield CPU, increasing slightly to avoid tight loop
            time.sleep(0.6)

        return statuses

    # -------- Tradebook Helpers --------
    @overload
    def _compute_tradebook_avg(
        self,
        trades,
        symbol: str,
        side: str = "B",
        orderno: Optional[str] = None,
        *,
        return_qty: Literal[False] = False,
    ) -> Optional[float]:
        ...

    @overload
    def _compute_tradebook_avg(
        self,
        trades,
        symbol: str,
        side: str = "B",
        orderno: Optional[str] = None,
        *,
        return_qty: Literal[True],
    ) -> Tuple[Optional[float], int]:
        ...

    def _compute_tradebook_avg(self, trades, symbol: str, side: str = "B", orderno: Optional[str] = None, *, return_qty: bool = False) -> Optional[float] | Tuple[Optional[float], int]:
        """Compute weighted avg price from tradebook for the latest order of a symbol/side.

        If orderno is provided, computes avg only for that order. If return_qty is True,
        returns a tuple (avg, total_qty).
        """
        try:
            if not trades or not symbol:
                return (None, 0) if return_qty else None
            side = str(side or "").upper()

            def _get_tsym(t):
                return t.get('tsym') or t.get('tradingsymbol') or t.get('symbol')

            def _get_side(t):
                for key in ('trantype', 'buySell', 'side', 'type'):
                    val = t.get(key)
                    if val is None:
                        continue
                    v = str(val).upper()
                    if v in ('B', 'BUY'):
                        return 'B'
                    if v in ('S', 'SELL'):
                        return 'S'
                return ''

            def _get_ordno(t):
                for key in ('norenordno', 'norenorderno', 'orderno', 'order_no', 'orderid'):
                    val = t.get(key)
                    if val not in (None, ''):
                        return str(val)
                return None

            def _get_price(t):
                for key in ('prc', 'price', 'avgprc', 'fillprice', 'trdprc', 'rate'):
                    val = t.get(key)
                    if val not in (None, ''):
                        try:
                            return float(val)
                        except Exception:
                            continue
                return None

            def _get_qty(t):
                for key in ('qty', 'fillqty', 'fill_qty', 'trdqty', 'trdq'):
                    val = t.get(key)
                    if val not in (None, ''):
                        try:
                            return int(float(val))
                        except Exception:
                            continue
                return 0

            def _get_time_key(t):
                for key in ('exch_tm', 'fltm', 'filltime', 'trantime', 'time', 'exchtime'):
                    val = t.get(key)
                    if not val:
                        continue
                    try:
                        return datetime.datetime.strptime(val, "%H:%M:%S").time()
                    except Exception:
                        try:
                            return datetime.datetime.strptime(val, "%H:%M").time()
                        except Exception:
                            continue
                return None

            filtered = []
            for t in trades:
                tsym = _get_tsym(t)
                if tsym != symbol:
                    continue
                if side and _get_side(t) != side:
                    continue
                if orderno:
                    ordno_val = _get_ordno(t)
                    if ordno_val is None or str(ordno_val) != str(orderno):
                        continue
                filtered.append(t)

            if not filtered:
                return (None, 0) if return_qty else None

            # Pick the latest trade (prefer time if available, else list order)
            time_candidates = []
            for idx, t in enumerate(filtered):
                tk = _get_time_key(t)
                if tk:
                    time_candidates.append((tk, idx, t))

            if time_candidates:
                _, _, last_trade = sorted(time_candidates, key=lambda x: (x[0], x[1]))[-1]
            else:
                last_trade = filtered[-1]

            if orderno:
                same_order = filtered
            else:
                last_ordno = _get_ordno(last_trade)
                if last_ordno:
                    same_order = [t for t in filtered if _get_ordno(t) == last_ordno]
                else:
                    same_order = [last_trade]

            total_qty = 0
            weighted_sum = 0.0
            for t in same_order:
                qty = _get_qty(t)
                price = _get_price(t)
                if qty > 0 and price is not None:
                    total_qty += qty
                    weighted_sum += price * qty

            if total_qty > 0 and weighted_sum > 0:
                avg_val = round(weighted_sum / total_qty, 2)
                return (avg_val, total_qty) if return_qty else avg_val

            # Fallback to last trade price if qty/price missing
            last_price = _get_price(last_trade)
            if last_price is not None and last_price > 0:
                avg_val = round(last_price, 2)
                return (avg_val, total_qty) if return_qty else avg_val
            return (None, 0) if return_qty else None
        except Exception as e:
            log_message(f"[TRADEBOOK] Error computing avg for {symbol}: {e}")
            return (None, 0) if return_qty else None

    def _get_latest_trade_avg(self, symbol: str, side: str = "B") -> Optional[float]:
        """Fetch tradebook and return latest weighted avg for symbol/side."""
        try:
            if not symbol:
                return None
            trades = self.api_master.get_trade_book() or []
            return self._compute_tradebook_avg(trades, symbol, side)
        except Exception as e:
            log_message(f"[TRADEBOOK] get_trade_book failed for {symbol}: {e}")
            return None

    def _get_latest_trade_avg_multi(self, symbol: str, side: str = "B", ordernos_map: Optional[Dict[str, Any]] = None, fills_map: Optional[Dict[str, Any]] = None) -> Optional[float]:
        """Aggregate tradebook avg across all accounts for the latest order (or specific ordernos).

        If ordernos_map is provided, uses each account's order number for filtering.
        If fills_map is provided, uses filled_qty for weighting (preferred).
        """
        try:
            if not symbol:
                return None
            accounts = getattr(self, 'multimgr', None)
            accounts = accounts.accounts if accounts and hasattr(accounts, 'accounts') else {}
            if not accounts:
                return self._get_latest_trade_avg(symbol, side)

            total_qty = 0
            weighted_sum = 0.0
            any_found = False

            for uid, acc in accounts.items():
                try:
                    api = acc.get('api')
                    if not api:
                        continue
                    trades = api.get_trade_book() or []
                    ordno = None
                    if ordernos_map and uid in ordernos_map:
                        ordno = str(ordernos_map[uid])
                    avg, qty = self._compute_tradebook_avg(trades, symbol, side, orderno=ordno, return_qty=True)

                    # Prefer actual filled qty from fills_map when available
                    if fills_map:
                        try:
                            fqty = int(fills_map.get(uid, {}).get('filled_qty', 0))
                            if fqty > 0:
                                qty = fqty
                        except Exception:
                            pass

                    if avg and qty and qty > 0:
                        weighted_sum += float(avg) * int(qty)
                        total_qty += int(qty)
                        any_found = True
                except Exception as e:
                    log_message(f"[TRADEBOOK] Account {uid} tradebook error: {e}")
                    continue

            if any_found and total_qty > 0:
                return round(weighted_sum / total_qty, 2)
            return None
        except Exception as e:
            log_message(f"[TRADEBOOK] Multi-account avg failed for {symbol}: {e}")
            return None

    def recover_orphaned_orders_on_restart(self):
        """
        CRITICAL FUNCTION: Called on program startup AFTER login to recover any orphaned positions
        that were open when the program crashed.
        
        Purpose:
        --------
        When the software crashes/hangs after a position is established but before 
        it's properly tracked in local variables (CE_buy_flag, symbol_qty_map), the broker
        still has an open position. This function:
        
        1. Fetches ALL current positions from ALL accounts
        2. Compares with local tracking state
        3. Recovers orphaned positions by reconstructing local state
        4. Alerts user about recovered positions
        
        Safety:
        -------
        - Read-only from broker (no order modifications)
        - Only syncs local vars to broker state
        - Broker is source of truth
        - Returns detailed report for user review
        
        Returns:
        --------
        dict: {
            'status': 'OK' | 'PARTIAL' | 'ERROR',
            'orphaned_orders_found': int,
            'orders_recovered': int,
            'errors': [list of error messages],
            'recovered_positions': [list of recovered positions]
        }
        """
        import traceback
        import datetime
        
        result = {
            'status': 'OK',
            'orphaned_orders_found': 0,
            'orders_recovered': 0,
            'errors': [],
            'recovered_positions': [],
            'timestamp': datetime.datetime.now().isoformat()
        }
        
        try:
            log_message("\n" + "="*80)
            log_message("[RECOVERY] ORPHANED POSITION RECOVERY STARTED")
            log_message("[RECOVERY] Scanning all broker accounts for open positions...")
            log_message("="*80)
            
            # ============================================================================
            # STEP 1: Fetch all current positions from ALL accounts
            # ============================================================================
            broker_positions = {}  # {symbol: [{account, netqty, netavgprc, side, ...}]}
            
            for uid, account_info in self.multimgr.accounts.items():
                try:
                    api = account_info['api']
                    user_email = account_info.get('email', uid)
                    
                    # Get positions for this account
                    positions = api.get_positions() or []
                    
                    for pos in positions:
                        netqty = int(pos.get('netqty', 0))
                        # Skip zero positions
                        if netqty == 0:
                            continue
                        
                        symbol = pos.get('tsym', '').strip()
                        if not symbol:
                            continue
                        
                        if symbol not in broker_positions:
                            broker_positions[symbol] = []
                        
                        broker_positions[symbol].append({
                            'uid': uid,
                            'email': user_email,
                            'netqty': netqty,
                            'netavgprc': float(pos.get('netavgprc', 0.0)),
                            'side': 'BUY' if netqty > 0 else 'SELL',  # Simplified
                            'product_type': pos.get('prd', 'MIS'),
                            'exchange': pos.get('exch', 'NFO'),
                            'raw_position': pos
                        })
                        
                except Exception as e:
                    error_msg = f"[RECOVERY] Error fetching positions from {uid}: {e}"
                    log_message(error_msg)
                    result['errors'].append(error_msg)
                    result['status'] = 'PARTIAL'
            
            log_message(f"[RECOVERY] Found {len(broker_positions)} symbols with open positions")
            
            # ============================================================================
            # STEP 2: Check local tracking state
            # ============================================================================
            local_state = {
                'symbol': self.common_symbol,
                'CE_buy_flag': self.CE_buy_flag,
                'PE_buy_flag': self.PE_buy_flag,
                'CE_order_flag': self.CE_order_flag,
                'PE_order_flag': self.PE_order_flag,
                'position_lots': self.position_lots,
                'symbol_qty_map': dict(self.symbol_qty_map),
                'symbol_avg_map': dict(self.symbol_avg_map),
                'active_order_id': self.active_order_id,
                'active_order_side': self.active_order_side,
            }
            
            log_message("\n[RECOVERY] Current local tracking state:")
            log_message(f"  ├─ symbol: {local_state['symbol']}")
            log_message(f"  ├─ CE_buy_flag: {local_state['CE_buy_flag']}")
            log_message(f"  ├─ PE_buy_flag: {local_state['PE_buy_flag']}")
            log_message(f"  ├─ position_lots: {local_state['position_lots']}")
            log_message(f"  ├─ symbol_qty_map: {local_state['symbol_qty_map']}")
            log_message(f"  ├─ symbol_avg_map: {local_state['symbol_avg_map']}")
            log_message(f"  ├─ active_order_id: {local_state['active_order_id']}")
            log_message(f"  └─ active_order_side: {local_state['active_order_side']}")
            
            # ============================================================================
            # STEP 3: Detect Orphaned Positions
            # ============================================================================
            log_message("\n[RECOVERY] Analyzing for orphaned positions...")
            
            for symbol, positions_list in broker_positions.items():
                local_qty = self.symbol_qty_map.get(symbol, 0)
                local_avg = self.symbol_avg_map.get(symbol, 0.0)
                
                # Calculate total net qty across all accounts for this symbol
                total_net_qty = sum(p['netqty'] for p in positions_list)
                
                log_message(f"\n  Symbol: {symbol}")
                log_message(f"    Local tracking: qty={local_qty}, avg={local_avg}")
                log_message(f"    Broker position: net_qty={total_net_qty}")
                
                # Check if there's a mismatch
                if total_net_qty != 0 and local_qty == 0:
                    # ORPHANED: Broker has open position but local tracking is empty
                    result['orphaned_orders_found'] += 1
                    
                    log_message(f"    🔴 ORPHANED POSITION DETECTED!")
                    log_message(f"       Broker has {total_net_qty} net qty open but local tracking shows 0")
                    
                    # ====================================================================
                    # STEP 4: Recover the orphaned order
                    # ====================================================================
                    try:
                        # Reconstruct local state from broker data
                        recovered_info = {
                            'symbol': symbol,
                            'broker_net_qty': total_net_qty,
                            'avg_price': positions_list[0]['netavgprc'] if positions_list else 0.0,
                            'positions': positions_list,
                            'side': positions_list[0]['side'] if positions_list else 'BUY'
                        }
                        
                        log_message(f"    ✓ RECOVERY ACTIONS:")
                        
                        # 1. Update symbol_qty_map
                        self.symbol_qty_map[symbol] = total_net_qty
                        log_message(f"       ✓ Updated symbol_qty_map[{symbol}] = {total_net_qty}")
                        
                        # 2. Update symbol_avg_map
                        if positions_list:
                            self.symbol_avg_map[symbol] = positions_list[0]['netavgprc']
                            log_message(f"       ✓ Updated symbol_avg_map[{symbol}] = {positions_list[0]['netavgprc']}")
                        
                        # 3. Update position_lots
                        lots = abs(total_net_qty) // int(self.lot_size) if self.lot_size else 0
                        self.set_position_lots(lots)
                        log_message(f"       ✓ Updated position_lots = {lots}")
                        
                        # 4. Determine order side and update flags
                        if positions_list:
                            side = positions_list[0]['side']  # BUY or SELL
                            
                            if 'CE' in symbol.upper():
                                if side.upper() == 'BUY':
                                    self.CE_buy_flag = True
                                    self.CE_order_flag = True
                                    self.CE_buy_avgltp = positions_list[0]['netavgprc']
                                    log_message(f"       ✓ Set CE_buy_flag=True, CE_order_flag=True")
                                    log_message(f"       ✓ Set CE_buy_avgltp={positions_list[0]['netavgprc']}")
                                recovered_info['flag_set'] = 'CE_buy_flag'
                            
                            elif 'PE' in symbol.upper():
                                if side.upper() == 'BUY':
                                    self.PE_buy_flag = True
                                    self.PE_order_flag = True
                                    self.PE_buy_avgltp = positions_list[0]['netavgprc']
                                    log_message(f"       ✓ Set PE_buy_flag=True, PE_order_flag=True")
                                    log_message(f"       ✓ Set PE_buy_avgltp={positions_list[0]['netavgprc']}")
                                recovered_info['flag_set'] = 'PE_buy_flag'
                        
                        # 5. CRITICAL FIX: Restore order_time for 1-hour rule tracking
                        order_time_str = positions_list[0].get('order_time', '') if positions_list else ''
                        if order_time_str:
                            try:
                                # Parse broker order time (format: "DDMMYYHHmmss")
                                order_time_obj = datetime.datetime.strptime(order_time_str, "%d%m%y%H%M%S")
                                if 'CE' in symbol.upper():
                                    self.CE_order_time = order_time_obj
                                    log_message(f"       ✓ Restored CE_order_time = {order_time_obj} (for 1-hour rule)")
                                elif 'PE' in symbol.upper():
                                    self.PE_order_time = order_time_obj
                                    log_message(f"       ✓ Restored PE_order_time = {order_time_obj} (for 1-hour rule)")
                                recovered_info['order_time_restored'] = order_time_obj.isoformat()
                            except Exception as time_parse_err:
                                log_message(f"       ⚠️  Could not parse order_time '{order_time_str}': {time_parse_err}")
                        else:
                            log_message(f"       ⚠️  broker order_time not available in recovery data")
                        
                        # 6. Restore Target1 Level (T1Level) - critical for 1-hour rule logic
                        # Try to retrieve entry underlying from persistent storage
                        entry_underlying = self._retrieve_entry_underlying(symbol)
                        if entry_underlying > 0:
                            # Calculate T1Level based on entry underlying and order type
                            if 'CE' in symbol.upper():
                                self.T1Level = entry_underlying + 40
                                log_message(f"       ✓ Calculated T1Level = {entry_underlying} + 40 = {self.T1Level} (from stored entry underlying)")
                            elif 'PE' in symbol.upper():
                                self.T1Level = entry_underlying - 40
                                log_message(f"       ✓ Calculated T1Level = {entry_underlying} - 40 = {self.T1Level} (from stored entry underlying)")
                            recovered_info['t1level_calculated'] = self.T1Level
                            recovered_info['entry_underlying'] = entry_underlying
                        else:
                            # Fallback: Use current intc (but this may be inaccurate if market moved)
                            if hasattr(self, 'intc_value') and self.intc_value > 0:
                                if 'CE' in symbol.upper():
                                    self.T1Level = self.intc_value + 40
                                    log_message(f"       ⚠️  No stored entry underlying; using current intc={self.intc_value} → T1Level={self.T1Level}")
                                    log_message(f"           (NOTE: This may be inaccurate if market moved since entry)")
                                elif 'PE' in symbol.upper():
                                    self.T1Level = self.intc_value - 40
                                    log_message(f"       ⚠️  No stored entry underlying; using current intc={self.intc_value} → T1Level={self.T1Level}")
                                    log_message(f"           (NOTE: This may be inaccurate if market moved since entry)")
                                recovered_info['t1level_estimated'] = self.T1Level
                            else:
                                log_message(f"       ⚠️  Cannot calculate T1Level - no stored entry or current intc available")
                        
                        # 7. Restore Target and Stoploss prices (if available)
                        # These are typically UI-entered values, so calculate defaults
                        avg_price = positions_list[0]['avg_price'] if positions_list else 0.0
                        if avg_price > 0:
                            # Default: Target = 2x entry, SL = 0.5x entry (can be overridden by user)
                            default_target = avg_price * 2
                            default_sl = avg_price * 0.5
                            
                            if 'CE' in symbol.upper():
                                self.targetLTP = default_target
                                self.stoplossLTP = default_sl
                                log_message(f"       ✓ Set default targetLTP = {self.targetLTP} (2x entry)")
                                log_message(f"       ✓ Set default stoplossLTP = {self.stoplossLTP} (0.5x entry)")
                                recovered_info['target_restored'] = default_target
                                recovered_info['stoploss_restored'] = default_sl
                            elif 'PE' in symbol.upper():
                                self.targetLTP = default_target
                                self.stoplossLTP = default_sl
                                log_message(f"       ✓ Set default targetLTP = {self.targetLTP} (2x entry)")
                                log_message(f"       ✓ Set default stoplossLTP = {self.stoplossLTP} (0.5x entry)")
                                recovered_info['target_restored'] = default_target
                                recovered_info['stoploss_restored'] = default_sl
                        else:
                            log_message(f"       ⚠️  Cannot restore target/SL: avg_price = {avg_price}")
                        
                        # 8. Update common variables for UI display
                        self.common_symbol = symbol
                        self.common_avgLTP = positions_list[0]['netavgprc'] if positions_list else 0.0
                        log_message(f"       ✓ Updated common_symbol={symbol}, common_avgLTP={self.common_avgLTP}")
                        
                        # 9. Store active order context
                        self.active_order_id = f"RECOVERED_{symbol}"  # Placeholder
                        self.active_order_symbol = symbol
                        if 'CE' in symbol:
                            self.active_order_side = 'CE'
                        elif 'PE' in symbol:
                            self.active_order_side = 'PE'
                        log_message(f"       ✓ Updated active_order_id={self.active_order_id}, active_order_side={self.active_order_side}")
                        
                        result['orders_recovered'] += 1
                        result['recovered_positions'].append(recovered_info)
                        result['status'] = 'OK'
                        self.PaperTrade_checkbox.setChecked(False)  # Ensure we switch to REAL mode after recovery
                    except Exception as recovery_error:
                        error_msg = f"[RECOVERY] Error recovering {symbol}: {recovery_error}\n{traceback.format_exc()}"
                        log_message(f"    🔴 {error_msg}")
                        result['errors'].append(error_msg)
                        result['status'] = 'PARTIAL'
                
                elif total_net_qty != 0 and local_qty != 0:
                    # Potential mismatch - log but don't auto-recover
                    if total_net_qty != local_qty:
                        log_message(f"    ⚠️  MISMATCH: broker={total_net_qty}, local={local_qty}")
                        log_message(f"       Run reconciliation manually if needed")
                    else:
                        log_message(f"    ✓ In sync: broker={total_net_qty}, local={local_qty}")
                
                elif total_net_qty == 0 and local_qty != 0:
                    # Local thinks we have position but broker doesn't - this is bad
                    log_message(f"    ⚠️  WARNING: Local has {local_qty} but broker shows 0!")
                    log_message(f"       Run manual reconciliation to sync")
            
            # ============================================================================
            # STEP 5: Final Report
            # ============================================================================
            log_message("\n" + "="*80)
            log_message("[RECOVERY] FINAL REPORT")
            log_message("="*80)
            log_message(f"Status: {result['status']}")
            log_message(f"Orphaned positions found: {result['orphaned_orders_found']}")
            log_message(f"Positions recovered: {result['orders_recovered']}")
            
            if result['recovered_positions']:
                log_message(f"\nRecovered positions:")
                for pos in result['recovered_positions']:
                    log_message(f"  • {pos['symbol']}")
                    log_message(f"    ├─ Net Qty: {pos['broker_net_qty']}")
                    log_message(f"    ├─ Avg Price: {pos['avg_price']}")
                    log_message(f"    ├─ Side: {pos['side']}")
                    log_message(f"    └─ Flag set: {pos.get('flag_set', 'N/A')}")
            
            if result['errors']:
                log_message(f"\nErrors encountered:")
                for err in result['errors']:
                    log_message(f"  • {err}")
            
            log_message("="*80 + "\n")
            
            return result
            
        except Exception as e:
            error_msg = f"[RECOVERY] FATAL ERROR: {e}\n{traceback.format_exc()}"
            log_message(error_msg)
            result['status'] = 'ERROR'
            result['errors'].append(error_msg)
            return result

    def place_and_confirm(self, buy_or_sell, product_type, exchange, tradingsymbol, quantity, price_type='MKT', price=0.0, trigger_price=None, timeout=30):
        """Place the same order across accounts and wait for fills. Returns aggregated fill info.

        This helper:
         - calls `multi_place_order`
         - extracts per-account order numbers (if created)
         - calls `_wait_for_fills` to verify fills
         - updates local `symbol_qty_map` and `position_lots` using broker fills (sum across accounts)

        Returns dict: {'results': results, 'ordernos': ordernos_map, 'fills': fills_status}
        """
        # Reconcile before placing in REAL mode
        import traceback
        if not self.PaperTrade_checkbox.isChecked():
            stack = traceback.format_stack(limit=4)
            synced = self._reconcile_position_with_broker(tradingsymbol)
            if not synced:
                log_message(f"[PLACE] Reconciliation adjusted local state; please verify before aggressive trading.\n[CALLSTACK]\n{''.join(stack)}")

        results = self.multi_place_order(buy_or_sell, product_type, exchange, tradingsymbol, quantity, price_type, price, trigger_price)

        # multi_place_order stores order numbers into account['orders']; build map of latest order per account
        ordernos_map = {}
        for uid, acc in self.multimgr.accounts.items():
            order_list = acc.get('orders', {}).get(tradingsymbol, [])
            if order_list:
                ordernos_map[uid] = order_list[-1]

        # persist last multi-place ordernos for debugging
        self._last_multi_place_ordernos = ordernos_map

        if not ordernos_map:
            log_message(f"[PLACE] No order numbers received for {tradingsymbol}; responses: {results}")
            return {'results': results, 'ordernos': {}, 'fills': {}}

        # Run waiting/polling in background executor to avoid blocking UI thread
        fills = {}
        try:
            future = self.executor.submit(self._wait_for_fills, ordernos_map, timeout)
            fills = future.result(timeout=timeout + 5)
        except Exception as e:
            log_message(f"[PLACE] _wait_for_fills failed/timeout: {e}")
            # Try a final synchronous attempt (short) to gather whatever info is available
            try:
                fills = self._wait_for_fills(ordernos_map, timeout=5)
            except Exception as e2:
                log_message(f"[PLACE] Final _wait_for_fills attempt failed: {e2}")
                fills = {uid: {'status': 'UNKNOWN', 'filled_qty': 0, 'avgprc': 0.0, 'resp': None} for uid in ordernos_map}

        # Aggregate filled qty across accounts and update local tracking
        total_filled_qty = 0
        weighted_sum = 0.0
        for uid, info in fills.items():
            if info['status'] == 'COMPLETE' and info['filled_qty'] > 0:
                fqty = int(info['filled_qty'])
                favg = float(info.get('avgprc', 0.0) or 0.0)
                total_filled_qty += fqty
                weighted_sum += favg * fqty

        if total_filled_qty > 0:
            avg = (weighted_sum / total_filled_qty) if weighted_sum else 0.0
            # Update symbol_qty_map depending on buy or sell
            with self.lock:
                prev_qty = int(self.symbol_qty_map.get(tradingsymbol, 0))
                if buy_or_sell == 'B':
                    # If local state looks flat but qty map still has value, treat as fresh entry
                    if prev_qty > 0 and (int(getattr(self, 'position_lots', 0)) == 0 or getattr(self, 'active_order_side', None) is None):
                        log_message(f"[WARN] Stale qty/avg detected for fresh entry in {tradingsymbol}; resetting avg/qty before recompute.")
                        prev_qty = 0
                        self.symbol_qty_map[tradingsymbol] = 0
                        if hasattr(self, 'symbol_avg_map'):
                            self.symbol_avg_map[tradingsymbol] = 0.0
                        self.common_avgLTP = 0.0
                    if prev_qty == 0:
                        trade_avg = self._get_latest_trade_avg_multi(tradingsymbol, 'B', ordernos_map, fills)
                        if trade_avg and trade_avg > 0:
                            log_message(f"[TRADEBOOK] Using latest buy avg {trade_avg} for {tradingsymbol} (orderbook avg {avg})")
                            avg = trade_avg
                    new_qty = prev_qty + total_filled_qty
                    # ✅ Weighted avg cost basis when adding to position
                    if prev_qty > 0 and self.common_avgLTP and self.common_avgLTP > 0:
                        prev_cost = float(self.common_avgLTP) * prev_qty
                        self.common_avgLTP = (prev_cost + avg * total_filled_qty) / new_qty
                    else:
                        self.common_avgLTP = avg
                else:
                    new_qty = max(prev_qty - total_filled_qty, 0)
                    # ✅ Reset avg when position fully closed
                    if new_qty == 0:
                        self.common_avgLTP = 0.0
                try:
                    ls = int(self.lot_size)
                except Exception:
                    ls = 1
                if ls and (total_filled_qty % ls) != 0:
                    log_message(f"[WARN] Filled qty {total_filled_qty} not multiple of lot_size {ls}; tracking in contracts but lots will be floored.")
                self.symbol_qty_map[tradingsymbol] = new_qty
                self.set_position_lots(self.qty_to_lots(new_qty))
            log_message(f"[PLACE] Confirmed fills for {tradingsymbol}: filled={total_filled_qty} avg={avg} prev_qty={prev_qty} new_qty={new_qty}")
            # Always sync with broker after fill
            self._reconcile_position_with_broker(tradingsymbol)

        return {'results': results, 'ordernos': ordernos_map, 'fills': fills}

    def _log_cache_stats(self):
        """Log cache statistics periodically."""
        try:
            stats = self.data_cache.get_stats()
            print(f"[CACHE] Stats - Total: {stats['total']}, Active: {stats['active']}, Expired: {stats['expired']}")
        except Exception as e:
            log_message(f"[ERROR] _log_cache_stats: {e}")

    def refresh_nse(self):
        """Reinitialize NSE session and clear related caches without restarting the app.

        Steps:
        - Recreate `NseSession`, `ExpiryFetcher`, `SymbolFetcher`
        - Clear `data_cache` and option-chain cache in `signal_generator` if present
        - Trigger a quick 9:15 analysis to validate the new session
        """
        try:
            # Disable button while refreshing
            try:
                self.refresh_nse_button.setEnabled(False)
            except Exception:
                pass

            log_message("[ACTION] Refreshing NSE session and clearing caches...")

            # Recreate NSE session & fetchers
            self.nse = NseSession()
            self.ef = ExpiryFetcher(self.nse)
            self.sf = SymbolFetcher(self.nse)

            # Clear local data cache
            if hasattr(self, 'data_cache') and self.data_cache:
                self.data_cache.clear()

            # Refresh signal generator components
            if hasattr(self, 'signal_generator') and self.signal_generator:
                try:
                    self.signal_generator.nse = self.nse
                    self.signal_generator.oc = OptionChainFetcher(self.nse)
                    if hasattr(self.signal_generator, '_oc_cache_store'):
                        self.signal_generator._oc_cache_store.clear()
                except Exception as e:
                    log_message(f"[WARN] refresh_nse: couldn't refresh signal_generator: {e}")

        except Exception as e:
            log_message(f"[ERROR] refresh_nse: {e}")
            QMessageBox.warning(self, "Refresh Failed", f"Failed to refresh NSE: {e}")

        finally:
            try:
                self.refresh_nse_button.setEnabled(True)
            except Exception:
                pass

    #+++++++++ WebSocket and LTP Handling ++++++++++++++          
    def start_webSocket(self):
        """Start FYERS websocket once."""
        with self._ws_start_lock:
            if self._ws_started:
                log_message("[WebSocket] Start skipped: websocket already started")
                return

            try:
                setattr(self, "websocket_connected", False)
                started = self.api_master.start_websocket(
                    subscribe_callback=self.on_tick,
                    socket_open_callback=self.on_open,
                    socket_close_callback=self.on_ws_close,
                    socket_error_callback=self.on_ws_error,
                    order_update_callback=self.on_order_update
                )
                if started is False:
                    self._ws_started = True
                    log_message("[WebSocket] Start skipped: websocket thread already running")
                else:
                    self._ws_started = True
                    log_message("[WebSocket] Started (FYERS auto-reconnect enabled)")
            except Exception as ws_error:
                err = str(ws_error)
                if "already opened" in err.lower() or "already running" in err.lower():
                    self._ws_started = True
                    log_message(f"[WebSocket] Already running: {err}")
                    return
                self._ws_started = False
                log_message(f"[WebSocket] Start failed: {err}")

    def on_open(self):
        """Called when WebSocket connection opens"""
        try:
            # mark connection state so we don't attempt to re-open later
            setattr(self, "websocket_connected", True)

            subscribe_list = []

            # Always subscribe to Nifty index for realtime intc_value updates
            # Use symbol name instead of token for better realtime performance
            subscribe_list.append('NSE:NIFTY50-INDEX')

            if self.subscribe_symbols:
                subscribe_list.extend(self.subscribe_symbols)
            
            log_message(f"[WebSocket] Subscribing to: {subscribe_list}")
            log_message(f"[WebSocket] Nifty symbol: NSE:NIFTY50-INDEX")
            self.api_master.subscribe(subscribe_list)
        except Exception as e:
            log_message(f"[ERROR] on_open: {e}")

    def prepare_tokens(self, strikes):
        """Prepare symbols for websocket subscription - SAFE NON-BLOCKING"""
        try:
            if not strikes:
                return

            pending_count = len(strikes)

            def token_received(sym, token):
                nonlocal pending_count

                if token:
                    if sym not in self.token_map:
                        self.token_map[sym] = token
                        self.token_to_symbol[token] = sym
                        log_message(f"[TOKEN] ✅ {sym} = {token}")
                    else:
                        log_message(f"[TOKEN] ℹ️ Token already known: {sym}")
                else:
                    log_message(f"[TOKEN] ⚠️ Token not found for {sym}")

                pending_count -= 1

                if pending_count == 0:
                    log_message(f"[TOKEN] All {len(strikes)} tokens prepared")
                    if not getattr(self, "websocket_connected", False):
                        log_message("[TOKEN] WebSocket not connected. Subscriptions queued for next socket open.")

            for strike in set(strikes):  # dedupe symbols
                self.subscribe_symbols.add('NFO:' + strike)
                self.GetToken(
                    'NFO',
                    strike,
                    callback=lambda token, s=strike: token_received(s, token)
                )

        except Exception as e:
            log_message(f"[ERROR] prepare_tokens: {e}")

    def on_ws_close(self):
        """Callback from the API when the socket is closed."""
        log_message("[WebSocket] socket closed")
        setattr(self, "websocket_connected", False)
        if self._ws_disconnected_since is None:
            self._ws_disconnected_since = time.time()

    def on_ws_error(self, error):
        """Callback from the API on websocket errors."""
        try:
            err = str(error)
            log_message(f"[WebSocket] error: {err}")
            if "NOT_OK" in err or "remote host was lost" in err.lower():
                self.force_reset_websocket("socket error callback")
        except Exception:
            pass

    def websocket_health_check(self):
        """Detect stuck websocket states and force a clean restart."""
        try:
            if not getattr(self, "_ws_started", False):
                return
            if not hasattr(self, "api_master") or not self.api_master:
                return

            api_connected = bool(getattr(self.api_master, "_NorenApi__websocket_connected", False))
            local_connected = bool(getattr(self, "websocket_connected", False))
            connected = api_connected and local_connected

            if connected:
                self._ws_disconnected_since = None
                return

            if self._ws_disconnected_since is None:
                self._ws_disconnected_since = time.time()
                return

            disconnected_for = time.time() - self._ws_disconnected_since
            if disconnected_for >= 15 and not self._ws_recovering:
                self.force_reset_websocket(f"disconnected {int(disconnected_for)}s")
        except Exception as e:
            log_message(f"[WebSocket] health check error: {e}")

    def force_reset_websocket(self, reason="unknown"):
        """Hard reset FYERS websocket internals to recover from stuck loops."""
        now_ts = time.time()
        if (now_ts - float(getattr(self, "_ws_last_reset_ts", 0.0))) < 10.0:
            return
        if self._ws_recovering:
            return

        self._ws_recovering = True
        self._ws_last_reset_ts = now_ts

        def _recover():
            try:
                log_message(f"[WebSocket] Force reset start: {reason}")
                if hasattr(self, "api_master") and self.api_master:
                    try:
                        self.api_master.close_websocket()
                    except Exception:
                        pass

                    try:
                        setattr(self.api_master, "_NorenApi__websocket_connected", False)
                    except Exception:
                        pass

                self.websocket_connected = False
                self._ws_started = False
                self._ws_disconnected_since = time.time()
                QTimer.singleShot(1000, self.start_webSocket)  # Non-blocking delay
            except Exception as e:
                log_message(f"[WebSocket] Force reset failed: {e}")
            finally:
                self._ws_recovering = False

        threading.Thread(target=_recover, daemon=True, name="WSForceReset").start()

    def remove_symbol_token(self, sym: str):
        """Remove a trading symbol and unsubscribe its symbol safely"""
        full_sym = 'NFO:' + sym
        if full_sym in self.subscribe_symbols:
            self.subscribe_symbols.remove(full_sym)
            log_message(f"[TOKEN_REMOVE] {sym} ({full_sym}) removed from subscriptions.")
            # if hasattr(self, "api_master") and self.api_master:
            #     # Avoid blocking GUI when internet/socket is down.
            #     worker = APIWorker(self.api_master.unsubscribe, [full_sym])
            #     worker.signals.error.connect(
            #         lambda err, s=full_sym: log_message(f"[TOKEN_REMOVE] unsubscribe failed for {s}: {err[0]}")
            #     )
            #     self.api_threadpool.start(worker)

        self.token_map.pop(sym, None)
        self.symbol_to_strike.pop(sym, None)
        token = self.token_map.get(sym)
        if token:
            self.token_to_symbol.pop(token, None)

    def on_tick(self, tick_data):
        """Process incoming tick data"""
        try:
            ltp = tick_data.get('lp')
            symbol = tick_data.get('symbol')

            if ltp is None or symbol is None:
                return

            # Nifty index updates (fast, symbol subscription)
            if symbol == 'NSE:NIFTY50-INDEX':
                self.nifty_update_signal.emit(float(ltp))
                return

            # Option ticks (symbol format: NFO:<SYMBOL>)
            if symbol.startswith('NFO:'):
                option_symbol = symbol.split(':', 1)[1]
                if option_symbol == self.common_symbol or option_symbol == getattr(self, 'Deli_common_symbol', None):
                    self.ltp_ready = True
                with self.lock:
                    self.ltp_data[option_symbol] = float(ltp)

        except Exception as e:
            log_message(f"[ERROR] on_tick: {e}")

    def currentLTP(self):
        """Update current LTP values"""
        try:
            with self.lock:
                # Prefer explicit keys (common_symbol, Deli_common_symbol)
                if getattr(self, 'common_symbol', None) and self.common_symbol in self.ltp_data:
                    self.common_currLTP = float(self.ltp_data[self.common_symbol])
                else:
                    # fallback to any available LTP
                    if self.ltp_data:
                        self.common_currLTP = float(next(iter(self.ltp_data.values())))

                if getattr(self, 'Deli_common_symbol', None) and self.Deli_common_symbol in self.ltp_data:
                    self.Deli_common_currLTP = float(self.ltp_data[self.Deli_common_symbol])
                else:
                    # fallback if we have at least two values pick second
                    if len(self.ltp_data) >= 2:
                        values = list(self.ltp_data.values())
                        self.Deli_common_currLTP = float(values[1])
        except Exception as e:
            log_message(f"[ERROR] currentLTP: {e}")

    #+++++++++ Order Update Handling ++++++++++++++
    def on_order_update(self, data):
        """
        FYERS order update handler
        """
        try:
            if data.get("t") != "om":
                return  # not an order message

            order_id = data.get("norenordno")
            status = data.get("status")
            reason = data.get("rejreason", "")

            # Ignore unrelated orders
            if order_id != getattr(self, "active_order_id", None):
                return

            log_message(f"[ORDER] {order_id} → {status}")

            if status == "REJECTED":
                self.handle_order_rejection(reason)

            elif status == "CANCELLED":
                self.handle_order_rejection("Order Cancelled")

            elif status == "COMPLETE":
                self.waiting_for_fill = False
                # avg LTP logic continues normally
                log_message("[ORDER] Filled successfully")

        except Exception as e:
            log_message(f"[ERROR] on_order_update: {e}")
    
    def handle_order_rejection(self, reason):
        log_message(f"[REJECTED] {reason}")

        # UI feedback
        self.order_label.setStyleSheet("color: Red")
        self.order_label.setText(f"Order Rejected ❌: {reason}")

        # Reset flags
        if self.active_order_side == "PE":
            self.PE_buy_flag = False
            self.PE_order_flag = False
        elif self.active_order_side == "CE":
            self.CE_buy_flag = False
            self.CE_order_flag = False

        # Reset UI
        self.stoploss_button.setEnabled(False)
        self.target_button.setEnabled(False)
        self.set_button_busy(self.MY_PE_buy_button, False,"&PE Buy")
        self.set_button_busy(self.MY_CE_buy_button, False,"&CE Buy")

        # Clear active order
        self.active_order_id = None
        self.waiting_for_fill = False
    
    def check_order_timeout(self):
        if getattr(self, "waiting_for_fill", False):
            log_message("[TIMEOUT] Order not confirmed")

            self.handle_order_rejection("Order timeout / No response from exchange")

    # +++++++++ LTP and Token Handling ++++++++++++++
    def GetLTP(self, exchange, token, callback=None, max_retries=3):
        """
        Get Last Traded Price (LTP) - NON-BLOCKING version with automatic retries.
        Args:
            exchange: Exchange name (e.g., 'NFO')
            token: Token ID as string
            callback: Function to call with result - callback(ltp_value)
            max_retries: Number of retry attempts (default: 3)
        
        Returns:
            If callback is None, returns 0 immediately (backward compatibility)
            If callback provided, returns None and calls callback with LTP or 0
        
        Example:
            # With callback (recommended):
            self.GetLTP('NFO', '12345', lambda ltp: print(f"LTP: {ltp}"))
            
            # Without callback (backward compatibility, returns 0):
            ltp = self.GetLTP('NFO', '12345')  # Returns 0 immediately
        """
        
        if token is None:
            if callback:
                callback(0.0)
            return 0.0
        
        # If no callback, return 0 for backward compatibility
        # (Original code expected synchronous return)
        if callback is None:
            log_message(f"[WARN] GetLTP called without callback for token {token}")
            return 0.0
        
        # Check if we already have a pending request for this token
        request_key = f"{exchange}_{token}"
        if request_key in self.pending_ltp_requests:
            log_message(f"[LTP] Request already pending for {request_key}")
            return None
        
        self.pending_ltp_requests[request_key] = True
        
        def fetch_with_retry(attempt=0):
            """Internal function to handle retries"""
            
            def on_success(result):
                """Called when API call succeeds"""
                # Remove from pending
                self.pending_ltp_requests.pop(request_key, None)
                
                if result and 'lp' in result:
                    ltp = float(result['lp'])
                    log_message(f"[LTP] ✅ {exchange}:{token} = {ltp}")
                    callback(ltp)
                else:
                    log_message(f"[LTP] ⚠️ No 'lp' in response for {token}")
                    self.pending_ltp_requests.pop(request_key, None)
                    callback(0.0)
            
            def on_error(error_tuple):
                """Called when API call fails"""
                exc, tb = error_tuple
                
                # Retry if attempts remaining
                if attempt < max_retries - 1:
                    retry_delay = 500  # milliseconds
                    log_message(f"[LTP] ⚠️ Attempt {attempt + 1} failed for {token}, retrying in {retry_delay}ms: {exc}")
                    
                    # Schedule retry after delay
                    QTimer.singleShot(retry_delay, lambda: fetch_with_retry(attempt + 1))
                else:
                    # No more retries, return 0
                    log_message(f"[LTP] ❌ All {max_retries} attempts failed for {token}: {exc}")
                    self.pending_ltp_requests.pop(request_key, None)
                    callback(0.0)
            
            # Create worker and execute
            worker = APIWorker(self.api_master.get_quotes, exchange, str(token))
            worker.signals.result.connect(on_success)
            worker.signals.error.connect(on_error)
            
            # Start the worker in thread pool
            self.api_threadpool.start(worker)
        
        # Start the first attempt
        fetch_with_retry(attempt=0)
        return None

    def GetToken(self, exchange, tradingSymbol, callback=None):
        """
        Get token for a trading symbol - NON-BLOCKING version.
        
        Args:
            exchange: Exchange name (e.g., 'NFO')
            tradingSymbol: Trading symbol string
            callback: Function to call with result - callback(token)
        
        Returns:
            If callback is None, returns None immediately
            If callback provided, calls callback with token or None
        
        Example:
            self.GetToken('NFO', 'NIFTY25DEC2425500CE', lambda token: print(f"Token: {token}"))
        """
        
        if callback is None:
            log_message(f"[WARN] GetToken called without callback for {tradingSymbol}")
            return None
        
        def on_success(response):
            """Called when searchscrip succeeds"""
            if response and 'values' in response and response['values']:
                token = response['values'][0].get('token')
                log_message(f"[TOKEN] ✅ {tradingSymbol} = {token}")
                callback(token)
            else:
                log_message(f"[TOKEN] ⚠️ No token found for {tradingSymbol}")
                callback(None)
        
        def on_error(error_tuple):
            """Called when searchscrip fails"""
            exc, tb = error_tuple
            log_message(f"[TOKEN] ❌ Failed for {tradingSymbol}: {exc}")
            callback(None)
        
        # Create and execute worker
        worker = APIWorker(self.api_master.searchscrip, exchange=exchange, searchtext=tradingSymbol)
        worker.signals.result.connect(on_success)
        worker.signals.error.connect(on_error)
        self.api_threadpool.start(worker)
        
        return None

    def find_buy_avgLTP(self, symbol, callback=None, max_retries=3, ordernos_map=None, fills_map=None, prefer_tradebook=False):
        """
        Find buy average LTP - NON-BLOCKING version with retry logic.
        
        Args:
            symbol: Trading symbol to find position for
            callback: Function to call with result - callback(avg_ltp)
            max_retries: Number of retry attempts (default: 3)
            ordernos_map: Optional dict of account->orderno to pin avg to latest order
            fills_map: Optional dict of account->fill details (preferred for weighting)
            prefer_tradebook: If True and ordernos_map provided, prefer tradebook avg over broker netavgprc
        
        Returns:
            If callback is None, returns 0.0 immediately (backward compatibility)
            If callback provided, calls callback with avg_ltp or 0.0
        
        Example:
            self.find_buy_avgLTP('NIFTY25DEC2425500PE', lambda avg: print(f"Avg: {avg}"))
        """
        self.rpnl, self.Total_mtm, __ = self.calculate_position_mtm()

        if not hasattr(self, 'symbol_qty_map'):
            self.symbol_qty_map = {}
        if not hasattr(self, 'symbol_avg_map'):
            self.symbol_avg_map = {}
        
        # Backward compatibility - return 0 if no callback
        if callback is None:
            log_message(f"[WARN] find_buy_avgLTP called without callback for {symbol}")
            return 0.0
        
        def fetch_with_retry(attempt=0):
            """Internal function to handle retries"""
            
            def on_success(positions):
                """Called when get_positions succeeds"""
                buy_ltp = 0.0
                fresh_entry = False
                symbol_netqty = None
                broker_avg = None
                
                try:
                    if not positions:
                        log_message(f"[POS] ⚠️ No positions returned for {symbol}")
                        callback(0.0)
                        return
                    
                    for position in positions:
                        try:
                            tsym = position['tsym']
                            netavgprc = float(position['netavgprc'])
                            netqty = int(position['netqty'])
                            
                            prev_qty = self.symbol_qty_map.get(tsym, 0)
                            prev_avg = self.symbol_avg_map.get(tsym, 0.0)
                            
                            # Found our symbol
                            if netqty > 0 and tsym == symbol and netavgprc != 0:
                                # In REAL MODE, netavgprc from broker is the TOTAL blended average
                                # Always use broker's figure as it's the authoritative source
                                broker_avg = round(netavgprc, 2)
                                buy_ltp = broker_avg
                                fresh_entry = prev_qty <= 0
                                symbol_netqty = netqty
                                
                                # Update tracking
                                self.symbol_qty_map[tsym] = netqty
                                self.symbol_avg_map[tsym] = netavgprc
                                
                                # Update common netQty if this is the active symbol
                                if self.common_symbol == tsym:
                                    self.netQty = int(self.symbol_qty_map[tsym])
                                    # keep integer lots / netQty consistent (use helper)
                                    self.set_position_lots(self.netQty // self.lot_size)

                                log_message(f"[POS] ✅ {symbol} Qty={netqty}, Avg={buy_ltp}")
                                
                            elif tsym == symbol and netqty <= 0:
                                # Position closed
                                self.symbol_qty_map[tsym] = 0
                                self.symbol_avg_map[tsym] = 0.0
                                log_message(f"[POS] Position closed for {symbol}")
                                if tsym == getattr(self, 'common_symbol', None) and not getattr(self, "waiting_for_fill", False):
                                    self._clear_mis_state("Broker reports position closed")
                        
                        except Exception as e:
                            log_message(f"[POS] ⚠️ Error processing position: {e}")
                            continue
                    
                    if buy_ltp > 0:
                        log_message(
                            f"[AVG] {symbol} broker_avg={broker_avg} netqty={symbol_netqty} "
                            f"fresh_entry={fresh_entry} prefer_tradebook={bool(prefer_tradebook)} "
                            f"ordernos_map={'yes' if ordernos_map else 'no'}"
                        )
                        # If caller explicitly wants tradebook avg for this specific order, honor it.
                        if prefer_tradebook and ordernos_map and symbol_netqty and symbol_netqty > 0:
                            try:
                                trade_avg = self._get_latest_trade_avg_multi(symbol, "B", ordernos_map, fills_map)
                                if trade_avg and trade_avg > 0:
                                    log_message(f"[AVG] {symbol} using ORDER tradebook avg={trade_avg} (override broker_avg={broker_avg})")
                                    log_message(f"[TRADEBOOK] Using order-filtered buy avg for {symbol}: {trade_avg}")
                                    callback(trade_avg)
                                    return
                            except Exception as e:
                                log_message(f"[TRADEBOOK] Order-filtered avg failed for {symbol}: {e}")
                        # If this looks like a fresh entry, prefer tradebook avg when available
                        if fresh_entry:
                            def on_tradebook_fresh(trade_avg):
                                if trade_avg and trade_avg > 0:
                                    log_message(f"[AVG] {symbol} using FRESH tradebook avg={trade_avg} (broker_avg={broker_avg})")
                                    log_message(f"[TRADEBOOK] Fresh entry avg for {symbol}: {trade_avg}")
                                    callback(trade_avg)
                                else:
                                    log_message(f"[AVG] {symbol} using broker_avg={broker_avg} (no fresh tradebook avg)")
                                    callback(buy_ltp)

                            def on_tradebook_fresh_error(err):
                                log_message(f"[TRADEBOOK] Fresh entry tradebook fetch failed for {symbol}: {err}")
                                callback(buy_ltp)

                            worker_tb = APIWorker(self._get_latest_trade_avg_multi, symbol, "B")
                            worker_tb.signals.result.connect(on_tradebook_fresh)
                            worker_tb.signals.error.connect(on_tradebook_fresh_error)
                            self.api_threadpool.start(worker_tb)
                            return

                        log_message(f"[AVG] {symbol} using broker_avg={broker_avg} (no tradebook override)")
                        callback(buy_ltp)
                        return

                    # Fallback: use tradebook for latest buy avg
                    def on_tradebook(trade_avg):
                        if trade_avg and trade_avg > 0:
                            log_message(f"[AVG] {symbol} fallback tradebook avg={trade_avg}")
                            log_message(f"[TRADEBOOK] Using latest buy avg for {symbol}: {trade_avg}")
                            callback(trade_avg)
                        else:
                            log_message(f"[AVG] {symbol} fallback tradebook avg not found; returning 0.0")
                            callback(0.0)

                    def on_tradebook_error(err):
                        log_message(f"[TRADEBOOK] Failed to fetch tradebook for {symbol}: {err}")
                        callback(0.0)

                    worker_tb = APIWorker(self._get_latest_trade_avg_multi, symbol, "B")
                    worker_tb.signals.result.connect(on_tradebook)
                    worker_tb.signals.error.connect(on_tradebook_error)
                    self.api_threadpool.start(worker_tb)
                    return
                    
                except Exception as e:
                    log_message(f"[POS] ❌ Error in on_success: {e}")
                    callback(0.0)
            
            def on_error(error_tuple):
                """Called when get_positions fails"""
                exc, tb = error_tuple
                
                # Retry if attempts remaining
                if attempt < max_retries - 1:
                    retry_delay = 500  # milliseconds
                    log_message(f"[POS] ⚠️ Attempt {attempt + 1} failed for {symbol}, retrying in {retry_delay}ms: {exc}")
                    
                    # Schedule retry after delay
                    QTimer.singleShot(retry_delay, lambda: fetch_with_retry(attempt + 1))
                else:
                    # No more retries
                    log_message(f"[POS] ❌ All {max_retries} attempts failed for {symbol}: {exc}")
                    callback(0.0)
            
            # Create worker and execute
            worker = APIWorker(self.api_master.get_positions)
            worker.signals.result.connect(on_success)
            worker.signals.error.connect(on_error)
            self.api_threadpool.start(worker)
        
        # Start the first attempt
        fetch_with_retry(attempt=0)
        return None

    def findATM_strike(self, Symbol, strikeDiff):
        """Find ATM strike price"""
        try:
            # During internet/DNS outage, avoid blocking UI on repeated REST calls.
            now_ts = time.time()
            cached_atm, cached_ltp = self._atm_cache.get(Symbol, (0, 0.0))
            if (not getattr(self, "websocket_connected", False)) and cached_atm:
                return cached_atm, cached_ltp
            if (now_ts - float(getattr(self, "_atm_last_error_ts", 0.0))) < 3.0 and cached_atm:
                return cached_atm, cached_ltp
            
            if Symbol == 'NIFTY':
                index = self.api_master.get_quotes('NSE',Config.NiftyToken)
            elif Symbol == 'BANKNIFTY':
                index = self.api_master.get_quotes('NSE',Config.BankNiftyToken)
            else:
                return 0, 0

            if not index or 'lp' not in index:
                return 0, 0

            indexLTP = float(index['lp'])
            mod = int(indexLTP) % strikeDiff
            if mod < (strikeDiff/2):
                atmStrike = int(math.floor(indexLTP/strikeDiff)) * strikeDiff
            else:
                atmStrike = int(math.ceil(indexLTP/strikeDiff)) * strikeDiff

            self._atm_cache[Symbol] = (atmStrike, indexLTP)
            return atmStrike, indexLTP
        except Exception as e:
            self._atm_last_error_ts = time.time()
            log_message(f"[ERROR] findATM_strike: {e}")
            return self._atm_cache.get(Symbol, (0, 0.0))

    def extract_expiry(self, date_str):
        """Convert expiry date to YYMDD format like 26317"""        
        try:
            date_obj = datetime.datetime.strptime(date_str, "%d-%b-%Y")

            year = date_obj.strftime("%y")     # 25
            month = str(date_obj.month)        # 3
            day = date_obj.strftime("%d")      # 17

            return f"{year}{month}{day}"
        except ValueError:
            log_message(f"[ERROR] Invalid date format: {date_str}")
            return "Invalid date format"
    
    #+++++++++ Multi-account Order Handling ++++++++++++++
    def multi_place_order(self, buy_or_sell, product_type, exchange, tradingsymbol, 
                        quantity, price_type='MKT', price=0.0, trigger_price=None, 
                        remarks='my_order_001'):
        """
        Place same order across all accounts IN PARALLEL.
        
        Args:
            buy_or_sell: 'B' or 'S'
            product_type: 'M' (MIS) or 'C' (CNC)
            exchange: 'NFO', 'NSE', etc.
            tradingsymbol: Trading symbol
            quantity: Order quantity
            price_type: 'MKT', 'LMT', 'SL-LMT'
            price: Limit price
            trigger_price: Stop loss trigger
            remarks: Order remarks
        
        Returns:
            Dict of {user_id: response} for all accounts
        """
        
        # Normalize and validate quantity to be multiple of lot size
        try:
            req_qty = int(quantity)
        except Exception:
            req_qty = int(quantity or 0)

        try:
            ls = int(self.lot_size) if hasattr(self, 'lot_size') else 1
        except Exception:
            ls = 1

        if ls and req_qty % ls != 0:
            adj_qty = (req_qty // ls) * ls
            log_message(f"[ORDER] ⚠️ Requested qty {req_qty} not multiple of lot_size {ls}. Adjusting to {adj_qty}.")
            # If adjusted becomes zero, set to one lot
            if adj_qty <= 0:
                adj_qty = ls
        else:
            adj_qty = req_qty

        def place_for_user(uid, api):
            """Place order for single user - runs in thread"""
            try:
                resp = api.place_order(
                    buy_or_sell=buy_or_sell,
                    product_type=product_type,
                    exchange=exchange,
                    tradingsymbol=tradingsymbol,
                    quantity=adj_qty,
                    discloseqty=0,
                    price_type=price_type,
                    price=price,
                    trigger_price=trigger_price,
                    retention='DAY',
                    remarks=remarks
                )
                
                if resp and 'norenordno' in resp:
                    log_message(f"[ORDER] ✅ {uid}: {tradingsymbol} orderno={resp['norenordno']}")
                    return uid, resp, resp['norenordno']
                else:
                    log_message(f"[ORDER] ⚠️ {uid}: {tradingsymbol} resp={resp}")
                    return uid, resp, None
                    
            except requests.exceptions.Timeout:
                log_message(f"[ORDER] ⏱️ {uid}: Timeout")
                return uid, None, None
            except Exception as e:
                log_message(f"[ORDER] ❌ {uid}: {e}")
                return uid, None, None
        
        # ✅ CHANGED: Execute in parallel using ThreadPoolExecutor
        results = {}
        futures = {}
        
        for uid, acc in self.multimgr.accounts.items():
            future = self.executor.submit(place_for_user, uid, acc['api'])
            futures[future] = uid
        
        # Collect results as they complete
        for future in as_completed(futures, timeout=10):
            try:
                uid, resp, orderno = future.result()
                results[uid] = resp
                
                # Store order number in account
                if orderno:
                    acc = self.multimgr.accounts[uid]
                    acc['orders'].setdefault(tradingsymbol, []).append(orderno)
                    
            except Exception as e:
                uid = futures[future]
                log_message(f"[ORDER] ❌ {uid}: Future exception: {e}")
                results[uid] = None
        
        return results

    def multi_modify_order(self, tradingsymbol, newprice_type, newprice, newtrigger_price=None):
        """
        Modify order across all accounts IN PARALLEL.
        
        Args:
            tradingsymbol: Symbol to modify
            newprice_type: 'MKT', 'LMT', 'SL-LMT'
            newprice: New price
            newtrigger_price: New trigger price
        
        Returns:
            Dict of {user_id: response} for all accounts
        """
        
        def modify_for_user(uid, api, orderno):
            """Modify order for single user - runs in thread"""
            try:
                # Determine appropriate quantity for modification:
                # If this is an existing mapped exit order (target/stoploss/exit), use its qty.
                new_qty = None
                try:
                    pos_map = getattr(self, 'position_orders', {}) or {}
                    po = pos_map.get(tradingsymbol, {})
                    for key in ('target', 'stoploss', 'exit'):
                        if po.get(key) and isinstance(po.get(key).get('qty'), int):
                            new_qty = po.get(key).get('qty')
                            break
                except Exception:
                    new_qty = None

                if new_qty is None:
                    try:
                        new_qty = int(self.position_lots) * int(self.lot_size)
                    except Exception:
                        new_qty = 0

                resp = api.modify_order(
                    exchange='NFO',
                    tradingsymbol=tradingsymbol,
                    orderno=orderno,
                    newquantity=new_qty,
                    newprice_type=newprice_type,
                    newprice=newprice,
                    newtrigger_price=newtrigger_price
                )
                log_message(f"[MODIFY] ✅ {uid}: {tradingsymbol} orderno={orderno}")
                return uid, resp
            except Exception as e:
                log_message(f"[MODIFY] ❌ {uid}: {e}")
                return uid, None
        
        # ✅ CHANGED: Execute in parallel
        results = {}
        futures = {}
        
        for uid, acc in self.multimgr.accounts.items():
            order_list = acc['orders'].get(tradingsymbol, [])
            if not order_list:
                log_message(f"[MODIFY] ⚠️ {uid}: No orders for {tradingsymbol}")
                results[uid] = None
                continue
            
            orderno = order_list[-1]
            future = self.executor.submit(modify_for_user, uid, acc['api'], orderno)
            futures[future] = uid
        
        # Collect results
        for future in as_completed(futures, timeout=10):
            try:
                uid, resp = future.result()
                results[uid] = resp
            except Exception as e:
                uid = futures[future]
                log_message(f"[MODIFY] ❌ {uid}: Future exception: {e}")

    def multi_cancel_order(self, tradingsymbol):
        """
        Cancel the latest order for `tradingsymbol` across all logged accounts in parallel.

        Returns dict of {user_id: response} where response is the API cancel response or None.
        """
        def cancel_for_user(uid, api, orderno):
            try:
                resp = api.cancel_order(orderno=orderno)
                log_message(f"[CANCEL] ✅ {uid}: {tradingsymbol} orderno={orderno}")
                return uid, resp
            except Exception as e:
                log_message(f"[CANCEL] ❌ {uid}: {e}")
                return uid, None

        results = {}
        futures = {}

        for uid, acc in self.multimgr.accounts.items():
            order_list = acc.get('orders', {}).get(tradingsymbol, [])
            if not order_list:
                log_message(f"[CANCEL] ⚠️ {uid}: No orders for {tradingsymbol}")
                results[uid] = None
                continue

            orderno = order_list[-1]
            future = self.executor.submit(cancel_for_user, uid, acc['api'], orderno)
            futures[future] = uid

        for future in as_completed(futures, timeout=10):
            try:
                uid, resp = future.result()
                results[uid] = resp
            except Exception as e:
                uid = futures[future]
                log_message(f"[CANCEL] ❌ {uid}: Future exception: {e}")
                results[uid] = None

        return results
 
    def round_to_tick(self, price, tick_size=0.05):
        """Round price to tick size"""
        return round(round(price / tick_size) * tick_size, 2)

    def _has_existing_order(self, symbol):
        """Return True if any account has a stored order for symbol"""
        if not symbol or not hasattr(self, 'multimgr'):
            return False
        for acc in self.multimgr.accounts.values():
            orders = acc.get('orders', {})
            if orders.get(symbol):
                return True
        return False

    def _cancel_broker_pending_exit_orders(self, symbol: str) -> int:
        """Cancel broker-side pending SELL orders for this symbol even if local tracking missed them."""
        if not symbol or not hasattr(self, 'multimgr'):
            return 0

        pending_status = {
            'OPEN', 'PENDING', 'NEW', 'REPLACED', 'TRIGGER_PENDING',
            'PUT ORDER REQ RECEIVED', 'MODIFY PENDING', 'AMO REQ RECEIVED'
        }
        total_cancelled = 0

        for uid, acc in self.multimgr.accounts.items():
            api = acc.get('api')
            if not api:
                continue
            try:
                ob = api.get_order_book() or []
            except Exception as e:
                log_message(f"[TARGET] {uid}: orderbook fetch failed while cancelling exits: {e}")
                continue

            for od in ob:
                try:
                    tsym = str(od.get('tsym') or '')
                    status = str(od.get('status') or '').upper()
                    side = str(od.get('trantype') or '').upper()
                    if tsym != symbol or side not in {'S', 'SELL'} or status not in pending_status:
                        continue

                    orderno = od.get('norenordno') or od.get('orderno')
                    if not orderno:
                        continue

                    api.cancel_order(orderno=orderno)
                    total_cancelled += 1
                    log_message(f"[TARGET] {uid}: cancelled broker exit order {orderno} ({status})")
                except Exception as e:
                    log_message(f"[TARGET] {uid}: failed cancelling broker exit order: {e}")

        if total_cancelled > 0 and symbol in self.position_orders:
            for key in ('target', 'stoploss', 'exit'):
                if self.position_orders[symbol].get(key):
                    self.position_orders[symbol][key]['status'] = 'CANCELLED'

        return total_cancelled

    def manual_set_target(self):
        log_message("[TARGET] Manual set target initiated")
        self.set_target()

    def set_target(self):
        self.set_button_busy(self.target_button, True, "Setting Target...")
        """Set target price
        The routine mirrors :meth:`set_stoploss` but for profit-taking orders.
        To avoid duplicate orders when multiple parts of the program call this
        method in quick succession (manual button click, live-price updates,
        priority logic), we perform a cooldown check and inspect the existing
        target order status before placing a new one.  The previous implementation
        simply cancelled everything unconditionally which could lead to two back-to-
        back API calls and/or race conditions with the websocket updates.
        """
        try:
            # ✅ COOLDOWN CHECK: prevent rapid-fire target placement
            pre_cancelled = False
            if not hasattr(self, '_last_target_placement_time'):
                self._last_target_placement_time = None
            if self._last_target_placement_time:
                since = (datetime.datetime.now() - self._last_target_placement_time).total_seconds()
                if since < 2.0:
                    log_message(f"[TARGET] Cooldown active ({since:.1f}s since last); skipping placement")
                    return

            # Always cancel all exit orders before placing a new target
            if self.common_symbol:
                self._init_position_orders(self.common_symbol)
                if self._has_any_exit_order(self.common_symbol):
                    log_message(f"[TARGET] Cancelling all existing exit orders for {self.common_symbol} before new target")
                    self._cancel_all_exit_orders(self.common_symbol)
                    pre_cancelled = True
                broker_cancelled = self._cancel_broker_pending_exit_orders(self.common_symbol)
                if broker_cancelled > 0:
                    pre_cancelled = True
                # check for an existing target order and its status, similar to SL logic
                if self.Target_order_flag or self.position_orders.get(self.common_symbol, {}).get('target'):
                    try:
                        existing_t = self.position_orders[self.common_symbol].get('target')
                        has_order_id = existing_t and existing_t.get('order_id')
                        current_status = existing_t.get('status', 'PENDING') if existing_t else None
                        if has_order_id and current_status == 'PENDING':
                            log_message(f"[TARGET] Existing target PENDING - cancelling before new placement...")
                            self._cancel_all_exit_orders(self.common_symbol)
                        elif has_order_id and current_status in ('EXECUTED', 'FILLED', 'COMPLETE'):
                            log_message(f"[TARGET] Existing target already {current_status} - clearing tracking")
                            self.position_orders[self.common_symbol]['target'] = {}
                            self.Target_order_flag = False
                            # if completion closed entire position, skip further target placement
                            try:
                                remaining = int(self.position_lots)
                            except Exception:
                                remaining = 0
                            if remaining <= 0:
                                # fallback to symbol_qty_map if available
                                try:
                                    remaining = int(self.symbol_qty_map.get(self.common_symbol, 0) // int(self.lot_size))
                                except Exception:
                                    pass
                            if remaining <= 0:
                                log_message(f"[TARGET] No remaining lots for {self.common_symbol}; skipping new target")
                                return
                        elif has_order_id and current_status is None:
                            log_message(f"[TARGET] ⚠️ Broker delay - order_id exists but status unknown, skipping")
                            return
                    except Exception as e:
                        log_message(f"[TARGET] Warning verifying existing order: {e}")
            # Basic validation
            if not self.common_avgLTP or self.common_avgLTP <= 0:
                log_message("[ERROR] No entry price available for target calculation")
                return
            if not self.common_symbol:
                log_message("[ERROR] No active symbol to set target for")
                return
            if int(self.position_lots) <= 0:
                log_message("[ERROR] No position lots available to set target")
                return

            input_val = self.target_entry.text()
            # Calculate target price (auto-detects % or price based on input)
            self.targetLTP = self.calculate_target_price(self.common_avgLTP, input_val)
            self.targetLTP = self.round_to_tick(self.targetLTP)
            self.target_entry.setText(str(self.targetLTP))

            if self.targetLTP <= 0:
                log_message(f"[ERROR] Invalid target price: {self.targetLTP}")
                return

            # Determine exit quantity
            squareoff_lots_text = self.squareoff_lots.text().strip()
            if squareoff_lots_text != '':
                try:
                    exit_lots = int(squareoff_lots_text)
                except ValueError:
                    log_message(f"[ERROR] Invalid TARGET lots: {squareoff_lots_text}")
                    return
                if exit_lots <= 0:
                    log_message(f"[ERROR] TARGET lots must be positive")
                    return
                if exit_lots > int(self.position_lots):
                    log_message(f"[ERROR] Cannot SET TARGET {exit_lots} lots, only {self.position_lots} lots in position")
                    return
                is_partial_target = True
                if exit_lots < int(self.position_lots):
                    is_partial_target = True
                elif exit_lots == int(self.position_lots):
                    is_partial_target = False
            else:
                exit_lots = int(self.position_lots)
                is_partial_target = False

            pre_exit_lots = int(self.position_lots)
            remaining_lots = pre_exit_lots - exit_lots
            TARGET_qty = exit_lots * int(self.lot_size)

            log_message(f'[TARGET] {self.common_symbol} {"Partial" if is_partial_target else "Full"} target:')
            log_message(f'  TARGET: {exit_lots} lots @ {self.targetLTP}, Avg: {self.common_avgLTP}')
            if is_partial_target:
                log_message(f'  Remaining: {remaining_lots} lots @ {self.common_avgLTP}')
                # ⚠️ DO NOT update position_lots here — keep full position active.
                # Actual position remains unchanged until broker confirms exit fill.

            log_message(f"[TARGET] Entry: {self.common_avgLTP}, Input: {input_val} → Target Price: {self.targetLTP}")

            # modify if there is an existing target order recorded for this symbol, otherwise place new
            existing_target = False
            try:
                existing_target = bool(self.position_orders.get(self.common_symbol, {}).get('target'))
            except Exception:
                existing_target = False

            if not existing_target:
                # Paper mode: simulate placement and update local tracking
                if self.PaperTrade_checkbox.isChecked():
                    # Paper mode: simulate placement but DO NOT modify tracked position here.
                    # Tracked position (`symbol_qty_map` / `position_lots`) should reflect actual position
                    # until an exit fill is simulated/confirmed.
                    self.multi_place_order('S', 'M', 'NFO', self.common_symbol, TARGET_qty, 'LMT', self.targetLTP)

                    # ✅ Map target order (do not change tracked qty)
                    self._init_position_orders(self.common_symbol)
                    self.position_orders[self.common_symbol]['target'] = {
                        'order_id': 'PAPER_MODE',
                        'qty': TARGET_qty,
                        'price': self.targetLTP,
                        'side': 'S',
                        'order_type': 'LMT',
                        'status': 'PENDING',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'placed_by': 'set_target()'
                    }
                    # record placement time for cooldown logic
                    self._last_target_placement_time = datetime.datetime.now()
                    QTimer.singleShot(2000, lambda: self._log_target_placed())
                else:
                    # Real mode: place LMT across accounts (do not wait for fills)
                    results = self.multi_place_order('S', 'M', 'NFO', self.common_symbol, TARGET_qty, 'LMT', self.targetLTP)
                    log_message(f"[TARGET] multi_place_order results: {results}")

                    # Build ordnos map from responses
                    ordernos = {}
                    for uid, resp in results.items():
                        try:
                            if isinstance(resp, dict):
                                ordno = resp.get('norenordno') or resp.get('ordno') or resp.get('orderId') or resp.get('order_id')
                                if ordno:
                                    ordernos[uid] = ordno
                        except Exception:
                            continue

                    if ordernos:
                        # ✅ Map target order with metadata
                        self._init_position_orders(self.common_symbol)
                        self.position_orders[self.common_symbol]['target'] = {
                            'order_id': list(ordernos.values())[0],
                            'qty': TARGET_qty,
                            'price': self.targetLTP,
                            'side': 'S',
                            'order_type': 'LMT',
                            'status': 'PENDING',
                            'timestamp': datetime.datetime.now().isoformat(),
                            'placed_by': 'set_target()'
                        }
                        # persist mapping for later modify/cancel
                        self.common_orderID = ordernos
                        # record placement time for cooldown logic
                        self._last_target_placement_time = datetime.datetime.now()
                        log_message(f"[TARGET] Order mapped - sample ID: {list(ordernos.values())[0]}, Qty: {TARGET_qty} @ {self.targetLTP}")
                        # Update broker MTM once after placing target order
                        try:
                            _, self.daily_total_MTM, __ = self.calculate_position_mtm()
                            log_message(f"[TARGET] Broker MTM updated after placing target: ₹{self.daily_total_MTM:.2f}")
                        except Exception:
                            pass
                        QTimer.singleShot(2000, lambda: self._log_target_placed())
                    else:
                        log_message(f"[TARGET] No order numbers received from multi_place_order for {self.common_symbol}; results: {results}")
            else:
                # Existing target detected — cancel any existing exit orders first
                if not pre_cancelled:
                    log_message(f"[TARGET] Existing target detected. Cancelling existing exit orders before placing new target for {self.common_symbol}")
                    try:
                        if self.common_symbol:
                            self._init_position_orders(self.common_symbol)
                            self._cancel_all_exit_orders(self.common_symbol)
                            self._cancel_broker_pending_exit_orders(self.common_symbol)
                    except Exception as e:
                        log_message(f"[TARGET] Warning cancelling existing orders: {e}")

                # After cancelling, place a fresh target order (paper or real)
                if self.PaperTrade_checkbox.isChecked():
                    # Paper mode replacement: place new target but keep tracked position unchanged
                    self.multi_place_order('S', 'M', 'NFO', self.common_symbol, TARGET_qty, 'LMT', self.targetLTP)

                    self._init_position_orders(self.common_symbol)
                    self.position_orders[self.common_symbol]['target'] = {
                        'order_id': 'PAPER_MODE',
                        'qty': TARGET_qty,
                        'price': self.targetLTP,
                        'side': 'S',
                        'order_type': 'LMT',
                        'status': 'PENDING',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'placed_by': 'set_target()'
                    }
                    QTimer.singleShot(2000, lambda: self._log_target_placed())
                else:
                    results = self.multi_place_order('S', 'M', 'NFO', self.common_symbol, TARGET_qty, 'LMT', self.targetLTP)
                    log_message(f"[TARGET] multi_place_order results (replaced): {results}")

                    ordernos = {}
                    for uid, resp in results.items():
                        try:
                            if isinstance(resp, dict):
                                ordno = resp.get('norenordno') or resp.get('ordno') or resp.get('orderId') or resp.get('order_id')
                                if ordno:
                                    ordernos[uid] = ordno
                        except Exception:
                            continue

                    if ordernos:
                        self._init_position_orders(self.common_symbol)
                        self.position_orders[self.common_symbol]['target'] = {
                            'order_id': list(ordernos.values())[0],
                            'qty': TARGET_qty,
                            'price': self.targetLTP,
                            'side': 'S',
                            'order_type': 'LMT',
                            'status': 'PENDING',
                            'timestamp': datetime.datetime.now().isoformat(),
                            'placed_by': 'set_target()'
                        }
                        self.common_orderID = ordernos
                        self._last_target_placement_time = datetime.datetime.now()
                        log_message(f"[TARGET] Replaced order mapped - sample ID: {list(ordernos.values())[0]}, Qty: {TARGET_qty} @ {self.targetLTP}")
                        try:
                            _, self.daily_total_MTM, __ = self.calculate_position_mtm()
                            log_message(f"[TARGET] Broker MTM updated after placing target: ₹{self.daily_total_MTM:.2f}")
                        except Exception:
                            pass
                        QTimer.singleShot(2000, lambda: self._log_target_placed())
                    else:
                        log_message(f"[TARGET] No order numbers received when replacing target for {self.common_symbol}; results: {results}")

            # set flags
            self.SL_order_flag = False
            self.Target_order_flag = True
            if not hasattr(self, 'target_info'):
                self.target_info = {}
            self.target_info['target_set'] = False

            if not hasattr(self, 'stoploss_info'):
                self.stoploss_info = {}
            self.stoploss_info['target_set'] = False

            # Store exit info for confirmation only; do not update tracked lots until confirmation in REAL mode
            self.target_info = {
                'is_partial': is_partial_target,
                'exit_lots': exit_lots,
                'remaining_lots': remaining_lots,
                'target_set': True
            }

        except Exception as e:
            log_message(f"[ERROR] set_target: {e}")
        finally:
            # Ensure the UI button is cleared in all cases
            try:
                self.set_button_busy(self.target_button, False, "&Target")
            except Exception:
                pass

    def _log_target_placed(self):
        """Log target placement after delay"""
        if self.common_orderID:
            log_message(f"Target LTP placed for {self.common_symbol} @ {self.targetLTP}")

    def manual_set_stoploss(self):
        log_message("[STOPLOSS] Manual set stoploss initiated")
        self.set_stoploss()

    def set_stoploss(self):
        self.set_button_busy(self.stoploss_button, True, "Setting Stoploss...")
        """Set stop loss"""
        try:
            # ✅ COOLDOWN CHECK: Prevent rapid-fire placement attempts within 2 seconds
            # This handles slow broker responses where status updates lag behind execution
            pre_cancelled = False
            if not hasattr(self, '_last_sl_placement_time'):
                self._last_sl_placement_time = None
            
            if self._last_sl_placement_time:
                time_since_last = (datetime.datetime.now() - self._last_sl_placement_time).total_seconds()
                if time_since_last < 2.0:  # Minimum 2 seconds between SL placements
                    log_message(f"[STOPLOSS] Cooldown active - last placement {time_since_last:.1f}s ago, skipping (prevent broker conflicts)")
                    return
            
            # Always cancel all exit orders before placing a new stoploss
            if self.common_symbol:
                self._init_position_orders(self.common_symbol)
                if self._has_any_exit_order(self.common_symbol):
                    log_message(f"[STOPLOSS] Cancelling all existing exit orders for {self.common_symbol} before new stoploss")
                    self._cancel_all_exit_orders(self.common_symbol)
                    pre_cancelled = True
                broker_cancelled = self._cancel_broker_pending_exit_orders(self.common_symbol)
                if broker_cancelled > 0:
                    pre_cancelled = True
                # ✅ CRITICAL FIX: Check both order_id presence AND status
                # order_id presence = order exists at broker (status may lag behind execution)
                if self.SL_order_flag or self.position_orders.get(self.common_symbol, {}).get('stoploss'):
                    # Check if existing SL is still pending at broker
                    try:
                        existing_sl = self.position_orders[self.common_symbol].get('stoploss')
                        has_order_id = existing_sl and existing_sl.get('order_id')  # Primary gate: order_id presence
                        current_status = existing_sl.get('status', 'PENDING') if existing_sl else None
                        
                        if has_order_id and current_status == 'PENDING':
                            # Order exists and status says PENDING - cancel it
                            log_message(f"[STOPLOSS] Existing SL PENDING - cancelling before new placement...")
                            self._cancel_all_exit_orders(self.common_symbol)
                            
                        elif has_order_id and current_status in ('EXECUTED', 'FILLED', 'COMPLETE'):
                            # Order was filled - clear tracking so new order can be placed
                            log_message(f"[STOPLOSS] Existing SL already {current_status} at broker - clearing for fresh placement")
                            self.position_orders[self.common_symbol]['stoploss'] = {}
                            self.SL_order_flag = False
                            # if completion closed entire position, skip further SL placement
                            try:
                                remaining = int(self.position_lots)
                            except Exception:
                                remaining = 0
                            if remaining <= 0:
                                try:
                                    remaining = int(self.symbol_qty_map.get(self.common_symbol, 0) // int(self.lot_size))
                                except Exception:
                                    pass
                            if remaining <= 0:
                                log_message(f"[STOPLOSS] No remaining lots for {self.common_symbol}; skipping new SL")
                                return
                            
                        elif has_order_id and current_status is None:
                            # ⚠️ SLOW BROKER: order_id exists but status unknown (likely not synced yet)
                            # Assume it's still active and skip new placement to prevent duplicates
                            log_message(f"[STOPLOSS] ⚠️ Broker delay - order_id exists but status not synced yet - skipping placement")
                            return
                            
                    except Exception as e:
                        log_message(f"[STOPLOSS] Warning verifying existing order: {e}")
                        
            # Basic validation
            if not self.common_avgLTP or self.common_avgLTP <= 0:
                log_message("[ERROR] No entry price available for stoploss calculation")
                return
            if not self.common_symbol:
                log_message("[ERROR] No active symbol to set stoploss for")
                return
            if int(self.position_lots) <= 0:
                log_message("[ERROR] No position lots available to set stoploss")
                return

            input_val = self.stoploss_entry.text()
            # Calculate stoploss price (auto-detects % or price based on input)
            self.stoplossLTP = self.calculate_stoploss_price(self.common_avgLTP, input_val)
            self.stoplossLTP = self.round_to_tick(self.stoplossLTP)
            self.stoploss_entry.setText(str(self.stoplossLTP))
            if self.stoplossLTP <= 0:
                log_message(f"[ERROR] Invalid stoploss price: {self.stoplossLTP}")
                return

            # Determine exit quantity
            squareoff_lots_text = self.squareoff_lots.text().strip()
            if squareoff_lots_text != '':
                try:
                    exit_lots = int(squareoff_lots_text)
                except ValueError:
                    log_message(f"[ERROR] Invalid TARGET lots: {squareoff_lots_text}")
                    return
                if exit_lots <= 0:
                    log_message(f"[ERROR] TARGET lots must be positive")
                    return
                if exit_lots > int(self.position_lots):
                    log_message(f"[ERROR] Cannot SET TARGET {exit_lots} lots, only {self.position_lots} lots in position")
                    return
                is_partial_stoploss = True
                if exit_lots < int(self.position_lots):
                    is_partial_stoploss = True
                elif exit_lots == int(self.position_lots):
                    is_partial_stoploss = False
            else:
                exit_lots = int(self.position_lots)
                is_partial_stoploss = False

            pre_exit_lots = int(self.position_lots)
            remaining_lots = pre_exit_lots - exit_lots
            STOPLOSS_qty = exit_lots * int(self.lot_size)

            log_message(f'[STOPLOSS] {self.common_symbol} {"Partial" if is_partial_stoploss else "Full"} stoploss:')
            log_message(f'  STOPLOSS: {exit_lots} lots @ {self.stoplossLTP}, Avg: {self.common_avgLTP}')
            if is_partial_stoploss:
                log_message(f'  Remaining: {remaining_lots} lots @ {self.common_avgLTP}')
                # ⚠️ DO NOT update position_lots here — keep full position active.
                # Actual position remains unchanged until broker confirms exit fill.

            log_message(f"[STOPLOSS] Entry: {self.common_avgLTP}, Input: {input_val} → SL Price: {self.stoplossLTP}")

            # place or modify stoploss based on whether previous stoploss order exists for symbol
            existing_stop = False
            try:
                existing_stop = bool(self.position_orders.get(self.common_symbol, {}).get('stoploss'))
            except Exception:
                existing_stop = False

            if not existing_stop:
                if self.PaperTrade_checkbox.isChecked():
                    # Paper mode: simulate placement but DO NOT modify tracked position here.
                    # Keep `symbol_qty_map` and `position_lots` unchanged until exit fill simulated.
                    self.multi_place_order('S', 'M', 'NFO', self.common_symbol, STOPLOSS_qty, 'SL-LMT', self.stoplossLTP, self.stoplossLTP + 0.5)

                    # ✅ Map stoploss order (do not change tracked qty)
                    self._init_position_orders(self.common_symbol)
                    self.position_orders[self.common_symbol]['stoploss'] = {
                        'order_id': 'PAPER_MODE',
                        'qty': STOPLOSS_qty,
                        'price': self.stoplossLTP,
                        'trigger_price': self.stoplossLTP + 0.5,
                        'side': 'S',
                        'order_type': 'SL-LMT',
                        'status': 'PENDING',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'placed_by': 'set_stoploss()'
                    }
                    # ✅ Record placement time for cooldown
                    self._last_sl_placement_time = datetime.datetime.now()
                    QTimer.singleShot(2000, lambda: self._log_stoploss_placed(self.stoplossLTP))
                else:
                    # Real mode: place SL-LMT across accounts (do not wait for fills)
                    results = self.multi_place_order('S', 'M', 'NFO', self.common_symbol, STOPLOSS_qty, 'SL-LMT', self.stoplossLTP, self.stoplossLTP + 0.5)
                    log_message(f"[STOPLOSS] multi_place_order results: {results}")

                    # Build ordnos map from responses
                    ordernos = {}
                    for uid, resp in results.items():
                        try:
                            if isinstance(resp, dict):
                                ordno = resp.get('norenordno') or resp.get('ordno') or resp.get('orderId') or resp.get('order_id')
                                if ordno:
                                    ordernos[uid] = ordno
                        except Exception:
                            continue

                    if ordernos:
                        # ✅ Map stoploss order with metadata
                        self._init_position_orders(self.common_symbol)
                        self.position_orders[self.common_symbol]['stoploss'] = {
                            'order_id': list(ordernos.values())[0],
                            'qty': STOPLOSS_qty,
                            'price': self.stoplossLTP,
                            'trigger_price': self.stoplossLTP + 0.05,
                            'side': 'S',
                            'order_type': 'SL-LMT',
                            'status': 'PENDING',
                            'timestamp': datetime.datetime.now().isoformat(),
                            'placed_by': 'set_stoploss()'
                        }
                        self.common_orderID = ordernos
                        # ✅ Record placement time for cooldown mechanism
                        self._last_sl_placement_time = datetime.datetime.now()
                        log_message(f"[STOPLOSS] Order mapped - sample ID: {list(ordernos.values())[0]}, Qty: {STOPLOSS_qty} @ {self.stoplossLTP} (Trigger: {self.stoplossLTP + 0.05})")
                        # Update broker MTM once after placing stoploss order
                        try:
                            _, self.daily_total_MTM, __ = self.calculate_position_mtm()
                            log_message(f"[STOPLOSS] Broker MTM updated after placing stoploss: ₹{self.daily_total_MTM:.2f}")
                        except Exception:
                            pass
                        QTimer.singleShot(2000, lambda: self._log_stoploss_placed(self.stoplossLTP))
                    else:
                        log_message(f"[STOPLOSS] No order numbers received from multi_place_order for {self.common_symbol}; results: {results}")
            else:
                # Existing stoploss detected — cancel any existing exit orders first
                if not pre_cancelled:
                    log_message(f"[STOPLOSS] Existing stoploss detected. Cancelling existing exit orders before placing new SL for {self.common_symbol}")
                    try:
                        if self.common_symbol:
                            self._init_position_orders(self.common_symbol)
                            self._cancel_all_exit_orders(self.common_symbol)
                            self._cancel_broker_pending_exit_orders(self.common_symbol)
                    except Exception as e:
                        log_message(f"[STOPLOSS] Warning cancelling existing orders: {e}")

                # After cancelling, place a fresh stoploss order
                if self.PaperTrade_checkbox.isChecked():
                    # Paper mode replacement: place new SL but keep tracked position unchanged
                    self.multi_place_order('S', 'M', 'NFO', self.common_symbol, STOPLOSS_qty, 'SL-LMT', self.stoplossLTP, self.stoplossLTP + 0.5)

                    self._init_position_orders(self.common_symbol)
                    self.position_orders[self.common_symbol]['stoploss'] = {
                        'order_id': 'PAPER_MODE',
                        'qty': STOPLOSS_qty,
                        'price': self.stoplossLTP,
                        'trigger_price': self.stoplossLTP + 0.5,
                        'side': 'S',
                        'order_type': 'SL-LMT',
                        'status': 'PENDING',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'placed_by': 'set_stoploss()'
                    }
                    # ✅ Record placement time for cooldown mechanism
                    self._last_sl_placement_time = datetime.datetime.now()
                    QTimer.singleShot(2000, lambda: self._log_stoploss_placed(self.stoplossLTP))
                else:
                    results = self.multi_place_order('S', 'M', 'NFO', self.common_symbol, STOPLOSS_qty, 'SL-LMT', self.stoplossLTP, self.stoplossLTP + 0.5)
                    log_message(f"[STOPLOSS] multi_place_order results (replaced): {results}")

                    ordernos = {}
                    for uid, resp in results.items():
                        try:
                            if isinstance(resp, dict):
                                ordno = resp.get('norenordno') or resp.get('ordno') or resp.get('orderId') or resp.get('order_id')
                                if ordno:
                                    ordernos[uid] = ordno
                        except Exception:
                            continue

                    if ordernos:
                        self._init_position_orders(self.common_symbol)
                        self.position_orders[self.common_symbol]['stoploss'] = {
                            'order_id': list(ordernos.values())[0],
                            'qty': STOPLOSS_qty,
                            'price': self.stoplossLTP,
                            'trigger_price': self.stoplossLTP + 0.05,
                            'side': 'S',
                            'order_type': 'SL-LMT',
                            'status': 'PENDING',
                            'timestamp': datetime.datetime.now().isoformat(),
                            'placed_by': 'set_stoploss()'
                        }
                        self.common_orderID = ordernos
                        # ✅ Record placement time for cooldown mechanism
                        self._last_sl_placement_time = datetime.datetime.now()
                        log_message(f"[STOPLOSS] Replaced order mapped - sample ID: {list(ordernos.values())[0]}, Qty: {STOPLOSS_qty} @ {self.stoplossLTP} (Trigger: {self.stoplossLTP + 0.05})")
                        try:
                            _, self.daily_total_MTM, __ = self.calculate_position_mtm()
                            log_message(f"[STOPLOSS] Broker MTM updated after placing stoploss: ₹{self.daily_total_MTM:.2f}")
                        except Exception:
                            pass
                        QTimer.singleShot(2000, lambda: self._log_stoploss_placed(self.stoplossLTP))
                    else:
                        log_message(f"[STOPLOSS] No order numbers received when replacing stoploss for {self.common_symbol}; results: {results}")

            self.SL_order_flag = True
            self.Target_order_flag = False
            self.Target_order_flag = True
            if not hasattr(self, 'target_info'):
                self.target_info = {}
            self.target_info['target_set'] = False

            if not hasattr(self, 'stoploss_info'):
                self.stoploss_info = {}
            self.stoploss_info['target_set'] = False
            
            # Store stoploss info for confirmation only; do not update tracked lots until confirmation in REAL mode
            self.stoploss_info = {
                'is_partial': is_partial_stoploss,
                'exit_lots': exit_lots,
                'remaining_lots': remaining_lots,
                'stoploss_set': True
            }

        except Exception as e:
            log_message(f"[ERROR] set_stoploss: {e}")
        finally:
            try:
                self.set_button_busy(self.stoploss_button, False, "&Stoploss")
            except Exception:
                pass

    def _log_stoploss_placed(self, stoplossLTP):
        """Log stoploss placement after delay"""
        if self.common_orderID:
            log_message(f"Stoploss placed for {self.common_symbol} @ {stoplossLTP}")
            self.order_label.setStyleSheet("color: blue")
    
    def calculate_target_price(self, entry_price: float, input_value: str) -> float:
        """
        Calculate target price based on input format.
        If input contains '%', treat as percentage gain. Otherwise, treat as absolute price.
        Args:
            entry_price: Entry price of the position
            input_value: User input (e.g., "25100" or "5%" or "5.5%")
        Returns:
            Target price as float
        """
        try:
            input_value = input_value.strip()
            if '%' in input_value:
                # Remove '%' and convert to float
                percent_str = input_value.replace('%', '').strip()
                pct = float(percent_str)
                # Calculate: entry_price * (1 + pct/100)
                return entry_price * (1.0 + pct / 100.0)
            else:
                # Absolute price
                return float(input_value)
        except Exception as e:
            log_message(f"[ERROR] calculate_target_price: {e}")
            return 0.0

    def calculate_stoploss_price(self, entry_price: float, input_value: str) -> float:
        """
        Calculate stoploss price based on input format.
        If input contains '%', treat as percentage loss. Otherwise, treat as absolute price.
        Args:            
            : Entry price of the position
            input_value: User input (e.g., "25000" or "3%" or "2.5%")
        Returns:
            Stoploss price as float
        """
        try:
            input_value = input_value.strip()
            if '%' in input_value:
                # Remove '%' and convert to float
                percent_str = input_value.replace('%', '').strip()
                pct = float(percent_str)
                # Calculate: entry_price * (1 - pct/100)
                return entry_price * (1.0 - pct / 100.0)
            else:
                # Absolute price
                return float(input_value)
        except Exception as e:
            log_message(f"[ERROR] calculate_stoploss_price: {e}")
            return 0.0
        
    #++++++++++++ main loop +++++++++++++++++
    def check_one_hour_rule(self):
        """Check 1-hour rule for PE and CE trades"""
        now = datetime.datetime.now()
        time_1430 = datetime.time(14, 30)

        # Check if current time has passed 14:30
        after_1430 = now.time() >= time_1430

        try:
            if self.oneHourRule_checkbox.isChecked():
                if self.PE_order_time is not None and self.PE_order_flag and hasattr(self, 'PE_order_time'):# and self.oneHourRule_checkbox.isChecked():
                    if (datetime.datetime.now() - self.PE_order_time) > datetime.timedelta(hours=1):
                        self.oneHourRule_checkbox.setChecked(False)
                        if self.intc_value <= self.T1Level:
                            log_message(f"PE T1-Level target hit in time: {self.intc_value} >= {self.T1Level}")
                        else:
                            log_message(f"PE T1-Level NOT reached in 1 hour. Exiting PE.")
                            self._squareOff_handler()

                if self.CE_order_time is not None and self.CE_order_flag and hasattr(self, 'CE_order_time'):# and self.oneHourRule_checkbox.isChecked():
                    if (datetime.datetime.now() - self.CE_order_time) > datetime.timedelta(hours=1):
                        self.oneHourRule_checkbox.setChecked(False)
                        if self.intc_value >= self.T1Level:
                            log_message(f"CE T1-Level target hit in time: {self.intc_value} <= {self.T1Level}")
                        else:
                            log_message(f"CE T1-Level NOT reached in 1 hour. Exiting CE.")
                            self._squareOff_handler()
            if after_1430:
                self.TSL_checkbox.setChecked(True)

        except Exception as e:
            log_message(f"[ERROR] check_one_hour_rule: {e}")

    def check_auto_logout_login(self):
        """Check for auto logout and login - UPDATED with cache cleanup"""
        try:
            now = QTime.currentTime()
            
            if not self.logout_flag and now.msecsSinceStartOfDay() > Config.MARKET_CLOSE.msecsSinceStartOfDay():
                self.logout_flag = True
                self.login_flag = False
                
                # ✅ ADD: Clear all caches at market close
                log_message("[CACHE] Clearing all caches at market close")
                self.data_cache.clear()
                if hasattr(self, 'signal_generator') and hasattr(self.signal_generator, '_oc_cache_store'):
                    self.signal_generator._oc_cache_store.clear()
                
                # Reset state
                self.current_direction = None
                self.reversal_gann_level = None
                self.last_gann_broken = None
                self.last_price = None
                self.reversal_initialized = False
                self.zone = None
                self.final_signal = "Wait"
                self.reset_all()

                self.logout_all()
                self.login_button.setText("Logout Successful")
                self.login_button.setStyleSheet("color: Red; font-weight: bold")
                self.run_summary()

            elif not self.login_flag and Config.LOGOUT_TIME.msecsSinceStartOfDay() > now.msecsSinceStartOfDay() > Config.LOGIN_TIME.msecsSinceStartOfDay():
                self.login_flag = True
                msecs_until = max(0, now.msecsTo(Config.LOGIN_TIME))
                if msecs_until > 0:
                    QTimer.singleShot(msecs_until, self.execute_login_at_9am)
                else:
                    self.execute_login_at_9am()
                    
        except Exception as e:
            log_message(f"[ERROR] check_auto_logout_login: {e}")

    def on_intc_value_fetched(self, intc_value):
        """Process intc value updates - SPLIT INTO SMALLER NON-BLOCKING PARTS"""
        try:
            # Initialize previous values if not present
            if not hasattr(self, "intc_value"):
                self.intc_value = intc_value
            # Determine color based on change
            if intc_value > self.intc_value:
                self.color_intc = "green"
            elif intc_value < self.intc_value:
                self.color_intc = "red"

            # Update stored values
            self.intc_value = intc_value
            
            # Update GUI with HTML styling
            self.currNifty.setText(
                f'Nifty: '
                f'<span style="color:{self.color_intc}">{intc_value}</span>'
            )
            self.signal_thread.core_intc_signal.emit(int(self.intc_value))
            
            now = QTime.currentTime().msecsSinceStartOfDay()
            
            if not (now < QTime(9, 16, 5).msecsSinceStartOfDay()):
                if now > QTime(9, 16).msecsSinceStartOfDay() and not self.reversal_initialized:
                    # ✅ Use QTimer to prevent blocking
                    QTimer.singleShot(0, self.initialize_reversal)
                
                # ✅ Schedule candle evaluation asynchronously
                curr_dt = QDateTime.currentDateTime().toPyDateTime().replace(second=0, microsecond=0)
                if self.last_candle_time is None or curr_dt > self.last_candle_time:
                    QTimer.singleShot(0, lambda: self.evaluate_current_candle(curr_dt))
            
            # ✅ Continue with rest of logic
            QTimer.singleShot(0, self.process_trading_signals)
            
        except Exception as e:
            log_message(f"[ERROR] on_intc_value_fetched: {e}")

    def process_trading_signals(self):
        """Process all trading signals - MAIN TRADING LOGIC"""
        try:
            # Zone identification
            if self.reversal_gann_level is not None and self.intc_value is not None:
                if self.intc_value > self.reversal_gann_level and self.zone is None:
                    log_message("Above Reversal Gann - Bullish Zone")
                    self.rev_label.setText(f"Reversal Level:- {self.reversal_gann_level} 🟢, ")
                    self.zone = "Bullish"
                elif self.intc_value < self.reversal_gann_level and self.zone is None:
                    log_message("Below Reversal Gann - Bearish Zone")
                    self.rev_label.setText(f"Reversal Level:- {self.reversal_gann_level} 🔴, ")
                    self.zone = "Bearish"

            if self.RSI_autoTrade_checkbox.isChecked():
                self.Action_plan()
                # Check 1-hour rule
                self.check_one_hour_rule()
                # Update LTP and PnL
                self.update_live_prices()
                # Auto logout/login
                self.check_auto_logout_login()
                return

            elif self.autoTrade_checkbox.isChecked():
                # Auto-trade signals
                # Allow initial entry OR add-on entry for same side when AutoTrade enabled.
                if (self.final_signal == "Buy CE" and self.zone == "Bullish" and self.CE_order_flag == False):
                    self.CE_buy()
                elif (self.final_signal == "Buy PE" and self.zone == "Bearish" and self.PE_order_flag == False):
                    self.PE_buy()
                # Trailing stop loss logic
                self.check_trailing_stop_loss(self.reversal_gann_level)

            self.Action_plan()      # here it just show RSI values and decision without auto trade (RSI)
            # Check 1-hour rule
            self.check_one_hour_rule()
            # Update LTP and PnL
            self.update_live_prices()
            # Auto logout/login
            self.check_auto_logout_login()
            
        except Exception as e:
            log_message(f"[ERROR] process_trading_signals: {e}")

    def check_trailing_stop_loss(self, reversal_gann_level):
        """Check and execute trailing stop loss"""
        try:
            if self.TSL_checkbox.isChecked():
                if self.PE_order_flag:# and self.TSL_checkbox.isChecked():
                    if float(self.intc_value) > int(reversal_gann_level):
                        log_message(f"TSL - square off PE MM trade as Gann Reversal level {reversal_gann_level} is reached.")
                        self._squareOff_handler()
                        self.TSL_checkbox.setChecked(False) 

                if self.CE_order_flag: # and self.TSL_checkbox.isChecked():
                    if float(self.intc_value) < int(reversal_gann_level):
                        log_message(f"TSL - square off CE MM trade as Gann reversal level {reversal_gann_level} is reached.")
                        self._squareOff_handler()
                        self.TSL_checkbox.setChecked(False)

            if not self.TSL_checkbox.isChecked():
                if self.PE_order_flag:# and not self.TSL_checkbox.isChecked():
                    self.bigProfit_flag = True
                    if float(self.intc_value) > int(reversal_gann_level):
                        log_message(f"NonTSL - square off PE MIS trade as Gann Reversal level {reversal_gann_level} is reached.")
                        self._squareOff_handler()
                        self.bigProfit_flag = False

                    if float(self.intc_value) < float(self.T1Level) and self.bigProfit_flag:
                        log_message(f"NonTSL - square off half {self.common_symbol} MM trade as T1 level {self.T1Level} is reached.")
                        # compute remaining qty/lots using integer math and update tracking first
                        remaining_netQty = int(self.netQty) // 2
                        remaining_lots = remaining_netQty // int(self.lot_size)
                        self.half_order_handle(remaining_lots)
                        self.PE_order_flag = False
                        self.autoTrade_checkbox.setChecked(False)
                        
                if self.CE_order_flag:# and not self.TSL_checkbox.isChecked():
                    self.bigProfit_flag = True
                    if float(self.intc_value) < int(reversal_gann_level):
                        log_message(f"nonTSL - square off CE MIS trade as Gann Reversal level {self.reversal_gann_level} is reached.")
                        self._squareOff_handler()
                        self.bigProfit_flag = False

                    if float(self.intc_value) > float(self.T1Level) and self.bigProfit_flag:
                        log_message(f"NonTSL - square off half {self.common_symbol} MM trade as T1 level {self.T1Level} is reached.")
                        remaining_netQty = int(self.netQty) // 2
                        remaining_lots = remaining_netQty // int(self.lot_size)
                        self.half_order_handle(remaining_lots)
                        self.CE_order_flag = False
                        self.autoTrade_checkbox.setChecked(False)
        except Exception as e:
            log_message(f"[ERROR] check_trailing_stop_loss: {e}")

    def _verify_and_update_position_after_fill(self, is_partial, exit_lots, remaining_lots, exit_type):
        """
        ✅ CONSISTENCY FIX: Verify broker position in REAL mode before updating position_lots
        - Paper mode: Update immediately (simulated fill)
        - Real mode: Verify with broker API before updating
        Args:
            is_partial: Boolean - is this a partial exit?
            exit_lots: Number of lots being exited
            remaining_lots: Number of lots remaining after exit
            exit_type: 'target' or 'stoploss' for logging
        """
        if self.PaperTrade_checkbox.isChecked():
            # Paper mode: immediate update (fill is simulated)
            self.set_position_lots(remaining_lots)
            if remaining_lots == 0:
                # Clear avg when completely exited
                self.common_avgLTP = 0.0
            log_message(f"[PAPER MODE] {exit_type.upper()} filled - position updated: {remaining_lots} lots")
            return

        # Real mode: Verify position with broker before updating
        log_message(f"[REAL MODE] Verifying {exit_type} fill with broker...")
        max_retries = 5
        retry_count = {'n': 0}
        start_time = time.time()
        timeout_secs = 5

        def check_position():
            retry_count['n'] += 1
            elapsed = time.time() - start_time

            def on_positions(positions):
                try:
                    current_qty = 0
                    if positions:
                        for pos in positions:
                            if pos.get('tsym') == self.common_symbol:
                                current_qty = abs(int(pos.get('netqty', 0)))
                                break

                    expected_qty = remaining_lots * self.lot_size
                    if current_qty == expected_qty:
                        log_message(f"[{exit_type.upper()} CONFIRMED] Broker position verified: {remaining_lots} lots")
                        self.set_position_lots(remaining_lots)
                        if remaining_lots == 0:
                            # Fully closed -> clear avg so next buy starts fresh
                            self.common_avgLTP = 0.0
                        return

                    # Timeout or max retries: proceed anyway with warning
                    if elapsed > timeout_secs or retry_count['n'] >= max_retries:
                        log_message(f"[{exit_type.upper()}] ⚠️ Broker verification timeout/max retries - proceeding anyway")
                        self.set_position_lots(remaining_lots)
                        if remaining_lots == 0:
                            self.common_avgLTP = 0.0
                        return

                    # Retry
                    log_message(f"[{exit_type.upper()} CHECK] Verifying... ({retry_count['n']}/{max_retries}, {elapsed:.1f}s)")
                    QTimer.singleShot(500, check_position)

                except Exception as e:
                    log_message(f"[ERROR] {exit_type} position check failed: {e}")
                    self.set_position_lots(remaining_lots)

            def on_error(err):
                log_message(f"[ERROR] {exit_type} API call: {err}")
                elapsed = time.time() - start_time
                if elapsed > timeout_secs or retry_count['n'] >= max_retries:
                    self.set_position_lots(remaining_lots)
                else:
                    QTimer.singleShot(500, check_position)

            # Use APIWorker to fetch positions from broker (non-blocking)
            worker = APIWorker(self.api_master.get_positions)
            worker.signals.result.connect(on_positions)
            worker.signals.error.connect(on_error)
            self.api_threadpool.start(worker)

        QTimer.singleShot(500, check_position)

    def update_live_prices(self):
        """Update live LTP and PnL - NON-BLOCKING"""
        #print(f"live lots - {self.position_lots}")
        try:
            if Config.NSE_error:
                self.refresh_nse_button.setStyleSheet("background-color: red; font-weight: bold")
                self.refresh_nse()
            else:
                self.refresh_nse_button.setStyleSheet("")
                
            if not self.ltp_ready:
                return
            if not self.ui_throttler.should_update('live_prices'):
                return
            self.currentLTP()

            if self.common_token is not None: 
                # order is placed and token is available.
                # self.targetLTP is set when option is bought.
                # compare current LTP with target price if it hit, and also calculate PnL for display.
                # LIMIT orders may or may not be placed at this point at broker.
                # If it is not placed self.target_info['target_set'] == False, then place it first.
                try:
                    if float(self.common_currLTP) >= float(self.targetLTP):
                        self.order_label.setStyleSheet("color: Purple")
                        if self.target_info['target_set'] == False:
                            self.set_target()
                        is_partial = self.target_info['is_partial']
                        exit_lots = self.target_info['exit_lots']
                        remaining_lots = self.target_info['remaining_lots']
                        log_message(f"[Before Half Exit] Set Target price {self.targetLTP} is achieved.")       
                        self.order_label.setText("MIS Trade - Set target achieved.")
                        if Config.manual_override:
                            self.reset_button.setEnabled(True)
                        PnL = round((int(self.common_currLTP) - float(self.common_avgLTP)) * int(exit_lots * self.lot_size), 2)
                        PnlPer = round((((self.common_currLTP - self.common_avgLTP) / self.common_avgLTP) * 100), 2)
                        log_message(f'  Exiting: {exit_lots} lots @ {self.common_currLTP}, Avg: {self.common_avgLTP}')
                        log_message(f'  P&L: ₹{PnL} ({PnlPer}%)')
                        if is_partial:
                            self.targetLTP += 40
                            self.target_entry.setText(str(self.targetLTP))
                            # ✅ Verify real mode position before updating
                            self._verify_and_update_position_after_fill(is_partial, exit_lots, remaining_lots, 'target')
                            self.target_info['target_set'] = False
                            self.target_info['is_partial'] = False  # reset partial target flag after partial target hit
                        else:
                            self.reset_all()
                            return
                        self.rpnl, self.Total_mtm, __ = self.calculate_position_mtm()
                except Exception:
                    log_message("[WARN] target comparison failed in MIS branch")              

            # stoplossLTP is set when option is bought and if T1Level is reached or half_order_handle executed due to 
            # partial exit orders, or when stoploss is placed/updated manually.
            # SL orders are already available at broker in such cases, so just compare current LTP with stoploss price, and if hit, then execute exit based on SL order details (partial or full).
            if getattr(self, 'stoplossLTP', None) is not None and self.SL_order_flag and self.common_token is not None:
                try:
                    if float(self.common_currLTP) <= float(self.stoplossLTP) and self.stoploss_info['stoploss_set']:
                        self.order_label.setStyleSheet("color: Yellow")
                        is_partial = self.stoploss_info['is_partial']
                        exit_lots = self.stoploss_info['exit_lots']
                        remaining_lots = self.stoploss_info['remaining_lots'] 
                        log_message(f"[Before Half Exit] Stoploss @ {self.stoplossLTP} is hit.")
                        self.order_label.setText("MIS Trade - Stoploss Hit.")
                        if Config.manual_override:
                            self.reset_button.setEnabled(True)
                        PnL = round((int(self.common_currLTP) - float(self.common_avgLTP)) * int(exit_lots * self.lot_size), 2)
                        PnlPer = round((((self.common_currLTP - self.common_avgLTP) / self.common_avgLTP) * 100), 2)
                        log_message(f'  Exiting: {exit_lots} lots @ {self.common_currLTP}, Avg: {self.common_avgLTP}')
                        log_message(f'  P&L: ₹{PnL} ({PnlPer}%)')
                        if is_partial:
                            self.SL_order_flag = False  # reset SL order flag to prevent multiple triggers until next SL is set
                            # ✅ Verify real mode position before updating
                            self._verify_and_update_position_after_fill(is_partial, exit_lots, remaining_lots, 'stoploss')
                            self.stoploss_info['is_partial'] = False  # reset partial stoploss flag after partial stoploss hit
                        else:
                            self.reset_all()
                            return
                        self.rpnl, self.Total_mtm, __ = self.calculate_position_mtm()
                except Exception:
                    log_message("[WARN] stoploss comparison failed in MIS branch")

            # Track PnL for MIS trade if token is available.
            if self.common_token is not None:
                if self.common_avgLTP != 0:
                    self.PnL = round((self.common_currLTP - float(self.common_avgLTP)) * int(self.position_lots * self.lot_size), 2)
                    self.PnlPer = round((((self.common_currLTP - self.common_avgLTP) / self.common_avgLTP) * 100), 2)
                daily_mtm = getattr(self, 'Total_mtm', None)
                if daily_mtm is None:
                    daily_mtm = self.PnL
                else:
                    daily_mtm = self.PnL + self.Total_mtm
                mtm_display = f" | Day MTM: ₹{daily_mtm:.2f}"
                self.order_label.setText(f"# {self.common_symbol}, lots = {self.position_lots} @ {self.common_avgLTP:,.2f}, Current = {self.common_currLTP}, PnL = {self.PnL} ({self.PnlPer}%){mtm_display}")

            # CNC Trade- PnL tracking
            if self.Deli_common_token is not None:
                if self.Deli_common_avgLTP != 0:
                    self.PnL2 = round((self.Deli_common_currLTP - float(self.Deli_common_avgLTP)) * int(self.Deli_netQty), 2)
                    self.PnlPer_Deli = round((((self.Deli_common_currLTP - self.Deli_common_avgLTP) / self.Deli_common_avgLTP) * 100), 2)
                self.Deli_order_label.setText(f"CNC Trade - {self.Deli_common_symbol}, netQty = {self.Deli_netQty} @ {self.Deli_common_avgLTP}, Current = {self.Deli_common_currLTP}, PnL = {self.PnL2} ({self.PnlPer_Deli}%)")

            now = QTime.currentTime()
            if now.msecsSinceStartOfDay() > Config.AUTO_SQUARE_OFF.msecsSinceStartOfDay() and self.autoSquareOff_checkbox.isChecked():
                self.autoSquareOff_checkbox.setChecked(False)
                log_message("Auto Square-Off time reached. Exiting MIS trades.")
                self.CE_PE_exit()
        except Exception as e:
            log_message(f"[ERROR] update_live_prices: {e}")

    #+++++++++++++++++++ PE buy Handling +++++++++++++
    def PE_buy_manual(self):
        log_message("PE Buy button pressed - manual entry")
        self.PE_buy()
         
    def PE_buy(self):
        """Handle PE buy button click"""
        try:
            # Refresh broker position state (REAL mode) before deciding add-on
            if not self.PaperTrade_checkbox.isChecked() and (self.PE_buy_flag or self.CE_buy_flag):
                sym = getattr(self, 'common_symbol', None)
                if sym:
                    self._reconcile_position_with_broker(sym)

            # Check if this is an add-on trade (valid open position exists)
            is_addon_trade = self._is_addon_trade("PE")
            if not is_addon_trade and (self.PE_buy_flag or self.CE_buy_flag) and int(getattr(self, "position_lots", 0)) == 0:
                self._clear_mis_state("No open lots for add-on PE")
            
            if not is_addon_trade and not self.RSI_autoTrade_checkbox.isChecked():
                # Original trade validations
                if self.reversal_gann_level is None:
                    self.order_label.setText(f"Reversal level is not set. Let software detect it or override it manually.")
                    self.order_label.setStyleSheet("color: Red")
                    self._clear_entry_data()
                    return
                elif self.zone == "Bullish":
                    self.order_label.setText(f"Market is in bullish zone, need to override it manually.")
                    self.order_label.setStyleSheet("color: Red")
                    self._clear_entry_data()
                    return
                else:
                    # validation passed; clear any prior text so new order updates cleanly
                    self.order_label.setStyleSheet("color: Black")
                    self.order_label.setText("MIS Trade -")
            
            self.set_button_busy(self.MY_PE_buy_button, True, "Placing PE...")
            self.reset_button.setEnabled(True)
            log_message(f"PE Buy button pressed. {'[ADD-ON TRADE]' if is_addon_trade else '[NEW TRADE]'}")
            self.CE_buy_flag = False
            self.MY_CE_buy_button.setEnabled(False)
            self.MY_PE_buy_button.setEnabled(True)
            self.target_button.setEnabled(True)
            self.stoploss_button.setEnabled(True)
            
            if is_addon_trade:
                # Add-on trade: use existing symbol
                self.PEBUY_ADDON()
                self.order_label.setStyleSheet("color: Blue")
                self.Deli_order_label.setText(f"Add-on Order Placed - {self.common_symbol}, Adding {self.position_lots} lots.")
            else:
                # New trade
                self.PEBUY()
                self.order_label.setStyleSheet("color: Blue")
                self.order_label.setText(f"MIS Order Placed - {self.common_symbol}, Qty= {self.netQty} (Waiting for fill...)")

        except Exception as e:
            log_message(f"[ERROR] PE_buy: {e}")

    def PEBUY_ADDON(self):
        """Execute PE add-on buy order - uses existing symbol"""
        try:
            if not self._is_addon_trade("PE"):
                log_message("[ADD-ON] No active PE position found; placing new trade instead.")
                self.PEBUY()
                return
            if not hasattr(self, 'common_symbol') or not self.common_symbol:
                log_message("[ERROR] No existing position found for add-on trade")
                return
            
            # Store previous position details
            self.prev_position_lots = self.position_lots if hasattr(self, 'position_lots') else 0
            self.prev_netQty = self.netQty if hasattr(self, 'netQty') else 0
            self.prev_avgLTP = self.common_avgLTP if hasattr(self, 'common_avgLTP') else 0
            
            # Calculate new position size (lots to add)
            addon_lots = int(self.lot_number.currentText())
            
            # ✅ Validate and adjust add-on lot size based on capital risk
            entry_price = self.entry_price.text() if self.entry_price is not None else ""
            if entry_price != '':
                entry_price = float(entry_price)
                entry_price = self.round_to_tick(entry_price)
            else:
                # Use current LTP if no entry price specified
                entry_price = float(self.common_currLTP) if hasattr(self, 'common_currLTP') and self.common_currLTP else 0
            
            if entry_price > 0:
                addon_lots = self.validate_and_adjust_lot_size_by_capital(entry_price, addon_lots)
            
            addon_qty = addon_lots * self.lot_size
            
            log_message(f"[ADD-ON] Existing: {self.prev_position_lots} lots @ {self.prev_avgLTP}")
            log_message(f"[ADD-ON] Adding: {addon_lots} lots to {self.common_symbol}")
            
            # Place add-on order
            addon_orderno = None
            
            if entry_price != '':
                entry_price = float(entry_price)
                entry_price = self.round_to_tick(entry_price)
                if self.PaperTrade_checkbox.isChecked():
                    log_message(f"[PAPER MODE] Add-on PE buy order for {self.common_symbol} @ LMT {entry_price}")
                else:
                    log_message(f"Add-on PE buy order for {self.common_symbol} @ LMT {entry_price}")
                    res = self.place_and_confirm('B', 'M', 'NFO', self.common_symbol, addon_qty, 'LMT', entry_price, timeout=30)
                    fills = res.get('fills', {})
                    ordernos = res.get('ordernos', {})
                    # pick any orderno for active tracking
                    if ordernos:
                        self.active_order_id = list(ordernos.values())[0]
                    total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                    if total_filled <= 0:
                        log_message(f"[ORDER] ⚠️ Add-on PE order placed but no fills reported for {self.common_symbol}")
                        addon_orderno = None
                    else:
                        addon_orderno = self.active_order_id
            elif self.PaperTrade_checkbox.isChecked():
                log_message(f"[PAPER MODE] Add-on PE buy order for {self.common_symbol} @ MKT")
            else:
                res = self.place_and_confirm('B', 'M', 'NFO', self.common_symbol, addon_qty, 'MKT', 0, timeout=30)
                fills = res.get('fills', {})
                ordernos = res.get('ordernos', {})
                if ordernos:
                    self.active_order_id = list(ordernos.values())[0]
                total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                if total_filled <= 0:
                    log_message(f"[ORDER] ⚠️ Add-on PE order placed but no fills reported for {self.common_symbol}")
                    addon_orderno = None
                else:
                    addon_orderno = self.active_order_id

            # Track order
            if not self.PaperTrade_checkbox.isChecked():
                if addon_orderno:
                    self.active_order_side = "PE_ADDON"
                    self.active_order_symbol = self.common_symbol
                    # active_order_id already set from ordernos_map
                    self.waiting_for_fill = False
                else:
                    log_message(f"[ORDER] ⚠️ Add-on PE order placed but order number not found or not filled")

            # Schedule finalization (will branch to real/paper inside)
            QTimer.singleShot(1000, lambda: self._finalize_PE_addon())
            
        except Exception as e:
            log_message(f"[ERROR] PEBUY_ADDON: {e}")

    def PEBUY(self):
        PE_primary_orderno = None
        """Execute PE buy order - NON-BLOCKING VERSION"""
        try:
            self.PE_Deli_Buy_symbol = None
            PE_buy_symbol = None
            index_symbol = self.symbol_input.currentText()
            atmStrike, currentIndexLTP = self.findATM_strike(index_symbol, self.indexStrikeDiff)
            step = self.indexStrikeDiff
            lowerStrike = int(currentIndexLTP // step) * step
            upperStrike = lowerStrike + step            
            if atmStrike == 0 or currentIndexLTP == 0:
                return
            expiry = self.extract_expiry(self.expiry_input.currentText())

            if self.FirstOTM_checkbox.isChecked():
                FirstOTM = upperStrike
                PE_buy_symbol = f"NSE:{index_symbol}{expiry}{FirstOTM}PE"
            elif self.FirstITM_checkbox.isChecked():
                FirstITM = atmStrike - 100
                PE_buy_symbol = f"NSE:{index_symbol}{expiry}{FirstITM}PE"
            else:
                PE_buy_symbol = f"NSE:{index_symbol}{expiry}{atmStrike}PE"
            
            if self.ThirdOTM_checkbox.isChecked() and (self.FirstOTM_checkbox.isChecked() or self.FirstITM_checkbox.isChecked()):
                log_message("MM + Delivery trade.")
                thirdOTM = atmStrike + 300
                self.expiry_input.setCurrentIndex(1)
                expiry = self.extract_expiry(self.expiry_input.currentText())
                self.PE_Deli_Buy_symbol = f"{index_symbol}{expiry}P{thirdOTM}"
                self.PE_Deli_lot_number = int(int(self.lot_number.currentText())/2)
                self.expiry_input.setCurrentIndex(0)
                self.exitCNC_button.setEnabled(True)
            elif self.ThirdOTM_checkbox.isChecked():
                thirdOTM = atmStrike + 300
                self.expiry_input.setCurrentIndex(1)
                expiry = self.extract_expiry(self.expiry_input.currentText())
                CE_buy_symbol = f"{index_symbol}{expiry}C{thirdOTM}"
            
            # ✅ CRUCIAL FIX: Only override position_lots if NOT set by RSI auto-trade
            # RSI auto-trade logic sets position_lots based on quality score BEFORE calling CE_buy()
            # If position_lots is still default/unset from combo box, use it; otherwise preserve RSI value
            if not hasattr(self, 'position_lots') or self.position_lots == 0:
                self.position_lots = int(self.lot_number.currentText())
            
            # Place MIS order
            entry_price = self.entry_price.text() if self.entry_price is not None else ""
            
            if entry_price != '':
                entry_price = float(entry_price)
                entry_price = self.round_to_tick(entry_price)
                
                # ✅ Validate and adjust lot size based on capital risk
                self.position_lots = self.validate_and_adjust_lot_size_by_capital(entry_price, self.position_lots)
                
                self.netQty = self.position_lots * self.lot_size 
                self.common_symbol = PE_buy_symbol
                self.ThirdOTM_checkbox.setChecked(False)
                self.ThirdOTM_checkbox.setCheckable(False)
                
                if self.PaperTrade_checkbox.isChecked():
                    log_message(f"[PAPER MODE] Placing PE buy order for {self.common_symbol} @ LMT {entry_price}")
                else:
                    log_message(f"Placing PE buy order for {self.common_symbol} @ LMT {entry_price}")
                    res = self.place_and_confirm('B', 'M', 'NFO', self.common_symbol, self.netQty, 'LMT', entry_price, timeout=30)
                    fills = res.get('fills', {})
                    ordernos = res.get('ordernos', {})
                    if ordernos:
                        self.active_order_id = list(ordernos.values())[0]
                    total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                    if total_filled <= 0:
                        log_message(f"[ORDER] ⚠️ PE order placed but no fills reported for {self.common_symbol}")
                        PE_primary_orderno = None
                    else:
                        PE_primary_orderno = self.active_order_id
            
            elif self.PaperTrade_checkbox.isChecked():
                self.common_symbol = PE_buy_symbol
                self.active_order_side = "PE"
                self.active_order_symbol = self.common_symbol
                log_message(f"[PAPER MODE] Common symbol for PE paper trade: {PE_buy_symbol}")
                self.capital_sizing(self.position_lots)
                if self.position_lots < 1:
                    log_message("[INFO] Capital not sufficient for even 1 lot. Trade blocked.")
                    return  # STOP order placement
                self.netQty = self.position_lots * self.lot_size
            else:
                requested_lots= self.position_lots
                self.netQty = self.position_lots * self.lot_size 
                self.common_symbol = CE_buy_symbol
                self.ThirdOTM_checkbox.setChecked(False)
                self.ThirdOTM_checkbox.setCheckable(False)
                # ✅ For market orders, entry_price is 0; perform capital check by
                # fetching a recent LTP.  _finalize_currentLTP_for_captal_sizing is
                # asynchronous, so wait briefly for the value.  If LTP remains
                # unavailable we restrict to 1 lot as a safety precaution.
                try:
                    self.capital_sizing(requested_lots)  # This will trigger async LTP fetch
                    if self.position_lots < 1:
                        log_message("[INFO] Capital not sufficient for even 1 lot. Trade blocked.")
                        return  # STOP order placement
                    self.netQty = self.position_lots * self.lot_size
                except Exception as e:
                    log_message(f"[WARN] Could not validate lot size for market order: {e}")
                    self.position_lots = min(requested_lots, 1)
                    self.netQty = self.position_lots * self.lot_size

            if not self.PaperTrade_checkbox.isChecked():
                res = self.place_and_confirm('B', 'M', 'NFO', self.common_symbol, self.netQty, 'MKT', 0, timeout=30)
                fills = res.get('fills', {})
                ordernos = res.get('ordernos', {})
                if ordernos:
                    self.active_order_id = list(ordernos.values())[0]
                total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                if total_filled <= 0:
                    log_message(f"[ORDER] ⚠️ PE order placed but no fills reported for {self.common_symbol}")
                    PE_primary_orderno = None
                else:
                    PE_primary_orderno = self.active_order_id

                if PE_primary_orderno:
                    self.active_order_side = "PE"
                    self.active_order_symbol = self.common_symbol
                    self.waiting_for_fill = False
                else:
                    log_message(f"[ORDER] ⚠️ PE order placed but primary order number not found or not filled")

            QTimer.singleShot(1000, lambda: self._process_PE_buy_step2())
            
        except Exception as e:
            log_message(f"[ERROR] PEBUY: {e}")

    '''def PEBUY(self):
        PE_primary_orderno = None  # Ensure variable is always defined
        """Execute PE buy order - NON-BLOCKING VERSION"""
        try:
            self.PE_Deli_Buy_symbol = None
            PE_buy_symbol = None
            index_symbol = self.symbol_input.currentText()
            atmStrike, currentIndexLTP = self.findATM_strike(index_symbol, self.indexStrikeDiff)
            step = self.indexStrikeDiff
            lowerStrike = int(currentIndexLTP // step) * step
            upperStrike = lowerStrike + step
            
            if atmStrike == 0 or currentIndexLTP == 0:
                return
            
            expiry = self.extract_expiry(self.expiry_input.currentText())

            if self.FirstOTM_checkbox.isChecked():
                FirstOTM = lowerStrike
                PE_buy_symbol = f"{index_symbol}{expiry}{FirstOTM}PE"
            elif self.FirstITM_checkbox.isChecked():
                FirstITM = atmStrike + 100
                PE_buy_symbol = f"{index_symbol}{expiry}{FirstITM}PE"
            else:
                PE_buy_symbol = f"{index_symbol}{expiry}{atmStrike}PE"
            
            if self.ThirdOTM_checkbox.isChecked() and (self.FirstOTM_checkbox.isChecked() or self.FirstITM_checkbox.isChecked()):
                log_message("MM + Delivery trade.")
                thirdOTM = atmStrike + 300
                self.expiry_input.setCurrentIndex(1)
                expiry = self.extract_expiry(self.expiry_input.currentText())
                self.PE_Deli_Buy_symbol = f"{index_symbol}{expiry}P{thirdOTM}"
                self.PE_Deli_lot_number = int(int(self.lot_number.currentText())/2)
                self.expiry_input.setCurrentIndex(0)
                self.exitCNC_button.setEnabled(True)
            elif self.ThirdOTM_checkbox.isChecked():
                thirdOTM = atmStrike - 300
                self.expiry_input.setCurrentIndex(1)
                expiry = self.extract_expiry(self.expiry_input.currentText())
                PE_buy_symbol = f"{index_symbol}{expiry}P{thirdOTM}"
            # ✅ CRUCIAL FIX: Only override position_lots if NOT set by RSI auto-trade
            # RSI auto-trade logic sets position_lots based on quality score BEFORE calling PE_buy()
            # If position_lots is still default/unset from combo box, use it; otherwise preserve RSI value
            if not hasattr(self, 'position_lots') or self.position_lots == 0:
                self.position_lots = int(self.lot_number.currentText())
            
            # Place MIS order
            entry_price = self.entry_price.text() if self.entry_price is not None else ""

            if entry_price != '':
                entry_price = float(entry_price)
                entry_price = self.round_to_tick(entry_price)
                
                # ✅ Validate and adjust lot size based on capital risk
                self.position_lots = self.validate_and_adjust_lot_size_by_capital(entry_price, self.position_lots)
                
                self.netQty = self.position_lots * self.lot_size
                self.common_symbol = PE_buy_symbol
                self.ThirdOTM_checkbox.setChecked(False)
                self.ThirdOTM_checkbox.setCheckable(False)
                
                if self.PaperTrade_checkbox.isChecked():
                    log_message(f"[PAPER MODE] Placing PE buy order for {self.common_symbol} @ LMT {entry_price}")
                else:
                    log_message(f"Placing PE buy order for {self.common_symbol} @ LMT {entry_price}")
                    res = self.place_and_confirm('B', 'M', 'NFO', self.common_symbol, self.netQty, 'LMT', entry_price, timeout=30)
                    fills = res.get('fills', {})
                    ordernos = res.get('ordernos', {})
                    if ordernos:
                        # Snapshot latest buy ordernos/fills to fetch accurate tradebook avg
                        self._last_buy_ordernos = ordernos
                        self._last_buy_fills = fills
                    if ordernos:
                        # Snapshot latest buy ordernos/fills to fetch accurate tradebook avg
                        self._last_buy_ordernos = ordernos
                        self._last_buy_fills = fills
                    if ordernos:
                        self.active_order_id = list(ordernos.values())[0]
                    total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                    if total_filled <= 0:
                        log_message(f"[ORDER] ⚠️ PE order placed but no fills reported for {self.common_symbol}")
                        PE_primary_orderno = None
                    else:
                        PE_primary_orderno = self.active_order_id

            elif self.PaperTrade_checkbox.isChecked():
                self.common_symbol = PE_buy_symbol
                log_message(f"[PAPER MODE] Common symbol for PE paper trade: {PE_buy_symbol}")
            else:
                requested_lots = self.position_lots
                self.netQty = self.position_lots * self.lot_size
                self.common_symbol = PE_buy_symbol
                self.ThirdOTM_checkbox.setChecked(False)
                self.ThirdOTM_checkbox.setCheckable(False)
                # ✅ For market orders, entry_price is 0; perform capital check by
                # fetching a recent LTP.  _finalize_currentLTP_for_captal_sizing is
                # asynchronous, so wait briefly for the value.  If LTP remains
                # unavailable we restrict to 1 lot as a safety precaution.
                try:
                    self._finalize_currentLTP_for_captal_sizing()
                    start = time.time()
                    while time.time() - start < 2 and (not hasattr(self, 'common_currLTP') or self.common_currLTP <= 0):
                        time.sleep(0.05)
                    current_ltp = float(self.common_currLTP) if hasattr(self, 'common_currLTP') and self.common_currLTP else 0
                    if current_ltp <= 0:
                        log_message("[CAP_SIZING] Timeout waiting for LTP; defaulting to 1 lot")
                        log_message("[WARN] Current LTP unavailable for capital check; defaulting to 1 lot")
                        max_allowed_lots = 1
                    else:
                        max_allowed_lots = self.validate_and_adjust_lot_size_by_capital(current_ltp, self.position_lots)
                    self.position_lots = min(requested_lots, max_allowed_lots)
                    if self.position_lots < 1:
                        log_message("[INFO] Capital not sufficient for even 1 lot. Trade blocked.")
                        return  # STOP order placement
                    self.netQty = self.position_lots * self.lot_size
                except Exception as e:
                    log_message(f"[WARN] Could not validate lot size for market order: {e}")
                    self.position_lots = min(requested_lots, 1)
                    self.netQty = self.position_lots * self.lot_size
                
                res = self.place_and_confirm('B', 'M', 'NFO', self.common_symbol, self.netQty, 'MKT', 0, timeout=30)
                fills = res.get('fills', {})
                ordernos = res.get('ordernos', {})
                if ordernos:
                    # Snapshot latest buy ordernos/fills to fetch accurate tradebook avg
                    self._last_buy_ordernos = ordernos
                    self._last_buy_fills = fills
                if ordernos:
                    # Snapshot latest buy ordernos/fills to fetch accurate tradebook avg
                    self._last_buy_ordernos = ordernos
                    self._last_buy_fills = fills
                if ordernos:
                    self.active_order_id = list(ordernos.values())[0]
                total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                if total_filled <= 0:
                    log_message(f"[ORDER] ⚠️ PE order placed but no fills reported for {self.common_symbol}")
                    PE_primary_orderno = None
                else:
                    PE_primary_orderno = self.active_order_id

            if not self.PaperTrade_checkbox.isChecked():
                if PE_primary_orderno:
                    self.active_order_side = "PE"
                    self.active_order_symbol = self.common_symbol
                    self.waiting_for_fill = False
                else:
                    log_message(f"[ORDER] ⚠️ PE order placed but primary order number not found or not filled")

            QTimer.singleShot(1000, lambda: self._process_PE_buy_step2())
            
        except Exception as e:
            log_message(f"[ERROR] PEBUY: {e}")
    '''
    
    def _process_PE_buy_step2(self):
        """Step 2: Process delivery order if needed"""
        try:
            if self.PE_Deli_Buy_symbol is not None:
                self.Deli_netQty = self.lot_size * self.PE_Deli_lot_number
                self.ThirdOTM_checkbox.setChecked(False)
                if self.PaperTrade_checkbox.isChecked():
                    log_message(f"[PAPER MODE] Placing Delivery PE buy order for {self.PE_Deli_Buy_symbol} @ MKT")      
                else:
                    log_message(f"Placing Delivery PE buy order for {self.PE_Deli_Buy_symbol} @ MKT")
                    # Place delivery buy and confirm fills before treating as CNC
                    res = self.place_and_confirm('B', 'M', 'NFO', self.PE_Deli_Buy_symbol, self.lot_size * self.PE_Deli_lot_number, 'MKT', 0, timeout=30)
                    ordernos = res.get('ordernos', {})
                    if ordernos:
                        self.Deli_common_orderID = ordernos
                
                QTimer.singleShot(2000, lambda: self._finalize_PE_buy())
            else:
                self._finalize_PE_buy()
        except Exception as e:
            log_message(f"[ERROR] _process_PE_buy_step2: {e}")
    
    def _finalize_PE_buy(self):
        try:
            if self.PaperTrade_checkbox.isChecked():
                self.rpnl, self.Total_mtm, __ = self.calculate_position_mtm()
                self._finalize_PE_buy_paper()
            else:
                self._finalize_PE_buy_real()
        except Exception as e:
            log_message(f"[ERROR] _finalize_PE_buy: {e}")

    def _finalize_PE_addon(self):
        """Finalize PE add-on trade"""
        try:
            if self.PaperTrade_checkbox.isChecked():
                _, self.Total_mtm, __ = self.calculate_position_mtm()
                self._finalize_PE_addon_paper()
            else:
                self._finalize_PE_addon_real()
        except Exception as e:
            log_message(f"[ERROR] _finalize_PE_addon: {e}")

    def _finalize_PE_addon_real(self):
        """Finalize PE add-on trade - REAL MODE"""
        try:
            MAX_FINALIZE_RETRIES = Config.MAX_FINALIZE_RETRIES

            def on_total_avg_received(total_avg_ltp, attempt=0):
                if not total_avg_ltp or total_avg_ltp <= 0:
                    if attempt < MAX_FINALIZE_RETRIES:
                        log_message(f"[REAL] Add-on avg price not available yet, retry {attempt+1}/{MAX_FINALIZE_RETRIES}")
                        QTimer.singleShot(1000, lambda: self.find_buy_avgLTP(self.common_symbol, callback=lambda avg: on_total_avg_received(avg, attempt+1)))
                    else:
                        log_message("[REAL] Add-on avg price not available after retries")
                    return

                # Calculate new average price
                addon_lots = int(self.lot_number.currentText())
                # Broker netavgprc already represents the TOTAL blended average after add-on
                total_qty = 0
                try:
                    total_qty = int(self.symbol_qty_map.get(self.common_symbol, 0))
                except Exception:
                    total_qty = 0
                if total_qty <= 0:
                    new_total_lots = self.prev_position_lots + addon_lots
                    total_qty = new_total_lots * self.lot_size
                else:
                    new_total_lots = self.qty_to_lots(total_qty)

                self.common_avgLTP = round(float(total_avg_ltp), 2)
                self.PE_buy_avgltp = self.common_avgLTP
                self.position_lots = new_total_lots
                self.netQty = total_qty

                # Update UI
                if self.SL_order_flag:
                    self.order_label.setStyleSheet("color: Blue")
                else:
                    self.order_label.setStyleSheet("color: Green")   
                self.order_label.setText(
                        f"MIS Trade - {self.common_symbol}, Qty= {self.netQty} @ {self.common_avgLTP:.2f} (Add-on: +{addon_lots} lots)"
                    )

                self.set_button_busy(self.MY_PE_buy_button, False, "&PE Buy")
                
                # Update target based on new average
                self.targetLTP = self.round_to_tick(self.common_avgLTP * 2)
                self.target_entry.setText(str(self.targetLTP))

                log_message(f"[REAL] Add-on complete: {new_total_lots} lots @ {self.common_avgLTP:.2f} (broker avg; was {self.prev_position_lots} @ {self.prev_avgLTP})")

            self.find_buy_avgLTP(self.common_symbol, callback=lambda avg: on_total_avg_received(avg, 0))

        except Exception as e:
            log_message(f"[ERROR] _finalize_PE_addon_real: {e}")

    def _finalize_PE_addon_paper(self):
        """Finalize PE add-on trade - PAPER MODE"""
        try:
            def on_ltp_received(ltp):
                if not ltp or ltp <= 0:
                    log_message("[PAPER] LTP not available for add-on trade")
                    return

                addon_price = self.round_to_tick(float(ltp))
                addon_lots = int(self.lot_number.currentText())
                new_total_lots = self.prev_position_lots + addon_lots
                
                # Weighted average calculation
                old_value = self.prev_position_lots * self.prev_avgLTP
                new_value = addon_lots * addon_price
                
                self.common_avgLTP = (old_value + new_value) / new_total_lots
                self.PE_buy_avgltp = self.common_avgLTP
                self.position_lots = new_total_lots
                self.netQty = new_total_lots * self.lot_size

                # Update UI
                if self.SL_order_flag:
                    self.order_label.setStyleSheet("color: Blue")   
                else:
                    self.order_label.setStyleSheet("color: Green")
                self.order_label.setText(
                    f"[PAPER] MIS Trade - {self.common_symbol}, Qty= {self.netQty} @ {self.common_avgLTP:.2f} (Add-on: +{addon_lots} lots)"
                )

                self.set_button_busy(self.MY_PE_buy_button, False, "&PE Buy")
                
                # Update target
                self.targetLTP = self.round_to_tick(self.common_avgLTP * 2)
                self.target_entry.setText(str(self.targetLTP))

                log_message(f"[PAPER] Add-on complete: {new_total_lots} lots @ {self.common_avgLTP:.2f} (was {self.prev_position_lots} @ {self.prev_avgLTP})")

            self.GetLTP('NFO', self.common_token, callback=on_ltp_received)

        except Exception as e:
            log_message(f"[ERROR] _finalize_PE_addon_paper: {e}")

    def _finalize_PE_buy_real(self):
        """Finalize PE buy - REAL MODE (async safe)"""
        try:
            MAX_FINALIZE_RETRIES = Config.MAX_FINALIZE_RETRIES  
            ordernos_map = getattr(self, "_last_buy_ordernos", None)
            fills_map = getattr(self, "_last_buy_fills", None)
            prefer_tradebook = bool(ordernos_map)

            def _clear_last_buy_snapshot():
                self._last_buy_ordernos = None
                self._last_buy_fills = None

            def on_mis_avg_received(avg_ltp, attempt=0):
                if avg_ltp is None or avg_ltp < 0:
                    if attempt < MAX_FINALIZE_RETRIES:
                        log_message(f"[REAL] MIS avg price not available yet, retry {attempt+1}/{MAX_FINALIZE_RETRIES}")
                        QTimer.singleShot(1000, lambda: self.find_buy_avgLTP(self.common_symbol, callback=lambda avg: on_mis_avg_received(avg, attempt+1), ordernos_map=ordernos_map, fills_map=fills_map, prefer_tradebook=prefer_tradebook))
                    else:
                        log_message("[REAL] MIS avg price not available after retries")
                        # even without avg price we still need to update UI so manual orders don't appear stuck
                        self.common_avgLTP = getattr(self, 'common_avgLTP', 0) or 0
                        self._finalize_PE_real_mis_state()
                        if self.PE_Deli_Buy_symbol:
                            self._finalize_PE_real_delivery_leg()
                        _clear_last_buy_snapshot()
                    return
                if avg_ltp == 0:
                    # broker says no position – clear stored avg
                    self.common_avgLTP = 0.0
                    self._finalize_PE_real_mis_state()
                    if self.PE_Deli_Buy_symbol:
                        self._finalize_PE_real_delivery_leg()
                    _clear_last_buy_snapshot()
                    return

                self.common_avgLTP = avg_ltp
                self.PE_buy_avgltp = avg_ltp
                self.ltp_ready = False  # ✅ Set immediately before GetToken to block update_live_prices until new tokens ready

                def on_token(token):
                    self.common_token = token
                    self.prepare_tokens([self.common_symbol])

                self.GetToken('NFO', self.common_symbol, callback=on_token)

                self._finalize_PE_real_mis_state()

                if self.PE_Deli_Buy_symbol:
                    self._finalize_PE_real_delivery_leg()

                _clear_last_buy_snapshot()

            self.find_buy_avgLTP(self.common_symbol, callback=lambda avg: on_mis_avg_received(avg, 0), ordernos_map=ordernos_map, fills_map=fills_map, prefer_tradebook=prefer_tradebook)

        except Exception as e:
            log_message(f"[ERROR] _finalize_PE_buy_real: {e}")

    def _finalize_PE_real_mis_state(self):
        try:
            # Check if order was actually filled - if not, reset everything
            if not self.common_avgLTP or self.common_avgLTP <= 0 or not self.netQty or self.netQty <= 0:
                log_message(f"[REAL] MIS PE {self.common_symbol}, Qty= {self.netQty} @ {self.common_avgLTP} this means order is not successful so call reset_all")
                self.Deli_order_label.setStyleSheet("color: Red")
                self.Deli_order_label.setText(f"MIS PE {self.common_symbol} order failed or not filled")
                self.reset_all()
                return
            
            if self.SL_order_flag:
                self.order_label.setStyleSheet("color: Blue")   
            else:
                self.order_label.setStyleSheet("color: Green")
            # Always update label, even if repeated buy
            self.order_label.setText(f"MIS Trade - {self.common_symbol}, Qty= {self.netQty} @ {self.common_avgLTP}")

            self.PE_buy_flag = True
            self.PE_order_flag = True
            self.bigProfit_flag = True
            self.MIS_exit_button.setEnabled(True)
            self.reset_button.setEnabled(False)
            self.set_button_busy(self.MY_PE_buy_button, False, "&PE Buy")

            self.targetLTP = self.round_to_tick(self.common_avgLTP * 2)
            self.target_entry.setText(str(self.targetLTP))

            self.T1Level = self.intc_value - 40
            self.T1level_label.setText(f"T1 Level - {self.T1Level}")
            self.active_order_side = "PE" 
            self.entry_time = datetime.datetime.now()
            self.entry_rsi_5m = self.rsi_5min
            self.entry_rsi_30m = self.rsi_30min
            self.PE_order_time = datetime.datetime.now()

            log_message(f"[REAL] MIS PE {self.common_symbol}, Qty= {self.netQty} @ {self.common_avgLTP}")

            # Record underlying at entry and defer paper-mode auto SL to live monitoring
            try:
                self.entry_underlying_at_buy = float(self.intc_value)
                # CRITICAL: Store entry underlying to disk for recovery after crash
                order_time_str = datetime.datetime.now().strftime("%d%m%y%H%M%S")
                if self.common_symbol:
                    self._store_entry_underlying(self.common_symbol, self.entry_underlying_at_buy, order_time_str)
            except Exception:
                self.entry_underlying_at_buy = None
        except Exception as e:
            log_message(f"[ERROR] _finalize_PE_real_mis_state: {e}")
            # Force label update on error
            self.order_label.setStyleSheet("color: Red")
            self.order_label.setText("PE Buy: Error occurred, but state updated.")

    def _finalize_PE_real_delivery_leg(self):
        MAX_FINALIZE_RETRIES = Config.MAX_FINALIZE_RETRIES
        
        def on_deli_avg_received(avg_ltp, attempt=0):
            if not avg_ltp or avg_ltp <= 0:
                if attempt < MAX_FINALIZE_RETRIES:
                    log_message(f"[REAL] Delivery avg not ready yet, retry {attempt+1}/{MAX_FINALIZE_RETRIES}")
                    QTimer.singleShot(1000, lambda: self.find_buy_avgLTP(self.PE_Deli_Buy_symbol, callback=lambda avg: on_deli_avg_received(avg, attempt+1)))
                else:
                    log_message("[REAL] Delivery avg not ready after retries")
                return

            self.PE_Deli_buy_avgltp = avg_ltp
            self.Deli_netQty = self.lot_size * self.PE_Deli_lot_number

            def on_deli_token(token):
                self.Deli_common_token = token
                self.Deli_common_symbol = self.PE_Deli_Buy_symbol
                self.prepare_tokens([self.Deli_common_symbol])

            self.GetToken('NFO', self.PE_Deli_Buy_symbol, callback=on_deli_token)

            self.Deli_order_label.setText(f"CNC Trade - {self.PE_Deli_Buy_symbol}, Qty= {self.Deli_netQty} @ {avg_ltp}")
            log_message(f"[REAL] CNC PE {self.PE_Deli_Buy_symbol}, Qty= {self.Deli_netQty} @ {avg_ltp}")

        self.find_buy_avgLTP(self.PE_Deli_Buy_symbol, callback=lambda avg: on_deli_avg_received(avg,0))

    def _finalize_PE_buy_paper(self):
        """Finalize PE buy in PAPER MODE (async-safe)"""
        try:
            def on_token_received(token):
                if not token:
                    log_message("[PAPER] Token not found, aborting PE paper fill")
                    return

                self.common_token = token

                def on_ltp_received(ltp):
                    if not ltp or ltp <= 0:
                        log_message("[PAPER] LTP not available, aborting PE paper fill")
                        return

                    self.common_currLTP = ltp
                    self._complete_PE_paper_fill(ltp)   

                self.GetLTP('NFO', token, callback=on_ltp_received)

            self.GetToken('NFO', self.common_symbol, callback=on_token_received)

        except Exception as e:
            log_message(f"[ERROR] _finalize_PE_buy_paper: {e}")

    def _complete_PE_paper_fill(self, raw_price):
        """Complete paper PE fill after price is known"""
        try:
            fill_price = self.round_to_tick(float(raw_price))

            self.common_avgLTP = fill_price
            self.PE_buy_avgltp = fill_price
            self.PE_buy_flag = True
            self.PE_order_flag = True
            self.bigProfit_flag = True
            self.ltp_ready = False  # ✅ Set immediately before GetToken to block update_live_prices until tokens ready

            def on_token(token):
                self.common_token = token
                self.prepare_tokens([self.common_symbol])

            self.GetToken('NFO', self.common_symbol, callback=on_token)

            if self.SL_order_flag:
                self.order_label.setStyleSheet("color: Blue")
            else:
                self.order_label.setStyleSheet("color: Green")
            self.order_label.setText(
                f"[PAPER] MIS Trade - {self.common_symbol}, Qty= {self.netQty} @ {fill_price}"
            )

            self.MIS_exit_button.setEnabled(True)
            self.reset_button.setEnabled(False)
            self.set_button_busy(self.MY_PE_buy_button, False, "&PE Buy")

            self.targetLTP = self.round_to_tick(fill_price * 2)
            self.target_entry.setText(str(self.targetLTP))

            self.T1Level = self.intc_value - 40
            self.T1level_label.setText(f"T1 Level - {self.T1Level}")
            self.active_order_side = "PE"
            self.PE_order_time = datetime.datetime.now()
            self.entry_time = datetime.datetime.now()
            self.entry_rsi_5m = self.rsi_5min
            self.entry_rsi_30m = self.rsi_30min

            log_message(f"[PAPER] PE MIS Trade - {self.common_symbol}, Qty= {self.netQty} @ {fill_price}")
           # Record underlying at entry and defer paper-mode auto SL to live monitoring
            try:
                self.entry_underlying_at_buy = float(self.intc_value)
                # CRITICAL: Store entry underlying to disk for recovery after crash
                order_time_str = datetime.datetime.now().strftime("%d%m%y%H%M%S")
                if self.common_symbol:
                    self._store_entry_underlying(self.common_symbol, self.entry_underlying_at_buy, order_time_str)
            except Exception:
                self.entry_underlying_at_buy = None

        except Exception as e:
            log_message(f"[ERROR] _complete_PE_paper_fill: {e}")

#+++++++++ CE Buy Handling ++++++++++++++
    def CE_buy_manual(self):
        log_message("CE Buy button clicked - manual entry")
        self.CE_buy()

    def CE_buy(self):    
        """Handle CE buy button click"""
        try:
            # Refresh broker position state (REAL mode) before deciding add-on
            if not self.PaperTrade_checkbox.isChecked() and (self.PE_buy_flag or self.CE_buy_flag):
                sym = getattr(self, 'common_symbol', None)
                if sym:
                    self._reconcile_position_with_broker(sym)

            # Check if this is an add-on trade (valid open position exists)
            is_addon_trade = self._is_addon_trade("CE")
            if not is_addon_trade and (self.PE_buy_flag or self.CE_buy_flag) and int(getattr(self, "position_lots", 0)) == 0:
                self._clear_mis_state("No open lots for add-on CE")
            
            if not is_addon_trade and not self.RSI_autoTrade_checkbox.isChecked():
                # Original trade validations
                if self.reversal_gann_level is None:
                    self.order_label.setText(f"Reversal level is not set. Let software detect it or override it manually.")
                    self.order_label.setStyleSheet("color: Red")
                    self._clear_entry_data()
                    return
                elif self.zone == "Bearish":
                    self.order_label.setText(f"Market is in bearish zone, need to override it manually.")
                    self.order_label.setStyleSheet("color: Red")
                    self._clear_entry_data()
                    return
                else:
                    # validation passed; clear any prior text
                    self.order_label.setStyleSheet("color: Black")
                    self.order_label.setText("MIS Trade -")

            self.set_button_busy(self.MY_CE_buy_button, True, "Placing CE...")
            self.reset_button.setEnabled(True)
            log_message(f"CE Buy button pressed. {'[ADD-ON TRADE]' if is_addon_trade else '[NEW TRADE]'}")
            
            self.PE_buy_flag = False
            self.MY_PE_buy_button.setEnabled(False)
            self.MY_CE_buy_button.setEnabled(True)
            self.target_button.setEnabled(True)
            self.stoploss_button.setEnabled(True)

            if is_addon_trade:
                # Add-on trade: use existing symbol
                self.CEBUY_ADDON()
                self.order_label.setStyleSheet("color: Blue")
                self.Deli_order_label.setText(f"Add-on Order Placed - {self.common_symbol}, Adding {self.position_lots} lots.")
            else:
                # New trade
                self.CEBUY()
                self.order_label.setStyleSheet("color: Blue")
                self.order_label.setText(f"MIS Order Placed - {self.common_symbol}, Qty= {self.netQty} (Waiting for fill...)")

        except Exception as e:
            log_message(f"[ERROR] CE_buy: {e}")

    def CEBUY_ADDON(self):
        """Execute CE add-on buy order - uses existing symbol"""
        try:
            if not self._is_addon_trade("CE"):
                log_message("[ADD-ON] No active CE position found; placing new trade instead.")
                self.CEBUY()
                return
            if not hasattr(self, 'common_symbol') or not self.common_symbol:
                log_message("[ERROR] No existing position found for add-on trade")
                return
            
            # Store previous position details
            self.prev_position_lots = self.position_lots if hasattr(self, 'position_lots') else 0
            self.prev_netQty = self.netQty if hasattr(self, 'netQty') else 0
            self.prev_avgLTP = self.common_avgLTP if hasattr(self, 'common_avgLTP') else 0
            
            # Calculate new position size (lots to add)
            addon_lots = int(self.lot_number.currentText())
            
            # ✅ Validate and adjust add-on lot size based on capital risk
            entry_price = self.entry_price.text() if self.entry_price is not None else ""
            if entry_price != '':
                entry_price = float(entry_price)
                entry_price = self.round_to_tick(entry_price)
            else:
                # Use current LTP if no entry price specified
                entry_price = float(self.common_currLTP) if hasattr(self, 'common_currLTP') and self.common_currLTP else 0
            
            if entry_price > 0:
                addon_lots = self.validate_and_adjust_lot_size_by_capital(entry_price, addon_lots)
            
            addon_qty = addon_lots * self.lot_size
            
            log_message(f"[ADD-ON] Existing: {self.prev_position_lots} lots @ {self.prev_avgLTP}")
            log_message(f"[ADD-ON] Adding: {addon_lots} lots to {self.common_symbol}")
            
            # Place add-on order
            addon_orderno = None
            
            if entry_price != '':
                entry_price = float(entry_price)
                entry_price = self.round_to_tick(entry_price)
                if self.PaperTrade_checkbox.isChecked():
                    log_message(f"[PAPER MODE] Add-on CE buy order for {self.common_symbol} @ LMT {entry_price}")
                else:
                    log_message(f"Add-on CE buy order for {self.common_symbol} @ LMT {entry_price}")
                    res = self.place_and_confirm('B', 'M', 'NFO', self.common_symbol, addon_qty, 'LMT', entry_price, timeout=30)
                    fills = res.get('fills', {})
                    ordernos = res.get('ordernos', {})
                    if ordernos:
                        self.active_order_id = list(ordernos.values())[0]
                    total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                    if total_filled <= 0:
                        log_message(f"[ORDER] ⚠️ Add-on CE order placed but no fills reported for {self.common_symbol}")
                        addon_orderno = None
                    else:
                        addon_orderno = self.active_order_id
            elif self.PaperTrade_checkbox.isChecked():
                log_message(f"[PAPER MODE] Add-on CE buy order for {self.common_symbol} @ MKT")
            else:
                res = self.place_and_confirm('B', 'M', 'NFO', self.common_symbol, addon_qty, 'MKT', 0, timeout=30)
                fills = res.get('fills', {})
                ordernos = res.get('ordernos', {})
                if ordernos:
                    self.active_order_id = list(ordernos.values())[0]
                total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                if total_filled <= 0:
                    log_message(f"[ORDER] ⚠️ Add-on CE order placed but no fills reported for {self.common_symbol}")
                    addon_orderno = None
                else:
                    addon_orderno = self.active_order_id

            # Track order
            if not self.PaperTrade_checkbox.isChecked():
                if addon_orderno:
                    self.active_order_side = "CE_ADDON"
                    self.active_order_symbol = self.common_symbol
                    self.waiting_for_fill = False
                else:
                    log_message(f"[ORDER] ⚠️ Add-on CE order placed but order number not found or not filled")

            # Schedule finalization
            QTimer.singleShot(1000, lambda: self._finalize_CE_addon())
            
        except Exception as e:
            log_message(f"[ERROR] CEBUY_ADDON: {e}")

    def CEBUY(self):
        CE_primary_orderno = None
        """Execute CE buy order - NON-BLOCKING VERSION"""
        try:
            self.CE_Deli_Buy_symbol = None
            CE_buy_symbol = None
            index_symbol = self.symbol_input.currentText()
            atmStrike, currentIndexLTP = self.findATM_strike(index_symbol, self.indexStrikeDiff)
            step = self.indexStrikeDiff
            lowerStrike = int(currentIndexLTP // step) * step
            upperStrike = lowerStrike + step            
            if atmStrike == 0 or currentIndexLTP == 0:
                return
            expiry = self.extract_expiry(self.expiry_input.currentText())

            if self.FirstOTM_checkbox.isChecked():
                FirstOTM = upperStrike
                CE_buy_symbol = f"NSE:{index_symbol}{expiry}{FirstOTM}CE"
            elif self.FirstITM_checkbox.isChecked():
                FirstITM = atmStrike - 100
                CE_buy_symbol = f"NSE:{index_symbol}{expiry}{FirstITM}CE"
            else:
                CE_buy_symbol = f"NSE:{index_symbol}{expiry}{atmStrike}CE"
            
            if self.ThirdOTM_checkbox.isChecked() and (self.FirstOTM_checkbox.isChecked() or self.FirstITM_checkbox.isChecked()):
                log_message("MM + Delivery trade.")
                thirdOTM = atmStrike + 300
                self.expiry_input.setCurrentIndex(1)
                expiry = self.extract_expiry(self.expiry_input.currentText())
                self.CE_Deli_Buy_symbol = f"{index_symbol}{expiry}C{thirdOTM}"
                self.CE_Deli_lot_number = int(int(self.lot_number.currentText())/2)
                self.expiry_input.setCurrentIndex(0)
                self.exitCNC_button.setEnabled(True)
            elif self.ThirdOTM_checkbox.isChecked():
                thirdOTM = atmStrike + 300
                self.expiry_input.setCurrentIndex(1)
                expiry = self.extract_expiry(self.expiry_input.currentText())
                CE_buy_symbol = f"{index_symbol}{expiry}C{thirdOTM}"
            
            # ✅ CRUCIAL FIX: Only override position_lots if NOT set by RSI auto-trade
            # RSI auto-trade logic sets position_lots based on quality score BEFORE calling CE_buy()
            # If position_lots is still default/unset from combo box, use it; otherwise preserve RSI value
            if not hasattr(self, 'position_lots') or self.position_lots == 0:
                self.position_lots = int(self.lot_number.currentText())
            
            # Place MIS order
            entry_price = self.entry_price.text() if self.entry_price is not None else ""
            
            if entry_price != '':
                entry_price = float(entry_price)
                entry_price = self.round_to_tick(entry_price)
                
                # ✅ Validate and adjust lot size based on capital risk
                self.position_lots = self.validate_and_adjust_lot_size_by_capital(entry_price, self.position_lots)
                
                self.netQty = self.position_lots * self.lot_size 
                self.common_symbol = CE_buy_symbol
                self.ThirdOTM_checkbox.setChecked(False)
                self.ThirdOTM_checkbox.setCheckable(False)
                
                if self.PaperTrade_checkbox.isChecked():
                    log_message(f"[PAPER MODE] Placing CE buy order for {self.common_symbol} @ LMT {entry_price}")
                else:
                    log_message(f"Placing CE buy order for {self.common_symbol} @ LMT {entry_price}")
                    res = self.place_and_confirm('B', 'M', 'NFO', self.common_symbol, self.netQty, 'LMT', entry_price, timeout=30)
                    fills = res.get('fills', {})
                    ordernos = res.get('ordernos', {})
                    if ordernos:
                        self.active_order_id = list(ordernos.values())[0]
                    total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                    if total_filled <= 0:
                        log_message(f"[ORDER] ⚠️ CE order placed but no fills reported for {self.common_symbol}")
                        CE_primary_orderno = None
                    else:
                        CE_primary_orderno = self.active_order_id
            
            elif self.PaperTrade_checkbox.isChecked():
                self.common_symbol = CE_buy_symbol
                self.active_order_side = "CE"
                self.active_order_symbol = self.common_symbol
                log_message(f"[PAPER MODE] Common symbol for CE paper trade: {CE_buy_symbol}")
                self.capital_sizing(self.position_lots)
                if self.position_lots < 1:
                    log_message("[INFO] Capital not sufficient for even 1 lot. Trade blocked.")
                    return  # STOP order placement
                self.netQty = self.position_lots * self.lot_size
            else:
                requested_lots= self.position_lots
                self.netQty = self.position_lots * self.lot_size 
                self.common_symbol = CE_buy_symbol
                self.ThirdOTM_checkbox.setChecked(False)
                self.ThirdOTM_checkbox.setCheckable(False)
                # ✅ For market orders, entry_price is 0; perform capital check by
                # fetching a recent LTP.  _finalize_currentLTP_for_captal_sizing is
                # asynchronous, so wait briefly for the value.  If LTP remains
                # unavailable we restrict to 1 lot as a safety precaution.
                try:
                    self.capital_sizing(requested_lots)  # This will trigger async LTP fetch
                    if self.position_lots < 1:
                        log_message("[INFO] Capital not sufficient for even 1 lot. Trade blocked.")
                        return  # STOP order placement
                    self.netQty = self.position_lots * self.lot_size
                except Exception as e:
                    log_message(f"[WARN] Could not validate lot size for market order: {e}")
                    self.position_lots = min(requested_lots, 1)
                    self.netQty = self.position_lots * self.lot_size

            if not self.PaperTrade_checkbox.isChecked():
                res = self.place_and_confirm('B', 'M', 'NFO', self.common_symbol, self.netQty, 'MKT', 0, timeout=30)
                fills = res.get('fills', {})
                ordernos = res.get('ordernos', {})
                if ordernos:
                    self.active_order_id = list(ordernos.values())[0]
                total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                if total_filled <= 0:
                    log_message(f"[ORDER] ⚠️ CE order placed but no fills reported for {self.common_symbol}")
                    CE_primary_orderno = None
                else:
                    CE_primary_orderno = self.active_order_id

                if CE_primary_orderno:
                    self.active_order_side = "CE"
                    self.active_order_symbol = self.common_symbol
                    self.waiting_for_fill = False
                else:
                    log_message(f"[ORDER] ⚠️ CE order placed but primary order number not found or not filled")

            QTimer.singleShot(1000, lambda: self._process_CE_buy_step2())
            
        except Exception as e:
            log_message(f"[ERROR] CEBUY: {e}")

    def _process_CE_buy_step2(self):
        """Step 2: Process delivery order if needed"""
        try:
            if self.CE_Deli_Buy_symbol is not None:
                self.Deli_netQty = self.lot_size * self.CE_Deli_lot_number
                self.ThirdOTM_checkbox.setChecked(False)
                self.ThirdOTM_checkbox.setCheckable(False)
                if self.PaperTrade_checkbox.isChecked():
                    log_message(f"[PAPER MODE] Placing Delivery CE buy order for {self.CE_Deli_Buy_symbol} @ MKT")
                else:
                    log_message(f"Placing Delivery CE buy order for {self.CE_Deli_Buy_symbol} @ MKT")
                    res = self.place_and_confirm('B', 'M', 'NFO', self.CE_Deli_Buy_symbol, self.lot_size * self.CE_Deli_lot_number, 'MKT', 0, timeout=30)
                    ordernos = res.get('ordernos', {})
                    if ordernos:
                        self.Deli_common_orderID = ordernos
                
                QTimer.singleShot(2000, lambda: self._finalize_CE_buy())
            else:
                self._finalize_CE_buy()
        except Exception as e:
            log_message(f"[ERROR] _process_CE_buy_step2: {e}")

    def _finalize_CE_addon(self):
        """Finalize CE add-on trade"""
        try:
            if self.PaperTrade_checkbox.isChecked():
                _, self.Total_mtm, __ = self.calculate_position_mtm()
                self._finalize_CE_addon_paper()
            else:
                self._finalize_CE_addon_real()
        except Exception as e:
            log_message(f"[ERROR] _finalize_CE_addon: {e}")

    def _finalize_CE_addon_real(self):
        """Finalize CE add-on trade - REAL MODE"""
        try:
            MAX_FINALIZE_RETRIES = Config.MAX_FINALIZE_RETRIES

            def on_total_avg_received(total_avg_ltp, attempt=0):
                if not total_avg_ltp or total_avg_ltp <= 0:
                    if attempt < MAX_FINALIZE_RETRIES:
                        log_message(f"[REAL] Add-on avg price not available yet, retry {attempt+1}/{MAX_FINALIZE_RETRIES}")
                        QTimer.singleShot(1000, lambda: self.find_buy_avgLTP(self.common_symbol, callback=lambda avg: on_total_avg_received(avg, attempt+1)))
                    else:
                        log_message("[REAL] Add-on avg price not available after retries")
                    return

                # Calculate new average price
                addon_lots = int(self.lot_number.currentText())
                # Broker netavgprc already represents the TOTAL blended average after add-on
                total_qty = 0
                try:
                    total_qty = int(self.symbol_qty_map.get(self.common_symbol, 0))
                except Exception:
                    total_qty = 0
                if total_qty <= 0:
                    new_total_lots = self.prev_position_lots + addon_lots
                    total_qty = new_total_lots * self.lot_size
                else:
                    new_total_lots = self.qty_to_lots(total_qty)

                self.common_avgLTP = round(float(total_avg_ltp), 2)
                self.CE_buy_avgltp = self.common_avgLTP
                self.position_lots = new_total_lots
                self.netQty = total_qty

                # Update UI
                if self.SL_order_flag:
                    self.order_label.setStyleSheet("color: Blue")
                else:
                    self.order_label.setStyleSheet("color: Green")
                self.order_label.setText(
                    f"MIS Trade - {self.common_symbol}, Qty= {self.netQty} @ {self.common_avgLTP:.2f} (Add-on: +{addon_lots} lots)"
                )

                self.set_button_busy(self.MY_CE_buy_button, False, "&CE Buy")
                
                # Update target based on new average
                self.targetLTP = self.round_to_tick(self.common_avgLTP * 2)
                self.target_entry.setText(str(self.targetLTP))

                log_message(f"[REAL] Add-on complete: {new_total_lots} lots @ {self.common_avgLTP:.2f} (broker avg; was {self.prev_position_lots} @ {self.prev_avgLTP})")

            self.find_buy_avgLTP(self.common_symbol, callback=lambda avg: on_total_avg_received(avg, 0))

        except Exception as e:
            log_message(f"[ERROR] _finalize_CE_addon_real: {e}")

    def _finalize_CE_addon_paper(self):
        """Finalize CE add-on trade - PAPER MODE"""
        try:
            def on_ltp_received(ltp):
                if not ltp or ltp <= 0:
                    log_message("[PAPER] LTP not available for add-on trade")
                    return

                addon_price = self.round_to_tick(float(ltp))
                addon_lots = int(self.lot_number.currentText())
                new_total_lots = self.prev_position_lots + addon_lots
                
                # Weighted average calculation
                old_value = self.prev_position_lots * self.prev_avgLTP
                new_value = addon_lots * addon_price
                
                self.common_avgLTP = (old_value + new_value) / new_total_lots
                self.CE_buy_avgltp = self.common_avgLTP
                self.position_lots = new_total_lots
                self.netQty = new_total_lots * self.lot_size

                # Update UI
                if self.SL_order_flag:
                    self.order_label.setStyleSheet("color: Blue")
                else:
                    self.order_label.setStyleSheet("color: Green")
                self.order_label.setText(
                    f"[PAPER] MIS Trade - {self.common_symbol}, Qty= {self.netQty} @ {self.common_avgLTP:.2f} (Add-on: +{addon_lots} lots)"
                )

                self.set_button_busy(self.MY_CE_buy_button, False, "&CE Buy")
                
                # Update target
                self.targetLTP = self.round_to_tick(self.common_avgLTP * 2)
                self.target_entry.setText(str(self.targetLTP))

                log_message(f"[PAPER] Add-on complete: {new_total_lots} lots @ {self.common_avgLTP:.2f} (was {self.prev_position_lots} @ {self.prev_avgLTP})")

            self.GetLTP('NFO', self.common_token, callback=on_ltp_received)

        except Exception as e:
            log_message(f"[ERROR] _finalize_CE_addon_paper: {e}")

    def _finalize_CE_buy(self):
        try:
            if self.PaperTrade_checkbox.isChecked():
                _, self.Total_mtm, __ = self.calculate_position_mtm()
                self._finalize_CE_buy_paper()
            else:
                self._finalize_CE_buy_real()
        except Exception as e:
            log_message(f"[ERROR] _finalize_CE_buy: {e}")

    def _finalize_CE_buy_real(self):
        """Finalize CE buy - REAL MODE (async safe)"""
        try:
            MAX_FINALIZE_RETRIES = Config.MAX_FINALIZE_RETRIES
            ordernos_map = getattr(self, "_last_buy_ordernos", None)
            fills_map = getattr(self, "_last_buy_fills", None)
            prefer_tradebook = bool(ordernos_map)

            def _clear_last_buy_snapshot():
                self._last_buy_ordernos = None
                self._last_buy_fills = None

            def on_mis_avg_received(avg_ltp, attempt=0):
                if avg_ltp is None or avg_ltp < 0:
                    if attempt < MAX_FINALIZE_RETRIES:
                        log_message(f"[REAL] MIS avg price not available yet, retry {attempt+1}/{MAX_FINALIZE_RETRIES}")
                        QTimer.singleShot(1000, lambda: self.find_buy_avgLTP(self.common_symbol, callback=lambda avg: on_mis_avg_received(avg, attempt+1), ordernos_map=ordernos_map, fills_map=fills_map, prefer_tradebook=prefer_tradebook))
                    else:
                        log_message("[REAL] MIS avg price not available after retries")
                        # update label anyway so manual CE orders reflect current state
                        self.common_avgLTP = getattr(self, 'common_avgLTP', 0) or 0
                        self._finalize_CE_real_mis_state()
                        if self.CE_Deli_Buy_symbol:
                            self._finalize_CE_real_delivery_leg()
                        _clear_last_buy_snapshot()
                    return
                if avg_ltp == 0:
                    # no position at broker – clear stored avg
                    self.common_avgLTP = 0.0
                    self._finalize_CE_real_mis_state()
                    if self.CE_Deli_Buy_symbol:
                        self._finalize_CE_real_delivery_leg()
                    _clear_last_buy_snapshot()
                    return

                self.common_avgLTP = avg_ltp
                self.CE_buy_avgltp = avg_ltp
                self.ltp_ready = False  # ✅ Set immediately before GetToken to block update_live_prices until new tokens ready
                
                def on_token(token):
                    self.common_token = token
                    self.prepare_tokens([self.common_symbol])

                self.GetToken('NFO', self.common_symbol, callback=on_token)

                self._finalize_CE_real_mis_state()

                if self.CE_Deli_Buy_symbol:
                    self._finalize_CE_real_delivery_leg()

                _clear_last_buy_snapshot()
                    
            self.find_buy_avgLTP(self.common_symbol, callback=lambda avg: on_mis_avg_received(avg,0), ordernos_map=ordernos_map, fills_map=fills_map, prefer_tradebook=prefer_tradebook)

        except Exception as e:
            log_message(f"[ERROR] _finalize_CE_buy_real: {e}")

    def _finalize_CE_real_mis_state(self):
        try:
            # Check if order was actually filled - if not, reset everything
            if not self.common_avgLTP or self.common_avgLTP <= 0 or not self.netQty or self.netQty <= 0:
                log_message(f"[REAL] MIS CE {self.common_symbol}, Qty= {self.netQty} @ {self.common_avgLTP} this means order is not successful so call reset_all")
                self.Deli_order_label.setStyleSheet("color: Red")
                self.Deli_order_label.setText(f"MIS CE {self.common_symbol} order failed or not filled")
                self.reset_all()
                return
            
            if self.SL_order_flag:
                self.order_label.setStyleSheet("color: Blue")   
            else: 
                self.order_label.setStyleSheet("color: Green")
            # Always update label, even if repeated buy
            self.order_label.setText(f"MIS Trade - {self.common_symbol}, Qty= {self.netQty} @ {self.common_avgLTP}")

            self.CE_buy_flag = True
            self.CE_order_flag = True
            self.bigProfit_flag = True

            self.MIS_exit_button.setEnabled(True)
            self.reset_button.setEnabled(False)
            self.set_button_busy(self.MY_CE_buy_button, False, "&CE Buy")

            self.targetLTP = self.round_to_tick(self.common_avgLTP * 2)
            self.target_entry.setText(str(self.targetLTP))

            self.T1Level = self.intc_value + 40
            self.T1level_label.setText(f"T1 Level - {self.T1Level}")
            self.active_order_side = "CE"
            self.entry_time = datetime.datetime.now()
            self.entry_rsi_5m = self.rsi_5min
            self.entry_rsi_30m = self.rsi_30min
            self.CE_order_time = datetime.datetime.now()

            log_message(f"[REAL] MIS CE {self.common_symbol}, Qty= {self.netQty} @ {self.common_avgLTP}")

            # Record underlying at entry and defer paper-mode auto SL to live monitoring
            try:
                self.entry_underlying_at_buy = float(self.intc_value)
                # CRITICAL: Store entry underlying to disk for recovery after crash
                order_time_str = datetime.datetime.now().strftime("%d%m%y%H%M%S")
                if self.common_symbol:
                    self._store_entry_underlying(self.common_symbol, self.entry_underlying_at_buy, order_time_str)
            except Exception:
                self.entry_underlying_at_buy = None
        except Exception as e:
            log_message(f"[ERROR] _finalize_CE_real_mis_state: {e}")
            # Force label update on error
            self.order_label.setStyleSheet("color: Red")
            self.order_label.setText("CE Buy: Error occurred, but state updated.")

    def _finalize_CE_real_delivery_leg(self):
        MAX_FINALIZE_RETRIES = Config.MAX_FINALIZE_RETRIES
        
        def on_deli_avg_received(avg_ltp, attempt=0):
            if not avg_ltp or avg_ltp <= 0:
                if attempt < MAX_FINALIZE_RETRIES:
                    log_message(f"[REAL] Delivery avg not ready yet, retry {attempt+1}/{MAX_FINALIZE_RETRIES}")
                    QTimer.singleShot(1000, lambda: self.find_buy_avgLTP(self.CE_Deli_Buy_symbol, callback=lambda avg: on_deli_avg_received(avg, attempt+1)))
                else:
                    log_message("[REAL] Delivery avg not ready after retries")
                return

            self.CE_Deli_buy_avgltp = avg_ltp
            self.Deli_netQty = self.lot_size * self.CE_Deli_lot_number
            
            def on_deli_token(token):
                self.Deli_common_token = token
                self.Deli_common_symbol = self.CE_Deli_Buy_symbol
                self.prepare_tokens([self.Deli_common_symbol])

            self.GetToken('NFO', self.CE_Deli_Buy_symbol, callback=on_deli_token)

            self.Deli_order_label.setText(f"CNC Trade - {self.CE_Deli_Buy_symbol}, Qty= {self.Deli_netQty} @ {avg_ltp}")
            log_message(f"[REAL] CNC CE {self.CE_Deli_Buy_symbol}, Qty= {self.Deli_netQty} @ {avg_ltp}")

        self.find_buy_avgLTP(self.CE_Deli_Buy_symbol, callback=lambda avg: on_deli_avg_received(avg,0))

    def _finalize_CE_buy_paper(self):
        """Finalize CE buy in PAPER MODE (async-safe)"""
        try:
            def on_token_received(token):
                if not token:
                    log_message("[PAPER] Token not found, aborting CE paper fill")
                    return

                self.common_token = token

                def on_ltp_received(ltp):
                    if not ltp or ltp <= 0:
                        log_message("[PAPER] LTP not available, aborting CE paper fill")
                        return

                    self.common_currLTP = ltp
                    self._complete_CE_paper_fill(ltp)   

                self.GetLTP('NFO', token, callback=on_ltp_received)

            self.GetToken('NFO', self.common_symbol, callback=on_token_received)

        except Exception as e:
            log_message(f"[ERROR] _finalize_CE_buy_paper: {e}")

    def _complete_CE_paper_fill(self, raw_price):
        """Complete paper CE fill after price is known"""
        try:
            fill_price = self.round_to_tick(float(raw_price))

            self.common_avgLTP = fill_price
            self.CE_buy_avgltp = fill_price
            self.CE_buy_flag = True
            self.CE_order_flag = True
            self.bigProfit_flag = True
            self.ltp_ready = False  # ✅ Set immediately before GetToken to block update_live_prices until tokens ready

            def on_token(token):
                self.common_token = token
                self.prepare_tokens([self.common_symbol])

            self.GetToken('NFO', self.common_symbol, callback=on_token)

            if self.SL_order_flag:
                self.order_label.setStyleSheet("color: Blue")       
            else:
                self.order_label.setStyleSheet("color: Green")
            self.order_label.setText(
                f"[PAPER] MIS Trade - {self.common_symbol}, Qty= {self.netQty} @ {fill_price}"
            )

            self.MIS_exit_button.setEnabled(True)
            self.reset_button.setEnabled(False)
            self.set_button_busy(self.MY_CE_buy_button, False, "&CE Buy")

            self.targetLTP = self.round_to_tick(fill_price * 2)
            self.target_entry.setText(str(self.targetLTP))

            self.T1Level = self.intc_value + 40
            self.T1level_label.setText(f"T1 Level - {self.T1Level}")
            self.active_order_side = "CE"
            self.CE_order_time = datetime.datetime.now()
            self.entry_time = datetime.datetime.now()
            self.entry_rsi_5m = self.rsi_5min
            self.entry_rsi_30m = self.rsi_30min

            log_message(f"[PAPER] CE MIS Trade - {self.common_symbol}, Qty= {self.netQty} @ {fill_price}")

           # Record underlying at entry and defer paper-mode auto SL to live monitoring
            try:
                self.entry_underlying_at_buy = float(self.intc_value)
                # CRITICAL: Store entry underlying to disk for recovery after crash
                order_time_str = datetime.datetime.now().strftime("%d%m%y%H%M%S")
                if self.common_symbol:
                    self._store_entry_underlying(self.common_symbol, self.entry_underlying_at_buy, order_time_str)
            except Exception:
                self.entry_underlying_at_buy = None

        except Exception as e:
            log_message(f"[ERROR] _complete_CE_paper_fill: {e}")

    #+++++++++ Exit Handling ++++++++++++++
    def _init_position_orders(self, symbol):
        """Initialize order mapping structure for a symbol"""
        if symbol not in self.position_orders:
            self.position_orders[symbol] = {
                'entry': None,
                'target': None,
                'stoploss': None,
                'exit': None
            }

    def _has_any_exit_order(self, symbol):
        """Return True if any target/stoploss/exit is tracked for symbol."""
        try:
            orders = self.position_orders.get(symbol, {})
            return bool(
                orders.get('target') or
                orders.get('stoploss') or
                orders.get('exit') or
                getattr(self, 'Target_order_flag', False) or
                getattr(self, 'SL_order_flag', False)
            )
        except Exception:
            return False
    
    def _cancel_all_exit_orders(self, symbol):
        """Cancel all pending target/SL/exit orders for a symbol - MASTER EXIT USE"""
        try:
            if symbol not in self.position_orders:
                return True
            
            orders = self.position_orders[symbol]
            cancelled_count = 0
            
            # Cancel target order if exists AND pending
            if orders.get('target'):
                status = orders['target'].get('status', 'PENDING')
                # Only cancel if status is PENDING; skip EXECUTED/FILLED/COMPLETED
                if status == 'PENDING':
                    log_message(f"[MASTER EXIT] Cancelling target order for {symbol}")
                    try:
                        self.multi_cancel_order(symbol)
                        orders['target']['status'] = 'CANCELLED'
                        cancelled_count += 1
                    except Exception as e:
                        log_message(f"[WARNING] Failed to cancel target order (may already be executed): {e}")
                        # Mark as completed anyway since broker likely rejects cancel on filled orders
                        orders['target']['status'] = 'COMPLETED'
                    time.sleep(0.5)
                elif status in ('EXECUTED', 'FILLED', 'COMPLETE'):
                    # Order already executed - no need to cancel
                    log_message(f"[MASTER EXIT] Target order already {status} at broker - skipping cancel")
            
            # Cancel stoploss order if exists AND pending
            if orders.get('stoploss'):
                status = orders['stoploss'].get('status', 'PENDING')
                # Only cancel if status is PENDING; skip EXECUTED/FILLED/COMPLETED
                if status == 'PENDING':
                    log_message(f"[MASTER EXIT] Cancelling stoploss order for {symbol}")
                    try:
                        self.multi_cancel_order(symbol)
                        orders['stoploss']['status'] = 'CANCELLED'
                        cancelled_count += 1
                    except Exception as e:
                        log_message(f"[WARNING] Failed to cancel stoploss order (may already be executed): {e}")
                        # Mark as completed anyway since broker likely rejects cancel on filled orders
                        orders['stoploss']['status'] = 'COMPLETED'
                    time.sleep(0.5)
                elif status in ('EXECUTED', 'FILLED', 'COMPLETE'):
                    # Order already executed - no need to cancel
                    log_message(f"[MASTER EXIT] Stoploss order already {status} at broker - skipping cancel")
            
            # Cancel any pending exit order
            if orders.get('exit'):
                status = orders['exit'].get('status', 'PENDING')
                # Only cancel if status is PENDING; skip EXECUTED/FILLED/COMPLETED
                if status == 'PENDING':
                    log_message(f"[MASTER EXIT] Cancelling previous exit order for {symbol}")
                    try:
                        self.multi_cancel_order(symbol)
                        orders['exit']['status'] = 'CANCELLED'
                        cancelled_count += 1
                    except Exception as e:
                        log_message(f"[WARNING] Failed to cancel exit order (may already be executed): {e}")
                        orders['exit']['status'] = 'COMPLETED'
                    time.sleep(0.5)
                elif status in ('EXECUTED', 'FILLED', 'COMPLETE'):
                    # Order already executed - no need to cancel
                    log_message(f"[MASTER EXIT] Exit order already {status} at broker - skipping cancel")
            
            if cancelled_count > 0:
                log_message(f"[MASTER EXIT] Cancelled {cancelled_count} pending order(s)")
            
            return True
            
        except Exception as e:
            log_message(f"[ERROR] _cancel_all_exit_orders: {e}")
            return False

    def manual_exit(self):
        log_message(f"[MANUAL EXIT] Initiating manual exit for {self.common_symbol}")
        self.CE_PE_exit()

    def CE_PE_exit(self):
        """
        MASTER EXIT FUNCTION - Handles all exit scenarios
        ✅ Cancels any existing target/SL orders before exiting
        ✅ Places fresh exit order at market
        ✅ Works for both full and partial exits
        ✅ Survives even if target/SL already exist at broker
        ✅ Smart order management - no conflicts
        """
        # mark scheduled flag and set busy UI
        self._exit_scheduled = True
        self.set_button_busy(self.MIS_exit_button, True, "Exiting...")
        try:
            # Determine exit quantity
            squareoff_lots_text = self.squareoff_lots.text().strip()
            
            if squareoff_lots_text != '':
                try:
                    exit_lots = int(squareoff_lots_text)
                except ValueError:
                    log_message(f"[ERROR] Invalid squareoff lots: {squareoff_lots_text}")
                    self.set_button_busy(self.MIS_exit_button, False, "&MIS Exit")
                    return
                
                # Validate exit quantity
                if exit_lots <= 0:
                    log_message(f"[ERROR] Exit lots must be positive")
                    self.set_button_busy(self.MIS_exit_button, False, "&MIS Exit")
                    return
                
                if exit_lots > self.position_lots:
                    log_message(f"[ERROR] Cannot exit {exit_lots} lots, only {self.position_lots} lots in position")
                    self.set_button_busy(self.MIS_exit_button, False, "&MIS Exit")
                    return
                
                is_partial_exit = (exit_lots < self.position_lots)
                
            else:
                # Full exit
                exit_lots = self.position_lots
                is_partial_exit = False
            
            # Store pre-exit position details
            pre_exit_lots = self.position_lots
            remaining_lots = pre_exit_lots - exit_lots
            exit_qty = exit_lots * self.lot_size

            # Calculate current price and average price early (needed for exit info)
            curr = float(self.common_currLTP)
            avg = float(self.common_avgLTP)

            if is_partial_exit:
                log_message(f'  Remaining: {remaining_lots} lots @ {avg}')
            
            # ✅ MASTER EXIT: CANCEL ANY EXISTING ORDERS FIRST
            log_message(f"[MASTER EXIT] Starting smart exit for {self.common_symbol}")
            if self.common_symbol:
                self._init_position_orders(self.common_symbol)
                self._cancel_all_exit_orders(self.common_symbol)
                
                # Place fresh exit order
                if self.PaperTrade_checkbox.isChecked():
                    log_message(f"[PAPER MODE] Placing exit order for {self.common_symbol}, qty={exit_qty} @ MKT")
                    self.sell_stat = self.multi_place_order('S', 'M', 'NFO', self.common_symbol, exit_qty, 'MKT', 0)
                    last_exit_res = None
                    ordernos = {}
                else:
                    # Real mode: Place and confirm exit
                    log_message(f"[REAL MODE] Placing exit order for {self.common_symbol}, qty={exit_qty} @ MKT")
                    last_exit_res = self.place_and_confirm('S', 'M', 'NFO', self.common_symbol, exit_qty, 'MKT', 0, timeout=30)
                    fills = last_exit_res.get('fills', {})
                    ordernos = last_exit_res.get('ordernos', {})
                    total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                    self._last_exit_res = last_exit_res
                    if total_filled <= 0:
                        log_message(f"[ORDER] ⚠️ Exit placed but no fills reported for {self.common_symbol}")
                    else:
                        log_message(f"[ORDER] ✅ Exit order filled: {total_filled} qty")
                
                # ✅ Map the exit order
                if ordernos:
                    self.position_orders[self.common_symbol]['exit'] = {
                        'order_id': list(ordernos.values())[0],
                        'qty': exit_qty,
                        'side': 'S',
                        'order_type': 'MKT',
                        'status': 'PENDING',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'placed_by': 'CE_PE_exit()'
                    }
                    log_message(f"[MASTER EXIT] Exit order mapped: {self.position_orders[self.common_symbol]['exit']['order_id']}")

            # Store exit info for confirmation only; do not update tracked lots until confirmation in REAL mode
            self.exit_info = {
                'is_partial': is_partial_exit,
                'exit_lots': exit_lots,
                'remaining_lots': remaining_lots,
                'avg_price': avg
            }
            if is_partial_exit:
                log_message(f"[EXIT] Pending confirmation for {exit_lots} lots; remaining expected: {remaining_lots} lots")
                
                # Clear squareoff input
                self.squareoff_lots.setText('')
            else:
                # Full exit: Will clear flags after confirmation
                self.exit_info = {
                    'is_partial': False,
                    'exit_lots': exit_lots,
                    'remaining_lots': 0,
                    'avg_price': avg
                }
                
                # Set flags to False for full exit
                self.PE_buy_flag = False
                self.CE_buy_flag = False
            
            # Calculate P&L for the exited portion
            PnL = round((curr - avg) * exit_qty, 2)
            if avg > 0:
                PnlPer = round(((curr - avg) / avg) * 100, 2)
            else:
                PnlPer = 0.0  # Avoid division by zero
            log_message(f'[EXIT*] {self.common_symbol} {"Partial" if is_partial_exit else "Full"} exit:')
            log_message(f'  Exiting: {exit_lots} lots @ {curr}, Avg: {avg}')
            log_message(f'  P&L: ₹{PnL} ({PnlPer}%)')

            # Start exit confirmation check
            self._check_exit_status()
            
        except Exception as e:
            log_message(f"[ERROR] CE_PE_exit: {e}")
            self.set_button_busy(self.MIS_exit_button, False, "&MIS Exit")
        finally:
            # Clear scheduled flag in all cases so subsequent exits can be scheduled
            try:
                self._exit_scheduled = False
            except Exception:
                pass

    def _check_exit_status(self):
        """Check if exit order is confirmed - with partial exit support"""
        try:
            if not hasattr(self, 'exit_info'):
                log_message("[ERROR] Exit info not found")
                self.set_button_busy(self.MIS_exit_button, False, "&MIS Exit")
                return
            
            is_partial = self.exit_info['is_partial']
            exit_lots = self.exit_info['exit_lots']
            remaining_lots = self.exit_info['remaining_lots']
            
            if self.PaperTrade_checkbox.isChecked():
                self._handle_paper_exit(is_partial, exit_lots, remaining_lots)
                return

            # Real mode: verify exit from broker using APIWorker (non-blocking)
            max_retries = 10  # Reduced from 15 to 10 (max 10 seconds of waiting)
            retry_count = {'n': 0}
            start_time = time.time()
            timeout_secs = 10  # Overall timeout of 10 seconds

            def check_position():
                retry_count['n'] += 1
                elapsed = time.time() - start_time

                def on_positions(positions):
                    try:
                        current_qty = 0
                        if positions:
                            for pos in positions:
                                if pos.get('tsym') == self.common_symbol:
                                    current_qty = abs(int(pos.get('netqty', 0)))
                                    break

                        expected_qty = remaining_lots * self.lot_size
                        if current_qty == expected_qty:
                            log_message(f"[EXIT CONFIRMED] Position verified: {remaining_lots} lots")
                            self._finalize_exit(is_partial, exit_lots, remaining_lots)
                            return

                        # Check timeout
                        if elapsed > timeout_secs:
                            log_message(f"[EXIT] Timeout after {timeout_secs}s - proceeding anyway")
                            self._finalize_exit(is_partial, exit_lots, remaining_lots)
                            return

                        if retry_count['n'] < max_retries:
                            log_message(f"[EXIT CHECK] Verifying... ({retry_count['n']}/{max_retries}, {elapsed:.1f}s)")
                            QTimer.singleShot(1000, check_position)
                            return

                        log_message(f"[EXIT] Max retries reached - proceeding anyway")
                        self._finalize_exit(is_partial, exit_lots, remaining_lots)

                    except Exception as e:
                        log_message(f"[ERROR] check_position/on_positions: {e}")
                        self._finalize_exit(is_partial, exit_lots, remaining_lots)

                def on_error(err):
                    log_message(f"[ERROR] check_position API call: {err}")
                    elapsed = time.time() - start_time
                    if elapsed > timeout_secs:
                        self._finalize_exit(is_partial, exit_lots, remaining_lots)
                    elif retry_count['n'] < max_retries:
                        QTimer.singleShot(1000, check_position)
                    else:
                        self._finalize_exit(is_partial, exit_lots, remaining_lots)

                # use APIWorker to fetch positions from master account
                worker = APIWorker(self.api_master.get_positions)
                worker.signals.result.connect(on_positions)
                worker.signals.error.connect(on_error)
                self.api_threadpool.start(worker)

            QTimer.singleShot(1000, check_position)
 
            
        except Exception as e:
            log_message(f"[ERROR] _check_exit_status: {e}")
            self.set_button_busy(self.MIS_exit_button, False, "&MIS Exit")

    def _handle_paper_exit(self, is_partial, exit_lots, remaining_lots):
        """Handle paper mode exit"""
        try:
            log_message(f"[PAPER MODE] Exit processed: {exit_lots} lots")
            # Delay slightly for realism
            QTimer.singleShot(500, lambda: self._finalize_exit(is_partial, exit_lots, remaining_lots))
        except Exception as e:
            log_message(f"[ERROR] _handle_paper_exit: {e}")
            self._finalize_exit(is_partial, exit_lots, remaining_lots)

    def _finalize_exit(self, is_partial, exit_lots, remaining_lots):
        """Finalize exit and update UI"""
        try:
            if is_partial:
                # Partial exit: Update UI but keep position active
                self.order_label.setStyleSheet("color: DarkOrange")
                self.Deli_order_label.setStyleSheet("color: DarkOrange")
                self.Deli_order_label.setText(
                    f"Partial Exit - {exit_lots} lots closed | "
                    f"Remaining: {remaining_lots} lots @ {self.common_avgLTP:.2f}"
                )
                
                # Keep position flags for remaining position
                self.set_position_lots(remaining_lots)
                
                # Ensure order flags reflect remaining position
                if self.active_order_side == "CE":
                    self.CE_order_flag = True
                    self.PE_order_flag = False
                    self.CE_buy_flag = True
                    if Config.manual_override:
                        self.MY_CE_buy_button.setEnabled(True)
                elif self.active_order_side == "PE":
                    self.PE_order_flag = True
                    self.CE_order_flag = False
                    self.PE_buy_flag = True
                    if Config.manual_override:
                        self.MY_PE_buy_button.setEnabled(True)
                
                # Keep exit button enabled
                self.MIS_exit_button.setEnabled(True)
                self.set_button_busy(self.MIS_exit_button, False, "&MIS Exit")
                
                # Update target for remaining position
                self.targetLTP = self.round_to_tick(self.common_avgLTP * 2)
                self.target_entry.setText(str(self.targetLTP))
                # Place stoploss for remaining lots to protect the remaining position
                try:
                    # Ensure position_lots already reflects remaining before placing SL
                    # set_stoploss will read self.position_lots and place SL accordingly
                    self.set_stoploss()
                except Exception as e:
                    log_message(f"[PARTIAL EXIT] ⚠️ Failed to place stoploss for remaining lots: {e}")
                
                log_message(f"[PARTIAL EXIT COMPLETE] {remaining_lots} lots @ {self.common_avgLTP:.2f} active")

            else:
                # Full exit: Reset everything
                self.order_label.setStyleSheet("color: Red")
                self.order_label.setText(f"Position Closed - {self.common_symbol}")
                
                # Reset position variables
                self.set_position_lots(0)
                self.active_order_side = None

                # Reset flags
                self.PE_buy_flag = False
                self.CE_buy_flag = False
                self.PE_order_flag = False
                self.CE_order_flag = False
                self.SL_order_flag = False
                self.Target_order_flag = False
                self.bigProfit_flag = False
                
                # Reset UI
                self.MIS_exit_button.setEnabled(False)
                self.set_button_busy(self.MIS_exit_button, False, "&MIS Exit")
                self.target_button.setEnabled(False)
                self.stoploss_button.setEnabled(False)                
                # Re-enable autotrade
                if Config.manual_override:
                    self.reset_button.setEnabled(True)
                    self.MY_CE_buy_button.setEnabled(True)
                    self.MY_PE_buy_button.setEnabled(True)
                else:
                    self.reset_button.setEnabled(False)
                    self.MY_CE_buy_button.setEnabled(False)
                    self.MY_PE_buy_button.setEnabled(False)
                    
                self.reset_all()
                
                log_message(f"[FULL EXIT COMPLETE] All positions closed")
            
            # Clean up exit info
            if hasattr(self, 'exit_info'):
                delattr(self, 'exit_info')
            if hasattr(self, 'exit_retry_count'):
                delattr(self, 'exit_retry_count')
                
        except Exception as e:
            log_message(f"[ERROR] _finalize_exit: {e}")
            self.set_button_busy(self.MIS_exit_button, False, "&MIS Exit")
    
    def _cancel_pending_buy_orders(self):
        """
        Cancel any pending (unfilled) limit buy orders before reset
        - Checks both MIS position (common_orderID) and CNC position (Deli_common_orderID)
        - Paper mode: no-op (orders auto-fill instantly)
        - Real mode: cancels via API using multi_cancel_order
        """
        try:
            # Skip if in paper mode (orders are auto-filled)
            if self.PaperTrade_checkbox.isChecked():
                log_message("[RESET] Paper mode - no pending orders to cancel")
                return
            
            cancelled_count = 0
            
            # ─────────────────────────────────────────────
            # Cancel pending MIS buy order
            # ─────────────────────────────────────────────
            if self.common_orderID is not None and self.common_symbol:
                log_message(f"[RESET] Cancelling pending MIS buy order for {self.common_symbol}")
                try:
                    # common_orderID is a dict: {user_id: order_no}
                    for user_id, order_no in self.common_orderID.items():
                        log_message(f"[RESET] Cancelling MIS order {order_no} for user {user_id}")
                        self.multi_cancel_order(self.common_symbol)
                        time.sleep(0.2)
                    cancelled_count += 1
                except Exception as e:
                    log_message(f"[RESET] Warning cancelling MIS buy order: {e}")
            
            # ─────────────────────────────────────────────
            # Cancel pending CNC (Delivery) buy order
            # ─────────────────────────────────────────────
            if hasattr(self, 'Deli_common_orderID') and self.Deli_common_orderID is not None and getattr(self, 'Deli_common_symbol', None):
                log_message(f"[RESET] Cancelling pending CNC buy order for {self.Deli_common_symbol}")
                try:
                    # Deli_common_orderID is a dict: {user_id: order_no}
                    for user_id, order_no in self.Deli_common_orderID.items():
                        log_message(f"[RESET] Cancelling CNC order {order_no} for user {user_id}")
                        self.multi_cancel_order(self.Deli_common_symbol)
                        time.sleep(0.2)
                    cancelled_count += 1
                except Exception as e:
                    log_message(f"[RESET] Warning cancelling CNC buy order: {e}")
            
            if cancelled_count > 0:
                log_message(f"[RESET] Cancelled {cancelled_count} pending buy order(s)")
            else:
                log_message("[RESET] No pending buy orders to cancel")
            
            return True
            
        except Exception as e:
            log_message(f"[ERROR] _cancel_pending_buy_orders: {e}")
            return False
        
    def reset_all(self):
        """Reset all trading flags and states"""
        try:
            # ✅ FIRST: Cancel any pending buy orders if they exist
            log_message("[RESET] Checking for pending buy orders to cancel...")
            self._cancel_pending_buy_orders()
            
            # Save symbol before clearing it (for map cleanup)
            saved_symbol = self.common_symbol
            saved_deli_symbol = self.Deli_common_symbol if hasattr(self, 'Deli_common_symbol') else None
            
            # Remove MIS position from websocket
            if self.common_token and self.common_symbol is not None:
                self.remove_symbol_token(self.common_symbol)
                self.on_open()
            
            # Remove Delivery position from websocket
            if hasattr(self, 'Deli_common_token') and self.Deli_common_token and saved_deli_symbol is not None:
                self.remove_symbol_token(saved_deli_symbol)
            
            # Clear MIS position maps using saved symbol
            if saved_symbol and saved_symbol in self.symbol_qty_map:
                self.symbol_qty_map[saved_symbol] = 0
                # CRITICAL: Clear entry tracking for recovery data
                self._clear_entry_underlying(saved_symbol)
            if saved_symbol and saved_symbol in self.symbol_avg_map:
                self.symbol_avg_map[saved_symbol] = 0.0
            
            # Clear Delivery position maps using saved symbol
            if saved_deli_symbol and saved_deli_symbol in self.symbol_qty_map:
                self.symbol_qty_map[saved_deli_symbol] = 0
                # CRITICAL: Clear entry tracking for recovery data
                self._clear_entry_underlying(saved_deli_symbol)
            if saved_deli_symbol and saved_deli_symbol in self.symbol_avg_map:
                self.symbol_avg_map[saved_deli_symbol] = 0.0
            self.set_button_busy(self.MY_PE_buy_button, False, "&PE Buy")
            self.set_button_busy(self.MY_CE_buy_button, False, "&CE Buy")   
            self.set_button_busy(self.MIS_exit_button, False, "&MIS Exit")
            self.set_button_busy(self.exitCNC_button, False, "&Exit CNC")
            self.set_button_busy(self.stoploss_button, False, "&Set Stoploss")
            self.set_button_busy(self.target_button, False, "Set &Target")
            self.stoploss_button.setEnabled(False)
            self.target_button.setEnabled(False)
            self.MIS_exit_button.setEnabled(False)
            self.exitCNC_button.setEnabled(False)
            if Config.manual_override:
                self.MY_PE_buy_button.setEnabled(True)
                self.MY_CE_buy_button.setEnabled(True)
            else:
                self.MY_PE_buy_button.setEnabled(False)
                self.MY_CE_buy_button.setEnabled(False)

            self.ThirdOTM_checkbox.setCheckable(True)
            self.T1Level = 0
            self.TSL_checkbox.setChecked(False)
            # ─────────────────────────────────────────────
            # MIS POSITION RESET
            # ─────────────────────────────────────────────
            self.CE_buy_flag = False
            self.PE_buy_flag = False
            self.PE_order_flag = False
            self.CE_order_flag = False
            self.bigProfit_flag = True
            self.common_orderID = None
            self._last_buy_ordernos = None
            self._last_buy_fills = None
            self.common_avgLTP = 0.0
            self.common_token = None
            self.common_symbol = None
            self.common_currLTP = 0.0

            # ─────────────────────────────────────────────
            # DELIVERY POSITION RESET
            # ─────────────────────────────────────────────
            self.Deli_common_symbol = None
            self.Deli_common_token = None
            self.Deli_common_orderID = None if hasattr(self, 'Deli_common_orderID') else None
            self.Deli_common_avgLTP = 0.0
            self.Deli_common_currLTP = 0.0
            self.Deli_netQty = 0
            self.PE_Deli_Buy_symbol = None
            self.CE_Deli_Buy_symbol = None
            self.PE_Deli_buy_avgltp = 0.0
            self.CE_Deli_buy_avgltp = 0.0
            self.PE_Deli_lot_number = 0
            self.CE_Deli_lot_number = 0

            # ─────────────────────────────────────────────
            # P&L RESET
            # ─────────────────────────────────────────────
            self.PnL = 0.0
            self.PnlPer = 0.0
            self.PnL2 = 0.0
            self.PnlPer_Deli = 0.0
            self.netQty = 0
            self.netavgprc = 0.0
            
            # ─────────────────────────────────────────────
            # UI RESET (with safety checks)
            # ─────────────────────────────────────────────
            if self.target_entry is not None:
                self.target_entry.setText("")
            if self.stoploss_entry is not None:
                self.stoploss_entry.setText("")
            if self.entry_price is not None:
                self.entry_price.setText('')
            if self.order_label is not None:
                self.order_label.setStyleSheet("color: Black")
                self.order_label.setText("MIS Trade - ")
            if self.Deli_order_label is None:
                self.Deli_order_label.setStyleSheet("color: Black")
                self.Deli_order_label.setText("CNC Trade - ")
            if self.T1level_label is not None:
                self.T1level_label.setText("T1 Level - ")
            self.SL_order_flag = False
            self.Target_order_flag = False
            self.target = 0
            self.stoplossLTP = 0

            # ─────────────────────────────────────────────
            # ENTRY DATA RESET
            # ─────────────────────────────────────────────
            self.entry_price = None if not hasattr(self, 'entry_price') else self.entry_price
            self.entry_rsi_5m = 0.0
            self.entry_rsi_30m = 0.0
            self.entry_underlying_at_buy = None
            self.entry_time = None
            self.PE_order_time = None
            self.CE_order_time = None
            self.targetLTP = 0.0
            self.T1Level = 0

            # ─────────────────────────────────────────────
            # SIGNAL & ACTION RESET
            # ─────────────────────────────────────────────
            self.act_divergence = None
            self.act_entry = None
            self.act_ce_exit = None
            self.act_pe_exit = None
            self.act_postion = None
            self.act_option_action = None
            self.act_entry_data = None
            self.position_lots = 0
            self.active_order_side = None
            
            # ─────────────────────────────────────────────
            # SETUP & BREAKOUT RESET
            # ─────────────────────────────────────────────
            self.bullish_setup_armed = False
            self.bearish_setup_armed = False
            self.bullish_setup_time = None
            self.bearish_setup_time = None
            self.structure_break_up = False
            self.structure_break_down = False
            self.valid_breakout = False
            self.in_whipsaw_zone = False
            
            # ─────────────────────────────────────────────
            # CLEAR HELPER DATA
            # ─────────────────────────────────────────────
            self._clear_entry_data()
            if hasattr(self, 'exit_info'):
                delattr(self, 'exit_info')
            if hasattr(self, 'target_info'):
                delattr(self, 'target_info')
            if hasattr(self, 'stoploss_info'):
                delattr(self, 'stoploss_info')
            if hasattr(self, 'exit_retry_count'):
                delattr(self, 'exit_retry_count')
            
            self.last_exit_time = datetime.datetime.now()

            now = QTime.currentTime().msecsSinceStartOfDay()
            if self.repeatRSIautoTrade and now < Config.MARKET_CLOSE.msecsSinceStartOfDay():
                self.RSI_autoTrade_checkbox.setChecked(True)

            print("[STOP ALL] Everything is cleared.")
        except Exception as e:
            log_message(f"[ERROR] stop_all: {e}")

    def exitCNC(self):
        self.set_button_busy(self.exitCNC_button, True, "Exiting...")
        """Exit CNC/Delivery trade - UPDATED with non-blocking confirmation"""
        new_lots = self.Deli_netQty//self.lot_size if self.Deli_netQty else 0
        try:
            if self.Deli_common_token:
                deli_sell_stat = None
                last_exit_res = None
                total_filled = 0
                if self.PaperTrade_checkbox.isChecked():
                    deli_sell_stat = self.multi_place_order('S', 'M', 'NFO', self.Deli_common_symbol, self.Deli_netQty, 'MKT', 0)
                    # We'll still run confirmation flow below
                    last_exit_res = None
                else:
                    # Place and confirm CNC exit in real mode
                    last_exit_res = self.place_and_confirm('S', 'M', 'NFO', self.Deli_common_symbol, self.Deli_netQty, 'MKT', 0, timeout=30)
                    fills = last_exit_res.get('fills', {})
                    total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')

                # ✅ CHANGED: Use non-blocking exit confirmation
                def on_cnc_exit_confirmed(success):
                    """Called when CNC exit is confirmed"""
                    if (self.PaperTrade_checkbox.isChecked() and (deli_sell_stat or success)) or (not self.PaperTrade_checkbox.isChecked() and (last_exit_res and total_filled > 0)):
                        log_message(f"[CNC EXIT] ✅ {self.Deli_common_symbol} square off @ price- {self.Deli_common_currLTP}, PnL = {self.PnL2} ({self.PnlPer_Deli}%)")
                        # clear symbol state
                        if self.Deli_common_symbol is not None:
                            self.remove_symbol_token(self.Deli_common_symbol)
                            self.Deli_common_symbol = None
                            self.on_open()
                            self.symbol_qty_map[self.Deli_common_symbol] = 0
                            self.symbol_avg_map[self.Deli_common_symbol] = 0.0
                            self.PnL2 = 0.0
                            self.PnlPer_Deli = 0.0
                            self.Deli_common_token = None
                            self.Deli_common_avgLTP = 0.0
                            self.Deli_order_label.setText("CNC Trade - ")
                            self.set_button_busy(self.exitCNC_button, False, "&Exit CNC")
                            self.exitCNC_button.setEnabled(False)
                    else:
                        log_message(f"[CNC EXIT] ⚠️ Exit confirmation failed")
                
                # Start non-blocking confirmation
                if self.PaperTrade_checkbox.isChecked(): # and not Config.PAPER_MODE:
                    timeout_duration = 1    
                else:
                    timeout_duration = 30   
                self.confirm_orderExit(self.Deli_common_symbol, new_lots, callback=on_cnc_exit_confirmed, timeout=timeout_duration)
                
        except Exception as e:
            log_message(f"[ERROR] exitCNC: {e}")

    def confirm_orderExit(self, tradingsymbol, lots_to_be_confirmed, callback=None, timeout=30):
        """
        Confirm order exit - NON-BLOCKING version with timeout.
        Args:
            tradingsymbol: Symbol to check for exit
            callback: Function to call with result - callback(success: bool)
            timeout: Maximum seconds to wait (default: 30)
        Returns:
            If callback is None, returns False immediately
            If callback provided, calls callback(True/False) when confirmed or timeout
        Example:
            self.confirm_orderExit('NIFTY25DEC2425500PE', lambda success: 
                print(f"Exit {'successful' if success else 'failed'}"))
        """
        
        if callback is None:
            log_message(f"[WARN] confirm_orderExit called without callback for {tradingsymbol}")
            return False
        
        start_time = time.time()
        check_count = [0]  # Use list to allow modification in nested function
        
        def check_position():
            """Recursively check position status"""
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                log_message(f"[EXIT] ⚠️ Exit confirmation timed out after {timeout}s for {tradingsymbol}")
                callback(False)
                return
            
            check_count[0] += 1
            
            def on_positions_received(positions):
                """Called when positions are fetched"""
                try:
                    if positions is None:
                        log_message(f"[EXIT] ⚠️ No positions returned (check {check_count[0]})")
                        # Schedule next check
                        QTimer.singleShot(500, check_position)
                        return
                    
                    found = False
                    for position in positions:
                        if position['tsym'] == tradingsymbol:
                            found = True
                            netqty = int(position['netqty'])
                            if netqty == int(lots_to_be_confirmed * self.lot_size):
                                log_message(f"[EXIT] ✅ {tradingsymbol} Exit confirmed with expected quantity (check {check_count[0]})")
                                callback(True)
                                return                              
                            if netqty == 0:
                                log_message(f"[EXIT] ✅ {tradingsymbol} Full Order exited successfully (check {check_count[0]})")
                                callback(True)
                                return
                            else:
                                log_message(f"[EXIT] ⏳ Waiting for exit. netqty: {netqty} (check {check_count[0]})")
                                break
                    
                    if not found:
                        # Position not in list = closed
                        log_message(f"[EXIT] ✅ {tradingsymbol} Position closed (check {check_count[0]})")
                        callback(True)
                        return
                    
                    # Not exited yet, schedule next check
                    QTimer.singleShot(500, check_position)
                    
                except Exception as e:
                    log_message(f"[EXIT] ❌ Error checking positions: {e}")
                    callback(False)
            
            def on_error(error_tuple):
                """Called when get_positions fails"""
                exc, tb = error_tuple
                log_message(f"[EXIT] ⚠️ Error fetching positions (check {check_count[0]}): {exc}")
                
                # Continue checking despite error
                QTimer.singleShot(500, check_position)
            
            # Fetch positions
            worker = APIWorker(self.api_master.get_positions)
            worker.signals.result.connect(on_positions_received)
            worker.signals.error.connect(on_error)
            self.api_threadpool.start(worker)
        
        # Start the first check
        log_message(f"[EXIT] Starting exit confirmation for {tradingsymbol} (timeout: {timeout}s)")
        check_position()
        return None

#+++++++++ Half Order Handling ++++++++++++++
    def half_order_handle(self, reduce_lots, only_one: bool = False):
        """Handle half order exit - UPDATED with non-blocking operations
        Args:
            reduce_lots: Number of lots to reduce/exit
            only_one: If True (and reduce_lots == 0), place SL at avg price for the 1 lot instead of exiting
        """
        try:
            self.timer_CL.stop()
            # save pre-half state to allow reliable restore on failure
            self._pre_half_netQty = int(getattr(self, "netQty", 0))
            self._pre_half_lots = int(getattr(self, "position_lots", 0))

            # ✅ SPECIAL CASE: only_one == True means we have exactly 1 lot and can't reduce
            if only_one and reduce_lots == 0:
                log_message(f"[PRIORITY 13] Only 1 lot in position → Placing SL @ avg price {self.common_avgLTP} instead of exit")
                self.stoplossLTP = self.round_to_tick(float(self.common_avgLTP))
                self.stoploss_entry.setText(str(self.stoplossLTP))
                # If current LTP is already at or below SL, force market exit for remaining lots
                curr_ltp = getattr(self, 'common_currLTP', None)
                if curr_ltp is not None and float(curr_ltp) <= float(self.stoplossLTP):
                    log_message("[HALF EXIT] current LTP below or equal to SL -> forcing market exit for remaining lots")
                    # Ensure CE_PE_exit will target the remaining lots (clear manual squareoff input)
                    try:
                        self.squareoff_lots.setText('')
                    except Exception:
                        pass
                    # Trigger immediate market exit for remaining lots
                    self.CE_PE_exit()
                    return
                else:            
                    self.set_stoploss()
                    log_message(f"[PRIORITY 14] ✅ SL placed @ {self.stoplossLTP} for 1 lot. Position held for 100% profit target.")
                    self.SL_order_flag = True
                    self.Target_order_flag = False
                    self.CE_order_flag = False
                    self.PE_order_flag = False
                    self.bigProfit_flag = False
                    self.target_button.setEnabled(True)
                    self.timer_CL.start(5000)  # Increased interval to reduce API load
                    return

            # Determine manually entered exit quantity
            squareoff_lots_text = self.squareoff_lots.text().strip()
            if squareoff_lots_text != '':
                try:
                    reduce_lots = int(squareoff_lots_text)
                except ValueError:
                    log_message(f"[ERROR] Invalid squared off lots: {squareoff_lots_text}")
                    return
                if reduce_lots <= 0:
                    log_message(f"[ERROR] squared off lots must be positive")
                    return
                if reduce_lots > int(self.position_lots):
                    log_message(f"[ERROR] Cannot SET squared off {reduce_lots} lots, only {self.position_lots} lots in position")
                    return

            new_lots = int(self.position_lots) - reduce_lots
            self.set_position_lots(new_lots)
            # also update symbol_qty_map in case other routines rely on it immediately
            try:
                if self.common_symbol:
                    self.symbol_qty_map[self.common_symbol] = new_lots * int(self.lot_size)
            except Exception:
                pass
                        
            # Place sale for half exit; confirm fills in real mode
            if self.PaperTrade_checkbox.isChecked():
                sell_stat = self.multi_place_order('S', 'M', 'NFO', self.common_symbol, reduce_lots * self.lot_size, 'MKT', 0)
                last_half_res = None
            else:
                last_half_res = self.place_and_confirm('S', 'M', 'NFO', self.common_symbol, reduce_lots * self.lot_size, 'MKT', 0, timeout=30)
                sell_stat = None

            # Diagnostic logging for half-exit placement results
            try:
                if sell_stat is not None:
                    log_message(f"[HALF EXIT] PAPER mode multi_place_order result: {sell_stat}")
                if last_half_res is not None:
                    log_message(f"[HALF EXIT] REAL mode place_and_confirm result: {last_half_res}")
                    fills = last_half_res.get('fills', {}) if isinstance(last_half_res, dict) else {}
                    log_message(f"[HALF EXIT] REAL mode fills summary: {fills}")
                    # persist for debug inspection
                    self._last_half_res = last_half_res
            except Exception as e:
                log_message(f"[HALF EXIT] ⚠️ Error logging half exit results: {e}")

            # ✅ CHANGED: Chain operations without delays
            def on_half_exit_confirmed(success):
                """Called when half exit is confirmed"""
                # Determine success for real mode if not provided by confirm_orderExit
                if not success and last_half_res:
                    fills = last_half_res.get('fills', {})
                    total_filled = sum(int(info.get('filled_qty', 0)) for info in fills.values() if info.get('status') == 'COMPLETE')
                    success = total_filled > 0

                if not success:
                    if self.PaperTrade_checkbox.isChecked():
                        log_message("[HALF EXIT] ⚠️ PAPER MODE: Simulated half exit.")
                    else:
                        # restore previous tracked lots/qty reliably
                        prev_lots = int(getattr(self, "_pre_half_lots", 0))
                        self.set_position_lots(prev_lots)
                        log_message("[HALF EXIT] ⚠️ Failed, restored previous quantity")

                # Define SL price early so it's available for all following checks
                stoplossLTP = float(self.common_avgLTP)
                
                # If current LTP is already at or below SL, force market exit for remaining lots
                try:
                    curr_ltp = getattr(self, 'common_currLTP', None)
                    if curr_ltp is not None and float(curr_ltp) <= float(stoplossLTP):
                        log_message("[HALF EXIT] current LTP below or equal to SL -> forcing market exit for remaining lots")
                        # Ensure CE_PE_exit will target the remaining lots (clear manual squareoff input)
                        try:
                            self.squareoff_lots.setText('')
                        except Exception:
                            pass
                        # Trigger immediate market exit for remaining lots
                        self.CE_PE_exit()
                        return
                except Exception as e:
                    log_message(f"[HALF EXIT] ⚠️ Error checking LTP vs SL: {e}")

                # Place SL-LMT order for remaining qty; use confirmed placement in REAL mode
                self.stoplossLTP = self.round_to_tick(stoplossLTP)
                self.stoploss_entry.setText(str(self.stoplossLTP))

                self.currentLTP()
                if self.ltp_ready:
                    PnL = round((self.common_currLTP - float(self.common_avgLTP)) * int(reduce_lots * self.lot_size), 2)
                    PnlPer = round((((self.common_currLTP - self.common_avgLTP) / self.common_avgLTP) * 100), 2)
                    log_message(f'[EXIT] {self.common_symbol} half exit:')
                    log_message(f'  Exiting: {reduce_lots} lots @ {self.common_currLTP}, Avg: {self.common_avgLTP}')
                    log_message(f'  P&L: ₹{PnL} ({PnlPer}%)')

                # Use the refactored set_stoploss() function
                self.set_stoploss()
                
                # Small delay before placing delivery SL
                QTimer.singleShot(1000, self._place_delivery_sl_after_half)
            
            # Confirm half exit
            if self.PaperTrade_checkbox.isChecked(): # and Config.PAPER_MODE:
                timeout_duration = 1
            else:
                timeout_duration = 30
            self.confirm_orderExit(self.common_symbol, new_lots, callback=on_half_exit_confirmed, timeout=timeout_duration)
            
        except Exception as e:
            log_message(f"[ERROR] half_order_handle: {e}")
            self.timer_CL.start(5000)  # Increased interval to reduce API load

    def _place_delivery_sl_after_half(self):
        """Place stop loss for delivery trade after half exit"""
        try:
            if self.common_orderID is not None:
                log_message(f"Limit SL is placed @ {self.common_avgLTP}, Lots - {self.position_lots} for MM-trade {self.common_symbol} and left for 100% profit.")

                if self.Deli_common_symbol is not None:
                    stoplossLTP2 = float(self.Deli_common_avgLTP)
                    stoplossLTP2 = self.round_to_tick(stoplossLTP2)
                    if self.PaperTrade_checkbox.isChecked():
                        self.Deli_common_orderID = self.multi_place_order('S', 'M', 'NFO', self.Deli_common_symbol, self.Deli_netQty, 'SL-LMT', stoplossLTP2, stoplossLTP2 + 0.5)
                    else:
                        res_deli_sl = self.place_and_confirm('S', 'M', 'NFO', self.Deli_common_symbol, self.Deli_netQty, 'SL-LMT', stoplossLTP2, timeout=30)
                        ordernos = res_deli_sl.get('ordernos', {})
                        if ordernos:
                            self.Deli_common_orderID = ordernos

                    if self.Deli_common_orderID:
                        log_message(f"Limit SL is placed @ {self.Deli_common_avgLTP} for Delivery-trade {self.Deli_common_symbol} and left for big profit.")
            
            self.timer_CL.start(5000)  # Increased interval to reduce API load
            
        except Exception as e:
            log_message(f"[ERROR] _place_delivery_sl_after_half: {e}")
            self.timer_CL.start(5000)  # Increased interval

    def _restart_timer(self):
        """Restart the main timer"""
        try:
            if self.Deli_common_orderID:
                log_message(f"Limit SL is placed @ {self.Deli_common_avgLTP} for Delivery-trade {self.Deli_common_symbol} and left for big profit.")
            self.timer_CL.start(5000)  # Increased interval to reduce API load
        except Exception as e:
            log_message(f"[ERROR] _restart_timer: {e}")

    def _squareOff_handler(self):
        """Square off handler"""
        try:
            self.timer_CL.stop()
            if self.common_token:
                self.CE_PE_exit()
            if self.Deli_common_token:
                self.exitCNC()
            self.timer_CL.start(5000)  # Increased interval
        except Exception as e:
            log_message(f"[ERROR] _squareOff_handler: {e}")

#+++++++++ Symbol and Expiry Handling ++++++++++++++        
    def get_OTM_ITM_day(self):
        """Set OTM/ITM checkbox based on day of week"""
        try:
            today = datetime.datetime.today().strftime('%A')
            OTM_days ={'Wednesday', 'Thursday', 'Friday'}
            ITM_days ={'Monday', 'Tuesday'}
            
            if today in OTM_days:
                self.FirstOTM_checkbox.setChecked(True)
            elif today in ITM_days:
                self.FirstITM_checkbox.setChecked(True)
        except Exception as e:
            log_message(f"[ERROR] get_OTM_ITM_day: {e}")

    def fetch_expiry_dates(self, symbol: str):
        """Fetch expiry dates from NSE"""
        try:
            print("[EXPIRY_DEBUG] Starting fetch_expiry_dates")
            
            # Safety check
            if not hasattr(self, 'ef'):
                print("[EXPIRY_DEBUG] self.ef does not exist, returning empty")
                log_message(f"[EXPIRY] ⚠️ NSE session (self.ef) not initialized yet")
                return []
            
            print("[EXPIRY_DEBUG] self.ef exists, calling fetch_expiries")
            log_message(f"[EXPIRY] Fetching expiry dates for {symbol}")
            raw_expiry_dates = self.ef.fetch_expiries("NIFTY")
            print(f"[EXPIRY_DEBUG] Raw expiry dates: {raw_expiry_dates}")
            log_message(f"[EXPIRY] Raw expiry dates: {raw_expiry_dates}")
            
            today = datetime.datetime.today().date()
            valid_expiry_dates = []

            for dt_str in raw_expiry_dates:
                try:
                    expiry_date = datetime.datetime.strptime(dt_str, '%d-%b-%Y').date()
                    if expiry_date >= today:
                        valid_expiry_dates.append(dt_str)
                except ValueError:
                    log_message(f"[EXPIRY] ⚠️ Invalid date format: {dt_str}")
                    continue

            print(f"[EXPIRY_DEBUG] Valid expiry dates: {valid_expiry_dates}")
            
            # Only update UI if expiry_input exists
            if not hasattr(self, 'expiry_input'):
                print("[EXPIRY_DEBUG] expiry_input not created yet, caching dates")
                log_message(f"[EXPIRY] ⚠️ expiry_input not yet created, caching dates for later")
                self._cached_expiry_dates = valid_expiry_dates
                print(f"[EXPIRY_DEBUG] Cached {len(valid_expiry_dates)} dates")
                return valid_expiry_dates
            
            print("[EXPIRY_DEBUG] expiry_input exists, clearing and populating")
            self.expiry_input.clear()

            if valid_expiry_dates:
                log_message(f"[EXPIRY] ✅ Populated {len(valid_expiry_dates)} expiry dates")
                self.expiry_input.addItems(valid_expiry_dates)
                print(f"[EXPIRY_DEBUG] Added {len(valid_expiry_dates)} items to dropdown")
            else:
                log_message(f"[EXPIRY] ❌ No valid future expiry dates found. Raw dates: {raw_expiry_dates}")
                QMessageBox.warning(self, "Data Fetch Error", "No valid future expiry dates found.")
                print("[EXPIRY_DEBUG] No valid dates found")

            print("[EXPIRY_DEBUG] fetch_expiry_dates completed successfully")
            return valid_expiry_dates

        except Exception as e:
            print(f"[EXPIRY_DEBUG] Exception in fetch_expiry_dates: {e}")
            log_message(f"[EXPIRY] ❌ Error fetching expiry dates: {e}")
            import traceback
            traceback.print_exc()
            return []

    def symbol_changed(self):
        """Handle symbol change event"""
        try:
            selected_symbol = self.symbol_input.currentText().strip()
            self.fetch_expiry_dates(selected_symbol)
            self.expiry_input.setCurrentIndex(0)
        except Exception as e:
            log_message(f"[ERROR] symbol_changed: {e}")

    def logout_all(self):
        """Logout from all FYERS accounts"""
        # Explicitly stop websocket so next login can start fresh without duplicate socket errors.
        if hasattr(self, 'api_master') and self.api_master:
            try:
                self.api_master.close_websocket()
                log_message("[LOGOUT] Websocket closed")
            except Exception as e:
                log_message(f"[LOGOUT] Websocket close warning: {e}")
            finally:
                self.websocket_connected = False
                self._ws_started = False

        for uid, acc in self.accounts.items():
            api = acc['api']
            try:
                resp = api.logout()
                log_message(f"[LOGOUT_OK] {uid} - {resp}")
            except Exception as e:
                log_message(f"[LOGOUT_ERR] {uid}: {e}")

    def reset_core(self):
        """Reset core range with user confirmation"""
        try:
            reply = QMessageBox.question(
                self,
                'Confirm Core Reset',
                'Are you sure you want to reset the core range?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                input_text, ok = QInputDialog.getText(
                    self,
                    'Enter Market Open Value',
                    'Enter market open value (leave empty for default):',
                    QLineEdit.EchoMode.Normal
                )

                if ok:
                    if input_text.strip().isdigit():
                        value = int(input_text.strip())
                        log_message(f"Manual core reset value entered: {value}")
                    else:
                        value = int(self.open_915)
                        log_message(f"Empty or invalid input, using 9:15 candle open @ {value}")

                    self.emit_core_reset(value)
        except Exception as e:
            log_message(f"[ERROR] reset_core: {e}")

    def emit_core_reset(self, value):
        """Emit core reset signal"""
        try:
            if hasattr(self, 'signal_thread'):
                self.signal_thread.core_intc_signal.emit(int(value))
                self.signal_thread.core_reset_signal.emit(value)
                self.core_update_allowed = True
                self.signal_thread.core_update_signal.emit(self.core_update_allowed)
        except Exception as e:
            log_message(f"[ERROR] emit_core_reset: {e}")

    def manual_override(self):
        """Manual override of GANN direction"""
        try:
            self.zone = None
            self.reversal_initialized = True
            direction = self.direction_box.currentText()
            level = float(self.level_box.currentText())
            self.override_gann_direction(direction, level)
        except Exception as e:
            log_message(f"[ERROR] manual_override: {e}")

    def override_gann_direction(self, direction: str, touched_level: float):
        """Override breakout direction"""
        try:
            assert direction in ["up", "down"], "Invalid direction; must be 'up' or 'down'"
            if touched_level not in self.gann_levels:
                log_message(f"[OVERRIDE FAILED] Level {touched_level} not in GANN levels")
                return

            self.current_direction = direction
            self.last_gann_broken = touched_level

            if direction == "up":
                lower = next((lvl for lvl in reversed(self.gann_levels) if lvl < touched_level), None)
                self.reversal_gann_level = lower
                log_message(f"[OVERRIDE] Breakout UP at {touched_level} - Reversal GANN = {lower}")
                self.rev_label.setText(f"Reversal Level:- {self.reversal_gann_level} 🟢, ")

            elif direction == "down":
                upper = next((lvl for lvl in self.gann_levels if lvl > touched_level), None)
                self.reversal_gann_level = upper
                log_message(f"[OVERRIDE] Breakout DOWN at {touched_level} - Reversal GANN = {upper}")
                self.rev_label.setText(f"Reversal Level:- {self.reversal_gann_level} 🔴, ")
        except Exception as e:
            log_message(f"[ERROR] override_gann_direction: {e}")

    def closeEvent(self, a0):
        """Handle window close event - UPDATED with executor cleanup"""
        try:
            if getattr(self, "_ws_started", False) and not getattr(self, "_allow_close", False):
                log_message("[CLEANUP] Close ignored while websocket/session is active")
                a0.ignore()
                return
            event = a0  # Map parameter to local variable for clarity
          # Stop signal thread
            if hasattr(self, 'signal_thread') and self.signal_thread.isRunning():
                self.signal_thread.stop()
            
            # Stop timer thread
            if hasattr(self, 'timer_thread'):
                self.stop_timer_thread()
            if hasattr(self, 'ws_watchdog_timer') and self.ws_watchdog_timer.isActive():
                self.ws_watchdog_timer.stop()
            
            # ✅ ADD: Shutdown thread executor
            if hasattr(self, 'executor'):
                log_message("[CLEANUP] Shutting down thread executor...")
                # ThreadPoolExecutor.shutdown() does not accept a 'timeout' kw on Python 3.11.
                # Call without 'timeout' to wait for worker completion; rely on API worker waitForDone below.
                try:
                    self.executor.shutdown(wait=True)
                    log_message("[CLEANUP] Thread executor shutdown complete")
                except Exception as e:
                    log_message(f"[CLEANUP] Executor shutdown error: {e}")
            
            # Wait for API workers
            if hasattr(self, 'api_threadpool'):
              log_message("[CLEANUP] Waiting for API workers...")
            self.api_threadpool.waitForDone(5000)
            log_message("[CLEANUP] API workers completed")
            
            # Clear caches
            if hasattr(self, 'data_cache'):
                self.data_cache.clear()
            
            # Unsubscribe websocket
            if self.full_tokens and hasattr(self, 'api_master'):
                self.api_master.unsubscribe(self.full_tokens)
            if hasattr(self, 'api_master') and self.api_master:
                try:
                    self.api_master.close_websocket()
                    log_message("[CLEANUP] Websocket closed")
                except Exception as e:
                    log_message(f"[CLEANUP] Websocket close warning: {e}")
                finally:
                    self.websocket_connected = False
                    self._ws_started = False
            
            a0.accept()
        except Exception as e:
            log_message(f"[ERROR] closeEvent: {e}")
            a0.accept()

#++++++++++
    def Action_plan(self):  
        if not hasattr(self, "last_divergence"):
            self.last_divergence = None
            self.divergence_change_time = None   
            self.last_entry = None
            self.entry_change_time = None
            self.last_ce_exit = None
            self.ce_exit_change_time = None
            self.last_pe_exit = None
            self.pe_exit_change_time = None
        if self.act_divergence != self.last_divergence:
            self.divergence_change_time = datetime.datetime.now()
            self.last_divergence = self.act_divergence
        if self.act_entry != self.last_entry:
            self.entry_change_time = datetime.datetime.now()
            self.last_entry = self.act_entry
        if self.act_ce_exit != self.last_ce_exit:
            self.ce_exit_change_time = datetime.datetime.now()
            self.last_ce_exit = self.act_ce_exit
        if self.act_pe_exit != self.last_pe_exit:
            self.pe_exit_change_time = datetime.datetime.now()
            self.last_pe_exit = self.act_pe_exit

          # Pass structured entry data (dict) to the engine. `act_entry_data` may be None.
        entry_payload = getattr(self, 'act_entry_data', None)
        self.act_option_action = self.option_action_engine(
            self.active_order_side if self.active_order_side else None,
            self.position_lots,
            entry_payload,
            self.act_ce_exit,
            self.act_pe_exit,
            self.act_divergence if self.act_divergence else "NEUTRAL",
            self.rsi_30min,
            self.rsi_5min,
            self.prev_rsi_5m
        )
         
        if self.RSI_autoTrade_checkbox.isChecked():
            # Extract quality score from signal data
            quality_score = getattr(self, 'act_entry_data', {}).get('quality_score', 0) if isinstance(getattr(self, 'act_entry_data', None), dict) else 0
            self.execute_option_action(self.act_option_action, self.position_lots, quality_score)
        
        act_current_state ={
            "divergence":self.act_divergence,
            "Entry":self.act_entry,
            "ce_exit":self.act_ce_exit,
            "pe_exit":self.act_pe_exit,
            "action":self.act_option_action
        }

        if act_current_state == self.last_logged_act_state:
            return  # ❌ nothing changed → no action

        if act_current_state != self.last_logged_act_state:
            self.last_logged_act_state = act_current_state.copy()

            msg = (
                "+++++++++++++++++++++++++++++++++++++++\n"
                "NIFTY FUTURES – RSI ANALYSIS\n"
                f"Divergence: {self.act_divergence}\n"
                f"Entry Suggestion: {self.act_entry}\n"
                f"CE: {self.act_ce_exit}\n"
                f"PE: {self.act_pe_exit}\n"
                f"ACTION: {self.act_option_action}\n"
                "+++++++++++++++++++++++++++++++++++++++"
            )

            log_message(msg)
            self.RSI_action_label.setText(f"{self.act_option_action}")
            
            if notification is not None:
                try:
                    notification.notify(title="RSI Alert", message=f"{self.act_option_action}", timeout=5)  # type: ignore[reportOptionalCall]
                except Exception as e:
                    print(f"[WARN] Notification skipped: {e}")
            else:
                print("[WARN] Notification library not available - skipping notification")

    def option_action_engine(
        self,
        position: str | None,
        lots: int,
        entry_signal_data: dict | None,  # Now receives full signal data with quality (or None)
        ce_exit_signal: str | None,
        pe_exit_signal: str | None,
        divergence: str,
        rsi_30m_latest: float,
        rsi_5m_latest: float,
        prev_rsi_5m: float
    ):
        """
        Enhanced structure-aware RSI option trading engine
        Key Improvements:
        1. Quality-based position sizing
        2. Timeout mechanism for armed setups
        3. Divergence validation with structure checks
        4. Time-of-day filters
        5. Re-entry cooldown
        """
        import datetime
        now = datetime.datetime.now()

        # ═══════════════════════════════════════════════
        # TRADING HOURS CHECK
        # ═══════════════════════════════════════════════
        market_open = datetime.time(9, 15)
        market_close = datetime.time(15, 30)
        avoid_start = datetime.time(9, 15)
        avoid_end = datetime.time(9, 20)
        avoid_eod_start = datetime.time(15, 15)

        current_time = now.time()
        # Block trading during volatile opening
        if avoid_start <= current_time < avoid_end:
            return "NO TRADE ⏸️ (Avoiding opening volatility - wait till 9:20 AM)"

        # Block trading near market close
        if current_time >= avoid_eod_start:
            if position in ("CE", "PE"):
                return "EXIT ALL 🚨 (Market closing soon)"
            return "NO TRADE ⏸️ (Too close to market close)"

        # Safety check
        if position not in (None, "CE", "PE"):
            log_message(f"[WARNING] Invalid position: {position}. Resetting to None.")
            position = None

        # ═══════════════════════════════════════════════
        # INITIALIZATION
        # ═══════════════════════════════════════════════
        if not hasattr(self, "prev_rsi_5m"):
            self.prev_rsi_5m = prev_rsi_5m
            self.prev_rsi_30m = rsi_30m_latest
            self.bullish_setup_armed = False
            self.bearish_setup_armed = False
            self.armed_time = None
            self.last_exit_time = None
            self.entry_quality = 0
            return "NO TRADE ⏸️ (Initializing RSI tracking)"

        rsi_5m_change = rsi_5m_latest - prev_rsi_5m
        rsi_30m_change = rsi_30m_latest - self.prev_rsi_30m
        self.prev_rsi_30m = rsi_30m_latest

        # Extract signal data (support None or legacy string payload)
        if isinstance(entry_signal_data, dict):
            entry_signal = entry_signal_data.get("entry_signal")
            signal_strength = entry_signal_data.get("strength")
            quality_score = entry_signal_data.get("quality_score", 0)
        else:
            # Backwards-compatible: caller passed a plain string or None
            entry_signal = entry_signal_data
            signal_strength = None
            quality_score = 0

        # ═══════════════════════════════════════════════
        # RE-ENTRY COOLDOWN (prevent revenge trading)
        # ═══════════════════════════════════════════════
        '''
        COOLDOWN_MINUTES = 15  # Wait 15 mins after exit before re-entering
        if position is None and hasattr(self, "last_exit_time") and self.last_exit_time:
            minutes_since_exit = (now - self.last_exit_time).total_seconds() / 60
            if minutes_since_exit < COOLDOWN_MINUTES:
                remaining = COOLDOWN_MINUTES - minutes_since_exit
                return f"NO TRADE ⏸️ (Cooldown: {remaining:.1f} mins remaining)"
        '''
        # ═══════════════════════════════════════════════
        # MARKET CONTEXT
        # ═══════════════════════════════════════════════
        if not hasattr(self, "rsi_30m_history"):
            self.rsi_30m_history = []

        self.rsi_30m_history.append(rsi_30m_latest)

        market = self.market_mindset_engine(
            now,
            rsi_30m_latest,
            rsi_5m_latest,
            self.rsi_30m_history,
        )
        rsi_slope_30m = market["rsi_30m_slope"]

        # ═══════════════════════════════════════════════
        # HOLD DURATION
        # ═══════════════════════════════════════════════
        hold_duration = 0
        if position in ("CE", "PE") and hasattr(self, "entry_time") and self.entry_time is not None:
            hold_duration = (now - self.entry_time).total_seconds() / 60

        # ═══════════════════════════════════════════════
        # CASE 1: NO POSITION → ENTRY LOGIC
        # ═══════════════════════════════════════════════
        if position is None:
            
            # ─────────────────────────────────────────────
            # ARMED SETUP TIMEOUT CHECK
            # ─────────────────────────────────────────────
            ARM_TIMEOUT_MINUTES = 10  # Disarm if no execution in 10 mins

            if hasattr(self, "armed_time") and self.armed_time:
                time_armed = (now - self.armed_time).total_seconds() / 60
                if time_armed > ARM_TIMEOUT_MINUTES:
                    self.bullish_setup_armed = False
                    self.bearish_setup_armed = False
                    self.armed_time = None
                    log_message("⏰ Armed setup expired - clearing")

            # ─────────────────────────────────────────────
            # ARM PHASE - Quality-Based Arming
            # ─────────────────────────────────────────────
            
            # ARM CE - Only arm STRONG or better signals
            if (entry_signal == "CE Entry Potential" and
                signal_strength in ("EXPLOSIVE", "STRONG", "STRONG_UNCONFIRMED") and
                self.structure_break_up and
                rsi_30m_latest <= 45 and
                45 <= rsi_5m_latest < 58 and
                divergence != "🔴 BEARISH RSI DIVERGENCE (30m)"):
                
                if not self.bullish_setup_armed:
                    self.bullish_setup_armed = True
                    self.armed_time = now
                    self.armed_entry_rsi = rsi_5m_latest
                    self.armed_quality = quality_score
                    
                    current_text = self.Deli_order_label.text()
                    if "🎯 CE Armed" not in current_text:
                        log_message(f"⚡ Bullish Setup ARMED - Quality: {quality_score}, Strength: {signal_strength}")
                        self.Deli_order_label.setText(f"{self.Deli_order_label.text()} | 🎯 CE Armed (Q:{quality_score})")

            # ARM PE - Only arm STRONG or better signals
            if (entry_signal == "PE Entry Potential" and
                signal_strength in ("EXPLOSIVE", "STRONG", "STRONG_UNCONFIRMED") and
                self.structure_break_down and
                rsi_30m_latest >= 55 and
                52 < rsi_5m_latest < 65 and
                divergence != "🟢 BULLISH RSI DIVERGENCE (30m)"):
                
                if not self.bearish_setup_armed:
                    self.bearish_setup_armed = True
                    self.armed_time = now
                    self.armed_entry_rsi = rsi_5m_latest
                    self.armed_quality = quality_score
                    
                    current_text = self.Deli_order_label.text()
                    if "🎯 PE Armed" not in current_text:
                        log_message(f"⚡ Bearish Setup ARMED - Quality: {quality_score}, Strength: {signal_strength}")
                        self.Deli_order_label.setText(f"{self.Deli_order_label.text()} | 🎯 PE Armed (Q:{quality_score})")

            # ─────────────────────────────────────────────
            # ARMED SETUP FADE CHECK (momentum reversal)
            # ─────────────────────────────────────────────
            if self.bullish_setup_armed and hasattr(self, "armed_entry_rsi"):
                rsi_5m_fade = rsi_5m_latest - self.armed_entry_rsi
                if rsi_5m_fade < -5:  # RSI dropped 5 points from armed level
                    log_message(f"🚫 Bullish setup DISARMED - RSI fade: {rsi_5m_fade:.1f}")
                    self.bullish_setup_armed = False
                    self.armed_time = None

            if self.bearish_setup_armed and hasattr(self, "armed_entry_rsi"):
                rsi_5m_fade = self.armed_entry_rsi - rsi_5m_latest
                if rsi_5m_fade < -5:  # RSI rose 5 points from armed level
                    log_message(f"🚫 Bearish setup DISARMED - RSI fade: {rsi_5m_fade:.1f}")
                    self.bearish_setup_armed = False
                    self.armed_time = None

            # ─────────────────────────────────────────────
            # EXECUTE CE - Quality-Based Sizing
            # ─────────────────────────────────────────────
            if entry_signal == "CE Entry Potential":
                
                # Structure check (mandatory)
                if not self.structure_break_up:
                    self.bullish_setup_armed = False
                    return "NO TRADE ❌ (Structure bearish, need bullish break)"
                
                # Divergence filter
                if divergence == "🔴 BEARISH RSI DIVERGENCE (30m)":
                    self.bullish_setup_armed = False
                    return "NO TRADE ❌ (Bearish divergence blocks CE)"
                
                # Quality threshold (skip weak signals)
                if quality_score < 55:
                    return f"NO TRADE ⏸️ (Quality too low: {quality_score})"
                
                # EXPLOSIVE entry (quality 95)
                if signal_strength == "EXPLOSIVE" and self.bullish_setup_armed:
                    self.entry_time = now
                    self.entry_rsi_5m = rsi_5m_latest
                    self.entry_rsi_30m = rsi_30m_latest
                    self.entry_quality = quality_score
                    self.bullish_setup_armed = False
                    self.bearish_setup_armed = False
                    
                    suggested_lots = lots  # Full size
                    return f"ENTER CE 🔥 EXPLOSIVE (Quality: {quality_score}, Lots: {suggested_lots})"
                
                # STRONG entry (quality 70-85)
                elif signal_strength in ("STRONG", "STRONG_UNCONFIRMED") and self.bullish_setup_armed:
                    self.entry_time = now
                    self.entry_rsi_5m = rsi_5m_latest
                    self.entry_rsi_30m = rsi_30m_latest
                    self.entry_quality = quality_score
                    self.bullish_setup_armed = False
                    self.bearish_setup_armed = False
                    
                    # Reduce size if 30m unconfirmed
                    suggested_lots = lots if signal_strength == "STRONG" else lots // 2
                    return f"ENTER CE ✅ STRONG (Quality: {quality_score}, Lots: {suggested_lots})"
                
                # MODERATE entry (quality 55)
                elif signal_strength == "MODERATE" and self.bullish_setup_armed:
                    self.entry_time = now
                    self.entry_rsi_5m = rsi_5m_latest
                    self.entry_rsi_30m = rsi_30m_latest
                    self.entry_quality = quality_score
                    self.bullish_setup_armed = False
                    self.bearish_setup_armed = False
                    
                    suggested_lots = lots // 2  # Half size for moderate
                    return f"ENTER CE ⚠️ MODERATE (Quality: {quality_score}, Lots: {suggested_lots})"
                
                # Setup armed but waiting for momentum
                elif self.bullish_setup_armed:
                    return f"NO TRADE ⏸️ (CE armed, awaiting momentum - Quality: {quality_score})"
                
                return "NO TRADE ⏸️ (CE setup not armed yet)"
            
            # ─────────────────────────────────────────────
            # EXECUTE PE - Quality-Based Sizing
            # ─────────────────────────────────────────────
            elif entry_signal == "PE Entry Potential":
                
                # Structure check (mandatory)
                if not self.structure_break_down:
                    self.bearish_setup_armed = False
                    return "NO TRADE ❌ (Structure bullish, need bearish break)"
                
                # Divergence filter
                if divergence == "🟢 BULLISH RSI DIVERGENCE (30m)":
                    self.bearish_setup_armed = False
                    return "NO TRADE ❌ (Bullish divergence blocks PE)"
                
                # Quality threshold (skip weak signals)
                if quality_score < 55:
                    return f"NO TRADE ⏸️ (Quality too low: {quality_score})"
                
                # EXPLOSIVE entry (quality 95)
                if signal_strength == "EXPLOSIVE" and self.bearish_setup_armed:
                    self.entry_time = now
                    self.entry_rsi_5m = rsi_5m_latest
                    self.entry_rsi_30m = rsi_30m_latest
                    self.entry_quality = quality_score
                    self.bullish_setup_armed = False
                    self.bearish_setup_armed = False
                    
                    suggested_lots = lots  # Full size
                    return f"ENTER PE 🔥 EXPLOSIVE (Quality: {quality_score}, Lots: {suggested_lots})"
                
                # STRONG entry (quality 70-85)
                elif signal_strength in ("STRONG", "STRONG_UNCONFIRMED") and self.bearish_setup_armed:
                    self.entry_time = now
                    self.entry_rsi_5m = rsi_5m_latest
                    self.entry_rsi_30m = rsi_30m_latest
                    self.entry_quality = quality_score
                    self.bullish_setup_armed = False
                    self.bearish_setup_armed = False
                    
                    # Reduce size if 30m unconfirmed
                    suggested_lots = lots if signal_strength == "STRONG" else lots // 2
                    return f"ENTER PE ✅ STRONG (Quality: {quality_score}, Lots: {suggested_lots})"
                
                # MODERATE entry (quality 55)
                elif signal_strength == "MODERATE" and self.bearish_setup_armed:
                    self.entry_time = now
                    self.entry_rsi_5m = rsi_5m_latest
                    self.entry_rsi_30m = rsi_30m_latest
                    self.entry_quality = quality_score
                    self.bullish_setup_armed = False
                    self.bearish_setup_armed = False
                    
                    suggested_lots = lots // 2  # Half size for moderate
                    return f"ENTER PE ⚠️ MODERATE (Quality: {quality_score}, Lots: {suggested_lots})"
                
                # Setup armed but waiting for momentum
                elif self.bearish_setup_armed:
                    return f"NO TRADE ⏸️ (PE armed, awaiting momentum - Quality: {quality_score})"
                
                return "NO TRADE ⏸️ (PE setup not armed yet)"
            
            # ─────────────────────────────────────────────
            # DIVERGENCE ENTRIES (with structure validation)
            # ─────────────────────────────────────────────
            elif divergence == "🟢 BULLISH RSI DIVERGENCE (30m)":
                
                # MUST have bullish structure OR neutral structure
                if self.structure_break_down:  # Bearish structure blocks bullish div
                    return "NO TRADE ❌ (Bullish divergence, but structure is bearish)"
                
                # RSI must be in valid entry zone
                if not (40 <= rsi_5m_latest < 60):
                    return f"NO TRADE ⏸️ (Divergence present but RSI @ {rsi_5m_latest:.1f} outside zone)"
                
                # Need upward momentum confirmation
                if rsi_5m_change > 1 and rsi_30m_change >= 0:
                    self.entry_time = now
                    self.entry_rsi_5m = rsi_5m_latest
                    self.entry_rsi_30m = rsi_30m_latest
                    self.entry_quality = 75  # Divergence = moderate quality
                    self.bullish_setup_armed = False
                    self.bearish_setup_armed = False
                    
                    suggested_lots = lots // 2  # Conservative sizing for divergence
                    return f"ENTER CE 🔄 DIVERGENCE (RSI5m: {rsi_5m_latest:.1f}, Lots: {suggested_lots})"
                
                return "NO TRADE ⏸️ (Bullish divergence, awaiting confirmation)"
            
            elif divergence == "🔴 BEARISH RSI DIVERGENCE (30m)":
                
                # MUST have bearish structure OR neutral structure
                if self.structure_break_up:  # Bullish structure blocks bearish div
                    return "NO TRADE ❌ (Bearish divergence, but structure is bullish)"
                
                # RSI must be in valid entry zone
                if not (50 < rsi_5m_latest <= 70):
                    return f"NO TRADE ⏸️ (Divergence present but RSI @ {rsi_5m_latest:.1f} outside zone)"
                
                # Need downward momentum confirmation
                if rsi_5m_change < -1 and rsi_30m_change <= 0:
                    self.entry_time = now
                    self.entry_rsi_5m = rsi_5m_latest
                    self.entry_rsi_30m = rsi_30m_latest
                    self.entry_quality = 75  # Divergence = moderate quality
                    self.bullish_setup_armed = False
                    self.bearish_setup_armed = False
                    
                    suggested_lots = lots // 2  # Conservative sizing for divergence
                    return f"ENTER PE 🔄 DIVERGENCE (RSI5m: {rsi_5m_latest:.1f}, Lots: {suggested_lots})"
                
                return "NO TRADE ⏸️ (Bearish divergence, awaiting confirmation)"
            
            # No valid entry condition
            return "NO TRADE ⏸️ (No valid entry setup)"

        # ════════════════════════════════════════════════════════════════════════
        # CASE 2: HOLDING CE POSITION - EXIT LOGIC
        # ════════════════════════════════════════════════════════════════════════
        
        elif position == "CE":
            
            # ─────────────────────────────────────────────────────────────────────
            # 🔴 PRIORITY 0: Time-based forced exit
            # ─────────────────────────────────────────────────────────────────────
            
            if hold_duration > 5:
                # Check for significant momentum fade
                if hasattr(self, 'entry_rsi_5m'):
                    rsi_5m_fade = rsi_5m_latest - self.entry_rsi_5m
                    if rsi_5m_fade < -10:
                        self._clear_entry_data()
                        return f"EXIT FULL CE 🚨 (5 min+ hold, momentum faded {rsi_5m_fade:.0f} pts (Priority 0))"
            
            if hold_duration > 15:
                # Check for 30m bias flip
                if hasattr(self, 'entry_rsi_30m'):
                    if self.entry_rsi_30m < 40 and rsi_30m_latest > 60:
                        self._clear_entry_data()
                        return f"EXIT FULL CE 🚨 (30m+ hold, 30m RSI flipped {self.entry_rsi_30m:.0f}→{rsi_30m_latest:.0f} (Priority 0))"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🔴 PRIORITY 1: Extreme 5-minute RSI
            # ─────────────────────────────────────────────────────────────────────
            
            '''if rsi_5m_latest > 80:
                self._clear_entry_data()
                return f"EXIT FULL CE 🚨 (5m RSI extreme: {rsi_5m_latest:.1f})"
            '''
            if rsi_5m_latest > 80:
                # Case 1: Higher TF still bullish → DO NOT EXIT
                if rsi_30m_latest > self.entry_rsi_30m and rsi_30m_latest > 50:
                    return "HOLD CE 🔥 (5m RSI strong, 30m rising)"
                
                # Case 2: 5m RSI rolling over → EXIT
                if rsi_5m_change < -5:
                    self._clear_entry_data()
                    return f"EXIT FULL CE 🚨 (5m RSI rollover from extreme: {rsi_5m_latest:.1f} (Priority 1))"
                
                # Case 3: No momentum loss yet → partial only
                exit_qty = self._calculate_exit_qty(lots, lots - 1) # if lots > 2 else 1)
                return f"REDUCE CE ⚠️ (Exit {exit_qty} lots – 5m RSI extreme, booking profits  (Priority 1))"

            
            # ─────────────────────────────────────────────────────────────────────
            # 🔴 PRIORITY 2: Sharp reversal from overbought
            # ─────────────────────────────────────────────────────────────────────
            
            if prev_rsi_5m > 75 and rsi_5m_change < -15:
                old_rsi = prev_rsi_5m
                self._clear_entry_data()
                return f"EXIT FULL CE 🚨 (5m RSI reversal: {old_rsi:.1f} → {rsi_5m_latest:.1f} (Priority 2))"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 3: Very overbought - partial exit
            # ─────────────────────────────────────────────────────────────────────
            
            if rsi_5m_latest > 75 and rsi_5m_change < -3:
                exit_qty = self._calculate_exit_qty(lots, 2)
                return f"REDUCE CE ⚠️ (Exit {exit_qty} lots – 5m RSI {rsi_5m_latest:.1f} (Priority 3))"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 4: Duration + momentum fade
            # ─────────────────────────────────────────────────────────────────────
            
            if hold_duration > 20 and hasattr(self, 'entry_rsi_5m'):
                if self.entry_rsi_5m > 60 and rsi_5m_latest < 50:
                    exit_qty = self._calculate_exit_qty(lots, 2)
                    return f"REDUCE CE ⏰ (Exit {exit_qty} lots – {hold_duration:.0f}min hold, 5m RSI fading (Priority 4))"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 5: Both timeframes overbought
            # ─────────────────────────────────────────────────────────────────────
            
            if rsi_30m_latest > 65 and rsi_5m_latest > 70 and rsi_5m_change < 0:
                exit_qty = self._calculate_exit_qty(lots, 2)
                return f"REDUCE CE ⚠️ (Exit {exit_qty} lots – both timeframes overbought) (Priority 5)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 6: Opposite direction signal (PE entry potential)
            # ─────────────────────────────────────────────────────────────────────
            
            if entry_signal == "PE Entry Potential":
                severity = self._assess_reversal_severity(
                    position='CE',
                    divergence=divergence,
                    rsi_30m=rsi_30m_latest,
                    rsi_5m=rsi_5m_latest,
                    opposite_exit=pe_exit_signal or ""
                )
                
                if severity == 5:  # Critical
                    self._clear_entry_data()
                    return "EXIT FULL CE 🚨 (PE entry + bearish divergence) (Priority 6)"
                elif severity == 4:  # High
                    exit_qty = self._calculate_exit_qty(lots, 3)
                    return f"REDUCE CE ⚠️ (Exit {exit_qty} lots – strong bearish momentum) (Priority 6)"
                elif severity == 3:  # Medium
                    exit_qty = self._calculate_exit_qty(lots, 2)
                    return f"REDUCE CE ⚠️ (Exit {exit_qty} lots – momentum shifting) (Priority 6)"
                elif severity >= 1:  # Low
                    exit_qty = self._calculate_exit_qty(lots, 1)
                    return f"REDUCE CE ⚠️ (Exit {exit_qty} lots – PE entry signal) (Priority 6)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🔴 PRIORITY 7: Strong exit signals
            # ─────────────────────────────────────────────────────────────────────
            
            if ce_exit_signal == "Exit CE: Bearish divergence":
                self._clear_entry_data()
                return "EXIT FULL CE 🚨 (Bearish divergence) (Priority 7)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 8: Overbought warning
            # ─────────────────────────────────────────────────────────────────────
            
            if ce_exit_signal == "Exit CE: Overbought":
                if divergence == "🔴 BEARISH RSI DIVERGENCE (30m)":
                    self._clear_entry_data()
                    return "EXIT FULL CE 🚨 (Overbought + divergence) (Priority 8)"
                exit_qty = self._calculate_exit_qty(lots, 3)
                return f"REDUCE CE ➖ (Exit {exit_qty} lots – overbought) (Priority 8)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 9: Short-term exhaustion
            # ─────────────────────────────────────────────────────────────────────
            
            if ce_exit_signal == "Exit CE: Short-term exhaustion":
                # If both sides exhausted, it's consolidation - hold
                if pe_exit_signal == "Exit PE: Short-term exhaustion":
                    return "HOLD CE 🟢 (Both sides exhausted – consolidation) (Priority 9)"
                exit_qty = self._calculate_exit_qty(lots, 2)
                return f"REDUCE CE ➖ (Exit {exit_qty} lots – momentum slowing) (Priority 9)"
            
            # ─────────────────────────────────────────────────────────────────────
            # ⚠️ PRIORITY 10: Bounce risk warning
            # ─────────────────────────────────────────────────────────────────────
            
            if pe_exit_signal == "Exit PE: Oversold / Bounce likely":
                exit_qty = self._calculate_exit_qty(lots, 2)
                return f"REDUCE CE ⚠️ (Exit {exit_qty} lots – bounce risk) (Priority 10)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟢 PRIORITY 11: Target 1 level reachced
            # ─────────────────────────────────────────────────────────────────────

            if float(self.intc_value) > float(self.T1Level) and self.bigProfit_flag:
                exit_qty = self._calculate_exit_qty(lots, 2)
                return f"REDUCE CE 🟢 (Exit {exit_qty} lots – Target 1 reached) (Priority 11)"
    
            # ─────────────────────────────────────────────────────────────────────
            # 🔴 PRIORITY 12: Premium loss 15% OR (Underlying drop 40 pts + RSI fall 2) → Fail-safe
            # ─────────────────────────────────────────────────────────────────────
            try:
                # Check premium loss first (simpler and faster)
                if self.common_avgLTP > 0 and self.common_currLTP > 0:
                    premium_loss_pct = ((self.common_avgLTP - self.common_currLTP) / self.common_avgLTP) * 100
                    if premium_loss_pct >= Config.AUTO_SL_PERCENT:
                        # Schedule auto-SL placement if not already placed
                        try:
                            # ✅ CRITICAL: Check both flag AND existing SL status to prevent duplicates
                            existing_sl = self.position_orders.get(self.common_symbol, {}).get('stoploss')
                            sl_already_pending = existing_sl and existing_sl.get('status') == 'PENDING'
                            
                            if not getattr(self, 'SL_order_flag', False) and not sl_already_pending:
                                if hasattr(self, 'stoploss_entry'):
                                    self.stoploss_entry.setText(f"{Config.AUTO_SL_PERCENT}%")
                                log_message(f"[AUTO-SL] Scheduling set_stoploss() before fail-safe exit (premium loss {premium_loss_pct:.1f}%) for {getattr(self,'common_symbol',None)}")
                                QTimer.singleShot(0, self.set_stoploss)
                            elif sl_already_pending:
                                log_message(f"[AUTO-SL] Stoploss already PENDING at broker - skipping duplicate (premium loss {premium_loss_pct:.1f}%)")
                        except Exception as e:
                            log_message(f"[ERROR] scheduling auto-SL: {e}")
                        # Force full exit
                        self._clear_entry_data()
                        return f"EXIT FULL CE 🚨 (Premium loss {premium_loss_pct:.1f}% >= {Config.AUTO_SL_PERCENT}% → Priority 12)"
                
                # Check underlying + RSI combo
                if hasattr(self, 'entry_underlying_at_buy') and self.entry_underlying_at_buy is not None:
                    entry_under = float(self.entry_underlying_at_buy)
                    curr_under = float(self.intc_value)
                    under_drop = entry_under - curr_under
                    rsi_fall = (self.entry_rsi_5m - rsi_5m_latest) if hasattr(self, 'entry_rsi_5m') else 0
                    if under_drop >= Config.AUTO_EXIT_UNDERLYING_DROP_PTS and rsi_fall >= Config.AUTO_EXIT_RSI_FALL:
                        # Schedule auto-SL placement if not already placed
                        try:
                            # ✅ CRITICAL: Check both flag AND existing SL status to prevent duplicates
                            existing_sl = self.position_orders.get(self.common_symbol, {}).get('stoploss')
                            sl_already_pending = existing_sl and existing_sl.get('status') == 'PENDING'
                            
                            if not getattr(self, 'SL_order_flag', False) and not sl_already_pending:
                                if hasattr(self, 'stoploss_entry'):
                                    self.stoploss_entry.setText(f"{Config.AUTO_SL_PERCENT}%")
                                log_message(f"[AUTO-SL] Scheduling set_stoploss() before fail-safe exit (underlying+RSI) for {getattr(self,'common_symbol',None)}")
                                QTimer.singleShot(0, self.set_stoploss)
                            elif sl_already_pending:
                                log_message(f"[AUTO-SL] Stoploss already PENDING at broker - skipping duplicate (underlying {under_drop:.0f}pts + RSI {rsi_fall:.1f})")
                        except Exception as e:
                            log_message(f"[ERROR] scheduling auto-SL: {e}")
                        # Force full exit
                        self._clear_entry_data()
                        return f"EXIT FULL CE 🚨 (Underlying dropped {under_drop:.0f} pts + RSI fell {rsi_fall:.1f}  → Priority 12)"
            except Exception:
                pass

            # All checks passed - hold position
            return "HOLD CE ✅ (Trend intact)"

        # ══════════════════════════════════════════════════════════════════════
        # CASE 3: HOLDING PE POSITION - EXIT LOGIC
        # ════════════════════════════════════════════════════════════════════════
        
        elif position == "PE":
            
            # ─────────────────────────────────────────────────────────────────────
            # 🔴 PRIORITY 0: Time-based forced exit
            # ─────────────────────────────────────────────────────────────────────
            
            if hold_duration > 5:
                # Check for significant momentum fade (reversed for PE)
                if hasattr(self, 'entry_rsi_5m'):
                    rsi_5m_fade = self.entry_rsi_5m - rsi_5m_latest  # Reversed
                    if rsi_5m_fade < -20:
                        self._clear_entry_data()
                        return f"EXIT FULL PE 🚨 (30min+ hold, momentum faded {rsi_5m_fade:.0f} pts) (Priority 0)"
            
            if hold_duration > 15:
                # Check for 30m bias flip
                if hasattr(self, 'entry_rsi_30m'):
                    if self.entry_rsi_30m > 60 and rsi_30m_latest < 40:
                        self._clear_entry_data()
                        return f"EXIT FULL PE 🚨 (30m+ hold, 30m RSI flipped {self.entry_rsi_30m:.0f}→{rsi_30m_latest:.0f}) (Priority 0)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🔴 PRIORITY 1: Extreme 5-minute RSI
            # ─────────────────────────────────────────────────────────────────────
            
            '''if rsi_5m_latest < 20:
                self._clear_entry_data()
                return f"EXIT FULL PE 🚨 (5m RSI extreme: {rsi_5m_latest:.1f})"
            '''
            if rsi_5m_latest < 20:
                # Case 1: Higher TF still bearish → DO NOT EXIT
                if rsi_30m_latest < self.entry_rsi_30m and rsi_30m_latest < 50:
                    return "HOLD PE 🔥 (5m RSI strong, 30m falling) (Priority 1)"

                # Case 2: 5m RSI rolling over from oversold → EXIT
                if rsi_5m_change > 5:
                    self._clear_entry_data()
                    return f"EXIT FULL PE 🚨 (5m RSI rollover from extreme: {rsi_5m_latest:.1f}) (Priority 1)"

                # Case 3: Extreme but not rolling → partial only
                exit_qty = self._calculate_exit_qty(lots, lots - 1) # if lots > 2 else 1)
                return f"REDUCE PE ⚠️ (Exit {exit_qty} lots – 5m RSI extreme, booking profits) (Priority 1)"

            # ─────────────────────────────────────────────────────────────────────
            # 🔴 PRIORITY 2: Sharp reversal from oversold
            # ─────────────────────────────────────────────────────────────────────
            
            if prev_rsi_5m < 25 and rsi_5m_change > 15:
                old_rsi = prev_rsi_5m
                self._clear_entry_data()
                return f"EXIT FULL PE 🚨 (5m RSI reversal: {old_rsi:.1f} → {rsi_5m_latest:.1f}) (Priority 2)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 3: Very oversold - partial exit
            # ─────────────────────────────────────────────────────────────────────
            
            if rsi_5m_latest < 25 and rsi_5m_change > 3:
                exit_qty = self._calculate_exit_qty(lots, 2)
                return f"REDUCE PE ⚠️ (Exit {exit_qty} lots – 5m RSI {rsi_5m_latest:.1f}) (Priority 3)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 4: Duration + momentum fade
            # ─────────────────────────────────────────────────────────────────────
            
            if hold_duration > 20 and hasattr(self, 'entry_rsi_5m'):
                if self.entry_rsi_5m < 40 and rsi_5m_latest > 50:
                    exit_qty = self._calculate_exit_qty(lots, 2)
                    return f"REDUCE PE ⏰ (Exit {exit_qty} lots – {hold_duration:.0f}min hold, 5m RSI rising) (Priority 4)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 5: Both timeframes oversold
            # ─────────────────────────────────────────────────────────────────────
            
            if rsi_30m_latest < 35 and rsi_5m_latest < 30 and rsi_5m_change > 0:
                exit_qty = self._calculate_exit_qty(lots, 2)
                return f"REDUCE PE ⚠️ (Exit {exit_qty} lots – both timeframes oversold) (Priority 5)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 6: Opposite direction signal (CE entry potential)
            # ─────────────────────────────────────────────────────────────────────
            
            if entry_signal == "CE Entry Potential":
                severity = self._assess_reversal_severity(
                    position='PE',
                    divergence=divergence,
                    rsi_30m=rsi_30m_latest,
                    rsi_5m=rsi_5m_latest,
                    opposite_exit=ce_exit_signal or ""
                )
                
                if severity == 5:  # Critical
                    self._clear_entry_data()
                    return "EXIT FULL PE 🚨 (CE entry + bullish divergence) (Priority 6)"
                elif severity == 4:  # High
                    exit_qty = self._calculate_exit_qty(lots, 3)
                    return f"REDUCE PE ⚠️ (Exit {exit_qty} lots – strong bullish momentum) (Priority 6)"
                elif severity == 3:  # Medium
                    exit_qty = self._calculate_exit_qty(lots, 2)
                    return f"REDUCE PE ⚠️ (Exit {exit_qty} lots – momentum shifting) (Priority 6)"
                elif severity >= 1:  # Low
                    exit_qty = self._calculate_exit_qty(lots, 1)
                    return f"REDUCE PE ⚠️ (Exit {exit_qty} lots – CE entry signal) (Priority 6)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🔴 PRIORITY 7: Strong exit signals
            # ─────────────────────────────────────────────────────────────────────
            
            if pe_exit_signal == "Exit PE: Bullish divergence":
                self._clear_entry_data()
                return "EXIT FULL PE 🚨 (Bullish divergence) (Priority 7)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 8: Oversold warning
            # ─────────────────────────────────────────────────────────────────────
            
            if pe_exit_signal == "Exit PE: Oversold / Bounce likely":
                if divergence == "🟢 BULLISH RSI DIVERGENCE (30m)":
                    self._clear_entry_data()
                    return "EXIT FULL PE 🚨 (Oversold + divergence) (Priority 8)"
                exit_qty = self._calculate_exit_qty(lots, 3)
                return f"REDUCE PE ➖ (Exit {exit_qty} lots – oversold) (Priority 8)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟡 PRIORITY 9: Short-term exhaustion
            # ─────────────────────────────────────────────────────────────────────
            
            if pe_exit_signal == "Exit PE: Short-term exhaustion":
                # If both sides exhausted, it's consolidation - hold
                if ce_exit_signal == "Exit CE: Short-term exhaustion":
                    return "HOLD PE 🟢 (Both sides exhausted – consolidation) (Priority 9)"
                exit_qty = self._calculate_exit_qty(lots, 2)
                return f"REDUCE PE ➖ (Exit {exit_qty} lots – momentum slowing) (Priority 9)"
            
            # ─────────────────────────────────────────────────────────────────────
            # 🟢 PRIORITY 10: CE overbought (supportive for PE)
            # ─────────────────────────────────────────────────────────────────────
            
            if ce_exit_signal == "Exit CE: Overbought":
                return "HOLD PE 🟢 (Upside stretched) (Priority 10)"

            # ─────────────────────────────────────────────────────────────────────
            # 🟢 PRIORITY 11: Target 1 level reachced
            # ─────────────────────────────────────────────────────────────────────

            if float(self.intc_value) < float(self.T1Level) and self.bigProfit_flag:
                exit_qty = self._calculate_exit_qty(lots, 2)
                return f"REDUCE PE 🟢 (Exit {exit_qty} lots – Target 1 reached) (Priority 11)"

            # ─────────────────────────────────────────────────────────────────────
            # 🔴 PRIORITY 12: Premium loss 15% OR (Underlying move 40 pts + RSI move 2) → Fail-safe
            # ─────────────────────────────────────────────────────────────────────
            try:
                # Check premium loss first (simpler and faster)
                if self.common_avgLTP > 0 and self.common_currLTP > 0:
                    premium_loss_pct = ((self.common_avgLTP - self.common_currLTP) / self.common_avgLTP) * 100
                    if premium_loss_pct >= Config.AUTO_SL_PERCENT:
                        # Schedule auto-SL placement if not already placed
                        try:
                            # ✅ CRITICAL: Check both flag AND existing SL status to prevent duplicates
                            existing_sl = self.position_orders.get(self.common_symbol, {}).get('stoploss')
                            sl_already_pending = existing_sl and existing_sl.get('status') == 'PENDING'
                            
                            if not getattr(self, 'SL_order_flag', False) and not sl_already_pending:
                                if hasattr(self, 'stoploss_entry'):
                                    self.stoploss_entry.setText(f"{Config.AUTO_SL_PERCENT}%")
                                log_message(f"[AUTO-SL] Scheduling set_stoploss() before fail-safe exit (premium loss {premium_loss_pct:.1f}%) for {getattr(self,'common_symbol',None)}")
                                QTimer.singleShot(0, self.set_stoploss)
                            elif sl_already_pending:
                                log_message(f"[AUTO-SL] Stoploss already PENDING at broker - skipping duplicate (premium loss {premium_loss_pct:.1f}%)")
                        except Exception as e:
                            log_message(f"[ERROR] scheduling auto-SL: {e}")
                        # Force full exit
                        self._clear_entry_data()
                        return f"EXIT FULL PE 🚨 (Premium loss {premium_loss_pct:.1f}% >= {Config.AUTO_SL_PERCENT}% → Priority 12)"
                
                # Check underlying + RSI combo
                if hasattr(self, 'entry_underlying_at_buy') and self.entry_underlying_at_buy is not None:
                    entry_under = float(self.entry_underlying_at_buy)
                    curr_under = float(self.intc_value)
                    under_move = curr_under - entry_under
                    rsi_move = (rsi_5m_latest - self.entry_rsi_5m) if hasattr(self, 'entry_rsi_5m') else 0
                    if under_move >= Config.AUTO_EXIT_UNDERLYING_DROP_PTS and rsi_move >= Config.AUTO_EXIT_RSI_FALL:
                        # Schedule auto-SL placement if not already placed
                        try:
                            # ✅ CRITICAL: Check both flag AND existing SL status to prevent duplicates
                            existing_sl = self.position_orders.get(self.common_symbol, {}).get('stoploss')
                            sl_already_pending = existing_sl and existing_sl.get('status') == 'PENDING'
                            
                            if not getattr(self, 'SL_order_flag', False) and not sl_already_pending:
                                if hasattr(self, 'stoploss_entry'):
                                    self.stoploss_entry.setText(f"{Config.AUTO_SL_PERCENT}%")
                                log_message(f"[AUTO-SL] Scheduling set_stoploss() before fail-safe exit (underlying+RSI) for {getattr(self,'common_symbol',None)}")
                                QTimer.singleShot(0, self.set_stoploss)
                            elif sl_already_pending:
                                log_message(f"[AUTO-SL] Stoploss already PENDING at broker - skipping duplicate (underlying {under_move:.0f}pts + RSI {rsi_move:.1f})")
                        except Exception as e:
                            log_message(f"[ERROR] scheduling auto-SL: {e}")
                        # Force full exit
                        self._clear_entry_data()
                        return f"EXIT FULL PE 🚨 (Underlying moved {under_move:.0f} pts adverse + RSI moved {rsi_move:.1f} → Priority 12)"
            except Exception:
                pass


            # All checks passed - hold position
            return "HOLD PE ✅ (Trend intact)"
        
        # Unknown position type
        return "INVALID STATE ❌"
 
    def execute_option_action(self, action_signal: str, target_lots: int = 1, quality_score: int = 0):
        """
        Execute trading action based on RSI signal with quality-based lot sizing.
        
        Args:
            action_signal: Signal string (e.g., 'ENTER CE 🔥 EXPLOSIVE')
            target_lots: Base lot number from GUI
            quality_score: Quality score (0-95) for granular lot scaling
        """

        #log_message(f"[RSI AUTO] 🧠 Action Signal: {action_signal} | Quality: {quality_score}")

        # ❌ Hard safety filter
        if any(x in action_signal for x in ["WAIT", "NO TRADE", "HOLD"]):
            return

        # ==============================
        # ENTER CE (Quality-Based Lot Scaling)
        # ==============================
        if action_signal.startswith("ENTER CE") and self.active_order_side == None:
            # Granular lot sizing based on quality score
            if quality_score >= 90:
                lots_to_use = int(target_lots)  # EXPLOSIVE (Q=95): 100%
                quality_label = "EXPLOSIVE"
            elif quality_score >= 80:
                lots_to_use = int(target_lots)  # STRONG (Q=85): 100%
                quality_label = "STRONG"
            elif quality_score >= 70:
                lots_to_use = max(1, int(target_lots) * 3 // 4)  # STRONG_UNCONFIRMED (Q=70): 75%
                quality_label = "STRONG_UNCONFIRMED"
            elif quality_score >= 55:
                lots_to_use = max(1, int(target_lots) // 2)  # MODERATE (Q=55): 50%
                quality_label = "MODERATE"
            else:
                # WEAK (Q<55): Skip entry
                log_message(f"[RSI AUTO] ⚡ CE signal quality too low (Q={quality_score}): skipping entry")
                return

            self.position_lots = lots_to_use
            self.CE_buy()
            #self.RSI_autoTrade_checkbox.setChecked(False)
            self.active_order_side = "CE"
            pct = int(lots_to_use*100/int(target_lots)) if int(target_lots) > 0 else 0
            log_message(f"[RSI AUTO] ✅ ENTERED CE | Quality={quality_label}(Q:{quality_score}) | Lots={lots_to_use} ({pct}% of base)")
            return

        # ==============================
        # ENTER PE (Quality-Based Lot Scaling)
        # ==============================
        if action_signal.startswith("ENTER PE") and self.active_order_side == None:
            # Granular lot sizing based on quality score
            if quality_score >= 90:
                lots_to_use = int(target_lots)  # EXPLOSIVE (Q=95): 100%
                quality_label = "EXPLOSIVE"
            elif quality_score >= 80:
                lots_to_use = int(target_lots)  # STRONG (Q=85): 100%
                quality_label = "STRONG"
            elif quality_score >= 70:
                lots_to_use = max(1, int(target_lots) * 3 // 4)  # STRONG_UNCONFIRMED (Q=70): 75%
                quality_label = "STRONG_UNCONFIRMED"
            elif quality_score >= 55:
                lots_to_use = max(1, int(target_lots) // 2)  # MODERATE (Q=55): 50%
                quality_label = "MODERATE"
            else:
                # WEAK (Q<55): Skip entry
                log_message(f"[RSI AUTO] ⚡ PE signal quality too low (Q={quality_score}): skipping entry")
                return

            self.position_lots = lots_to_use
            self.PE_buy()
            self.active_order_side = "PE"
            pct = int(lots_to_use*100/int(target_lots)) if int(target_lots) > 0 else 0
            log_message(f"[RSI AUTO] ✅ ENTERED PE | Quality={quality_label}(Q:{quality_score}) | Lots={lots_to_use} ({pct}% of base)")
            return

        # ==============================
        # REDUCE POSITION
        # ==============================
        if action_signal.startswith("REDUCE") and self.active_order_side in ("CE", "PE") and (self.PE_order_flag or self.CE_order_flag):
            # ✅ SAFETY CHECK: Sync position with broker before reducing
            if self.common_symbol:
                try:
                    self._reconcile_position_with_broker(self.common_symbol)
                    log_message(f"[REDUCE] Position synced with broker before executing REDUCE")
                except Exception as e:
                    log_message(f"[REDUCE] Warning: Could not sync position with broker: {e}")
            
            reduce_lots = self.extract_exit_lots(action_signal)
            reduce_lots = min(reduce_lots, max(0, int(self.position_lots) - 1))
            only_one = False  # ✅ Initialize flag
            if reduce_lots == 0:
                only_one = True

            # update tracked lots first (integer math), then perform half/sell handling
            self.half_order_handle(reduce_lots, only_one)

            log_message(f"[RSI AUTO] ➖ REDUCED {reduce_lots} lots | Remaining={self.position_lots} and SL is placed @ {self.common_avgLTP}")
            self.SL_order_flag = True
            self.Target_order_flag = False
            self.CE_order_flag = False
            self.PE_order_flag = False
            self.RSI_autoTrade_checkbox.setChecked(False)
            return

        # ==============================
        # EXIT FULL
        # ==============================
        if action_signal.startswith("EXIT FULL") and self.active_order_side in ("CE", "PE"):
            # ✅ SAFETY CHECK: Sync position with broker before exiting
            if self.common_symbol:
                try:
                    self._reconcile_position_with_broker(self.common_symbol)
                    log_message(f"[EXIT FULL] Position synced with broker before exiting")
                except Exception as e:
                    log_message(f"[EXIT FULL] Warning: Could not sync position with broker: {e}")

            self.CE_PE_exit()
            self.RSI_autoTrade_checkbox.setChecked(False)

            log_message(f"[RSI AUTO] 🚨 EXITED FULL {self.active_order_side}")

            self.active_order_side = None
            self.position_lots = 0
            if self.repeatRSIautoTrade:
                self.RSI_autoTrade_checkbox.setChecked(True)

    def market_mindset_engine(
        self,
        now,
        rsi_30m_latest,
        rsi_5m_latest,
        rsi_30m_history,
        lookback=5
    ):
        """
        Unified Market Mindset Engine
        Uses 30m RSI + slope + ATR regime + 5m RSI
        Builds bias from 9:00 AM onwards
        """
        # ─────────────────────────────────────────────
        # UPDATE MEMORY
        # ─────────────────────────────────────────────
        bias_delta = 0

        # Update only once per 5-min candle
        if self.market_memory["last_update"] == now:
            return None
        self.market_memory["last_update"] = now

        # ─────────────────────────────────────────────
        # 1️⃣ RSI SLOPE (30m)
        # ─────────────────────────────────────────────
        if len(rsi_30m_history) != self._last_30m_rsi_len:
            y = np.array(rsi_30m_history[-lookback:])
            x = np.arange(len(y))
            rsi_slope = np.polyfit(x, y, 1)[0]
            self._last_30m_rsi_len = len(rsi_30m_history)
        else:
            rsi_slope = 0.0  # no new information

        # ─────────────────────────────────────────────
        # 2️⃣ ATR REGIME
        # ─────────────────────────────────────────────
        if Config.trend_day:
            atr_regime = "TREND"
        elif Config.range_day:
            atr_regime = "RANGE"
            bias_delta *= 0.5
        else:
            atr_regime = "NEUTRAL"

        # ─────────────────────────────────────────────
        # 3️⃣ RSI STATES
        # ─────────────────────────────────────────────
        # 30m RSI state (intent)
        if rsi_30m_latest < 40:
            rsi30_state = "STRONG_BEAR"
        elif rsi_30m_latest < 45:
            rsi30_state = "BEAR"
        elif rsi_30m_latest < 55:
            rsi30_state = "NEUTRAL"
        elif rsi_30m_latest < 60:
            rsi30_state = "BULL"
        else:
            rsi30_state = "STRONG_BULL"

        # 5m RSI state (execution)
        if rsi_5m_latest < 40:
            rsi5_state = "WEAK"
        elif rsi_5m_latest < 50:
            rsi5_state = "PULLBACK"
        elif rsi_5m_latest < 60:
            rsi5_state = "MOMENTUM"
        else:
            rsi5_state = "EXPLOSIVE"

        # ─────────────────────────────────────────────
        # 4️⃣ BIAS UPDATE LOGIC
        # ─────────────────────────────────────────────

        # 30m RSI intent
        if rsi30_state in ("STRONG_BEAR", "BEAR"):
            bias_delta -= 2
        elif rsi30_state in ("STRONG_BULL", "BULL"):
            bias_delta += 2

        # RSI slope confirmation
        if rsi_slope > 0.20:
            bias_delta += 1
        elif rsi_slope < -0.20:
            bias_delta -= 1

        # Flat RSI penalty (theta trap)
        if abs(rsi_slope) < 0.05 and atr_regime != "TREND":
            bias_delta -= 1

        # ATR expansion
        if atr_regime == "TREND":
            bias_delta *= 1.5
        elif atr_regime == "RANGE":
            bias_delta *= 0.5

        # 5m execution pressure
        if rsi5_state == "EXPLOSIVE":
            bias_delta += 1
        elif rsi5_state == "WEAK":
            bias_delta -= 1

        # ✅ UPDATE MEMORY (CRITICAL)
        self.market_memory["bias_score"] += bias_delta
        self.market_memory["bias_score"] = max(
            -8, min(8, self.market_memory["bias_score"])
        )

        score = self.market_memory["bias_score"]

        # ─────────────────────────────────────────────
        # BUYER SAFETY: DECAY / RESET LOGIC
        # ─────────────────────────────────────────────
        # 1️⃣ Regime flip protection (range = theta danger)
        if atr_regime == "RANGE":
            self.market_memory["bias_score"] *= 0.7

        # 2️⃣ Trend exhaustion protection
        if abs(score) >= 6 and abs(rsi_slope) < 0.05:
            self.market_memory["bias_score"] *= 0.5

        # ─────────────────────────────────────────────
        # 5️⃣ MARKET MINDSET OUTPUT
        # ─────────────────────────────────────────────
        score = self.market_memory["bias_score"]

        if score <= -6:
            mindset = "STRONG_BEARISH"
        elif score <= -3:
            mindset = "BEARISH"
        elif score >= 6:
            mindset = "STRONG_BULLISH"
        elif score >= 3:
            mindset = "BULLISH"
        else:
            mindset = "NEUTRAL"

        # ─────────────────────────────────────────────
        # 6️⃣ LIVE LABELS (UI)
        # ─────────────────────────────────────────────
        if rsi_slope > 0.08:
            slope_label = "RSI Slope ↗️ (Up Impulse)"
            self.last_rsi_impulse_direction = "UP"

        elif rsi_slope < -0.08:
            slope_label = "RSI Slope ↘️ (Down Impulse)"
            self.last_rsi_impulse_direction = "DOWN"

        elif rsi_30m_latest < 40:
            slope_label = "RSI Flat (Bearish Absorption)"

        elif rsi_30m_latest > 60:
            slope_label = "RSI Flat (Bullish Absorption)"

        else:
            slope_label = "RSI Flat (Balance)"

        colored_slope = self.get_slope_html(slope_label)

        self.market_mindset_label.setTextFormat(Qt.TextFormat.RichText)
        self.market_mindset_label.setText(
            f"{mindset} | {colored_slope} | ATR: {atr_regime}"
        )

        current_status = f"{mindset} | {slope_label} | ATR: {atr_regime}"

        # Update only if something changed
        if current_status != getattr(self, "_last_market_status", None):
            self.market_mindset_label.setText(current_status)
            log_message(current_status)   # 👈 log ONLY on change
            self._last_market_status = current_status


        # ─────────────────────────────────────────────
        # 7️⃣ RETURN STRUCTURED OUTPUT (FOR TRADING LOGIC)
        # ─────────────────────────────────────────────
        return {
            "mindset": mindset,
            "bias_score": score,
            "rsi_30m_state": rsi30_state,
            "rsi_5m_state": rsi5_state,
            "rsi_30m_slope": rsi_slope,
            "atr_regime": atr_regime
        }

    def get_slope_html(self, slope_label):
        if self.last_rsi_impulse_direction == "UP":
            color = "#2ecc71"   # green
        elif self.last_rsi_impulse_direction == "DOWN":
            color = "#e74c3c"   # red
        else:
            color = "#bdc3c7"   # neutral

        return f'<span style="color:{color}; ">{slope_label}</span>'   #font-weight:bold;

    def _clear_entry_data(self):
        """
        ✅ FIX: Clear entry tracking data when exiting positions.
        This ensures clean state for next trade.
        """
        if hasattr(self, 'entry_time'):
            delattr(self, 'entry_time')
        if hasattr(self, 'entry_rsi_5m'):
            delattr(self, 'entry_rsi_5m')
        if hasattr(self, 'entry_rsi_30m'):
            delattr(self, 'entry_rsi_30m')
        self.bullish_setup_armed = False
        self.bearish_setup_armed = False    

    def _calculate_exit_qty(self, total_lots: int, desired_exit: int) -> int:
        """
        ✅ FIX: Safely calculate exit quantity with bounds checking.
        
        Args:
            total_lots: Total lots currently held
            desired_exit: Desired number of lots to exit
        
        Returns:
            Safe exit quantity (always >= 1, <= total_lots)
        
        Examples:
            _calculate_exit_qty(5, 2) -> 2  # Exit 2 lots
            _calculate_exit_qty(1, 2) -> 1  # Can't exit more than held
            _calculate_exit_qty(2, 3) -> 2  # Can't exit more than held
        """
        if total_lots <= 1:
            return 1  # Always exit at least 1 lot
        
        # Exit desired amount, but never more than total-1 (keep at least 1)
        # and never more than total lots
        return min(desired_exit, total_lots - 1, total_lots)

    def _assess_reversal_severity(self, 
        position: str,
        divergence: str,
        rsi_30m: float,
        rsi_5m: float,
        opposite_exit: str
    ) -> int:
        """
        ✅ FIX: Assess severity of reversal signals (simplified logic).
        
        Returns severity score:
            5 = Critical (full exit recommended)
            4 = High (large partial exit)
            3 = Medium (medium partial exit)
            2 = Low (small partial exit)
            1 = Minimal (tiny partial exit)
            0 = None (no action)
        
        Args:
            position: Current position ('CE' or 'PE')
            divergence: Current divergence signal
            rsi_30m: 30-minute RSI
            rsi_5m: 5-minute RSI
            opposite_exit: Exit signal for opposite position
        
        Returns:
            Severity score (0-5)
        """
        severity = 0
        
        if position == 'CE':
            # Check for bearish signals
            if divergence == "🔴 BEARISH RSI DIVERGENCE (30m)":
                severity = max(severity, 5)  # Critical
            
            if rsi_5m < 40:
                severity = max(severity, 4)  # High
            
            if rsi_30m > 60:
                severity = max(severity, 3)  # Medium
            
            if opposite_exit and "exhaustion" in opposite_exit:
                severity = max(severity, 2)  # Low
            
            if severity == 0:
                severity = 1  # Minimal (generic PE entry)
        
        elif position == 'PE':
            # Check for bullish signals
            if divergence == "🟢 BULLISH RSI DIVERGENCE (30m)":
                severity = max(severity, 5)  # Critical
            
            if rsi_5m > 60:
                severity = max(severity, 4)  # High
            
            if rsi_30m < 40:
                severity = max(severity, 3)  # Medium
            
            if opposite_exit and "exhaustion" in opposite_exit:
                severity = max(severity, 2)  # Low
            
            if severity == 0:
                severity = 1  # Minimal (generic CE entry)
        
        return severity

    def extract_exit_lots(self, action_signal: str) -> int:
        import re
        match = re.search(r"Exit (\d+) lots", action_signal)

        return int(match.group(1)) if match else 0

#++++++++++++++++++++++++
    def start_timer_thread(self):
        """Start the unified timer thread"""
        try:
            self.timer_thread = UnifiedTimerThread(self)
            self.timer_thread.second_signal.connect(self.update_time_display)
            self.timer_thread.rsi_signal.connect(self.update_RSI_display)
            self.timer_thread.risDivergence_signal.connect(self.update_RSI_divergence)
            self.timer_thread.suggest_entry_signal.connect(self.update_suggest_entry)
            self.timer_thread.ce_exit_signal.connect(self.update_ce_exit_signal)
            self.timer_thread.pe_exit_signal.connect(self.update_pe_exit_signal)
            self.timer_thread.start()
        except Exception as e:
            log_message(f"[ERROR] start_timer_thread: {e}")

    def stop_timer_thread(self):
        """Stop the timer thread"""
        try:
            if hasattr(self, 'timer_thread') and self.timer_thread:
                self.timer_thread.stop()
        except Exception as e:
            log_message(f"[ERROR] stop_timer_thread: {e}")

    def update_time_display(self, time_string):
        """Update the GUI with the current time"""
        self.time_label.setText("Time : " + time_string)
    
    def update_RSI_display(self, RSI_string):
        """Update the GUI with RSI value and color direction"""
        try:
            '''if Config.trend_day:
                self.Deli_order_label.setText("Trending Day.")
            elif Config.range_day:
                self.Deli_order_label.setText("Range Bound Day.")
            '''

            rsi_30_new, rsi_5_new, rsi_5_prev = map(float, RSI_string.split("/"))

            self.rsi_30min = rsi_30_new
            self.rsi_5min = rsi_5_new   

            # Initialize previous values if not present
            if not hasattr(self, "prev_rsi_30min"):
                self.prev_rsi_30min = rsi_30_new
                self.prev_rsi_5m = rsi_5_new
                self.rsi_5m_last_changed = datetime.datetime.now()  # Initialize timestamp

            # Determine color based on change
            if rsi_30_new > self.prev_rsi_30min:
                self.color_30 = "green"
            elif rsi_30_new < self.prev_rsi_30min:
                self.color_30 = "red"

            if rsi_5_new != self.prev_rsi_5m:  # Check if actually different
                if rsi_5_new > self.prev_rsi_5m:
                    self.color_5 = "green"
                else:
                    self.color_5 = "red"
                self.rsi_5m_last_changed = datetime.datetime.now()  # Record change time

            # Update stored values
            self.prev_rsi_30min = rsi_30_new
            self.prev_rsi_5m = rsi_5_new  # ← Fixed: was rsi_5_prev

            # Calculate time since last change
            if hasattr(self, "rsi_5m_last_changed"):
                time_since_change = datetime.datetime.now() - self.rsi_5m_last_changed
                minutes_ago = int(time_since_change.total_seconds() / 60)
                time_info = f" ({minutes_ago}m ago) || "
            else:
                time_info = ""

            # Update GUI with HTML styling
            self.RSI_label.setText(
                f'RSI: '
                f'<span style="color:{self.color_30}">{rsi_30_new:.2f}</span>'
                f' / '
                f'<span style="color:{self.color_5}">{rsi_5_new:.2f}</span>'
                f'({rsi_5_prev:.2f}){time_info}'
            )

            self.Re_entry_label.setText(f"{Config.Re_entry}")
            
            log_message(f"[RSI] 30min RSI: {self.rsi_30min:.2f}, 5min RSI: {self.rsi_5min:.2f}, Pre.5min RSI: {rsi_5_prev:.2f}, Nifty LTP: {self.intc_value}")
            
        except Exception as e:
            log_message(f"[ERROR] update_RSI_display: {e}")
            import traceback
            log_message(f"[TRACEBACK] {traceback.format_exc()}")
        
    def update_RSI_divergence(self, divergence_string):
        try:
            if divergence_string:
                self.act_divergence = divergence_string
                if self.divergence_change_time:
                    age = self.divergence_age_minutes()
                    self.divergence_label.setText(
                        f"{self.act_divergence} ({age}m ago)"
                    )
                else:
                    self.divergence_label.setText(divergence_string)
            else:
                self.act_divergence = None
                self.divergence_label.setText("")
        except Exception as e:
            log_message(f"[ERROR] update_RSI_divergence: {e}")
            import traceback
            log_message(f"[TRACEBACK] {traceback.format_exc()}")

    def divergence_age_minutes(self):
        if not self.divergence_change_time:
            return None
        age = int((datetime.datetime.now() - self.divergence_change_time).total_seconds() / 60)
        return age

    def update_suggest_entry(self, suggestion_data):
        """Receive structured suggestion dict from timer thread."""
        try:
            if suggestion_data:
                self.act_entry_data = suggestion_data
                self.act_entry = suggestion_data.get("entry_signal")
                # store quality for downstream lot-size decisions
                try:
                    self.quality_score = suggestion_data.get("quality_score")
                except Exception:
                    self.quality_score = None

                # 🚨 Guard against None
                if not self.act_entry:
                    self.entery_suggestion_label.setText("")
                    self.entery_suggestion_label.setStyleSheet("")
                    return

                # 🎨 Color logic
                if "CE" in self.act_entry:
                    self.entery_suggestion_label.setStyleSheet("color: green;")
                elif "PE" in self.act_entry:
                    self.entery_suggestion_label.setStyleSheet("color: red;")

                if self.entry_change_time:
                    age = self.entry_age_minutes()
                    self.entery_suggestion_label.setText(
                        f"{self.act_entry} ({age}m ago)"
                    )
                else:
                    self.entery_suggestion_label.setText(self.act_entry)
                    self.entry_change_time = datetime.datetime.now()

            else:
                self.act_entry_data = None
                self.act_entry = None
                self.entery_suggestion_label.setText("")
                self.entery_suggestion_label.setStyleSheet("")
        except Exception as e:
            log_message(f"[ERROR] update_suggest_entry: {e}")
            import traceback
            log_message(f"[TRACEBACK] {traceback.format_exc()}")

    def entry_age_minutes(self):
        if not self.entry_change_time:
            return None
        age = int((datetime.datetime.now() - self.entry_change_time).total_seconds() / 60)
        return age

    def update_ce_exit_signal(self, ce_exit_signal_string):
        try:
            if ce_exit_signal_string:
                self.act_ce_exit = ce_exit_signal_string

                if self.ce_exit_change_time:
                    age = self.ce_exit_age_minutes()
                    self.CE_exit_signal_label.setText(
                        f"{self.act_ce_exit} ({age}m ago)"
                    )
                else:
                    self.CE_exit_signal_label.setText(ce_exit_signal_string)
                    self.ce_exit_change_time = datetime.datetime.now()
            else:
                self.act_ce_exit = None
                self.CE_exit_signal_label.setText("")
        except Exception as e:
            log_message(f"[ERROR] update_ce_exit_signal: {e}")
            import traceback
            log_message(f"[TRACEBACK] {traceback.format_exc()}")        

    def ce_exit_age_minutes(self):
        if not self.ce_exit_change_time:
            return None
        age = int((datetime.datetime.now() - self.ce_exit_change_time).total_seconds() / 60)
        return age

    def update_pe_exit_signal(self, pe_exit_signal_string):
        try:
            if pe_exit_signal_string:
                self.act_pe_exit = pe_exit_signal_string
                if self.pe_exit_change_time:
                    age = self.pe_exit_age_minutes()
                    self.PE_exit_signal_label.setText(
                        f"{self.act_pe_exit} ({age}m ago)"
                    )
                else:
                    self.PE_exit_signal_label.setText(pe_exit_signal_string)
                    self.pe_exit_change_time = datetime.datetime.now()
            else:
                self.act_pe_exit = None
                self.PE_exit_signal_label.setText("")
        except Exception as e:
            log_message(f"[ERROR] update_pe_exit_signal: {e}")
            import traceback
            log_message(f"[TRACEBACK] {traceback.format_exc()}")
            
    def pe_exit_age_minutes(self):
        if not self.pe_exit_change_time:
            return None
        age = int((datetime.datetime.now() - self.pe_exit_change_time).total_seconds() / 60)
        return age
  
    def schedule_auto_trade_activation(self):
        """Schedule auto trade activation at 9:20 AM"""
        cred_dir = "creds"
        autoTrade = False
        yaml_file = None
        for cred_file in os.listdir(cred_dir):
            if not (cred_file.startswith("cred_") and cred_file.endswith(".yml")):
                continue
            yaml_file = os.path.join(cred_dir, cred_file)
            try:
                with open(yaml_file) as f:
                    cred = yaml.load(f, Loader=yaml.FullLoader)

                autoTrade = cred['autoTrade']

                self.repeatRSIautoTrade = cred['repeatRSIaAutoTrade']

            except Exception as e:
                log_message(f"[ERROR] Loading credentials from {yaml_file}: {e}")
                return
        if not autoTrade:
            log_message(f"AutoTrade not scheduled (autoTrade disabled in {yaml_file}).")
            return
            
        try:
            today = QDate.currentDate().dayOfWeek()
            now = QTime.currentTime()
            target_time = QTime(9, 20)
            off_time = QTime(9, 30)

            if today in (6, 7):  # Skip Saturday & Sunday
                log_message("AutoTrade not scheduled (weekend).")
                return

            if target_time.msecsSinceStartOfDay() <= now.msecsSinceStartOfDay() < off_time.msecsSinceStartOfDay():
                if self.repeatRSIautoTrade:
                    self.RSI_autoTrade_checkbox.setChecked(True)
                    self.autoTrade_checkbox.setChecked(False)
                else:
                    self.autoTrade_checkbox.setChecked(True)
                    self.RSI_autoTrade_checkbox.setChecked(False)
            elif now.msecsSinceStartOfDay() < target_time.msecsSinceStartOfDay():
                msecs_until = now.msecsTo(target_time)
                QTimer.singleShot(msecs_until, self.activate_auto_trade_checkbox)
            else:
                log_message("AutoTrade window missed for today.")

        except Exception as e:
            log_message(f"[ERROR] schedule_auto_trade_activation: {e}")

    def activate_auto_trade_checkbox(self):
        if self.repeatRSIautoTrade:
            self.RSI_autoTrade_checkbox.setChecked(True)
            self.autoTrade_checkbox.setChecked(False)
        else:
            self.autoTrade_checkbox.setChecked(True)
            self.RSI_autoTrade_checkbox.setChecked(False)
    
    def show_closest_level(self):
        """Show closest GANN level - NON-BLOCKING VERSION"""
        try:
            index_symbol = self.symbol_input.currentText()
            
            # Async API call to avoid blocking GUI
            if index_symbol == 'NIFTY':
                token = Config.NiftyToken
            elif index_symbol == 'BANKNIFTY':
                token = Config.BankNiftyToken
            else:
                return
            
            # Check cache first
            now_ts = time.time()
            cached_atm, cached_ltp = self._atm_cache.get(index_symbol, (0, 0.0))
            if (not getattr(self, "websocket_connected", False)) and cached_atm:
                self._on_atm_fetched(index_symbol, cached_atm, cached_ltp)
                return
            if (now_ts - float(getattr(self, "_atm_last_error_ts", 0.0))) < 3.0 and cached_atm:
                self._on_atm_fetched(index_symbol, cached_atm, cached_ltp)
                return
            
            # Use APIWorker for non-blocking call
            worker = APIWorker(self.api_master.get_quotes, 'NSE', token)
            worker.signals.result.connect(lambda result: self._on_quotes_received(index_symbol, result))
            worker.signals.error.connect(lambda error: self._on_quotes_error(index_symbol, error))
            self.api_threadpool.start(worker)
            
        except Exception as e:
            log_message(f"[ERROR] show_closest_level: {e}")

    def _on_quotes_received(self, symbol, index):
        """Handle successful quotes response"""
        try:
            if not index or 'lp' not in index:
                log_message(f"[WARN] No LTP in quotes for {symbol}")
                return
            
            indexLTP = float(index['lp'])
            strikeDiff = getattr(self, 'indexStrikeDiff', 50)  # Default to 50
            mod = int(indexLTP) % strikeDiff
            if mod < (strikeDiff / 2):
                atmStrike = int(math.floor(indexLTP / strikeDiff)) * strikeDiff
            else:
                atmStrike = int(math.ceil(indexLTP / strikeDiff)) * strikeDiff
            
            self._atm_cache[symbol] = (atmStrike, indexLTP)
            self._on_atm_fetched(symbol, atmStrike, indexLTP)
            
        except Exception as e:
            log_message(f"[ERROR] _on_quotes_received: {e}")

    def _on_quotes_error(self, symbol, error):
        """Handle quotes API error"""
        self._atm_last_error_ts = time.time()
        cached_atm, cached_ltp = self._atm_cache.get(symbol, (0, 0.0))
        if cached_atm:
            self._on_atm_fetched(symbol, cached_atm, cached_ltp)
        else:
            log_message(f"[ERROR] Quotes failed for {symbol}: {error}")

    def _on_atm_fetched(self, symbol, atmStrike, intc_value):
        """Process ATM strike and LTP once fetched"""
        if atmStrike == 0 or intc_value == 0:
            return
            
        self.closest_Gann_level = self.find_closest_levels_with_ATM(self.gann_levels, intc_value)
        self.CL_lable.setText(f"Closest Level: {self.closest_Gann_level}, ")
        level_text = str(self.closest_Gann_level)
        # Check if item already exists in combo box
        index = self.level_box.findText(level_text)

        if index == -1:
            self.level_box.addItem(level_text)
            index = self.level_box.findText(level_text)

        # Select the item
        self.level_box.setCurrentIndex(index)
        
        # ✅ Schedule heavy operation asynchronously
        QTimer.singleShot(0, lambda: self.on_intc_value_fetched(intc_value))

    def initialize_reversal(self):
        """Initialize reversal in separate method"""
        try:
            self.analyze_915_and_set_reversal()
            self.signal_thread.core_reset_signal.emit(int(self.open_915))
            self.core_update_allowed = True
            self.signal_thread.core_update_signal.emit(self.core_update_allowed)
            self.reversal_initialized = True
        except Exception as e:
            log_message(f"[ERROR] initialize_reversal: {e}")

    def get_latest_candles(self, exchange='NSE', token=Config.NiftyToken, minutes=5):
        """
        Get only the latest N minutes of candle data (faster than full day).
        
        Args:
            exchange: Exchange name
            token: Token ID
            minutes: Number of minutes to fetch
        
        Returns:
            DataFrame or None
        """
        try:
            now = datetime.datetime.now()
            start_time = now - datetime.timedelta(minutes=minutes)
            start_timestamp = start_time.timestamp()
            
            ret = self.api_master.get_time_price_series(
                exchange=exchange,
                token=token,
                starttime=start_timestamp,
                interval=1
            )
            
            if ret:
                df = pd.DataFrame(ret)
                if 'intc' in df.columns:
                    print(f"[TS] ✅ Fetched last {minutes} minutes ({len(df)} candles)")
                    return df
            
            return None
            
        except Exception as e:
            log_message(f"[TS] ❌ Error fetching latest candles: {e}")
            return None

    def evaluate_current_candle(self, curr_dt):
        """Evaluate candle asynchronously - structure-aware, lightweight"""
        try:
            df = self.get_latest_candles(exchange='NSE', token=Config.NiftyToken, minutes=5)

            if df is None or df.empty:
                return

            df['time'] = pd.to_datetime(df['time'], format='%d-%m-%Y %H:%M:%S')
            df = df.sort_values('time')
            latest_candle = df.iloc[-1]

            candle = {
                "o": float(latest_candle['into']),
                "h": float(latest_candle['inth']),
                "l": float(latest_candle['intl']),
                "c": float(latest_candle['intc']),
            }

            print(f"[CANDLE] 📊 O:{candle['o']} H:{candle['h']} L:{candle['l']} C:{candle['c']}")

            # ─────────────────────────────────────────────
            # STRUCTURE ANALYSIS (LIGHTWEIGHT)
            # ─────────────────────────────────────────────

            self.structure_break_up = False
            self.structure_break_down = False
            self.in_whipsaw_zone = False
            self.valid_breakout = False
            structure_msg = ""

            if self.prev_candle:
                prev = self.prev_candle
                
                # Structure breaks
                if candle['c'] > prev['h']:
                    self.structure_break_up = True
                    structure_msg += "Structure Bullish, "

                if candle['c'] < prev['l']:
                    self.structure_break_down = True
                    structure_msg += "Structure Bearish, "
                # Inside / whipsaw candle
                if candle['h'] <= prev['h'] and candle['l'] >= prev['l']:
                    self.in_whipsaw_zone = True
                    structure_msg += "candle in whipsaw, "
                else:
                    structure_msg += "No candle whipsaw, "

                # Valid breakout candle (range expansion)
                body = abs(candle['c'] - candle['o'])
                range_ = candle['h'] - candle['l']

                if range_ > 0 and body / range_ > 0.6:
                    self.valid_breakout = True
                    structure_msg += "Valid_Breakout"

        
            # Save candle for next iteration
            self.prev_candle = candle

            # Existing logic (unchanged)
            self.evaluate_candle_for_gann(candle)
            self.last_candle_time = curr_dt

            # ─────────────────────────────────────────────
            # STRUCTURE STRENGTH SCORE (0 to 3)
            # ─────────────────────────────────────────────

            self.structure_strength = 0

            if self.structure_break_up or self.structure_break_down:
                self.structure_strength += 1

            if self.valid_breakout:
                self.structure_strength += 1

            if not self.in_whipsaw_zone:
                self.structure_strength += 1

            self.Deli_order_label.setText(f"{structure_msg.strip(', ')}, Strength: {self.structure_strength}/3")

        except Exception as e:
            log_message(f"[ERROR] evaluate_current_candle: {e}")

#++++++++++++ time series +++++++++++++++++
    def get_time_series(self, exchange='NSE', token=Config.NiftyToken, days=1, interval=1, use_cache=True):
        """
        Get time series with caching support.
        
        Args:
            exchange: Exchange name
            token: Token ID
            days: Number of days
            interval: Interval in minutes
            use_cache: Use cached data if available (default: True)
        
        Returns:
            DataFrame or None
        """
        try:
            cache_key = f"timeseries_{exchange}_{token}_{days}_{interval}"
            
            # ✅ CHANGED: Check cache first (60 second TTL)
            if use_cache:
                cached = self.data_cache.get(cache_key)
                if cached is not None:
                    #log_message(f"[TS] ✅ Using cached time series")
                    return cached
            
            # Cache miss - fetch fresh data
            now = datetime.datetime.now()
            now = now.replace(hour=0, minute=0, second=0, microsecond=0)
            prev_day = now - datetime.timedelta(days=days)
            prev_day_timestamp = prev_day.timestamp()
            
            ret = self.api_master.get_time_price_series(
                exchange=exchange,
                token=token,
                starttime=prev_day_timestamp,
                interval=interval
            )
            
            if ret:
                df = pd.DataFrame(ret)
                
                if df is not None and not df.empty:
                    required_cols = {'into', 'inth', 'intl', 'intc'}
                    if required_cols.issubset(df.columns):
                        latest = df.iloc[-1]
                        self.open_915 = float(latest['into'])
                        self.high_915 = float(latest['inth'])
                        self.low_915 = float(latest['intl'])
                        self.close_915 = float(latest['intc'])
                
                if 'intc' in df.columns:
                    # ✅ CHANGED: Cache for 60 seconds
                    self.data_cache.set(cache_key, df, ttl=60)
                    print(f"[TS] ✅ Fresh data fetched and cached")
                    return df
            
            return None
            
        except requests.exceptions.Timeout:
            log_message("[TS] ⏱️ Timeout fetching time series")
            return None
        except Exception as e:
            log_message(f"[TS] ❌ Error: {e}")
            return None

    def find_closest_levels_with_ATM(self, levels, atm_strike):
        """Find closest GANN level"""
        try:
            sorted_levels = sorted(levels)
            closest_level = min(sorted_levels, key=lambda x: abs(x - atm_strike))
            return closest_level
        except Exception as e:
            log_message(f"[ERROR] find_closest_levels_with_ATM: {e}")
            return 0
        
    def analyze_915_and_set_reversal(self):
        """Analyze 9:15 candle and set reversal"""
        try:
            df = self.get_time_series(exchange='NSE', token=Config.NiftyToken, days=1, interval=1)
            if df is None:
                log_message("[ERROR] Could not fetch 9:15 candle.")
                return
            
            df['time'] = pd.to_datetime(df['time'], format='%d-%m-%Y %H:%M:%S')
            candle_915_row = df[df['time'].dt.time == datetime.time(9, 15)]

            if not candle_915_row.empty: 

                row = candle_915_row.iloc[0]
                self.open_915 = float(row['into'])
                self.high_915 = float(row['inth'])
                self.low_915 = float(row['intl'])
                self.close_915 = float(row['intc'])

                log_message(f"[9:15 Candle] O: {self.open_915}, H: {self.high_915}, L: {self.low_915}, C: {self.close_915}")
                
                if not Config.NSE_error:
                    self.evaluate_candle_for_gann({
                        "o": self.open_915,
                        "h": self.high_915,
                        "l": self.low_915,
                        "c": self.close_915
                    })

            else:
                log_message("[ERROR] 9:15 candle not found in time series")
        except Exception as e:
            log_message(f"[ERROR] analyze_915_and_set_reversal: {e}")

    def evaluate_candle_for_gann(self, candle):
        """Evaluate candle for GANN level breakout"""
        try:
            o = candle["o"]
            h = candle["h"]
            l = candle["l"]
            c = candle["c"]
            tolerance = 1

            if None in (o, h, l, c):
                log_message("[CANDLE] Missing OHLC data, skipping evaluation.")
                return

            gann_sorted = sorted(self.gann_levels)
            touched = [lvl for lvl in gann_sorted if (l - tolerance) <= lvl <= (h + tolerance)]
            
            if not touched:
                return

            touched.sort(key=lambda lvl: abs(o - lvl))

            for lvl in touched:
                # Whipsaw Protection
                if lvl == self.last_gann_broken:
                    #log_message(f"[CANDLE SKIP] Whipsaw on same GANN level {lvl}, no reversal.")
                    return

                # Full Reversal Based on OHLC
                if o >= lvl and c <= lvl:
                    self.current_direction = "down"
                    self.last_gann_broken = lvl
                    self.reversal_gann_level = next((g for g in gann_sorted if g > lvl), None)
                    #log_message(f"[CANDLE REVERSAL] Breakdown at {lvl} - Reversal GANN = {self.reversal_gann_level}")
                    self.rev_label.setText(f"Reversal Level:- {self.reversal_gann_level} 🔴, ")
                    self.zone = None
                    return

                elif o <= lvl and c >= lvl:
                    self.current_direction = "up"
                    self.last_gann_broken = lvl
                    self.reversal_gann_level = next((g for g in reversed(gann_sorted) if g < lvl), None)
                    #log_message(f"[CANDLE REVERSAL] Breakout at {lvl} - Reversal GANN = {self.reversal_gann_level}")
                    self.rev_label.setText(f"Reversal Level:- {self.reversal_gann_level} 🟢, ")
                    self.zone = None
                    return

                # Weak Wick-based movement
                elif o >= lvl and l <= lvl:
                    self.current_direction = "down"
                    self.last_gann_broken = lvl
                    self.reversal_gann_level = next((g for g in gann_sorted if g > lvl), None)
                    #log_message(f"[CANDLE WICK] Weak breakdown at {lvl} - Reversal GANN = {self.reversal_gann_level}")
                    self.rev_label.setText(f"Reversal Level:- {self.reversal_gann_level} 🔴, ")
                    self.zone = None
                    return

                elif o <= lvl and h >= lvl:
                    self.current_direction = "up"
                    self.last_gann_broken = lvl
                    self.reversal_gann_level = next((g for g in reversed(gann_sorted) if g < lvl), None)
                    #log_message(f"[CANDLE WICK] Weak breakout at {lvl} - Reversal GANN = {self.reversal_gann_level}")
                    self.rev_label.setText(f"Reversal Level:- {self.reversal_gann_level} 🟢, ")
                    self.zone = None
                    return

            # Dynamic Flip if price touched reversal GANN itself
            if self.reversal_gann_level and abs(c - self.reversal_gann_level) <= tolerance:
                prev_dir = self.current_direction
                    # Guard against None - this should never happen in practice given your logic above
                if prev_dir is None:
                    #log_message("[CANDLE WARNING] Reversal flip attempted but current_direction is None")
                    return
                self.current_direction = "down" if self.current_direction == "up" else "up"
                old_reversal = self.reversal_gann_level
                self.reversal_gann_level = self.last_gann_broken
                self.last_gann_broken = old_reversal
                self.zone = None
                #log_message(f"[CANDLE REVERSAL FLIP] {prev_dir.upper()} → {self.current_direction.upper()} at {c} - New Reversal GANN = {self.reversal_gann_level}")
                return

            #log_message("[CANDLE] GANN touched, but no valid breakout/down pattern.")
        except Exception as e:
            log_message(f"[ERROR] evaluate_candle_for_gann: {e}")

    def execute_login_at_9am(self):
        """Execute login at 9 AM"""
        if getattr(self, "_login_in_progress", False):
            log_message("[LOGIN] Skipped: login already in progress")
            return
        if (time.time() - float(getattr(self, "_last_login_completed_ts", 0.0))) < 30.0:
            log_message("[LOGIN] Skipped: recently completed")
            return
        if getattr(self, "login_flag", False) and getattr(self, "_ws_started", False):
            log_message("[LOGIN] Skipped: session already active")
            return

        self._login_in_progress = True
        try:
            GannLevelCalculator()
            self.gann_manager = GannLevelsManager()
            self.gann_levels = []
            self.gann_manager.gann_levels = self.gann_levels
            self.gann_manager.read_gann_levels()
            try:
                self.level_box.clear()
            except Exception:
                pass
            
            for lvl in self.gann_levels:
                self.level_box.addItem(str(lvl))
            
            self.fetch_expiry_dates("NIFTY")

            self.multimgr = MultiAccountManager(creds_dir=Config.CREDS_DIR)
            self.api_master = self.multimgr.get_master_api()
            self.accounts = self.multimgr.accounts
            self.master_user = self.multimgr.master_user
            
            self.get_OTM_ITM_day()
           
            self.schedule_auto_trade_activation()
            
            # Start websocket only for master account (after event loop starts)
            QTimer.singleShot(0, self.start_webSocket)
            self.autoSquareOff_checkbox.setChecked(True)
            self.oneHourRule_checkbox.setChecked(True)

            FUTexpiry = self.get_valid_FUT_expiry_date()
            print(f"✅ Valid FUT expiry: {FUTexpiry}")
            fut_symbol = self.date_to_nifty_fut_symbol(FUTexpiry)
            fut_symbol = "NIFTY26JUNFUT"  # ← HARDCODED for testing - replace with dynamic symbol in production
            res = self.api_master.searchscrip(exchange="NSE", searchtext=fut_symbol)
            if res and 'values' in res and res['values'] and 'token' in res['values'][0]:
                self.fut_token = res['values'][0]['token']
                print(f"✅ Token for {fut_symbol}: {self.fut_token}")
            else:
                log_message(f"[ERROR] Could not fetch token for {fut_symbol}. Response: {res}")
                QMessageBox.critical(self, "Login Error", f"Failed to fetch token for {fut_symbol}. Please check symbol or API response.")
                return

            self.login_button.setText("Login Successful")
            self.login_button.setStyleSheet("color: Green; font-weight: bold")
            self.logout_flag = False
            self.login_flag = True
            self._last_login_completed_ts = time.time()
            
            # Fetch initial LTP after successful login
            self.show_closest_level()
            
            # ✅ NEW: Recover any orphaned orders from previous crash/hang
            log_message("\n[LOGIN] Attempting to recover orphaned orders...")
            recovery_result = self.recover_orphaned_orders_on_restart()
            if recovery_result['status'] == 'ERROR':
                log_message(f"[WARNING] Recovery encountered errors: {recovery_result['errors']}")
                QMessageBox.warning(self, "Recovery Warning", 
                    f"Orphaned order recovery encountered errors.\n\n"
                    f"Found: {recovery_result['orphaned_orders_found']} orphaned orders\n"
                    f"Recovered: {recovery_result['orders_recovered']}\n\n"
                    f"Check logs for details. You may need to manual reconcile.")
            elif recovery_result['orphaned_orders_found'] > 0:
                log_message(f"[SUCCESS] Recovered {recovery_result['orders_recovered']} of {recovery_result['orphaned_orders_found']} orphaned orders")
                QMessageBox.information(self, "Orders Recovered", 
                    f"Successfully recovered {recovery_result['orders_recovered']} orphaned order(s)!\n\n"
                    f"Position state has been restored.\n"
                    f"Check logs for details.")
            else:
                log_message("[INFO] No orphaned orders found - system state is clean")
            
            # Start the timer thread only if not already started
            if not hasattr(self, 'timer_thread_started') or not self.timer_thread_started:
                self.start_timer_thread()
                self.timer_thread_started = True

            # ✅ FIXED: Start timer only if not already running
            if not self.timer_CL.isActive():
                self.timer_CL.start(5000)  # Increased from 1000ms to reduce API calls
            
            # After successful login: reconcile all known symbols (safe default)
            for sym in list(self.symbol_qty_map.keys()):
                try:
                    self._reconcile_position_with_broker(sym)
                except Exception as e:
                    log_message(f"[WARN] reconcile at login for {sym}: {e}")
                    
        except Exception as e:
            log_message(f"[ERROR] execute_login_at_9am: {e}")
            QMessageBox.critical(self, "Login Error", f"Failed to login: {e}")
        finally:
            self._login_in_progress = False

    def refresh_coi_plot(self):
        """Refresh COI plot"""
        try:
            # Clear plots if current time is 09:13 AM
            if datetime.datetime.now().strftime("%H:%M") == "09:13":
                self.upper_plot.clear()
                self.lower_plot.clear()
                self.coi_data_points.clear()
                return

            if not self.coi_data_points:
                return

            df = pd.DataFrame(list(self.coi_data_points))
            df.set_index("time", inplace=True)

            # Filter only market hours
            df = df.between_time("09:15", "15:30")

            selected_mas = []
            if self.coi_checkbox_1min.isChecked():
                selected_mas.append(1)
            if self.coi_checkbox_3min.isChecked():
                selected_mas.append(3)
            if self.coi_checkbox_5min.isChecked():
                selected_mas.append(5)

            if not selected_mas:
                return

            self.upper_plot.clear()
            self.lower_plot.clear()

            ce_colors = {1: '#66ff66', 3: '#00cc00', 5: '#006600'}
            pe_colors = {1: '#ff9999', 3: '#ff3333', 5: '#990000'}

            x_ticks = None
            for ma in selected_mas:
                rolled = df.rolling(window=ma).mean()

                x_ticks = list(enumerate(pd.to_datetime(rolled.index).strftime("%H:%M")))
                x_vals = list(range(len(x_ticks)))

                self.upper_plot.plot(
                    x_vals, rolled["uce"].to_numpy(),
                    pen=pg.mkPen(ce_colors[ma], width=2),
                    name=f"{ma}-min Upper CE"
                )
                self.upper_plot.plot(
                    x_vals, rolled["upe"].to_numpy(),
                    pen=pg.mkPen(pe_colors[ma], width=2, style=Qt.PenStyle.DashLine),
                    name=f"{ma}-min Upper PE"
                )

                self.lower_plot.plot(
                    x_vals, rolled["lce"].to_numpy(),
                    pen=pg.mkPen(ce_colors[ma], width=2),
                    name=f"{ma}-min Lower CE"
                )
                self.lower_plot.plot(
                    x_vals, rolled["lpe"].to_numpy(),
                    pen=pg.mkPen(pe_colors[ma], width=2, style=Qt.PenStyle.DashLine),
                    name=f"{ma}-min Lower PE"
                )

            if x_ticks is not None:
                self.upper_plot.getAxis('bottom').setTicks([x_ticks])
                self.lower_plot.getAxis('bottom').setTicks([x_ticks])

            if self.core_update_allowed:
                self.core_update_allowed = False
                self.signal_thread.core_update_signal.emit(self.core_update_allowed)
        except Exception as e:
            log_message(f"[ERROR] refresh_coi_plot: {e}")

    def handle_signal_result(self, result):
        """Handle signal result from signal thread"""
        try:
            self.final_signal, text_report, upper_ce, upper_pe, lower_ce, lower_pe = result
            self.analysis_output.setPlainText(text_report)

            timestamp = datetime.datetime.now().replace(second=0, microsecond=0)

            if self.last_coi_plot_time is None or timestamp > self.last_coi_plot_time:
                # Check if any CE or PE value is zero; skip appending if so
                if all(val != 0 for val in [upper_ce, upper_pe, lower_ce, lower_pe]):
                    self.last_coi_plot_time = timestamp
                    self.coi_data_points.append({
                        "time": timestamp,
                        "uce": upper_ce,
                        "upe": upper_pe,
                        "lce": lower_ce,
                        "lpe": lower_pe
                    })

            # Initialize last_plot_update_time if not present
            if not hasattr(self, 'last_plot_update_time'):
                self.last_plot_update_time = {1: datetime.datetime.now(), 3: datetime.datetime.now(), 5: datetime.datetime.now()}

            # Trigger refresh only for the selected interval(s) if their time has come
            for ma in [1, 3, 5]:
                if getattr(self, f"coi_checkbox_{ma}min").isChecked():
                    last = self.last_plot_update_time.get(ma)
                    if last is None or isinstance(last, datetime.datetime) and (timestamp - last).seconds >= ma * 60:
                        self.last_plot_update_time[ma] = timestamp
                        self.refresh_coi_plot()
                        break
        except Exception as e:
            log_message(f"[ERROR] handle_signal_result: {e}")

    def safe_float(self, val):
        """Safely convert value to float"""
        try:
            return float(val)
        except:
            return 0.0

#++++++++++++ Cashflow and MTM Calculation +++++++++++++++++
    def calculate_position_mtm(self):
        """Calculate position MTM"""
        try:
            positions = self.api_master.get_positions()
            if not positions:
                return 0.0, 0.0, "❌ No positions to fetch."

            total_urmtom = 0.0
            total_rpnl = 0.0

            summary_lines = ["📈 Positional Summary:"]
            for pos in positions:
                try:
                    tsym = pos["tsym"]
                    exch = pos["exch"]
                    netqty = int(pos["netqty"])
                    urmtom = float(pos["urmtom"])
                    rpnl = float(pos["rpnl"])
                    netavg = float(pos["netavgprc"])
                    ltp = float(pos["lp"])

                    total_urmtom += urmtom
                    total_rpnl += rpnl

                    summary_lines.append(
                        f"🔹 {tsym} ({exch}) | Qty: {netqty} | Avg: {netavg} | LTP: {ltp} | PnL: ₹{urmtom + rpnl:.2f}"
                    )
                except Exception as e:
                    summary_lines.append(f"[WARN] Skipped position: {e}")
                    continue

            total_m2m = total_urmtom + total_rpnl
            summary_lines.append(f"✅ Total Day MTM = ₹{total_m2m:.2f}")
            return round(total_rpnl, 2), round(total_m2m, 2), "\n".join(summary_lines)

        except Exception as e:
            return 0.0, 0.0, f"❌ Failed to fetch positions: {e}"

    def track_cashflow_summary(self, api_client: Optional[FyersApiAdapter] = None):
        """Track cashflow summary"""
        try:
            api_client = api_client or getattr(self, "api_master", None) or api
            limits = api_client.get_limits() if api_client else {}
            holdings = api_client.get_holdings(product_type='C') if api_client else []

            opening_balance = self.safe_float(limits.get("openingbalance"))
            available_cash = self.safe_float(limits.get("cash"))
            margin_used = self.safe_float(limits.get("marginused"))
            payin = self.safe_float(limits.get("payin"))
            payout = self.safe_float(limits.get("payout") or limits.get("withdrawreq") or limits.get("payoutamt"))
            brokerage = self.safe_float(limits.get("brokerage"))

            rpnl, mtm_total, mtm_log = self.calculate_position_mtm()

            holding_value = 0.0
            holding_investment = 0.0
            holding_log = ["📦 Holdings Valuation:"]
            
            if holdings:
                for h in holdings:
                    try:
                        valuation_qty = (
                            int(h["holdqty"]) +
                            int(h["btstqty"]) +
                            int(h.get("brkcolqty", 0)) +
                            int(h.get("unplgdqty", 0)) +
                            int(h.get("benqty", 0)) +
                            max(int(h.get("dpqty", 0)), int(h.get("npoadqty", 0))) -
                            int(h["usedqty"])
                        )

                        if valuation_qty <= 0:
                            holding_log.append("❌ Skipping holding with net qty 0")
                            continue

                        exch_tsym_list = h.get("exch_tsym")
                        if not exch_tsym_list:
                            holding_log.append("❌ exch_tsym missing or empty")
                            continue

                        buy_avg_price = self.safe_float(h.get("upldprc", 0.0))
                        holding_investment += valuation_qty * buy_avg_price

                        for item in exch_tsym_list:
                            exch = item.get("exch")
                            tsym = item.get("tsym")
                            quote = api_client.get_quotes(exch, tsym) if api_client else {}
                            if quote and 'lp' in quote:
                                ltp = float(quote['lp'])
                                value = valuation_qty * ltp
                                holding_value += value
                                holding_log.append(
                                    f"✅ {tsym}: ₹{ltp} × {valuation_qty} = ₹{value:.2f} "
                                    f"(Invested: ₹{buy_avg_price} × {valuation_qty} = ₹{valuation_qty * buy_avg_price:.2f})"
                                )
                                break

                    except Exception as e:
                        holding_log.append(f"[ERROR] Holding valuation failed: {e}")
                        continue

            net_cash_available = available_cash - payout
            total_assets = available_cash + margin_used + holding_value
            net_day_pnl = total_assets - opening_balance
            net_worth = total_assets
            net_cash_inflow = payin - payout

            Net_fee = (mtm_total - brokerage) * 0.40
            
            summary = {
                "Date": datetime.date.today().isoformat(),
                "OpeningBalance": round(opening_balance, 2),
                "AvailableCash": round(available_cash, 2),
                "MarginUsed": round(margin_used, 2),
                "Payin": round(payin, 2),
                "Payout": round(payout, 2),
                "Holding Invested": round(holding_investment, 2),
                "HoldingsValue": round(holding_value, 2),
                "NetUsableCash": round(net_cash_available, 2),
                "NetDayPnL": round(net_day_pnl, 2),
                "NetWorth": round(net_worth, 2),
                "NetCashInflow": round(net_cash_inflow, 2),
                "MTM": round(mtm_total, 2),
                "Brokerage": round(brokerage, 2),
                "Total Charges": round(Net_fee, 2)
            }

            return summary, mtm_log + "\n" + "\n".join(holding_log)
        except Exception as e:
            log_message(f"[ERROR] track_cashflow_summary: {e}")
            return {}, ""

    def fetch_order_book(self, save_dir=Config.PNL_DIR, user="", name="", api_client: Optional[FyersApiAdapter] = None):
        """Fetch order book and save to file"""
        try:
            api_client = api_client or getattr(self, "api_master", None) or api
            orders = api_client.get_order_book() if api_client else []
            if not orders:
                return "❌ No orders found."

            lines = [f"🔒 Order Book: {datetime.date.today().isoformat()}"]
            for o in orders:
                try:
                    tsym = o.get("tsym")
                    exch = o.get("exch")
                    qty = o.get("qty")
                    prc = o.get("prc")
                    status = o.get("status")
                    trantype = o.get("trantype")
                    ordertime = o.get("ordtime")
                    avgprc = o.get("avgprc")

                    lines.append(
                        f"🕐 {ordertime} | {tsym} ({exch}) | {trantype} | "
                        f"Qty: {qty} | Price: {prc} | Avg: {avgprc} | Status: {status}"
                    )
                except Exception as e:
                    lines.append(f"[WARN] Skipped order: {e}")

            # Save to text file
            os.makedirs(save_dir, exist_ok=True)
            filename = os.path.join(save_dir, f"orderbook_{name}_{user}.txt")
            with open(filename, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n\n")

            return "\n".join(lines)

        except Exception as e:
            return f"❌ Failed to fetch order book: {e}"

    def run_summary(self):
        """Run end-of-day summary for all accounts"""
        try:
            cred_dir = "creds"
            output_dir = "Fyers_PnL"
            os.makedirs(output_dir, exist_ok=True)

            processed_count = 0
            skipped_count = 0

            for cred_file in os.listdir(cred_dir):
                if not (cred_file.startswith("cred_") and cred_file.endswith(".yml")):
                    continue

                yaml_file = os.path.join(cred_dir, cred_file)
                try:
                    with open(yaml_file) as f:
                        cred = yaml.load(f, Loader=yaml.FullLoader)

                    name = cred['name']
                    app_id = str(cred.get('fyers_app_id', cred.get('app_id', ''))).strip()
                    access_token = str(cred.get('fyers_access_token', cred.get('access_token', ''))).strip()
                    if not app_id or not access_token:
                        log_message(f"[SUMMARY] Missing FYERS credentials for {cred.get('user')}")
                        skipped_count += 1
                        continue

                    api_local = FyersApiAdapter(app_id=app_id, access_token=access_token)
                    login_res = api_local.login(app_id=app_id, access_token=access_token)
                    if not login_res or login_res.get("stat") != "Ok":
                        log_message(f"[SUMMARY] Login failed for {cred.get('user')} - {login_res}")
                        skipped_count += 1
                        continue

                    summary, _ = self.track_cashflow_summary(api_local)
                    order_log = self.fetch_order_book(output_dir, cred['user'], cred['name'], api_client=api_local)
                    
                    filename = os.path.join(output_dir, f"cashflow_{cred['name']}_{cred['user']}.csv")
                    file_exists = os.path.exists(filename)
                    today_str = summary["Date"]

                    should_write = True
                    if file_exists:
                        try:
                            df_existing = pd.read_csv(filename)
                            if today_str in df_existing['Date'].values:
                                should_write = False
                                log_message(f"[SUMMARY] Entry for today already exists for {cred['user']}")
                        except Exception as e:
                            log_message(f"[SUMMARY] Error checking CSV for {cred['user']}: {e}")
                            skipped_count += 1
                            continue

                    if should_write:
                        with open(filename, "a", newline='') as csvfile:
                            writer = csv.DictWriter(csvfile, fieldnames=summary.keys())
                            if not file_exists:
                                writer.writeheader()
                            writer.writerow(summary)
                        log_message(f"[SUMMARY] Written summary for {cred['user']}")
                        processed_count += 1

                    # FYERS logout is optional; tokens are short-lived and safe to omit here.

                except Exception as e:
                    log_message(f"[SUMMARY] Error processing {cred_file}: {str(e)}")
                    skipped_count += 1

            log_message(f"[SUMMARY] Processed: {processed_count}, Skipped: {skipped_count}")
        except Exception as e:
            log_message(f"[ERROR] run_summary: {e}")

    def set_button_busy(self, btn, busy=True, text=None):
        if busy:
            btn.setEnabled(False)
            btn._orig_text = btn.text()
            btn.setText(text if text is not None else "Processing...")
            btn.setStyleSheet("background-color: #f0ad4e; color: white;")
        else:
            btn.setEnabled(True)
            btn.setText(
                text if text is not None else getattr(btn, "_orig_text", "")
            )
            btn.setStyleSheet("border: 2px solid red;")  # restore default

    def monitor_performance(self):
        """
        Monitor and log performance metrics.
        Call this from a timer to track system health.
        """
        try:
            # ThreadPool stats
            if hasattr(self, 'api_threadpool'):
                active = self.api_threadpool.activeThreadCount()
                log_message(f"[PERF] API ThreadPool - Active: {active}/{self.api_threadpool.maxThreadCount()}")
            
            # Executor stats
            if hasattr(self, 'executor'):
                # Note: ThreadPoolExecutor doesn't expose active count directly
                log_message(f"[PERF] Multi-account executor - Max workers: {self.executor._max_workers}")
            
            # Cache stats
            if hasattr(self, 'data_cache'):
                stats = self.data_cache.get_stats()
                log_message(f"[PERF] Cache - Total: {stats['total']}, Active: {stats['active']}")
            
            # Pending requests
            if hasattr(self, 'pending_ltp_requests'):
                pending = len(self.pending_ltp_requests)
                if pending > 0:
                    log_message(f"[PERF] ⚠️ Pending LTP requests: {pending}")
            
        except Exception as e:
            log_message(f"[ERROR] monitor_performance: {e}")

    # --- Fetch raw 5-min candles ---
    def fetch_Nifty_FUT_candles(self, days=5, interval=5):
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=days)
        start = start.replace(hour=9, minute=15, second=0, microsecond=0)
        end = end.replace(hour=15, minute=30, second=0, microsecond=0)

        raw = self.api_master.get_time_price_series(
            exchange="NFO",
            token=self.fut_token,
            starttime=start.timestamp(),
            endtime=end.timestamp(),
            interval=interval
        )
        if not raw:
            raise RuntimeError("❌ No candle data returned")

        df = pd.DataFrame(raw)
        df['time'] = pd.to_datetime(df['time'], dayfirst=True, errors='coerce')
        df = df.sort_values('time')
        df.set_index('time', inplace=True)
        df['close'] = pd.to_numeric(df['intc'], errors='coerce')
        df['v'] = pd.to_numeric(df['vol'], errors='coerce')  # Map volume column
        return df

    def last_FUT_expiry_day(self, year, month):
        # Get last day of the month
        if month == 12:
            last_day = date(year, 12, 31)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)

        offset = (last_day.weekday() - Config.ExpiryDay) % 7
        return last_day - timedelta(days=offset)

    def date_to_nifty_fut_symbol(self, expiry_date):
        month_map = {
            1: "JAN", 2: "FEB", 3: "MAR", 4: "APR",
            5: "MAY", 6: "JUN", 7: "JUL", 8: "AUG",
            9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC"
        }

        month = month_map[expiry_date.month]
        year = str(expiry_date.year)[-2:]

        # FYERS futures symbol format does NOT include day (e.g., NIFTY26MARFUT)
        return f"NIFTY{year}{month}FUT"

    def get_valid_FUT_expiry_date(self):
        today = date.today()

        # Last Tuesday of current month
        lt_current = self.last_FUT_expiry_day(today.year, today.month)

        if today <= lt_current:
            return lt_current
        else:
            # Move to next month
            if today.month == 12:
                return self.last_FUT_expiry_day(today.year + 1, 1)
            else:
                return self.last_FUT_expiry_day(today.year, today.month + 1)

# ============================================
class AlgoNiftyTelegramReporter:
    def __init__(self,
                 bot_token: str,
                 admin_chat_id: str,
                 creds_dir: str = "creds",
                 pnl_dir: str = "Fyers_PnL",
                 expiry_days: int = 90,
                 reminder_days: int = 1):
        self.TELEGRAM_BOT_TOKEN = bot_token
        self.ADMIN_CHAT_ID = admin_chat_id
        self.creds_dir = creds_dir
        self.PNL_DIR = pnl_dir
        self.EXPIRY_DAYS = expiry_days
        self.REMINDER_DAYS = reminder_days

        self.chat_to_file = {}
        self.user_states = {}
        self.app = None
        self._last_poll_error_ts = 0.0
        self._last_poll_error_msg = ""

    def load_chat_mapping(self):
        """Load chat ID to credential file mapping"""
        self.chat_to_file.clear()
        for file_name in os.listdir(self.creds_dir):
            if file_name.startswith("cred") and file_name.endswith(".yml"):
                path = os.path.join(self.creds_dir, file_name)
                try:
                    with open(path, "r") as f:
                        data = yaml.safe_load(f) or {}
                    chat_id = str(data.get("chatID"))
                    if chat_id:
                        self.chat_to_file[chat_id] = path
                except Exception as e:
                    print(f"[WARN] Failed loading {file_name}: {e}")

    async def check_password_expiry(self):
        """Check password expiry for all accounts"""
        if self.app is None:
            print("[WARN] App not initialized, skipping password expiry check")
            return
            
        today = datetime.datetime.today().date()
        admin_report = []

        for file_name in os.listdir(self.creds_dir):
            if file_name.startswith("cred") and file_name.endswith(".yml"):
                path = os.path.join(self.creds_dir, file_name)
                try:
                    with open(path, "r") as f:
                        data = yaml.safe_load(f) or {}

                    start_date_str = data.get("startDate")
                    chat_id = data.get("chatID")
                    if not start_date_str or not chat_id:
                        continue

                    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
                    expiry_date = start_date + timedelta(days=self.EXPIRY_DAYS)
                    reminder_date = expiry_date - timedelta(days=self.REMINDER_DAYS)

                    if today == reminder_date or today >= expiry_date:
                        if today == reminder_date:
                            msg = f"⚠️ Your password will expire tomorrow ({expiry_date}). Did you change it?"
                        else:
                            msg = f"❌ Your password expired on {expiry_date}. Did you change it?"

                        keyboard = [[
                            InlineKeyboardButton("✅ Yes", callback_data=f"yes_{chat_id}"),
                            InlineKeyboardButton("❌ No", callback_data=f"no_{chat_id}")
                        ]]
                        reply_markup = InlineKeyboardMarkup(keyboard)

                        await self.app.bot.send_message(chat_id=chat_id, text=msg, reply_markup=reply_markup)
                        admin_report.append(f"{file_name}: alert sent ({expiry_date})")
            
                        msg = await self.app.bot.send_message(
                            chat_id=chat_id,
                            text="📌 Reminder: To update password, send:\n\n"
                                "`update <password> <YYYY-MM-DD>`",
                            parse_mode="Markdown"
                        )
                        await self.app.bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id)

                except Exception as e:
                    print(f"[ERROR] Could not process {file_name}: {e}")

        if admin_report:
            full = "📋 Daily Expiry Report:\n" + "\n".join(admin_report)
            await self.app.bot.send_message(chat_id=self.ADMIN_CHAT_ID, text=full)

    async def send_pnl_reports(self):
        """Send PnL reports to all users"""
        if self.app is None:
            print("[WARN] App not initialized, skipping PnL reports")
            return
        
        today_str = datetime.datetime.today().strftime("%Y-%m-%d")
        admin_msgs = []

        for chat_id, file_path in self.chat_to_file.items():
            try:
                with open(file_path, "r") as f:
                    data = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"[WARN] Can't read {file_path}: {e}")
                continue

            user_id = data.get("user")
            display_name = data.get("name", user_id)

            if not user_id:
                continue

            csv_file = None
            try:
                for fname in os.listdir(self.PNL_DIR):
                    if fname.startswith("cashflow_") and fname.endswith(f"_{user_id}.csv"):
                        csv_file = os.path.join(self.PNL_DIR, fname)
                        break
            except FileNotFoundError:
                pass

            if not csv_file or not os.path.exists(csv_file):
                msg = f"⚠️ No PnL file found for {display_name} ({user_id})."
                await self.app.bot.send_message(chat_id=chat_id, text=msg)
                admin_msgs.append(msg)
                continue

            try:
                df = pd.read_csv(csv_file)
                if "Date" not in df.columns:
                    msg = f"⚠️ Invalid PnL file for {display_name} ({user_id}) – missing 'Date' column."
                    await self.app.bot.send_message(chat_id=chat_id, text=msg)
                    admin_msgs.append(msg)
                    continue

                df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
                today_rows = df[df["Date"] == today_str]
                if today_rows.empty:
                    msg = f"⏳ No PnL entry for {display_name} on {today_str}."
                    await self.app.bot.send_message(chat_id=chat_id, text=msg)
                    admin_msgs.append(msg)
                    continue

                row = today_rows.iloc[-1]
                try:
                    mtm = row["MTM"]
                    brokerage = row["Brokerage"]
                    total_charges = row["Total Charges"]
                except KeyError:
                    mtm, brokerage, total_charges = row.iloc[-3], row.iloc[-2], row.iloc[-1]

                msg = (
                    f"📊 Daily PnL Report ({today_str})\n"
                    f"👤 {display_name} ({user_id})\n"
                    f"💰 MTM: {mtm}\n"
                    f"🏦 Brokerage: {brokerage}\n"
                    f"💸 Total Charges: {total_charges}"
                )
                await self.app.bot.send_message(chat_id=chat_id, text=msg)
                admin_msgs.append(msg)

            except Exception as e:
                err = f"[ERROR] Reading PnL for {display_name} ({user_id}): {e}"
                print(err)
                admin_msgs.append(err)

        if admin_msgs:
            summary = "📋 Daily PnL Summary:\n\n" + "\n\n".join(admin_msgs)
            await self.app.bot.send_message(chat_id=self.ADMIN_CHAT_ID, text=summary)

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        data = query.data
        if data is None:
            return
        action, chat_id = data.split("_", 1)

        if action == "yes":
            self.user_states[chat_id] = "awaiting_pwd"
            await query.edit_message_text("✅ Great! Please send your new password.")
        elif action == "no":
            await query.edit_message_text("⏳ Okay, please remember to change your password soon.")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages"""
        if update.effective_chat is None:
            return
        if update.message is None:
            return
        chat_id = str(update.effective_chat.id)
        text = (update.message.text or "").strip()

        if chat_id not in self.chat_to_file:
            await update.message.reply_text("❌ I don't know which account this is linked to.")
            return

        # Manual update (anytime with prefix 'update')
        if text.lower().startswith("update "):
            parts = text.split()
            if len(parts) != 3:
                await update.message.reply_text("⚠️ Format error. Use: update <password> <YYYY-MM-DD>")
                return

            new_pwd, new_date_str = parts[1], parts[2]
            try:
                new_date = datetime.datetime.strptime(new_date_str, "%Y-%m-%d").date()
            except ValueError:
                await update.message.reply_text("❌ Invalid date format. Please use YYYY-MM-DD.")
                return

            file_path = self.chat_to_file[chat_id]
            try:
                with open(file_path, "r") as f:
                    data = yaml.safe_load(f) or {}
            except Exception as e:
                await update.message.reply_text(f"⚠️ Could not read your credential file: {e}")
                return

            data["pwd"] = new_pwd
            data["startDate"] = str(new_date)

            try:
                with open(file_path, "w") as f:
                    yaml.safe_dump(data, f, default_flow_style=False)
            except Exception as e:
                await update.message.reply_text(f"⚠️ Could not update your credential file: {e}")
                return

            await update.message.reply_text(
                f"✅ Password and startDate updated manually.\n\n"
                f"📅 New Date: {new_date}\n"
                f"🔑 New Password: {new_pwd}"
            )

            await context.bot.send_message(
                chat_id=self.ADMIN_CHAT_ID,
                text=f"📝 Manual update by user {chat_id}\n"
                    f"File: {file_path}\n"
                    f"📅 New startDate: {new_date}\n"
                    f"🔑 New password: {new_pwd}"
            )

            self.load_chat_mapping()
            return

        # Reminder-driven update (after bot asks)
        state = self.user_states.get(chat_id)

        if state == "awaiting_pwd":
            self.user_states[chat_id] = {"pwd": text, "step": "awaiting_date"}
            await update.message.reply_text("🔑 Password received. Now please send the new startDate (YYYY-MM-DD).")
            return

        if isinstance(state, dict) and state.get("step") == "awaiting_date":
            try:
                new_date = datetime.datetime.strptime(text, "%Y-%m-%d").date()
            except ValueError:
                await update.message.reply_text("❌ Invalid date format. Please reply with YYYY-MM-DD.")
                return

            new_pwd = state["pwd"]
            file_path = self.chat_to_file[chat_id]

            try:
                with open(file_path, "r") as f:
                    data = yaml.safe_load(f) or {}
            except Exception as e:
                await update.message.reply_text(f"⚠️ Could not read your credential file: {e}")
                return

            data["pwd"] = new_pwd
            data["startDate"] = str(new_date)

            try:
                with open(file_path, "w") as f:
                    yaml.safe_dump(data, f, default_flow_style=False)
            except Exception as e:
                await update.message.reply_text(f"⚠️ Could not update your credential file: {e}")
                return

            await update.message.reply_text(
                f"✅ Thanks! Your password and startDate have been updated.\n\n"
                f"📅 New Date: {new_date}\n"
                f"🔑 New Password: {new_pwd}"
            )

            await context.bot.send_message(
                chat_id=self.ADMIN_CHAT_ID,
                text=f"📄 Updated {file_path}\nNew startDate: {new_date}\nNew password: {new_pwd}"
            )

            self.user_states.pop(chat_id, None)
            self.load_chat_mapping()
            return

        await update.message.reply_text("ℹ️ Please wait for a reminder or use: update <password> <YYYY-MM-DD>")

    async def run(self):
        """Main run method"""
        self.load_chat_mapping()
        self.app = Application.builder().token(self.TELEGRAM_BOT_TOKEN).build()

        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        print("🤖 Bot is running...")

        async def daily_report_task():
            while True:
                now = datetime.datetime.now()
                target = now.replace(hour=15, minute=40, second=0, microsecond=0)
                if now >= target:
                    target = target + timedelta(days=1)

                wait_seconds = (target - now).total_seconds()
                print(f"[Scheduler] Next report at {target} (waiting {wait_seconds/60:.1f} min)")

                await asyncio.sleep(wait_seconds)

                try:
                    await self.check_password_expiry()
                    await self.send_pnl_reports()
                    print(f"[Scheduler] Reports sent at {datetime.datetime.now()}")
                except Exception as e:
                    print(f"[Scheduler Error] {e}")

        async def shutdown_at_morning():
            while True:
                now = datetime.datetime.now().time()
                if now >= datetime.time(8, 50):
                    print("🛑 Stopping Telegram Reporter at 08:50")
                    if self.app is not None:
                        await self.app.stop()
                    break
                await asyncio.sleep(30)

        await self.app.initialize()
        await self.app.start()

        def polling_error_callback(exc):
            """Handle polling errors without dumping full traceback repeatedly."""
            try:
                msg = str(exc)
                now_ts = time.time()
                if (
                    msg != self._last_poll_error_msg
                    or (now_ts - self._last_poll_error_ts) >= 15
                ):
                    print(f"[Telegram] Polling network error: {msg}")
                    self._last_poll_error_msg = msg
                    self._last_poll_error_ts = now_ts
            except Exception:
                pass
        
        # ✅ FIX: Check if updater exists before calling start_polling()
        if self.app and self.app.updater:
            await self.app.updater.start_polling(error_callback=polling_error_callback)
        else:
            print("[ERROR] Application updater is not initialized")
            return

        await asyncio.gather(
            daily_report_task(),
            shutdown_at_morning()
        )

# ============================================
class NseSession:
    BASE_URL = "https://www.nseindia.com"
    HEADERS = {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130 Safari/537.36"
        ),
        "accept-language": "en-US,en;q=0.9"
    }

    def __init__(self):
        self.session = requests.Session()
        self.cookies = {}
        self._warmup()

    def _warmup(self):
        """Fetch NSE homepage → obtain cookies to avoid 401/403."""
        try:
            r = self.session.get(self.BASE_URL, headers=self.HEADERS, timeout=5)
            self.cookies = r.cookies.get_dict()
        except Exception:
            self.cookies = {}

    def get(self, url, timeout=5):
        """Perform GET with session, headers, cookies."""
        return self.session.get(
            url,
            headers=self.HEADERS,
            cookies=self.cookies,
            timeout=timeout
        )

class SymbolFetcher:
    SYMBOL_URL = "https://www.nseindia.com/api/underlying-information"

    def __init__(self, nse: NseSession):
        self.nse = nse

    def fetch_symbols(self):
        """Returns (indices, stocks) from NSE."""
        try:
            r = self.nse.get(self.SYMBOL_URL)
            data = r.json()
        except:
            return [], []

        indices = [d["symbol"] for d in data["data"]["IndexList"]]
        stocks = [d["symbol"] for d in data["data"]["UnderlyingList"]]

        return indices, stocks

class ExpiryFetcher:
    EXPIRY_URL = "https://www.nseindia.com/api/option-chain-contract-info?symbol={}"
    OC_URL     = "https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={}&expiry={}"

    def __init__(self, nse: NseSession):
        self.nse = nse

    def fetch_expiries(self, symbol: str):
        url = self.EXPIRY_URL.format(symbol.upper())

        try:
            r = self.nse.get(url)
            data = r.json()
        except Exception:
            return []

        raw_expiries = data.get("expiryDates", [])
        today = datetime.date.today()

        # Step 1: future dates only
        future_exp = []
        for ex in raw_expiries:
            try:
                d = datetime.datetime.strptime(ex, "%d-%b-%Y").date()
                if d >= today:
                    future_exp.append(ex)
            except:
                pass

        # Step 2: TEST each expiry for actual CE/PE data
        valid_expiries = []
        for ex in future_exp:
            try:
                test_url = self.OC_URL.format(symbol.upper(), ex)
                r2 = self.nse.get(test_url)
                d2 = r2.json()

                if d2.get("records", {}).get("data", []):
                    valid_expiries.append(ex)
            except:
                pass

        return valid_expiries

class OptionChainFetcher:
    OC_URL = "https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={}&expiry={}"

    def __init__(self, nse: NseSession):
        self.nse = nse

    def normalize_exp(self, date_str):
        """
        Normalize any expiry format into DD-MMM-YYYY.
        Handles: 16-Dec-2025, 16-12-2025, 16/12/2025, etc.
        """
        fmts = ["%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"]
        for f in fmts:
            try:
                d = datetime.datetime.strptime(date_str, f)
                return d.strftime("%d-%b-%Y")
            except:
                continue
        return date_str

    def fetch_option_chain(self, symbol: str, expiry: str):
        expiry_norm = self.normalize_exp(expiry)
        url = self.OC_URL.format(symbol.upper(), expiry_norm)
        #print("Fetching:", url)
        try:
            r = self.nse.get(url)
            data = r.json()
        except Exception:
            return None, None, expiry

        records = data.get("records", {})
        data_list = records.get("data", [])

        # ✅ spot extracted here
        spot = records.get("underlyingValue")

        ce_list = []
        pe_list = []

        for row in data_list:
            row_exp = self.normalize_exp(
                row.get("expiryDates") or row.get("expiryDate") or ""
            )

            if row_exp != expiry_norm:
                continue
            if row.get("CE") and row["CE"].get("strikePrice", 0) != 0:
                ce_list.append(row["CE"])
            if row.get("PE") and row["PE"].get("strikePrice", 0) != 0:
                pe_list.append(row["PE"])

        if not ce_list or not pe_list:
            return None, spot, expiry_norm

        ce_df = pd.DataFrame(ce_list)
        pe_df = pd.DataFrame(pe_list)
        merged = pd.merge(
            ce_df,
            pe_df,
            on="strikePrice",
            suffixes=("_CE", "_PE")
        )
        return merged, spot, expiry_norm

    # ---------------------------------------------------
    def get_strike_coi(self, df: pd.DataFrame, strike: int):
        row = df[df["strikePrice"] == strike]
        if row.empty:
            return None
        return {
            "strike": strike,
            "CE_COI": int(row["changeinOpenInterest_CE"].iloc[0]),
            "PE_COI": int(row["changeinOpenInterest_PE"].iloc[0])
        }

    # ---------------------------------------------------
    def get_range_coi(self, df: pd.DataFrame, start: int, end: int):
        rows = df[(df["strikePrice"] >= start) & (df["strikePrice"] <= end)]
        if rows.empty:
            return None
        return {
            "start_strike": start,
            "end_strike": end,
            "CE_COI_total": int(rows["changeinOpenInterest_CE"].sum()),
            "PE_COI_total": int(rows["changeinOpenInterest_PE"].sum())
        }

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    def _global_excepthook(exc_type, exc, tb):
        log_message(f"[FATAL] Unhandled exception: {exc_type.__name__}: {exc}")
        import traceback as _traceback
        log_message(_traceback.format_exc())

    def _thread_excepthook(args):
        log_message(f"[FATAL] Thread exception in {args.thread.name}: {args.exc_type.__name__}: {args.exc_value}")
        import traceback as _traceback
        log_message("".join(_traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = _global_excepthook
    threading.excepthook = _thread_excepthook
    # Start Telegram expiry/PnL reporter in background
    Thread(target=start_reporter, daemon=True).start()

    # Check license
    license_check_result = check_license()
    if license_check_result:
        if "License will expire in" in license_check_result:
            QMessageBox.warning(None, "License Warning", license_check_result)
        else:
            QMessageBox.critical(None, "License Error", license_check_result)
            sys.exit(app.exec())
    
    # Create and show main window
    window = ATMStrikePriceFinder()
    window.show()
    sys.exit(app.exec())
    
# Om Gan Ganapataye Namah  🙏
