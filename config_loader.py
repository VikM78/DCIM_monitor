#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Загрузчик переменных окружения из .secrets/.env
"""

import os
from pathlib import Path
from dotenv import load_dotenv

def load_env():
    """Загружает .env из папки .secrets"""
    project_root = Path(__file__).parent
    env_path = project_root / ".secrets" / ".env"
    
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ .env загружен из: {env_path}")
        return True
    else:
        print(f"⚠️ .env не найден в {env_path}")
        print("   Создайте файл: cp .env.example .secrets/.env")
        return False

# Автоматическая загрузка при импорте
load_env()