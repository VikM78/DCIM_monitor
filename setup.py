#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Универсальный установщик автозапуска для DCIM Monitoring System
Поддерживает Windows, Linux, macOS

Использование:
    python setup.py              - интерактивное меню
    python setup.py -h           - показать эту справку
    python setup.py install      - установить автозапуск
    python setup.py status       - проверить статус автозапуска
    python setup.py remove       - удалить автозапуск

Аргументы:
    install, i    Установить автозапуск (автоопределение ОС)
    status, s     Проверить статус автозапуска
    remove, r     Удалить автозапуск
    -h, --help    Показать эту справку

Примеры:
    python setup.py              # интерактивное меню
    python setup.py install      # установить автозапуск
    python setup.py status       # проверить статус
    python setup.py remove       # удалить автозапуск
"""

import os
import sys
import subprocess
import platform
import shutil
import json
from pathlib import Path

# ==================== КОНФИГУРАЦИЯ ====================
PROJECT_ROOT = Path(__file__).parent
SERVICE_NAME = "dcim-monitor"
TASK_NAME = "DCIM_Monitor"
CONFIG_FILE = PROJECT_ROOT / ".setup_config.json"


def print_help():
    """Вывод справки"""
    print(__doc__)
    sys.exit(0)


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def print_header():
    """Вывод заголовка"""
    print("=" * 60)
    print("🔧 УНИВЕРСАЛЬНЫЙ УСТАНОВЩИК АВТОЗАПУСКА")
    print("=" * 60)


def detect_os():
    """Определение ОС"""
    system = platform.system()
    if system == "Windows":
        return "windows"
    elif system == "Linux":
        return "linux"
    elif system == "Darwin":
        return "macos"
    else:
        return "unknown"


def get_python_path():
    """Получить путь к Python"""
    python_path = shutil.which("python")
    if not python_path:
        python_path = shutil.which("python3")
    return python_path


def is_admin():
    """Проверка прав администратора (Windows)"""
    if platform.system() != "Windows":
        return os.geteuid() == 0
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False


def request_admin_privileges():
    """Запрос прав администратора (Windows)"""
    if platform.system() != "Windows":
        return False
    
    if is_admin():
        return True
    
    try:
        import ctypes
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        return True
    except:
        return False


def save_config(data):
    """Сохранить конфигурацию"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def load_config():
    """Загрузить конфигурацию"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}


# ==================== УСТАНОВКА ДЛЯ РАЗНЫХ ОС ====================

def setup_windows():
    """Установка для Windows (Task Scheduler)"""
    print("\n🪟 Установка автозапуска для Windows...")
    
    if not is_admin():
        print("⚠️ Требуются права администратора!")
        print("🔄 Запрос прав...")
        if request_admin_privileges():
            print("✅ Права получены. Перезапустите установку.")
        else:
            print("❌ Отказ в правах администратора.")
        return
    
    python_path = get_python_path()
    if not python_path:
        print("❌ Python не найден!")
        return
    
    script_path = PROJECT_ROOT / "run_monitor.py"
    log_path = PROJECT_ROOT / "logs"
    
    log_path.mkdir(exist_ok=True)
    
    ps_script = f"""
$TaskName = "{TASK_NAME}"
$PythonPath = "{python_path}"
$ScriptPath = "{script_path}"
$LogPath = "{log_path}"

$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument $ScriptPath -WorkingDirectory "{PROJECT_ROOT}"
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 999
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

try {{
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "DCIM Monitor Service - автоматический мониторинг и рассылка email"
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "✅ Задача '$TaskName' создана и запущена"
    Write-Host "📁 Логи: $LogPath"
}} catch {{
    Write-Host "❌ Ошибка: $_"
    exit 1
}}
"""
    
    ps_file = PROJECT_ROOT / "setup_temp.ps1"
    with open(ps_file, 'w', encoding='utf-8') as f:
        f.write(ps_script)
    
    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps_file)],
        capture_output=True,
        text=True
    )
    
    ps_file.unlink()
    
    if result.returncode == 0:
        print("✅ Автозапуск успешно установлен")
        save_config({"task_name": TASK_NAME, "os": "windows"})
    else:
        print("❌ Ошибка установки:")
        print(result.stderr)


def setup_linux():
    """Установка для Linux (systemd)"""
    print("\n🐧 Установка автозапуска для Linux...")
    
    if not shutil.which("systemctl"):
        print("❌ systemd не найден. Установите systemd.")
        return
    
    if os.geteuid() != 0:
        print("⚠️ Требуются права root!")
        print("   Запустите: sudo python setup.py")
        return
    
    python_path = get_python_path()
    if not python_path:
        print("❌ Python не найден!")
        return
    
    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
    
    service_content = f"""[Unit]
Description=DCIM Monitor Service
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User={os.getlogin()}
WorkingDirectory={PROJECT_ROOT}
Environment="PATH=/usr/bin:/usr/local/bin"
ExecStart={python_path} {PROJECT_ROOT}/run_monitor.py
Restart=always
RestartSec=10
StandardOutput=append:{PROJECT_ROOT}/logs/monitor_stdout.log
StandardError=append:{PROJECT_ROOT}/logs/monitor_stderr.log
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
"""
    
    service_path = Path(f"/etc/systemd/system/{SERVICE_NAME}.service")
    
    with open(service_path, 'w') as f:
        f.write(service_content)
    
    print(f"✅ Создан service файл: {service_path}")
    
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    print("✅ systemd перезагружен")
    
    subprocess.run(["systemctl", "enable", SERVICE_NAME], check=True)
    print(f"✅ {SERVICE_NAME} включён в автозагрузку")
    
    subprocess.run(["systemctl", "start", SERVICE_NAME], check=True)
    print(f"✅ {SERVICE_NAME} запущен")
    
    save_config({"service_name": SERVICE_NAME, "os": "linux"})


def setup_macos():
    """Установка для macOS (launchd)"""
    print("\n🍎 Установка автозапуска для macOS...")
    
    if not shutil.which("launchctl"):
        print("❌ launchctl не найден")
        return
    
    python_path = get_python_path()
    if not python_path:
        print("❌ Python не найден!")
        return
    
    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
    
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{SERVICE_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{PROJECT_ROOT}/run_monitor.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{PROJECT_ROOT}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{PROJECT_ROOT}/logs/monitor_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{PROJECT_ROOT}/logs/monitor_stderr.log</string>
</dict>
</plist>
"""
    
    plist_path = Path(f"/Users/{os.getlogin()}/Library/LaunchAgents/{SERVICE_NAME}.plist")
    
    with open(plist_path, 'w') as f:
        f.write(plist_content)
    
    print(f"✅ Создан plist: {plist_path}")
    
    subprocess.run(["launchctl", "load", "-w", str(plist_path)], check=True)
    print(f"✅ {SERVICE_NAME} загружен")
    
    subprocess.run(["launchctl", "start", SERVICE_NAME], check=True)
    print(f"✅ {SERVICE_NAME} запущен")
    
    save_config({"service_name": SERVICE_NAME, "os": "macos"})


def setup_auto():
    """Автоопределение ОС и установка"""
    os_type = detect_os()
    
    if os_type == "windows":
        setup_windows()
    elif os_type == "linux":
        setup_linux()
    elif os_type == "macos":
        setup_macos()
    else:
        print(f"❌ Неподдерживаемая ОС: {os_type}")


# ==================== СТАТУС ====================

def show_status():
    """Показать статус автозапуска"""
    os_type = detect_os()
    config = load_config()
    
    print("\n📊 СТАТУС АВТОЗАПУСКА")
    print("=" * 40)
    print(f"📌 ОС: {os_type.upper()}")
    print(f"📁 Проект: {PROJECT_ROOT}")
    
    if os_type == "windows":
        result = subprocess.run(
            ["powershell", "-Command", 
             f"$t=Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
             f"if($t){{$t.State}}else{{'NotFound'}}"],
            capture_output=True,
            text=True
        )
        status = result.stdout.strip()
        
        if status and status != "NotFound":
            print(f"✅ Задача {TASK_NAME}: активна")
            print(f"   Статус: {status}")
            print("   🔧 Управление: taskschd.msc")
        else:
            print(f"❌ Задача {TASK_NAME}: не установлена")
    
    elif os_type == "linux":
        result = subprocess.run(
            ["systemctl", "is-active", SERVICE_NAME],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"✅ Сервис {SERVICE_NAME}: активен")
        else:
            print(f"❌ Сервис {SERVICE_NAME}: не установлен или неактивен")
            print("   🔧 Управление: systemctl")
    
    elif os_type == "macos":
        plist_path = Path(f"/Users/{os.getlogin()}/Library/LaunchAgents/{SERVICE_NAME}.plist")
        if plist_path.exists():
            print(f"✅ {SERVICE_NAME}: установлен")
        else:
            print(f"❌ {SERVICE_NAME}: не установлен")
            print("   🔧 Управление: launchctl")
    
    print("=" * 40)


# ==================== УДАЛЕНИЕ ====================

def remove_windows():
    """Удаление для Windows"""
    print("\n🗑️ Удаление автозапуска для Windows...")
    
    if not is_admin():
        print("⚠️ Требуются права администратора!")
        if request_admin_privileges():
            print("✅ Права получены. Перезапустите удаление.")
        else:
            print("❌ Отказ в правах администратора.")
        return
    
    result = subprocess.run(
        ["powershell", "-Command", 
         f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue"],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print(f"✅ Задача {TASK_NAME} удалена")
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
    else:
        print(f"⚠️ Задача {TASK_NAME} не найдена или уже удалена")


def remove_linux():
    """Удаление для Linux"""
    print("\n🗑️ Удаление автозапуска для Linux...")
    
    if os.geteuid() != 0:
        print("⚠️ Требуются права root!")
        print("   Запустите: sudo python setup.py remove")
        return
    
    subprocess.run(["systemctl", "stop", SERVICE_NAME], capture_output=True)
    subprocess.run(["systemctl", "disable", SERVICE_NAME], capture_output=True)
    
    service_path = Path(f"/etc/systemd/system/{SERVICE_NAME}.service")
    if service_path.exists():
        service_path.unlink()
        print(f"✅ Удалён {service_path}")
    
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
    print("✅ systemd перезагружен")
    
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()


def remove_macos():
    """Удаление для macOS"""
    print("\n🗑️ Удаление автозапуска для macOS...")
    
    plist_path = Path(f"/Users/{os.getlogin()}/Library/LaunchAgents/{SERVICE_NAME}.plist")
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", "-w", str(plist_path)], capture_output=True)
        plist_path.unlink()
        print(f"✅ Удалён {plist_path}")
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
    else:
        print(f"⚠️ {SERVICE_NAME} не установлен")


def remove_auto():
    """Автоудаление в зависимости от ОС"""
    os_type = detect_os()
    
    if os_type == "windows":
        remove_windows()
    elif os_type == "linux":
        remove_linux()
    elif os_type == "macos":
        remove_macos()
    else:
        print(f"❌ Неподдерживаемая ОС: {os_type}")


# ==================== ОСНОВНАЯ ФУНКЦИЯ ====================

def main():
    """Основная функция"""
    # Обработка -h и --help
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print_help()
    
    print_header()
    
    os_type = detect_os()
    print(f"\n📌 Обнаружена ОС: {os_type.upper()}")
    print(f"   {platform.platform()}")
    
    # Обработка аргументов командной строки
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command in ['status', 's']:
            show_status()
        elif command in ['remove', 'uninstall', 'r']:
            remove_auto()
        elif command in ['install', 'i']:
            setup_auto()
        else:
            print(f"❌ Неизвестная команда: {command}")
            print("   Доступные: install, status, remove, -h")
        return
    
    # Интерактивное меню
    print("\n📋 Выберите действие:")
    print(f"   1. 📥 Установить автозапуск (для {os_type.upper()})")
    print("   2. 📊 Проверить статус")
    print("   3. 🗑️  Удалить автозапуск")
    print("   0. ❌ Выход")
    
    choice = input("\n👉 Введите номер: ").strip()
    
    if choice == "0":
        print("👋 До свидания!")
    elif choice == "1":
        setup_auto()
        input("\nНажмите Enter для продолжения...")
    elif choice == "2":
        show_status()
        input("\nНажмите Enter для продолжения...")
    elif choice == "3":
        if input("Вы уверены? (y/n): ").lower() in ['y', 'yes', 'да']:
            remove_auto()
        else:
            print("Отмена")
        input("\nНажмите Enter для продолжения...")
    else:
        print("❌ Неверный выбор")


if __name__ == "__main__":
    main()