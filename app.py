"""Orange Pi system dashboard.

A background thread samples the system every SAMPLE_SEC seconds and keeps the
last HISTORY_SEC seconds in memory, so charts are full the moment the page
opens and every browser tab sees the same numbers. The Flask app only serves
what the sampler has already collected.
"""
import collections
import glob
import hmac
import http.client
import json
import logging
import os
import platform
import socket
import threading
import time

import psutil
from flask import Flask, Response, jsonify, render_template, request

SAMPLE_SEC = float(os.environ.get('DASH_SAMPLE_SEC', 2))
HISTORY_SEC = int(os.environ.get('DASH_HISTORY_SEC', 3600))
SLOW_EVERY = 5  # processes, containers and mounts are refreshed every 5th sample (~10 s)
DOCKER_SOCK = os.environ.get('DASH_DOCKER_SOCK', '/var/run/docker.sock')
AUTH_USER = os.environ.get('DASH_USER', 'admin')
AUTH_PASS = os.environ.get('DASH_PASSWORD', '')  # empty = no password (e.g. behind Cloudflare Access)

TEMP_NAMES = {
    'cpub_thermal_zone': 'CPU (Big)',
    'cpul_thermal_zone': 'CPU (Little)',
    'gpu_thermal_zone': 'GPU',
    'npu_thermal_zone': 'NPU',
    'ddr_thermal_zone': 'RAM',
    'skin_zone': 'Board Surface',
}
IGNORE_ZONES = {'cpub_idle_zone', 'cpul_idle_zone'}
VIRTUAL_DISKS = ('loop', 'zram', 'ram', 'dm-')  # in-memory / stacked devices, not real I/O

log = logging.getLogger('dashboard')
app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)  # no console line per request


# ---------------------------------------------------------------- discovery

def read_file(path):
    with open(path) as f:
        return f.read().strip()


def board_model():
    try:
        return read_file('/proc/device-tree/model').rstrip('\x00').strip()
    except OSError:
        return ''


def find_zones():
    """Thermal zones never change at runtime: look them up once."""
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


def physical_nics():
    """Real network cards only. Loopback, docker bridges, veth pairs and VPN
    tunnels have no `device` link; counting them would count the same bytes
    two or three times (container -> veth -> bridge -> end0)."""
    try:
        names = os.listdir('/sys/class/net')
    except OSError:
        return []
    return sorted(n for n in names if os.path.exists(f'/sys/class/net/{n}/device'))


def physical_disks():
    """Whole block devices only (nvme0n1, not nvme0n1p1), so I/O is not counted
    twice, and no zram/loop devices, which are RAM or files, not disks."""
    try:
        names = os.listdir('/sys/block')
    except OSError:
        return []
    return sorted(d for d in names
                  if not d.startswith(VIRTUAL_DISKS) and os.path.exists(f'/sys/block/{d}/device'))


ZONES = find_zones()
NICS = physical_nics()
DISKS = physical_disks()
MODEL = board_model()
_ip_cache = {'ts': 0.0, 'ip': '—'}


def get_ip():
    if time.monotonic() - _ip_cache['ts'] > 60 or not _ip_cache['ts']:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(('10.255.255.255', 1))  # no packet is sent, this only picks a route
                _ip_cache['ip'] = s.getsockname()[0]
        except OSError:
            _ip_cache['ip'] = '—'
        _ip_cache['ts'] = time.monotonic()
    return _ip_cache['ip']


# ---------------------------------------------------------------- readers

def get_temps():
    out = []
    for _, path in ZONES:
        try:
            out.append(round(float(read_file(path)) / 1000.0, 1))
        except (OSError, ValueError):
            out.append(None)
    return out


def get_freqs(count):
    freqs = []
    for i in range(count):
        try:
            freqs.append(int(read_file(
                f'/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq')) // 1000)
        except (OSError, ValueError):
            freqs.append(None)
    return freqs


def net_counters():
    per = psutil.net_io_counters(pernic=True)
    rx = tx = err = drop = 0
    for n in NICS:
        c = per.get(n)
        if c:
            rx += c.bytes_recv
            tx += c.bytes_sent
            err += c.errin + c.errout
            drop += c.dropin + c.dropout
    return rx, tx, err, drop


def disk_counters():
    per = psutil.disk_io_counters(perdisk=True) or {}
    rd = sum(per[d].read_bytes for d in DISKS if d in per)
    wr = sum(per[d].write_bytes for d in DISKS if d in per)
    return rd, wr


def get_mounts():
    """Every real filesystem once. Bind mounts (/boot and /media/mmcboot are
    the same partition) are collapsed to the shortest mount point."""
    best = {}
    for p in psutil.disk_partitions(all=False):
        dev = p.device
        if not dev.startswith('/dev/') or os.path.basename(dev).startswith(VIRTUAL_DISKS):
            continue
        if dev not in best or len(p.mountpoint) < len(best[dev].mountpoint):
            best[dev] = p
    out = []
    for dev, p in best.items():
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        out.append({'mount': p.mountpoint, 'device': os.path.basename(dev), 'fs': p.fstype,
                    'used': u.used, 'total': u.total, 'percent': u.percent})
    out.sort(key=lambda m: (m['mount'] != '/', m['mount']))
    return out


def get_procs(limit=8):
    """Top processes by CPU over the last refresh period (not the lifetime
    average that `ps %cpu` shows). psutil keeps the Process objects between
    calls, so cpu_percent() is the delta since the previous call."""
    rows = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        i = p.info
        rows.append({'pid': i['pid'], 'name': (i['name'] or '?')[:32],
                     'cpu': round(i['cpu_percent'] or 0.0, 1),
                     'mem': round(i['memory_percent'] or 0.0, 1)})
    rows.sort(key=lambda r: (r['cpu'], r['mem']), reverse=True)
    return rows[:limit], len(rows)


# ---------------------------------------------------------------- docker

class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout=2.0):
        super().__init__('localhost', timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


def docker_get(path):
    conn = _UnixHTTPConnection(DOCKER_SOCK)
    try:
        conn.request('GET', path)
        r = conn.getresponse()
        body = r.read()
        if r.status != 200:
            raise OSError(f'docker API returned {r.status}')
        return json.loads(body)
    finally:
        conn.close()


def _cgroup_dir(cid):
    for d in (f'/sys/fs/cgroup/system.slice/docker-{cid}.scope', f'/sys/fs/cgroup/docker/{cid}'):
        if os.path.isdir(d):
            return d
    return None


def cgroup_usage(cid):
    """(cpu seconds, memory bytes) straight from cgroup v2. Much cheaper than
    the docker stats API, which blocks for ~1 s per container."""
    d = _cgroup_dir(cid)
    if not d:
        return None, None
    cpu = mem = None
    try:
        for line in read_file(f'{d}/cpu.stat').splitlines():
            k, v = line.split()
            if k == 'usage_usec':
                cpu = int(v) / 1e6
                break
        mem = int(read_file(f'{d}/memory.current'))
        for line in read_file(f'{d}/memory.stat').splitlines():
            k, v = line.split()
            if k == 'inactive_file':  # same as `docker stats`: page cache that can be dropped
                mem = max(0, mem - int(v))
                break
    except (OSError, ValueError):
        pass
    return cpu, mem


def health_of(status):
    s = status.lower()
    if '(unhealthy)' in s:
        return 'unhealthy'
    if '(healthy)' in s:
        return 'healthy'
    if 'health: starting' in s:
        return 'starting'
    return None


_docker_prev = {}


def get_containers(now):
    """None when docker is not installed or not accessible: the card is hidden."""
    try:
        items = docker_get('/containers/json?all=1')
    except (OSError, ValueError, http.client.HTTPException):
        return None
    out, seen = [], set()
    for c in items:
        cid = c.get('Id', '')
        seen.add(cid)
        status = c.get('Status', '')
        row = {'name': (c.get('Names') or ['?'])[0].lstrip('/'), 'image': c.get('Image', ''),
               'state': c.get('State', ''), 'status': status, 'health': health_of(status),
               'cpu': None, 'mem': None}
        if row['state'] == 'running':
            cpu, row['mem'] = cgroup_usage(cid)
            prev = _docker_prev.get(cid)
            if cpu is not None:
                if prev and now > prev[0]:
                    row['cpu'] = round(max(0.0, (cpu - prev[1]) / (now - prev[0]) * 100), 1)
                _docker_prev[cid] = (now, cpu)
        out.append(row)
    for cid in list(_docker_prev):
        if cid not in seen:
            del _docker_prev[cid]
    out.sort(key=lambda r: (r['state'] != 'running', r['name']))
    return out


# ---------------------------------------------------------------- sampler

class Monitor(threading.Thread):
    """Only this thread touches the stateful psutil counters, so two open
    tabs can no longer reset each other's CPU measurement window."""

    def __init__(self):
        super().__init__(name='sampler', daemon=True)
        self.lock = threading.Lock()
        # one point = [t, cpu%, rx B/s, tx B/s, read B/s, write B/s, temp0, temp1, ...]
        self.history = collections.deque(maxlen=max(1, int(HISTORY_SEC / SAMPLE_SEC)))
        self.now = None
        self._last_t = 0.0
        self.slow ={'procs': [], 'proc_count': 0, 'containers': None, 'mounts': []}

    def run(self):
        psutil.cpu_percent(percpu=True)
        get_procs()  # warm-up of the per-process CPU counters
        self._net, self._disk = net_counters(), disk_counters()
        last = time.monotonic()
        n = 0
        while True:
            time.sleep(max(0.0, last + SAMPLE_SEC - time.monotonic()))
            mono = time.monotonic()
            dt, last = mono - last, mono
            try:
                self.sample(dt)
            except Exception:  # never let one bad read kill the sampler
                log.exception('sample failed')
            if n % SLOW_EVERY == 0:
                try:
                    self.sample_slow(mono)
                except Exception:
                    log.exception('slow sample failed')
            n += 1

    def sample(self, dt):
        cores = psutil.cpu_percent(percpu=True)
        net, disk = net_counters(), disk_counters()
        rx = max(0.0, (net[0] - self._net[0]) / dt)
        tx = max(0.0, (net[1] - self._net[1]) / dt)
        rd = max(0.0, (disk[0] - self._disk[0]) / dt)
        wr = max(0.0, (disk[1] - self._disk[1]) / dt)
        self._net, self._disk = net, disk

        ram, swap = psutil.virtual_memory(), psutil.swap_memory()
        temps = get_temps()
        cpu = round(sum(cores) / len(cores), 1) if cores else 0.0
        # strictly increasing, even if NTP steps the clock back: clients ask for `since=<t>`
        t = self._last_t = max(round(time.time(), 2), round(self._last_t + 0.01, 2))
        now = {
            't': t,
            'cpu_percent': cpu,
            'cores': [round(c, 1) for c in cores],
            'freqs': get_freqs(len(cores)),
            'temps': temps,
            'ram': {'used': ram.used, 'total': ram.total, 'percent': ram.percent,
                    'cache': getattr(ram, 'cached', 0) + getattr(ram, 'buffers', 0)},
            'swap': {'used': swap.used, 'total': swap.total, 'percent': swap.percent},
            'net': {'rx': rx, 'tx': tx, 'recv': net[0], 'sent': net[1],
                    'errors': net[2], 'drops': net[3]},
            'disk_io': {'read': rd, 'write': wr},
        }
        point = [t, cpu, round(rx), round(tx), round(rd), round(wr), *temps]
        with self.lock:
            self.history.append(point)
            self.now = now

    def sample_slow(self, mono):
        procs, count = get_procs()
        slow = {'procs': procs, 'proc_count': count,
                'containers': get_containers(mono), 'mounts': get_mounts()}
        with self.lock:
            self.slow = slow

    def snapshot(self, since=None):
        with self.lock:
            if since is None:
                points = list(self.history)
            else:
                points = []
                for p in reversed(self.history):
                    if p[0] <= since:
                        break
                    points.append(p)
                points.reverse()
            return self.now, dict(self.slow), points


monitor = Monitor()
if os.environ.get('DASH_SAMPLER', '1') != '0':
    monitor.start()


# ---------------------------------------------------------------- http

@app.before_request
def require_auth():
    if not AUTH_PASS or request.path == '/healthz':
        return None
    a = request.authorization
    if a and hmac.compare_digest((a.username or '').encode(), AUTH_USER.encode()) \
            and hmac.compare_digest((a.password or '').encode(), AUTH_PASS.encode()):
        return None
    return Response('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="Dashboard"'})


@app.after_request
def security_headers(r):
    r.headers.setdefault('X-Content-Type-Options', 'nosniff')
    r.headers.setdefault('X-Frame-Options', 'DENY')
    r.headers.setdefault('Referrer-Policy', 'no-referrer')
    if request.path.startswith('/api/') or request.path == '/healthz':
        r.headers['Cache-Control'] = 'no-store'
    return r


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/stats')
def stats():
    """Current values plus every history point newer than `?since=<t>`
    (all of them when `since` is missing)."""
    since = request.args.get('since', type=float)
    now, slow, points = monitor.snapshot(since)
    return jsonify({
        'server_time': time.time(),
        'sample_sec': SAMPLE_SEC,
        'history_sec': HISTORY_SEC,
        'info': {'hostname': socket.gethostname(), 'model': MODEL, 'ip': get_ip(),
                 'kernel': platform.release(), 'uptime_sec': time.time() - psutil.boot_time()},
        'temp_names': [name for name, _ in ZONES],
        'now': now,
        'points': points,
        **slow,
    })


@app.route('/healthz')
def healthz():
    now, _, _ = monitor.snapshot(since=float('inf'))
    fresh = now is not None and time.time() - now['t'] < SAMPLE_SEC * 5
    return ('ok', 200) if fresh else ('sampler stalled', 503)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    host = os.environ.get('DASH_HOST', '0.0.0.0')
    port = int(os.environ.get('DASH_PORT', 8080))
    log.info('model=%r nics=%s disks=%s zones=%d', MODEL, NICS, DISKS, len(ZONES))
    try:
        from waitress import serve
    except ImportError:
        log.warning('waitress is not installed, falling back to the Flask development server')
        app.run(host=host, port=port, threaded=True)
        return
    log.info('serving on http://%s:%d', host, port)
    serve(app, host=host, port=port, threads=4)


if __name__ == '__main__':
    main()
