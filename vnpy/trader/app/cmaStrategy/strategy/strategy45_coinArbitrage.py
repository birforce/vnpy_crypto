# encoding: UTF-8

# 首先写系统内置模块
import sys
import os
from datetime import datetime, timedelta, date
from time import sleep
import copy
import logging
import traceback

# 第三方模块
import talib as ta
import math
import numpy
import requests
import execjs

# vntrader基础模块
from vnpy.trader.vtConstant import DIRECTION_LONG, DIRECTION_SHORT
from vnpy.trader.vtConstant import PRICETYPE_LIMITPRICE, OFFSET_OPEN, OFFSET_CLOSE, STATUS_ALLTRADED, STATUS_CANCELLED, STATUS_REJECTED
from vnpy.trader.vtConstant import EXCHANGE_OKEX, EXCHANGE_BINANCE, EXCHANGE_GATEIO,EXCHANGE_FCOIN
# 然后CTA模块
from vnpy.trader.app.cmaStrategy.cmaTemplate import *
from vnpy.trader.app.ctaStrategy.ctaBase import *
from vnpy.trader.app.ctaStrategy.ctaLineBar import *
from vnpy.trader.app.ctaStrategy.ctaPosition import *
from vnpy.trader.app.ctaStrategy.ctaGridTrade import *
from vnpy.trader.app.ctaStrategy.ctaPolicy import CtaPolicy
ca_engine_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

########################################################################

class CMA_Policy(CtaPolicy):
    """跨市场套利事务"""
    def __init__(self, strategy):
        super(CMA_Policy, self).__init__(strategy)

        self.last_operation = EMPTY_STRING
        self.last_diff = EMPTY_FLOAT
        self.last_open_time = EMPTY_STRING
        self.uncomplete_orders = []

    def toJson(self):
        """
        将数据转换成dict
        :return:
        """
        j = OrderedDict()
        j['create_time']       = self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time is not None else EMPTY_STRING
        j['save_time']         = self.save_time.strftime('%Y-%m-%d %H:%M:%S') if self.save_time is not None else EMPTY_STRING
        j['last_operation']    = self.last_operation
        j['last_diff']   = self.last_diff if self.last_diff is not None else 0
        j['last_open_time']     = self.last_open_time if self.last_open_time is not None else EMPTY_STRING
        j['uncomplete_orders']  = self.uncomplete_orders
        return j

    def fromJson(self, json_data):
        """
        将dict转化为属性
        :param json_data:
        :return:
        """
        if not isinstance(json_data,dict):
            return

        if 'create_time' in json_data:
            try:
                self.create_time = datetime.strptime(json_data['create_time'], '%Y-%m-%d %H:%M:%S')
            except Exception as ex:
                self.writeCtaError(u'解释create_time异常:{}'.format(str(ex)))
                self.create_time = datetime.now()

        if 'save_time' in json_data:
            try:
                self.save_time = datetime.strptime(json_data['save_time'], '%Y-%m-%d %H:%M:%S')
            except Exception as ex:
                self.writeCtaError(u'解释save_time异常:{}'.format(str(ex)))
                self.save_time = datetime.now()

        self.last_operation    = json_data.get('last_operation',EMPTY_STRING)
        self.last_open_time     = json_data.get('last_open_time',EMPTY_STRING)
        self.last_diff          = json_data.get('last_diff',0.0)

    def clean(self):
        """
        清空数据
        :return:
        """
        self.writeCtaLog(u'清空policy数据')
        self.last_operation = EMPTY_STRING
        self.last_open_time =  EMPTY_STRING
        self.last_diff = EMPTY_FLOAT

class Strategy45(CmaTemplate):
    """跨市场数字货币合约的套利
    v 1:
    1) 行情框架（撮合tick，有效性，初始化各类k线数据）
    2）买卖点判断
    3）事务
    4） 交易判断、交易事务过程控制
    """
    className = 'Strategy45'
    author = u'李来佳'

    # 策略在外部设置的参数
    inputSS = 0.001                # 参数SS，下单，范围是1~100，步长为1，默认=1，
    minDiff = 0.01                 # 商品的最小交易价格单位
    min_trade_size = 0.001         # 下单最小成交单位
#----------------------------------------------------------------------
    def __init__(self, cmaEngine, setting=None):
        """Constructor"""
        super(Strategy45, self).__init__(cmaEngine, setting)

        self.paramList.append('inputSS')
        self.paramList.append('inputSS')
        self.paramList.append('inputSS')
        self.paramList.append('min_trade_size')
        self.varList.append('m_pos')
        self.varList.append('s_pos')
        self.varList.append('m5_atan')
        self.varList.append('m5_period')
        self.varList.append('m1_atan')

        self.cancelSeconds = 20                  # 未成交撤单的秒数

        self.curDateTime = None                 # 当前Tick时间
        self.curTick = None                     # 最新的tick

        self.m_pos = EMPTY_STRING               # 显示主交易所交易货币持仓得信息
        self.s_pos = EMPTY_STRING               # 显示从交易所交易货币持仓得信息

        self.last_master_tick = None            # 主交易所比对得最后一个tick
        self.last_slave_tick  = None            # 次交易所比对得最后一个tick
        self.master_base_pos = None
        self.master_quote_pos = None
        self.slave_base_pos = None
        self.slave_quote_pos = None

        self.lastTradedTime = datetime.now()        # 上一交易时间
        self.deadLine = EMPTY_STRING  # 允许最后的开仓期限（参数，字符串）
        self.deadLineDate = None  # 允许最后的开仓期限（日期类型）
        self.tradingOpen = True  # 允许开仓
        self.recheckPositions = True

        self.forceClose = EMPTY_STRING  # 强制平仓的日期（参数，字符串）
        self.forceCloseDate = None  # 强制平仓的日期（日期类型）
        self.forceTradingClose = False          # 强制平仓标志

        # 是否完成了策略初始化
        self.inited = False

        self.policy = CMA_Policy(strategy=self)

        self.m1_atan = EMPTY_FLOAT                 # M1的切线
        self.m1_atan_list = []                          # M1的切线队列

        self.m5_atan = EMPTY_FLOAT
        self.m5_atan_list = []                      # M5的切线队列
        self.m5_period = EMPTY_STRING


        self.lineDiff = None                       # 1分钟价差K线
        self.lineRatio = None                      # 1分钟比价K线
        self.lineMD = None                         # 1分钟残差K线
        self.lineM5 = None                         # 5分钟比价K线
        self.lineMaster = None                     # 主交易所币对，一分钟k线
        self.lineSlave = None                      # 主交易所币对，一分钟k线

        self.logMsg = EMPTY_STRING              # 临时输出日志变量

        self.delayMission = []                  # 延迟的任务
        self.auto_fix_close_price = False       # 自动修正平仓价格

        self.save_orders = []
        self.save_signals = OrderedDict()

        if setting:
            # 根据配置文件更新参数
            self.setParam(setting)

            # 创建的M1 Spread K线, = Leg1 - Leg2
            lineDiffSetting = {}
            lineDiffSetting['name'] = u'M1Diff'
            lineDiffSetting['barTimeInterval'] = 60
            lineDiffSetting['inputBollLen'] = 20
            lineDiffSetting['inputBollStdRate'] = 2
            lineDiffSetting['minDiff'] = self.minDiff
            lineDiffSetting['shortSymbol'] = self.vtSymbol
            lineDiffSetting['is_7x24'] = self.is_7x24
            self.lineDiff = CtaLineBar(self, self.onBar, lineDiffSetting)

            # 创建的M1 Ratio  K线 = Leg2/Leg1
            lineRatioSetting = {}
            lineRatioSetting['name'] = u'M1Ratio'
            lineRatioSetting['barTimeInterval'] = 60
            lineRatioSetting['inputRsi1Len'] = 14
            lineRatioSetting['inputKF'] = True
            lineRatioSetting['minDiff'] = 0.0001
            lineRatioSetting['shortSymbol'] = self.vtSymbol
            lineRatioSetting['is_7x24'] = self.is_7x24
            self.lineRatio = CtaLineBar(self, self.onBarRatio, lineRatioSetting)

            # 创建的M1 Mean Diff K线 Mean-Leg2
            lineMDSetting = {}
            lineMDSetting['name'] = u'M1MeanDiff'
            lineMDSetting['barTimeInterval'] = 60
            lineMDSetting['inputBollLen'] = 60
            lineMDSetting['inputBollStdRate'] = 2
            lineMDSetting['minDiff'] = self.minDiff
            lineMDSetting['shortSymbol'] = self.vtSymbol
            lineMDSetting['is_7x24'] = self.is_7x24
            self.lineMD = CtaLineBar(self, self.onBarMeanDiff, lineMDSetting)

            lineM5Setting = {}
            lineM5Setting['name'] = u'M5Ratio'
            lineM5Setting['barTimeInterval'] = 5
            lineM5Setting['period'] = PERIOD_MINUTE
            lineM5Setting['inputBollLen'] = 20
            lineM5Setting['inputRsi1Len'] = 14
            lineM5Setting['inputKF'] = True
            lineM5Setting['minDiff'] =  0.0001      # 万分之一
            lineM5Setting['shortSymbol'] = self.vtSymbol
            lineM5Setting['is_7x24'] = self.is_7x24
            self.lineM5 = CtaLineBar(self, self.onBarM5, lineM5Setting)

            self.master_symbol = '.'.join([self.vtSymbol, self.master_exchange])
            self.slave_symbol = '.'.join([self.vtSymbol, self.slave_exchange])

            self.base_symbol = self.vtSymbol.split('_')[0]
            self.quote_symbol = self.vtSymbol.split('_')[-1]

            lineMasterSetting = {}
            lineMasterSetting['name'] = 'M_M1'
            lineMasterSetting['period'] = PERIOD_SECOND
            lineMasterSetting['barTimeInterval'] = 60
            lineMasterSetting['inputPreLen'] = 5
            lineMasterSetting['inputMa1Len'] = 20
            lineMasterSetting['inputBollLen'] = 20
            lineMasterSetting['inputBollStdRate'] = 2
            lineMasterSetting['inputSkd'] = True
            lineMasterSetting['inputYb'] = True
            lineMasterSetting['mode'] = CtaLineBar.TICK_MODE
            lineMasterSetting['minDiff'] = self.minDiff
            lineMasterSetting['shortSymbol'] = self.vtSymbol
            lineMasterSetting['is_7x24'] = True
            self.lineMaster = CtaLineBar(self, self.onBarMaster, lineMasterSetting)

            lineSlaveSetting = {}
            lineSlaveSetting['name'] = 'S_M1'
            lineSlaveSetting['period'] = PERIOD_SECOND
            lineSlaveSetting['barTimeInterval'] = 60
            lineSlaveSetting['inputPreLen'] = 5
            lineSlaveSetting['inputMa1Len'] = 20
            lineSlaveSetting['inputBollLen'] = 20
            lineSlaveSetting['inputBollStdRate'] = 2
            lineSlaveSetting['inputSkd'] = True
            lineSlaveSetting['inputYb'] = True
            lineSlaveSetting['mode'] = CtaLineBar.TICK_MODE
            lineSlaveSetting['minDiff'] = self.minDiff
            lineSlaveSetting['shortSymbol'] = self.vtSymbol
            lineSlaveSetting['is_7x24'] = True
            self.lineSlave = CtaLineBar(self, self.onBarSlave, lineSlaveSetting)

            self.lineM5.export_filename = os.path.abspath(
                os.path.join(self.cmaEngine.get_logs_path(),
                             u'{}_{}_{}.csv'.format(self.name, self.vtSymbol, self.lineM5.name)))

            if os.path.exists(self.lineM5.export_filename):
                os.remove(self.lineM5.export_filename)
            self.lineM5.export_fields = [
                {'name': 'datetime', 'source': 'bar', 'attr': 'datetime', 'type_': 'datetime'},
                {'name': 'open', 'source': 'bar', 'attr': 'open', 'type_': 'float'},
                {'name': 'high', 'source': 'bar', 'attr': 'high', 'type_': 'float'},
                {'name': 'low', 'source': 'bar', 'attr': 'low', 'type_': 'float'},
                {'name': 'close', 'source': 'bar', 'attr': 'close', 'type_': 'float'},
                {'name': 'turnover', 'source': 'bar', 'attr': 'turnover', 'type_': 'float'},
                {'name': 'volume', 'source': 'bar', 'attr': 'volume', 'type_': 'float'},
                {'name': 'openInterest', 'source': 'bar', 'attr': 'openInterest', 'type_': 'float'},
                {'name': 'upper', 'source': 'lineBar', 'attr': 'lineUpperBand', 'type_': 'list'},
                {'name': 'middle', 'source': 'lineBar', 'attr': 'lineMiddleBand', 'type_': 'list'},
                {'name': 'lower', 'source': 'lineBar', 'attr': 'lineLowerBand', 'type_': 'list'},
                {'name': 'kf', 'source': 'lineBar', 'attr': 'lineStateMean', 'type_': 'list'},
                {'name': 'rsi', 'source': 'lineBar', 'attr': 'lineRsi1', 'type_': 'list'}
            ]

    def get_data_source(self, exchange_name):
        ds = None
        if exchange_name == EXCHANGE_OKEX:
            from vnpy.data.okex.okex_data import OkexData
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

        return ds

    #----------------------------------------------------------------------
    def onInit(self, force = False):
        """初始化
        从sina上读取近期合约和远期合约，合成价差
        """
        if force:
            self.writeCtaLog(u'策略强制初始化')
            self.inited = False
            self.trading = False                        # 控制是否启动交易
        else:
            self.writeCtaLog(u'策略初始化')
            if self.inited:
                self.writeCtaLog(u'已经初始化过，不再执行')
                return

        master_ds = self.get_data_source(self.master_exchange)
        slave_ds  = self.get_data_source(self.slave_exchange)

        m_rt, master_bars = master_ds.get_bars(self.vtSymbol,period='1min', callback=self.lineMaster.addBar)
        s_rt, slave_bars  = slave_ds.get_bars(self.vtSymbol, period='1min', callback=self.lineSlave.addBar)

        if not m_rt or not s_rt:
            self.writeCtaError(u'初始化数据失败,{}:{},{}:{}'
                               .format(self.master_exchange, u'成功' if m_rt else u'失败',
                                       self.slave_exchange,  u'成功' if s_rt else u'失败'))
        # List -> Dict 以时间为key
        slave_bars_dict = dict([bar.datetime, bar] for bar in slave_bars)

        for bar in master_bars:
            slave_bar = slave_bars_dict.get(bar.datetime,None)
            if slave_bar is None:
                continue

            spread_bar = CtaBarData()
            spread_bar.vtSymbol = self.vtSymbol
            spread_bar.symbol = self.vtSymbol
            spread_bar.volume = min(bar.volume, slave_bar.volume)
            spread_bar.datetime = bar.datetime
            spread_bar.date = bar.date
            spread_bar.time = bar.time

            ratio_bar = copy.copy(spread_bar)
            mean_bar  = copy.copy(spread_bar)

            spread_bar.open  = bar.open - slave_bar.open
            spread_bar.close = bar.close - slave_bar.close
            spread_bar.high  = max(spread_bar.open,spread_bar.close, bar.high-slave_bar.high, bar.low - slave_bar.low)
            spread_bar.low   = min(spread_bar.open,spread_bar.close, bar.high-slave_bar.high, bar.low - slave_bar.low)

            self.lineDiff.addBar(spread_bar, bar_is_completed=True, bar_freq=1)

            ratio_bar.open  = (bar.open / slave_bar.open) if slave_bar.open !=0 else 1
            ratio_bar.close = (bar.close / slave_bar.close) if slave_bar.close !=0 else 1
            ratio_bar.high  = max(ratio_bar.open, ratio_bar.close, bar.high/slave_bar.high, bar.low/slave_bar.low)
            ratio_bar.low   = min(ratio_bar.open, ratio_bar.close, bar.high/slave_bar.high, bar.low/slave_bar.low)

            self.lineRatio.addBar(ratio_bar, bar_is_completed=True, bar_freq=1)
            self.lineM5.addBar(ratio_bar)

            # 添加Mean-Diff Bar
            ratio = self.lineRatio.lineStateMean[-1] if len(self.lineRatio.lineStateMean) > 0 else ratio_bar.open
            mean_bar.open  = bar.open / ratio - slave_bar.open
            mean_bar.close = bar.close / ratio - slave_bar.close
            mean_bar.high  = max(mean_bar.open, mean_bar.close, bar.high / ratio - slave_bar.high,  bar.low / ratio - slave_bar.low)
            mean_bar.low   = min(mean_bar.open, mean_bar.close, bar.high / ratio - slave_bar.high,  bar.low / ratio - slave_bar.low)
            self.lineMD.addBar(mean_bar)

        # 更新初始化标识和交易标识
        self.inited = True
        self.trading = True                             # 控制是否启动交易

        if self.deadLine != EMPTY_STRING:
            try:
                self.deadLineDate = datetime.strptime(self.deadLine, '%Y-%m-%d')
                if not self.backtesting:
                    dt = datetime.now()
                    if (dt - self.deadLineDate).days >= 0:
                        self.tradingOpen = False
                        self.writeCtaNotification(u'日期超过最后开仓日期，不再开仓')
            except Exception:
                pass

        self.putEvent()
        self.writeCtaLog(u'策略初始化完成')

    def onStart(self):
        """启动策略（必须由用户继承实现）"""
        self.writeCtaLog(u'启动')
        self.trading = True

    #----------------------------------------------------------------------
    def onStop(self):
        """停止策略（必须由用户继承实现）"""
        self.uncompletedOrders.clear()
        self.recheckPositions = True


        self.entrust = 0


        self.trading = False
        self.writeCtaLog(u'停止' )
        self.putEvent()

    #----------------------------------------------------------------------
    def onTrade(self, trade):
        """交易更新"""
        self.writeCtaLog(u'{},OnTrade(),vtTradeId:{},vtOrderId:{},direction:{},offset:{},volume:{},price:{} '
                         .format(self.curDateTime, trade.vtTradeID, trade.vtOrderID,
                                 trade.direction, trade.offset,trade.volume,trade.price))

    #----------------------------------------------------------------------
    def onOrder(self, order):
        """报单更新"""
        msg = u'vrOrderID:{}, orderID:{},{},totalVol:{},tradedVol:{},offset:{},price:{},direction:{},status:{}，gatewayName:{}' \
            .format(order.vtOrderID, order.orderID, order.vtSymbol, order.totalVolume, order.tradedVolume, order.offset,
                    order.price, order.direction, order.status, order.gatewayName)
        self.writeCtaLog(u'OnOrder()报单更新 {0}'.format(msg))

        orderkey = order.gatewayName+u'.'+order.orderID
        if orderkey in self.uncompletedOrders:
            if order.totalVolume == order.tradedVolume:
                # 开仓，平仓委托单全部成交
                self.__onOrderAllTraded(order)

            elif order.tradedVolume > 0 and not order.totalVolume == order.tradedVolume :
                # 委托单部分成交
                self.__onOrderPartTraded(order)

            elif order.status in [STATUS_CANCELLED,STATUS_REJECTED]:
                self.__onOpenOrderCanceled(order)
                self.writeCtaNotification(u'委托单被撤销'.format(msg))

            else:
                self.writeCtaLog(u'OnOrder()委托单返回，total:{0},traded:{1}'
                                 .format(order.totalVolume, order.tradedVolume,))
        else:
            self.writeCtaLog(u'uncompletedOrders {}, 找不到 orderKey:{}'.format(self.uncompletedOrders,orderkey))
        self.putEvent()

    def __onOrderAllTraded(self, order):
        """订单的所有成交事件"""
        self.writeCtaLog(u'onOrderAllTraded(),{0},委托单全部完成'.format(order.orderTime ))
        orderkey = order.gatewayName+u'.'+order.orderID

        # 平多仓完成(sell)
        if self.uncompletedOrders[orderkey]['DIRECTION'] == DIRECTION_SHORT and order.offset == OFFSET_CLOSE:
            self.writeCtaLog(u'{}平多仓完成(sell),价格:{}'.format(order.vtSymbol, order.price))

        # 开多仓完成
        if self.uncompletedOrders[orderkey]['DIRECTION'] == DIRECTION_LONG and order.offset == OFFSET_OPEN:
            self.writeCtaLog(u'{0}开多仓完成'.format(order.vtSymbol))

        if order.vtSymbol == self.master_symbol:
            self.master_entrust = 0
        else:
            self.slave_entrust = 0

        try:
            del self.uncompletedOrders[orderkey]
        except Exception as ex:
            self.writeCtaLog(u'onOrder uncompletedOrders中找不到{0}'.format(orderkey))

    def __onOrderPartTraded(self, order):
        """订单部分成交"""
        self.writeCtaLog(u'onOrderPartTraded(),{0},委托单部分完成'.format(order.orderTime ))
        orderkey = order.gatewayName+u'.'+order.orderID
        o = self.uncompletedOrders.get(orderkey,None)
        if o is not None:
            self.writeCtaLog(u'更新订单{}部分完成:{}=>{}'.format(o,o.get('TradedVolume',0.0),order.tradedVolume))
            self.uncompletedOrders[orderkey]['TradedVolume'] = order.tradedVolume
        else:
            self.writeCtaLog(u'异常，找不到委托单:{0}'.format(orderkey))

    def __onOpenOrderCanceled(self, order):
        """委托开仓单撤销"""
        orderkey = order.gatewayName+u'.'+order.orderID
        self.writeCtaLog(u'__onOpenOrderCanceled(),{},委托开仓单：{} 已撤销'.format(order.orderTime, orderkey))
        try:
            if orderkey in self.uncompletedOrders:
                self.writeCtaLog(u'删除本地未完成订单:{}'.format(self.uncompletedOrders.get(orderkey)))
                del self.uncompletedOrders[orderkey]

                if order.vtSymbol == self.master_symbol:
                    self.writeCtaLog(u'设置{}的委托状态为0'.format(order.vtSymbol))
                    self.master_entrust = 0
                else:
                    self.writeCtaLog(u'设置{}的委托状态为0'.format(order.vtSymbol))
                    self.slave_entrust = 0
                if order.status == STATUS_CANCELLED:
                    self.writeCtaLog(u'重新执行委托检查')
                    self.resumbit_orders()
        except Exception as ex:
            self.writeCtaError(u'Order canceled Exception:{}/{}'.format(str(ex),traceback.format_exc()))


    # ----------------------------------------------------------------------
    def onStopOrder(self, orderRef):
        """停止单更新"""
        self.writeCtaLog(u'{0},停止单触发，orderRef:{1}'.format(self.curDateTime, orderRef))
        pass

    # ----------------------------------------------------------------------
    def __combineTick(self, tick):
        """合并两腿合约，成为套利合约"""

        combinable = False

        if tick.vtSymbol == self.master_symbol:
            # leg1合约
            self.last_master_tick = tick
            if self.last_slave_tick is not None:
                # 检查两腿tick 时间是否一致
                if (self.last_master_tick.datetime - self.last_slave_tick.datetime).seconds <=10:
                    combinable = True

        elif tick.vtSymbol == self.slave_symbol:
            # leg2合约
            self.last_slave_tick = tick
            if self.last_master_tick is not None:
                # 检查两腿tick 时间是否一致
                if (self.last_slave_tick.datetime - self.last_master_tick.datetime).seconds <=10:
                    combinable = True

        # 不能合并
        if not combinable:
            return None, None, None

        spread_tick = CtaTickData()
        spread_tick.vtSymbol = self.vtSymbol
        spread_tick.symbol = self.symbol

        spread_tick.datetime = self.last_master_tick.datetime           # 使用主交易所时间
        spread_tick.date = self.last_master_tick.date
        spread_tick.time = self.last_master_tick.time

        # 叫卖价差=leg1.askPrice1 - leg2.bidPrice1，volume为两者最小
        spread_tick.askPrice1 = self.last_master_tick.askPrice1 - self.last_slave_tick.bidPrice1
        spread_tick.askVolume1 = min(self.last_master_tick.askVolume1, self.last_slave_tick.bidVolume1)
        spread_tick.lastPrice = self.last_master_tick.lastPrice - self.last_slave_tick.lastPrice

        # 叫买价差=leg1.bidPrice1 - leg2.askPrice1，volume为两者最小
        spread_tick.bidPrice1 = self.last_master_tick.bidPrice1 - self.last_slave_tick.askPrice1
        spread_tick.bidVolume1 = min(self.last_master_tick.bidVolume1, self.last_slave_tick.askVolume1)

        # 比率tick
        ratio_tick = copy.copy(spread_tick)
        ratio_tick.askPrice1 = self.last_master_tick.askPrice1 / self.last_slave_tick.bidPrice1
        ratio_tick.bidPrice1 = self.last_master_tick.bidPrice1 / self.last_slave_tick.askPrice1
        ratio_tick.lastPrice = self.last_master_tick.lastPrice / self.last_slave_tick.lastPrice

        # 残差tick
        ratio = ratio_tick.lastPrice
        if len(self.lineRatio.lineStateMean) > 0:
            ratio = self.lineRatio.lineStateMean[-1]

        mean_tick = copy.copy(spread_tick)
        mean_tick.askPrice1 = self.last_master_tick.askPrice1 / ratio - self.last_slave_tick.bidPrice1
        mean_tick.bidPrice1 = self.last_master_tick.bidPrice1 / ratio - self.last_slave_tick.askPrice1
        mean_tick.lastPrice = self.last_master_tick.lastPrice / ratio - self.last_slave_tick.lastPrice

        return spread_tick, ratio_tick, mean_tick

    # ----------------------------------------------------------------------
    def buy(self, volume):
        """跨市场套利正套（开多）指令"""
        self.writeCtaLog(u'正套（开多）单,v:{}'.format(volume))
        if not self.trading:
            self.writeCtaLog(u'停止状态，不进行正套')
            return False

        if self.master_quote_pos is None or self.slave_base_pos is None:
            self.writeCtaError(u'{}市场货币{}持仓为None，或{}市场{}持仓为None，不进行正套'
                               .format(self.master_gateway,self.quote_symbol, self.slave_exchange, self.base_symbol))
            return False

        if self.master_quote_pos.longPosition / self.last_master_tick.lastPrice < volume:
            self.writeCtaLog(u'{}市场货币:{}不足买入:{} {}'.format(self.master_gateway,self.quote_symbol, volume, self.base_symbol))
            return False

        if (self.slave_base_pos.longPosition - self.slave_base_pos.frozen) < volume:
            self.writeCtaLog(
                u'{}市场货币:{} {},fz:{}不足卖出:{} '
                    .format(self.slave_gateway, self.base_symbol,
                            self.slave_base_pos.longPosition , self.slave_base_pos.frozen,volume))
            return False

        # 主交易所，买入base
        orderID = self.cmaEngine.sendOrder(self.master_symbol, CTAORDER_BUY, self.last_master_tick.bidPrice1+self.minDiff,volume, self)
        if orderID is None or len(orderID) == 0:
            self.writeCtaLog(u'异常，{} 开多{}失败,price:{}，volume:{}'.format(self.master_gateway, self.master_symbol,self.last_master_tick.bidPrice1+self.minDiff,volume))
            return False

        order  = {'SYMBOL': self.master_symbol, 'DIRECTION': DIRECTION_LONG,
                                           'OFFSET': OFFSET_OPEN, 'Volume': volume,
                                           'Price': self.last_master_tick.bidPrice1+self.minDiff, 'TradedVolume': EMPTY_FLOAT,
                                           'OrderTime': self.curDateTime, 'Canceled': False}
        self.writeCtaLog(u'登记未成交委托:{}:{}'.format(orderID, order))
        self.uncompletedOrders[orderID] = order

        self.master_entrust = 1
        # 从交易所，卖出base
        orderID = self.cmaEngine.sendOrder(self.slave_symbol, CTAORDER_SELL, self.last_slave_tick.askPrice1-self.minDiff, volume, self)
        if (orderID is None) or len(orderID) == 0:
            self.writeCtaLog(u'异常，{}卖出{}失败，price:{},volume:{}'.format(self.slave_gateway, self.slave_symbol, self.last_slave_tick.askPrice1 - self.minDiff,volume))
            return False
        order = {'SYMBOL': self.slave_symbol, 'DIRECTION': DIRECTION_SHORT,
                                           'OFFSET': OFFSET_CLOSE, 'Volume': volume,
                                           'Price': self.last_slave_tick.askPrice1 - self.minDiff, 'TradedVolume': EMPTY_FLOAT,
                                           'OrderTime': self.curDateTime ,'Canceled': False}
        self.writeCtaLog(u'登记未成交委托:{}:{}'.format(orderID, order))
        self.uncompletedOrders[orderID] = order

        self.slave_entrust = -1

        return True

    # ----------------------------------------------------------------------
    def sell(self, volume):
        """跨市场套利反套指令"""
        self.writeCtaLog(u'套利价差反套单,v:{}'.format(volume))
        if not self.trading:
            self.writeCtaLog(u'停止状态，不开仓')
            return False

        if self.master_base_pos is None or self.slave_quote_pos is None:
            self.writeCtaLog(u'{}市场货币{}持仓为None，或{}市场{}持仓为None，不进行正套'
                               .format(self.master_gateway, self.base_symbol, self.slave_gateway, self.quote_symbol))
            return False

        if self.master_base_pos.longPosition - self.master_base_pos.frozen < volume:
            self.writeCtaLog(
                u'{}市场货币:{} {},fz:{}不足卖出:{} '
                    .format(self.master_gateway, self.quote_symbol,
                            self.master_base_pos.longPosition , self.master_base_pos.frozen, volume))
            return False

        if (self.slave_quote_pos.longPosition - self.slave_quote_pos.frozen) / self.last_slave_tick.lastPrice < volume:
            self.writeCtaLog(
                u'{}市场货币:{}不足买入:{} {}'.format(self.slave_gateway, self.quote_symbol, volume, self.base_symbol))
            return False

        # 主交易所，卖出base
        orderID = self.cmaEngine.sendOrder(self.master_symbol, CTAORDER_SELL,
                                           self.last_master_tick.askPrice1 - self.minDiff, volume, self)
        if orderID is None or len(orderID) == 0:
            self.writeCtaLog(u'异常，{} 卖出{}失败,price:{}，volume:{}'.format(self.master_gateway, self.master_symbol,
                                                                       self.last_master_tick.askPrice1 - self.minDiff,
                                                                       volume))
            return False

        order = {'SYMBOL': self.master_symbol, 'DIRECTION': DIRECTION_SHORT,
                                           'OFFSET': OFFSET_CLOSE, 'Volume': volume,
                                           'Price': self.last_master_tick.askPrice1 - self.minDiff,
                                           'TradedVolume': EMPTY_INT,
                                           'OrderTime': self.curDateTime,'Canceled': False}
        self.writeCtaLog(u'登记未成交委托:{}:{}'.format(orderID, order))
        self.uncompletedOrders[orderID] = order

        self.master_entrust = -1

        # 从交易所，买入base
        orderID = self.cmaEngine.sendOrder(self.slave_symbol, CTAORDER_BUY,
                                           self.last_slave_tick.bidPrice1 + self.minDiff, volume, self)
        if (orderID is None) or len(orderID) == 0:
            self.writeCtaLog(u'异常，{}买入{}失败，price:{},volume:{}'.format(self.slave_gateway, self.slave_symbol,
                                                                      self.last_slave_tick.bidPrice1 + self.minDiff,
                                                                      volume))
            return False
        order = {'SYMBOL': self.slave_symbol, 'DIRECTION': DIRECTION_LONG,
                                           'OFFSET': OFFSET_OPEN, 'Volume': volume,
                                           'Price': self.last_slave_tick.bidPrice1 + self.minDiff,
                                           'TradedVolume': EMPTY_INT,
                                           'OrderTime': self.curDateTime,'Canceled': False}
        self.writeCtaLog(u'登记未成交委托:{}:{}'.format(orderID, order))
        self.uncompletedOrders[orderID] = order

        self.slave_entrust = 1

        return True

    def update_pos_info(self):
        self.m_pos = EMPTY_STRING
        if self.master_base_pos:
            self.m_pos += u'[{}:{},Fz:{}]'.format(self.base_symbol, self.master_base_pos.longPosition, self.master_base_pos.frozen)
        if self.master_quote_pos:
            self.m_pos += u'[{}:{},Fz:{}]'.format(self.quote_symbol, self.master_quote_pos.longPosition,
                                                      self.master_quote_pos.frozen)
        self.s_pos = EMPTY_STRING
        if self.slave_base_pos:
            self.s_pos += u'[{}:{},Fz:{}]'.format(self.base_symbol, self.slave_base_pos.longPosition,
                                                  self.slave_base_pos.frozen)
        if self.slave_quote_pos:
            self.s_pos += u'[{}:{},Fz:{}]'.format(self.quote_symbol, self.slave_quote_pos.longPosition,
                                                  self.slave_quote_pos.frozen)
    # ----------------------------------------------------------------------
    def onTick(self, tick):
        """行情更新
        :type tick: object
        """
        # 更新策略执行的时间（用于回测时记录发生的时间）
        self.curDateTime = tick.datetime

        spread_tick = None
        ratio_tick = None
        mean_tick = None

        # 分别推入各自1分钟k线
        if tick.vtSymbol == self.master_symbol and self.inited:
            self.lineMaster.onTick(tick)
            self.master_base_pos = self.cmaEngine.posBufferDict.get('.'.join([self.base_symbol,self.master_exchange]),None)
            self.master_quote_pos = self.cmaEngine.posBufferDict.get('.'.join([self.quote_symbol, self.master_exchange]),None)

        elif tick.vtSymbol == self.slave_symbol and self.inited:
            self.lineSlave.onTick(tick)
            self.slave_base_pos = self.cmaEngine.posBufferDict.get('.'.join([self.base_symbol, self.slave_exchange]),
                                                                    None)
            self.slave_quote_pos = self.cmaEngine.posBufferDict.get('.'.join([self.quote_symbol, self.slave_exchange]),
                                                                     None)

        # 合并tick
        spread_tick, ratio_tick, mean_tick = self.__combineTick(tick)
        if spread_tick is None or ratio_tick is None or mean_tick is None:
            return

        self.curTick = spread_tick

        if not self.inited:
            return

        self.lineRatio.onTick(ratio_tick)
        self.lineDiff.onTick(spread_tick)
        self.lineMD.onTick(mean_tick)
        self.lineM5.onTick(ratio_tick)

        # 4、交易逻辑
        # 首先检查是否是实盘运行还是数据预处理阶段
        if not (self.inited and len(self.lineDiff.lineMiddleBand) > 0 and len(self.lineRatio.lineStateMean) > 0 and len(self.lineMD.lineMiddleBand) > 0 and len(self.lineM5.lineUpperBand)>0) :
            return

        # 执行撤单逻辑
        self.cancelLogic(self.curDateTime)

        short_signal = False
        buy_signal = False

        # m1_std = 2 if self.lineDiff.lineBollStd[-1] < 2 else self.lineDiff.lineBollStd[-1]

        if spread_tick.bidPrice1 > self.lineDiff.lineUpperBand[-1]\
                and ratio_tick.bidPrice1 > self.lineM5.lineUpperBand[-1] \
                and spread_tick.bitPrice1 > self.lineMD.lineUpperBand[-1] \
                and ratio_tick.bidPrice1 >= 1.001:
            self.writeCtaLog(u'Short Signal:{},sell master:{}/{}/{},buy slave:{}/{}/{}'
                             .format(spread_tick.bidPrice1,
                                     self.last_master_tick.askPrice1, self.last_master_tick.lastPrice, self.last_master_tick.bidPrice1,
                                     self.last_slave_tick.askPrice1, self.last_slave_tick.lastPrice, self.last_slave_tick.bidPrice1))
            # 当前没有委托，没有未完成的订单，没有重新激活的订单
            if self.master_entrust == 0 and self.slave_entrust == 0 and len(self.uncompletedOrders)==0 and len(self.policy.uncomplete_orders) ==0:
                self.sell(self.inputSS)

        if spread_tick.askPrice1 < self.lineDiff.lineLowerBand[-1] \
                and ratio_tick.askPrice1 < self.lineM5.lineLowerBand[-1] \
                and spread_tick.askPrice1 < self.lineMD.lineLowerBand[-1] \
                and ratio_tick.bidPrice1 <= 0.999:
            self.writeCtaLog(u'Buy Signal:{}, buy master:{}/{}/{}, sell slave:{}/{}/{}'
                             .format(spread_tick.askPrice1,
                                     self.last_master_tick.askPrice1, self.last_master_tick.lastPrice, self.last_master_tick.bidPrice1,
                                     self.last_slave_tick.askPrice1, self.last_slave_tick.lastPrice, self.last_slave_tick.bidPrice1))
            # 当前没有委托，没有未完成的订单，没有重新激活的订单
            if self.master_entrust == 0 and self.slave_entrust == 0 and len(self.uncompletedOrders)==0 and len(self.policy.uncomplete_orders) ==0:
                self.buy(self.inputSS)

        self.update_pos_info()
        self.putEvent()

    # ----------------------------------------------------------------------
    def onBar(self, bar):
        """分钟K线数据更新
        bar，k周期数据
        """

        self.writeCtaLog(self.lineDiff.displayLastBar())
        self.writeCtaLog(u'{}持仓: {}，{}持仓:{}'.format(self.master_gateway,self.m_pos, self.slave_gateway,self.s_pos))
        self.writeCtaLog(u'{}委托状态:{},{}委托状态:{}'.format(self.master_gateway,self.master_entrust, self.slave_gateway,self.slave_entrust))
        if len(self.uncompletedOrders) > 0:
            self.writeCtaLog(u'未完成委托单：{}'.format(self.uncompletedOrders))
        if len(self.policy.uncomplete_orders) > 0:
            self.writeCtaLog(u'待重开委托单:{}'.format(self.policy.uncomplete_orders))

    # ----------------------------------------------------------------------
    def onBarRatio(self, bar):
        """比率线的OnBar事件"""
        l = len(self.lineRatio.lineStateMean)
        if l > 0:
            ma = self.lineRatio.lineStateMean[-1]
        else:
            ma = bar.close

        if l > 6:
            listKf = [x for x in self.lineRatio.lineStateMean[-7:-1]]
            malist = ta.MA(numpy.array(listKf, dtype=float), 5)
            ma5 = malist[-1]
            ma5_ref1 = malist[-2]
            if ma5 <= 0 or ma5_ref1 <= 0:
                self.writeCtaLog(u'卡尔曼均线异常')
                return
            self.m1_atan = math.atan((ma5/ma5_ref1 -1)*100*180/math.pi)

        if len(self.m1_atan_list)> 10:
            del self.m1_atan_list[0]

        self.m1_atan_list.append(self.m1_atan)
        self.writeCtaLog(self.lineRatio.displayLastBar())

    def onBarMeanDiff(self, bar):
        """残差线的OnBar事件"""

        if len(self.lineMD.lineUpperBand) > 0:
            boll_upper = self.lineMD.lineUpperBand[-1]
        else:
            boll_upper = 0

        if len(self.lineMD.lineMiddleBand) > 0:
            boll_mid = self.lineMD.lineMiddleBand[-1]
        else:
            boll_mid = 0

        if len(self.lineMD.lineLowerBand) > 0:
            boll_lower = self.lineMD.lineLowerBand[-1]
        else:
            boll_lower = 0

        if len(self.lineMD.lineBollStd) > 0:
            boll_std = self.lineMD.lineBollStd[-1]
        else:
            boll_std = 0

        self.writeCtaLog(self.lineMD.displayLastBar())

    def onBarM5(self, bar):
        """5分钟Ratio的OnBar事件"""

        if len(self.lineM5.lineMiddleBand) < 2 or len(self.lineM5.lineStateMean) < 2:
            return

        if self.lineM5.curPeriod is not None:
            self.m5_atan = self.lineM5.atan
            self.m5_period = u'{}=>{}'.format(self.lineM5.curPeriod.pre_mode, self.lineM5.curPeriod.mode)

        self.writeCtaLog(
            u'[M5-Ratio]{0} c:{1},kf:{2},M5_atan:{3},m5_atan:{4})'.format(bar.datetime, bar.close, self.lineM5.lineStateMean[-1],
                                                                                       self.m1_atan, self.m5_atan ))

    def onBarMaster(self, bar):
        self.writeCtaLog(self.lineMaster.displayLastBar())

    def onBarSlave(self, bar):
        self.writeCtaLog(self.lineSlave.displayLastBar())

    def cancelLogic(self, dt, force=False):
        "撤单逻辑"""
        if len(self.uncompletedOrders) < 1:
            return

        order_keys = list(self.uncompletedOrders.keys())

        for order_key in order_keys:
            if order_key not in self.uncompletedOrders:
                self.writeCtaError(u'{0}不在未完成的委托单中。'.format(order_key))
                continue
            order = self.uncompletedOrders[order_key]
            order_time = order['OrderTime']
            order_symbol = copy.copy(order['SYMBOL'])
            order_price = order['Price']
            canceled = order.get('Canceled',True)
            if (dt - order_time).seconds > self.cancelSeconds and not canceled :
                self.writeCtaLog(u'{0}超时{1}秒未成交，取消委托单：{2}'.format(order_symbol, (dt - order_time).seconds, order_key))

                # 撤销该委托单
                self.cancelOrder(str(order_key))
                order['Canceled']=True

                if order['Volume'] - order['TradedVolume'] > 2 * self.min_trade_size:
                    self.policy.uncomplete_orders.append(copy.copy(order))
                else:
                    if orderorder['SYMBOL'] == self.master_symbol:
                        self.master_entrust = 0
                    else:
                        self.slave_entrust = 0
                    self.writeCtaLog(u'委托数量:{}，成交数量:{}，剩余数量:{},不足:{}，放弃重新下单'
                                     .format(order['Volume'], order['TradedVolume']
                                             ,order['Volume']-order['TradedVolume'], 2*self.min_trade_size))

    def resumbit_orders(self):
        """重新提交订单"""
        for order in list(self.policy.uncomplete_orders):
            order_symbol = copy.copy(order['SYMBOL'])
            order_volume = order['Volume'] - order['TradedVolume']
            # 撤销的委托单，属于平仓类，需要追平
            if order['OFFSET'] == OFFSET_CLOSE and order['DIRECTION'] == DIRECTION_SHORT:
                if order_symbol == self.master_symbol:
                    sellPrice = min(self.last_master_tick.bidPrice1, self.last_master_tick.lastPrice) - self.minDiff
                else:
                    sellPrice = min(self.last_slave_tick.bidPrice1, self.last_slave_tick.lastPrice) - self.minDiff

                orderID = self.cmaEngine.sendOrder(order_symbol, CTAORDER_SELL, sellPrice, order_volume, self)

                if orderID is None:
                    self.writeCtaError(u'重新提交{0} {1}手平多单{2}失败'.format(order_symbol, order_volume, sellPrice))
                    continue

                # 重新添加平多委托单
                new_order = {'SYMBOL': order_symbol, 'DIRECTION': DIRECTION_SHORT,
                                                   'OFFSET': OFFSET_CLOSE, 'Volume': order_volume,
                                                   'TradedVolume': EMPTY_INT,
                                                   'Price': sellPrice, 'OrderTime': self.curDateTime,'Canceled': False}
                self.writeCtaLog(u'重新提交，登记未成交委托:{}:{}'.format(orderID, new_order))
                self.uncompletedOrders[orderID] = new_order


                if order_symbol == self.master_symbol:
                    self.master_entrust = -1
                else:
                    self.slave_entrust = -1

            # 属于开多委托单
            else:
                if order_symbol == self.master_symbol:
                    buyPrice = max(self.last_master_tick.askPrice1, self.last_master_tick.lastPrice) + self.minDiff
                else:
                    buyPrice = max(self.last_slave_tick.askPrice1, self.last_slave_tick.lastPrice) + self.minDiff

                # 发送委托
                self.writeCtaLog(u'重新提交{0} {1}手开多单{2}'.format(order_symbol, order_volume, buyPrice))
                orderID = self.cmaEngine.sendOrder(order_symbol, CTAORDER_BUY, buyPrice, order_volume, self)
                if orderID is None or len(orderID) == 0:
                    self.writeCtaError(u'重新提交{0} {1}手开多单{2}失败'.format(order_symbol, order_volume, buyPrice))
                    continue

                # 重新添加开空委托单
                new_order  = {'SYMBOL': order_symbol, 'DIRECTION': DIRECTION_LONG,
                                                   'OFFSET': OFFSET_OPEN, 'Volume': order_volume,
                                                   'Price': buyPrice, 'TradedVolume': EMPTY_INT,
                                                   'OrderTime': self.curDateTime,'Canceled': False}
                self.writeCtaLog(u'重新提交，登记未成交委托:{}:{}'.format(orderID, new_order))
                self.uncompletedOrders[orderID] = new_order

                if order_symbol == self.master_symbol:
                    self.master_entrust = 1
                else:
                    self.slave_entrust = 1

            self.writeCtaLog(u'移除未完成得订单:{}'.format(order))
            self.policy.uncomplete_orders.remove(order)
    # ----------------------------------------------------------------------
    def saveData(self):
        pass
