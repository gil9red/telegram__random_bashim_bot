#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


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

REPLY_KEYBOARD_MARKUP = ReplyKeyboardMarkup([[KeyboardButton('Хочу цитату!')]], resize_keyboard=True)


def get_random_quotes_list():
    log.debug('get_random_quotes_list')

    quotes = []

    try:
        with urlopen(Request(config.URL, headers={'User-Agent': config.USER_AGENT})) as f:
            root = BeautifulSoup(f.read(), 'html.parser')

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
    global QUOTES_LIST
    log.debug('get_random_quote (QUOTES_LIST: %s)', len(QUOTES_LIST))

    quote_text, url = None, None

    try:
        # Если пустой, запрос и заполняем список новыми цитатами
        if not QUOTES_LIST:
            log.debug('QUOTES_LIST is empty, do new request.')
            QUOTES_LIST += get_random_quotes_list()

            log.debug('New quotes: %s.', len(QUOTES_LIST))

        # Перемешиваем список цитат и берем последний элемент
        random.shuffle(QUOTES_LIST)
        quote_text, url = QUOTES_LIST.pop()

    except Exception as e:
        log.exception(e)

    return quote_text, url


def error_callback(update, context):
    log.warning('Update "%s" caused error "%s"', update, context.error)


# TODO: может с цитатой передавать дату и рейтинг?
def work(update: Update, context: CallbackContext):
    log.debug('work')
    bot = context.bot

    try:
        text, url = get_random_quote()
        if config.LOG_QUOTE_TEXT:
            log.debug('Quote text (%s):\n%s', url, text)
        else:
            log.debug('Quote text (%s)', url)

        if not text:
            log.warning('Dont receive quote...')
            bot.sendMessage(update.message.chat_id, config.ERROR_TEXT)
            return

        # Отправка цитаты и отключение link preview -- чтобы по ссылке не генерировалась превью
        bot.sendMessage(
            update.message.chat_id,
            url + '\n\n' + text,
            disable_web_page_preview=True,
            reply_markup=REPLY_KEYBOARD_MARKUP
        )

    except Exception as e:
        log.exception(e)
        bot.sendMessage(update.message.chat_id, config.ERROR_TEXT)


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
