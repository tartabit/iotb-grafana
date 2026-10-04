"""Dashboard contracts and optional real PromQL regression checks.

Run: python -m unittest discover -s tests -v
Set PROMTOOL to a promtool executable to also evaluate synthetic metrics.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('overview', 'list', 'single')
KEYS = 'accountId, triggerId'


def dashboards():
    return {name: json.loads((ROOT / 'library/dashboards' /
                             f'iotbridge-triggers-{name}.json').read_text())['dashboard']
            for name in NAMES}


def expand(expr):
    return (expr.replace('${accountId:regex}', '.*').replace('${triggerId:regex}', '.*')
            .replace('$__rate_interval', '5m').replace('$__range', '5m'))


def fixture_series(decimal_bounds=False):
    """Different execution weights, duplicate names/IDs, absent mapping, idle."""
    series = []

    def add(name, labels, delta, initial=0):
        labeltext = ','.join(f'{k}="{v}"' for k, v in labels.items())
        series.append({'series': f'{name}{{{labeltext}}}', 'values': f'{initial}+{delta}x5'})

    for account, trigger, count, ops, duration in (
        ('a', 't', 10, 100, 20), ('a', 'u', 2, 1000, 20000),
        ('b', 't', 1, 600000, 30000), ('b', 'idle', 0, 100, 10),
    ):
        labels = dict(accountId=account, triggerId=trigger, pod='core-trigger-test')
        for metric, value, buckets in (
            ('execcount', ops, [10,50,100,250,500,750,1000,2000,5000,10000,20000,50000,100000,250000,500000]),
            ('exectime', duration, [10,50,100,250,500,750,1000,2000,5000,10000,20000]),
        ):
            prefix = 'iotbridge_trigger_engine_' + metric
            add(prefix + '_count', labels, count)
            add(prefix + '_sum', labels, count * value)
            for bound in buckets + ['+Inf']:
                label = f'{bound}.0' if decimal_bounds and bound != '+Inf' else bound
                add(prefix + '_bucket', dict(labels, le=label), count if bound == '+Inf' or value <= bound else 0)
        add('iotbridge_trigger_engine_errors', dict(labels, error='none'), count)
    # Replicated mapping must neither multiply values nor fail a many-to-many join.
    for replica in ('one', 'two'):
        add('iotbridge_account_map', dict(accountId='a', accountName='test account', instance=replica), 0, 1)
        for trigger in ('t', 'u'):
            add('iotbridge_trigger_map', dict(accountId='a', triggerId=trigger, accountName='test account', triggerName='same name', instance=replica), 0, 1)
    return series


class DashboardContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = dashboards()

    def test_layout_titles_and_identity(self):
        self.assertEqual(self.d['overview']['uid'], 'FZTjoZ2Sk')
        self.assertEqual(self.d['single']['uid'], 'a97efa86-05fd-4950-adf0-a67806a01efa')
        self.assertEqual(self.d['list']['uid'], 'iotbridge-triggers-list')
        for name, d in self.d.items():
            seen = set()
            for p in d['panels']:
                self.assertEqual(p['title'], p['title'].lower())
                self.assertNotIn(p['id'], seen)
                seen.add(p['id'])
                a = p['gridPos']
                self.assertLessEqual(a['x'] + a['w'], 24)
                for q in d['panels']:
                    if p['id'] >= q['id']:
                        continue
                    b = q['gridPos']
                    overlap = (a['x'] < b['x']+b['w'] and b['x'] < a['x']+a['w']
                               and a['y'] < b['y']+b['h'] and b['y'] < a['y']+a['h'])
                    self.assertFalse(overlap, (name, p['id'], q['id']))

    def test_retains_noise_filters_and_scope_markers(self):
        for name in ('overview', 'single'):
            panels = {p['id']: p for p in self.d[name]['panels']}
            for id, threshold in ((23, 1), (41, 10), (28, 200)):
                self.assertRegex(panels[id]['targets'][0]['expr'], rf'>\s*{threshold}$')
            for id, bound in ((39, 500000), (40, 20000)):
                self.assertIn(f'le=~"{bound}([.]0+)?"', panels[id]['targets'][0]['expr'])
                self.assertTrue(panels[id]['targets'][0]['instant'])
            self.assertIn('topk(20,', panels[7]['targets'][0]['expr'])
        self.assertEqual({p['id'] for p in self.d['single']['panels'] if p['title'].startswith('(x) ')}, {2,3,7})

    def test_table_parity_sort_and_drilldown(self):
        tables = [next(p for p in self.d[n]['panels'] if p['type']=='table') for n in ('list','single')]
        self.assertEqual(tables[0]['targets'], tables[1]['targets'])
        for p in tables:
            self.assertEqual(p['options']['sortBy'], [{'displayName':'total operations','desc':True}])
            self.assertTrue(p['options']['enablePagination'])
            self.assertEqual(p['transformations'][0]['options']['byField'], 'rowKey')
            self.assertTrue(all(t['instant'] and not t['range'] for t in p['targets']))
            for identity in ('accountId', 'triggerId'):
                override = next(o for o in p['fieldConfig']['overrides'] if o['matcher']['options']==identity)
                self.assertIn({'id':'custom.hideFrom.viz','value':True}, override['properties'])
            link = next(o for o in p['fieldConfig']['overrides'] if o['matcher']['options']=='trigger')['properties'][0]['value'][0]['url']
            for part in ('var-accountId=${__data.fields.accountId}', 'var-triggerId=${__data.fields.triggerId}', 'from=${__from}', 'to=${__to}'):
                self.assertIn(part, link)

    def test_percentages_keep_fixed_membership_and_other(self):
        for p in self.d['overview']['panels']:
            if p['id'] not in (43,44):
                continue
            self.assertIn('topk(50,', p['targets'][0]['expr'])
            self.assertIn('@ end()', p['targets'][0]['expr'])
            self.assertEqual(p['targets'][1]['legendFormat'], 'other')
            self.assertEqual(p['fieldConfig']['defaults']['unit'], 'percent')
            self.assertEqual(p['fieldConfig']['defaults']['max'], 100)
            self.assertEqual(p['fieldConfig']['defaults']['custom']['drawStyle'], 'line')
            self.assertEqual(p['fieldConfig']['defaults']['custom']['scaleDistribution'], {'type':'linear'})


@unittest.skipUnless(os.environ.get('PROMTOOL'), 'set PROMTOOL for Prometheus query evaluation')
class PromQLRegression(unittest.TestCase):
    def run_promtool(self, command, payload):
        with tempfile.TemporaryDirectory(prefix='trigger-promql-') as directory:
            path = Path(directory) / 'input.json'
            path.write_text(json.dumps(payload), encoding='utf-8')
            result = subprocess.run([os.environ['PROMTOOL'], *command, str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_expressions_parse(self):
        rules = []
        for name,d in dashboards().items():
            for p in d['panels']:
                for t in p.get('targets', []):
                    rules.append({'record':f'check_{len(rules)}','expr':expand(t['expr'])})
            for v in d['templating']['list']:
                query = v['query']['query']
                if query.startswith('query_result('):
                    rules.append({'record':f'check_{len(rules)}','expr':expand(query[len('query_result('):-1])})
        self.run_promtool(['check','rules'], {'groups':[{'name':'dashboards','rules':rules}]})

    def test_table_weighting_overflow_names_and_idle(self):
        table = dashboards()['list']['panels'][0]
        expected = [
            [('a/t',50),('a/u',10),('b/t',5)],
            [('a/t',5000),('a/u',10000),('b/t',3000000)],
            [('a/t',100),('a/u',1000),('b/t',500001)],
            [('a/t',100),('a/u',1000),('b/t',600000)],
            [('a/t',97.5),('a/u',987.5),('b/t',500001)],
            [('a/t',50),('a/u',20000),('b/t',20001)],
            [('a/t',20),('a/u',20000),('b/t',30000)],
            [('a/t',48),('a/u',19500),('b/t',20001)],
        ]
        checks = []
        for i, target in enumerate(table['targets']):
            samples = []
            for key,value in expected[i]:
                labels = dict(rowKey=key)
                if i==0:
                    account,trigger = key.split('/')
                    labels.update(accountId=account, triggerId=trigger,
                                  accountName='test account' if account=='a' else account,
                                  triggerName='same name' if account=='a' else trigger)
                labeltext = ','.join(f'{k}="{v}"' for k,v in sorted(labels.items()))
                samples.append({'labels':'{'+labeltext+'}', 'value':value})
            checks.append({'expr':expand(target['expr']),'eval_time':'5m','exp_samples':samples})
        sd = dashboards()['single']
        summaries = {p['id']:p for p in sd['panels']}
        for id,value in ((50,65),(51,3015000),(52,351000),(53,3015000/65),(54,500001),(55,500001),(56,351000/65),(57,20001),(58,20001),(59,0)):
            checks.append({'expr':expand(summaries[id]['targets'][0]['expr']),'eval_time':'5m','exp_samples':[{'labels':'{}','value':value}]})
        for decimal_bounds in (False, True):
            with self.subTest(decimal_bounds=decimal_bounds):
                self.run_promtool(['test','rules'], {'evaluation_interval':'1m','tests':[{'interval':'1m','input_series':fixture_series(decimal_bounds),'promql_expr_test':checks}]})

    def test_exceeding_thresholds_keep_unmapped_triggers(self):
        checks = []
        for name in ('overview', 'single'):
            panels = {p['id']: p for p in dashboards()[name]['panels']}
            for id in (39, 40):
                checks.append({'expr': expand(panels[id]['targets'][0]['expr']),
                               'eval_time': '5m', 'exp_samples': [{
                                   'labels': '{accountId="b",triggerId="t",accountName="b",triggerName="t"}',
                                   'value': 5}]})
        for decimal_bounds in (False, True):
            with self.subTest(decimal_bounds=decimal_bounds):
                self.run_promtool(['test', 'rules'], {'evaluation_interval': '1m', 'tests': [{
                    'interval': '1m', 'input_series': fixture_series(decimal_bounds),
                    'promql_expr_test': checks}]})

    def test_share_totals_resets_idle_and_top50(self):
        d = dashboards()['overview']
        series = []
        for i in range(60):
            # Each increment is distinct, so top-50 membership has no ties.
            series.append({'series':f'iotbridge_trigger_engine_execcount_sum{{accountId="a{i:02}",triggerId="t",pod="core-trigger-test"}}','values':f'0+{i+1}x5'})
        checks=[]
        for id in (43,44):
            p=next(p for p in d['panels'] if p['id']==id)
            main,other = [expand(t['expr']) for t in p['targets']]
            for expression, value in ((f'count({main})',50),(f'sum({main}) + ({other})',100),(other,100*55/1830)):
                checks.append({'expr':expression,'eval_time':'5m','exp_samples':[{'labels':'{}','value':value}]})
        tests=[{'interval':'1m','input_series':series,'promql_expr_test':checks}]
        # A reset must not produce a negative share; zero work must leave gaps.
        for values, active in [('100 120 0 20 40 60',True),('10+0x5',False)]:
            p=next(p for p in d['panels'] if p['id']==44)
            expressions=[expand(t['expr']) for t in p['targets']]
            checks=[{'expr':f'sum({expressions[0]}) + ({expressions[1]})','eval_time':'5m','exp_samples':[{'labels':'{}','value':100}] if active else []}]
            tests.append({'interval':'1m','input_series':[{'series':'iotbridge_trigger_engine_execcount_sum{accountId="reset",triggerId="t"}','values':values}],'promql_expr_test':checks})
        self.run_promtool(['test','rules'], {'evaluation_interval':'1m','tests':tests})

    def test_missing_statistics_and_failure_denominator(self):
        d = dashboards()
        summaries = {p['id']:p for p in d['single']['panels']}
        failure = expand(summaries[59]['targets'][0]['expr'])
        inputs = [
            {'series':'iotbridge_trigger_engine_errors{accountId="a",triggerId="t",error="none"}','values':'0+9x5'},
            {'series':'iotbridge_trigger_engine_errors{accountId="a",triggerId="t",error="compile-failed"}','values':'0+1x5'},
            {'series':'iotbridge_trigger_engine_errors{accountId="a",triggerId="t",error="panic"}','values':'0+2x5'},
        ]
        checks = [{'expr':failure,'eval_time':'5m','exp_samples':[{'labels':'{}','value':25}]}]
        for id in range(50,59):
            checks.append({'expr':expand(summaries[id]['targets'][0]['expr']),'eval_time':'5m','exp_samples':[]})
        self.run_promtool(['test','rules'], {'evaluation_interval':'1m','tests':[{'interval':'1m','input_series':inputs,'promql_expr_test':checks}]})


if __name__ == '__main__':
    unittest.main()
