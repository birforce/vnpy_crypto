# encoding: UTF-8

# 从bitmex载数据
from datetime import datetime, timezone
import sys
import requests
import execjs
import traceback
from vnpy.trader.app.ctaStrategy.ctaBase import CtaBarData, CtaTickData
from vnpy.trader.vtFunction import systemSymbolToVnSymbol

period_list = ['1m', '5m', '1h', '1d']
symbol_list = ['XBTUSD', 'XRPU18']


class BitmexData(object):

    # ----------------------------------------------------------------------
    def __init__(self, strategy=None):
        """
        构造函数
        :param strategy: 上层策略，主要用与使用strategy.writeCtaLog（）
        """
        self.strategy = strategy

        # 设置HTTP请求的尝试次数，建立连接session
        requests.adapters.DEFAULT_RETRIES = 5
        self.session = requests.session()
        self.session.keep_alive = False

    def writeLog(self, content):
        if self.strategy:
            self.strategy.writeCtaLog(content)
        else:
            print(content)

    def writeError(self, content):
        if self.strategy:
            self.strategy.writeCtaError(content)
        else:
            print(content, file=sys.stderr)

    def get_bars(self, symbol, period, callback, bar_is_completed=False,bar_freq=1, start_dt=None):
        """
        返回k线数据
        symbol：合约
        period: 周期: 1min,3min,5min,15min,30min,1day,3day,1hour,2hour,4hour,6hour,12hour
        """
        ret_bars = []
        symbol = symbol.upper()

        if symbol not in symbol_list:
            msg = u'{} {}不在下载清单中'.format(datetime.now(), symbol)
            if self.strategy:
                self.strategy.writeCtaError(msg)
            else:
                print(msg)
            return False,ret_bars

        if period not in period_list:
            self.writeError(u'{}不在下载时间周期范围:{} 内'.format(period, period_list))
            return False,ret_bars

        candleCount = 200
        url = u'https://www.bitmex.com/api/v1/trade/bucketed?binSize={}&partial=false&symbol={}&count={}&reverse=true'.format(period, symbol, candleCount)

        self.writeLog('{}开始下载:{} {}数据.URL:{}'.format(datetime.now(), symbol, period, url))

        content = None
        try:
            content = self.session.get(url).content.decode('gbk')
        except Exception as ex:
            self.writeError('exception in get:{},{},{}'.format(url, str(ex), traceback.format_exc()))
            return False,ret_bars

        bars = execjs.eval(content)

        if not isinstance(bars, list):
            self.writeError('返回数据不是list:{}'.format(content))
            return False,ret_bars
        # example bar:
        # {"timestamp":"2018-08-09T02:37:00.000Z","symbol":"XBTUSD","open":6313.5,"high":6313.5,"low":6313,"close":6313.5,
        # "trades":63,"volume":243870,"vwap":6313.5299,"lastSize":1000,"turnover":3862773286,"homeNotional":38.62773286,
        # "foreignNotional":243870}
        for i, bar in enumerate(bars):
            add_bar = CtaBarData()
            try:
                add_bar.vtSymbol = bar['symbol']
                add_bar.symbol = bar['symbol']
                raw_datetime = bar['timestamp']
                raw_datetime = raw_datetime.split('T')
                add_bar.date = raw_datetime[0]
                add_bar.time = raw_datetime[1][:-5]
                date = add_bar.date.split('-')
                time = add_bar.time.split(':')
                add_bar.datetime = datetime(
                    int(date[0]), int(date[1]), int(date[2]), int(time[0]), int(time[1]), int(time[2]))
                add_bar.tradingDay = add_bar.date
                add_bar.open = bar['open']
                add_bar.high = bar['high']
                add_bar.low = bar['low']
                add_bar.close = bar['close']
                add_bar.volume = bar['volume']
            except Exception as ex:
                self.strategy.writeCtaError('error when convert bar:{},ex:{},t:{}'.format(bar, str(ex), traceback.format_exc()))
                return False,ret_bars

            if start_dt is not None and bar.datetime < start_dt:
                continue

            if callback is not None:
                callback(add_bar, bar_is_completed, bar_freq)

            ret_bars.append(add_bar)

        return True,ret_bars

class TestStrategy(object):

    def __init__(self):

        self.minDiff = 1
        self.vtSymbol = 'XBTUSD'

        self.TMinuteInterval = 1
    def addBar(self,bar,bar_is_completed, bar_freq):
        print(u'tradingDay:{},dt:{},{} o:{},h:{},l:{},c:{},v:{}'.format(bar.tradingDay, bar.datetime,bar.vtSymbol, bar.open, bar.high,
                                                                     bar.low, bar.close, bar.volume))
    def onBar(self, bar):
        print(u'tradingDay:{},dt:{},{} o:{},h:{},l:{},c:{},v:{}'.format(bar.tradingDay,bar.datetime,bar.vtSymbol, bar.open, bar.high, bar.low, bar.close, bar.volume))

    def writeCtaLog(self, content):
        print(content)

    def writeCtaError(self, content):
        print(content)


if __name__ == '__main__':
    t = TestStrategy()

    hb_data = BitmexData(t)

    bars = hb_data.get_bars(symbol='XBTUSD', period='1m', callback=None)

    for bar in bars[1]:
        print(bar.datetime)