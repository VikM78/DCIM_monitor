#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Конфигурация мониторинга
Вынесена из основного кода для удобства
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env файл
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

# База данных
DB_CONFIG = {
    'dbname': os.environ.get('DB_MESSAGE_NAME', 'message_db'),
    'user': os.environ.get('DB_MESSAGE_USER', 'DCIM_Archive'),
    'password': os.environ.get('DB_MESSAGE_PASSWORD', 'DCIM_Archive_pwd'),
    'host': os.environ.get('DB_MESSAGE_HOST', 'localhost'),
    'port': os.environ.get('DB_MESSAGE_PORT', '5432')
}

# Таблицы
SOURCE_TABLE = 'events_recs'
TARGET_TABLE = 'events_monitor'
SCHEDULE_TABLE = 'email_schedule'

# Настройки мониторинга
MONITOR_INTERVAL = int(os.environ.get('MONITOR_INTERVAL', 60))
MAX_FAILURES = int(os.environ.get('MAX_FAILURES', 5))
SCHEDULE_CHECK_INTERVAL = int(os.environ.get('SCHEDULE_CHECK_INTERVAL', 60))

# Настройки email
MAX_EVENTS_PER_EMAIL = 100
EMAIL_CHECK_INTERVAL = 60

# Версия
VERSION = "0.007"

# Пути
PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"