
#!-*-coding:utf-8 -*-
#@TIME    : 2018/5/30/0030 15:18
#@Author  : Nogo

import config
from pymongo import MongoClient
from bson.objectid import ObjectId
import datetime

settings = {
    "ip": '121.41.84.202',      #ip
    "port": 27017,              #端口
    "db_name": "fcoin",         #数据库名字
    "col": config.col_name,     #集合名字
}

class mongodb():
    def __init__(self):
        try:
            self.conn = MongoClient(settings["ip"], settings["port"])
        except Exception as e:
            print(e)
        self.db = self.conn[settings["db_name"]]

    def add(self, type, price, amount):
        col = self.db[settings['col']]
        if col:
            data = {}
            data['type'] = type
            data['price'] = price
            data['amount'] = amount
            data['state'] = 0
            data['createTime'] = datetime.datetime.now()-datetime.timedelta(hours=8) #time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            try:
                col.insert(data)
                return True, ''
            except Exception as e:
                error = e
        else:
            error = '集合不存在'
        return False, error

    def get(self, type, cur_price):
        try:
            col = self.db[settings['col']]
            if col:
                result = col.find_one({'type': type, 'state': 0, 'price': {'$lt': cur_price}})
                return result
            else:
                return None
        except Exception as e:
            print('error', e)
            return None


    def update_state(self,id,state=-1):
        try:
            col = self.db[settings['col']]
            if col:
                col.update({'_id': ObjectId(id)}, {'$set': {'state': state}})
        except Exception as e:
            print('error', e)


    def update(self, id, amount):
        try:
            col = self.db[settings['col']]
            if col:
                col.update({'_id': ObjectId(id)}, {'$inc':{'amount':-amount}})
        except Exception as e:
            print('error', e)
