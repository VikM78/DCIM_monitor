-- ============================================================
-- Миграция базы данных для DCIM Monitoring System
-- Версия: 2.0.0 → 2.1.0
-- Дата: 2026-06-19
-- Описание: Добавление системы подписок на события
-- ============================================================

-- 1. Добавление новых колонок в email_schedule
ALTER TABLE email_schedule ADD COLUMN IF NOT EXISTS event_type VARCHAR(50) DEFAULT 'all';
ALTER TABLE email_schedule ADD COLUMN IF NOT EXISTS send_without_time BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN email_schedule.event_type IS 'Тип события: appearance, disappearance, ack, all';
COMMENT ON COLUMN email_schedule.send_without_time IS 'Отправлять без привязки ко времени';

-- 2. Создание таблицы подписок
CREATE TABLE IF NOT EXISTS email_subscriptions (
    id SERIAL PRIMARY KEY,
    email_id INTEGER REFERENCES email_list(id) ON DELETE CASCADE,
    schedule_id INTEGER REFERENCES email_schedule(id) ON DELETE CASCADE,
    subscribed BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(email_id, schedule_id)
);

COMMENT ON TABLE email_subscriptions IS 'Подписки email на расписания событий';

-- 3. Индексы
CREATE INDEX IF NOT EXISTS idx_email_subscriptions_email_id ON email_subscriptions(email_id);
CREATE INDEX IF NOT EXISTS idx_email_subscriptions_schedule_id ON email_subscriptions(schedule_id);

-- 4. Триггер для updated_at
CREATE OR REPLACE FUNCTION update_subscriptions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_email_subscriptions_updated_at ON email_subscriptions;
CREATE TRIGGER update_email_subscriptions_updated_at
    BEFORE UPDATE ON email_subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION update_subscriptions_updated_at();

-- ============================================================
-- Проверка миграции
-- ============================================================
SELECT '✅ Миграция v2.1.0 выполнена успешно' as status;