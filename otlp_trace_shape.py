#!/usr/bin/env python3
"""Bounded, offline graph checks for one OTLP/JSON trace export request."""

import argparse
import json
import math
import os
import re
import sys

VERSION = '1.0.0'
DEFAULT_BYTES = 10 * 1024 * 1024
DEFAULT_DEPTH = 64
DEFAULT_SPANS = 100_000
HEX = re.compile(r'[0-9a-fA-F]+\Z')
DECIMAL = re.compile(r'[0-9]{1,20}\Z')


class ShapeError(Exception):
    """A stable code; never carries input text or paths."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _configuration(max_bytes, max_depth, max_spans):
    for value, upper in ((max_bytes, 1_073_741_824), (max_depth, 256),
                         (max_spans, 1_000_000)):
        if type(value) is not int or not 1 <= value <= upper:
            raise ShapeError('invalid_configuration')


def _depth_check(text, limit):
    # Scan before the recursive stdlib decoder. Strings/escapes do not add depth.
    depth = 0
    quoted = False
    escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > limit:
                raise ShapeError('depth_limit')
        elif char in ']}':
            depth -= 1


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ShapeError('duplicate_json_key')
        result[key] = value
    return result


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ShapeError('invalid_json')
    return value


def _constant(_text):
    raise ShapeError('invalid_json')


def _object(value):
    if not isinstance(value, dict):
        raise ShapeError('invalid_container')
    return value


def _array(value):
    if not isinstance(value, list):
        raise ShapeError('invalid_container')
    return value


def _metadata(item):
    for name in ('attributes', 'events', 'links'):
        if name in item:
            for entry in _array(item[name]):
                _object(entry)


def _identifier(value, length, code):
    if (not isinstance(value, str) or len(value) != length
            or HEX.fullmatch(value) is None or not any(c != '0' for c in value)):
        raise ShapeError(code)
    return value.lower()


def _timestamp(value):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and DECIMAL.fullmatch(value):
        number = int(value)
    else:
        raise ShapeError('invalid_timestamp')
    if not 0 <= number <= 2**64-1:
        raise ShapeError('invalid_timestamp')
    return number


def analyze_bytes(raw, *, require_parents=False, max_bytes=DEFAULT_BYTES,
                  max_depth=DEFAULT_DEPTH, max_spans=DEFAULT_SPANS):
    """Return counts and indexed findings, or raise ShapeError on invalid input.

    Span indexes are zero-based, in resource/scope/span traversal order.
    No input values, IDs, names, or paths are included in reports.
    """
    _configuration(max_bytes, max_depth, max_spans)
    if len(raw) > max_bytes:
        raise ShapeError('byte_limit')
    try:
        text = raw.decode('utf-8')
        _depth_check(text, max_depth)
        document = json.loads(text, object_pairs_hook=_pairs,
                              parse_constant=_constant, parse_float=_finite_float)
    except (UnicodeError, ValueError, RecursionError):
        raise ShapeError('invalid_json') from None
    _object(document)
    if any(name in document for name in ('spans', 'traces', 'resource_spans')):
        raise ShapeError('unsupported_shape')
    if document and 'resourceSpans' not in document:
        raise ShapeError('unsupported_shape')
    counts = dict(resourceSpans=0, scopeSpans=0, spans=0, uniqueSpans=0,
                  traces=0, roots=0, parentEdges=0, missingParents=0)
    nodes = {}
    findings = []
    information = []
    for resource in _array(document.get('resourceSpans', [])):
        _object(resource)
        counts['resourceSpans'] += 1
        if any(name in resource for name in ('instrumentationLibrarySpans',
                                             'instrumentation_library_spans', 'scope_spans')):
            raise ShapeError('unsupported_shape')
        if 'resource' in resource:
            _metadata(_object(resource['resource']))
        for scope in _array(resource.get('scopeSpans', [])):
            _object(scope)
            counts['scopeSpans'] += 1
            if 'scope' in scope:
                _metadata(_object(scope['scope']))
            for item in _array(scope.get('spans', [])):
                index = counts['spans']
                counts['spans'] += 1
                if counts['spans'] > max_spans:
                    raise ShapeError('span_limit')
                _object(item)
                _metadata(item)
                trace = _identifier(item.get('traceId'), 32, 'invalid_trace_id')
                sid = _identifier(item.get('spanId'), 16, 'invalid_span_id')
                parent = item.get('parentSpanId', '')
                if parent != '':
                    parent = _identifier(parent, 16, 'invalid_parent_id')
                start = _timestamp(item.get('startTimeUnixNano'))
                end = _timestamp(item.get('endTimeUnixNano'))
                key = (trace, sid)
                if start > end:
                    findings.append(dict(code='time_order', spanIndex=index))
                if key in nodes:
                    findings.append(dict(code='duplicate_span', spanIndex=index,
                                         firstSpanIndex=nodes[key][0]))
                else:
                    nodes[key] = (index, (trace, parent) if parent else None)
    counts['uniqueSpans'] = len(nodes)
    counts['traces'] = len({key[0] for key in nodes})
    for key, (index, parent) in nodes.items():
        if parent is None:
            counts['roots'] += 1
        elif parent == key:
            counts['parentEdges'] += 1
            findings.append(dict(code='self_parent', spanIndex=index))
        elif parent in nodes:
            counts['parentEdges'] += 1
        else:
            counts['missingParents'] += 1
            target = findings if require_parents else information
            target.append(dict(code='missing_parent', spanIndex=index))
    # A functional graph (one parent per node) needs only a path map and done set.
    # Each node is completed once; no recursion even for long chains/cycles.
    done = set()
    for key in nodes:
        path = []
        positions = {}
        cursor = key
        while cursor in nodes and cursor not in done:
            if cursor in positions:
                cycle = path[positions[cursor]:]
                if len(cycle) > 1:  # Self-parent already has its specific finding.
                    findings.append(dict(code='parent_cycle',
                        spanIndexes=sorted(nodes[node][0] for node in cycle)))
                break
            positions[cursor] = len(path)
            path.append(cursor)
            cursor = nodes[cursor][1]
        done.update(path)
    if not nodes:
        information.append(dict(code='empty_input'))
    return dict(schemaVersion=1, status='findings' if findings else 'clean',
                counts=counts, findings=findings, information=information)


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ShapeError('invalid_cli')


def _parser():
    parser = _Parser(description=__doc__)
    parser.add_argument('input', nargs='?', default='-', help='UTF-8 JSON file; - for stdin')
    parser.add_argument('--json', action='store_true', help='emit stable JSON')
    parser.add_argument('--require-parents', action='store_true',
                        help='treat missing parents as findings')
    parser.add_argument('--max-bytes', type=int, default=DEFAULT_BYTES,
                        help='input byte limit (default: 10485760, maximum: 1073741824)')
    parser.add_argument('--max-depth', type=int, default=DEFAULT_DEPTH,
                        help='JSON container depth (default: 64, maximum: 256)')
    parser.add_argument('--max-spans', type=int, default=DEFAULT_SPANS,
                        help='span limit (default: 100000, maximum: 1000000)')
    parser.add_argument('--version', action='version', version=VERSION)
    return parser


def _render(report, as_json):
    if as_json:
        return json.dumps(report, sort_keys=True, separators=(',', ':')) + '\n'
    if report['status'] == 'invalid':
        return 'invalid: ' + report['error']['code'] + '\n'
    counts = ' '.join(f'{key}={value}' for key, value in report['counts'].items())
    lines = [report['status'] + ': ' + counts]
    for group in ('findings', 'information'):
        for finding in report[group]:
            details = ' '.join(f'{key}={value}' for key, value in finding.items()
                               if key != 'code')
            lines.append(f"{group}: {finding['code']}" + (' '+details if details else ''))
    return '\n'.join(lines) + '\n'


def main(argv=None):
    args = None
    try:
        args = _parser().parse_args(argv)
        _configuration(args.max_bytes, args.max_depth, args.max_spans)
        try:
            if args.input == '-':
                raw = sys.stdin.buffer.read(args.max_bytes+1)
            else:
                with open(args.input, 'rb') as stream:
                    raw = stream.read(args.max_bytes+1)
        except (OSError, ValueError):
            raise ShapeError('input_io') from None
        report = analyze_bytes(raw, require_parents=args.require_parents,
                               max_bytes=args.max_bytes, max_depth=args.max_depth,
                               max_spans=args.max_spans)
        code = 1 if report['findings'] else 0
    except ShapeError as error:
        report = dict(schemaVersion=1, status='invalid', error=dict(code=error.code))
        code = 2
    as_json = args.json if args else '--json' in (argv if argv is not None else sys.argv[1:])
    sys.stdout.write(_render(report, as_json))
    sys.stdout.flush()
    return code


def _entrypoint():
    try:
        try:
            return main()
        except SystemExit as exit_request:  # argparse help/version also need a checked flush.
            sys.stdout.flush()
            return exit_request.code
    except OSError:
        # Replace stdout's descriptor before interpreter shutdown to avoid a second
        # implicit-flush traceback. This does not spawn a process or access a network.
        try:
            with open(os.devnull, 'w') as sink:
                os.dup2(sink.fileno(), sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        try:
            sys.stderr.write('output_io\n')
            sys.stderr.flush()
        except OSError:
            pass
        return 2


if __name__ == '__main__':
    sys.exit(_entrypoint())
