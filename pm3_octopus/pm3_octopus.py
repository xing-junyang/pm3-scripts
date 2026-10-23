#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Proxmark3 Octopus FeliCa read-only balance viewer (EN / JA).

Publicly documented Octopus FeliCa balance service: PM3 --scl 1701
(which is the on-wire byte order of numerical service code 0x0117).

This tool does NOT claim to read transaction history from the card.
If provided, an external CSV of legitimate historical balances can be shown
as a last-five-entries table and an ASCII line chart.
"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date as CalendarDate
import unicodedata

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
REQ_RE = re.compile(r"Send\s+raw\s+command\s*-\s*Frame:\s*(.+)", re.I)
RAW_RE = re.compile(r"\[\+\]\s*\(\s*\d+\s*\)\s*((?:[0-9a-fA-F]{2}(?:\s+|$)){8,})")
IDM_RE = re.compile(r"\bIDm\b[^\r\n]*?\b([0-9a-fA-F]{16})\b", re.I)
PMM_RE = re.compile(r"\bPMm\b[^\r\n]*?\b([0-9a-fA-F]{16})\b", re.I)
BYTE_RE = re.compile(r"\b[0-9a-fA-F]{2}\b")
SERVICE_RE = re.compile(r"\bSVC_([0-9A-Fa-f]{4})\b")

LABEL = {
    'en': {
        'heading': 'PM3 Octopus / FeliCa | Read-only',
        'card': 'Card information', 'idm': 'IDm', 'pmm': 'PMm',
        'platform': 'Card platform', 'apple_wallet': 'Apple Wallet / Mobile FeliCa',
        'system': 'System Code', 'service': 'Balance service',
        'not_observed': 'Not confirmed by reader output',
        'detected': '8008 detected', 'balance': 'Card balance',
        'balance_error': 'Not available', 'balance_data': 'Raw block 0',
        'offset': 'Balance offset', 'offset_note': '500 after 2017; try 350 for older cards',
        'validate': 'Verify the calculated balance in the official Octopus App.',
        'history': 'Last 5 transactions (external CSV)',
        'no_history': 'Not available via this PM3 reading. Provide --history-csv for a separately obtained history.',
        'chart': 'Balance trend | oldest to newest',
        'date': 'Date', 'description': 'Description', 'amount': 'Change',
        'remaining': 'Balance', 'unknown': 'Unknown',
        'note': 'CSV values are user-supplied; not extracted from Octopus card.',
        'protected': 'Discovery returned no readable services or may be unsupported by this card.',
        'services': 'Discovered service codes',
        'mismatch': 'CSV latest balance differs from card balance; check chronology and freshness.',
        'help': 'Inspect an Octopus card using PM3, then optionally plot a CSV of historical balances.',
    },
    'ja': {
        'heading': 'PM3 オクトパス / FeliCa | 読み取り専用',
        'card': 'カード基本情報', 'idm': 'IDm', 'pmm': 'PMm',
        'platform': 'カード種別', 'apple_wallet': 'Apple Wallet / モバイルFeliCa',
        'system': 'システムコード', 'service': '残高サービス',
        'not_observed': 'カード応答から未確認',
        'detected': '8008 を検出', 'balance': 'カード残高',
        'balance_error': '取得できません', 'balance_data': 'ブロック0生データ',
        'offset': '残高補正値', 'offset_note': '2017年以降は500、旧カードでは350の可能性',
        'validate': '残高は公式 Octopus アプリで照合してください。',
        'history': '直近5件の取引履歴（外部CSV）',
        'no_history': 'このPM3読み取りでは取得できません。外部の履歴は --history-csv で指定できます。',
        'chart': '残高推移 | 古い順 → 新しい順',
        'date': '日付', 'description': '内容', 'amount': '増減額',
        'remaining': '残高', 'unknown': '不明',
        'note': 'CSVは利用者が入力した履歴であり、カードから取得したものではありません。',
        'protected': 'サービス未検出またはカードが探索に未対応です。',
        'services': '検出したサービス',
        'mismatch': 'CSV最新残高とカード残高が異なります。日付・更新状況を確認してください。',
        'help': 'PM3で八達通の公開残高を読み取り、任意のCSV履歴を折れ線グラフで表示します。',
    },
}


def tr(lang: str, key: str) -> str:
    return LABEL[lang][key]


def compact_hex(s: str) -> bytes:
    return bytes.fromhex(' '.join(BYTE_RE.findall(s)))


@dataclass
class BalanceRead:
    idm: str | None = None
    raw: bytes | None = None
    flags: str | None = None
    error: str | None = None


def parse_log(log: str) -> tuple[str | None, str | None, bool, list[str], BalanceRead, bool]:
    clean = ANSI_RE.sub('', log)
    idm = None
    pmm = None
    mi = IDM_RE.search(clean)
    if mi:
        idm = mi.group(1).upper()
    # May be formatted with spaces like `IDm: 01 02 ...`.
    for line in clean.splitlines():
        if 'idm' in line.lower() and idm is None:
            h = compact_hex(line.split('IDm')[-1])
            if len(h) >= 8:
                idm = h[:8].hex().upper()
        if 'pmm' in line.lower() and pmm is None:
            h = compact_hex(re.split('PMm', line, flags=re.I)[-1])
            if len(h) >= 8:
                pmm = h[:8].hex().upper()
    pm = PMM_RE.search(clean)
    if pm:
        pmm = pm.group(1).upper()

    # Only test for 8008 when used as a system field; don't infer from an IDm.
    system_8008 = any(
        ('8008' in re.sub(r'[^0-9A-Fa-f]', '', line).upper() or re.search(r'\b80\s+08\b', line, re.I))
        and re.search(r'system|syscode', line, re.I)
        for line in clean.splitlines()
    )
    services = sorted({s.upper() for s in SERVICE_RE.findall(clean)})

    pending = None
    result = BalanceRead()
    for line in clean.splitlines():
        req = REQ_RE.search(line)
        if req:
            data = compact_hex(req.group(1))
            # 06 + 8byte IDm + 01 + 2byte service + 01 + 2byte BLE.
            if len(data) >= 15 and data[0] == 6 and data[9] == 1 and data[10:12] == bytes.fromhex('1701') and data[12] == 1 and data[13:15] == bytes.fromhex('8000'):
                pending = data[1:9]
                result = BalanceRead(idm=pending.hex().upper(), error='No matching card response')
            else:
                pending = None
            continue
        if pending is None:
            continue
        response = RAW_RE.search(line)
        if response is None:
            continue
        r = compact_hex(response.group(1))
        if len(r) < 16 or r[:2] != bytes.fromhex('B2 4D') or r[3] != 7:
            result.error = 'Unexpected response header'
        elif r[4:12] != pending:
            result.error = 'Response IDm mismatch'
        elif r[2] + 4 != len(r):
            result.error = 'Response length mismatch'
        else:
            result.flags = f'{r[12]:02X} {r[13]:02X}'
            if r[12:14] != b'\x00\x00':
                result.error = 'Card rejected read (status ' + result.flags + ')'
            elif len(r) != 33 or r[14] != 1:
                result.error = 'Expected one 16-byte block'
            else:
                result.raw = r[15:31]
                result.error = None
        pending = None
    is_apple_wallet = bool(re.search(r'Mobile\s+FeliCa\s+for\s+Apple\s+Wallet', clean, re.I))
    return idm or result.idm, pmm, system_8008, services, result, is_apple_wallet


def hk(cents: int) -> str:
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return f'{sign}HK${cents // 100:,}.{cents % 100:02d}'


def hk_change(cents: int) -> str:
    return ('+' if cents > 0 else '') + hk(cents)


def visual_width(text: str) -> int:
    # Japanese full-width glyphs occupy two columns in most CLI fonts.
    return sum(2 if unicodedata.east_asian_width(c) in 'FW' else 1 for c in text)


def column(text: str, width: int, *, right: bool = False) -> str:
    pad = ' ' * max(0, width - visual_width(text))
    return pad + text if right else text + pad


def balance_cents(raw: bytes, offset: int) -> int:
    # Public Octopus balance service: 32-bit big-endian, in tenths of HKD,
    # with an additive raw offset (500 on post-2017 cards; 350 on older ones).
    return (int.from_bytes(raw[:4], 'big') - offset) * 10


@dataclass
class Entry:
    date: str
    description: str
    cents: int


def load_csv(path: Path) -> list[Entry]:
    result = []
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {'date', 'balance'}.issubset(set(reader.fieldnames)):
            raise ValueError('CSV needs columns: date,balance (optional: description)')
        for item in reader:
            date = (item.get('date') or '').strip()
            amount = (item.get('balance') or '').strip().replace('HK$', '').replace(',', '')
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
                raise ValueError('CSV date must be YYYY-MM-DD')
            try:
                cents_dec = Decimal(amount) * 100
                if not cents_dec.is_finite() or cents_dec != cents_dec.to_integral_value():
                    raise ValueError('Balance needs at most 2 decimal places')
                cents = int(cents_dec)
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f'Invalid balance {amount!r}') from exc
            result.append(Entry(date, (item.get('description') or '').strip(), cents))
    # Transaction time is not required. Preserve CSV order for same-day rows.
    # Reject decreasing dates rather than drawing a misleading chronological chart.
    previous = None
    for entry in result:
        try:
            day = CalendarDate.fromisoformat(entry.date)
        except ValueError as exc:
            raise ValueError('CSV date must be a valid YYYY-MM-DD date') from exc
        if previous is not None and day < previous:
            raise ValueError('CSV must be in oldest-to-newest order')
        previous = day
    return result[-5:]


def graph(points: list[Entry]) -> str:
    if not points:
        return ''
    spacing = 13
    width = max(1, (len(points) - 1) * spacing + 1)
    height = 9
    lo, hi = min(p.cents for p in points), max(p.cents for p in points)
    def yval(v: int) -> int:
        return height // 2 if hi == lo else round((hi - v) * (height - 1) / (hi - lo))
    coords = [(i * spacing, yval(p.cents)) for i, p in enumerate(points)]
    screen = [[' ' for _ in range(width)] for _ in range(height)]
    for i in range(1, len(coords)):
        x0, y0 = coords[i - 1]
        x1, y1 = coords[i]
        for x in range(x0 + 1, x1):
            y = round(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
            screen[y][x] = '/' if y < y0 else '\\' if y > y0 else '-'
    for x, y in coords:
        screen[y][x] = '*'
    lines = []
    for y, line in enumerate(screen):
        label = hk(round(hi - y * (hi - lo) / (height - 1))) if y in (0, height // 2, height - 1) else ''
        lines.append(f' {label:>13} |' + ''.join(line))
    lines.append(' ' + ' ' * 13 + ' +' + '-' * width + '>')
    dates = [' ' for _ in range(width + 9)]
    for (x, _), point in zip(coords, points):
        name = point.date[5:]
        for j, char in enumerate(name):
            if x + j < len(dates):
                dates[x + j] = char
    lines.append(' ' * 17 + ''.join(dates).rstrip())
    return '\n'.join(lines)


def report(log: str, args: argparse.Namespace) -> int:
    t = LABEL[args.lang]
    idm, pmm, confirmed, services, reading, is_apple_wallet = parse_log(log)
    print('=' * 68)
    print(' ' + t['heading'])
    print('=' * 68)
    print('\n[' + t['card'] + ']')
    print(f" {column(t['idm'], 22)}: {idm or t['unknown']}")
    print(f" {column(t['pmm'], 22)}: {pmm or t['unknown']}")
    if is_apple_wallet:
        print(f" {column(t['platform'], 22)}: {t['apple_wallet']}")
    print(f" {column(t['system'], 22)}: {t['detected'] if confirmed else t['not_observed']}")
    print(f" {column(t['service'], 22)}: 1701 (numeric 0x0117)")
    if args.discover:
        print(f" {column(t['services'], 22)}: {', '.join(services[:30]) if services else t['protected']}")
    calculated = None
    print('\n[' + t['balance'] + ']')
    if reading.raw is not None:
        calculated = balance_cents(reading.raw, args.offset)
        print(f' {hk(calculated)}')
        print(f" {t['balance_data']}: {reading.raw.hex(' ').upper()}")
        print(f" {t['offset']}: {args.offset} ({t['offset_note']})")
        print(' ' + t['validate'])
    else:
        print(f" {t['balance_error']}: {reading.error or t['unknown']}")
    print('\n[' + t['history'] + ']')
    if not args.history_csv:
        print(' ' + t['no_history'])
    else:
        try:
            rows = load_csv(args.history_csv)
        except (OSError, ValueError) as exc:
            print(' CSV error: ' + str(exc), file=sys.stderr)
            return 2
        print(' ' + '  '.join((column(t['date'], 10), column(t['description'], 20),
                               column(t['remaining'], 12, right=True), column(t['amount'], 13, right=True))))
        print(' ' + '-' * 63)
        for i, e in enumerate(reversed(rows)):
            actual = len(rows) - i - 1
            old = rows[actual - 1].cents if actual > 0 else None
            change = hk_change(e.cents - old) if old is not None else '--'
            print(' ' + '  '.join((column(e.date, 10), column(e.description[:18], 20),
                                   column(hk(e.cents), 12, right=True), column(change, 13, right=True))))
        print('\n[' + t['chart'] + ']')
        print(graph(rows))
        print(' ' + t['note'])
        if calculated is not None and rows and rows[-1].cents != calculated:
            print(' ! ' + t['mismatch'])
    if args.raw:
        print('\n[PM3 RAW]\n' + ANSI_RE.sub('', log))
    return 0 if reading.raw is not None or args.history_csv or args.demo else 1


def demo_log() -> str:
    idm = bytes.fromhex('0102030405060708')
    pmm = '01 16 8B 86 8F BE CB FF'
    # Synthetic data with the same known raw balance value as the user-verified
    # HK$100 Octopus example; do not include the user's actual card identifier.
    payload = (1500).to_bytes(4, 'big') + bytes(12)
    request = bytes([6]) + idm + bytes.fromhex('01 17 01 01 80 00')
    response = bytes.fromhex('B2 4D 1D 07') + idm + bytes([0, 0, 1]) + payload + bytes([0, 0])
    return ('[=] IDm: ' + idm.hex().upper() + '\n' +
            '[=] PMm: ' + pmm + '\n' +
            '[=] IC code...... 0116 ( Mobile FeliCa for Apple Wallet )\n' +
            '[=] System Code: 8008\n' +
            '[=] Send raw command - Frame: ' + request.hex(' ').upper() + '\n' +
            '[+] (33) ' + response.hex(' ').upper() + '\n')


def main() -> int:
    argv = sys.argv[1:]
    language = 'ja' if '--lang=ja' in argv or ('--lang' in argv and argv.index('--lang') + 1 < len(argv) and argv[argv.index('--lang') + 1] == 'ja') else 'en'
    p = argparse.ArgumentParser(description=LABEL[language]['help'])
    p.add_argument('--lang', choices=('en', 'ja'), default='en')
    p.add_argument('--pm3', default='pm3', help='Path to Proxmark3 client')
    p.add_argument('--port', help='PM3 serial port, e.g. /dev/ttyACM0')
    p.add_argument('--offset', choices=(350, 500), type=int, default=500, help='Stored balance adjustment: 500 (default) or 350 (legacy)')
    p.add_argument('--discover', action='store_true', help='Also run service discovery (may be unsupported)')
    p.add_argument('--from-log', type=Path, help='Read a captured PM3 transcript instead of contacting hardware')
    p.add_argument('--history-csv', type=Path, help='Optional CSV: date,description,balance, oldest first')
    p.add_argument('--save-log', type=Path, help='Save raw PM3 console output (may contain card IDm)')
    p.add_argument('--raw', action='store_true', help='Print complete PM3 output')
    p.add_argument('--demo', action='store_true', help='Synthetic demo; no hardware needed')
    p.add_argument('--timeout', type=int, default=120)
    a = p.parse_args()
    if a.demo:
        output = demo_log()
    elif a.from_log:
        try:
            output = a.from_log.read_text(encoding='utf-8', errors='replace')
        except OSError as exc:
            p.error(str(exc))
    else:
        steps = ['hf search', 'hf felica info', 'hf felica rqsyscode',
                 'hf felica rdbl --sn 01 --scl 1701 --bn 01 --ble 8000']
        if a.discover:
            steps.append('hf felica discnodes')
        cmd = [a.pm3]
        if a.port:
            cmd += ['-p', a.port]
        cmd += ['-c', ';'.join(steps)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=a.timeout)
        except FileNotFoundError:
            p.error(f'PM3 client executable not found: {a.pm3!r}')
        except subprocess.TimeoutExpired:
            p.error(f'PM3 timed out after {a.timeout}s')
        output = proc.stdout + '\n' + proc.stderr
        if proc.returncode:
            print(f'Warning: PM3 returned exit status {proc.returncode}', file=sys.stderr)
    if a.save_log:
        try:
            a.save_log.write_text(output, encoding='utf-8')
        except OSError as exc:
            p.error(str(exc))
    return report(output, a)


if __name__ == '__main__':
    sys.exit(main())
