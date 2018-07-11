
#!-*-coding:utf-8 -*-
#@TIME    : 2018/5/12/0012 14:48
#@Author  : Nogo


class notifier(object):

    def __init__(self):
        self.observers = None

    def subscribe(self, observer):
        self.observers = observer

    def notify(self, action):
        if self.observers:
            self.observers(action)


class stream(object):

    def __init__(self):
        self.stream_error = notifier()
        self.stream_ticker = notifier()
        self.stream_klines = notifier()
        self.stream_depth = notifier()
        self.stream_marketTrades = notifier()
        self.stream_index = notifier()
        self.stream_forecast = notifier()
        self.stream_userinfo = notifier()
        self.stream_userTrades = notifier()
        self.stream_positions = notifier()

    def raiseError(self, data):
        self.stream_error.notify(data)

    def raiseTicker(self, data):
        self.stream_ticker.notify(data)

    def raiseKline(self, data):
        self.stream_klines.notify(data)

    def raiseDepth(self, data):
        self.stream_depth.notify(data)

    def raiseMarketTrades(self, data):
        self.stream_marketTrades.notify(data)

    def raiseIndex(self, data):
        self.stream_index.notify(data)

    def raiseForecast(self, data):
        self.stream_forecast.notify(data)

    def raiseUserinfo(self, data):
        self.stream_userinfo.notify(data)

    def raiseUserTrades(self, data):
        self.stream_userTrades.notify(data)

    def raisePositions(self, data):
        self.stream_positions.notify(data)