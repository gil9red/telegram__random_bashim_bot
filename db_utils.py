#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import functools
import logging
import time

# pip install python-telegram-bot
from telegram import Update
from telegram.ext import CallbackContext

import config
from db import User, Chat, Quote, Request, Error


def process_request(logger: logging.Logger):
    def actual_decorator(func):
        @functools.wraps(func)
        def wrapper(update: Update, context: CallbackContext):
            try:
                user = chat = quote = None
                if update:
                    user = User.get_from(update.effective_user)
                    if user:
                        user.update_last_activity()

                    chat = Chat.get_from(update.effective_chat)
                    if chat:
                        chat.update_last_activity()

                t = time.perf_counter_ns()

                result = func(update, context)

                elapsed_ms = (time.perf_counter_ns() - t) // 1_000_000

                if isinstance(result, Quote):
                    quote = result

                Request.create(
                    func_name=func.__name__,
                    elapsed_ms=elapsed_ms,
                    user=user,
                    chat=chat,
                    quote=quote
                )

                return result

            except Exception as e:
                logger.exception('Error: %s\nUpdate: %s', context.error, update)

                Error.create_from(func, e, update)

                if update and update.message:
                    update.message.reply_text(config.ERROR_TEXT)

        return wrapper
    return actual_decorator
