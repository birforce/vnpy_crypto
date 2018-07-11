# encoding: utf-8

import sys,os
# 将repostory的目录i，作为根目录，添加到系统环境中。
ROOT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(ROOT_PATH)

import hmac
import hashlib
import requests

import time
import base64
import json
from collections import OrderedDict

from concurrent import futures

from fcoin import Fcoin
from time import sleep

from datetime import datetime
from vnpy.trader.util_gpid import *
import signal

#account1 
accessKey = 'xxx'
secretyKey = 'xxx'

log_file = "log.log"

log_file = open(log_file , "w")


'''
'''
def writeLog(msg):
    global log_file

    print(msg)

    s = datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " : " + msg + "\n"
    log_file.write(s)
    log_file.flush()

'''
'''
def runBuy( accessKey , secretyKey , price, volume):
    fcoin = Fcoin()
    fcoin.auth(accessKey, secretyKey) 

    return fcoin.buy('btcusdt', price, volume)

'''
'''
def runSell(accessKey , secretyKey , price , volume):
    fcoin = Fcoin()
    fcoin.auth(accessKey, secretyKey) 

    return fcoin.sell('btcusdt', price, volume)

'''
'''
def deal( price , bidPrice1 , askPrice1 , volume = 1  ):
    """
    同时发单
    :param price:
    :param bidPrice1:
    :param askPrice1:
    :param volume:
    :return:
    """
    with futures.ThreadPoolExecutor(max_workers=2) as executor:

        future1 = executor.submit(runBuy , accessKey , secretyKey, bidPrice1 , volume)
        future2 = executor.submit(runSell , accessKey , secretyKey , askPrice1 , volume)

        print(future1.result())
        print(future2.result())

'''
'''
def cancelAll():
    print("cancelAll")
    sleep(1.5)

    cancel_order_nums = 3
    public_order_deal = Fcoin()
    public_order_deal.auth( accessKey , secretyKey)

    all_orders = []
    
    for state in ["submitted" , "partial_filled" ]:
        result,data = public_order_deal.list_orders( symbol = "btcusdt" , states = state)

        if str(data["status"]) == "0":
            orders = data["data"]

            for use_order in orders:
                all_orders.append(use_order)

        sleep(2)

    if len(all_orders) > 0:        
        buy_order_array = []
        sell_order_array = []

        for use_order in all_orders:
            systemID = str(use_order["id"])
            status = use_order["state"]
            tradedVolume = float(use_order["filled_amount"])
            totalVolume = float(use_order["amount"])
            price = float(use_order["price"])
            side = use_order["side"]

            if status in ["partial_filled" , "submitted" , "partial_canceled"]:
                if side == "buy":
                    buy_order_array.append( [price , systemID])
                else:
                    sell_order_array.append( [price , systemID])

        all_need_cancel = []
        if len(buy_order_array) > cancel_order_nums:
            sort_buy_arr = sorted(buy_order_array , key=lambda price_pair: price_pair[0] )
            sort_buy_arr.reverse()

            print('sort_buy_arr :{}'.format(sort_buy_arr))

            for i in range(cancel_order_nums , len(sort_buy_arr)):
                all_need_cancel.append( str(sort_buy_arr[i][1]) )
                # public_order_deal.cancel_order( str(sort_buy_arr[i][1]))

        if len(sell_order_array) > cancel_order_nums:
            sort_sell_arr = sorted(sell_order_array , key=lambda price_pair: price_pair[0] )

            print (u'sort_sell_arr'.format(sort_sell_arr))
            
            for i in range(cancel_order_nums , len(sell_order_array)):
                all_need_cancel.append( str(sort_sell_arr[i][1]) )

        for systemID in all_need_cancel:
            try:
                print(public_order_deal.cancel_order( systemID ))
                sleep(1.5)
            except Exception as ex:
                print (ex,file=sys.stderr)

    else:
        print("order_all is not ")

'''
'''
def getMidPrice():
    """
    获取btc_usdt的深度行情
    :return:
    """
    public_ticker = Fcoin()

    result, data = public_ticker.get_market_depth( "L20" , "btcusdt")
    if data["status"] == 0:
        info = data["data"]

        bids_data = info["bids"]
        asks_data = info["asks"]

        bids_data = [float(x) for x in bids_data]
        asks_data = [float(x) for x in asks_data]
    
        llen_bids = len(bids_data)
        llen_asks = len(asks_data)

        new_bids_arr = []
        for i in range(int(llen_bids / 2)):
            new_bids_arr.append( [bids_data[2*i] , bids_data[2*i+1]] )

        new_asks_arr = []
        for i in range(int(llen_asks / 2)):
            new_asks_arr.append( [asks_data[2*i] , asks_data[2*i+1]] )

        sort_bids_data = sorted(new_bids_arr , key=lambda price_pair: price_pair[0] )
        sort_asks_data = sorted(new_asks_arr, key=lambda price_pair: price_pair[0] )

        sort_bids_data.reverse()

        bidPrice1, bidVolume1 = sort_bids_data[0]
        askPrice1, askVolume1 = sort_asks_data[0]

        midPrice = (bidPrice1 + askPrice1) / 2.0

        midPrice = round(midPrice , 2)

        return (midPrice , bidPrice1 , askPrice1)
    else:
        return None , None , None

'''
'''
def getBalance():
    """
    返回 btc/usdt/ft的持仓信息
    :return:
    """
    public_balance_deal = Fcoin()
    public_balance_deal.auth( accessKey , secretyKey)
    result, data = public_balance_deal.get_balance()

    btc_num = 0
    usdt_num = 0
    ft_num = 0
    if str(data["status"]) == "0":
        for info in data["data"]:
            currency = info["currency"].lower()
            if currency == "btc":
                btc_num = float(info["balance"])

            if currency == "usdt":
                usdt_num = float(info["balance"])

            if currency == "ft":
                ft_num = float(info["balance"])

        return btc_num , usdt_num , ft_num

    else:
        return btc_num , usdt_num , ft_num

'''
运行脚本
'''
def run( volume = 0.003 , hard_flag = False):
    count_time = 0

    flag = False
    usdt_val = 0.0  # usdt持仓
    btc_val  = 0.0  # btc持仓
    ft_val   = 0.0  # ft持仓
    for i in range( 5 ):
        try:
            # 获取持仓
            btc_val , usdt_val , ft_val = getBalance()
            sleep(1.5)

            break
        except Exception as ex:
            print (ex,file=sys.stderr)

    all_msg = "now usdt_val:{} , btc_val:{}".format(usdt_val , btc_val)

    writeLog(all_msg)

    # 如果 usdt 持仓，超过 btc等值持仓
    if usdt_val > btc_val * 6400:
        flag = True

    while True:
        try:
            #if ft_val < 2000:
            #    writeLog( "ft is all used! < 2000")
            #    break
            dt = datetime.now()
            if dt.minute == 1:
                gpid_file = os.path.abspath(os.path.join(os.path.dirname(__file__), 'logs', 'gpid.txt'))
                gpid = 0
                if os.path.exists(gpid_file):
                    with open(gpid_file, 'r') as f:
                        gpid = f.read().strip()
                        gpid = int(gpid)
                        print(u'gpid={}'.format(gpid))

                    if gpid > 0:
                        os.kill(gpid, signal.SIGTERM)

            count_time += 1

            # 获取中间价，买1价，卖1价
            midPrice , bidPrice1 , askPrice1 = getMidPrice()

            if midPrice != None:

                # print "before" , midPrice , bidPrice1 , askPrice1
                if flag == True:
                    # usdt 占比多，降低usdt占比
                    bidPrice1 = bidPrice1 + 0.01
                    askPrice1 = askPrice1 + 0.01

                else:
                    # btc占比多，降低btc
                    bidPrice1 = bidPrice1 - 0.01
                    askPrice1 = askPrice1 - 0.01

                deal(midPrice ,  bidPrice1 , askPrice1 , volume )

            if count_time % 6 == 0:
                cancelAll()

                btc_val , usdt_val  , ft_val = getBalance()
                sleep(1.5)
                total_usdt = float(btc_val) * float(midPrice) + usdt_val
                
                now_msg = "now usdt_val:{} , btc_val:{} ,ft_val:{} total_usdt:{}".format(usdt_val , btc_val ,ft_val, total_usdt )
                writeLog(now_msg)

                if hard_flag == False:
                    # 采用总仓位的1/10 进行下单
                    volume = round( total_usdt / midPrice / 10.0 , 3)

                now_msg = "now volume is {}".format(volume)
                writeLog(now_msg)

                if usdt_val > btc_val * 6700:
                    flag = True
                else:
                    flag = False

        except Exception as ex:
            print (ex,file=sys.stderr)


if __name__ == '__main__':

    cancelAll()
    run(0.03, hard_flag = True)
    
    # if len(sys.argv) > 1:
    #   deal(float(sys.argv[1]) , volume = 0.01)
    # else:
    #   print "canshu not enough"
