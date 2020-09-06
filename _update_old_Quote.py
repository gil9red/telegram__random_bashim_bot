#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import datetime as DT
from random import randint
import time

from common import update_quote
from db import Quote


for quote in Quote.select().where(
    Quote.modification_date <= DT.date(2020, 9, 6)
):
    update_quote(quote.id)

    # 5 - 20
    seconds = randint(5, 20)
    time.sleep(seconds)
