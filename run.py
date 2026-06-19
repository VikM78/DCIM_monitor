#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Универсальный запускатор DCIM Monitoring System

Версия: 2.1.0
Дата: 2026-06-19

Использование:
    python run.py                    - интерактивное меню
    python run.py -h                 - показать эту справку
    python run.py -m                 - запустить мониторинг
    python run.py -e                 - запустить веб-интерфейс (email_manager)
    python run.py -s                 - запустить планировщик (schedule)
    python run.py -a                 - запустить всё (мониторинг + веб)
    python run.py -m -e              - запустить мониторинг и веб
    python run.py -m -s -e           - запустить всё
    python run.py --status           - проверить статус
    python run.py --stop             - остановить всё
    python run.py -m --stop          - остановить только мониторинг
    python run.py -e --stop          - остановить только веб
    python run.py -v                 - показать версию

Аргументы:
    -m, --monitor    Запустить/остановить мониторинг
    -e, --web        Запустить/остановить веб-интерфейс
    -s, --schedule   Запустить/остановить планировщик
    -a, --all        Запустить всё (мониторинг + веб)
    --status         Показать статус всех компонентов
    --stop           Остановить указанные компоненты (или все)
    -v, --version    Показать версию
    -h, --help       Показать эту справку

Примеры:
    python run.py -m                # запустить мониторинг
    python run.py -e                # запустить веб-интерфейс
    python run.py -a                # запустить всё
    python run.py --status          # проверить статус
    python run.py --stop            # остановить всё
    python run.py -m --stop         # остановить только мониторинг
"""

import os
import sys
import subprocess
import platform
import time
import psutil
from pathlib import Path

# ==================== ВЕРСИЯ ====================
VERSION = "2.1.0"
APP_NAME = "DCIM Monitoring System"


# ==================== КОНФИГУРАЦИЯ ====================
PROJECT_ROOT = Path(__file__).parent
EMAIL_MANAGER_DIR = PROJECT_ROOT / "email_manager"
MONITOR_DIR = PROJECT_ROOT / "monitor_and_send_email"
SCHEDULE_DIR = PROJECT_ROOT / "schedule_email"

# Файлы для запуска
WEB_SCRIPT = EMAIL_MANAGER_DIR / "app.py"
MONITOR_WRAPPER = PROJECT_ROOT / "run_monitor.py"
SCHEDULE_SCRIPT = SCHEDULE_DIR / "schedule_manager.py"


def print_version():
    """Вывод версии"""
    print(f"{APP_NAME} v{VERSION}")
    sys.exit(0)


def print_help():
    """Вывод справки"""
    print(__doc__)
    sys.exit(0)


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def print_header():
    """Вывод заголовка"""
    print("=" * 60)
    print(f"🚀 {APP_NAME} v{VERSION}")
    print(f"   Проект: {PROJECT_ROOT}")
    print("=" * 60)


def is_process_running(script_name):
    """
    Проверка, запущен ли процесс по имени скрипта
    Использует psutil для точного определения
    """
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline:
                cmdline_str = ' '.join(cmdline)
                if script_name in cmdline_str:
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def get_pids(script_name):
    """Получить список PID для процесса"""
    pids = []
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline:
                cmdline_str = ' '.join(cmdline)
                if script_name in cmdline_str:
                    pids.append(proc.info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def kill_process(script_name):
    """Остановка процесса по имени скрипта"""
    pids = get_pids(script_name)
    if not pids:
        return
    
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            time.sleep(1)
            if proc.is_running():
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def run_component(script_path, name, args=None):
    """Запуск компонента в новом окне"""
    if not script_path.exists():
        print(f"❌ Файл не найден: {script_path}")
        return None
    
    if is_process_running(script_path.name):
        print(f"⚠️ {name} уже запущен")
        return None
    
    print(f"🚀 Запуск {name}...")
    
    if platform.system() == "Windows":
        subprocess.Popen(
            f'start "DCIM - {name}" python "{script_path}"',
            shell=True,
            cwd=str(script_path.parent)
        )
    else:
        subprocess.Popen(
            ["python3", str(script_path)] + (args or []),
            cwd=str(script_path.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    
    time.sleep(2)
    if is_process_running(script_path.name):
        print(f"✅ {name} запущен")
        return True
    else:
        print(f"⚠️ {name} не удалось запустить")
        return None


def run_monitor():
    """Запуск мониторинга (через run_monitor.py)"""
    return run_component(MONITOR_WRAPPER, "Мониторинг")


def run_web():
    """Запуск веб-интерфейса"""
    return run_component(WEB_SCRIPT, "Веб-интерфейс (http://localhost:5000)")


def run_schedule():
    """Запуск планировщика"""
    return run_component(SCHEDULE_SCRIPT, "Планировщик")


def show_status():
    """Показать статус всех компонентов"""
    print("\n📊 СТАТУС КОМПОНЕНТОВ")
    print("=" * 40)
    
    components = [
        ("Мониторинг", "run_monitor.py"),
        ("Веб-интерфейс", "app.py"),
        ("Планировщик", "schedule_manager.py"),
    ]
    
    for name, script in components:
        if is_process_running(script):
            pids = get_pids(script)
            print(f"✅ {name}: работает (PID: {', '.join(map(str, pids))})")
        else:
            print(f"❌ {name}: остановлен")
    
    print("=" * 40)


def stop_component(process_name, display_name):
    """Остановка компонента"""
    print(f"⏹️ Остановка {display_name}...")
    
    pids = get_pids(process_name)
    if not pids:
        print(f"⚠️ {display_name} не запущен")
        return
    
    kill_process(process_name)
    time.sleep(1)
    
    if is_process_running(process_name):
        print(f"⚠️ {display_name} не удалось остановить")
        print(f"   Попробуйте вручную закрыть окно")
    else:
        print(f"✅ {display_name} остановлен")


def stop_all():
    """Остановка всех компонентов"""
    print("\n⏹️ ОСТАНОВКА ВСЕХ КОМПОНЕНТОВ")
    print("=" * 40)
    
    stop_component("run_monitor.py", "Мониторинг")
    stop_component("app.py", "Веб-интерфейс")
    stop_component("schedule_manager.py", "Планировщик")
    
    print("=" * 40)


def print_menu():
    """Вывод меню"""
    print(f"\n📋 {APP_NAME} v{VERSION}")
    print("=" * 40)
    print("   1. 📊 Запустить мониторинг")
    print("   2. 🌐 Запустить веб-интерфейс (email_manager)")
    print("   3. 🗓️  Запустить планировщик (schedule)")
    print("   4. 🚀 Запустить всё (мониторинг + веб)")
    print("   5. 🔍 Проверить статус")
    print("   6. ⏹️  Остановить всё")
    print("   0. ❌ Выход")
    print("=" * 40)


def parse_arguments():
    """Разбор аргументов командной строки"""
    if len(sys.argv) < 2:
        return None
    
    args = sys.argv[1:]
    result = {"components": [], "stop": False, "status": False}
    
    for arg in args:
        if arg in ["-h", "--help"]:
            print_help()
        elif arg in ["-v", "--version"]:
            print_version()
        elif arg in ["-m", "--monitor"]:
            result["components"].append("monitor")
        elif arg in ["-e", "--web"]:
            result["components"].append("web")
        elif arg in ["-s", "--schedule"]:
            result["components"].append("schedule")
        elif arg in ["-a", "--all"]:
            result["components"] = ["monitor", "web"]
        elif arg == "--stop":
            result["stop"] = True
        elif arg == "--status":
            result["status"] = True
        else:
            print(f"❌ Неизвестный аргумент: {arg}")
            print_help()
            return None
    
    return result


# ==================== ОСНОВНАЯ ФУНКЦИЯ ====================

def main():
    """Основная функция"""
    args = parse_arguments()
    
    if args is not None:
        if args["status"]:
            show_status()
            return
        
        if args["stop"]:
            if not args["components"]:
                stop_all()
            else:
                print("\n⏹️ ОСТАНОВКА КОМПОНЕНТОВ")
                print("=" * 40)
                for comp in args["components"]:
                    if comp == "monitor":
                        stop_component("run_monitor.py", "Мониторинг")
                    elif comp == "web":
                        stop_component("app.py", "Веб-интерфейс")
                    elif comp == "schedule":
                        stop_component("schedule_manager.py", "Планировщик")
                print("=" * 40)
            return
        
        if not args["components"]:
            print("⚠️ Не указаны компоненты для запуска")
            print("   Используйте: python run.py -m (мониторинг)")
            print("   или: python run.py -e (веб)")
            print("   или: python run.py -s (планировщик)")
            print("   или: python run.py -a (всё)")
            print("   или: python run.py -h (справка)")
            return
        
        print_header()
        print("\n🚀 ЗАПУСК КОМПОНЕНТОВ")
        print("=" * 40)
        
        for comp in args["components"]:
            if comp == "monitor":
                run_monitor()
            elif comp == "web":
                run_web()
            elif comp == "schedule":
                run_schedule()
        
        print("=" * 40)
        return
    
    # Интерактивное меню
    print_header()
    
    while True:
        print_menu()
        choice = input("\n👉 Введите номер: ").strip()
        
        if choice == "0":
            print("\n👋 До свидания!")
            break
        elif choice == "1":
            run_monitor()
        elif choice == "2":
            run_web()
        elif choice == "3":
            run_schedule()
        elif choice == "4":
            print("\n🚀 Запуск всех компонентов...")
            run_monitor()
            run_web()
            print("✅ Все компоненты запущены!")
        elif choice == "5":
            show_status()
        elif choice == "6":
            stop_all()
        else:
            print("❌ Неверный выбор")
        
        input("\nНажмите Enter для продолжения...")
        print_header()


if __name__ == "__main__":
    main()