# encoding: UTF-8

"""
一个根据一分钟K线开/平仓的策略。当遇到阳线时，开多单或平空单。
此策略暂时用于Bitmex交易所，其他交易所尚未测试。
date: 2018-08-09
"""

import os
import sys
from datetime import datetime, timedelta, date

import talib
import numpy as np

from vnpy.trader.app.ctaStrategy.ctaBase import *
from vnpy.trader.app.ctaStrategy.ctaBacktesting import BacktestingEngine
from vnpy.trader.app.ctaStrategy.ctaLineBar import *
from vnpy.trader.app.ctaStrategy.ctaEngine import *
from vnpy.trader.app.ctaStrategy.ctaTemplate import CtaTemplate
from vnpy.trader.vtConstant import EXCHANGE_OKEX, EXCHANGE_BINANCE, EXCHANGE_GATEIO, EXCHANGE_FCOIN, EXCHANGE_HUOBI, EXCHANGE_BITMEX

#####################################################################################
class OneStep1MAStrategy(CtaTemplate):
    className = 'OneStep1MAStrategy'
    author = u'比特量能'

    # 策略在外部设置的参数
    inputVolume = 10  # 下单手数，范围是1~100，步长为1，默认=1
    min_trade_volume = 0.0001  # 商品的下单最小成交单位

    # ----------------------------------------------------------------------
    def __init__(self, ctaEngine, setting):
        """Constructor"""
        super(OneStep1MAStrategy, self).__init__(ctaEngine, setting)

        self.exchange = EXCHANGE_BITMEX
        self.gateway = u'BITMEX_1'
        self.vtSymbol = u'XBTUSD'
        self.vtSymbolWithExchange = '.'.join([self.vtSymbol, self.exchange])

        self.paramList.append('inputVolume')  # 下单手数
        self.paramList.append('min_trade_volume')  # 该商品下单最小成交单位
        self.varList.append('position')  # 交易所交易货币仓位

        self.curDateTime = None  # 当前时间
        self.is_7x24 = True

        self.exchange_position = EMPTY_STRING  # 交易所交易货币仓位
        self.pos = EMPTY_INT  # 交易所交易货币仓位, 回测时用

        self.last_tick = None  # 交易所比对得最后一个ticket
        self.base_position = None  # 交易所交易主货币持仓
        self.quote_position = None  # 交易所基准货币持仓

        self.lastTradedTime = datetime.now()  # 上一交易时间

        # 是否完成了策略初始化
        self.isInited = False
        # 交易状态
        self.trading = False

        self.lineM1 = None  # M1K线
        lineM1Setting = {}
        lineM1Setting['name'] = u'LineM1'
        lineM1Setting['barTimeInterval'] = 60  # bar時間間隔,60秒
        lineM1Setting['shortSymbol'] = self.vtSymbol  # 商品短号
        lineM1Setting['is_7x24'] = self.is_7x24
        self.lineM1 = CtaLineBar(self, self.onBar, lineM1Setting)  # M1K线：CtaLineBar对象

        self.logMsg = EMPTY_STRING  # 临时输出日志变量

        self.orderList = []  # 保存委托代码的列表

    # ----------------------------------------------------------------------
    def onInit(self):
        """初始化策略（必须由用户继承实现）"""
        self.writeCtaLog(u'%s策略初始化' % self.name)

        line1MBarAvailabled = False
        if not self.backtesting:
            # 获取交易所数据源对象
            ds = self.get_data_source(self.exchange)
            # 返回交易所获得的1分钟Bar数据（合约代码；时间间隔：1分钟；主交易货币对M1K线.加入一个Bar）
            line1MBarAvailabled, history_bars = ds.get_bars(self.vtSymbol, period='1m',
                                                                    callback=self.lineM1.addBar)

        # 更新初始化标识和交易标识
        if line1MBarAvailabled or self.backtesting:
            self.isInited = True  # 策略初始化状态
            self.trading = True  # 交易状态

            self.putEvent()  # 策略状态变化事件
            self.writeCtaLog(u'策略初始化完成')

    def get_data_source(self, exchange_name):
        """
        获取数据源
        :param:exchange_name:交易所名
        :return:ds:交易所数据类
        """
        ds = None
        if exchange_name == EXCHANGE_OKEX:
            from vnpy.data.okex.okex_data import OkexData
            # 初始化OkexData对象（设置HTTP请求的尝试次数，建立连接session）
            ds = OkexData(self)
        elif exchange_name == EXCHANGE_BINANCE:
            from vnpy.data.binance.binance_data import BinanceData
            ds = BinanceData(self)
        elif exchange_name == EXCHANGE_GATEIO:
            from vnpy.data.gateio.gateio_data import GateioData
            ds = GateioData(self)
        elif exchange_name == EXCHANGE_FCOIN:
            from vnpy.data.fcoin.fcoin_data import FcoinData
            ds = FcoinData(self)
        elif exchange_name == EXCHANGE_HUOBI:
            from vnpy.data.huobi.huobi_data import HuobiData
            ds = HuobiData(self)
        elif exchange_name == EXCHANGE_BITMEX:
            from vnpy.data.bitmex.bitmex_data import BitmexData
            ds = BitmexData(self)

        return ds

    # ----------------------------------------------------------------------
    def onStart(self):
        """启动策略（必须由用户继承实现）"""
        self.writeCtaLog(u'%s策略启动' %self.name)
        self.putEvent()

    # ----------------------------------------------------------------------
    def onStop(self):
        """停止策略（必须由用户继承实现）"""
        self.writeCtaLog(u'%s策略停止' %self.name)
        self.putEvent()

    # ----------------------------------------------------------------------
    def onTick(self, tick):
        """收到行情TICK推送（必须由用户继承实现）"""

        # 更新策略执行的时间（用于回测时记录发生的时间）
        self.curDateTime = tick.datetime
        # 记录最新tick
        self.last_tick = tick

        # 首先检查是否已经初始化策略
        if not self.isInited:
            return

        # 推送至1分钟K线
        if tick.vtSymbol == self.vtSymbolWithExchange:
            self.lineM1.onTick(tick)

    # -------------------------------------------------------------
    # 当生成新的bar时判断是否交易
    def onBar(self, bar):
        # self.writeCtaLog("收到新Bar {}".format(self.lineM1.displayLastBar()))

        # 首先检查是否已经初始化策略
        if not self.isInited:
            return

        if self.backtesting:
            self.lineM1.lineBar.append(bar)
            # self.writeCtaLog("Bar的数量 {}".format(len(self.lineM1.lineBar)))

        # 当没有足够数据时先返回
        if len(self.lineM1.lineBar) < 2:
            return

        # 撤销未完成订单
        for orderID in self.orderList:
            self.cancelOrder(orderID)
        self.orderList = []

        # 读交易所仓位
        self.exchange_position = self.ctaEngine.posBufferDict.get(
            '.'.join([self.vtSymbol, self.exchange]),
            None)

        # self.writeCtaLog("Bar open:{}, close {}".format(self.lineM1.lineBar[-2].open, self.lineM1.lineBar[-2].close))

        # 交易逻辑
        # 当M1 K线为阳线时, tick来时平掉空单, 若没有多单则加一手多单
        if self.lineM1.lineBar[-2].close > self.lineM1.lineBar[-2].open:
            # self.writeCtaLog("阳线")
            if not self.backtesting:
                if self.exchange_position.longPosition < 0:
                    orderID = self.buy(self.last_tick.askPrice1, abs(self.exchange_position.longPosition))

                    self.orderList.append(orderID)
                if self.exchange_position.longPosition == 0:
                    orderID = self.buy(self.last_tick.askPrice1, self.inputVolume)
                    self.orderList.append(orderID)
            else:
                if self.pos < 0:
                    orderID = self.buy(self.lineM1.lineBar[-1].close, abs(self.pos))
                if self.pos == 0:
                    orderID = self.buy(self.lineM1.lineBar[-1].close, self.inputVolume)

        # 当M1 K线为阴线时, tick来时平掉多单, 若没有空单则加一手空单
        if self.lineM1.lineBar[-2].close < self.lineM1.lineBar[-2].open:
            # self.writeCtaLog("阴线")
            if not self.backtesting:
                if self.exchange_position.longPosition > 0:
                    orderID = self.sell(self.last_tick.bidPrice1, self.exchange_position.longPosition)
                    self.orderList.append(orderID)
                if self.exchange_position.longPosition == 0:
                    orderID = self.sell(self.last_tick.bidPrice1, self.inputVolume)
                    self.orderList.append(orderID)
            else:
                if self.pos > 0:
                    orderID = self.sell(self.lineM1.lineBar[-1].close, self.pos)
                if self.pos == 0:
                    orderID = self.sell(self.lineM1.lineBar[-1].close, self.inputVolume)

        self.putEvent()  # 策略状态变化事件

    # ----------------------------------------------------------------------
    # 撤单（判断未完成列表长度，遍历委托单，判断委托单有无超时，撤销该委托单；委托单的剩余数量大于2倍下单最小成交单位，加入撤销列表，）
    def cancelOrder(self, vtOrderID):
        """撤单"""

        # 如果发单号为空字符串，则不进行后续操作
        if not vtOrderID or vtOrderID == '':
            return

        if STOPORDERPREFIX in vtOrderID:
            self.ctaEngine.cancelStopOrder(vtOrderID)
        else:
            self.ctaEngine.cancelOrder(vtOrderID)
    # ----------------------------------------------------------------------
    def onOrder(self, order):
        """收到委托变化推送（必须由用户继承实现）"""
        pass

    # ----------------------------------------------------------------------
    def onTrade(self, trade):
        # 发出状态更新事件
        self.putEvent()

    # ------------------------------------------------------------------------
    # 保存数据
    def saveData(self):
        pass


# 从csv文件进行回测
if __name__ == '__main__':
    # 提供直接双击回测的功能
    # 导入PyQt4的包是为了保证matplotlib使用PyQt4而不是PySide，防止初始化出错
    from vnpy.trader.app.ctaStrategy.ctaBacktesting import *
    from vnpy.trader.setup_logger import setup_logger

    cta_engine_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    log_file_name = os.path.abspath(os.path.join(cta_engine_path, 'TestLogs',
                                                  '{0}_{1}.log'.format(OneStep1MAStrategy.className,
                                                                       datetime.now().strftime('%m%d_%H%M'))))
    setup_logger(
         filename=log_file_name,
         debug=False)

    # 创建回测引擎
    engine = BacktestingEngine()
    # 设置引擎的回测模式为bar
    engine.setBacktestingMode(engine.BAR_MODE)

    # 设置回测用的数据起始日期
    engine.setStartDate('20180520')

    # 设置回测用的数据结束日期
    engine.setEndDate('20180521')

    engine.setDatabase(dbName='VnTrader_1Min_Db',symbol='XBTUSD.Bitmex')

    # 设置产品相关参数
    engine.setSlippage(0)     # 1跳（0.1）2跳0.2
    engine.setRate(float(0.002))    # 万1
    engine.setSize(1)         # 合约大小

    settings = {}
    settings['vtSymbol'] = 'XBTUSD.Bitmex'
    settings['symbol'] = 'XBTUSD.Bitmex'
    settings['name'] = 'samho1'
    settings['mode'] = 'bar'
    settings['backtesting'] = True
    settings['percentLimit'] = 100

    # 在引擎中创建策略对象
    engine.initStrategy(OneStep1MAStrategy, setting=settings)

    # 使用简单复利模式计算
    engine.usageCompounding = False     # True时，只针对FINAL_MODE有效

    # 启用实时计算净值模式REALTIME_MODE / FINAL_MODE 回测结束时统一计算模式
    engine.calculateMode = engine.FINAL_MODE
    engine.initCapital = 100000      # 设置期初资金
    engine.percentLimit = 100       # 设置资金使用上限比例(%)
    engine.barTimeInterval = 300    # bar的周期秒数，用于csv文件自动减时间

    # 开始跑回测
    cta_engine_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    data_file = os.path.abspath(os.path.join(cta_engine_path, 'TestLogs','BNbtc_usdt.csv'))
    engine.runBackTestingWithBarFile(data_file)
    # engine.runBacktesting()

    # 显示回测结果
    engine.showBacktestingResult()