#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Общие функции для работы с базой данных
Используется всеми модулями проекта
"""

import psycopg2
from psycopg2 import OperationalError
import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env файл из корня проекта
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

DB_CONFIG = {
    'dbname': os.environ.get('DB_MESSAGE_NAME', 'message_db'),
    'user': os.environ.get('DB_MESSAGE_USER', 'DCIM_Archive'),
    'password': os.environ.get('DB_MESSAGE_PASSWORD', 'DCIM_Archive_pwd'),
    'host': os.environ.get('DB_MESSAGE_HOST', 'localhost'),
    'port': os.environ.get('DB_MESSAGE_PORT', '5432')
}


def get_db_connection(max_retries=3, retry_delay=1):
    """Получить соединение с БД с повторными попытками"""
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            conn.autocommit = False
            return conn
        except OperationalError as e:
            if attempt < max_retries - 1:
                import time
                time.sleep(retry_delay)
            else:
                raise e
    return None


def get_db_config():
    """Вернуть конфигурацию БД (без пароля)"""
    config = DB_CONFIG.copy()
    config['password'] = '***HIDDEN***'
    return config