#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import enum
import logging
import re
import time
from typing import Optional, Dict, List, Callable

# pip install python-telegram-bot
from telegram import (
    Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction, ParseMode
)
from telegram.ext import Updater, MessageHandler, CommandHandler, Filters, CallbackContext, CallbackQueryHandler

import db
from config import (
    ERROR_TEXT, DIR_COMICS, CHECKBOX, CHECKBOX_EMPTY, RADIOBUTTON, RADIOBUTTON_EMPTY, LIMIT_UNIQUE_QUOTES,
    MAX_MESSAGE_LENGTH, ITEMS_PER_PAGE
)
from common import (
    log, log_func, REPLY_KEYBOARD_MARKUP, FILTER_BY_ADMIN, fill_commands_for_help,
    update_quote, reply_help, reply_error, reply_quote, reply_info,
    BUTTON_HELP_COMMON, BUTTON_HELP_ADMIN, START_TIME, get_elapsed_time,
    get_deep_linking, split_list, get_page, is_equal_inline_keyboards, reply_text_or_edit_with_keyboard_paginator
)
from db_utils import process_request, get_user_message_repr, catch_error
from third_party import bash_im


PATTERN_QUOTE_STATS = re.compile(r'(?i)^quote[ _]stats$|^статистика[ _]цитат$')
PATTERN_QUERY_QUOTE_STATS = 'quote_stats'

PATTERN_COMICS_STATS = re.compile(f'^comics_stats$')

PATTERN_GET_QUOTES = re.compile(r'^get_(\d+)_([\d,]+)$')
PATTERN_GET_USERS_SHORT_BY_PAGE = re.compile(r'^get_users_short_by_page_(\d+)$')
PATTERN_GET_USER_BY_PAGE = re.compile(r'^get_user_by_page_(\d+)$')


# SOURCE: https://github.com/gil9red/telegram_bot__gamebook/blob/7b7399c83ae6249da9dc92ea5dc475cc0565edc0/bot/regexp.py#L22
def fill_string_pattern(pattern: re.Pattern, *args) -> str:
    pattern = pattern.pattern
    pattern = pattern.strip('^$')
    return re.sub(r'\(.+?\)', '{}', pattern).format(*args)


def composed(*decs) -> Callable:
    def deco(f):
        for dec in reversed(decs):
            f = dec(f)
        return f
    return deco


def mega_process(func) -> Callable:
    return composed(
        catch_error(log),
        process_request(log),
        log_func(log),
    )(func)


class SettingState(enum.Enum):
    YEAR = " ⁃ Фильтрация получения цитат по годам"
    LIMIT = " ⁃ Количество получаемых уникальных цитат"  # TODO: Удалить, т.к. ограничения нет смысла использовать
    MAIN = enum.auto()

    def get_callback_data(self) -> str:
        return str(self).replace('.', '_')

    def get_pattern_with_params(self) -> re.Pattern:
        return re.compile('^' + self.get_callback_data() + '_(.+)$')

    def get_pattern_full(self) -> re.Pattern:
        return re.compile(
            '^' + self.get_callback_data() + '$|' + self.get_pattern_with_params().pattern
        )


INLINE_KEYBOARD_BUTTON_BACK = InlineKeyboardButton(
    "<назад>", callback_data=SettingState.MAIN.get_callback_data()
)


def get_random_quote(update: Update, context: CallbackContext) -> Optional[db.Quote]:
    user = db.User.get_from(update.effective_user)

    if 'quotes' not in context.user_data:
        context.user_data['quotes'] = []

    quotes = context.user_data['quotes']
    log.debug(f'get_random_quote (quotes: {len(quotes)})')

    # Заполняем список новыми цитатами, если он пустой
    if not quotes:
        log.debug('Quotes is empty, filling from database.')

        years_of_quotes = user.get_years_of_quotes()
        update_cache(user, years_of_quotes, log, update, context)

    if quotes:
        return quotes.pop()

    return


def get_context_value(context: CallbackContext) -> Optional[str]:
    value = None
    try:
        # Значение вытаскиваем из регулярки
        if context.match:
            value = context.match.group(1)
        else:
            # Значение из значений команды
            value = ' '.join(context.args)
    except:
        pass

    return value


def get_quote_id(context: CallbackContext) -> Optional[int]:
    try:
        value = get_context_value(context)
        return int(value)
    except:
        pass


def reply_local_quote(
        update: Update, context: CallbackContext,
        quote_id: int = None, **kwargs
) -> Optional[db.Quote]:
    if not quote_id:
        quote_id = get_quote_id(context)

    if not quote_id:
        reply_error('Номер цитаты не указан', update, context)
        return

    quote_obj = db.Quote.get_or_none(quote_id)
    if not quote_obj:
        reply_error(f'Цитаты #{quote_id} нет в базе', update, context)
        return

    reply_quote(
        quote_obj, update,
        context,
        **kwargs
    )

    return quote_obj


def reply_quote_ids(items: List[int], update: Update, context: CallbackContext):
    sep = ', '

    def _get_search_result(items: list) -> str:
        result = sep.join(get_deep_linking(quote_id, update) for quote_id in items)
        return f'Найдено {len(items)}:\n{result}'

    def _get_result(items: list, post_fix='...') -> str:
        text = _get_search_result(items)
        if len(text) <= MAX_MESSAGE_LENGTH:
            return text

        # Результат может быть слишком большим, а нужно вместить сообщение в MAX_MESSAGE_LENGTH
        # Поэтому, если при составлении текста результата длина вышла больше нужно уменьшить
        prev = 0
        while True:
            i = text.find(sep, prev + 1)
            if i == -1:
                break

            # Если на этой итерации кусочек текста превысил максимум, значит нужно остановиться,
            # а предыдущий кусочек текста сохранить -- его размер как раз подходит
            if len(text[:i]) + len(post_fix) > MAX_MESSAGE_LENGTH:
                text = text[:prev] + post_fix
                break

            prev = i

        return text

    if items:
        text = _get_result(items)
    else:
        text = 'Не найдено!'

    from_message_id = update.effective_message.message_id

    # Первые 50 результатов
    max_results = 50

    # Результат будет разделен по группам: 1-5, 6-10, ...
    parts = 5

    buttons = []
    for i in range(0, len(items[:max_results]), parts):
        sub_items = items[i:i + parts]
        start = i + 1
        end = i + len(sub_items)
        text_btn = f'{start}' if start == end else f'{start}-{end}'

        data = fill_string_pattern(PATTERN_GET_QUOTES, from_message_id, ",".join(map(str, sub_items)))

        buttons.append(
            InlineKeyboardButton(text_btn, callback_data=data)
        )

    buttons = split_list(buttons, columns=5)
    reply_markup = InlineKeyboardMarkup(buttons)

    reply_info(
        text,
        update, context,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
        quote=True,
        reply_markup=reply_markup,
    )


def reply_get_used_quote(user_id: int, quote_id: int, update: Update, context: CallbackContext):
    sub_query = db.Request.get_all_quote_id_by_user(user_id)
    items = [i for i, x in enumerate(sub_query) if x.quote_id == quote_id]
    if items:
        text = f'Цитата #{quote_id} найдена в {items}'
    else:
        text = f'Цитата #{quote_id} не найдена'

    reply_info(text, update, context)


@mega_process
def on_start(update: Update, context: CallbackContext) -> Optional[db.Quote]:
    # При открытии цитаты через ссылку (deep linking)
    # https://t.me/<bot_name>?start=<start_argument>
    if context.args:
        # ["400245_2046"] -> 400245, 2046
        quote_id, message_id = map(int, context.args[0].split('_'))
        quote = reply_local_quote(
            update, context,
            quote_id=quote_id,
            reply_to_message_id=message_id
        )

        # Удаление сообщения с /start при клике на id цитат в сообщении с результатом поиска
        update.effective_message.delete()

        return quote

    reply_help(update, context)


@mega_process
def on_help(update: Update, context: CallbackContext):
    """
    Получение помощи по командам:
     - /help
     - help или помощь
    """

    reply_help(update, context)


def update_cache(
        user: db.User,
        years_of_quotes: Dict[int, bool],
        log: logging.Logger,
        update: Update,
        context: CallbackContext
):
    years = [year for year, is_selected in years_of_quotes.items() if is_selected]
    log.debug(f'Start [{update_cache.__name__}], selected years: {years}')

    if 'quotes' not in context.user_data:
        context.user_data['quotes'] = []

    quotes = context.user_data['quotes']

    if years:
        log.debug(f'Quotes from year(s): {", ".join(map(str, years))}.')

    quotes += user.get_user_unique_random(years)

    log.debug(f'Finish [{update_cache.__name__}]. Quotes: {len(quotes)}')


@mega_process
def on_settings(update: Update, context: CallbackContext):
    """
    Вызов настроек:
     - /settings
     - settings или настройки
    """

    query = update.callback_query

    # Если функция вызвана из CallbackQueryHandler
    if query:
        query.answer()

    message = update.effective_message

    reply_markup = InlineKeyboardMarkup.from_column([
        InlineKeyboardButton(SettingState.YEAR.value, callback_data=SettingState.YEAR.get_callback_data()),
        InlineKeyboardButton(SettingState.LIMIT.value, callback_data=SettingState.LIMIT.get_callback_data()),
    ])

    text = 'Выбор настроек:'

    # Если функция вызвана из CallbackQueryHandler
    if query:
        message.edit_text(text, reply_markup=reply_markup)
    else:
        message.reply_text(text, reply_markup=reply_markup)


# TODO: Перенести реализацию checkbox/radio в SimplePyScripts
def _on_reply_year(log: logging.Logger, update: Update, context: CallbackContext):
    query = update.callback_query

    settings = SettingState.YEAR

    user = db.User.get_from(update.effective_user)
    years_of_quotes = user.get_years_of_quotes()

    pattern = settings.get_pattern_with_params()
    m = pattern.search(query.data)
    if m:
        year = int(m.group(1))
        if year not in years_of_quotes:
            return

        years_of_quotes[year] = not years_of_quotes[year]
        log.debug(f'    {year} = {years_of_quotes[year]}')

        # Нужно обновить кэш цитат в соответствии с выбранными годами
        log.debug('Clear cache quotes')

        if 'quotes' not in context.user_data:
            context.user_data['quotes'] = []

        quotes = context.user_data['quotes']
        quotes.clear()

        update_cache(user, years_of_quotes, log, update, context)

    # Генерация матрицы кнопок
    items = [
        InlineKeyboardButton(
            (CHECKBOX if is_selected else CHECKBOX_EMPTY) + f' {year}',
            callback_data=fill_string_pattern(pattern, year)
        )
        for year, is_selected in years_of_quotes.items()
    ]
    buttons = split_list(items, columns=4)
    buttons.append([INLINE_KEYBOARD_BUTTON_BACK])

    reply_markup = InlineKeyboardMarkup(buttons)

    # Fix error: "telegram.error.BadRequest: Message is not modified"
    if is_equal_inline_keyboards(reply_markup, query.message.reply_markup):
        return

    # Обновление базы данных должно быть в соответствии с тем, что видит пользователь
    user.set_years_of_quotes(years_of_quotes)

    text = 'Выбор года:'
    query.edit_message_text(text, reply_markup=reply_markup)


# TODO: Перенести реализацию checkbox/radio в SimplePyScripts
# TODO: Удалить, т.к. ограничения нет смысла использовать
def _on_reply_limit(log: logging.Logger, update: Update, context: CallbackContext):
    query = update.callback_query

    settings = SettingState.LIMIT
    user = db.User.get_from(update.effective_user)

    # Если значение было передано
    pattern = settings.get_pattern_with_params()
    m = pattern.search(query.data)
    if m:
        data_limit = int(m.group(1))
        if data_limit not in LIMIT_UNIQUE_QUOTES:
            return

        log.debug(f'    limit_unique_quotes = {data_limit}')

        user.set_limit_unique_quotes(data_limit)

    limit = user.get_limit_unique_quotes()

    # Генерация матрицы кнопок
    items = [
        InlineKeyboardButton(
            (RADIOBUTTON if x == limit else RADIOBUTTON_EMPTY) + f' {x}',
            callback_data=fill_string_pattern(pattern, x)
        )
        for x in LIMIT_UNIQUE_QUOTES
    ]
    buttons = split_list(items, columns=3)
    buttons.append([INLINE_KEYBOARD_BUTTON_BACK])

    reply_markup = InlineKeyboardMarkup(buttons)

    # Fix error: "telegram.error.BadRequest: Message is not modified"
    if is_equal_inline_keyboards(reply_markup, query.message.reply_markup):
        return

    text = 'Количество уникальных цитат:'
    query.edit_message_text(text, reply_markup=reply_markup)


@mega_process
def on_settings_year(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    _on_reply_year(log, update, context)


# TODO: Удалить, т.к. ограничения нет смысла использовать
@mega_process
def on_settings_limit(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    _on_reply_limit(log, update, context)


@mega_process
def on_request(update: Update, context: CallbackContext) -> Optional[db.Quote]:
    quote_obj = get_random_quote(update, context)
    if not quote_obj:
        text = 'Закончились уникальные цитаты'

        user = db.User.get_from(update.effective_user)
        if any(user.get_years_of_quotes().values()):
            text += '. Попробуйте в настройках убрать фильтрацию цитат по годам.\n/settings'

        reply_info(text, update, context)
        return

    log.debug('Quote text (%s)', quote_obj.url)

    if quote_obj.has_comics():
        reply_markup = InlineKeyboardMarkup.from_button(
            InlineKeyboardButton("Комикс", callback_data=str(quote_obj.id))
        )
    else:
        # Недостаточно при запуске отправить ReplyKeyboardMarkup, чтобы она всегда оставалась.
        # Удаление сообщения, которое принесло клавиатуру, уберет ее.
        # Поэтому при любой возможности, добавляем клавиатуру
        reply_markup = REPLY_KEYBOARD_MARKUP

    reply_quote(quote_obj, update, context, reply_markup)

    return quote_obj


@mega_process
def on_get_used_quote_in_requests(update: Update, context: CallbackContext):
    r"""
    Получение порядка вызова указанной цитаты у текущего пользователя:
     - /get_used_quote (\d+)
     - get[ _]used[ _]quote (\d+) или (\d+)
    """

    quote_id = get_quote_id(context)
    if not quote_id:
        reply_error('Номер цитаты не указан', update, context)
        return

    user_id = update.effective_user.id
    reply_get_used_quote(user_id, quote_id, update, context)


@mega_process
def on_get_used_last_quote_in_requests(update: Update, context: CallbackContext):
    r"""
    Получение порядка вызова у последней цитаты текущего пользователя:
     - /get_used_last_quote
     - get[ _]used[ _]last[ _]quote или ?
    """

    user_id = update.effective_user.id
    quote_id = db.Request.get_all_quote_id_by_user(user_id).first().quote_id

    reply_get_used_quote(user_id, quote_id, update, context)


@mega_process
def on_get_user_stats(update: Update, context: CallbackContext):
    """
    Получение статистики текущего пользователя:
     - /stats
     - stats или статистика
    """

    user = db.User.get_from(update.effective_user)

    first_request = user.requests.first()
    last_request = user.requests.order_by(db.Request.id.desc()).first()
    elapsed_days = (last_request.date_time - first_request.date_time).days

    quote_count = user.get_total_quotes()
    quote_with_comics_count = user.get_total_quotes(with_comics=True)

    text = f'''\
<b>Статистика.</b>

Получено цитат <b>{quote_count}</b>, с комиксами <b>{quote_with_comics_count}</b>
Всего запросов боту: <b>{user.requests.count()}</b>
Разница между первым и последним запросом: <b>{elapsed_days}</b> дней
    '''

    update.effective_message.reply_html(text)


@mega_process
def on_get_admin_stats(update: Update, context: CallbackContext):
    """
    Получение статистики админа:
     - /admin_stats
     - admin[ _]stats или статистика[ _]админа
    """

    quote_count = db.Quote.select().count()
    quote_with_comics_count = db.Quote.get_all_with_comics().count()

    text = f'''\
<b>Статистика админа.</b>

Пользователей: <b>{db.User.select().count()}</b>
Цитат <b>{quote_count}</b>, с комиксами <b>{quote_with_comics_count}</b>
Запросов: <b>{db.Request.select().count()}</b>

Бот запущен с <b>{START_TIME:%d/%m/%Y}</b> (прошло <b>{get_elapsed_time(START_TIME)}</b>)
С первого запроса прошло <b>{get_elapsed_time(db.Request.get_first_date_time())}</b>
    '''

    update.effective_message.reply_html(text)


@mega_process
def on_get_number_of_unique_quotes(update: Update, context: CallbackContext):
    """
    Возвращение количества оставшихся уникальных цитат:
     - /get_number_of_unique_quotes
     - ??
    """

    message = update.effective_message

    user = db.User.get_from(update.effective_user)
    years = user.get_list_years_of_quotes()

    quote_count = db.Quote.get_number_of_unique_quotes(user, years)

    lines = [
        '<b>Количество оставшихся уникальных цитат.</b>',
        '',
        f'Осталось: <b>{quote_count}</b>',
    ]
    if years:
        years_str = ", ".join(f"<b>{year}</b>" for year in years)
        lines.append(f'Фильтрация по годам: {years_str}')

    text = '\n'.join(lines).strip()
    message.reply_html(text)


@mega_process
def on_get_detail_of_unique_quotes(update: Update, context: CallbackContext):
    """
    Возвращение детального описания количества оставшихся уникальных цитат:
     - /get_detail_of_unique_quotes
     - ???
    """

    message = update.effective_message

    user = db.User.get_from(update.effective_user)

    years_of_quotes = user.get_years_of_quotes()
    total_count = 0
    rows = []
    for year in years_of_quotes:
        count = db.Quote.get_number_of_unique_quotes(user, years=[year])
        rows.append(f'    <b>{year}</b>: {count}')

        total_count += count

    lines = [
        '<b>Количество оставшихся уникальных цитат.</b>',
        '',
        f'Всего осталось <b>{total_count}</b>:'
    ]
    lines.extend(rows)

    text = '\n'.join(lines).strip()
    message.reply_html(text)


@mega_process
def on_get_quote_stats(update: Update, context: CallbackContext):
    """
    Получение статистики по цитатам:
     - /quote_stats
     - quote[ _]stats или статистика[ _]цитат
    """

    message = update.effective_message

    query = update.callback_query
    if query:
        query.answer()

    quote_count = db.Quote.select().count()
    quote_with_comics_count = db.Quote.get_all_with_comics().count()

    text_year_by_counts = "\n".join(
        f'    <b>{year}</b>: {count}'
        for year, count in db.Quote.get_year_by_counts()
    )

    text = f'''\
<b>Статистика по цитатам.</b>

Всего <b>{quote_count}</b>, с комиксами <b>{quote_with_comics_count}</b>:
{text_year_by_counts}
    '''

    reply_markup = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton('➡️ Комиксы', callback_data=fill_string_pattern(PATTERN_COMICS_STATS))
    )

    is_new = not message.edit_date
    if is_new:
        message.reply_html(
            text,
            reply_markup=reply_markup
        )
    else:
        message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )


@mega_process
def on_get_comics_stats(update: Update, context: CallbackContext):
    message = update.effective_message

    query = update.callback_query
    query.answer()

    quote_query = db.Quote.get_all_with_comics()
    quote_count = quote_query.count()

    year_by_number = {k: 0 for k in db.Quote.get_years()}
    for quote in quote_query.select(db.Quote.date):
        year = quote.date.year
        year_by_number[year] += 1

    text_year_by_counts = "\n".join(
        f'    <b>{year}</b>: {count}'
        for year, count in year_by_number.items()
    )

    text = f'''\
<b>Статистика по комиксам.</b>

Всего <b>{quote_count}</b>:
{text_year_by_counts}
    '''

    reply_markup = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton('⬅️ Назад', callback_data=PATTERN_QUERY_QUOTE_STATS)
    )

    message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


@mega_process
def on_get_users_short(update: Update, context: CallbackContext):
    r"""
    Получение пользователей (короткая):
     - /get_users_short
     - get[ _]users[ _]short
    """

    message = update.effective_message

    query = update.callback_query
    if query:
        query.answer()

    page = get_page(context)

    total_users = db.User.select().count()
    items_per_page = ITEMS_PER_PAGE
    start = ((page - 1) * items_per_page) + 1

    users = db.User.get_by_page(page=page, items_per_page=items_per_page)

    items = []
    for i, user in enumerate(users, start):
        short_title = user.get_short_title()
        short_title = f'{i}. {short_title}'
        items.append(short_title)

    text = 'Пользователи:\n' + '\n'.join(items)

    reply_text_or_edit_with_keyboard_paginator(
        message, query, text,
        page_count=(total_users // items_per_page) + 1,
        current_page=page,
        data_pattern=fill_string_pattern(PATTERN_GET_USERS_SHORT_BY_PAGE, '{page}'),
    )


@mega_process
def on_get_users(update: Update, context: CallbackContext):
    r"""
    Получение пользователей:
     - /get_users (\d+)
     - get[ _]users (\d+)
    """

    message = update.effective_message

    query = update.callback_query
    if query:
        query.answer()

    page = get_page(context)

    total_users = db.User.select().count()

    user = db.User.get_by_page(page=page, items_per_page=1)[0]
    description = get_user_message_repr(user)
    text = f'Пользователь №{page}:\n{description}'

    reply_text_or_edit_with_keyboard_paginator(
        message, query, text,
        page_count=total_users,
        current_page=page,
        data_pattern=fill_string_pattern(PATTERN_GET_USER_BY_PAGE, '{page}'),
    )


@mega_process
def on_get_quote(update: Update, context: CallbackContext) -> Optional[db.Quote]:
    """
    Получение цитаты из базы:
     - /get_quote <номер цитаты>
     - get quote <номер цитаты>
     - #<номер цитаты>
    """

    return reply_local_quote(update, context)


@mega_process
def on_get_external_quote(update: Update, context: CallbackContext):
    """
    Получение цитаты из сайта:
     - /get_external_quote <номер цитаты>
     - get external quote <номер цитаты>
    """

    quote_id = get_quote_id(context)
    if not quote_id:
        reply_error('Номер цитаты не указан', update, context)
        return

    quote_obj = bash_im.Quote.parse_from(quote_id)
    if not quote_obj:
        reply_error(f'Цитаты #{quote_id} на сайте нет', update, context)
        return

    reply_quote(quote_obj, update, context)


@mega_process
def on_update_quote(update: Update, context: CallbackContext):
    r"""
    Обновление цитаты в базе с сайта:
     - /update_quote (\d+)
     - update[ _]quote (\d+)
    """

    quote_id = get_quote_id(context)
    if not quote_id:
        reply_error('Номер цитаты не указан', update, context)
        return

    update_quote(quote_id, update, context, log)


@mega_process
def on_find_my(update: Update, context: CallbackContext):
    r"""
    Поиск цитат среди уже полученных:
     - /find_my (.+)
     - find[_ ]my (.+)
    """

    user = db.User.get_from(update.effective_user)

    value = get_context_value(context)
    items = user.find(value)
    reply_quote_ids(items, update, context)


@mega_process
def on_find(update: Update, context: CallbackContext):
    r"""
    Поиск цитат в базе:
     - /find (.+)
     - find (.+)
    """

    value = get_context_value(context)
    items = db.Quote.find(value)
    reply_quote_ids(items, update, context)


@mega_process
def on_find_new(update: Update, context: CallbackContext):
    r"""
    Поиск цитат в базе, что еще не были получены:
     - /find_new (.+)
     - find[_ ]new (.+)
    """

    user = db.User.get_from(update.effective_user)
    value = get_context_value(context)

    items_all = db.Quote.find(value)
    items_user = user.find(value)
    items = [x for x in items_all if x not in items_user]

    reply_quote_ids(items, update, context)


@mega_process
def on_cache(update: Update, context: CallbackContext):
    r"""
    Возвращение количества цитат в кэше:
     - /cache
     - cache
    """

    quotes = context.user_data.get('quotes', [])
    reply_info(
        f'Цитат в кэше пользователя: **{len(quotes)}**',
        update, context,
        parse_mode=ParseMode.MARKDOWN
    )


@mega_process
def on_get_quotes(update: Update, context: CallbackContext) -> List[db.Quote]:
    query = update.callback_query
    query.answer()

    # Example: ('2116', '391788,395909,397806,399835,404251')
    from_message_id, quote_ids = context.match.groups()
    from_message_id = int(from_message_id)

    items = []
    for quote_id in map(int, quote_ids.split(',')):
        quote = reply_local_quote(
            update, context,
            quote_id=quote_id,
            reply_to_message_id=from_message_id,
        )
        if quote:
            items.append(quote)

        time.sleep(0.05)

    # Возвращаем для учета в декораторе показанных цитат
    return items


@mega_process
def on_quote_comics(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    context.bot.send_chat_action(
        chat_id=query.message.chat_id, action=ChatAction.UPLOAD_PHOTO
    )

    quote_id = query.data
    files = list(DIR_COMICS.glob(f'quote{quote_id}_*.png'))
    max_parts = 10

    for i in range(0, len(files), max_parts):
        media = [
            InputMediaPhoto(f.open('rb')) for f in files[i: i+max_parts]
        ]
        query.message.reply_media_group(media=media, quote=True)


@catch_error(log)
def on_error(update: Update, context: CallbackContext):
    log.error('Error: %s\nUpdate: %s', context.error, update, exc_info=context.error)

    db.Error.create_from(on_error, context.error, update)

    if update:
        reply_error(ERROR_TEXT, update, context)


def setup(updater: Updater):
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', on_start))

    dp.add_handler(CommandHandler('help', on_help))
    dp.add_handler(
        MessageHandler(
            Filters.regex(r'(?i)^help$|^помощь$'),
            on_help
        )
    )
    dp.add_handler(
        CallbackQueryHandler(
            on_help, pattern=f"^{BUTTON_HELP_COMMON.callback_data}|{BUTTON_HELP_ADMIN.callback_data}$"
        )
    )

    dp.add_handler(CommandHandler('more', on_request))

    dp.add_handler(CommandHandler('settings', on_settings))
    dp.add_handler(
        MessageHandler(
            Filters.regex(r'(?i)^settings$|^настройк[иа]$'),
            on_settings
        )
    )
    dp.add_handler(
        CallbackQueryHandler(on_settings, pattern=SettingState.MAIN.get_pattern_full())
    )
    dp.add_handler(
        CallbackQueryHandler(on_settings_year, pattern=SettingState.YEAR.get_pattern_full())
    )
    # TODO: Удалить, т.к. ограничения нет смысла использовать
    dp.add_handler(
        CallbackQueryHandler(on_settings_limit, pattern=SettingState.LIMIT.get_pattern_full())
    )

    # Возвращение статистики текущего пользователя
    dp.add_handler(CommandHandler('stats', on_get_user_stats))
    dp.add_handler(
        MessageHandler(
            Filters.regex(r'(?i)^stats$|^статистика$'),
            on_get_user_stats
        )
    )

    # Возвращение статистики админа
    dp.add_handler(CommandHandler('admin_stats', on_get_admin_stats, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^admin[ _]stats$|^статистика[ _]админа$'),
            on_get_admin_stats
        )
    )

    # Возвращение количества оставшихся уникальных цитат
    dp.add_handler(CommandHandler('get_number_of_unique_quotes', on_get_number_of_unique_quotes, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'^\?\?$'),
            on_get_number_of_unique_quotes
        )
    )

    # Возвращение детального описания количества оставшихся уникальных цитат
    dp.add_handler(CommandHandler('get_detail_of_unique_quotes', on_get_detail_of_unique_quotes, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'^\?\?\?$'),
            on_get_detail_of_unique_quotes
        )
    )

    # Возвращение статистики цитат
    dp.add_handler(CommandHandler('quote_stats', on_get_quote_stats, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(PATTERN_QUOTE_STATS),
            on_get_quote_stats
        )
    )
    dp.add_handler(CallbackQueryHandler(on_get_quote_stats, pattern=PATTERN_QUOTE_STATS))
    dp.add_handler(CallbackQueryHandler(on_get_comics_stats, pattern=PATTERN_COMICS_STATS))

    # Возвращение порядка вызова указанной цитаты у текущего пользователя, сортировка от конца
    dp.add_handler(CommandHandler('get_used_quote', on_get_used_quote_in_requests, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & (Filters.regex(r'(?i)^get[ _]used[ _]quote (\d+)$') | Filters.regex(r'^(\d+)$')),
            on_get_used_quote_in_requests
        )
    )

    # Возвращение порядка вызова у последней полученный цитаты у текущего пользователя, сортировка от конца
    dp.add_handler(
        CommandHandler('get_used_last_quote', on_get_used_last_quote_in_requests, FILTER_BY_ADMIN)
    )
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^get[ _]used[ _]last[ _]quote$|^\?$'),
            on_get_used_last_quote_in_requests
        )
    )

    dp.add_handler(CommandHandler('get_users_short', on_get_users_short, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & (Filters.regex(r'(?i)^get[ _]users[ _]short$')),
            on_get_users_short
        )
    )
    dp.add_handler(CallbackQueryHandler(on_get_users_short, pattern=PATTERN_GET_USERS_SHORT_BY_PAGE))

    dp.add_handler(CommandHandler('get_users', on_get_users, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^get[ _]users$'),
            on_get_users
        )
    )
    dp.add_handler(CallbackQueryHandler(on_get_users, pattern=PATTERN_GET_USER_BY_PAGE))

    dp.add_handler(CommandHandler('get_quote', on_get_quote))
    dp.add_handler(
        MessageHandler(
            Filters.regex(r'(?i)^get[ _]quote (\d+)$') | Filters.regex(r'(?i)^#(\d+)$'),
            on_get_quote
        )
    )

    dp.add_handler(CommandHandler('get_external_quote', on_get_external_quote))
    dp.add_handler(
        MessageHandler(
            Filters.regex(r'(?i)^get[ _]external[ _]quote (\d+)$'),
            on_get_external_quote
        )
    )

    dp.add_handler(CommandHandler('update_quote', on_update_quote, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^update[ _]quote (\d+)$'),
            on_update_quote
        )
    )

    dp.add_handler(CommandHandler('find_my', on_find_my, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^find[ _]my (.+)$'),
            on_find_my
        )
    )

    dp.add_handler(CommandHandler('find_new', on_find_new, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^find[ _]new (.+)$'),
            on_find_new
        )
    )

    dp.add_handler(CommandHandler('find', on_find, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^find (.+)$'),
            on_find
        )
    )

    # Возвращение количества цитат в кэше
    dp.add_handler(CommandHandler('cache', on_cache, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^cache$'),
            on_cache
        )
    )

    dp.add_handler(CallbackQueryHandler(on_get_quotes, pattern=PATTERN_GET_QUOTES))

    dp.add_handler(MessageHandler(Filters.text, on_request))
    dp.add_handler(CallbackQueryHandler(on_quote_comics, pattern=r'^\d+$'))

    fill_commands_for_help(dp)

    dp.add_error_handler(on_error)
