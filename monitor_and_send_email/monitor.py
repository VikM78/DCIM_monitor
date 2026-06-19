#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Единая программа мониторинга сообщений и отправки email уведомлений
Отслеживает события в таблице events_recs и отправляет email уведомления

Версия: 0.009
Дата: 2026-06-17

История изменений:
------------------
v0.009 (2026-06-17):
- Добавлено отображение времени подтверждения (acked_time)
- Добавлено отображение комментариев в активных авариях
- Убран лимит обрезания сообщений (полный текст)
- Улучшено форматирование письма

v0.008 (2026-06-17):
- Исправлена ошибка чтения полей из events_monitor (update_type → last_update_type)
- Добавлен метод refresh_columns() для обновления списка колонок
- Добавлена диагностика в get_active_events()
"""

import psycopg2
import smtplib
import time
import sys
import signal
import logging
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta, time as dt_time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional, Tuple

# ==================== ГЛОБАЛЬНЫЙ ФЛАГ ДЛЯ GRACEFUL SHUTDOWN ====================
running = True

def signal_handler(signum, frame):
    """Обработка сигналов для корректного завершения"""
    global running
    print(f"\n🛑 Получен сигнал {signum}, завершаем работу...")
    running = False

# Регистрация обработчиков сигналов
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ==================== КОНФИГУРАЦИЯ ====================
from config import (
    DB_CONFIG, SOURCE_TABLE, TARGET_TABLE, SCHEDULE_TABLE,
    MONITOR_INTERVAL, MAX_FAILURES, SCHEDULE_CHECK_INTERVAL,
    MAX_EVENTS_PER_EMAIL, VERSION
)


# Часовой пояс UTC+3
UTC_PLUS_3 = timezone(timedelta(hours=3))

# Эпоха для FILETIME (1 января 1601 года в UTC)
FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

# Битовые маски для msg_sended (email) и msg_view (консоль)
MSG_APPEARED = 0x001
MSG_ACKED = 0x010
MSG_DISAPPEARED = 0x100

# Константы для update_type
UPDATE_TYPE_APPEAR = 1
UPDATE_TYPE_DISAPPEAR = 2
UPDATE_TYPE_ACK = 3


# ==================== ЛОГИРОВАНИЕ ====================

def setup_logging() -> logging.Logger:
    current_date = datetime.now().strftime('%Y-%m-%d')
    log_dir = Path(f"./logs/{current_date}")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    current_time = datetime.now().strftime('%H-%M-%S')
    log_filename = f"monitor_{current_time}.log"
    log_filepath = log_dir / log_filename
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filepath, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def filetime_to_datetime(filetime_value):
    if filetime_value is None or filetime_value == 0:
        return None
    seconds = filetime_value / 10000000.0
    utc_dt = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    local_dt = utc_dt.astimezone(UTC_PLUS_3)
    return local_dt


def format_datetime(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_update_type_text(update_type: int) -> Tuple[str, str, str]:
    if update_type == UPDATE_TYPE_APPEAR:
        return ("ПОЯВЛЕНИЕ АВАРИИ", "appearance", "🟡")
    elif update_type == UPDATE_TYPE_DISAPPEAR:
        return ("ИСЧЕЗНОВЕНИЕ АВАРИИ", "disappearance", "🟢")
    elif update_type == UPDATE_TYPE_ACK:
        return ("ПОДТВЕРЖДЕНИЕ АВАРИИ", "ack", "🔵")
    else:
        return ("НЕИЗВЕСТНОЕ СОБЫТИЕ", "unknown", "❓")


def get_severity_text(severity: int) -> Tuple[str, str]:
    if severity >= 800:
        return ("КРИТИЧЕСКИЙ", "critical")
    elif severity >= 600:
        return ("ВЫСОКИЙ", "high")
    elif severity >= 400:
        return ("СРЕДНИЙ", "medium")
    elif severity >= 200:
        return ("НИЗКИЙ", "low")
    else:
        return ("ИНФО", "info")


def calculate_msg_status(current_status, update_type):
    new_status = current_status
    if update_type == UPDATE_TYPE_APPEAR:
        new_status |= MSG_APPEARED
    elif update_type == UPDATE_TYPE_ACK:
        new_status |= MSG_ACKED
    elif update_type == UPDATE_TYPE_DISAPPEAR:
        new_status |= MSG_DISAPPEARED
    return new_status


def should_display_message(update_type, msg_view):
    if update_type == UPDATE_TYPE_APPEAR:
        return not (msg_view & MSG_APPEARED)
    elif update_type == UPDATE_TYPE_ACK:
        return not (msg_view & MSG_ACKED)
    elif update_type == UPDATE_TYPE_DISAPPEAR:
        return not (msg_view & MSG_DISAPPEARED)
    return False


def should_send_email(update_type, msg_sended):
    if update_type == UPDATE_TYPE_APPEAR:
        return not (msg_sended & MSG_APPEARED)
    elif update_type == UPDATE_TYPE_ACK:
        return not (msg_sended & MSG_ACKED)
    elif update_type == UPDATE_TYPE_DISAPPEAR:
        return not (msg_sended & MSG_DISAPPEARED)
    return False


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} сек"
    elif seconds < 3600:
        return f"{seconds / 60:.0f} мин"
    elif seconds < 86400:
        return f"{seconds / 3600:.1f} ч"
    else:
        return f"{seconds / 86400:.1f} дн"


def check_schedule_time(schedule_time: dt_time, days_of_week: List[int], last_sent: datetime) -> bool:
    now = datetime.now()
    current_weekday = now.isoweekday()
    
    if days_of_week and current_weekday not in days_of_week:
        return False
    
    schedule_datetime = datetime.combine(now.date(), schedule_time)
    time_diff = abs((now - schedule_datetime).total_seconds())
    
    if last_sent and last_sent.date() == now.date():
        return False
    
    return time_diff <= 300


def check_interval_schedule(interval_minutes: int, last_sent: datetime) -> bool:
    if not last_sent:
        return True
    time_since_last = (datetime.now() - last_sent).total_seconds() / 60
    return time_since_last >= interval_minutes


# ==================== РАБОТА С БАЗОЙ ДАННЫХ ====================

class DatabaseManager:
    def __init__(self):
        self.conn = None
        self.events_columns = []
        
    def connect(self) -> bool:
        try:
            self.conn = psycopg2.connect(**DB_CONFIG)
            self.conn.autocommit = False
            logger.info(f"Успешно подключено к БД {DB_CONFIG['dbname']}")
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных: {e}")
            return False
    
    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("Соединение с БД закрыто")
    
    def refresh_columns(self):
        """Принудительное обновление списка колонок таблицы events_monitor"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(f"""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = '{TARGET_TABLE}' 
                    ORDER BY ordinal_position
                """)
                self.events_columns = [row[0] for row in cur.fetchall()]
                logger.info(f"✅ Обновлены колонки ({len(self.events_columns)}): {self.events_columns}")
                return self.events_columns
        except Exception as e:
            logger.error(f"❌ Ошибка обновления колонок: {e}")
            return []
    
    def ensure_columns_exist(self):
        """Проверка и создание необходимых колонок"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = '{TARGET_TABLE}'
                    )
                """)
                table_exists = cur.fetchone()[0]
                
                if not table_exists:
                    return
                
                # Проверяем колонку msg_view
                cur.execute(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = '{TARGET_TABLE}' AND column_name = 'msg_view'
                    )
                """)
                if not cur.fetchone()[0]:
                    cur.execute(f"ALTER TABLE {TARGET_TABLE} ADD COLUMN msg_view INTEGER DEFAULT 0")
                    logger.info("✓ Добавлена колонка msg_view")
                
                # Проверяем колонку last_email_sent
                cur.execute(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = '{TARGET_TABLE}' AND column_name = 'last_email_sent'
                    )
                """)
                if not cur.fetchone()[0]:
                    cur.execute(f"ALTER TABLE {TARGET_TABLE} ADD COLUMN last_email_sent TIMESTAMP")
                    logger.info("✓ Добавлена колонка last_email_sent")
                
                # Проверяем колонку comments
                cur.execute(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = '{TARGET_TABLE}' AND column_name = 'comments'
                    )
                """)
                if not cur.fetchone()[0]:
                    cur.execute(f"ALTER TABLE {TARGET_TABLE} ADD COLUMN comments TEXT DEFAULT ''")
                    logger.info("✓ Добавлена колонка comments")
                
                self.conn.commit()
                self.refresh_columns()
        except Exception as e:
            logger.error(f"Ошибка при проверке колонок: {e}")
            self.conn.rollback()
    
    def check_source_table_structure(self) -> bool:
        try:
            self.conn.rollback()
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = %s
                    )
                """, (SOURCE_TABLE,))
                table_exists = cur.fetchone()[0]
                
                if not table_exists:
                    logger.error(f"Таблица {SOURCE_TABLE} не существует")
                    return False
                
                required_columns = ['id', 'alarm_id', 'severity', 'active', 'acked', 
                                   'active_time', 'in_active_time', 'acked_time', 
                                   'message', 'update_type']
                
                for col in required_columns:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns 
                            WHERE table_name = %s AND column_name = %s
                        )
                    """, (SOURCE_TABLE, col))
                    if not cur.fetchone()[0]:
                        logger.error(f"Поле {col} отсутствует")
                        return False
                
                logger.info(f"✓ Таблица {SOURCE_TABLE} успешно проверена")
                self.conn.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка при проверке: {e}")
            self.conn.rollback()
            return False
    
    def check_target_table(self) -> bool:
        try:
            self.conn.rollback()
            with self.conn.cursor() as cur:
                cur.execute(f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '{TARGET_TABLE}')")
                return cur.fetchone()[0]
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return False
    
    def create_monitor_table(self) -> bool:
        try:
            self.conn.rollback()
            with self.conn.cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS {TARGET_TABLE} CASCADE")
                cur.execute(f"""
                    CREATE TABLE {TARGET_TABLE} (
                        alarm_id INTEGER PRIMARY KEY,
                        severity INTEGER,
                        active INTEGER,
                        acked INTEGER,
                        active_time BIGINT,
                        in_active_time BIGINT,
                        acked_time BIGINT,
                        message TEXT,
                        comments TEXT DEFAULT '',
                        msg_sended INTEGER DEFAULT 0,
                        msg_view INTEGER DEFAULT 0,
                        last_id INTEGER,
                        last_update_type INTEGER,
                        first_seen TIMESTAMP,
                        last_updated TIMESTAMP,
                        last_displayed TIMESTAMP,
                        last_email_sent TIMESTAMP
                    )
                """)
                self.conn.commit()
                self.refresh_columns()
                logger.info(f"✓ Таблица {TARGET_TABLE} успешно создана")
                return True
        except Exception as e:
            logger.error(f"Ошибка при создании: {e}")
            self.conn.rollback()
            return False
    
    def insert_initial_data(self) -> int:
        try:
            with self.conn.cursor() as cur:
                query = f"""
                    INSERT INTO {TARGET_TABLE} (alarm_id, severity, active, acked, 
                                               active_time, in_active_time, acked_time, 
                                               message, comments, msg_sended, msg_view, 
                                               last_id, last_update_type, first_seen, last_updated)
                    SELECT DISTINCT ON (alarm_id)
                        alarm_id, severity, active, acked, active_time,
                        CASE WHEN in_active_time >= active_time THEN in_active_time ELSE 0 END,
                        CASE WHEN acked_time >= active_time THEN acked_time ELSE 0 END,
                        message, '', 0, 0, id, update_type,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    FROM {SOURCE_TABLE}
                    WHERE severity >= 750 AND active = 1 AND update_type = 1
                    ORDER BY alarm_id, id DESC
                """
                cur.execute(query)
                self.conn.commit()
                
                cur.execute(f"SELECT COUNT(*) FROM {TARGET_TABLE}")
                count = cur.fetchone()[0]
                logger.info(f"Добавлено {count} записей")
                return count
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            self.conn.rollback()
            return 0
    
    def update_comments(self, alarm_id: int, comment: str):
        """Обновление комментария для аварии"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {TARGET_TABLE} 
                    SET comments = CASE 
                        WHEN comments = '' THEN %s
                        ELSE comments || E'\n' || %s
                    END
                    WHERE alarm_id = %s
                """, (comment, comment, alarm_id))
                self.conn.commit()
                logger.debug(f"Добавлен комментарий для alarm_id={alarm_id}: {comment}")
        except Exception as e:
            logger.error(f"Ошибка обновления комментария: {e}")
            self.conn.rollback()
    
    def clear_comments(self, alarm_id: int):
        """Очистка комментариев при повторном появлении аварии"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(f"UPDATE {TARGET_TABLE} SET comments = '' WHERE alarm_id = %s", (alarm_id,))
                self.conn.commit()
                logger.info(f"Очищены комментарии для alarm_id={alarm_id}")
        except Exception as e:
            logger.error(f"Ошибка очистки комментариев: {e}")
            self.conn.rollback()
    
    def get_max_id_from_source(self) -> int:
        try:
            with self.conn.cursor() as cur:
                cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {SOURCE_TABLE}")
                return cur.fetchone()[0]
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return 0
    
    def check_source_changes(self, last_processed_id: int) -> Tuple[List[Dict], int]:
        try:
            with self.conn.cursor() as cur:
                query = f"""
                    SELECT id, alarm_id, severity, active, acked, active_time, 
                           in_active_time, acked_time, message, update_type
                    FROM {SOURCE_TABLE}
                    WHERE id > %s AND severity >= 750 AND update_type IN (1, 2, 3)
                    ORDER BY id ASC
                """
                cur.execute(query, (last_processed_id,))
                results = cur.fetchall()
                
                changes = []
                for row in results:
                    record_id, alarm_id, severity, active, acked, active_time, in_active_time, acked_time, message, update_type = row
                    
                    valid_in_active_time = in_active_time if in_active_time and in_active_time >= active_time else 0
                    valid_acked_time = acked_time if acked_time and acked_time >= active_time else 0
                    valid_acked = acked if not (acked_time and acked_time < active_time) else 0
                    
                    cur.execute(f"SELECT active, acked, msg_sended, msg_view, comments FROM {TARGET_TABLE} WHERE alarm_id = %s", (alarm_id,))
                    existing = cur.fetchone()
                    
                    if not existing:
                        if update_type == UPDATE_TYPE_APPEAR:
                            changes.append({
                                'type': 'NEW', 'record_id': record_id, 'alarm_id': alarm_id,
                                'severity': severity, 'active': active, 'acked': valid_acked,
                                'active_time': active_time, 'in_active_time': valid_in_active_time,
                                'acked_time': valid_acked_time, 'message': message, 'update_type': update_type
                            })
                    else:
                        old_active, old_acked, old_msg_sended, old_msg_view, old_comments = existing
                        
                        msg_view_reset = False
                        msg_sended_reset = False
                        
                        # При повторном появлении (active 0→1) очищаем комментарии
                        if old_active == 0 and active == 1:
                            self.clear_comments(alarm_id)
                            msg_view_to_use = 0
                            msg_sended_to_use = 0
                            msg_view_reset = True
                            msg_sended_reset = True
                        else:
                            msg_view_to_use = old_msg_view
                            msg_sended_to_use = old_msg_sended
                        
                        # При подтверждении (update_type=3) добавляем комментарий
                        if update_type == UPDATE_TYPE_ACK and active == 1:
                            comment = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Подтверждение: {message}"
                            self.update_comments(alarm_id, comment)
                        
                        should_display = should_display_message(update_type, msg_view_to_use)
                        should_send = should_send_email(update_type, msg_sended_to_use)
                        
                        if should_display or should_send:
                            new_msg_view = calculate_msg_status(msg_view_to_use, update_type) if should_display else msg_view_to_use
                            new_msg_sended = calculate_msg_status(msg_sended_to_use, update_type) if should_send else msg_sended_to_use
                            
                            changes.append({
                                'type': 'UPDATE', 'event_type': get_update_type_text(update_type)[0],
                                'record_id': record_id, 'alarm_id': alarm_id,
                                'severity': severity, 'active': active, 'acked': valid_acked,
                                'old_active': old_active, 'old_acked': old_acked,
                                'active_time': active_time, 'in_active_time': valid_in_active_time,
                                'acked_time': valid_acked_time, 'message': message, 'update_type': update_type,
                                'msg_view': new_msg_view, 'msg_sended': new_msg_sended,
                                'old_msg_view': msg_view_to_use, 'old_msg_sended': msg_sended_to_use,
                                'should_display': should_display, 'should_send': should_send,
                                'msg_view_reset': msg_view_reset, 'msg_sended_reset': msg_sended_reset
                            })
                
                max_id = max([row[0] for row in results], default=last_processed_id)
                self.conn.commit()
                return changes, max_id
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            self.conn.rollback()
            return [], last_processed_id
    
    def reset_alarm_fields(self, alarm_id: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {TARGET_TABLE} 
                    SET in_active_time = 0, acked_time = 0, msg_sended = 0, msg_view = 0
                    WHERE alarm_id = %s
                """, (alarm_id,))
                self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            self.conn.rollback()
    
    def update_monitor_table(self, change: Dict) -> bool:
        try:
            with self.conn.cursor() as cur:
                if change['type'] == 'NEW':
                    cur.execute(f"""
                        INSERT INTO {TARGET_TABLE} (alarm_id, severity, active, acked,
                            active_time, in_active_time, acked_time, message, comments,
                            msg_sended, msg_view, last_id, last_update_type, first_seen, last_updated)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '', 0, 0, %s, %s,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """, (change['alarm_id'], change['severity'], change['active'], change['acked'],
                          change['active_time'], change['in_active_time'], change['acked_time'],
                          change['message'], change['record_id'], change['update_type']))
                    self.conn.commit()
                    return True
                    
                elif change['type'] == 'UPDATE':
                    set_parts = ["active = %s", "acked = %s", "in_active_time = %s",
                                "acked_time = %s", "message = %s", "last_id = %s",
                                "last_update_type = %s", "last_updated = CURRENT_TIMESTAMP"]
                    params = [change['active'], change['acked'], change['in_active_time'],
                             change['acked_time'], change['message'], change['record_id'], change['update_type']]
                    
                    has_last_displayed = False
                    has_last_email_sent = False
                    
                    if change.get('should_display', False) and not change.get('msg_view_reset', False):
                        set_parts.append("msg_view = %s")
                        params.append(change['msg_view'])
                        set_parts.append("last_displayed = CURRENT_TIMESTAMP")
                        has_last_displayed = True
                    
                    if change.get('should_send', False) and not change.get('msg_sended_reset', False):
                        set_parts.append("msg_sended = %s")
                        params.append(change['msg_sended'])
                        set_parts.append("last_email_sent = CURRENT_TIMESTAMP")
                        has_last_email_sent = True
                    
                    if change.get('msg_view_reset', False):
                        set_parts.append("msg_view = 0")
                        if not has_last_displayed:
                            set_parts.append("last_displayed = CURRENT_TIMESTAMP")
                    
                    if change.get('msg_sended_reset', False):
                        set_parts.append("msg_sended = 0")
                        if not has_last_email_sent:
                            set_parts.append("last_email_sent = CURRENT_TIMESTAMP")
                    
                    params.append(change['alarm_id'])
                    query = f"UPDATE {TARGET_TABLE} SET {', '.join(set_parts)} WHERE alarm_id = %s"
                    cur.execute(query, params)
                    self.conn.commit()
                    return True
            return False
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            self.conn.rollback()
            return False
    
    def get_active_events(self) -> List[Dict]:
        try:
            with self.conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {TARGET_TABLE} WHERE active = 1 ORDER BY severity DESC, first_seen DESC")
                rows = cur.fetchall()
                
                logger.info(f"📊 Найдено {len(rows)} активных записей в {TARGET_TABLE}")
                if rows and self.events_columns:
                    logger.info(f"📋 Колонки: {self.events_columns}")
                    first_row_dict = dict(zip(self.events_columns, rows[0]))
                    logger.info(f"📝 Пример записи: alarm_id={first_row_dict.get('alarm_id')}, "
                               f"severity={first_row_dict.get('severity')}, "
                               f"message={first_row_dict.get('message', '')[:50] if first_row_dict.get('message') else 'None'}...")
                
                events = []
                for row in rows:
                    event = {}
                    for i, col in enumerate(self.events_columns):
                        val = row[i]
                        if isinstance(val, datetime):
                            val = val.strftime('%Y-%m-%d %H:%M:%S')
                        event[col] = val
                    events.append(self._process_event(event))
                return events
        except Exception as e:
            logger.error(f"Ошибка получения активных событий: {e}")
            return []
    
    def _process_event(self, event: Dict) -> Dict:
        TICKS_PER_SECOND = 10000000
        
        # Временные поля
        for field in ['active_time', 'in_active_time', 'acked_time']:
            val = event.get(field, 0)
            if val and val > 0:
                dt = filetime_to_datetime(val)
                event[f"{field}_str"] = format_datetime(dt) if dt else "Не установлено"
            else:
                event[f"{field}_str"] = "Не установлено"
        
        # Время подтверждения (отдельно для отображения)
        acked_time_val = event.get('acked_time', 0)
        if acked_time_val and acked_time_val > 0:
            dt = filetime_to_datetime(acked_time_val)
            event['acked_time_str'] = format_datetime(dt) if dt else "Не подтверждено"
        else:
            event['acked_time_str'] = "Не подтверждено"
        
        # Используем last_update_type (это поле есть в таблице)
        update_type = event.get('last_update_type', 0)
        event['update_type_text'], event['update_type_class'], event['update_type_icon'] = get_update_type_text(update_type)
        
        # Длительность
        if event.get('active_time', 0) > 0 and event.get('in_active_time', 0) > 0:
            duration_sec = (event['in_active_time'] - event['active_time']) / TICKS_PER_SECOND
            event['duration'] = format_duration(duration_sec)
        else:
            event['duration'] = "Активно"
        
        severity_val = event.get('severity', 0)
        event['severity_text'], event['severity_class'] = get_severity_text(severity_val)
        
        return event
    
    def get_schedules(self) -> List[Dict]:
        try:
            with self.conn.cursor() as cur:
                cur.execute(f"""
                    SELECT id, schedule_name, send_time, days_of_week, is_active, last_sent,
                           send_on_appearance, send_on_disappearance, send_on_ack
                    FROM {SCHEDULE_TABLE} WHERE is_active = TRUE
                """)
                rows = cur.fetchall()
                return [{'id': r[0], 'name': r[1], 'send_time': r[2], 'days_of_week': r[3],
                        'is_active': r[4], 'last_sent': r[5],
                        'send_on_appearance': r[6], 'send_on_disappearance': r[7], 'send_on_ack': r[8]}
                        for r in rows]
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return []
    
    def update_schedule_last_sent(self, schedule_id: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute(f"UPDATE {SCHEDULE_TABLE} SET last_sent = CURRENT_TIMESTAMP WHERE id = %s", (schedule_id,))
                self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка: {e}")


# ==================== EMAIL МЕНЕДЖЕР ====================

class EmailManager:
    def __init__(self):
        self.smtp_settings = None
    
    def load_smtp_settings(self, db: DatabaseManager) -> bool:
        try:
            with db.conn.cursor() as cur:
                cur.execute("""
                    SELECT smtp_server, smtp_port, login, password, sender_email 
                    FROM email_settings ORDER BY updated_at DESC LIMIT 1
                """)
                row = cur.fetchone()
                if row:
                    self.smtp_settings = {
                        'smtp_server': row[0], 'smtp_port': row[1],
                        'username': row[2], 'password': row[3], 'from_addr': row[4]
                    }
                    logger.info(f"SMTP: {self.smtp_settings['smtp_server']}:{self.smtp_settings['smtp_port']}")
                    return True
                logger.error("Настройки SMTP не найдены")
                return False
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return False
    
    def get_recipients_with_conditions(self, db: DatabaseManager, update_type: int = None) -> List[Dict]:
        """Получение получателей с учетом условий отправки для конкретного типа события"""
        try:
            with db.conn.cursor() as cur:
                query = """
                    SELECT email, name FROM email_list 
                    WHERE is_active = true AND (unsubscribe_at IS NULL OR unsubscribe_at > NOW())
                """
                cur.execute(query)
                recipients = [{'email': r[0], 'name': r[1] if r[1] else r[0].split('@')[0]} for r in cur.fetchall()]
                
                if update_type is not None:
                    schedules = db.get_schedules()
                    filtered_recipients = []
                    
                    for recipient in recipients:
                        send_allowed = False
                        for schedule in schedules:
                            if update_type == UPDATE_TYPE_APPEAR and schedule.get('send_on_appearance', True):
                                send_allowed = True
                                break
                            elif update_type == UPDATE_TYPE_DISAPPEAR and schedule.get('send_on_disappearance', True):
                                send_allowed = True
                                break
                            elif update_type == UPDATE_TYPE_ACK and schedule.get('send_on_ack', True):
                                send_allowed = True
                                break
                        
                        if not schedules:
                            send_allowed = True
                        
                        if send_allowed:
                            filtered_recipients.append(recipient)
                    
                    logger.info(f"Получателей: {len(filtered_recipients)} из {len(recipients)} (условия для update_type={update_type})")
                    return filtered_recipients
                
                logger.info(f"Загружено {len(recipients)} получателей")
                return recipients
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return []
    
    def format_email_body(self, changed_events: List[Dict], active_events: List[Dict]) -> Tuple[str, str, str]:
        """Форматирование письма: сначала изменения, затем активные аварии"""
        
        # Формирование темы
        if changed_events:
            first_event = changed_events[0]
            _, _, icon = get_update_type_text(first_event.get('last_update_type', 0))
            subject = f"{icon} Изменение в системе мониторинга DCIM"
        else:
            subject = f"📊 Активные аварии DCIM от {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Текстовая версия
        text_body = "=" * 80 + "\n"
        text_body += "СИСТЕМА МОНИТОРИНГА DCIM\n"
        text_body += f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        text_body += "=" * 80 + "\n\n"
        
        # Сначала показываем изменения (если есть)
        if changed_events:
            text_body += "🔔 СОБЫТИЯ ИЗМЕНЕНИЙ:\n"
            text_body += "-" * 40 + "\n\n"
            
            for event in changed_events:
                _, _, icon = get_update_type_text(event.get('last_update_type', 0))
                text_body += f"{icon} {event.get('update_type_text', 'Событие')}\n"
                text_body += f"   Alarm ID: {event.get('alarm_id', 'N/A')}\n"
                text_body += f"   Важность: {event.get('severity_text', 'N/A')} ({event.get('severity', 'N/A')})\n"
                text_body += f"   Сообщение: {event.get('message', 'N/A')}\n"
                text_body += f"   Время: {event.get('active_time_str', 'N/A')}\n"
                
                if event.get('comments'):
                    text_body += f"   Комментарии:\n"
                    for line in event.get('comments', '').split('\n'):
                        if line.strip():
                            text_body += f"     • {line}\n"
                
                text_body += "\n"
            
            text_body += "\n"
        
        # Затем показываем активные аварии
        if active_events:
            text_body += "⚠️ АКТИВНЫЕ АВАРИИ:\n"
            text_body += "-" * 40 + "\n\n"
            
            for event in active_events:
                text_body += f"Alarm ID: {event.get('alarm_id', 'N/A')}\n"
                text_body += f"   Важность: {event.get('severity_text', 'N/A')} ({event.get('severity', 'N/A')})\n"
                text_body += f"   Сообщение: {event.get('message', 'N/A')}\n"  # Полный текст без обрезания
                text_body += f"   Время появления: {event.get('active_time_str', 'N/A')}\n"
                text_body += f"   Время подтверждения: {event.get('acked_time_str', 'Не подтверждено')}\n"
                text_body += f"   Длительность: {event.get('duration', 'N/A')}\n"
                text_body += f"   Статус: {'✅ Подтверждено' if event.get('acked') == 1 else '⏳ Ожидает'}\n"
                
                if event.get('comments'):
                    text_body += f"   📝 Комментарии:\n"
                    for line in event.get('comments', '').split('\n'):
                        if line.strip():
                            text_body += f"      • {line}\n"
                
                text_body += "\n"
        else:
            text_body += "✅ Нет активных аварий\n"
        
        html_body = self._build_html_body(changed_events, active_events)
        
        return subject, text_body, html_body
    
    def _build_html_body(self, changed_events: List[Dict], active_events: List[Dict]) -> str:
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>DCIM Мониторинг</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: white; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; }}
        .section {{ padding: 20px; border-bottom: 1px solid #eee; }}
        .section-title {{ font-size: 18px; font-weight: bold; margin-bottom: 15px; color: #333; }}
        .event-card {{ background: #f9f9f9; border-radius: 8px; padding: 15px; margin-bottom: 15px; border-left: 4px solid; }}
        .event-appearance {{ border-left-color: #ff9800; }}
        .event-disappearance {{ border-left-color: #4caf50; }}
        .event-ack {{ border-left-color: #2196f3; }}
        .event-title {{ font-weight: bold; font-size: 16px; margin-bottom: 10px; }}
        .event-detail {{ font-size: 13px; color: #555; margin: 5px 0; }}
        .severity-critical {{ color: #f44336; font-weight: bold; }}
        .severity-high {{ color: #ff9800; font-weight: bold; }}
        .severity-medium {{ color: #ffc107; font-weight: bold; }}
        .comments {{ background: #f0f0f0; padding: 10px; border-radius: 5px; margin-top: 10px; font-size: 12px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f5f5f5; }}
        .footer {{ padding: 20px; font-size: 11px; color: #999; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔔 Система мониторинга DCIM</h1>
            <p>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
"""
        
        # Секция изменений
        if changed_events:
            html += """
        <div class="section">
            <div class="section-title">🔔 События изменений</div>
"""
            for event in changed_events:
                _, class_name, icon = get_update_type_text(event.get('last_update_type', 0))
                html += f"""
            <div class="event-card event-{class_name}">
                <div class="event-title">{icon} {event.get('update_type_text', 'Событие')}</div>
                <div class="event-detail"><strong>Alarm ID:</strong> {event.get('alarm_id', 'N/A')}</div>
                <div class="event-detail"><strong>Важность:</strong> <span class="severity-{event.get('severity_class', '')}">{event.get('severity_text', 'N/A')}</span> ({event.get('severity', 'N/A')})</div>
                <div class="event-detail"><strong>Сообщение:</strong> {event.get('message', 'N/A')}</div>
                <div class="event-detail"><strong>Время:</strong> {event.get('active_time_str', 'N/A')}</div>
"""
                if event.get('comments'):
                    html += f"""
                <div class="comments">
                    <strong>📝 Комментарии:</strong><br>
                    {event.get('comments', '').replace(chr(10), '<br>')}
                </div>
"""
                html += """
            </div>
"""
            html += """
        </div>
"""
        
        # Секция активных аварий
        if active_events:
            html += """
        <div class="section">
            <div class="section-title">⚠️ Активные аварии</div>
            <table>
                <thead>
                    <tr>
                        <th>Alarm ID</th>
                        <th>Важность</th>
                        <th>Сообщение</th>
                        <th>Время появления</th>
                        <th>Время подтверждения</th>
                        <th>Длительность</th>
                        <th>Статус</th>
                    </tr>
                </thead>
                <tbody>
"""
            for event in active_events:
                status = "✅ Подтверждено" if event.get('acked') == 1 else "⏳ Ожидает"
                html += f"""
                    <tr>
                        <td>{event.get('alarm_id', 'N/A')}</td>
                        <td class="severity-{event.get('severity_class', '')}">{event.get('severity_text', 'N/A')}<br><small>({event.get('severity', 'N/A')})</small></td>
                        <td>{event.get('message', 'N/A')}</td>
                        <td>{event.get('active_time_str', 'N/A')}</td>
                        <td>{event.get('acked_time_str', 'Не подтверждено')}</td>
                        <td>{event.get('duration', 'N/A')}</td>
                        <td>{status}</td>
                    </tr>
"""
                if event.get('comments'):
                    html += f"""
                    <tr>
                        <td colspan="7">
                            <div class="comments">
                                <strong>📝 Комментарии:</strong><br>
                                {event.get('comments', '').replace(chr(10), '<br>')}
                            </div>
                        </td>
                    </tr>
"""
            html += """
                </tbody>
            </table>
        </div>
"""
        else:
            html += """
        <div class="section">
            <div class="section-title">✅ Статус</div>
            <p>Нет активных аварий</p>
        </div>
"""
        
        html += f"""
        <div class="footer">
            <hr>
            <p>⚠️ Автоматическое сообщение от системы мониторинга DCIM</p>
        </div>
    </div>
</body>
</html>"""
        
        return html
    
    def send_email(self, to_email: str, to_name: str, subject: str, text_body: str, html_body: str) -> bool:
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = self.smtp_settings['from_addr']
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))
            
            for port in [self.smtp_settings['smtp_port'], 587, 465, 25]:
                try:
                    if port == 465:
                        with smtplib.SMTP_SSL(self.smtp_settings['smtp_server'], port, timeout=30) as server:
                            server.login(self.smtp_settings['username'], self.smtp_settings['password'])
                            server.send_message(msg)
                    else:
                        with smtplib.SMTP(self.smtp_settings['smtp_server'], port, timeout=30) as server:
                            if port == 587:
                                server.starttls()
                            server.login(self.smtp_settings['username'], self.smtp_settings['password'])
                            server.send_message(msg)
                    logger.info(f"✅ Письмо отправлено: {to_email} (порт {port})")
                    return True
                except:
                    continue
            raise Exception("Все порты недоступны")
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            return False
    
    def send_bulk_emails(self, db: DatabaseManager, changed_events: List[Dict] = None, is_scheduled: bool = False) -> int:
        """Отправка email с учетом условий для получателей"""
        
        active_events = db.get_active_events()
        
        if not active_events and not changed_events:
            logger.info("Нет событий для отправки")
            return 0
        
        update_type = None
        if changed_events and len(changed_events) > 0:
            update_type = changed_events[0].get('update_type')
        
        recipients = self.get_recipients_with_conditions(db, update_type)
        
        if not recipients:
            logger.warning("Нет получателей для данного типа события")
            return 0
        
        subject, text_body, html_body = self.format_email_body(changed_events or [], active_events)
        
        success_count = 0
        for recipient in recipients:
            if self.send_email(recipient['email'], recipient['name'], subject, text_body, html_body):
                success_count += 1
        
        logger.info(f"📊 Рассылка: успешно {success_count}, ошибок {len(recipients) - success_count}")
        return success_count


# ==================== ОСНОВНАЯ ПРОГРАММА ====================

def display_message(change: Dict):
    print(f"\n{'='*80}")
    if change['type'] == 'NEW':
        print(f"🆕 НОВОЕ СООБЩЕНИЕ (Alarm ID: {change['alarm_id']})")
    else:
        print(f"🔄 ИЗМЕНЕНИЕ (Alarm ID: {change['alarm_id']})")
        print(f"   Active: {change['active']} (было: {change['old_active']})")
    print(f"{'='*80}")
    print(f"   Текст: {change['message']}")
    print(f"   Severity: {change['severity']}")
    print(f"{'='*80}\n")


def display_active_messages(db: DatabaseManager):
    events = db.get_active_events()
    if events:
        print(f"\n{'='*80}")
        print("АКТИВНЫЕ СООБЩЕНИЯ")
        print(f"{'='*80}")
        for event in events:
            print(f"\n⚠️ Alarm ID: {event.get('alarm_id')}")
            print(f"   Сообщение: {event.get('message')}")
            print(f"   Severity: {event.get('severity')}")
            print(f"   Активен: {'Да' if event.get('active') == 1 else 'Нет'}")
        print(f"{'='*80}")
    else:
        print("\n✅ Нет активных сообщений")


def process_schedules(db: DatabaseManager, email_mgr: EmailManager):
    schedules = db.get_schedules()
    for schedule in schedules:
        should_send = False
        if schedule.get('send_time'):
            should_send = check_schedule_time(schedule['send_time'], schedule.get('days_of_week', []), schedule.get('last_sent'))
        
        if should_send:
            logger.info(f"🕐 Расписание: {schedule['name']}")
            email_mgr.send_bulk_emails(db, is_scheduled=True)
            db.update_schedule_last_sent(schedule['id'])


def cleanup_old_logs(days: int = 30):
    try:
        logs_dir = Path("./logs")
        if logs_dir.exists():
            now = datetime.now()
            for item in logs_dir.iterdir():
                if item.is_dir():
                    try:
                        folder_date = datetime.strptime(item.name, '%Y-%m-%d')
                        if (now - folder_date).days > days:
                            import shutil
                            shutil.rmtree(item)
                            logger.info(f"Удалена: {item}")
                    except:
                        pass
    except Exception as e:
        logger.error(f"Ошибка очистки: {e}")


def health_check():
    """Простой health check для мониторинга"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            conn.close()
        return True
    except:
        return False


def main():
    global running
    
    print(f"{'='*80}")
    print(f"🚀 МОНИТОРИНГ DCIM (Версия {VERSION})")
    print(f"{'='*80}")
    print(f"📁 Таблица мониторинга: {TARGET_TABLE}")
    print(f"\n🛑 Для остановки Ctrl+C")
    print(f"{'='*80}\n")
    
    db = DatabaseManager()
    email_mgr = EmailManager()
    last_schedule_check = datetime.now()
    
    try:
        if not db.connect():
            logger.error("Не удалось подключиться к БД")
            sys.exit(1)
        
        if not db.check_source_table_structure():
            logger.error("Ошибка структуры исходной таблицы")
            return
        
        is_first_run = not db.check_target_table()
        
        if is_first_run:
            print("⚠️ Создание таблицы мониторинга...")
            if not db.create_monitor_table():
                print("❌ Ошибка создания таблицы")
                return
            
            print("📥 Заполнение начальными данными...")
            db.insert_initial_data()
            
            db.refresh_columns()
            
            if email_mgr.load_smtp_settings(db):
                print("📧 Отправка начальных сообщений...")
                active_events = db.get_active_events()
                email_mgr.send_bulk_emails(db, changed_events=active_events)
        else:
            db.refresh_columns()
            
            display_active_messages(db)
            if email_mgr.load_smtp_settings(db):
                print("📧 Проверка неотправленных сообщений...")
                active_events = db.get_active_events()
                if active_events:
                    email_mgr.send_bulk_emails(db, changed_events=active_events)
        
        db.ensure_columns_exist()
        last_processed_id = db.get_max_id_from_source()
        print(f"\n📍 Последний ID: {last_processed_id}")
        print("🔍 Начинаем мониторинг...\n")
        
        while running:
            if not health_check():
                logger.error("❌ Потеря соединения с БД, переподключение...")
                db.close()
                time.sleep(2)
                if not db.connect():
                    logger.error("❌ Не удалось переподключиться к БД")
                    time.sleep(10)
                    continue
            
            changes, new_id = db.check_source_changes(last_processed_id)
            
            if changes:
                for change in changes:
                    if db.update_monitor_table(change):
                        display_message(change)
                        if change.get('should_send', False) and email_mgr.smtp_settings:
                            logger.info(f"📧 Отправка для alarm_id={change['alarm_id']}")
                            email_mgr.send_bulk_emails(db, changed_events=[change])
                last_processed_id = new_id
            
            if (datetime.now() - last_schedule_check).total_seconds() >= SCHEDULE_CHECK_INTERVAL:
                if email_mgr.smtp_settings:
                    process_schedules(db, email_mgr)
                last_schedule_check = datetime.now()
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        print(f"\n🛑 ОСТАНОВЛЕНО (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
    finally:
        cleanup_old_logs(30)
        db.close()
        print("🏁 Мониторинг завершён")


if __name__ == "__main__":
    main()