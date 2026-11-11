"""Run with:  python3 -m unittest discover -s tests"""
import os
import sys
import unittest
from collections import namedtuple
from unittest import mock

os.environ['DASH_SAMPLER'] = '0'  # tests drive the sampler by hand
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

Part = namedtuple('Part', 'device mountpoint fstype opts')
Usage = namedtuple('Usage', 'total used free percent')


def fresh_monitor():
    m = app.Monitor()
    m._net, m._disk = app.net_counters(), app.disk_counters()
    app.psutil.cpu_percent(percpu=True)
    return m


class HelpersTest(unittest.TestCase):
    def test_health_parsing(self):
        self.assertEqual(app.health_of('Up 2 hours (healthy)'), 'healthy')
        self.assertEqual(app.health_of('Up 5 minutes (unhealthy)'), 'unhealthy')
        self.assertEqual(app.health_of('Up 3 seconds (health: starting)'), 'starting')
        self.assertIsNone(app.health_of('Up 10 hours'))
        self.assertIsNone(app.health_of('Exited (0) 2 weeks ago'))

    def test_mounts_skip_virtual_and_collapse_bind_mounts(self):
        parts = [Part('/dev/nvme0n1p1', '/', 'ext4', ''),
                 Part('/dev/mmcblk1p1', '/media/mmcboot', 'ext4', ''),
                 Part('/dev/mmcblk1p1', '/boot', 'ext4', ''),
                 Part('/dev/nvme0n1p1', '/var/hdd.log', 'ext4', ''),
                 Part('/dev/zram1', '/var/log', 'ext4', ''),
                 Part('/dev/loop0', '/snap/x', 'squashfs', '')]
        with mock.patch.object(app.psutil, 'disk_partitions', return_value=parts), \
                mock.patch.object(app.psutil, 'disk_usage', return_value=Usage(100, 40, 60, 40.0)):
            mounts = app.get_mounts()
        self.assertEqual([(m['mount'], m['device']) for m in mounts],
                         [('/', 'nvme0n1p1'), ('/boot', 'mmcblk1p1')])

    def test_virtual_interfaces_and_partitions_are_excluded(self):
        self.assertNotIn('lo', app.NICS)
        self.assertFalse(any(n.startswith(('veth', 'docker', 'br-')) for n in app.NICS))
        self.assertFalse(any(d.startswith(app.VIRTUAL_DISKS) for d in app.DISKS))

    def test_procs_are_sorted_by_cpu(self):
        procs, count = app.get_procs(limit=5)
        self.assertLessEqual(len(procs), 5)
        self.assertGreaterEqual(count, len(procs))
        cpus = [p['cpu'] for p in procs]
        self.assertEqual(cpus, sorted(cpus, reverse=True))


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.m = fresh_monitor()
        self.patch = mock.patch.object(app, 'monitor', self.m)
        self.patch.start()
        self.client = app.app.test_client()

    def tearDown(self):
        self.patch.stop()

    def test_starting_state_has_no_data(self):
        d = self.client.get('/api/stats').get_json()
        self.assertIsNone(d['now'])
        self.assertEqual(d['points'], [])
        self.assertEqual(self.client.get('/healthz').status_code, 503)

    def test_stats_and_incremental_history(self):
        for _ in range(3):
            self.m.sample(app.SAMPLE_SEC)
        self.m.sample_slow(1.0)
        r = self.client.get('/api/stats')
        self.assertEqual(r.headers['Cache-Control'], 'no-store')
        d = r.get_json()
        self.assertEqual(len(d['points']), 3)
        self.assertEqual(len(d['points'][0]), 6 + len(d['temp_names']))
        for key in ('cpu_percent', 'cores', 'freqs', 'temps', 'ram', 'swap', 'net', 'disk_io'):
            self.assertIn(key, d['now'])
        self.assertTrue(d['mounts'])

        since = d['points'][-2][0]
        d2 = self.client.get(f'/api/stats?since={since}').get_json()
        self.assertEqual(d2['points'], d['points'][-1:])
        self.assertEqual(self.client.get('/healthz').status_code, 200)

    def test_basic_auth(self):
        with mock.patch.object(app, 'AUTH_PASS', 's3cret'):
            self.assertEqual(self.client.get('/api/stats').status_code, 401)
            ok = self.client.get('/api/stats', auth=('admin', 's3cret'))
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(self.client.get('/api/stats', auth=('admin', 'nope')).status_code, 401)
            self.assertNotEqual(self.client.get('/healthz').status_code, 401)


if __name__ == '__main__':
    unittest.main()
