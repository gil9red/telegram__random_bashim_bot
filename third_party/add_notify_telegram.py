#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


# SOURCE: https://github.com/gil9red/SimplePyScripts/blob/e86c04660322fd2b7671d7023e565170e24f3114/telegram_notifications/add_notify_use_web.py


import requests


HOST = '127.0.0.1'
PORT = 10016

URL = f'http://{HOST}:{PORT}/add_notify'


def add_notify(name: str, message: str, type='INFO'):
    data = {
        'name': name,
        'message': message,
        'type': type,
    }

    rs = requests.post(URL, json=data)
    rs.raise_for_status()


if __name__ == '__main__':
    add_notify('TEST', 'Hello World! Привет мир!')
    add_notify('', 'Hello World! Привет мир!')
    add_notify('Ошибка!', 'Hello World! Привет мир!', 'ERROR')
