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
import numpy

from vnpy.trader.vtConstant import DIRECTION_LONG, DIRECTION_SHORT
from vnpy.trader.vtConstant import PRICETYPE_LIMITPRICE, OFFSET_OPEN, OFFSET_CLOSE, STATUS_ALLTRADED, STATUS_CANCELLED, \
    STATUS_REJECTED
from vnpy.trader.vtConstant import EXCHANGE_OKEX, EXCHANGE_BINANCE, EXCHANGE_GATEIO, EXCHANGE_FCOIN
from vnpy.trader.app.cmaStrategy.cmaTemplate import *
from vnpy.trader.app.ctaStrategy.ctaLineBar import *
from vnpy.trader.app.ctaStrategy.ctaGridTrade import *
from vnpy.trader.app.ctaStrategy.ctaPolicy import CtaPolicy

ca_engine_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


########################################################################

class CMA_Policy(CtaPolicy):
    """跨市场套利事务"""

    def __init__(self, strategy):
        super(CMA_Policy, self).__init__(strategy)

        # 初始化值
        self.last_operation = EMPTY_STRING
        self.last_diff = EMPTY_FLOAT
        self.last_open_time = EMPTY_STRING
        self.uncomplete_orders = []  # 待重开委托单

    # 属性转换为dict
    def toJson(self):
        """
        将数据转换成dict
        :return: j
        """

        # 初始化一个记住插入顺序的字典
        j = OrderedDict()
        # 日期：字符串转成datetime对象
        j['create_time'] = self.create_time.strftime(
            '%Y-%m-%d %H:%M:%S') if self.create_time is not None else EMPTY_STRING
        # 日期：字符串转成datetime对象
        j['save_time'] = self.save_time.strftime('%Y-%m-%d %H:%M:%S') if self.save_time is not None else EMPTY_STRING
        # ？
        j['last_operation'] = self.last_operation
        # 最后的价差
        j['last_diff'] = self.last_diff if self.last_diff is not None else 0
        # 最后開始時間
        j['last_open_time'] = self.last_open_time if self.last_open_time is not None else EMPTY_STRING
        # uncomplete_orders：待重开委托单
        j['uncomplete_orders'] = self.uncomplete_orders
        return j

    # dict转换为属性
    def fromJson(self, json_data):
        """
        将dict转化为属性
        :param json_data:
        :return:
        """
        # 判断json——data是否为字典
        if not isinstance(json_data, dict):
            return

        if 'create_time' in json_data:
            try:
                # 日期字符串转成datetime日期
                self.create_time = datetime.strptime(json_data['create_time'], '%Y-%m-%d %H:%M:%S')
            except Exception as ex:
                # 打印异常
                self.writeCtaError(u'解释create_time异常:{}'.format(str(ex)))
                # create_time = 当前时间
                self.create_time = datetime.now()

        if 'save_time' in json_data:
            try:
                self.save_time = datetime.strptime(json_data['save_time'], '%Y-%m-%d %H:%M:%S')
            except Exception as ex:
                self.writeCtaError(u'解释save_time异常:{}'.format(str(ex)))
                self.save_time = datetime.now()

        self.last_operation = json_data.get('last_operation', EMPTY_STRING)
        self.last_open_time = json_data.get('last_open_time', EMPTY_STRING)
        self.last_diff = json_data.get('last_diff', 0.0)

    # 清空数据（属性值 = 0）
    def clean(self):
        """
        清空数据
        :return:
        """
        self.writeCtaLog(u'清空policy数据')
        self.last_operation = EMPTY_STRING
        self.last_open_time = EMPTY_STRING
        self.last_diff = EMPTY_FLOAT


class CrossMarketSpotArbitrageStrategy(CmaTemplate):
    """
    套利交易：即买入一种期货合约的同时卖出另一种不同的期货合约，这里的期货合约既可以是同一期货品种的不同交割月份。
    也可以是相互关联的两种不同商品。还可以是不同期货市场的同种商品。
    套利交易者同时在一种期货合约上做多在另一种期货合约上做空，通过两个合约间价差变动来获利，与绝对价格水平关系不大。
    （注：此策略中为现货交易， 非期货交易。）

    跨市场数字货币套利
    1) 行情框架（撮合tick，有效性，初始化各类k线数据）
    2）买卖点判断
    3）事务
    4） 交易判断、交易事务过程控制
    """
    # 类名/作者
    className = 'CrossMarketSpotArbitrageStrategy'
    author = u'李来佳'

    # 策略在外部设置的参数
    inputOrderCount = 0.001  # 下单手数，范围是1~100，步长为1，默认=1，
    minDiff = 0.01  # 商品的最小交易价格单位
    min_trade_size = 0.001  # 下单最小成交单位

    # ----------------------------------------------------------------------

    # 初始化（属性；类；切线；价差K线；比率K线；残差K线）
    def __init__(self, cmaEngine, setting=None):
        """
        构造器
        :param:cmaEngine:cma引擎，setting：
        :return:
        """

        # 调用父类构造器
        super(CrossMarketSpotArbitrageStrategy, self).__init__(cmaEngine, setting)

        self.paramList.append('inputOrderCount')  # 下单范围
        self.paramList.append('min_trade_size')  # 下单最小成交单位
        self.varList.append('master_position')  # 主交易所交易货币仓位, master为主交易所
        self.varList.append('slave_position')  # 从交易所交易货币仓位， slave为次交易所
        self.varList.append('m5_atan')  # M5切线
        self.varList.append('m5_period')  # M5周期
        self.varList.append('m1_atan')  # M1切线

        self.cancelSeconds = 20  # 未成交撤单的秒数

        self.curDateTime = None  # 当前时间
        self.curTick = None  # 当前Ticket

        self.master_position = EMPTY_STRING  # 主交易所交易货币仓位
        self.slave_position = EMPTY_STRING  # 从交易所交易货币仓位

        self.last_master_tick = None  # 主交易所比对得最后一个ticket
        self.last_slave_tick = None  # 从交易所比对得最后一个ticket
        self.master_base_position = None  # 主交易所交易主货币持仓
        self.master_quote_position = None  # 主交易所基准货币持仓
        self.slave_base_position = None  # 从交易所交易主货币持仓
        self.slave_quote_position = None  # 从交易所基准货币持仓

        self.lastTradedTime = datetime.now()  # 上一交易时间
        self.deadLine = EMPTY_STRING  # 允许最后的开仓期限（参数，字符串）
        self.deadLineDate = None  # 允许最后的开仓期限（日期类型）
        self.isTradingOpen = True  # 允许开仓
        self.recheckPositions = True

        self.forceClose = EMPTY_STRING  # 强制平仓的日期（字符串类型）
        self.forceCloseDate = None  # 强制平仓的日期（日期类型）
        self.forceTradingClose = False  # 强制平仓标志

        # 是否完成了策略初始化
        self.isInited = False

        # 初始化CMA_Policy:存放待重开委托单
        self.policy = CMA_Policy(strategy=self)

        self.m1_atan = EMPTY_FLOAT  # M1切线
        self.m1_atan_list = []  # M1的切线队列

        self.m5_atan = EMPTY_FLOAT  # M5切线
        self.m5_atan_list = []  # M5的切线队列
        self.m5_period = EMPTY_STRING

        self.lineDiff = None  # M1价差K线
        self.lineRatio = None  # M1比率K线
        self.lineMD = None  # M1残差K线
        self.lineM5 = None  # M5比率K线
        self.lineMaster = None  # 主交易所币对M1k线
        self.lineSlave = None  # 从交易所币对M1k线

        self.logMsg = EMPTY_STRING  # 临时输出日志变量

        self.delayMission = []  # 延迟的任务
        self.auto_fix_close_price = False  # 自动修正平仓价格

        self.save_orders = []  # 保存的委托单
        self.save_signals = OrderedDict()  # 任務字典？

        if setting:
            # 根据配置文件更新paramList
            self.setParam(setting)

            # 创建的M1价差K线 = Leg1 - Leg2
            lineDiffSetting = {}
            lineDiffSetting['name'] = u'M1Diff'
            lineDiffSetting['barTimeInterval'] = 60  # bar時間間隔,60秒
            lineDiffSetting['inputBollLen'] = 20  # 布林特线周期
            lineDiffSetting['inputBollStdRate'] = 2  # 布林特线标准差
            lineDiffSetting['minDiff'] = self.minDiff  # 最小价差
            lineDiffSetting['shortSymbol'] = self.vtSymbol  # 商品短号
            lineDiffSetting['is_7x24'] = self.is_7x24
            self.lineDiff = CtaLineBar(self, self.onBar, lineDiffSetting)  # M1价差K线：CtaLineBar对象

            # 创建的M1比率K线 = Leg2/Leg1
            lineRatioSetting = {}
            lineRatioSetting['name'] = u'M1Ratio'
            lineRatioSetting['barTimeInterval'] = 60
            lineRatioSetting['inputRsi1Len'] = 14  # Rsi线1周期
            lineRatioSetting['inputKF'] = True
            lineRatioSetting['minDiff'] = 0.0001  # 万分之一
            lineRatioSetting['shortSymbol'] = self.vtSymbol
            lineRatioSetting['is_7x24'] = self.is_7x24
            self.lineRatio = CtaLineBar(self, self.onBarRatio, lineRatioSetting)  # M1比率K线：CtaLineBar对象

            # 创建的M1残差K线 Mean-Leg2
            lineMDSetting = {}
            lineMDSetting['name'] = u'M1MeanDiff'
            lineMDSetting['barTimeInterval'] = 60
            lineMDSetting['inputBollLen'] = 60  # 布林特线周期
            lineMDSetting['inputBollStdRate'] = 2  # 布林特线标准差
            lineMDSetting['minDiff'] = self.minDiff
            lineMDSetting['shortSymbol'] = self.vtSymbol
            lineMDSetting['is_7x24'] = self.is_7x24
            self.lineMD = CtaLineBar(self, self.onBarMeanDiff, lineMDSetting)  # M1残差K线：CtaLineBar对象

            # 创建的M5比率K线
            lineM5Setting = {}
            lineM5Setting['name'] = u'M5Ratio'
            lineM5Setting['barTimeInterval'] = 5
            lineM5Setting['period'] = PERIOD_MINUTE
            lineM5Setting['inputBollLen'] = 20  # 布林特线周期
            lineM5Setting['inputRsi1Len'] = 14  # Rsi线1周期
            lineM5Setting['inputKF'] = True
            lineM5Setting['minDiff'] = 0.0001  # 万分之一
            lineM5Setting['shortSymbol'] = self.vtSymbol
            lineM5Setting['is_7x24'] = self.is_7x24
            self.lineM5 = CtaLineBar(self, self.onBarM5, lineM5Setting)  # M5比率K线：CtaLineBar对象

            # 主交易所币对 = 合约代码 + 主交易所
            self.master_symbol = '.'.join([self.vtSymbol, self.master_exchange])
            # 从交易所币对 = 合约代码 + 从交易所
            self.slave_symbol = '.'.join([self.vtSymbol, self.slave_exchange])

            # 交易主货币和基准货币
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
            self.lineMaster = CtaLineBar(self, self.onBarMaster, lineMasterSetting)  # 主交易货币对M1K线：CtaLineBar对象

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
            self.lineSlave = CtaLineBar(self, self.onBarSlave, lineSlaveSetting)  # 从交易货币对M1K线：CtaLineBar对象

            # os.path.abspath():返回path规范化的绝对路径
            # get_logs_path():获取CTA策略的对应日志目录
            # export_filename = 返回CTA策略的对应日志目录的规范化绝对路径
            self.lineM5.export_filename = os.path.abspath(
                os.path.join(self.cmaEngine.get_logs_path(),
                             u'{}_{}_{}.csv'.format(self.name, self.vtSymbol, self.lineM5.name)))

            # 若M5比率K线的export_filename存在则删除
            if os.path.exists(self.lineM5.export_filename):
                os.remove(self.lineM5.export_filename)

            # 输出的字段
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

    # 获取数据源（返回相应交易所数据对象）
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

        return ds

    # ----------------------------------------------------------------------

    # 初始化（初始化策略；返回从交易所获得的K线数据；合成价差K线，比率K线，均值K线；是否开仓）
    def onInit(self, force=False):
        if force:
            self.writeCtaLog(u'策略强制初始化')
            self.isInited = False  # 策略初始化状态
            self.isTrading = False  # 启动交易状态
        else:
            self.writeCtaLog(u'策略初始化')
            if self.isInited:
                self.writeCtaLog(u'已经初始化过，不再执行')
                return
        # 获取主交易所数据对象
        master_ds = self.get_data_source(self.master_exchange)

        # 获取从交易所数据对象
        slave_ds = self.get_data_source(self.slave_exchange)

        # 返回主交易所获得的1分钟Bar数据（合约代码；时间间隔：1分钟；主交易货币对M1K线.加入一个Bar）
        master1MinBarAvailabled, master_bars = master_ds.get_bars(self.vtSymbol, period='1min', callback=self.lineMaster.addBar)

        # 返回从交易所获得的1分钟Bar数据（合约代码；时间间隔：1分钟；回调函数=从交易货币对M1K线.加入一个Bar）
        slave1MinBarAvailabled, slave_bars = slave_ds.get_bars(self.vtSymbol, period='1min', callback=self.lineSlave.addBar)
        # 判断初始化结果，输出信息
        if not master1MinBarAvailabled or not slave1MinBarAvailabled:
            self.writeCtaError(u'初始化数据失败,{}:{},{}:{}'.format(self.master_exchange, u'成功' if master1MinBarAvailabled else u'失败',
                                                             self.slave_exchange, u'成功' if slave1MinBarAvailabled else u'失败'))
        # key：时间，value：bar
        slave_bars_dict = dict([bar.datetime, bar] for bar in slave_bars)
        # 遍历master_bars
        for bar in master_bars:
            # 返回slave_bars_dict字典中datetime的值为bar.datetime的slave_bar
            slave_bar = slave_bars_dict.get(bar.datetime, None)
            # 若slave_bar为空，开始下次循环
            if slave_bar is None:
                continue

            # 初始化价差Bar对象
            spread_bar = CtaBarData()
            # 写入基本属性值
            spread_bar.vtSymbol = self.vtSymbol  # vt合约代码
            spread_bar.symbol = self.vtSymbol  # 合约代码
            spread_bar.volume = min(bar.volume, slave_bar.volume)  # 数量
            spread_bar.datetime = bar.datetime  # python的datetime时间对象
            spread_bar.date = bar.date  # bar开始的日期
            spread_bar.time = bar.time  # 时间
            # 复制一份：比率Bar、均值Bar
            ratio_bar = copy.copy(spread_bar)
            mean_bar = copy.copy(spread_bar)

            # 价差Bar数据
            # 价差Bar.open = 主bar的开 - 从bar的开
            spread_bar.open = bar.open - slave_bar.open
            spread_bar.close = bar.close - slave_bar.close
            # 近似取价差Bar的高点和低点，此取法不准确
            spread_bar.high = max(spread_bar.open, spread_bar.close, bar.high - slave_bar.high, bar.low - slave_bar.low)
            spread_bar.low = min(spread_bar.open, spread_bar.close, bar.high - slave_bar.high, bar.low - slave_bar.low)

            # 添加bar到M1价差K线
            # 插入的bar，其周期与K线周期一致，bar_is_completed就设为True
            self.lineDiff.addBar(spread_bar, bar_is_completed=True, bar_freq=1)

            # 比率bar数据
            # ？？ 上面lineRatio是Leg2/Leg1
            ratio_bar.open = (bar.open / slave_bar.open) if slave_bar.open != 0 else 1
            ratio_bar.close = (bar.close / slave_bar.close) if slave_bar.close != 0 else 1
            ratio_bar.high = max(ratio_bar.open, ratio_bar.close, bar.high / slave_bar.high, bar.low / slave_bar.low)
            ratio_bar.low = min(ratio_bar.open, ratio_bar.close, bar.high / slave_bar.high, bar.low / slave_bar.low)

            # 添加bar到M1比率K线
            self.lineRatio.addBar(ratio_bar, bar_is_completed=True, bar_freq=1)
            # 添加bar到M5比率K线
            # ？？ 为什么这个与M1的一样
            self.lineM5.addBar(ratio_bar)

            #
            ratio = self.lineRatio.lineStateMean[-1] if len(self.lineRatio.lineStateMean) > 0 else ratio_bar.open

            # ?? 残差
            mean_bar.open = bar.open / ratio - slave_bar.open
            mean_bar.close = bar.close / ratio - slave_bar.close
            mean_bar.high = max(mean_bar.open, mean_bar.close, bar.high / ratio - slave_bar.high,
                                bar.low / ratio - slave_bar.low)
            mean_bar.low = min(mean_bar.open, mean_bar.close, bar.high / ratio - slave_bar.high,
                               bar.low / ratio - slave_bar.low)

            self.lineMD.addBar(mean_bar)

        # 更新初始化标识和交易标识
        self.isInited = True  # 策略初始化状态
        self.isTrading = True  # 交易状态

        # 最后开仓期限（字符串）
        if self.deadLine != EMPTY_STRING:
            try:
                # 转换为日期对象
                self.deadLineDate = datetime.strptime(self.deadLine, '%Y-%m-%d')
                # 判断是否回测
                if not self.backtesting:
                    # 当前时间
                    dt = datetime.now()
                    # 当前时间 - 最后开仓期限 >= 0
                    if (dt - self.deadLineDate).days >= 0:
                        self.isTradingOpen = False  # 不允许开仓
                        self.writeCtaNotification(u'日期超过最后开仓日期，不再开仓')
            except Exception:
                pass

        self.putEvent()  # 策略状态变化事件
        self.writeCtaLog(u'策略初始化完成')

    # 启动策略（启动交易）
    def onStart(self):
        """启动策略（必须由用户继承实现）"""
        self.writeCtaLog(u'启动')
        self.isTrading = True  # 交易标识

    # 停止策略（清空未完成的委托单，停止交易，策略状态变化事件）
    def onStop(self):
        """停止策略（必须由用户继承实现）"""
        # 清空未完成的委托单
        self.uncompletedOrders.clear()
        self.recheckPositions = True

        # 表示无委托
        self.entrust = 0

        self.isTrading = False  # 交易标识
        self.writeCtaLog(u'停止交易')
        self.putEvent()  # 策略状态变化事件

    # 交易状态更新（输出日志）
    def onTrade(self, trade):
        """
        交易更新
        :param trade:交易状态
        """
        # 输出交易状态日志
        self.writeCtaLog(u'{},OnTrade(),vtTradeId:{},vtOrderId:{},direction:{},offset:{},volume:{},price:{} '
                         .format(self.curDateTime, trade.vtTradeID, trade.vtOrderID,
                                 trade.direction, trade.offset, trade.volume, trade.price))

    # 报单更新（对uncompletedOrders列表中的委托单处理；分支：委托单全部成交/部分成交/开仓单撤销/委托单返回）
    def onOrder(self, order):
        """
        报单更新
        :param order:报单
        """
        # 输出报单日志
        msg = u'vrOrderID:{}, orderID:{},{},totalVol:{},tradedVol:{},offset:{},price:{},direction:{},status:{}，gatewayName:{}' \
            .format(order.vtOrderID, order.orderID, order.vtSymbol, order.totalVolume, order.tradedVolume, order.offset,
                    order.price, order.direction, order.status, order.gatewayName)
        self.writeCtaLog(u'OnOrder()报单更新 {0}'.format(msg))
        # 委托单编号 = 账户名称 + 委托单ID
        orderkey = order.gatewayName + u'.' + order.orderID
        # 报单是否在未完成的委托单中
        if orderkey in self.uncompletedOrders:

            # 报单总数量 = 报单成交数量
            if order.totalVolume == order.tradedVolume:
                # 调用委托单全部成交
                # __onOrderAllTraded：获取委托单编号；判断买入还是卖出，更新委托状态，写入日志；删除委托单
                self.__onOrderAllTraded(order)

            # 报单成交数量 > 0 和 报单总数量 != 报单成交数量
            elif order.tradedVolume > 0 and not order.totalVolume == order.tradedVolume:
                # 委托单部分成交
                # __onOrderPartTraded：获取orderkey的委托单，更新委托单的成交数量，写入日志
                self.__onOrderPartTraded(order)

            # 撤销状态或拒绝状态的委托单
            elif order.status in [STATUS_CANCELLED, STATUS_REJECTED]:
                # 委托开仓单撤销
                # __onOpenOrderCanceled：获取委托单编号，如果委托单在未完成委托单中:删除列表中的委托单；更新委托状态，重新执行委托检查
                self.__onOpenOrderCanceled(order)
                self.writeCtaNotification(u'委托单被撤销'.format(msg))

            else:
                # 打印总量和成交量
                self.writeCtaLog(u'OnOrder()委托单返回，total:{0},traded:{1}'
                                 .format(order.totalVolume, order.tradedVolume, ))
        else:
            self.writeCtaLog(u'uncompletedOrders {}, 找不到 orderKey:{}'.format(self.uncompletedOrders, orderkey))
        self.putEvent()  # 策略状态变化事件

    # 委托单全部成交（获取委托单编号，判断买入还是卖出，写入日志，完成后删除order）
    def __onOrderAllTraded(self, order):
        """订单的所有成交事件"""
        self.writeCtaLog(u'onOrderAllTraded(),{0},委托单全部完成'.format(order.orderTime))
        # 委托单编号
        orderkey = order.gatewayName + u'.' + order.orderID

        # 未完成委托单[委托单编号][方向] = 空头 and 报单开平仓 =
        if self.uncompletedOrders[orderkey]['DIRECTION'] == DIRECTION_SHORT and order.offset == OFFSET_CLOSE:
            self.writeCtaLog(u'{}平多仓完成(sell),价格:{}'.format(order.vtSymbol, order.price))

        # 未完成委托单[委托单编号][方向] = 多头 and 报单开平仓 =
        if self.uncompletedOrders[orderkey]['DIRECTION'] == DIRECTION_LONG and order.offset == OFFSET_OPEN:
            self.writeCtaLog(u'{0}开多仓完成'.format(order.vtSymbol))

        # 委托单合约代码 = 主交易所币对
        if order.vtSymbol == self.master_symbol:
            # 更新主交易所委托状态
            self.master_entrust = 0
        else:
            # 更新从交易所委托状态
            self.slave_entrust = 0

        try:
            # 事件完成，删除列表中的此order
            del self.uncompletedOrders[orderkey]
        except Exception as ex:
            self.writeCtaLog(u'onOrder uncompletedOrders中找不到{0}'.format(orderkey))

    # 委托单部分成交（获取orderkey的委托单，更新委托单的成交数量，写入日志）
    def __onOrderPartTraded(self, order):
        """订单部分成交"""
        self.writeCtaLog(u'onOrderPartTraded(),{0},委托单部分完成'.format(order.orderTime))
        # 委托单编号
        orderkey = order.gatewayName + u'.' + order.orderID
        # 在uncompletedOrders中获取orderkey的委托单,没有返回空
        uncompletedOrder = self.uncompletedOrders.get(orderkey, None)
        if uncompletedOrder is not None:
            self.writeCtaLog(u'更新订单{}部分完成:{}=>{}'.format(uncompletedOrder, uncompletedOrder.get('TradedVolume', 0.0), order.tradedVolume))
            # 更新列表的委托单的成交数量
            self.uncompletedOrders[orderkey]['TradedVolume'] = order.tradedVolume
        else:
            self.writeCtaLog(u'异常，找不到委托单:{0}'.format(orderkey))

    # 委托开仓单撤销（获取委托单编号，如果委托单在未完成委托单中:删除列表中的委托单；更新委托状态，重新执行委托检查）
    def __onOpenOrderCanceled(self, order):
        """委托开仓单撤销"""
        # 委托单编号
        orderkey = order.gatewayName + u'.' + order.orderID
        self.writeCtaLog(u'__onOpenOrderCanceled(),{},委托开仓单：{} 已撤销'.format(order.orderTime, orderkey))
        try:
            # 如果委托单在未完成委托单中
            if orderkey in self.uncompletedOrders:
                self.writeCtaLog(u'删除本地未完成订单:{}'.format(self.uncompletedOrders.get(orderkey)))

                # 删除列表中的此委托单
                del self.uncompletedOrders[orderkey]

                # 委托单的合约代码 == 主交易所币对
                if order.vtSymbol == self.master_symbol:
                    self.writeCtaLog(u'设置{}的委托状态为0'.format(order.vtSymbol))
                    # 更新委托状态
                    self.master_entrust = 0
                else:
                    self.writeCtaLog(u'设置{}的委托状态为0'.format(order.vtSymbol))
                    # 更新委托状态
                    self.slave_entrust = 0

                if order.status == STATUS_CANCELLED:
                    self.writeCtaLog(u'重新执行委托检查')
                    self.resumbit_orders()
        except Exception as ex:
            self.writeCtaError(u'Order canceled Exception:{}/{}'.format(str(ex), traceback.format_exc()))

    # 停止单更新（停止单触发）
    def onStopOrder(self, orderRef):
        """停止单更新"""
        self.writeCtaLog(u'{0},停止单触发，orderRef:{1}'.format(self.curDateTime, orderRef))
        pass

    # 合并合约（判断合约代码，检查时间是否一致；初始化ticket，插入数据；求得叫买价差和叫卖价差，得到比率ticket和均值ticket）
    def __combineTick(self, tick):
        """合并两腿合约，成为套利合约"""

        # 是否可以合并
        combinable = False

        # 合约vt系统合约代码 = 主交易所币对
        if tick.vtSymbol == self.master_symbol:

            # leg1合约
            self.last_master_tick = tick  # ticket为主交易所比对的最后一个ticket

            # 从交易所比对得最后一个ticket不为空
            if self.last_slave_tick is not None:

                # 检查两腿tick时间是否一致（主交易所比对得最后一个ticket与从交易所比对得最后一个ticket的时间差 < 10秒）
                if 0 <= (self.last_master_tick.datetime - self.last_slave_tick.datetime).seconds <= 10:
                    # 可以合并
                    combinable = True

        # 合约vt系统代码 == 从交易所币对
        elif tick.vtSymbol == self.slave_symbol:

            # leg2合约
            self.last_slave_tick = tick  # ticket为从交易所比对的最后一个ticket

            # 主交易所比对得最后一个ticket不为空
            if self.last_master_tick is not None:

                # 检查两腿ticket时间是否一致（从交易所比对得最后一个ticket与主交易所比对得最后一个ticket的时间差 < 10秒）
                if 0 <= (self.last_slave_tick.datetime - self.last_master_tick.datetime).seconds <= 10:
                    combinable = True

        # 不能合并，返回
        if not combinable:
            return None, None, None

        # 初始化价差Ticket数据（成交数据，五档行情，时间）
        spread_tick = CtaTickData()

        # 属性
        spread_tick.vtSymbol = self.vtSymbol
        spread_tick.symbol = self.symbol
        # 使用主交易所比对的最后一个ticket的时间
        spread_tick.datetime = self.last_master_tick.datetime
        spread_tick.date = self.last_master_tick.date
        spread_tick.time = self.last_master_tick.time

        # 叫卖价差 = leg1.askPrice1 - leg2.bidPrice1

        # 价差tick的卖价 = 主交易所比对的最后一个tick的卖价 - 从交易所比对的最后一个tick的买价
        spread_tick.askPrice1 = self.last_master_tick.askPrice1 - self.last_slave_tick.bidPrice1

        # 成交量 = min（主交易所最后一个tick卖的成交量，从交易所最后一个tick买的成交量）
        spread_tick.askVolume1 = min(self.last_master_tick.askVolume1, self.last_slave_tick.bidVolume1)

        # 价差tick的最后价格 = 主交易所比对的最后一个tick的最后价格 - 从交易所比对的最后一个tick的最后价格
        spread_tick.lastPrice = self.last_master_tick.lastPrice - self.last_slave_tick.lastPrice

        # 叫买价差 = leg1.bidPrice1 - leg2.askPrice1

        # 价差tick的买价 = 主交易所比对的最后一个tick的买价 - 从交易所比对的最后一个tick的卖价
        spread_tick.bidPrice1 = self.last_master_tick.bidPrice1 - self.last_slave_tick.askPrice1

        # 成交量 = 取两个之中的较小值
        spread_tick.bidVolume1 = min(self.last_master_tick.bidVolume1, self.last_slave_tick.askVolume1)

        # 比率tick
        ratio_tick = copy.copy(spread_tick)

        # 比率tick的卖价 = 主交易所比对的最后一个tick的卖价 / 从交易所比对的最后一个tick的买价
        ratio_tick.askPrice1 = self.last_master_tick.askPrice1 / self.last_slave_tick.bidPrice1

        ratio_tick.bidPrice1 = self.last_master_tick.bidPrice1 / self.last_slave_tick.askPrice1

        ratio_tick.lastPrice = self.last_master_tick.lastPrice / self.last_slave_tick.lastPrice

        # 比率tick的最后价格
        ratio = ratio_tick.lastPrice
        # M1比率K线的均值
        if len(self.lineRatio.lineStateMean) > 0:
            #
            ratio = self.lineRatio.lineStateMean[-1]

        # ？？残差tick
        mean_tick = copy.copy(spread_tick)

        mean_tick.askPrice1 = self.last_master_tick.askPrice1 / ratio - self.last_slave_tick.bidPrice1
        mean_tick.bidPrice1 = self.last_master_tick.bidPrice1 / ratio - self.last_slave_tick.askPrice1
        mean_tick.lastPrice = self.last_master_tick.lastPrice / ratio - self.last_slave_tick.lastPrice
        # 返回价差ticket，比率ticket，均值ticket
        return spread_tick, ratio_tick, mean_tick

    # 开多指令
    def buy(self, volume):
        """跨市场套利开多（看涨开仓）指令"""
        self.writeCtaLog(u'开多单（看涨）,v:{}'.format(volume))
        # 交易标识
        if not self.isTrading:
            self.writeCtaLog(u'停止状态，不进行正套')
            return False

        # master_quote_position：主市场基准货币持仓；slave_base_position：从市场交易主货币持仓
        if self.master_quote_position is None or self.slave_base_position is None:
            self.writeCtaError(u'{}市场货币{}持仓为None，或{}市场{}持仓为None，不进行正套'
                               .format(self.master_gateway, self.quote_symbol, self.slave_exchange, self.base_symbol))
            return False

        # 主市场基准货币持仓.仓位（多头） / 主交易所比对的最后一个tick.最后价格 < 买入数量
        if self.master_quote_position.longPosition / self.last_master_tick.lastPrice < volume:
            self.writeCtaLog(
                u'{}市场货币:{}不足买入:{} {}'.format(self.master_gateway, self.quote_symbol, volume, self.base_symbol))
            return False

        # 从市场交易货币持仓.仓位数量 - 从交易所比对的冻结数量 < 卖出数量
        if (self.slave_base_position.longPosition - self.slave_base_position.frozen) < volume:
            self.writeCtaLog(
                u'{}市场货币:{} {},冻结数量:{}不足卖出:{} '
                    .format(self.slave_gateway, self.base_symbol,
                            self.slave_base_position.longPosition, self.slave_base_position.frozen, volume))
            return False

        # 主交易所，买入base
        # sendOrder（主交易所币对，u'买入'，主交易所比对得最后一个tick.买价 + 商品的最小交易价格单位，委托数量）
        orderID = self.cmaEngine.sendOrder(self.master_symbol, CTAORDER_BUY,
                                           self.last_master_tick.bidPrice1 + self.minDiff, volume, self)
        # 如果委托单ID为空，报告异常
        if orderID is None or len(orderID) == 0:
            self.writeCtaLog(u'异常，{} 开多{}失败,price:{}，volume:{}'.format(self.master_gateway, self.master_symbol,
                                                                       self.last_master_tick.bidPrice1 + self.minDiff,
                                                                       volume))
            return False

        # 属性
        order = {'SYMBOL': self.master_symbol, 'DIRECTION': DIRECTION_LONG,
                 'OFFSET': OFFSET_OPEN, 'Volume': volume,
                 'Price': self.last_master_tick.bidPrice1 + self.minDiff, 'TradedVolume': EMPTY_FLOAT,
                 'OrderTime': self.curDateTime, 'Canceled': False}
        self.writeCtaLog(u'登记未成交委托:{}:{}'.format(orderID, order))

        # 插入到未完成委托到列表
        self.uncompletedOrders[orderID] = order

        # 主市场存在多仓的委托
        self.master_entrust = 1

        # 从交易所，卖出base
        # 发送委托单（从交易所币对，u'卖出'，从交易所比对得最后一个tick.卖价 - 商品的最小交易价格单位，委托数量）
        orderID = self.cmaEngine.sendOrder(self.slave_symbol, CTAORDER_SELL,
                                           self.last_slave_tick.askPrice1 - self.minDiff, volume, self)
        # 如果委托单ID为空，报告异常
        if (orderID is None) or len(orderID) == 0:
            self.writeCtaLog(u'异常，{}卖出{}失败，price:{},volume:{}'.format(self.slave_gateway, self.slave_symbol,
                                                                      self.last_slave_tick.askPrice1 - self.minDiff,
                                                                      volume))
            return False

        # 属性
        order = {'SYMBOL': self.slave_symbol, 'DIRECTION': DIRECTION_SHORT,
                 'OFFSET': OFFSET_CLOSE, 'Volume': volume,
                 'Price': self.last_slave_tick.askPrice1 - self.minDiff, 'TradedVolume': EMPTY_FLOAT,
                 'OrderTime': self.curDateTime, 'Canceled': False}

        # 插入未完成委托到列表
        self.writeCtaLog(u'登记未成交委托:{}:{}'.format(orderID, order))
        self.uncompletedOrders[orderID] = order

        # 从市场存在空仓的委托
        self.slave_entrust = -1

        return True

    # 开空指令
    def sell(self, volume):
        """跨市场套利开空（看空开仓）指令"""
        self.writeCtaLog(u'套利价差反套单,v:{}'.format(volume))
        # 交易标识
        if not self.isTrading:
            self.writeCtaLog(u'停止状态，不开仓')
            return False

        # master_base_position：主市场交易货币持仓；slave_quote_position：从市场基准货币持仓
        if self.master_base_position is None or self.slave_quote_position is None:
            self.writeCtaLog(u'{}市场货币{}持仓为None，或{}市场{}持仓为None，不进行正套'
                             .format(self.master_gateway, self.base_symbol, self.slave_gateway, self.quote_symbol))
            return False

        # 主市场交易货币持仓.仓位 - 主市场交易货币持仓.冻结数量 < 委托数量
        if self.master_base_position.longPosition - self.master_base_position.frozen < volume:
            self.writeCtaLog(
                u'{}主市场货币:{} {},fz:{}不足卖出:{} '
                    .format(self.master_gateway, self.quote_symbol,
                            self.master_base_position.longPosition, self.master_base_position.frozen, volume))
            return False

        # 从市场基准货币持仓.仓位 / 从交易所比对得最后一个tick.最后价格 < 委托数量
        if self.slave_quote_position.longPosition / self.last_slave_tick.lastPrice < volume:
            self.writeCtaLog(
                u'{}从市场货币:{}不足买入:{} {}'.format(self.slave_gateway, self.quote_symbol, volume, self.base_symbol))
            return False

        # 主交易所，卖出base
        # sendOrder（主交易所币对，u'卖出'，主交易所比对得最后一个tick的卖价 - 商品的最小交易价格单位，委托数量）
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
                 'OrderTime': self.curDateTime, 'Canceled': False}
        self.writeCtaLog(u'登记未成交委托:{}:{}'.format(orderID, order))

        # 插入到未完成委托单列表
        self.uncompletedOrders[orderID] = order

        # 主市场存在空仓的委托
        self.master_entrust = -1

        # 从交易所，买入base
        # sendOrder（从交易所币对，u'买入'，从交易所比对得最后一个tick的买价 + 商品的最小交易价格单位，委托数量）
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
                 'OrderTime': self.curDateTime, 'Canceled': False}
        self.writeCtaLog(u'登记未成交委托:{}:{}'.format(orderID, order))

        #  插入到未完成委托单列表
        self.uncompletedOrders[orderID] = order

        # 从市场存在多仓的委托
        self.slave_entrust = 1

        return True

    # 更新持仓（更新主、从交易所持仓）
    def update_pos_info(self):
        # 主、从交易所持仓
        self.master_position = EMPTY_STRING
        self.slave_position = EMPTY_STRING

        # master_base_position：主交易主货币持仓
        if self.master_base_position:
            self.master_position += u'[{}:{},Fz:{}]'.format(self.base_symbol, self.master_base_position.longPosition,
                                                  self.master_base_position.frozen)
        # master_quote_position：主基准货币持仓
        if self.master_quote_position:
            self.master_position += u'[{}:{},Fz:{}]'.format(self.quote_symbol, self.master_quote_position.longPosition,
                                                  self.master_quote_position.frozen)
        if self.slave_base_position:
            self.slave_position += u'[{}:{},Fz:{}]'.format(self.base_symbol, self.slave_base_position.longPosition,
                                                  self.slave_base_position.frozen)
        if self.slave_quote_position:
            self.slave_position += u'[{}:{},Fz:{}]'.format(self.quote_symbol, self.slave_quote_position.longPosition,
                                                  self.slave_quote_position.frozen)

    # 行情更新（推入各自1分钟K线，合并合约，更新tick，执行撤单逻辑，进过逻辑判断后选择开多还是开空，更新持仓，发送事件）
    def onTick(self, tick):
        """行情更新
        :type tick: object
        """
        # 更新策略执行的时间（用于回测时记录发生的时间）
        self.curDateTime = tick.datetime

        # 价差Ticket
        spread_tick = None

        # 比率Ticket
        ratio_tick = None

        # 均值Ticket
        mean_tick = None

        # 分别推入各自1分钟k线---------------------------------------
        # vt系统合约代码 == 主交易所币对；
        if tick.vtSymbol == self.master_symbol and self.isInited:

            # 主交易货币对M1K线插入Ticket
            self.lineMaster.onTick(tick)

            self.master_base_position = self.cmaEngine.positionBufferDict.get(
                '.'.join([self.base_symbol, self.master_exchange]),
                None)

            self.master_quote_position = self.cmaEngine.positionBufferDict.get(
                '.'.join([self.quote_symbol, self.master_exchange]), None)

        # vt系统合约代码 == 从交易所币对；
        elif tick.vtSymbol == self.slave_symbol and self.isInited:

            # 插入Ticket
            self.lineSlave.onTick(tick)

            # 从交易所交易货币持仓 = 持仓缓存字典交易货币合约代码和从交易所的持仓
            self.slave_base_position = self.cmaEngine.positionBufferDict.get(
                '.'.join([self.base_symbol, self.slave_exchange]),
                None)
            # 从交易所基准货币持仓 = 持仓缓存字典基准货币合约代码和从交易所的持仓
            self.slave_quote_position = self.cmaEngine.positionBufferDict.get(
                '.'.join([self.quote_symbol, self.slave_exchange]),
                None)

        # 合并合约，得到价差ticket，比率ticket，均值ticket
        spread_tick, ratio_tick, mean_tick = self.__combineTick(tick)

        # 判断是否为空
        if spread_tick is None or ratio_tick is None or mean_tick is None:
            return

        # curTick：记录最新tick
        self.curTick = spread_tick

        # 是否完成了策略初始化
        if not self.isInited:
            return

        # 更新行情
        self.lineRatio.onTick(ratio_tick)
        self.lineDiff.onTick(spread_tick)
        self.lineMD.onTick(mean_tick)
        self.lineM5.onTick(ratio_tick)

        ##### 4.交易逻辑-----------------------------------------------------------

        # 首先检查是否是实盘运行还是数据预处理阶段
        if not (self.isInited and len(self.lineDiff.lineMiddleBand) > 0 and len(self.lineRatio.lineStateMean) > 0 and len(
                self.lineMD.lineMiddleBand) > 0 and len(self.lineM5.lineUpperBand) > 0):
            return

        # 执行撤单逻辑（撤掉未完成的委托单）
        self.cancelLogic(self.curDateTime)

        short_signal = False
        buy_signal = False

        # 若1分钟价差K线的布林线标准差小于2则m1_std = 2，否则m1_std = self.lineDiff.lineBollStd[-1]
        m1_std = 2 if self.lineDiff.lineBollStd[-1] < 2 else self.lineDiff.lineBollStd[-1]

        # 价差超过布林特线上轨，预测其会回归中线=》高位卖出---------------------------
        # 价差ticket.买价 > 1分钟价差K线.上轨 and 比率ticket.买价 > 5分钟比率K线.上轨 and 比率ticket.买价 >= 1.001
        if spread_tick.bidPrice1 > self.lineDiff.lineUpperBand[-1] \
                and ratio_tick.bidPrice1 > self.lineM5.lineUpperBand[-1] \
                and ratio_tick.bidPrice1 >= 1.001:
            self.writeCtaLog(u'Short Signal:{},sell master:{}/{}/{},buy slave:{}/{}/{}'
                             .format(spread_tick.bidPrice1,
                                     self.last_master_tick.askPrice1, self.last_master_tick.lastPrice,
                                     self.last_master_tick.bidPrice1,
                                     self.last_slave_tick.askPrice1, self.last_slave_tick.lastPrice,
                                     self.last_slave_tick.bidPrice1))

            # 当前没有委托，没有未完成的订单，没有重新激活的订单
            if self.master_entrust == 0 and self.slave_entrust == 0 and len(self.uncompletedOrders) == 0 and len(
                    self.policy.uncomplete_orders) == 0:
                self.sell(self.inputOrderCount)  # 反套（卖出）

        # 价差低于布林特线下轨，预测其会回归中线=》低位卖入---------------------------
        # spread_tick.卖价 < 1分钟价差K线.下轨 and ratio_tick.卖价 < 5分钟比率K线.下轨 and ratio_tick.买价 <= 0.999
        if spread_tick.askPrice1 < self.lineDiff.lineLowerBand[-1] \
                and ratio_tick.askPrice1 < self.lineM5.lineLowerBand[-1] \
                and ratio_tick.bidPrice1 <= 0.999:
            self.writeCtaLog(u'Buy Signal:{}, buy master:{}/{}/{}, sell slave:{}/{}/{}'
                             .format(spread_tick.askPrice1,
                                     self.last_master_tick.askPrice1, self.last_master_tick.lastPrice,
                                     self.last_master_tick.bidPrice1,
                                     self.last_slave_tick.askPrice1, self.last_slave_tick.lastPrice,
                                     self.last_slave_tick.bidPrice1))

            # 当前没有委托，没有未完成的订单，没有重新激活的订单
            if self.master_entrust == 0 and self.slave_entrust == 0 and len(self.uncompletedOrders) == 0 and len(
                    self.policy.uncomplete_orders) == 0:
                self.buy(self.inputOrderCount)  # 正套（买入）

        self.update_pos_info()  # 更新主、从交易所持仓
        self.putEvent()  # 策略状态变化事件

    # K线更新（显示1分钟价差K线的最后一个Bar信息）
    def onBar(self, bar):
        """分钟K线数据更新
        bar，k周期数据
        """
        # 显示M1价差K线的最后一个Bar信息
        self.writeCtaLog(self.lineDiff.displayLastBar())
        self.writeCtaLog(u'{}持仓: {}，{}持仓:{}'.format(self.master_gateway, self.master_position, self.slave_gateway, self.slave_position))
        self.writeCtaLog(u'{}委托状态:{},{}委托状态:{}'.format(self.master_gateway, self.master_entrust, self.slave_gateway,
                                                       self.slave_entrust))
        # 未完成委托单写入日志
        if len(self.uncompletedOrders) > 0:
            self.writeCtaLog(u'未完成委托单：{}'.format(self.uncompletedOrders))

        # 待重开委托单写入日志
        if len(self.policy.uncomplete_orders) > 0:
            self.writeCtaLog(u'待重开委托单:{}'.format(self.policy.uncomplete_orders))

    # 比率线更新
    def onBarRatio(self, bar):
        """比率线的OnBar事件"""
        # 获取比率线的长度
        l = len(self.lineRatio.lineStateMean)
        if l > 0:
            ma = self.lineRatio.lineStateMean[-1]
        else:
            ma = bar.close

        if l > 6:
            listKf = [x for x in self.lineRatio.lineStateMean[-7:-1]]
            # MA():？
            # numpy.array(listKf, dtype = float：转浮点型
            malist = ta.MA(numpy.array(listKf, dtype=float), 5)
            ma5 = malist[-1]
            ma5_ref1 = malist[-2]
            if ma5 <= 0 or ma5_ref1 <= 0:
                self.writeCtaLog(u'卡尔曼均线异常')
                return
            # ？
            self.m1_atan = math.atan((ma5 / ma5_ref1 - 1) * 100 * 180 / math.pi)
        # M1的切线队列长度 > 10
        if len(self.m1_atan_list) > 10:
            del self.m1_atan_list[0]
        # m1_atan_list加入m1_atan
        self.m1_atan_list.append(self.m1_atan)
        # displayLastBar()显示最后一个Bar的信息
        self.writeCtaLog(self.lineRatio.displayLastBar())

    # 残差线更新
    def onBarMeanDiff(self, bar):
        """残差线的OnBar事件"""
        # 一分钟残差线.上轨长度 > 0
        if len(self.lineMD.lineUpperBand) > 0:
            boll_upper = self.lineMD.lineUpperBand[-1]
        else:
            boll_upper = 0
        # 一分钟残差线.中轨长度 > 0
        if len(self.lineMD.lineMiddleBand) > 0:

            boll_mid = self.lineMD.lineMiddleBand[-1]
        else:
            boll_mid = 0

        # 一分钟残差线.下轨长度 > 0
        if len(self.lineMD.lineLowerBand) > 0:
            # 布林线下轨 = 1分组残差K线
            boll_lower = self.lineMD.lineLowerBand[-1]
        else:
            boll_lower = 0

        # 一分钟残差线.标准差长度 > 0
        if len(self.lineMD.lineBollStd) > 0:
            boll_std = self.lineMD.lineBollStd[-1]
        else:
            boll_std = 0

        self.writeCtaLog(self.lineMD.displayLastBar())

    # 5分钟K线更新
    def onBarM5(self, bar):
        """5分钟Ratio的OnBar事件"""
        # 5分钟比率K线的中线 < 2 或 5分钟比率K线的.. < 2
        if len(self.lineM5.lineMiddleBand) < 2 or len(self.lineM5.lineStateMean) < 2:
            return
        # 5分钟比率K线的CTA周期不为空？
        if self.lineM5.curPeriod is not None:
            self.m5_atan = self.lineM5.atan
            self.m5_period = u'{}=>{}'.format(self.lineM5.curPeriod.pre_mode, self.lineM5.curPeriod.mode)

        self.writeCtaLog(
            u'[M5-Ratio]{0} c:{1},kf:{2},m5_atan:{3},m5_atan:{4})'.format(bar.datetime, bar.close,
                                                                          self.lineM5.lineStateMean[-1],
                                                                          self.m1_atan, self.m5_atan))

    # 显示主交易所最后一个Bar信息
    def onBarMaster(self, bar):
        self.writeCtaLog(self.lineMaster.displayLastBar())

    # 显示从交易所最后一个Bar信息
    def onBarSlave(self, bar):
        self.writeCtaLog(self.lineSlave.displayLastBar())

    # 撤单（判断未完成列表长度，遍历委托单，判断委托单有无超时，撤销该委托单；委托单的剩余数量大于2倍下单最小成交单位，加入撤销列表，）
    def cancelLogic(self, dt, force=False):
        "撤单逻辑"""
        # 如果未完成委托单列表长度 < 1
        if len(self.uncompletedOrders) < 1:
            return

        # 委托单编号列表
        order_keys = list(self.uncompletedOrders.keys())

        # 遍历委托单编号列表
        for order_key in order_keys:
            # 委托单编号不在未完成委托单列表中
            if order_key not in self.uncompletedOrders:
                self.writeCtaError(u'{0}不在未完成的委托单中。'.format(order_key))
                continue
            # 获取此委托单
            order = self.uncompletedOrders[order_key]
            order_time = order['OrderTime']
            order_symbol = copy.copy(order['SYMBOL'])
            order_price = order['Price']
            # 获取Canceled的状态
            canceled = order.get('Canceled', True)
            # (当前时间 - 委托单时间).秒数 > 未成交撤单的秒数 和 Canceled状态为False
            if (dt - order_time).seconds > self.cancelSeconds and not canceled:
                self.writeCtaLog(u'{0}超时{1}秒未成交，取消委托单：{2}'.format(order_symbol, (dt - order_time).seconds, order_key))

                # 撤销该委托单
                self.cancelOrder(str(order_key))
                # 撤销状态为True
                order['Canceled'] = True

                # 委托数量 - 成交数量 > 2倍下单最小成交单位，即委托单可以重新下单
                if order['Volume'] - order['TradedVolume'] > 2 * self.min_trade_size:

                    # 待重开委托单字典加入此委托单
                    self.policy.uncomplete_orders.append(copy.copy(order))
                else:

                    # 委托单的合约代码 == 主交易所币对
                    if order['SYMBOL'] == self.master_symbol:

                        # 主交易所无委托
                        self.master_entrust = 0
                    else:

                        # 从交易所无委托
                        self.slave_entrust = 0

                    self.writeCtaLog(u'委托数量:{}，成交数量:{}，剩余数量:{},不足:{}，放弃重新下单'
                                     .format(order['Volume'], order['TradedVolume']
                                             , order['Volume'] - order['TradedVolume'], 2 * self.min_trade_size))

    # 重新提交订单（遍历待重开委托单列表，对撤销的委托单追平买入/卖出，追平后重新提交委托单，移除待重开委托单）
    def resumbit_orders(self):
        """重新提交订单"""
        # 遍历待重开委托单列表
        for order in list(self.policy.uncomplete_orders):
            # 委托单合约代码
            order_symbol = copy.copy(order['SYMBOL'])
            # 重新委托数量 = 委托数量 - 成交数量
            order_volume = order['Volume'] - order['TradedVolume']
            # 撤销的委托单，属于平仓类，需要追平
            if order['OFFSET'] == OFFSET_CLOSE and order['DIRECTION'] == DIRECTION_SHORT:
                # 委托单合约代码 == 主交易所币对
                if order_symbol == self.master_symbol:

                    # 卖出价格 = min(主交易所比对得最后一个tick.买价，主交易所比对得最后一个ticket.最后价格) - 商品的最小交易价格单位
                    # 价格低一点卖出
                    sellPrice = min(self.last_master_tick.bidPrice1, self.last_master_tick.lastPrice) - self.minDiff
                else:

                    # 卖出价格 = min(从交易所比对得最后一个tick.买价，从交易所比对得最后一个ticket.最后价格) - 商品的最小交易价格单位
                    sellPrice = min(self.last_slave_tick.bidPrice1, self.last_slave_tick.lastPrice) - self.minDiff

                # 委托单ID = sendOrder(委托单合约代码，u'卖出'，卖出价格，委托数量)
                orderID = self.cmaEngine.sendOrder(order_symbol, CTAORDER_SELL, sellPrice, order_volume, self)

                if orderID is None:
                    self.writeCtaError(u'重新提交{0} {1}手平多单{2}失败'.format(order_symbol, order_volume, sellPrice))
                    continue

                # 重新添加平多委托单
                new_order = {'SYMBOL': order_symbol, 'DIRECTION': DIRECTION_SHORT,
                             'OFFSET': OFFSET_CLOSE, 'Volume': order_volume,
                             'TradedVolume': EMPTY_INT,
                             'Price': sellPrice, 'OrderTime': self.curDateTime, 'Canceled': False}
                self.writeCtaLog(u'重新提交，登记未成交委托:{}:{}'.format(orderID, new_order))

                # 加入委托单到未完成列表
                self.uncompletedOrders[orderID] = new_order

                # 委托单的合约代码 = 主交易所币对
                if order_symbol == self.master_symbol:
                    # 标识主交易所空仓委托
                    self.master_entrust = -1
                else:
                    # 标识从交易所空仓委托
                    self.slave_entrust = -1

            # 属于开多委托单
            else:
                # 合约代码 = 主交易所币对
                if order_symbol == self.master_symbol:

                    # 买入价格 = max（主交易所比对得最后一个ticket.卖价，主交易所比对得最后一个ticket.最后价格）+ 商品的最小交易价格单位
                    # 价格高一点买入
                    buyPrice = max(self.last_master_tick.askPrice1, self.last_master_tick.lastPrice) + self.minDiff

                else:

                    # 买入价格 = max（从交易所比对得最后一个ticket.卖价，从交易所比对得最后一个ticket.最后价格）+ 商品的最小交易价格单位
                    buyPrice = max(self.last_slave_tick.askPrice1, self.last_slave_tick.lastPrice) + self.minDiff

                self.writeCtaLog(u'重新提交{0} {1}手开多单{2}'.format(order_symbol, order_volume, buyPrice))

                # sendOrder(合约代码，u'买入'，买入价格，委托数量)
                orderID = self.cmaEngine.sendOrder(order_symbol, CTAORDER_BUY, buyPrice, order_volume, self)

                # 如果编号为空
                if orderID is None or len(orderID) == 0:
                    self.writeCtaError(u'重新提交{0} {1}手开多单{2}失败'.format(order_symbol, order_volume, buyPrice))
                    continue

                # 重新添加委托单
                new_order = {'SYMBOL': order_symbol, 'DIRECTION': DIRECTION_LONG,
                             'OFFSET': OFFSET_OPEN, 'Volume': order_volume,
                             'Price': buyPrice, 'TradedVolume': EMPTY_INT,
                             'OrderTime': self.curDateTime, 'Canceled': False}
                self.writeCtaLog(u'重新提交，登记未成交委托:{}:{}'.format(orderID, new_order))
                # 加入到未完成委托单字典中
                self.uncompletedOrders[orderID] = new_order

                # 合约代码 = 主交易所币对
                if order_symbol == self.master_symbol:
                    # 标识主交易所多仓委托
                    self.master_entrust = 1
                else:
                    # 标识从交易所多仓委托
                    self.slave_entrust = 1

            self.writeCtaLog(u'移除未完成得订单:{}'.format(order))

            # 待重开委托单字典移除此委托单
            self.policy.uncomplete_orders.remove(order)

    # 保存数据
    def saveData(self):
        pass
