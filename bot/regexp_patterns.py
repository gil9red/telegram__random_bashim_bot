#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import re


PATTERN_QUOTE_STATS = re.compile(r'(?i)^quote[ _]stats$|^статистика[ _]цитат$')
PATTERN_QUERY_QUOTE_STATS = re.compile(f'^quote_stats$')
PATTERN_COMICS_STATS = re.compile(f'^comics_stats$')

PATTERN_GET_QUOTES = re.compile(r'^get_(\d+)_([\d,]+)$')

PATTERN_GET_BY_DATE = re.compile(r'^\d{2}\.\d{2}\.\d{4}$')
PATTERN_PAGE_GET_BY_DATE = re.compile(r'^get_page#(\d+)_by_date=(.+)$')

PATTERN_HELP_COMMON = re.compile(r'^help_common_by_page_(\d+)$')
PATTERN_HELP_ADMIN = re.compile(r'^help_admin_by_page_(\d+)$')

PATTERN_GET_USERS_SHORT_BY_PAGE = re.compile(r'^get_users_short_by_page_(\d+)$')
PATTERN_GET_USER_BY_PAGE = re.compile(r'^get_user_by_page_(\d+)$')

PATTERN_GET_GROUP_CHATS_SHORT_BY_PAGE = re.compile(r'^get_group_chats_short_by_page_(\d+)$')

PATTERN_GET_ERRORS_SHORT_BY_PAGE = re.compile(r'^get_errors_short_by_page_(\d+)$')


# SOURCE: https://github.com/gil9red/telegram_bot__gamebook/blob/7b7399c83ae6249da9dc92ea5dc475cc0565edc0/bot/regexp.py#L22
def fill_string_pattern(pattern: re.Pattern, *args) -> str:
    pattern = pattern.pattern
    pattern = pattern.strip('^$')
    return re.sub(r'\(.+?\)', '{}', pattern).format(*args)


if __name__ == '__main__':
    assert fill_string_pattern(PATTERN_COMICS_STATS) == 'comics_stats'
    assert fill_string_pattern(PATTERN_GET_QUOTES, 1, 2) == 'get_1_2'
