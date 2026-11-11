# DashBoard

A lightweight real-time monitoring dashboard for Linux single-board computers (Orange Pi, Raspberry Pi and similar).

A background sampler reads the system every 2 seconds and keeps the last hour in memory, so the charts are already full when the page opens, every open tab sees the same numbers, and a tab that was in the background catches up without gaps.

## Features

- CPU load, per-core usage and frequency
- Temperatures from Linux thermal zones
- RAM (used / cache / free) and swap
- Every mounted filesystem, plus disk read/write rates
- Network RX/TX for the physical interfaces only (no double counting through loopback, Docker bridges or veth pairs)
- Docker containers: state, health check, CPU and memory (read from cgroup v2, no slow `docker stats` calls)
- Top processes by CPU over the last 10 seconds
- Charts for the last 5 min / 15 min / 1 h with a hover tooltip
- A health indicator that names the problem: overheating, full disk, low memory, heavy swap use, unhealthy container
- No frontend dependencies: plain canvas, about 30 KB in total
- Optional HTTP basic auth, `/healthz` endpoint for external monitoring

## Requirements

- Linux, Python 3.8+
- `flask`, `psutil`; `waitress` is recommended for running it as a service
- Docker is optional. The Containers card shows up when the user running the dashboard can read `/var/run/docker.sock` (is in the `docker` group)

## Installation

```bash
git clone https://github.com/kostyan99/DashBoard.git
cd DashBoard
pip install -r requirements.txt
# or on Debian/Ubuntu: sudo apt install python3-flask python3-psutil python3-waitress
python3 app.py
```

Open `http://localhost:8080`.

### Running as a service

```bash
sudo cp deploy/dashboard.service /etc/systemd/system/dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now dashboard
```

Edit `User=` and the paths in the unit if your setup is different.

### Publishing through Cloudflare Tunnel

The unit binds to `127.0.0.1`, so the dashboard can be reached only through the tunnel. Point the tunnel's public hostname to `http://localhost:8080`.

The dashboard shows process names, container names and the local IP. Protect the hostname with **Cloudflare Access** (Zero Trust → Access → Applications → Self-hosted, allow your e-mail). That needs no changes here. Alternatively, set `DASH_PASSWORD` to turn on basic auth.

## Configuration

All settings are environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `DASH_HOST` | `0.0.0.0` | Address to listen on |
| `DASH_PORT` | `8080` | Port |
| `DASH_SAMPLE_SEC` | `2` | Sampling period, seconds |
| `DASH_HISTORY_SEC` | `3600` | How much history to keep in memory |
| `DASH_USER` | `admin` | Basic auth user name |
| `DASH_PASSWORD` | *(empty)* | Basic auth password. Empty turns auth off |
| `DASH_DOCKER_SOCK` | `/var/run/docker.sock` | Docker API socket |

## API

- `GET /api/stats` returns the current values, all history points, top processes, containers and mounts.
- `GET /api/stats?since=<t>` returns the same, but only history points newer than `t`. The page uses this on every refresh.
- `GET /healthz` returns `200 ok`, or `503` if the sampler has stopped. It never asks for a password.

A history point is `[t, cpu%, rx B/s, tx B/s, read B/s, write B/s, temp0, temp1, …]`. The temperature order follows `temp_names`.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Project structure

```text
DashBoard/
├── app.py                  # sampler + Flask API
├── templates/index.html    # the whole frontend
├── tests/test_app.py
├── deploy/dashboard.service
└── requirements.txt
```

---

# DashBoard (на русском)

Лёгкая веб-панель мониторинга в реальном времени для одноплатных компьютеров на Linux (Orange Pi, Raspberry Pi и похожих).

Фоновый поток опрашивает систему каждые 2 секунды и хранит последний час в памяти. Поэтому графики заполнены сразу при открытии страницы, все вкладки показывают одинаковые цифры, а вкладка, которая была в фоне, догружает пропущенное без разрывов.

## Возможности

- Загрузка CPU, нагрузка и частота каждого ядра
- Температуры из thermal zones
- RAM (занято / кэш / свободно) и swap
- Все смонтированные файловые системы и скорость чтения/записи дисков
- Сетевой трафик только по физическим интерфейсам: без двойного счёта через loopback, Docker-мосты и veth
- Docker-контейнеры: состояние, healthcheck, CPU и память (читаются из cgroup v2, без медленного `docker stats`)
- Топ процессов по CPU за последние 10 секунд
- Графики за 5 мин / 15 мин / 1 ч с подсказкой при наведении
- Индикатор состояния называет конкретную проблему: перегрев, заполненный диск, нехватку памяти, активный swap, нездоровый контейнер
- На фронтенде нет зависимостей: чистый canvas, около 30 КБ
- Необязательная basic-авторизация, эндпоинт `/healthz` для внешнего мониторинга

## Установка

```bash
git clone https://github.com/kostyan99/DashBoard.git
cd DashBoard
pip install -r requirements.txt
# или: sudo apt install python3-flask python3-psutil python3-waitress
python3 app.py
```

Откройте `http://localhost:8080`.

### Запуск как сервис

```bash
sudo cp deploy/dashboard.service /etc/systemd/system/dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now dashboard
```

### Публикация через Cloudflare Tunnel

Сервис слушает только `127.0.0.1`, поэтому панель доступна только через туннель. В настройках туннеля публичный hostname должен вести на `http://localhost:8080`.

Панель показывает имена процессов, контейнеров и локальный IP. Закройте hostname через **Cloudflare Access** (Zero Trust → Access → Applications → Self-hosted, разрешить свой e-mail): менять код для этого не нужно. Другой вариант — задать `DASH_PASSWORD`, тогда включится basic-авторизация.

Все настройки (переменные окружения), API и запуск тестов описаны в английской части выше.
