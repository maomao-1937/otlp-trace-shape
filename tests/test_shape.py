import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
T = 'a' * 32
U = 'b' * 32


def span(number=1, parent=None, trace=T, **extra):
    result = dict(traceId=trace, spanId=f'{number:016x}',
                  startTimeUnixNano='10', endTimeUnixNano='20')
    if parent is not None:
        result['parentSpanId'] = f'{parent:016x}' if isinstance(parent, int) else parent
    result.update(extra)
    return result


def request(*spans):
    return {'resourceSpans': [{'scopeSpans': [{'spans': list(spans)}]}]}


class ShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A missing production module is the first real RED condition.
        cls.module = __import__('otlp_trace_shape')

    def analyze(self, document, **options):
        return self.module.analyze_bytes(json.dumps(document).encode(), **options)

    def invalid(self, document, code, **options):
        with self.assertRaises(self.module.ShapeError) as context:
            self.analyze(document, **options)
        self.assertEqual(context.exception.code, code)

    def codes(self, report, key='findings'):
        return [item['code'] for item in report[key]]

    def test_empty_reports_zero_evidence(self):
        result = self.analyze({})
        self.assertEqual(result['status'], 'clean')
        self.assertEqual(result['counts']['spans'], 0)
        self.assertEqual(result['counts']['traces'], 0)
        self.assertEqual(self.codes(result, 'information'), ['empty_input'])

    def test_parent_child_across_resources(self):
        document = request(span())
        document['resourceSpans'].extend(request(span(2, 1))['resourceSpans'])
        result = self.analyze(document)
        self.assertEqual(result['counts']['parentEdges'], 1)
        self.assertEqual(result['counts']['roots'], 1)
        self.assertEqual(result['counts']['resourceSpans'], 2)

    def test_case_normalization_detects_duplicate(self):
        result = self.analyze(request(span(), span(trace=T.upper())))
        self.assertEqual(self.codes(result), ['duplicate_span'])
        self.assertEqual(result['counts']['uniqueSpans'], 1)

    def test_same_span_id_in_different_traces_is_legal(self):
        result = self.analyze(request(span(), span(trace=U)))
        self.assertEqual(result['status'], 'clean')
        self.assertEqual(result['counts']['traces'], 2)

    def test_missing_parent_is_information(self):
        result = self.analyze(request(span(2, 1)))
        self.assertEqual(result['status'], 'clean')
        self.assertEqual(self.codes(result, 'information'), ['missing_parent'])
        self.assertEqual(result['counts']['missingParents'], 1)

    def test_missing_parent_strict_policy(self):
        self.assertEqual(self.codes(self.analyze(request(span(2, 1)), require_parents=True)),
                         ['missing_parent'])

    def test_parent_in_other_trace_does_not_resolve(self):
        result = self.analyze(request(span(trace=U), span(2, 1)))
        self.assertEqual(result['counts']['missingParents'], 1)

    def test_empty_parent_is_root(self):
        self.assertEqual(self.analyze(request(span(parent='')))['counts']['roots'], 1)

    def test_zero_parent_is_invalid_not_root(self):
        self.invalid(request(span(parent='0' * 16)), 'invalid_parent_id')

    def test_self_parent(self):
        self.assertEqual(self.codes(self.analyze(request(span(1, 1)))), ['self_parent'])

    def test_cycle_and_tail(self):
        result = self.analyze(request(span(1, 2), span(2, 1), span(3, 1)))
        self.assertEqual(self.codes(result), ['parent_cycle'])
        self.assertEqual(result['findings'][0]['spanIndexes'], [0, 1])

    def test_disjoint_cycles(self):
        result = self.analyze(request(span(1, 2), span(2, 1), span(3, 4), span(4, 3)))
        self.assertEqual(self.codes(result), ['parent_cycle', 'parent_cycle'])

    def test_deep_graph_does_not_recurse(self):
        result = self.analyze(request(*(span(i, i-1 if i > 1 else None)
                                        for i in range(1, 3001))))
        self.assertEqual(result['counts']['parentEdges'], 2999)
        self.assertEqual(result['status'], 'clean')

    def test_parent_time_containment_is_not_required(self):
        result = self.analyze(request(span(), span(2, 1, startTimeUnixNano='1',
                                                    endTimeUnixNano='99')))
        self.assertEqual(result['status'], 'clean')

    def test_reversed_time_is_finding(self):
        self.assertEqual(self.codes(self.analyze(request(span(startTimeUnixNano='21')))),
                         ['time_order'])

    def test_uint64_boundary_and_integer_timestamp(self):
        result = self.analyze(request(span(startTimeUnixNano=0,
                                          endTimeUnixNano=str(2**64-1))))
        self.assertEqual(result['status'], 'clean')

    def test_invalid_timestamps(self):
        for value in (True, None, -1, 1.0, '1.0', '+1', ' 1', '1e2', 2**64,
                      str(2**64), '1' * 5000):
            with self.subTest(value=str(value)[:40]):
                self.invalid(request(span(startTimeUnixNano=value)), 'invalid_timestamp')

    def test_missing_timestamp(self):
        item = span()
        del item['endTimeUnixNano']
        self.invalid(request(item), 'invalid_timestamp')

    def test_bad_ids(self):
        for field, code, values in (
            ('traceId', 'invalid_trace_id', ['', '0'*32, 'z'*32, 'a'*31, None, 7]),
            ('spanId', 'invalid_span_id', ['', '0'*16, 'g'*16, 'a'*15, None, 7]),
            ('parentSpanId', 'invalid_parent_id', ['a'*15, None, 7])):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.invalid(request(span(**{field: value})), code)

    def test_malformed_structural_containers(self):
        for document in ([], None, {'resourceSpans': None}, {'resourceSpans': {}},
                         {'resourceSpans': [None]}, {'resourceSpans': [{'scopeSpans': {}}]},
                         {'resourceSpans': [{'scopeSpans': [None]}]},
                         {'resourceSpans': [{'scopeSpans': [{'spans': {}}]}]},
                         request(None)):
            with self.subTest(document=document):
                self.invalid(document, 'invalid_container')

    def test_malformed_metadata_containers(self):
        for path, value in [('resource', []), ('scope', []), ('attributes', {})]:
            document = request(span())
            if path == 'resource':
                document['resourceSpans'][0][path] = value
            elif path == 'scope':
                document['resourceSpans'][0]['scopeSpans'][0][path] = value
            else:
                document['resourceSpans'][0]['scopeSpans'][0]['spans'][0][path] = value
            self.invalid(document, 'invalid_container')

    def test_empty_repeated_fields_are_supported(self):
        for document in ({'resourceSpans': []}, {'resourceSpans': [{}]},
                         {'resourceSpans': [{'scopeSpans': [{}]}]}):
            self.assertEqual(self.analyze(document)['counts']['spans'], 0)

    def test_unsupported_legacy_and_flat(self):
        for document in ({'spans': []}, {'traces': []}, {'resource_spans': []},
                         {'resourceSpans': [{'instrumentationLibrarySpans': []}]}):
            self.invalid(document, 'unsupported_shape')

    def test_snake_case_wrappers_are_not_silent_empty_evidence(self):
        self.invalid({'resourceSpans': [{'scope_spans': []}]}, 'unsupported_shape')
        self.invalid({'resourceSpans': [{'instrumentation_library_spans': []}]},
                     'unsupported_shape')

    def test_duplicate_json_keys_at_any_depth(self):
        for raw in (b'{"resourceSpans":[],"resourceSpans":[]}',
                    b'{"resourceSpans":[],"ignored":{"secret":1,"secret":2}}'):
            with self.assertRaises(self.module.ShapeError) as context:
                self.module.analyze_bytes(raw)
            self.assertEqual(context.exception.code, 'duplicate_json_key')

    def test_nonfinite_rejected_even_in_ignored_data(self):
        for token in ('NaN', 'Infinity', '-Infinity', '1e999'):
            with self.assertRaises(self.module.ShapeError) as context:
                self.module.analyze_bytes(('{"resourceSpans":[],"x":'+token+'}').encode())
            self.assertEqual(context.exception.code, 'invalid_json')

    def test_bad_encoding_json_and_jsonl(self):
        for raw in (b'\xff', b'{', b'{}\n{}', b'\x00', b'{"secret":\n}'):
            with self.assertRaises(self.module.ShapeError) as context:
                self.module.analyze_bytes(raw)
            self.assertEqual(context.exception.code, 'invalid_json')

    def test_byte_limit_boundary(self):
        self.assertEqual(self.module.analyze_bytes(b'{}', max_bytes=2)['status'], 'clean')
        with self.assertRaises(self.module.ShapeError) as context:
            self.module.analyze_bytes(b'{} ', max_bytes=2)
        self.assertEqual(context.exception.code, 'byte_limit')

    def test_depth_limit_and_brackets_in_strings(self):
        self.analyze({'resourceSpans': [], 'x': '[{\\"}]'}, max_depth=2)
        self.invalid({'resourceSpans': [], 'x': [[[]]]}, 'depth_limit', max_depth=3)
        with self.assertRaises(self.module.ShapeError) as context:
            self.module.analyze_bytes(('['*2000+']'*2000).encode())
        self.assertEqual(context.exception.code, 'depth_limit')

    def test_span_limit(self):
        self.analyze(request(span()), max_spans=1)
        self.invalid(request(span(), span(2)), 'span_limit', max_spans=1)

    def test_no_payload_values_or_ids_in_report(self):
        item = span(2, 1, name='SECRET_NAME', attributes=[{'key': 'SECRET_KEY',
                    'value': {'stringValue': 'SECRET_VALUE'}}])
        result = json.dumps(self.analyze(request(item), require_parents=True))
        for secret in ('SECRET_', T, '0000000000000002'):
            self.assertNotIn(secret, result)


class CliTests(unittest.TestCase):
    def run_cli(self, *args, data=None):
        return subprocess.run([sys.executable, str(ROOT/'otlp_trace_shape.py'), *args],
                              input=data, capture_output=True, timeout=15)

    def test_stdin_json_and_deterministic_output(self):
        raw = json.dumps(request(span(2, 1))).encode()
        first = self.run_cli('-', '--json', data=raw)
        second = self.run_cli('-', '--json', data=raw)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(json.loads(first.stdout)['counts']['spans'], 1)

    def test_graph_finding_exit_one(self):
        result = self.run_cli('-', '--json', '--require-parents',
                              data=json.dumps(request(span(2, 1))).encode())
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['status'], 'findings')

    def test_invalid_json_exit_two_no_payload_echo(self):
        result = self.run_cli('-', '--json', data=b'{"SECRET_VALUE":')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_json')
        self.assertNotIn(b'SECRET', result.stdout+result.stderr)

    def test_file_human_output(self):
        result = self.run_cli(str(ROOT/'examples/clean.json'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'spans=2', result.stdout)
        self.assertNotIn(b'traceId', result.stdout)

    def test_unreadable_file_hides_path(self):
        result = self.run_cli('SECRET_PATH_DOES_NOT_EXIST', '--json')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'input_io')
        self.assertNotIn(b'SECRET', result.stdout+result.stderr)

    def test_invalid_cli_options_hide_value(self):
        for args in (('--SECRET_OPTION',), ('--max-depth', 'SECRET'),
                     ('--max-spans', '0'), ('--max-depth', '257'),
                     ('--max-bytes', '-1')):
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(b'SECRET', result.stderr+result.stdout)

    def test_cli_bounded_read_and_span_policy(self):
        for args, code in ((['--max-bytes', '1'], 'byte_limit'),
                           (['--max-spans', '1'], 'span_limit'),
                           (['--max-depth', '1'], 'depth_limit')):
            result = self.run_cli('examples/clean.json', '--json', *args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['error']['code'], code)

    def test_help_and_broken_pipe_flush(self):
        result = self.run_cli('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'--require-parents', result.stdout)
        for args in (['--help'], ['examples/clean.json', '--json']):
            process = subprocess.Popen([sys.executable, 'otlp_trace_shape.py', *args],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            process.stdout.close()
            stderr = process.stderr.read()
            process.wait(timeout=15)
            self.assertEqual(process.returncode, 2, stderr)
            self.assertNotIn(b'Traceback', stderr)
            self.assertNotIn(b'Exception ignored', stderr)
            self.assertIn(b'output_io', stderr)
            process.stderr.close()


if __name__ == '__main__':
    unittest.main()
