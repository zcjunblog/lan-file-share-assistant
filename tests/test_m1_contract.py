"""Protocol evidence only: synthetic assertions, no server and no user file reads."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from m1_contract import classify, expired, report_errors, request_errors, utc


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads((ROOT/'examples/m1/cases.json').read_text())
        cls.request = json.loads((ROOT/'examples/m1/base-request.json').read_text())
        cls.report = json.loads((ROOT/'examples/m1/base-report.json').read_text())

    def test_request_cases(self):
        for case in self.cases['request_cases']:
            with self.subTest(case=case['name']):
                request = copy.deepcopy(self.request)
                request.update(case['changes'])
                self.assertEqual(not request_errors(request), case['valid'])

    def test_report_cases(self):
        for case in self.cases['report_cases']:
            with self.subTest(case=case['name']):
                report = copy.deepcopy(self.report)
                for check in report['checks']:
                    check.update(case['changes'].get(check['id'], {}))
                self.assertEqual(classify(report['checks']), case['expected'])
                report.update(result=case['expected'], can_start=case['expected']=='supported')
                self.assertEqual(report_errors(report, allow_fixture=True), [])

    def test_deadline_cases(self):
        for case in self.cases['deadline_cases']:
            with self.subTest(case=case['name']):
                self.assertEqual(expired(case['wall_now'], case['mono_now'], case['wall_deadline'], case['mono_deadline']), case['expired'])

    def test_fake_pass_and_tampered_verdict_rejected(self):
        report = copy.deepcopy(self.report)
        report['checks'][0].update(status='unknown', evidence='not_tested', reason_code='host_unconfirmed', remediation=['确认执行位置'])
        self.assertTrue(report_errors(report, allow_fixture=True))

    def test_missing_and_duplicate_checks_rejected(self):
        report = copy.deepcopy(self.report)
        report['checks'].pop()
        self.assertEqual(classify(report['checks']), 'needs_action')
        self.assertTrue(report_errors(report, allow_fixture=True))
        report['checks'].append(copy.deepcopy(report['checks'][0]))
        self.assertTrue(report_errors(report, allow_fixture=True))

    def test_fixture_is_not_production_evidence(self):
        self.assertTrue(report_errors(self.report))

    def test_not_tested_cannot_pass(self):
        report = copy.deepcopy(self.report)
        report['checks'][0]['evidence'] = 'not_tested'
        self.assertTrue(report_errors(report, allow_fixture=True))

    def test_failure_needs_remediation(self):
        report = copy.deepcopy(self.report)
        report.update(result='needs_action', can_start=False)
        report['checks'][4].update(status='fail', reason_code='dependency_missing')
        self.assertTrue(report_errors(report, allow_fixture=True))

    def test_preflight_does_not_publish_or_verify_receiver(self):
        for key, value in [('can_publish', True), ('receiver_status', 'reachable')]:
            report = copy.deepcopy(self.report)
            report[key] = value
            self.assertTrue(report_errors(report, allow_fixture=True))

    def test_report_requires_fresh_time_and_matching_request(self):
        checked = utc(self.report['checked_at'])
        self.assertFalse(report_errors(self.report, allow_fixture=True, now=checked+timedelta(seconds=29), request=self.request))
        for offset in (-1, 30, 31):
            self.assertTrue(report_errors(self.report, allow_fixture=True, now=checked+timedelta(seconds=offset)))
        request = copy.deepcopy(self.request)
        request['ttl_seconds'] = 1200
        self.assertTrue(report_errors(self.report, allow_fixture=True, request=request))

    def test_invalid_time_and_lifetime_rejected(self):
        for value in ('not a timestamp', '2026-11-06Z', '2026-11-06T04:00:30+08:00', '2026-11-06T04:01:00Z'):
            report = copy.deepcopy(self.report)
            report['valid_until'] = value
            self.assertTrue(report_errors(report, allow_fixture=True))

    def test_unknown_top_level_fields_are_rejected(self):
        for key in ('access_token', 'control_token', 'source_path', 'local_ip'):
            report = copy.deepcopy(self.report)
            report[key] = 'not permitted in this report shape'
            self.assertTrue(report_errors(report, allow_fixture=True))


if __name__ == '__main__':
    unittest.main()
