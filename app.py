from flask import Flask, request, jsonify
from lumibot.brokers import Alpaca
from lumibot.backtesting import YahooDataBacktesting
from lumibot.strategies.strategy import Strategy
from lumibot.traders import Trader
from datetime import datetime
from alpaca_trade_api import REST
from timedelta import Timedelta
from finbert_utils import estimate_sentiment
import multiprocessing
import logging
from flask_cors import CORS

API_KEY = "PKLCVJU4KFGW6P7JO2BW"
API_SECRET = "WvpwMXCyAhV3NjncwihgSldhpaXU4HdYEDozFeUI"
BASE_URL = "https://paper-api.alpaca.markets"

ALPACA_CREDS = {
    "API_KEY": API_KEY,
    "API_SECRET": API_SECRET,
    "PAPER": True
}

logging.basicConfig(level=logging.DEBUG)

class MLTrader(Strategy):
    def initialize(self, symbol: str = "SPY", cash_at_risk: float = .5):
        self.symbol = symbol
        self.sleeptime = "24H"
        self.last_trade = None
        self.cash_at_risk = cash_at_risk
        self.api = REST(base_url=BASE_URL, key_id=API_KEY, secret_key=API_SECRET)

    def position_sizing(self):
        cash = self.get_cash()
        last_price = self.get_last_price(self.symbol)
        quantity = round(cash * self.cash_at_risk / last_price, 0)
        return cash, last_price, quantity

    def get_dates(self):
        today = self.get_datetime()
        three_days_prior = today - Timedelta(days=3)
        return today.strftime('%Y-%m-%d'), three_days_prior.strftime('%Y-%m-%d')

    def get_sentiment(self):
        today, three_days_prior = self.get_dates()
        news = self.api.get_news(symbol=self.symbol,
                                 start=three_days_prior,
                                 end=today)
        news = [ev.__dict__["_raw"]["headline"] for ev in news]
        probability, sentiment = estimate_sentiment(news)
        return probability, sentiment

    def on_trading_iteration(self):
        cash, last_price, quantity = self.position_sizing()
        probability, sentiment = self.get_sentiment()

        if cash > last_price:
            if sentiment == "positive" and probability > .999:
                if self.last_trade == "sell":
                    self.sell_all()
                order = self.create_order(
                    self.symbol,
                    quantity,
                    "buy",
                    type="bracket",
                    take_profit_price=last_price * 1.20,
                    stop_loss_price=last_price * .95
                )
                self.submit_order(order)
                self.last_trade = "buy"
            elif sentiment == "negative" and probability > .999:
                if self.last_trade == "buy":
                    self.sell_all()
                order = self.create_order(
                    self.symbol,
                    quantity,
                    "sell",
                    type="bracket",
                    take_profit_price=last_price * .8,
                    stop_loss_price=last_price * 1.05
                )
                self.submit_order(order)
                self.last_trade = "sell"

def run_backtest(symbol, start_date, end_date, cash_at_risk):
    try:
        broker = Alpaca(ALPACA_CREDS)
        strategy = MLTrader(name='mlstrat', broker=broker,
                           parameters={"symbol": symbol,
                                       "cash_at_risk": cash_at_risk})
        strategy.backtest(
            YahooDataBacktesting,
            start_date,
            end_date,
            parameters={"symbol": symbol, "cash_at_risk": cash_at_risk}
        )
        trader = Trader()
        trader.add_strategy(strategy)
        trader.run_all()
        logging.info("Backtest completed successfully.")
    except Exception as e:
        logging.error(f"Error during backtest: {e}")

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

@app.route('/run_strategy', methods=['POST'])
def run_strategy():
    data = request.json
    symbol = data.get('symbol', 'SPY')
    start_date = datetime.strptime(data.get('start_date', '2020-01-01'), '%Y-%m-%d')
    end_date = datetime.strptime(data.get('end_date', '2023-12-31'), '%Y-%m-%d')
    cash_at_risk = float(data.get('cash_at_risk', 0.5))

    logging.info(f"Received data: symbol={symbol}, start_date={start_date}, end_date={end_date}, cash_at_risk={cash_at_risk}")

    process = multiprocessing.Process(target=run_backtest, args=(symbol, start_date, end_date, cash_at_risk))
    process.start()
    process.join()

    return jsonify({"message": "Strategy executed successfully"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001,debug=True)
