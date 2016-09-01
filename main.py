#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


def get_logger():
    import logging
    import sys

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


import config


from lxml import etree
from urllib.request import urlopen, Request
from urllib.parse import urljoin


def get_random_quote():
    log.debug('get_random_quote')
    quote_text, url = None, None

    try:
        with urlopen(Request(config.URL, headers={'User-Agent': config.USER_AGENT})) as f:
            root = etree.HTML(f.read())

            # TODO: брать рандомный элемент с цитатой
            quote_el = root.xpath('//*[@class="quote"]')[0]
            text_el = quote_el.xpath('//*[@class="text"]')[0]

            url = urljoin(config.URL, quote_el.xpath('//*[@class="id"]')[0].attrib['href'])
            log.debug(url)

            # По умолчанию, lxml работает с байтами и по умолчанию считает, что работает с ISO8859-1 (latin-1)
            # а на баше кодировка страниц cp1251, поэтому сначала нужно текст раскодировать в байты,
            # а потом закодировать как cp1251
            quote_text = '\n'.join([text.encode('ISO8859-1').decode('cp1251') for text in text_el.itertext()])
            if config.LOG_QUOTE_TEXT:
                log.debug(quote_text)

    except Exception as e:
        log.exception(e)

    return quote_text, url


from telegram.ext import Updater, MessageHandler, CommandHandler, Filters
from telegram import ReplyKeyboardMarkup, KeyboardButton


REPLY_KEYBOARD_MARKUP = ReplyKeyboardMarkup([[KeyboardButton('Хочу цитату!')]], resize_keyboard=True)


def error(bot, update, error):
    log.error('Update "%s" caused error "%s"' % (update, error))


# TODO: может с цитатой передавать дату и рейтинг?
def work(bot, update):
    log.debug('work')

    try:
        text, url = get_random_quote()
        if config.LOG_QUOTE_TEXT:
            log.debug('Quote text (%s):\n%s', url, text)
        else:
            log.debug('Quote text (%s)', url)

        if text is None:
            log.warn('Dont receive quote...')
            bot.sendMessage(update.message.chat_id, config.ERROR_TEXT)
            return

        # Отправка цитаты и отключение link preview -- чтобы по ссылке не генерировалась превью
        bot.sendMessage(update.message.chat_id,
                        url + '\n\n' + text,
                        disable_web_page_preview=True,
                        reply_markup=REPLY_KEYBOARD_MARKUP)

    except Exception as e:
        log.exception(e)
        bot.sendMessage(update.message.chat_id, config.ERROR_TEXT)


# TODO: оптимизировать работу, кэшируя цитаты:
# Держать в памяти цитаты и при запросе от телеграмма, вытаскивать случайную, пока не закончится список
# После того как список закончился, сделать запрос на башорг, скачать следующую пачку цитат, поместить в список
# и отдать случайную
if __name__ == '__main__':
    log.debug('Start')

    # Create the EventHandler and pass it your bot's token.
    updater = Updater(config.TOKEN)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', work))
    dp.add_handler(MessageHandler([Filters.text], work))

    # log all errors
    dp.add_error_handler(error)

    # Start the Bot
    updater.start_polling()

    # Run the bot until the you presses Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()

    log.debug('Finish')
