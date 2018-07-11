
#!-*-coding:utf-8 -*-
#@TIME    : 2018/6/10/0010 11:56
#@Author  : Nogo



class balance(object):

    def __init__(self, available, frozen, balance):
        self._available = available
        self._frozen = frozen
        self._balance = balance

    @property
    def available(self):
        return self._available

    @available.setter
    def available(self, value):
        self._available = value

    @property
    def frozen(self):
        return self._frozen

    @frozen.setter
    def frozen(self, value):
        self._frozen = value

    @property
    def balance(self):
        return self._balance

    @balance.setter
    def balance(self, value):
        self._balance = value