# encoding: UTF-8

print('laod vtConstant.py')

# 默认空值
EMPTY_STRING = ''
EMPTY_UNICODE = u''
EMPTY_INT = 0
EMPTY_FLOAT = 0.0

# k线颜色
COLOR_RED = u'Red'      # 上升K线
COLOR_BLUE = u'Blue'    # 下降K线
COLOR_EQUAL = u'Equal'  # 平K线

# 策略若干判断状态
NOTRUN = u'NotRun'   # 没有运行；
RUNING = u'Runing'   # 正常运行；
FORCECLOSING = u'ForceClosing'  #正在关闭
FORCECLOSED = u'ForceClosed'    #:已经关闭

# 交易方向
DIRECTION_LONG = u'DirectionLong'      # 做多
DIRECTION_SHORT = u'DirectionShort'    # 做空
DIRECTION_NET = u'DirectionNet'

# 交易属性
PRICETYPE_LIMITPRICE = u'PriceTypeLimitPrice'
PRICETYPE_MARKETPRICE = u'PriceTypeMarketPrice'
OFFSET_OPEN = u'OffsetOpen'
OFFSET_CLOSE = u'OffsetClose'
STATUS_ALLTRADED = u'StatusAllTraded'
STATUS_CANCELLED = u'StatusCancelled'
STATUS_REJECTED = u'StatusRejected'
STATUS_NOTTRADED = u'StatusNotTraded'
STATUS_PARTTRADED = u'StatusPartTraded'
STATUS_UNKNOWN = u'Status_Unknown'

GATEWAYTYPE_BTC = u'GatewayType_BTC'

# 交易所
EXCHANGE_OKEX = u'Okex'
EXCHANGE_BINANCE = u'Binance'
EXCHANGE_GATEIO = u'GateIo'
EXCHANGE_FCOIN = u'FCoin'
EXCHANGE_HUOBI = u'Huobi'
EXCHANGE_BITMEX = u'Bitmex'

from vnpy.trader.language import constant

# 将常量定义添加到vtConstant.py的局部字典中
d = locals()
for name in dir(constant):
    if '__' not in name:
        d[name] = constant.__getattribute__(name)
