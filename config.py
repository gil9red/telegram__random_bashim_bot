#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import os


TOKEN = os.environ.get('TOKEN') or open('TOKEN.txt', encoding='utf-8').read().strip()

URL = 'https://bash.im/random'
USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:48.0) Gecko/20100101 Firefox/48.0'

ERROR_TEXT = '⚠ Возникла какая-то проблема. Попробуйте повторить запрос или попробовать чуть позже...'
LOG_QUOTE_TEXT = False
