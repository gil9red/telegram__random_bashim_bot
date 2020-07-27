#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import html
import logging
import sys
from urllib.request import urlopen, Request
from urllib.parse import urljoin
import random

import config

from bs4 import BeautifulSoup

# pip install python-telegram-bot
from telegram.ext import Updater, MessageHandler, CommandHandler, Filters, CallbackContext
from telegram import ReplyKeyboardMarkup, KeyboardButton, Update


def get_logger():
    log = logging.getLogger(__name__)
    log.setLevel(logging.DEBUG)

    formatter = logging.Formatter('[%(asctime)s] %(filename)s[LINE:%(lineno)d] %(levelname)-8s %(message)s')

    fh = logging.FileHandler('log', encoding='utf-8')
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(stream=sys.stdout)
    ch.setLevel(logging.DEBUG)

    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    log.addHandler(fh)
    log.addHandler(ch)

    return log


log = get_logger()


# Хранилище цитат башорга, из которого будут браться цитаты, и посылаться в телеграм.
# Когда этот список будет пустым, оно будет заполнено с сайта.
QUOTES_LIST = list()

REPLY_KEYBOARD_MARKUP = ReplyKeyboardMarkup(
    [['Хочу цитату!']], resize_keyboard=True
)


# SOURCE: https://github.com/gil9red/SimplePyScripts/blob/511a9fb408d8e8e470ce7f3ea4bcbf8d632e10a6/random_quote_bashim.py#L16
def get_random_quotes_list():
    log.debug('get_random_quotes_list')

    quotes = []

    try:
        with urlopen(Request(config.URL, headers={'User-Agent': config.USER_AGENT})) as f:
            root = BeautifulSoup(f.read(), 'html.parser')

            # Remove comics
            for x in root.select('.quote__strips'):
                x.decompose()

            for quote_el in root.select('.quote'):
                try:
                    href = quote_el.select_one('.quote__header_permalink')['href']
                    url = urljoin(config.URL, href)
                    quote_text = quote_el.select_one('.quote__body').get_text(separator='\n', strip=True)
                    quotes.append((quote_text, url))
                except IndexError:
                    pass

    except Exception as e:
        log.exception(f'{e} + \n\nQuote:\n{quote_el}')

    return quotes


def get_random_quote():
    log.debug('get_random_quote (QUOTES_LIST: %s)', len(QUOTES_LIST))

    quote_text, url = None, None

    try:
        # Если пустой, запрос и заполняем список новыми цитатами
        if not QUOTES_LIST:
            log.debug('QUOTES_LIST is empty, do new request.')
            QUOTES_LIST.extend(get_random_quotes_list())

            log.debug('New quotes: %s.', len(QUOTES_LIST))

        quote_text, url = QUOTES_LIST.pop()

    except Exception as e:
        log.exception(e)

    return quote_text, url


def get_html_message(text: str, url: str) -> str:
    link = f"""<a href="{url}">#{url.split('/')[-1]}</a>"""
    return html.escape(text) + '\n' + link


def error_callback(update: Update, context: CallbackContext):
    log.warning('Update "%s" caused error "%s"', update, context.error)


# TODO: может с цитатой передавать дату и рейтинг?
def work(update: Update, context: CallbackContext):
    chat_id = None
    if update.effective_chat:
        chat_id = update.effective_chat.id
    elif update.effective_user:
        chat_id = update.effective_user.id

    log.debug('work[chat_id=%s]', chat_id)

    try:
        text, url = get_random_quote()
        if config.LOG_QUOTE_TEXT:
            log.debug('Quote text (%s):\n%s', url, text)
        else:
            log.debug('Quote text (%s)', url)

        if not text:
            log.warning("Don't receive quote...")
            update.message.reply_text(config.ERROR_TEXT)
            return

        # Отправка цитаты и отключение link preview -- чтобы по ссылке не генерировалась превью
        update.message.reply_html(
            get_html_message(text, url),
            disable_web_page_preview=True,
            reply_markup=REPLY_KEYBOARD_MARKUP
        )

    except Exception as e:
        log.exception(e)
        update.message.reply_text(config.ERROR_TEXT)


if __name__ == '__main__':
    log.debug('Start')

    # Create the EventHandler and pass it your bot's token.
    updater = Updater(config.TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', work))
    dp.add_handler(MessageHandler(Filters.text, work))

    # log all errors
    dp.add_error_handler(error_callback)

    # Start the Bot
    updater.start_polling()

    # Run the bot until the you presses Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()

    log.debug('Finish')
