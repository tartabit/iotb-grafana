"""Retention dashboard layout and optional real PromQL behavior checks."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = json.loads((ROOT / 'library/dashboards/iotbridge-system-retention.json').read_text())
DASHBOARD = PAYLOAD['dashboard']
PANELS = {p['id']: p for p in DASHBOARD['panels']}


def expand(expr):
    return (expr.replace('${target:regex}', '.*')
            .replace('${rollover_pod:regex}', '.*').replace('$target', '.*'))


def expression(panel_id):
    return expand(PANELS[panel_id]['targets'][0]['expr'])


def series(name, values, target='logs', instance='current', pod=None, **labels):
    labels = dict(target=target, instance=instance, pod=pod or instance, **labels)
    text = ','.join(f'{k}="{v}"' for k, v in labels.items())
    return {'series': f'iotbridge_retention_rollover_{name}{{{text}}}', 'values': values}


def sample(value, instance='current', target='logs'):
    return {'labels': f'{{pod="{instance}",target="{target}"}}', 'value': value}


class DashboardLayout(unittest.TestCase):
    def test_identity_scope_and_layout(self):
        self.assertEqual(DASHBOARD['uid'], 'iotb-system-retention')
        self.assertEqual(PAYLOAD['meta']['folderUid'], 'G6bUnD54k')
        self.assertEqual(DASHBOARD['refresh'], '30s')
        self.assertEqual(len(PANELS), len(DASHBOARD['panels']))
        self.assertTrue(set(range(1, 29)).issubset(PANELS))
        for p in DASHBOARD['panels']:
            a = p['gridPos']
            self.assertLessEqual(a['x'] + a['w'], 24)
            for q in DASHBOARD['panels']:
                if q['id'] <= p['id']:
                    continue
                b = q['gridPos']
                self.assertFalse(a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w']
                                 and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h'],
                                 (p['id'], q['id']))
        for id in range(31, 43):
            for t in PANELS[id]['targets']:
                self.assertIn('${target:regex}', t['expr'])
                self.assertIn('${rollover_pod:regex}', t['expr'])


@unittest.skipUnless(os.environ.get('PROMTOOL'), 'set PROMTOOL for Prometheus query evaluation')
class PromQLBehavior(unittest.TestCase):
    def run_promtool(self, command, payload):
        with tempfile.TemporaryDirectory(prefix='retention-promql-') as directory:
            path = Path(directory) / 'input.json'
            path.write_text(json.dumps(payload), encoding='utf-8')
            result = subprocess.run([os.environ['PROMTOOL'], *command, str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def reporter_series(self, inputs):
        """Every controller publishes duration together with the other gauges."""
        import re
        reporters = {}
        for item in inputs:
            labels = dict(re.findall(r'(\w+)="([^"]*)"', item['series']))
            key = tuple(labels[k] for k in ('target', 'instance', 'pod'))
            reporters[key] = labels
        existing = {item['series'] for item in inputs}
        generated = []
        for (target, instance, pod) in reporters:
            item = series('duration_seconds', '0+60x5', target=target, instance=instance, pod=pod)
            if item['series'] not in existing:
                generated.append(item)
        return generated

    def evaluate(self, inputs, checks):
        self.run_promtool(['test', 'rules'], {'evaluation_interval': '1m', 'tests': [{
            'interval': '1m', 'input_series': inputs + self.reporter_series(inputs),
            'promql_expr_test': [{'expr': expression(id), 'eval_time': '5m',
                                  'exp_samples': expected} for id, expected in checks],
        }]})

    def test_all_queries_parse(self):
        rules = [{'record': f'panel_{p["id"]}_{t["refId"]}', 'expr': expand(t['expr'])}
                 for p in DASHBOARD['panels'] for t in p.get('targets', [])]
        self.run_promtool(['check', 'rules'], {'groups': [{'name': 'retention', 'rules': rules}]})

    def test_drain_rate_reporter_separation_and_idle(self):
        inputs = []
        for instance, values, phase in [('current', '10000-600x5', 'draining'),
                                        ('old', '10000+0x5', 'draining'),
                                        ('growing', '1000+60x5', 'draining'),
                                        ('idle', '5000-600x5', 'idle')]:
            inputs.extend([series('draining_records', values, instance=instance),
                           series('phase', '1+0x5', instance=instance, phase=phase)])
        self.evaluate(inputs, [(36, [sample(10), sample(0, 'old'), sample(-1, 'growing')]),
                               (32, [sample(7000), sample(10000, 'old'),
                                     sample(1300, 'growing'), sample(2000, 'idle')])])

    def test_phases_and_elapsed(self):
        inputs, expected = [], []
        names = ['idle', 'preparing', 'switching', 'draining', 'dropping']
        for i, name in enumerate(names):
            expected.append(sample(i, name))
            inputs.append(series('duration_seconds', '0+60x5', instance=name))
            for phase in names:
                inputs.append(series('phase', f'{int(phase == name)}+0x5', instance=name, phase=phase))
        self.evaluate(inputs, [(31, expected), (40, expected),
                               (33, [sample(300, name) for name in names if name != 'idle'])])

    def test_errors_absent_telemetry_and_counter_reset(self):
        inputs = [series('phase', '1+0x5', phase='draining'),
                  series('phase', '1+0x5', instance='zero', phase='idle'),
                  series('errors_total', '0 1 2 0 1 2', phase='draining')]
        # Four increments despite the restart; the initial zero bounds
        # extrapolation at the beginning of this series.
        self.evaluate(inputs, [(34, [sample(4), sample(0, 'zero')])])
        self.evaluate([], [(31, []), (32, []), (34, []), (36, [])])

    def test_ip_change_continues_one_pod_series(self):
        inputs = []
        for ip, counts, duration, phase, errors in [
            ('10.0.0.1:9090', '10000 9400 8800 _ _ _', '0 60 120 _ _ _',
             '1 1 1 _ _ _', '5 5 5 _ _ _'),
            ('10.0.0.2:9090', '_ _ _ 8200 7600 7000', '_ _ _ 180 240 300',
             '_ _ _ 1 1 1', '_ _ _ 0 1 2'),
        ]:
            labels = dict(instance=ip, pod='core-events-0')
            inputs.extend([series('draining_records', counts, **labels),
                           series('duration_seconds', duration, **labels),
                           series('phase', phase, phase='draining', **labels),
                           series('errors_total', errors, phase='draining', **labels)])
        self.evaluate(inputs, [(31, [sample(3, 'core-events-0')]),
                               (32, [sample(7000, 'core-events-0')]),
                               (33, [sample(300, 'core-events-0')]),
                               (34, [sample(2, 'core-events-0')]),
                               (36, [sample(10, 'core-events-0')])])

    def test_new_ip_phase_wins_over_old_ip_during_lookback(self):
        inputs = [series('duration_seconds', '0 60 120 _ _ _',
                         instance='old-ip', pod='core-events-0'),
                  series('phase', '1 1 1 _ _ _', phase='draining',
                         instance='old-ip', pod='core-events-0'),
                  series('duration_seconds', '_ _ _ 0 0 0',
                         instance='new-ip', pod='core-events-0'),
                  series('phase', '_ _ _ 1 1 1', phase='idle',
                         instance='new-ip', pod='core-events-0')]
        self.evaluate(inputs, [(31, [sample(0, 'core-events-0')]),
                               (40, [sample(0, 'core-events-0')]), (33, []), (36, [])])

    def test_adaptive_metrics_follow_pod_across_ip_change(self):
        inputs = [series('duration_seconds', '0 60 120 _ _ _',
                         instance='old-ip', pod='core-events-0'),
                  series('transfer_limit_records', '900 900 900 _ _ _',
                         instance='old-ip', pod='core-events-0'),
                  series('transfer_duration_seconds', '2 2 2 _ _ _',
                         instance='old-ip', pod='core-events-0'),
                  series('duration_seconds', '_ _ _ 180 240 300',
                         instance='new-ip', pod='core-events-0'),
                  series('transfer_limit_records', '_ _ _ 500 520 540',
                         instance='new-ip', pod='core-events-0'),
                  series('transfer_duration_seconds', '_ _ _ 0.5 0.5 0.5',
                         instance='new-ip', pod='core-events-0')]
        self.evaluate(inputs, [(41, [sample(540, 'core-events-0')]),
                               (42, [sample(0.5, 'core-events-0')])])
        self.evaluate([], [(41, []), (42, [])])


if __name__ == '__main__':
    unittest.main()

