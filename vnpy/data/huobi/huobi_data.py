# encoding: UTF-8

# 从huobi下载数据
from datetime import datetime, timezone

import requests
import execjs
import traceback
import base64
import datetime
import hashlib
import hmac
import json
import urllib
import urllib.parse
import urllib.request
import requests
from vnpy.trader.app.ctaStrategy.ctaBase import CtaBarData, CtaTickData

PERIOD_MAPPING = {}
PERIOD_MAPPING['1min']   = 'M1'
PERIOD_MAPPING['3min']   = 'M3'
PERIOD_MAPPING['5min']   = 'M5'
PERIOD_MAPPING['15min']  = 'M15'
PERIOD_MAPPING['30min']  = 'M30'
PERIOD_MAPPING['1hour']  = 'H1'
PERIOD_MAPPING['2hour']  = 'H2'
PERIOD_MAPPING['4hour']  = 'H4'
PERIOD_MAPPING['6hour']  = 'H6'
PERIOD_MAPPING['8hour']  = 'H8'
PERIOD_MAPPING['12hour'] = 'H12'
PERIOD_MAPPING['1day']   = 'D1'
PERIOD_MAPPING['1week']  = 'W1'
PERIOD_MAPPING['1month'] = 'M1'

PERIOD_LIST = ['1min','3min','5min','15min','30min','1day','1week','1hour','2hour','4hour','6hour','12hour']
SYMBOL_LIST = ['ltc_btc','eth_btc','etc_btc','bch_btc','btc_usdt','eth_usdt','ltc_usdt','etc_usdt','bch_usdt',
              'etc_eth','bt1_btc','bt2_btc','btg_btc','qtum_btc','hsr_btc','neo_btc','gas_btc', 'xrp_usdt',
              'qtum_usdt','hsr_usdt','neo_usdt','gas_usdt']

# API 请求地址
MARKET_URL = "https://api.huobi.pro"
TRADE_URL = "https://api.huobi.pro"

class HuobiData(object):
    # ----------------------------------------------------------------------
    def __init__(self, strategy):
        """
        构造函数
        :param strategy: 上层策略，主要用与使用strategy.writeCtaLog（）
        """
        self.strategy = strategy

        # 设置HTTP请求的尝试次数，建立连接session

        self.session = requests.session()
        self.session.keep_alive = False

    def http_get_request(url, params, add_to_headers=None):
        headers = {
            "Content-type": "application/x-www-form-urlencoded",
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.71 Safari/537.36',
        }
        if add_to_headers:
            headers.update(add_to_headers)
        postdata = urllib.parse.urlencode(params)
        response = requests.get(url, postdata, headers=headers, timeout=5)
        try:

            if response.status_code == 200:
                return response.json()
            else:
                return
        except BaseException as e:
            print("httpGet failed, detail is:%s,%s" % (response.text, e))
            return

    def get_bars(self, symbol, period, callback, bar_is_completed=False, bar_freq=1, start_dt=None):
        """
        返回k线数据
        symbol：合约
        period: 周期: 1min,3min,5min,15min,30min,1day,3day,1hour,2hour,4hour,6hour,12hour
        """
        size = 200
        params = {'symbol': symbol,
                  'period': period,
                  'size': size}

        url = MARKET_URL + '/market/history/kline'
        response = self.http_get_request(url, params)
        self.strategy.writeCtaLog('开始下载huobi数据:{}'.format(response))




