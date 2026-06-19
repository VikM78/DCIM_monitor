#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Принудительный перезапуск мониторинга
Использование: python scripts/restart_monitor.py
"""

import subprocess
import sys
import time
import os
from pathlib import Path

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent.parent


def stop_monitor():
    """Остановка мониторинга"""
    print("🛑 Остановка мониторинга...")
    try:
        # Ищем все процессы monitor.py и run_monitor.py
        subprocess.run(['pkill', '-f', 'monitor.py'], capture_output=True)
        subprocess.run(['pkill', '-f', 'run_monitor.py'], capture_output=True)
        time.sleep(2)
        print("✅ Процессы остановлены")
        return True
    except Exception as e:
        print(f"❌ Ошибка остановки: {e}")
        return False


def start_monitor():
    """Запуск мониторинга"""
    print("🚀 Запуск мониторинга...")
    try:
        script_path = PROJECT_ROOT / "run_monitor.py"
        process = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(PROJECT_ROOT)
        )
        print(f"✅ Мониторинг запущен (PID: {process.pid})")
        return True
    except Exception as e:
        print(f"❌ Ошибка запуска: {e}")
        return False


def main():
    """Основная функция"""
    print("=" * 50)
    print("🔄 ПЕРЕЗАПУСК МОНИТОРИНГА DCIM")
    print("=" * 50)
    
    # Остановка
    if not stop_monitor():
        print("⚠️ Не удалось остановить мониторинг (возможно, уже остановлен)")
    
    # Запуск
    if start_monitor():
        print("✅ Мониторинг перезапущен успешно")
    else:
        print("❌ Ошибка перезапуска")
    
    print("=" * 50)


if __name__ == "__main__":
    main()