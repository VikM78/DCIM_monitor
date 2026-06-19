#!/usr/bin/env python3
"""
Обёртка для запуска мониторинга с автоперезапуском при падении.

Версия: 1.0.0
Дата: 2026-06-19

Использование: python run_monitor.py
"""

import subprocess
import sys
import time
import os
import signal
from pathlib import Path

# ==================== ВЕРСИЯ ====================
VERSION = "1.0.0"
APP_NAME = "DCIM Monitor Launcher"

# Конфигурация
MONITOR_SCRIPT = Path(__file__).parent / "monitor_and_send_email" / "monitor.py"
MAX_RESTARTS = 10
RESTART_WINDOW = 60
RESTART_DELAY = 5


class MonitorLauncher:
    def __init__(self):
        self.restart_count = 0
        self.restart_times = []
        self.running = True
        
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        print(f"\n🛑 Получен сигнал {signum}, завершаем работу...")
        self.running = False
    
    def can_restart(self):
        now = time.time()
        self.restart_times = [t for t in self.restart_times if now - t < RESTART_WINDOW]
        
        if len(self.restart_times) >= MAX_RESTARTS:
            print(f"❌ Превышен лимит перезапусков ({MAX_RESTARTS} за {RESTART_WINDOW} сек)")
            return False
        
        self.restart_times.append(now)
        return True
    
    def run(self):
        print("=" * 60)
        print(f"🚀 {APP_NAME} v{VERSION}")
        print(f"   Скрипт: {MONITOR_SCRIPT}")
        print(f"   Макс. перезапусков: {MAX_RESTARTS} за {RESTART_WINDOW} сек")
        print("=" * 60)
        
        while self.running:
            try:
                process = subprocess.Popen(
                    [sys.executable, str(MONITOR_SCRIPT)],
                    cwd=MONITOR_SCRIPT.parent,
                    stdout=None,
                    stderr=None
                )
                
                print(f"📊 Мониторинг запущен (PID: {process.pid})")
                return_code = process.wait()
                
                if return_code == 0:
                    print("✅ Мониторинг завершил работу штатно")
                    break
                else:
                    print(f"⚠️ Мониторинг завершился с кодом {return_code}")
                    
                    if self.can_restart():
                        print(f"🔄 Перезапуск через {RESTART_DELAY} сек...")
                        time.sleep(RESTART_DELAY)
                    else:
                        print("❌ Лимит перезапусков превышен. Остановка.")
                        break
                        
            except KeyboardInterrupt:
                print("\n🛑 Прерывание от пользователя")
                if process:
                    process.terminate()
                    process.wait(timeout=5)
                break
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                if self.can_restart():
                    time.sleep(RESTART_DELAY)
                else:
                    break
        
        print("🏁 Мониторинг остановлен")


if __name__ == "__main__":
    launcher = MonitorLauncher()
    launcher.run()