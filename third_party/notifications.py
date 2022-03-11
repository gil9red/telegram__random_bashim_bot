#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


# SOURCE: https://github.com/gil9red/Check_with_notification/blob/850d2a9c38ee0ef04278a6a599b54377a429fe2d/root_common.py#L75


import time

import requests

from config import SMS_API_ID, SMS_TO, DIR
from common import get_logger
from third_party.add_notify_telegram import add_notify


def send_sms(api_id: str, to: str, text: str, log):
    api_id = api_id.strip()
    to = to.strip()

    if not api_id or not to:
        log.warning('Параметры api_id или to не указаны, отправка СМС невозможна!')
        return

    log.info(f'Отправка sms: {text!r}')

    if len(text) > 70:
        text = text[:70-3] + '...'
        log.info(f'Текст sms будет сокращен, т.к. слишком длинное (больше 70 символов): {text!r}')

    # Отправляю смс на номер
    url = 'https://sms.ru/sms/send?api_id={api_id}&to={to}&text={text}'.format(
        api_id=api_id,
        to=to,
        text=text
    )
    log.debug(repr(url))

    while True:
        try:
            rs = requests.get(url)
            log.debug(repr(rs.text))
            break

        except:
            log.exception("При отправке sms произошла ошибка:")
            log.debug('Через 5 минут попробую снова...')

            # Wait 5 minutes before next attempt
            time.sleep(5 * 60)


def simple_send_sms(text: str, log=None):
    # Если логгер не определен, тогда создаем свой, который логирует в консоль
    if not log:
        log = get_logger('all_common', log_file=False)

    return send_sms(SMS_API_ID, SMS_TO, text, log)


def send_telegram_notification(
        name: str,
        message: str,
        type: str = 'INFO',
        url: str = None,
        has_delete_button: bool = False,
):
    try:
        add_notify(name=name, message=message, type=type, url=url, has_delete_button=has_delete_button)
    except Exception as e:
        log = get_logger('error_send_telegram', file=str(DIR / 'errors.txt'))
        log.exception('')

        simple_send_sms(f'[Error] {e}', log)

        # Пробрасываем ошибку, чтобы она не прошла незаметно для скриптов
        raise e


def send_telegram_notification_error(name: str, message: str):
    send_telegram_notification(name, message, 'ERROR', has_delete_button=True)
