# DashBoard

DashBoard is a lightweight real-time system monitoring dashboard for Linux-based devices such as Orange Pi, Raspberry Pi, and other single-board computers.

It collects key hardware and system metrics from the operating system and presents them in a modern dark-themed web interface. The dashboard updates automatically and shows CPU load, memory usage, disk usage, temperatures, network throughput, and top running processes.

## Features

- Real-time CPU usage
- Per-core utilization and frequency
- Temperature monitoring from Linux thermal zones
- RAM and swap statistics
- Disk usage and I/O activity
- Network RX/TX traffic and error/drops counters
- Top processes by CPU usage
- Automatic refresh with live charts
- Clean dark dashboard UI
- JSON API for system stats

## Tech Stack

- Python
- Flask
- psutil
- HTML
- CSS
- JavaScript

## Requirements

- Python 3.8+
- Linux-based system
- Access to `/sys` entries such as:
  - `/sys/class/thermal/thermal_zone*`
  - `/sys/devices/system/cpu/*/cpufreq/scaling_cur_freq`

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/kostyan99/DashBoard.git
   cd DashBoard
   ```

2. Create and activate a virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install flask psutil
   ```

## Running the Project

Start the dashboard:

```bash
python app.py
```

Then open the app in your browser:

```text
http://localhost:8080
```

## API

The application exposes a JSON endpoint that returns the current system statistics:

```text
GET /api/stats
```

Example response fields include:
- `hostname`
- `ip`
- `kernel`
- `uptime_sec`
- `cpu_percent`
- `cores`
- `freqs`
- `ram`
- `swap`
- `disk`
- `disk_io`
- `temps`
- `net`
- `procs`
- `proc_count`

## Project Structure

```text
DashBoard/
├── app.py
├── templates/
│   └── index.html
├── requirements.txt (optional if added later)
└── README.md
```

## Notes

This project is specifically optimized for systems exposing hardware and thermal data through Linux sysfs. On unsupported platforms, some values (such as temperatures or CPU frequencies) may be missing or show as unavailable.

---

# Русский перевод

# DashBoard

DashBoard — это лёгкая веб-панель мониторинга системы в реальном времени для Linux-устройств, таких как Orange Pi, Raspberry Pi и другие одноплатные компьютеры.

Приложение собирает основные показатели железа и системы из операционной системы и отображает их в современном интерфейсе с тёмной темой. Панель автоматически обновляется и показывает загрузку процессора, использование памяти, диска, температуру, сетевой трафик и самые ресурсоёмкие процессы.

## Возможности

- Мониторинг загрузки CPU в реальном времени
- Использование каждого ядра и частота процессора
- Контроль температуры через Linux thermal zones
- Статистика RAM и swap
- Использование диска и активность ввода-вывода
- Сетевой трафик RX/TX и счётчики ошибок/потерь
- Топ процессов по загрузке CPU
- Автообновление с графиками
- Современный тёмный интерфейс
- JSON API для статистики системы

## Технологии

- Python
- Flask
- psutil
- HTML
- CSS
- JavaScript

## Требования

- Python 3.8+
- Linux-система
- Доступ к файлам `/sys`, например:
  - `/sys/class/thermal/thermal_zone*`
  - `/sys/devices/system/cpu/*/cpufreq/scaling_cur_freq`

## Установка

1. Склонируйте репозиторий:
   ```bash
   git clone https://github.com/kostyan99/DashBoard.git
   cd DashBoard
   ```

2. Создайте и активируйте виртуальное окружение (рекомендуется):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. Установите зависимости:
   ```bash
   pip install flask psutil
   ```

## Запуск проекта

Запустите приложение:

```bash
python app.py
```

Посл�� этого откройте страницу в браузере:

```text
http://localhost:8080
```

## API

Приложение предоставляет JSON-эндпоинт со статистикой системы:

```text
GET /api/stats
```

Примеры полей ответа:
- `hostname`
- `ip`
- `kernel`
- `uptime_sec`
- `cpu_percent`
- `cores`
- `freqs`
- `ram`
- `swap`
- `disk`
- `disk_io`
- `temps`
- `net`
- `procs`
- `proc_count`

## Структура проекта

```text
DashBoard/
├── app.py
├── templates/
│   └── index.html
├── requirements.txt (если будет добавлен позже)
└── README.md
```

## Примечания

Этот проект специально оптимизирован для систем, которые предоставляют данные о железе и температуре через Linux sysfs. На неподдерживаемых устройствах некоторые значения, такие как температура или частота CPU, могут отсутствовать или отображаться как недоступные.
