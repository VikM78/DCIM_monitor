#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Проверка здоровья мониторинга
Использование: python scripts/health_check.py
"""

import subprocess
import sys
import os
from pathlib import Path

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from shared.database import get_db_connection


def check_monitor_process():
    """Проверка, запущен ли процесс мониторинга"""
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'monitor.py'],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def check_database():
    """Проверка подключения к БД"""
    try:
        conn = get_db_connection(max_retries=1)
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.close()
            return True
        return False
    except Exception:
        return False


def main():
    """Основная функция"""
    print("=" * 50)
    print("🔍 HEALTH CHECK - DCIM Monitor")
    print("=" * 50)
    
    # Проверка БД
    db_ok = check_database()
    print(f"📊 База данных: {'✅ OK' if db_ok else '❌ ERROR'}")
    
    # Проверка процесса
    proc_ok = check_monitor_process()
    print(f"📊 Процесс мониторинга: {'✅ RUNNING' if proc_ok else '❌ STOPPED'}")
    
    # Если процесс остановлен и БД работает - пробуем запустить
    if not proc_ok and db_ok:
        print("\n🔄 Попытка перезапуска мониторинга...")
        try:
            script_path = PROJECT_ROOT / "run_monitor.py"
            subprocess.Popen(
                [sys.executable, str(script_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(PROJECT_ROOT)
            )
            print("✅ Команда запуска отправлена")
        except Exception as e:
            print(f"❌ Ошибка запуска: {e}")
    
    print("\n" + "=" * 50)


if __name__ == "__main__":
    main()