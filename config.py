#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import os
from pathlib import Path


DIR = Path(__file__).resolve().parent

DIR_LOG = DIR / 'logs'
DIR_LOG.mkdir(parents=True, exist_ok=True)

TOKEN_FILE_NAME = DIR / 'TOKEN.txt'
TOKEN = os.environ.get('TOKEN') or TOKEN_FILE_NAME.read_text('utf-8').strip()

try:
    SMS_TOKEN_FILE_NAME = DIR / 'SMS_TOKEN.txt'
    SMS_TOKEN = os.environ.get('SMS_TOKEN') or SMS_TOKEN_FILE_NAME.read_text('utf-8').strip()

    # <API_ID>:<PHONE>
    SMS_API_ID, SMS_TO = SMS_TOKEN.split(':')
except:
    SMS_API_ID, SMS_TO = '', ''
    print('[#] Рекомендуется задать SMS_TOKEN')

ADMIN_USERNAME = '@ilya_petrash'

DIR_COMICS = DIR / 'comics'
DIR_COMICS.mkdir(parents=True, exist_ok=True)

DB_DIR_NAME = DIR / 'database'
DB_DIR_NAME.mkdir(parents=True, exist_ok=True)

DB_FILE_NAME = str(DB_DIR_NAME / 'database.sqlite')

BACKUP_ROOT = Path('D:/')
BACKUP_DIR_NAME = BACKUP_ROOT / 'backup' / DIR.name

DB_DIR_NAME_ERROR = DIR / 'database_error'
DB_DIR_NAME_ERROR.mkdir(parents=True, exist_ok=True)

DB_FILE_NAME_ERROR = str(DB_DIR_NAME_ERROR / 'database_error.sqlite')

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
LENGTH_TEXT_OF_SMALL_QUOTE = 200

ITEMS_PER_PAGE = 10
COMMANDS_PER_PAGE = 5
ERRORS_PER_PAGE = 5
MAX_MESSAGE_LENGTH = 4096

DATE_FORMAT: str = '%d/%m/%Y'
DATE_TIME_FORMAT: str = f'{DATE_FORMAT} %H:%M:%S'
