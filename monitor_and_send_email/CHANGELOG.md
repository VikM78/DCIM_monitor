
---

## 📄 4. `requirements.txt` (корень проекта)

```txt
# DCIM Monitoring System - общие зависимости
# Updated: 2026-06-16

# Core
psycopg2-binary==2.9.9
python-dotenv==1.0.0

# Web interface (email_manager)
Flask==2.3.3
gunicorn==21.2.0

# GUI (shedule_email) - tkinter встроен в Python
# schedule - для расписания
schedule==1.2.0