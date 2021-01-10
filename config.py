#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import os
from pathlib import Path


DIR = Path(__file__).resolve().parent
TOKEN_FILE_NAME = DIR / 'TOKEN.txt'

TOKEN = os.environ.get('TOKEN') or TOKEN_FILE_NAME.read_text('utf-8').strip()

ADMIN_USERNAME = '@ilya_petrash'

DIR_COMICS = DIR / 'comics'
DIR_COMICS.mkdir(parents=True, exist_ok=True)

URL = 'https://bash.im/random'
USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:48.0) Gecko/20100101 Firefox/48.0'

ERROR_TEXT = 'Возникла какая-то проблема. Попробуйте повторить запрос или попробовать чуть позже...'

TEXT_BUTTON_MORE = 'Хочу цитату!'
HELP_TEXT = (
    f'Для получения цитаты отправьте любое сообщение, '
    f'или нажмите на кнопку "{TEXT_BUTTON_MORE}", '
    f'или отправьте команду /more'
)

CHECKBOX = '✅'
CHECKBOX_EMPTY = '⬜'

RADIOBUTTON = '🟢'
RADIOBUTTON_EMPTY = '⚪️'

QUOTES_LIMIT = 20

IGNORED_LAST_QUOTES = 2000
LIMIT_UNIQUE_QUOTES = [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9999]

MAX_MESSAGE_LENGTH = 4096
