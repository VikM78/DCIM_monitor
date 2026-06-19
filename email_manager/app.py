#!/usr/bin/env python3
"""
Email Manager - Production версия v2.1.0
Дата: 2026-06-19
Версия: 2.1.0
Новое: Система подписок на события планировщика
"""

import os
import secrets
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import psycopg2
from psycopg2 import sql, OperationalError
from datetime import datetime

# ============ ЗАГРУЗКА .env ============
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config_loader  # Загружает .env
# ======================================

# Версия приложения
VERSION = "2.1.0"
APP_NAME = "Email Manager"

# Настройка логирования
def setup_logging():
    """Настройка системы логирования"""
    log_dir = Path(__file__).parent.parent / "logs"
    if not log_dir.exists():
        log_dir.mkdir(parents=True)
    
    file_handler = RotatingFileHandler(
        str(log_dir / 'email_manager.log'),
        maxBytes=10240,
        backupCount=10
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info(f'{APP_NAME} v{VERSION} запущен')

app = Flask(__name__)

# Настройка логирования
setup_logging()

# Production-безопасный ключ
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    app.secret_key = secrets.token_hex(32)
    app.logger.warning(f"Используется сгенерированный ключ: {app.secret_key[:8]}...")
    print(f"⚠️ Внимание: Используется сгенерированный ключ: {app.secret_key[:8]}...")
    print("Для production укажите SECRET_KEY в .env файле или переменных окружения")

# Конфигурация базы данных
DB_CONFIG = {
    'dbname': os.environ.get('DB_MESSAGE_NAME', 'message_db'),
    'user': os.environ.get('DB_MESSAGE_USER', 'DCIM_Archive'),
    'password': os.environ.get('DB_MESSAGE_PASSWORD', 'DCIM_Archive_pwd'),
    'host': os.environ.get('DB_MESSAGE_HOST', 'localhost'),
    'port': os.environ.get('DB_MESSAGE_PORT', '5432')
}

# Настройки для production
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'True').lower() == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = int(os.environ.get('SESSION_LIFETIME', 3600))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

def get_db_connection():
    """Установка соединения с базой данных с повторными попытками"""
    max_retries = int(os.environ.get('DB_MESSAGE_MAX_RETRIES', 3))
    retry_delay = int(os.environ.get('DB_MESSAGE_RETRY_DELAY', 1))
    
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            app.logger.info(f"Подключение к БД установлено (попытка {attempt + 1})")
            return conn
        except OperationalError as e:
            app.logger.warning(f"Попытка {attempt + 1} не удалась: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(retry_delay)
            else:
                app.logger.error(f"Ошибка подключения к БД после {max_retries} попыток: {e}")
                return None

def init_db():
    """Инициализация таблиц"""
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            
            # Таблица email_list
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_list (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    name VARCHAR(100),
                    is_active BOOLEAN DEFAULT TRUE,
                    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    unsubscribe_at TIMESTAMP,
                    source VARCHAR(50),
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Индексы
            cur.execute("CREATE INDEX IF NOT EXISTS idx_email_list_email ON email_list(email)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_email_list_is_active ON email_list(is_active)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_email_list_subscribed_at ON email_list(subscribed_at)")
            
            # Триггер для updated_at
            cur.execute("""
                CREATE OR REPLACE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ language 'plpgsql'
            """)
            
            cur.execute("""
                DROP TRIGGER IF EXISTS update_email_list_updated_at ON email_list;
                CREATE TRIGGER update_email_list_updated_at
                    BEFORE UPDATE ON email_list
                    FOR EACH ROW
                    EXECUTE FUNCTION update_updated_at_column()
            """)
            
            # Таблица email_subscriptions (подписки)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_subscriptions (
                    id SERIAL PRIMARY KEY,
                    email_id INTEGER REFERENCES email_list(id) ON DELETE CASCADE,
                    schedule_id INTEGER REFERENCES email_schedule(id) ON DELETE CASCADE,
                    subscribed BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(email_id, schedule_id)
                )
            """)
            
            cur.execute("CREATE INDEX IF NOT EXISTS idx_email_subscriptions_email_id ON email_subscriptions(email_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_email_subscriptions_schedule_id ON email_subscriptions(schedule_id)")
            
            cur.execute("""
                DROP TRIGGER IF EXISTS update_email_subscriptions_updated_at ON email_subscriptions;
                CREATE TRIGGER update_email_subscriptions_updated_at
                    BEFORE UPDATE ON email_subscriptions
                    FOR EACH ROW
                    EXECUTE FUNCTION update_updated_at_column()
            """)
            
            conn.commit()
            app.logger.info("Таблицы успешно созданы/проверены")
            print("✅ Таблицы успешно созданы/проверены")
            
        except Exception as e:
            app.logger.error(f"Ошибка при создании таблиц: {e}")
            print(f"❌ Ошибка при создании таблиц: {e}")
        finally:
            cur.close()
            conn.close()
    else:
        app.logger.error("Не удалось подключиться к БД для инициализации")
        print("❌ Не удалось подключиться к БД для инициализации")

# Инициализируем БД при запуске
init_db()


# ==================== ОСНОВНЫЕ МАРШРУТЫ ====================

@app.route('/')
def index():
    """Главная страница - список всех записей"""
    app.logger.info("Запрос главной страницы")
    conn = get_db_connection()
    if not conn:
        flash('❌ Ошибка подключения к базе данных', 'error')
        return render_template('index.html', emails=[])
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, email, name, is_active, 
                   subscribed_at, source, notes
            FROM email_list 
            ORDER BY id DESC
        """)
        emails = cur.fetchall()
        cur.close()
        conn.close()
        app.logger.info(f"Загружено {len(emails)} записей")
        return render_template('index.html', emails=emails, version=VERSION)
    except Exception as e:
        app.logger.error(f"Ошибка при получении данных: {e}")
        flash(f'❌ Ошибка: {e}', 'error')
        return render_template('index.html', emails=[], version=VERSION)


@app.route('/add', methods=['GET', 'POST'])
def add_email():
    """Добавление новой записи"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        name = request.form.get('name', '').strip() or None
        source = request.form.get('source', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        is_active = request.form.get('is_active') == 'on'
        
        if not email:
            flash('❌ Email обязателен для заполнения', 'error')
            return redirect(url_for('add_email'))
        
        if '@' not in email or '.' not in email:
            flash('❌ Введите корректный email адрес', 'error')
            return redirect(url_for('add_email'))
        
        app.logger.info(f"Добавление email: {email}")
        
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO email_list (email, name, source, notes, is_active)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (email, name, source, notes, is_active))
                conn.commit()
                app.logger.info(f"Email {email} успешно добавлен (ID: {cur.fetchone()[0]})")
                flash(f'✅ Email {email} успешно добавлен!', 'success')
                cur.close()
                conn.close()
                return redirect(url_for('index'))
            except psycopg2.IntegrityError:
                app.logger.warning(f"Попытка добавить дубликат email: {email}")
                flash(f'❌ Email {email} уже существует в базе данных!', 'error')
                conn.rollback()
            except Exception as e:
                app.logger.error(f"Ошибка при добавлении: {e}")
                flash(f'❌ Ошибка при добавлении: {e}', 'error')
            finally:
                if 'cur' in locals():
                    cur.close()
                conn.close()
        else:
            flash('❌ Ошибка подключения к БД', 'error')
        
        return redirect(url_for('add_email'))
    
    return render_template('add.html', version=VERSION)


@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_email(id):
    """Редактирование записи"""
    conn = get_db_connection()
    if not conn:
        flash('❌ Ошибка подключения к базе данных', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        name = request.form.get('name', '').strip() or None
        source = request.form.get('source', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        is_active = request.form.get('is_active') == 'on'
        
        if not email:
            flash('❌ Email обязателен для заполнения', 'error')
            return redirect(url_for('edit_email', id=id))
        
        if '@' not in email or '.' not in email:
            flash('❌ Введите корректный email адрес', 'error')
            return redirect(url_for('edit_email', id=id))
        
        app.logger.info(f"Редактирование записи ID: {id}")
        
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE email_list 
                SET email = %s, name = %s, source = %s, 
                    notes = %s, is_active = %s
                WHERE id = %s
                RETURNING email
            """, (email, name, source, notes, is_active, id))
            result = cur.fetchone()
            conn.commit()
            app.logger.info(f"Запись ID {id} обновлена: {result[0] if result else 'unknown'}")
            flash('✅ Запись успешно обновлена!', 'success')
            cur.close()
            conn.close()
            return redirect(url_for('index'))
        except psycopg2.IntegrityError:
            app.logger.warning(f"Конфликт email при редактировании ID {id}")
            flash(f'❌ Email {email} уже существует!', 'error')
            conn.rollback()
        except Exception as e:
            app.logger.error(f"Ошибка при обновлении ID {id}: {e}")
            flash(f'❌ Ошибка при обновлении: {e}', 'error')
        finally:
            if 'cur' in locals():
                cur.close()
            conn.close()
        
        return redirect(url_for('edit_email', id=id))
    
    # GET запрос - показываем форму с текущими данными
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, email, name, is_active, source, notes
            FROM email_list WHERE id = %s
        """, (id,))
        email_data = cur.fetchone()
        cur.close()
        conn.close()
        
        if not email_data:
            app.logger.warning(f"Запись ID {id} не найдена")
            flash('❌ Запись не найдена', 'error')
            return redirect(url_for('index'))
        
        return render_template('edit.html', email=email_data, version=VERSION)
    except Exception as e:
        app.logger.error(f"Ошибка при загрузке ID {id}: {e}")
        flash(f'❌ Ошибка: {e}', 'error')
        return redirect(url_for('index'))


@app.route('/delete/<int:id>')
def delete_email(id):
    """Удаление записи"""
    app.logger.info(f"Удаление записи ID: {id}")
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT email FROM email_list WHERE id = %s", (id,))
            result = cur.fetchone()
            email = result[0] if result else 'Неизвестный'
            
            cur.execute("DELETE FROM email_list WHERE id = %s", (id,))
            conn.commit()
            app.logger.info(f"Запись {email} (ID: {id}) успешно удалена")
            flash(f'✅ Запись "{email}" успешно удалена!', 'success')
            cur.close()
            conn.close()
        except Exception as e:
            app.logger.error(f"Ошибка при удалении ID {id}: {e}")
            flash(f'❌ Ошибка при удалении: {e}', 'error')
    else:
        flash('❌ Ошибка подключения к БД', 'error')
    
    return redirect(url_for('index'))


@app.route('/toggle/<int:id>')
def toggle_active(id):
    """Переключение статуса is_active"""
    app.logger.info(f"Переключение статуса ID: {id}")
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE email_list 
                SET is_active = NOT is_active
                WHERE id = %s
                RETURNING is_active, email
            """, (id,))
            result = cur.fetchone()
            conn.commit()
            
            if result:
                new_status = "активен" if result[0] else "неактивен"
                app.logger.info(f"Статус записи {result[1]} (ID: {id}) изменен на {new_status}")
                flash(f'✅ Статус изменен на "{new_status}"!', 'success')
            else:
                flash('❌ Запись не найдена', 'error')
            
            cur.close()
            conn.close()
        except Exception as e:
            app.logger.error(f"Ошибка при изменении статуса ID {id}: {e}")
            flash(f'❌ Ошибка: {e}', 'error')
    else:
        flash('❌ Ошибка подключения к БД', 'error')
    
    return redirect(url_for('index'))


# ==================== ПОДПИСКИ НА СОБЫТИЯ ====================

@app.route('/subscribe/<int:email_id>', methods=['GET', 'POST'])
def manage_subscriptions(email_id):
    """Управление подписками на события"""
    conn = get_db_connection()
    if not conn:
        flash('❌ Ошибка подключения к базе данных', 'error')
        return redirect(url_for('index'))
    
    try:
        cur = conn.cursor()
        
        # Получаем информацию о email
        cur.execute("SELECT id, email, name FROM email_list WHERE id = %s", (email_id,))
        email_data = cur.fetchone()
        if not email_data:
            flash('❌ Email не найден', 'error')
            conn.close()
            return redirect(url_for('index'))
        
        # Получаем все активные расписания
        cur.execute("""
            SELECT id, schedule_name, event_type, send_without_time,
                   send_on_appearance, send_on_disappearance, send_on_ack
            FROM email_schedule 
            WHERE is_active = TRUE
            ORDER BY schedule_name
        """)
        schedules = cur.fetchall()
        
        # Получаем текущие подписки
        cur.execute("""
            SELECT schedule_id FROM email_subscriptions 
            WHERE email_id = %s AND subscribed = TRUE
        """, (email_id,))
        subscribed_ids = [row[0] for row in cur.fetchall()]
        
        cur.close()
        conn.close()
    except Exception as e:
        app.logger.error(f"Ошибка: {e}")
        flash(f'❌ Ошибка: {e}', 'error')
        if conn:
            conn.close()
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        selected = request.form.getlist('subscriptions')
        selected_ids = [int(x) for x in selected] if selected else []
        
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                # Удаляем старые подписки
                cur.execute("DELETE FROM email_subscriptions WHERE email_id = %s", (email_id,))
                
                # Добавляем новые
                for schedule_id in selected_ids:
                    cur.execute("""
                        INSERT INTO email_subscriptions (email_id, schedule_id, subscribed)
                        VALUES (%s, %s, TRUE)
                    """, (email_id, schedule_id))
                
                conn.commit()
                cur.close()
                conn.close()
                flash(f'✅ Подписки для {email_data[1]} обновлены!', 'success')
                return redirect(url_for('index'))
            except Exception as e:
                app.logger.error(f"Ошибка сохранения подписок: {e}")
                flash(f'❌ Ошибка: {e}', 'error')
                conn.rollback()
                conn.close()
        else:
            flash('❌ Ошибка подключения к БД', 'error')
    
    return render_template('subscribe.html', 
                          email=email_data, 
                          schedules=schedules,
                          subscribed_ids=subscribed_ids,
                          version=VERSION)


# ==================== API И СТАТИСТИКА ====================

@app.route('/api/emails', methods=['GET'])
def api_get_emails():
    """API endpoint для получения списка email (JSON)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, email, name, is_active, subscribed_at, source
            FROM email_list 
            ORDER BY id DESC
        """)
        emails = cur.fetchall()
        cur.close()
        conn.close()
        
        result = []
        for email in emails:
            result.append({
                'id': email[0],
                'email': email[1],
                'name': email[2],
                'is_active': email[3],
                'subscribed_at': email[4].isoformat() if email[4] else None,
                'source': email[5]
            })
        
        return jsonify(result), 200
    except Exception as e:
        app.logger.error(f"API ошибка: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health_check():
    """Endpoint для проверки работоспособности"""
    status = {
        'status': 'healthy',
        'version': VERSION,
        'app_name': APP_NAME,
        'timestamp': datetime.now().isoformat(),
        'database': 'disconnected'
    }
    
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            conn.close()
            status['database'] = 'connected'
            return jsonify(status), 200
        except Exception as e:
            status['status'] = 'unhealthy'
            status['database'] = 'error'
            status['error'] = str(e)
            return jsonify(status), 500
    
    status['status'] = 'unhealthy'
    return jsonify(status), 500


@app.route('/version')
def show_version():
    """Показать информацию о версии"""
    return jsonify({
        'version': VERSION,
        'app_name': APP_NAME,
        'environment': os.environ.get('FLASK_ENV', 'production'),
        'database': 'PostgreSQL',
        'python_version': os.environ.get('PYTHON_VERSION', '3.9+'),
        'flask_version': Flask.__version__
    })


@app.route('/stats')
def get_stats():
    """Статистика по email"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN is_active THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN NOT is_active THEN 1 ELSE 0 END) as inactive,
                COUNT(DISTINCT source) as sources_count
            FROM email_list
        """)
        stats = cur.fetchone()
        
        cur.execute("""
            SELECT source, COUNT(*) as count
            FROM email_list
            WHERE source IS NOT NULL
            GROUP BY source
            ORDER BY count DESC
        """)
        sources = cur.fetchall()
        
        cur.close()
        conn.close()
        
        result = {
            'total': stats[0],
            'active': stats[1],
            'inactive': stats[2],
            'sources_count': stats[3],
            'sources': [{'name': s[0], 'count': s[1]} for s in sources]
        }
        
        return jsonify(result), 200
    except Exception as e:
        app.logger.error(f"Ошибка получения статистики: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== ОБРАБОТКА ОШИБОК ====================

@app.errorhandler(404)
def not_found_error(error):
    app.logger.warning(f"404 error: {request.url}")
    return render_template('index.html', error="Страница не найдена", version=VERSION), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal Server Error: {error}")
    flash('❌ Внутренняя ошибка сервера. Попробуйте позже.', 'error')
    return render_template('index.html', emails=[], version=VERSION), 500


# ==================== ЗАПУСК ====================

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    if debug_mode:
        app.logger.info("Запуск в DEVELOPMENT режиме")
        print("🔧 Запуск в DEVELOPMENT режиме")
        app.run(debug=True, host='0.0.0.0', port=5000)
    else:
        app.logger.info("Для production используйте gunicorn")
        print("🚀 Для production используйте:")
        print("   gunicorn -w 4 -b 0.0.0.0:5000 app:app")
        print("   или")
        print("   python app.py --debug")