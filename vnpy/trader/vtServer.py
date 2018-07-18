# encoding: utf-8

import os
import sys

import ctypes
from datetime import datetime, timedelta, date
from time import sleep
from threading import Thread

# 将repostory的目录i，作为根目录，添加到系统环境中。
ROOT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(ROOT_PATH)

from datetime import datetime
from time import sleep
from threading import Thread

import vtEvent
from vnpy.rpc import RpcServer
from vnpy.trader.vtEngine import MainEngine

from vnpy.trader.gateway import ctpGateway

init_gateway_names = {'CTP': ['CTP', 'CTP_Prod', 'CTP_Post', 'CTP_EBF', 'CTP_JR', 'CTP_JR2']}


########################################################################
class VtServer(RpcServer):
    """
        ---vn.trader服务器：
        注册主引擎方法
        注册通用事件处理函数
        运行服务器
    """

    # ----------------------------------------------------------------------
    def __init__(self, repAddress, pubAddress):
        """构造器"""
        super(VtServer, self).__init__(repAddress, pubAddress)
        # 使用cPickle作为数据的序列化工具
        self.usePickle()

        # 创建主引擎对象
        self.engine = MainEngine()

        for gw_name in init_gateway_names['CTP']:
            print('add {0}'.format(gw_name))
            # ？
            self.engine.addGateway(ctpGateway, gw_name)

        # 注册vtEngine的MainEngine的方法到Rpc服务器的功能函数字典__functions
        self.register(self.engine.connect)  # 连接特定名称的接口
        self.register(self.engine.disconnect)  # 断开底层gateway的连接
        self.register(self.engine.subscribe)  # 订阅特定接口的行情
        self.register(self.engine.sendOrder)  # 对特定接口发单
        self.register(self.engine.cancelOrder)  # 对特定接口撤单
        self.register(self.engine.qryAccount)  # 查询特定接口的账户
        self.register(self.engine.qryPosition)  # 查询特定接口的持仓
        self.register(self.engine.checkGatewayStatus)  # 检测gateway的连接状态
        self.register(self.engine.qryStatus)  # 检测ctaEngine的状态
        self.register(self.engine.exit)
        self.register(self.engine.writeLog)
        self.register(self.engine.dbConnect)
        self.register(self.engine.dbInsert)
        self.register(self.engine.dbQuery)
        self.register(self.engine.dbUpdate)
        self.register(self.engine.getContract)  # 查询合约
        self.register(self.engine.getAllContracts)
        self.register(self.engine.getOrder)  # 查询委托
        self.register(self.engine.getAllWorkingOrders)  # 查询所有的活跃的委托
        self.register(self.engine.getAllGatewayNames)  # 查询引擎中所有可用接口的名称
        self.register(self.engine.saveData)  # 保存策略的数据

        #  将通用事件处理函数注册到__generalHandlers中
        # __generalHandlers：用来保存通用回调函数（所有事件均调用）
        self.engine.eventEngine.registerGeneralHandler(self.eventHandler)

    # ----------------------------------------------------------------------
    def eventHandler(self, event):
        """事件处理"""
        # 打包数据，广播发送
        self.publish(event.type_, event)

    # ----------------------------------------------------------------------
    def stopServer(self):
        """停止服务器"""
        # 关闭主引擎
        self.engine.exit()

        # 停止服务器线程
        self.stop()


# ----------------------------------------------------------------------
def printLog(content):
    """打印日志"""
    print(datetime.now().strftime("%H:%M:%S"), '\t', content)


# ----------------------------------------------------------------------
def runServer():
    """运行服务器"""
    repAddress = 'tcp://*:2014'
    pubAddress = 'tcp://*:2016'

    # 创建并启动服务器
    server = VtServer(repAddress, pubAddress)
    server.start()  # 启动工作线程：__thread.start()

    printLog('-' * 50)
    printLog(u'vn.trader服务器已启动')

    # 进入主循环
    while True:
        printLog(u'请输入exit来关闭服务器')
        if raw_input() != 'exit':
            continue

        printLog(u'确认关闭服务器？yes|no')
        if raw_input() == 'yes':
            break

    # 停止服务器
    server.stopServer()


if __name__ == '__main__':
    runServer()
