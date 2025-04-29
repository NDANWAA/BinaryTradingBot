#wwww.BinaryAcademy.uk
#Binary Options Trading Bot with EMA Strategy
#EDITED BY BINARY ACADEMY
#This bot uses EMA strategy to trade binary options on Deriv platform.
#It uses the Deriv API to place trades based on EMA signals.
#The bot is designed to be run in a simulated environment for testing purposes.
#It is not intended for live trading without proper testing and validation.
#Please use at your own risk.
#This bot is for educational purposes only and should not be considered as financial advice.
#Join our community at www.binaryacademy.uk for more resources and support.

#For customized trading strategies and advanced features, please visit our website or contact us directly.
#

import time
import datetime as dt
from datetime import datetime, timedelta
import json
import logging
import websocket
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from collections import deque
import datetime
import os
import threading
import queue

API_TOKEN = "replace_with_your_api_token"
APP_ID = "replace_with_your_app_id"
#Read Articles about how to create Deriv API Credentials on https://binaryacademy.uk/Artticles/
SYMBOL = "replace_with_your_symbol"
INITIAL_STAKE = 1.00  # Initial stake amount
# Define the multipliers for each consecutive loss
MULTIPLIERS = [10, 2, 2, 2]  
SAVE_DIR = "replace_with_your_save_directory/"
SLOPE_INCREMENT = 0.01  # Increment for slope denominator
TRADE_PAUSE_SECONDS = 2
RECONNECT_DELAY = 5
MAX_LOSSES = len(MULTIPLIERS)
WINDOW_SIZE = 50  
TRADE_DURATION = 5

current_stake = INITIAL_STAKE
trade_active = False
latest_contract_id = None
trade_end_time = None
simulation_mode = True
successful_simulations = 0
price_window = deque(maxlen=WINDOW_SIZE)
consecutive_losses = 0
price_window = deque(maxlen=WINDOW_SIZE)
previous_ema13 = None
last_direction = None 
log_queue = queue.Queue() 
current_time = datetime.datetime.now().strftime("%d%m%H")
loss_count = 0  
last_touch = False
first_touch_completed = False
test_price_1 = None
multiplier_index = 0  # Initialize multiplier index
initial_slope_denominator = 50  # Initial slope denominator for EMA calculation
slope_denominator = initial_slope_denominator  # Initialize slope denominator

PROFIT_LOG_PATH = f"{SAVE_DIR}profit_{SYMBOL}_{current_time}.csv"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def place_trade(ws, action, ema50_slope, short_slope):
    """
    Places a trade based on the given action. Validates action format.
    """
    global trade_active, current_stake, latest_contract_id, trade_end_time

    # Check for slope conflicts
    if ema50_slope is not None and short_slope is not None:
        if ema50_slope * short_slope < 0:
            logging.info(f"Slopes are conflicting: EMA50 Slope={ema50_slope:.5f}, Short Slope={short_slope:.5f}. Skipping trade.")
            return

    # Check if action is valid and trade is not already active
    if action is None or trade_active:
        logging.info("No trade placed: No action or trade already active.")
        return

    if not isinstance(action, tuple) or len(action) != 3:
        logging.error(f"Invalid action format received: {action} (type={type(action)})")
        return

    try:
        # Unpack the action tuple
        direction, duration, duration_unit = action
        if not isinstance(direction, int) or not isinstance(duration, int) or not isinstance(duration_unit, str):
            raise ValueError("Action components must be (int, int, str).")

        # Round the stake to 2 decimal places
        stake = round(current_stake, 2)

        # Construct the trade request
        trade_request = {
            "buy": 1,
            "price": stake,
            "parameters": {
                "amount": stake,
                "basis": "stake",
                "contract_type": "CALL" if direction == 0 else "PUT",
                "currency": "USD",
                "duration": duration,
                "duration_unit": duration_unit,
                "symbol": SYMBOL,
            }
        }

        # Send trade request via WebSocket
        ws.send(json.dumps(trade_request))
        logging.info(f"Trade request sent: {trade_request}")

        # Mark the trade as active and set the trade end time
        trade_active = True
        trade_end_time = dt.datetime.utcnow() + timedelta(seconds=duration)

    except Exception as e:
        logging.error(f"Error placing trade: {e}")
        trade_active = False


def process_tick(ws, tick):
    global trade_active, trade_end_time, latest_contract_id, price_window
    global last_touch, first_touch_completed, test_price_1

    if trade_active:
        if latest_contract_id and dt.datetime.utcnow() >= trade_end_time:
            check_trade_result(ws, latest_contract_id)
        return

    price = tick.get('quote')
    if price is None:
        logging.warning("Missing 'quote' in tick. Skipping.")
        return

    price_window.append(float(price))

    if len(price_window) >= 50:
        # Calculate EMAs
        ema50_values = pd.Series(price_window).ewm(span=50, adjust=False).mean()
        ema50 = ema50_values.iloc[-1]
        ema21 = pd.Series(price_window).ewm(span=21, adjust=False).mean().iloc[-1]
        ema13 = pd.Series(price_window).ewm(span=13, adjust=False).mean().iloc[-1]
        ema3 = pd.Series(price_window).ewm(span=3, adjust=False).mean().iloc[-1]

        # Calculate slopes
        ema50_slope = (ema50_values.iloc[-1] - ema50_values.iloc[-50]) / initial_slope_denominator
        short_slope = (price_window[-1] - price_window[-3]) / 3

        logging.info(
            f"EMA Values -> EMA3: {ema3:.5f}, EMA13: {ema13:.5f}, EMA21: {ema21:.5f}, EMA50: {ema50:.5f}, Price: {price:.5f}"
        )
        logging.info(f"Slopes -> EMA50 Slope: {ema50_slope:.5f}, Short Slope: {short_slope:.5f}")

        # Filter slope conflicts
        if ema50_slope * short_slope < 0:
            logging.info("Slopes are conflicting. Skipping trade.")
            return

        # Detect trends
        uptrend = ema13 > ema21 > ema50 and ema50_slope > 0.023
        downtrend = ema13 < ema21 < ema50 and ema50_slope < -0.023

        # Uptrend logic
        if uptrend:
            logging.info("Uptrend detected: EMA13 > EMA21 > EMA50.")
            if ema3 > price > ema21:
                if not first_touch_completed:
                    logging.info("First touch detected in uptrend. Marking the zone.")
                    first_touch_completed = True
                    last_touch = "uptrend"
                elif first_touch_completed and last_touch == "uptrend":
                    logging.info("Second touch detected. Placing CALL trade.")
                    place_trade(ws, (0, TRADE_DURATION, "t"), ema50_slope, short_slope)
            elif price > ema21 or price < ema3:
                logging.info("Price exited the EMA3-EMA21 range after first touch. Waiting for Second Touch.")

        # Downtrend logic
        elif downtrend:
            logging.info("Downtrend detected: EMA13 < EMA21 < EMA50.")
            if ema3 < price < ema21:
                if not first_touch_completed:
                    logging.info("First touch detected in downtrend. Marking the zone.")
                    first_touch_completed = True
                    last_touch = "downtrend"
                elif first_touch_completed and last_touch == "downtrend":
                    logging.info("Second touch detected. Placing PUT trade.")
                    place_trade(ws, (1, TRADE_DURATION, "t"), ema50_slope, short_slope)
            elif price < ema21 or price > ema3:
                logging.info("Price exited the EMA3-EMA21 range after first touch. Waiting for Second Touch.")
        else:
            logging.info("No clear trend detected. Skipping trade.")

def reset_trade_conditions():
    """Reset tracking variables for the next signal."""
    global first_touch_completed, last_touch
    logging.info("Resetting trade conditions for next signal.")
    first_touch_completed = False
    last_touch = None


def on_message(ws, message):
    global latest_contract_id

    try:
        data = json.loads(message)
        logging.debug(f"WebSocket message received: {data}")

        if 'authorize' in data:
            logging.info("Authorization successful.")
            ws.send(json.dumps({"ticks": SYMBOL, "subscribe": 1}))
            logging.info("Subscription request sent.")

        elif 'tick' in data:
            process_tick(ws, data['tick'])

        elif 'buy' in data:
            if 'error' in data:
                logging.error(f"Trade placement failed: {data['error']['message']}")
            else:
                latest_contract_id = data['buy'].get('contract_id')
                if latest_contract_id:
                    logging.info(f"Trade placed successfully: Contract ID={latest_contract_id}")

        elif 'proposal_open_contract' in data:
            contract = data.get('proposal_open_contract', {})
            if contract.get('is_sold'):
                profit = contract.get('profit', 0)
                logging.info(f"Trade result received. Profit: {profit}")
                handle_trade_result(profit)

    except Exception as e:
        logging.error(f"Unexpected error while processing WebSocket message: {e}")


def check_trade_result(ws, contract_id):
    """
    Sends a request to check the trade result of a specific contract ID.
    """
    try:
        result_request = {
            "proposal_open_contract": 1,
            "contract_id": contract_id,
        }
        ws.send(json.dumps(result_request))
        logging.info(f"Requested result for Contract ID {contract_id}.")
    except Exception as e:
        logging.error(f"Failed to request trade result: {e}")

def handle_trade_result(profit):
    """
    Processes the trade result, updates stake based on multipliers, and resets on win or after exhausting multipliers.
    """
    global current_stake, consecutive_losses, trade_active, multiplier_index, slope_denominator

    trade_active = False

    if profit > 0:  
        logging.info(f"Trade won. Profit: {profit}. Resetting stake and multipliers.")
        current_stake = INITIAL_STAKE
        consecutive_losses = 0
        multiplier_index = 0  # Reset multiplier index on win
        slope_denominator = initial_slope_denominator  # Reset slope denominator
    else:  
        consecutive_losses += 1
        if multiplier_index < MAX_LOSSES - 1:
            current_stake *= MULTIPLIERS[multiplier_index]
            multiplier_index += 1  # Increment multiplier index
            slope_denominator += SLOPE_INCREMENT  # Increase slope denominator
            logging.info(f"Trade lost. Updating stake to {current_stake:.2f} and slope denominator to {slope_denominator}.")
        else:
            current_stake = INITIAL_STAKE
            multiplier_index = 0  # Reset multiplier index if max losses reached
            slope_denominator = initial_slope_denominator  # Reset slope denominator
        logging.info(
            f"Trade lost. Updating stake to {current_stake:.2f}, multiplier index: {multiplier_index}, "
        )

    log_profit_and_losses(profit, consecutive_losses)


def async_logger():
    """
    Continuously writes logs from the log_queue to the CSV file.
    Runs in a separate thread to avoid blocking the main workflow.
    """
    while True:
        try:
            profit, losses = log_queue.get()
            if profit is None and losses is None: 
                break

            os.makedirs(SAVE_DIR, exist_ok=True)

            file_exists = os.path.isfile(PROFIT_LOG_PATH)
            if not file_exists:
                with open(PROFIT_LOG_PATH, mode='w', newline='') as file:
                    file.write("Profit,Consecutive_Losses\n") 

            with open(PROFIT_LOG_PATH, mode='a', newline='') as file:
                file.write(f"{profit},{losses}\n")

            log_queue.task_done()
        except Exception as e:
            logging.error(f"Error in async logger: {e}")
            time.sleep(1) 

logger_thread = threading.Thread(target=async_logger, daemon=True)
logger_thread.start()

def log_profit_and_losses(profit, losses):
    """
    Adds profit and losses to the logging queue for asynchronous processing.
    """
    try:
        log_queue.put((profit, losses))
        logging.info(f"Queued profit: {profit}, Consecutive losses: {losses}")
    except Exception as e:
        logging.error(f"Error queuing profit and losses: {e}")

def run_bot():
    ws_url = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"

    def on_open(ws):
        logging.info("WebSocket connection opened.")
        ws.send(json.dumps({"authorize": API_TOKEN}))

    def on_close(ws, close_status_code, close_msg):
        logging.warning(f"WebSocket closed: {close_status_code}, {close_msg}")
        time.sleep(RECONNECT_DELAY)
        run_bot()

    def on_error(ws, error):
        logging.error(f"WebSocket error: {error}")
        time.sleep(RECONNECT_DELAY)
        run_bot()

    ws = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_close=on_close,
        on_error=on_error,
    )
    ws.run_forever(ping_interval=30, ping_timeout=10)


if __name__ == "__main__":
    run_bot()
