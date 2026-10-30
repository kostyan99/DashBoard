import glob
import logging
import platform
import socket
import subprocess
import time

import psutil
from flask import Flask, jsonify, render_template

app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)  # no console line per request

TEMP_NAMES = {
    'cpub_thermal_zone': 'CPU (Big)',
    'cpul_thermal_zone': 'CPU (Little)',
    'gpu_thermal_zone': 'GPU',
    'npu_thermal_zone': 'NPU',
    'ddr_thermal_zone': 'RAM',
    'skin_zone': 'Board Surface',
}
IGNORE_ZONES = {'cpub_idle_zone', 'cpul_idle_zone'}

PROCS_TTL = 10  # seconds. Spawning `ps` is the most expensive thing here, so do it rarely.

# Warm-up of the CPU counter
psutil.cpu_percent(percpu=True)

_ip_cache = {'ts': 0, 'ip': '—'}
_procs_cache = {'ts': float('-inf'), 'list': [], 'count': 0}


def read_file(path):
    with open(path) as f:
        return f.read().strip()


def get_ip():
    if time.time() - _ip_cache['ts'] > 60:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('10.255.255.255', 1))
            _ip_cache['ip'] = s.getsockname()[0]
            s.close()
        except OSError:
            _ip_cache['ip'] = '—'
        _ip_cache['ts'] = time.time()
    return _ip_cache['ip']


def find_zones():
    """Thermal zones never change at runtime: look them up once at startup."""
    zones = []
    paths = glob.glob('/sys/class/thermal/thermal_zone*')
    for zone in sorted(paths, key=lambda p: int(p.rsplit('thermal_zone', 1)[1])):
        try:
            raw = read_file(f'{zone}/type')
        except OSError:
            continue
        if raw not in IGNORE_ZONES:
            zones.append((TEMP_NAMES.get(raw, raw), f'{zone}/temp'))
    return zones


ZONES = find_zones()


def get_temps():
    temps = []
    for name, path in ZONES:
        try:
            temps.append({'name': name, 'value': round(float(read_file(path)) / 1000.0, 1)})
        except (OSError, ValueError):
            continue
    return temps


def get_freqs(count):
    freqs = []
    for i in range(count):
        try:
            freqs.append(int(read_file(
                f'/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq')) // 1000)
        except (OSError, ValueError):
            freqs.append(None)
    return freqs


def get_top_procs(limit=6):
    """Returns (top list, total process count). Cached for PROCS_TTL seconds."""
    c = _procs_cache
    if time.monotonic() - c['ts'] < PROCS_TTL:
        return c['list'], c['count']

    rows = []
    try:
        # one fork instead of three (no shell, no `head`)
        out = subprocess.run(
            ['ps', '--no-headers', '-eo', 'pid,%cpu,%mem,comm', '--sort=-%cpu'],
            capture_output=True, text=True, timeout=3).stdout
        for line in out.splitlines():
            parts = line.split(maxsplit=3)
            if len(parts) == 4 and parts[3] != 'ps':
                rows.append({'pid': int(parts[0]), 'cpu': float(parts[1]),
                             'mem': float(parts[2]), 'name': parts[3][:25]})
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

    c.update(ts=time.monotonic(), list=rows[:limit], count=len(rows))
    return c['list'], c['count']


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/stats')
def stats():
    cores = psutil.cpu_percent(percpu=True)
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage('/')
    net = psutil.net_io_counters()
    dio = psutil.disk_io_counters()
    procs, proc_count = get_top_procs()

    return jsonify({
        'ts': time.time(),
        'hostname': socket.gethostname(),
        'ip': get_ip(),
        'kernel': platform.release(),
        'uptime_sec': time.time() - psutil.boot_time(),
        'cpu_percent': round(sum(cores) / len(cores), 1),
        'cores': cores,
        'freqs': get_freqs(len(cores)),
        'ram': {'used': ram.used, 'total': ram.total, 'percent': ram.percent,
                'cached': getattr(ram, 'cached', 0)},
        'swap': {'used': swap.used, 'total': swap.total, 'percent': swap.percent},
        'disk': {'used': disk.used, 'total': disk.total, 'percent': disk.percent},
        'disk_io': {'read': dio.read_bytes, 'write': dio.write_bytes} if dio else None,
        'temps': get_temps(),
        'net': {'sent': net.bytes_sent, 'recv': net.bytes_recv,
                'errors': net.errin + net.errout, 'drops': net.dropin + net.dropout},
        'procs': procs,
        'proc_count': proc_count,
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
