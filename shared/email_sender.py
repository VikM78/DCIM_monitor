#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Общие функции для отправки email
Используется всеми модулями проекта
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env файл из корня проекта
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)


def get_smtp_config():
    """Получить конфигурацию SMTP из переменных окружения"""
    return {
        'host': os.environ.get('SMTP_HOST', 'smtp.mail.ru'),
        'port': int(os.environ.get('SMTP_PORT', 465)),
        'user': os.environ.get('SMTP_USER', ''),
        'password': os.environ.get('SMTP_PASSWORD', ''),
        'from_addr': os.environ.get('SMTP_FROM', '')
    }


def send_email(to_addr, subject, body, html_body=None, smtp_config=None):
    """
    Отправка email через SMTP
    
    Args:
        to_addr: получатель
        subject: тема письма
        body: текст письма
        html_body: HTML версия (опционально)
        smtp_config: настройки SMTP (если None - берутся из .env)
    
    Returns:
        bool: True если отправлено успешно
    """
    if smtp_config is None:
        smtp_config = get_smtp_config()
    
    if not smtp_config['user'] or not smtp_config['password']:
        print("❌ SMTP не настроен")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = smtp_config['from_addr']
        msg['To'] = to_addr
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        if html_body:
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        
        ports = [smtp_config['port'], 587, 465, 25]
        for port in ports:
            try:
                if port == 465:
                    with smtplib.SMTP_SSL(smtp_config['host'], port, timeout=30) as server:
                        server.login(smtp_config['user'], smtp_config['password'])
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(smtp_config['host'], port, timeout=30) as server:
                        if port == 587:
                            server.starttls()
                        server.login(smtp_config['user'], smtp_config['password'])
                        server.send_message(msg)
                print(f"✅ Письмо отправлено на {to_addr} (порт {port})")
                return True
            except Exception:
                continue
        
        print(f"❌ Не удалось отправить письмо на {to_addr}")
        return False
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return False