
#!-*-coding:utf-8 -*-
#@TIME    : 2018/6/11/0011 15:32
#@Author  : Nogo

import math
import time
import talib
import numpy as np
import logging
from collections import defaultdict
from threading import Thread


from fcoin import Fcoin
from WSS.fcoin_client import fcoin_client
from balance import balance
import config

class wss_app():

    def __init__(self):
        self.client = fcoin_client()
        self.client.stream.stream_depth.subscribe(self.depth)
        self.client.stream.stream_klines.subscribe(self.candle)
        self.client.stream.stream_ticker.subscribe(self.ticker)
        self.fcoin = Fcoin()
        self.fcoin.auth(config.key, config.secret)

        self.buy_price = None               #买1价
        self.buy_amount = None              #买1量
        self.sell_price = None              #卖1价
        self.sell_amount = None             #卖1量
        self.ts = None                      #深度更新时间

        self.market_price = None            #市价

        self.total_bids = 0
        self.total_asks = 0

        self.filled_buy_order_list = []
        self.order_list = defaultdict(lambda: None)
        self.buy_order_id = None
        self.dic_balance = defaultdict(lambda: None)
        self.time_order = time.time()

        self.price_list = []
        self.candle_list = None
        self.SMA = None
        self._init_log()

    #日志初始化
    def _init_log(self):
        self._log = logging.getLogger(__name__)
        self._log.setLevel(level=logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(message)s') #格式

        '''
        保存文档
        '''
        handler = logging.FileHandler("app.log")
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        self._log.addHandler(handler)

        '''
        控制台显示
        '''
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        self._log.addHandler(console)

    #精度控制，直接抹除多余位数，非四舍五入
    def digits(self, num, digit):
        site = pow(10, digit)
        tmp = num * site
        tmp = math.floor(tmp) / site
        return tmp

    #wss订阅深度接收
    def depth(self, data):
        bids = data['bids']
        asks = data['asks']

        self.ts = time.time()
        
        self.buy_price = bids[0]  # 买
        self.buy_amount = bids[1]
        self.sell_price = asks[0]  # 卖
        self.sell_amount = asks[1]

        for i in range(3):
            self.total_bids += bids[2 * i - 1]
            self.total_asks += asks[2 * i - 1]

    # wss订阅K线接收
    def candle(self, data):
        if self.candle_list is None:
            self.candle_list = [{'timestamp': data['id'],
                                 'open': data['open'],
                                 'high': data['high'],
                                 'low': data['low'],
                                 'close': data['close'],
                                 'volume': data['base_vol']}]
        else:
            last_candle = self.candle_list[-1]
            if last_candle['timestamp'] == data['id']:
                self.candle_list[-1] = {'timestamp': data['id'],
                                        'open': data['open'],
                                        'high': data['high'],
                                        'low': data['low'],
                                        'close': data['close'],
                                        'volume': data['base_vol']}
            else:
                self.candle_list.append({'timestamp': data['id'],
                                         'open': data['open'],
                                         'high': data['high'],
                                         'low': data['low'],
                                         'close': data['close'],
                                         'volume': data['base_vol']})


            if len(self.candle_list) > 10:
                self.candle_list.pop(0)

        if len(self.candle_list) >= 7:
            close_array = np.array([item['close'] for item in self.candle_list])
            self.SMA = talib.SMA(close_array, timeperiod=7)

    #市价
    def ticker(self, data):
        self.ts = time.time()
        self.market_price = data['ticker'][0]

    #刷单流程
    def process(self):

        if self.ts and time.time() - self.ts < 10 and self.buy_price and self.market_price:
            price = self.market_price if config.fix_price == 0 else config.fix_price
            amount = 0

            '''
            挂卖单
            '''
            success_item_list = []
            for item in self.filled_buy_order_list:
                amount = self.digits(item['amount'], config.symbol['amount_precision'])
                price = self.digits(max(item['price'], price), config.symbol['price_precision'])
                order = [amount,price]
                if amount >= config.symbol['min_amount']:
                    success, data = self.fcoin.sell(config.symbol['name'], price, amount)  # 卖
                    if success:
                        success_item_list.append(item)
                        self.order_list[data['data']] = order
                        self._log.info('挂卖单成功[%s:%s]' % (amount, price))

            '''
            删除已成功订单
            '''
            for item in success_item_list:
                self.filled_buy_order_list.remove(item)

            keys = []
            for key in self.order_list.keys():
                success, data = self.fcoin.get_order(key)
                if success:
                    state = data['data']['state']
                    if state == 'filled':
                        keys.append([0, key])
                    elif state in ('partial_canceled', 'canceled'):
                        keys.append([1, key])

            for tag, key in keys:
                self.order_list.pop(key)
                if tag == 0:
                    self._log.info('已经成交：' + key)
                else:
                    self._log.info('已经撤单：' + key)

            '''
            买单不存在时
            '''
            if not self.buy_order_id:
                '''
                 价格异动识别,可以根据实际情况改动,价格固定时无效
                 '''
                if config.fix_price == 0:
                    if abs(self.buy_price - self.sell_price) > 0.5:
                        self._log.info('价格异动买卖差价:%s' % abs(self.buy_price - self.sell_price))
                        return
                    elif self.SMA is None:
                        if len(self.price_list) > 0:
                            avg = sum(self.price_list) / len(self.price_list)
                            if abs(avg - self.buy_price) > 10:
                                self._log.info('价格异动avg:%s [%s]' % (avg, self.buy_price))
                                self.price_list.append(self.buy_price)
                                self.price_list.append(self.sell_price)
                                if len(self.price_list) >= 120:
                                    self.price_list.pop(0)
                                return
                        else:
                            self.price_list.append(self.buy_price)
                            self.price_list.append(self.sell_price)
                    else:
                        last = self.SMA[-2]
                        if not np.isnan(last):
                            if abs(self.buy_price - last) >= 0.5:
                                self._log.info('价格异动:%s' % abs(self.buy_price - last))
                                return

                '''
                查询余额度
                '''
                self.dic_balance = self.get_balance()

                '''
                判断币种持仓量，到设定值停止买入。
                '''
                coin = self.dic_balance[config.symbol['coin']]
                if coin and coin.balance > config.limit_amount:
                    self._log.info('%s余额度达到最大值[%s]' % (config.symbol['coin'],coin.balance))
                    return
                '''
                挂买单
                '''
                usdt = self.dic_balance['usdt']
                if usdt:
                    if config.fix_price:
                        diff = abs(config.fix_price - self.market_price)
                        if config.diff_price < diff:
                            self._log.info('固定价格模式差价异常[%-0.2f]' % diff)
                            return

                    price = self.market_price if config.fix_price == 0 else config.fix_price
                    if usdt.available > price * config.max_amount:
                        amount = config.max_amount if self.total_bids > config.total_amount and self.total_asks > config.total_amount else config.min_amount
                    else:
                        amount = usdt.available/price
                    amount = self.digits(amount, config.symbol['amount_precision'])
                    if amount >= config.symbol['min_amount']:
                        price = self.digits(price, config.symbol['price_precision'])
                        success, data = self.fcoin.buy(config.symbol['name'], price, amount)  # 买
                        if success:
                            self.time_order = time.time()
                            self.buy_order_id = data['data']
                            self._log.info('挂买单成功[%s:%s]' % (amount, price))
                    else:
                        self._log.info('usdt不足[%s]' % (usdt.available))
                else:
                    self._log.info('查询余额错误')
            else:
                '''
                买单ID存在时查询订单状态
                '''
                success, data = self.fcoin.get_order(self.buy_order_id)
                if success:
                    state = data['data']['state']
                    amount = float(data['data']['filled_amount']) - float(data['data']['fill_fees'])
                    price = float(data['data']['price'])

                    if amount > 0 and state in ('filled', 'partial_canceled'):
                        self.filled_buy_order_list.append({'price': price, 'amount': amount})

                    if state == 'filled':
                        self.buy_order_id = None
                        self._log.info('买单已成交')

                    elif state == 'canceled' or state == 'partial_canceled':
                        self.buy_order_id = None
                        self._log.info('买单已撤单')

                    elif state not in ('pending_cancel'):
                        '''
                        超时判断
                        '''
                        if time.time() - self.time_order >= config.delay:
                            self.fcoin.cancel_order(self.buy_order_id)
                            self._log.info('%s秒超时撤单' % config.delay)
        else:
            self._log.info('等待WebSocket数据……')

    #循环
    def loop(self):

        if config.min_amount < config.symbol['min_amount'] or config.min_amount < config.symbol['min_amount']:
            self._log.info('max_amount,min_amount ≥ 规定的最小数量[%s]' % (config.symbol['min_amount']))
            return

        self.client.start()

        while not self.client.isConnected:
            self._log.info('waitting……')
            time.sleep(1)

        self.client.subscribe_depth(config.symbol['name'], 'L20')
        self.client.subscribe_candle(config.symbol['name'], 'M1')
        self.client.subscribe_ticker(config.symbol['name'])
        while True:
            try:
                self.process()
            except Exception as error:
                self._log.info('未知错误')
            time.sleep(0.5)

    #获取余额
    def get_balance(self):
        dic_balance = defaultdict(lambda: None)
        success, data = self.fcoin.get_balance()
        if success:
            for item in data['data']:
                dic_balance[item['currency']] = balance(float(item['available']), float(item['frozen']),float(item['balance']))
        return dic_balance

    #获取订单
    def get_orders(self, symbol, states, limit=1):
        '''
        :param symbol:
        :param states: submitted/partial_filled/partial_canceled/canceled/pending_cancel/filled
        :return:
        '''
        success, data = self.fcoin.list_orders(symbol=symbol, states=states, limit=limit)
        if success:
            return data['data']
        else:
            print(data)
            return None

if __name__ == '__main__':
    run = wss_app()
    thread = Thread(target=run.loop)
    thread.start()
    thread.join()
    print('done')