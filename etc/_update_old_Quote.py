#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = "ipetrash"


import datetime as dt
import time
from random import randint

from bot.db_utils import update_quote
from bot.db import Quote, fn


i = 0
for quote in (
    Quote.select()
    .where(Quote.modification_date <= dt.date(2020, 9, 6))
    .order_by(fn.Random())
):
    i += 1
    while True:
        try:
            print(i, quote.id)
            update_quote(quote.id)
            break
        except:
            time.sleep(60)

    seconds = randint(20, 60)
    time.sleep(seconds)
