#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Proxmark3 FeliCa history viewer with English/Japanese CLI output.

Runs one Proxmark3 CLI session or parses a saved PM3 log. Reads public FeliCa
blocks; never attempts authentication, card writing, or emulation. Requires
Python 3.10+ and no third-party Python packages.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
HEX_BYTE_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{2}(?![0-9A-Fa-f])")
RAW_RE = re.compile(r"\[\+\]\s*\(\s*\d+\s*\)\s*((?:[0-9A-Fa-f]{2}(?:\s+|$)){8,})")
REQ_RE = re.compile(r"Send\s+raw\s+command\s*-\s*Frame:\s*(.+)", re.I)
IDM_RE = re.compile(r"\bIDm\b\s*[:.=]+\s*((?:[0-9A-Fa-f]{2}\s*){8})", re.I)
PMM_RE = re.compile(r"\bPMm\b\s*[:.=]+\s*((?:[0-9A-Fa-f]{2}\s*){8})", re.I)

TEXT = {
    "en": {
        "title": "PM3 FeliCa | Last 5 transactions and balance trend (read only)",
        "unknown_idm": "Not detected",
        "unknown_pmm": "Not found in output",
        "card_format": "Card format",
        "block_name": "Block",
        "protocol": "Protocol",
        "balance_svc": "Balance service",
        "history_svc": "History service",
        "system_missing": "Not confirmed; run hf felica rqsyscode separately",
        "format_detected": "System Code 0003 found; decoding as Suica/PASMO-style data",
        "format_unconfirmed": "System Code not verified; currency and transaction types are tentative",
        "current_balance": "8B00 balance",
        "unreadable": "Unavailable",
        "history_heading": "Last 5 transactions",
        "history_detail": "Block 0 is newest; only successfully read records are shown",
        "no_history": "No decodable records. Use --raw to inspect PM3 output.",
        "block": "Block",
        "date": "Date",
        "type": "Type",
        "balance": "Balance",
        "change": "Change",
        "seq": "Seq",
        "trend": "Balance trend | Oldest to newest | ASCII line graph",
        "chart_no_data": "No balance records.",
        "chart_y": "Balance ^  (* = actual record; horizontal spacing = record order)",
        "chart_x": "Record order",
        "chart_note": "Note: gaps in block numbers are not connected.",
        "chart_caution": "Y-axis = balance after transaction; verify card format and currency.",
        "summary": "Summary",
        "latest": "Latest record",
        "after_balance": "balance after transaction",
        "balance_check": "8B00 vs. latest record",
        "match": "Match",
        "mismatch": "Mismatch (later activity or incompatible format possible)",
        "missing_count": "Unreadable records",
        "general_note": "0F09 alone cannot establish card type, actual account balance, or currency.",
        "raw_output": "Raw PM3 output",
        "estimated": "Suica-style estimate",
        "cmd_start": "Reading card details, balance block, and last 5 records. Keep card on antenna.",
        "cmd_nonzero": "PM3 exited with code {code}; checking any returned card data.",
        "err_no_response": "No valid response received",
        "err_invalid_rwe": "Response is not a single-block RWE frame",
        "err_idm_mismatch": "Response IDm differs from request",
        "err_length_mismatch": "Frame length mismatch",
        "err_card_reject": "Card refused read (status {flags})",
        "err_bad_block_count": "Invalid response block count/length",
        "err_missing": "Not attempted / no read result found",
        "err_decode": "Cannot decode as Suica-style record ({reason})",
        "err_invalid_block": "not a 16-byte block",
        "err_invalid_date": "invalid encoded date",
        "help_description": "Read 5 FeliCa transaction blocks and draw an ASCII balance line chart.",
        "help_pm3": "PM3 client executable (default: pm3)",
        "help_port": "Device port, e.g. /dev/ttyACM0 or COM3",
        "help_timeout": "PM3 timeout in seconds (default: 90)",
        "help_raw": "Append raw PM3 output for troubleshooting",
        "help_demo": "Offline demo based on 3 real sample blocks",
        "help_log": "Parse an existing PM3 session log instead of using hardware",
        "help_lang": "CLI display language: en (default) or ja",
        "err_read_log": "Could not read log: {error}",
        "err_pm3_missing": "PM3 executable not found: {exe!r}; specify it using --pm3",
        "err_timeout": "PM3 timed out; check the antenna, serial port, and reader connection",
    },
    "ja": {
        "title": "PM3 FeliCa | 直近5件の取引履歴と残高推移（読み取り専用）",
        "unknown_idm": "未検出",
        "unknown_pmm": "出力から取得できませんでした",
        "card_format": "カード形式",
        "block_name": "ブロック",
        "protocol": "通信方式",
        "balance_svc": "残高サービス",
        "history_svc": "履歴サービス",
        "system_missing": "未確認（hf felica rqsyscode で確認してください）",
        "format_detected": "System Code 0003 を検出。Suica/PASMO 互換形式として解釈",
        "format_unconfirmed": "System Code 未確認。通貨と取引種別は暫定的な解釈です",
        "current_balance": "8B00 の残高",
        "unreadable": "読み取り不可",
        "history_heading": "直近5件の取引履歴",
        "history_detail": "Block 0 が最新。読み取れた履歴のみ表示",
        "no_history": "解析できる履歴がありません。--raw で PM3 の出力を確認してください。",
        "block": "ブロック",
        "date": "日付",
        "type": "取引種別",
        "balance": "残高",
        "change": "増減額",
        "seq": "連番",
        "trend": "残高推移 | 古い順 → 新しい順 | ASCII 折れ線グラフ",
        "chart_no_data": "残高履歴がありません。",
        "chart_y": "残高 ^  (* = 実際の記録、横方向は記録順)",
        "chart_x": "記録順",
        "chart_note": "注: ブロック番号が連続していない場合は線をつなぎません。",
        "chart_caution": "縦軸は取引後残高です。カード形式と通貨を確認してください。",
        "summary": "概要",
        "latest": "最新の履歴",
        "after_balance": "取引後残高",
        "balance_check": "8B00 と最新履歴の比較",
        "match": "一致",
        "mismatch": "不一致（後続の取引、または形式の違いの可能性）",
        "missing_count": "取得できなかった履歴",
        "general_note": "0F09 だけではカード種別・実際の口座残高・通貨は確定できません。",
        "raw_output": "PM3 生ログ",
        "estimated": "Suica 互換形式での推定値",
        "cmd_start": "カード情報・残高ブロック・直近5件の履歴を読み取ります。カードをアンテナ上に置いてください。",
        "cmd_nonzero": "PM3 の終了コード: {code}。取得できたデータを確認します。",
        "err_no_response": "有効な応答がありません",
        "err_invalid_rwe": "応答が単一ブロック RWE フレームではありません",
        "err_idm_mismatch": "応答 IDm が要求と一致しません",
        "err_length_mismatch": "フレーム長が一致しません",
        "err_card_reject": "カードが読み取りを拒否しました（状態 {flags}）",
        "err_bad_block_count": "応答のブロック数または長さが不正です",
        "err_missing": "未実行、または読み取り結果がありません",
        "err_decode": "Suica 互換形式として解析できません（{reason}）",
        "err_invalid_block": "16 バイトのブロックではありません",
        "err_invalid_date": "日付の符号化が不正です",
        "help_description": "FeliCa の直近5件の取引履歴を読み取り、ASCII 残高折れ線グラフを表示します。",
        "help_pm3": "PM3 クライアントのパス（既定値: pm3）",
        "help_port": "デバイスポート（例: /dev/ttyACM0、COM3）",
        "help_timeout": "PM3 のタイムアウト秒数（既定値: 90）",
        "help_raw": "調査用に PM3 の生ログも表示",
        "help_demo": "実際に読み取った3件のサンプルによるオフラインデモ",
        "help_log": "ハードウェアを使わず既存の PM3 ログを解析",
        "help_lang": "表示言語: en（英語・既定値）または ja（日本語）",
        "err_read_log": "ログを読み込めません: {error}",
        "err_pm3_missing": "PM3 クライアントが見つかりません: {exe!r}。--pm3 で指定してください",
        "err_timeout": "PM3 がタイムアウトしました。アンテナ、ポート、接続を確認してください",
    },
}

OPERATIONS = {
    "en": {
        0x01: "Fare", 0x02: "Top-up", 0x03: "Ticket", 0x04: "Fare adjust",
        0x07: "Issue", 0x0D: "Bus", 0x0F: "Bus", 0x14: "Auto top-up",
        0x46: "Purchase", 0x49: "Deposit", 0xC6: "Purchase+cash",
    },
    "ja": {
        0x01: "乗車", 0x02: "チャージ", 0x03: "切符購入", 0x04: "精算",
        0x07: "発行", 0x0D: "バス", 0x0F: "バス", 0x14: "オートチャージ",
        0x46: "物販", 0x49: "入金", 0xC6: "物販（一部現金）",
    },
}


def tr(lang: str, key: str, **values: object) -> str:
    return TEXT[lang][key].format(**values)


@dataclass
class BlockRead:
    service: str
    number: int
    idm: str
    data: bytes | None
    flags: tuple[int, int] | None
    error: str = ""


@dataclass
class Record:
    block: int
    date: str
    date_sort: dt.date
    balance: int
    operation_code: int
    terminal_code: int
    sequence: int


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "")


def to_bytes(text: str) -> bytes:
    return bytes(int(x, 16) for x in HEX_BYTE_RE.findall(text))


def parse_pm3(text: str):
    """Match each raw response with its preceding request, not printed row indices."""
    text = strip_ansi(text)
    idm_match = IDM_RE.search(text)
    pmm_match = PMM_RE.search(text)
    idm = to_bytes(idm_match.group(1)).hex().upper() if idm_match else ""
    pmm = to_bytes(pmm_match.group(1)).hex().upper() if pmm_match else ""
    system_lines: list[str] = []
    for line in text.splitlines():
        if re.search(r"\bsystem\s*codes?\b", line, re.I):
            line = re.sub(r"^\s*\[[^]]*\]\s*", "", line).strip()
            if line not in system_lines and len(line) < 150:
                system_lines.append(line)

    reads: dict[tuple[str, int], BlockRead] = {}
    pending: tuple[str, int, str] | None = None
    for line in text.splitlines():
        match = REQ_RE.search(line)
        if match:
            req = to_bytes(match.group(1))
            if len(req) >= 15 and req[0] == 6 and req[9] == 1 and req[12] == 1:
                service = req[10:12].hex().upper()
                block = req[14] if req[13] == 0x80 else -1
                requested_idm = req[1:9].hex().upper()
                if block >= 0:
                    pending = (service, block, requested_idm)
                    reads[(service, block)] = BlockRead(service, block, requested_idm, None, None, "err_no_response")
                else:
                    pending = None
            else:
                pending = None
            continue
        response = RAW_RE.search(line)
        if pending is None or response is None:
            continue
        raw = to_bytes(response.group(1))
        service, block, requested_idm = pending
        record = reads[(service, block)]
        pending = None
        if len(raw) < 15 or raw[:4] != b"\xB2\x4D\x1D\x07":
            record.error = "err_invalid_rwe"
            continue
        if raw[4:12].hex().upper() != requested_idm:
            record.error = "err_idm_mismatch"
            continue
        if raw[2] + 4 != len(raw):
            record.error = "err_length_mismatch"
            continue
        record.flags = (raw[12], raw[13])
        if record.flags != (0, 0):
            record.error = "err_card_reject"
            continue
        if raw[14] != 1 or len(raw) != 33:
            record.error = "err_bad_block_count"
            continue
        record.data = raw[15:31]
        record.error = ""
        if not idm:
            idm = requested_idm
    return idm, pmm, system_lines, reads


def decode_history(block: int, data: bytes) -> Record:
    if len(data) != 16:
        raise ValueError("err_invalid_block")
    word = (data[4] << 8) | data[5]
    try:
        date = dt.date(2000 + (word >> 9), (word >> 5) & 0xF, word & 0x1F)
    except ValueError as exc:
        raise ValueError("err_invalid_date") from exc
    return Record(
        block, date.isoformat(), date, int.from_bytes(data[10:12], "little"),
        data[1] & 0x7F, data[0], int.from_bytes(data[12:15], "big"),
    )


def read_current_balance(data: bytes) -> int:
    if len(data) != 16:
        raise ValueError("err_invalid_block")
    return int.from_bytes(data[11:13], "little")


def display_width(text: str) -> int:
    """Terminal width without dependencies (handles full-width Japanese text)."""
    return sum(0 if unicodedata.combining(c) else (2 if unicodedata.east_asian_width(c) in "WF" else 1) for c in text)


def cell(text: object, width: int, right: bool = False) -> str:
    s = str(text)
    pad = " " * max(0, width - display_width(s))
    return pad + s if right else s + pad


def read_error(entry: BlockRead | None, lang: str) -> str:
    if entry is None:
        return tr(lang, "err_missing")
    if entry.error == "err_card_reject" and entry.flags:
        flags = f"{entry.flags[0]:02X} {entry.flags[1]:02X}"
        return tr(lang, "err_card_reject", flags=flags)
    return tr(lang, entry.error) if entry.error else ""


def money(amount: int, confirmed: bool, lang: str) -> str:
    return f"¥{amount:,}" if confirmed else f"{amount:,} ({tr(lang, 'estimated')})"


def balance_line_chart(history: list[Record], lang: str = "en", height: int = 11, spacing: int = 12) -> str:
    """ASCII line graph, oldest to newest. Gaps in block numbers are not connected."""
    if not history:
        return "  " + tr(lang, "chart_no_data")
    points = sorted(history, key=lambda r: r.block, reverse=True)
    minimum, maximum = min(r.balance for r in points), max(r.balance for r in points)
    height, spacing = max(height, 3), max(spacing, 11)
    width = (len(points) - 1) * spacing + 1
    canvas = [[" " for _ in range(width)] for _ in range(height)]

    def y_at(amount: int) -> int:
        if maximum == minimum:
            return height // 2
        return round((maximum - amount) * (height - 1) / (maximum - minimum))

    coords = [(n * spacing, y_at(record.balance)) for n, record in enumerate(points)]
    for i in range(1, len(points)):
        if points[i - 1].block - points[i].block != 1:
            continue
        x1, y1 = coords[i - 1]
        x2, y2 = coords[i]
        for x in range(x1 + 1, x2):
            y = round(y1 + (y2 - y1) * (x - x1) / (x2 - x1))
            canvas[y][x] = "/" if y2 < y1 else "\\" if y2 > y1 else "-"
    for x, y in coords:
        canvas[y][x] = "*"

    labels: dict[int, str] = {}
    for point, (_, y) in zip(points, coords):
        if all(other.balance == point.balance for other, xy in zip(points, coords) if xy[1] == y):
            labels[y] = f"{point.balance:,}"
    if maximum != minimum:
        for y in (0, height // 2, height - 1):
            labels.setdefault(y, f"{round(maximum - y * (maximum - minimum) / (height - 1)):,}")
    else:
        labels[height // 2] = f"{minimum:,}"

    margin = max(7, *(len(value) for value in labels.values()))
    lines = ["  " + tr(lang, "chart_y")]
    for y, chars in enumerate(canvas):
        lines.append(f"  {labels.get(y, ''):>{margin}} |{''.join(chars)}")
    lines.append(f"  {'':>{margin}} +{'-' * width}> {tr(lang, 'chart_x')}")
    left_pad = " " * (margin + 4)

    def xlabels(items: list[str]) -> str:
        chars = [" " for _ in range(width + spacing)]
        for (x, _), label in zip(coords, items):
            start = max(0, x - (len(label) - 1) // 2)
            for n, character in enumerate(label):
                if start + n < len(chars):
                    chars[start + n] = character
        return left_pad + "".join(chars).rstrip()

    lines.append(xlabels([record.date[5:] for record in points]))
    lines.append(xlabels([f"B{record.block:02d}" for record in points]))
    lines.append("  " + tr(lang, "chart_note"))
    return "\n".join(lines)


def report(text: str, *, lang: str = "en", raw: bool = False) -> int:
    idm, pmm, system_lines, reads = parse_pm3(text)
    print("=" * 70)
    print(" " + tr(lang, "title"))
    print("=" * 70)
    print(f" IDm              : {idm or tr(lang, 'unknown_idm')}")
    print(f" PMm              : {pmm or tr(lang, 'unknown_pmm')}")
    print(f" {cell(tr(lang, 'protocol'), 17)}: FeliCa / NFC-F")
    print(f" {cell(tr(lang, 'balance_svc'), 17)}: 8B00 (0x008B)")
    print(f" {cell(tr(lang, 'history_svc'), 17)}: 0F09 (0x090F)")
    if system_lines:
        print(" System Code      :")
        for line in system_lines[:5]:
            print("   " + line)
    else:
        print(" System Code      : " + tr(lang, "system_missing"))

    confirmed = any(re.search(r"\b(?:0x)?0003\b", line, re.I) for line in system_lines)
    print(f" {cell(tr(lang, 'card_format'), 17)}: "
          + tr(lang, "format_detected" if confirmed else "format_unconfirmed"))

    attr = reads.get(("8B00", 0))
    attr_balance = read_current_balance(attr.data) if attr and attr.data else None
    print(f" {cell(tr(lang, 'current_balance'), 17)}: " + (
        money(attr_balance, confirmed, lang) if attr_balance is not None
        else tr(lang, "unreadable") + (f" ({read_error(attr, lang)})" if attr else "")
    ))

    history: list[Record] = []
    errors: list[str] = []
    for i in range(5):
        entry = reads.get(("0F09", i))
        if not entry or entry.data is None:
            errors.append(f"{tr(lang, 'block_name')} {i}: {read_error(entry, lang)}")
            continue
        try:
            history.append(decode_history(i, entry.data))
        except (ValueError, OverflowError) as exc:
            reason = tr(lang, str(exc)) if str(exc) in TEXT[lang] else str(exc)
            errors.append(f"{tr(lang, 'block_name')} {i}: " + tr(lang, "err_decode", reason=reason))

    print("\n[" + tr(lang, "history_heading") + "] (" + tr(lang, "history_detail") + ")")
    if not history:
        print(" " + tr(lang, "no_history"))
        for err in errors:
            print("  - " + err)
        if raw:
            print("\n[" + tr(lang, "raw_output") + "]\n" + strip_ansi(text))
        return 1

    cols = [
        ("block", 7, True), ("date", 10, False), ("type", 18, False),
        ("balance", 10, True), ("change", 10, True), ("seq", 7, True),
    ]
    print(" " + "  ".join(cell(tr(lang, name), width, right) for name, width, right in cols))
    print(" " + "-" * 74)
    for record in history:
        older = next((r for r in history if r.block == record.block + 1), None)
        change = f"{record.balance - older.balance:+,}" if older else "--"
        op = OPERATIONS[lang].get(
            record.operation_code,
            f"Unknown 0x{record.operation_code:02X}" if lang == "en" else f"不明 0x{record.operation_code:02X}",
        )
        values = (record.block, record.date, op, f"{record.balance:,}", change, record.sequence)
        print(" " + "  ".join(cell(value, width, right) for value, (_, width, right) in zip(values, cols)))

    print("\n[" + tr(lang, "trend") + "]")
    print(balance_line_chart(history, lang))
    print(" " + tr(lang, "chart_caution"))
    latest = min(history, key=lambda r: r.block)
    print("\n[" + tr(lang, "summary") + "]")
    print(f" {tr(lang, 'latest')}: {latest.date}, {tr(lang, 'after_balance')} "
          + money(latest.balance, confirmed, lang))
    if attr_balance is not None:
        print(" " + tr(lang, "balance_check") + ": "
              + tr(lang, "match" if attr_balance == latest.balance else "mismatch"))
    if errors:
        print(f" {tr(lang, 'missing_count')}: {len(errors)}")
        for error in errors:
            print("  - " + error)
    print(" " + tr(lang, "general_note"))
    if raw:
        print("\n[" + tr(lang, "raw_output") + "]\n" + strip_ansi(text))
    return 0


def commands() -> str:
    steps = ["hf felica reader", "hf felica info", "hf felica rqsyscode",
             "hf felica rdbl --sn 01 --scl 8B00 --bn 01 --ble 8000"]
    steps.extend(f"hf felica rdbl --sn 01 --scl 0F09 --bn 01 --ble 80{i:02X}" for i in range(5))
    return ";".join(steps)


def make_demo() -> str:
    # Exactly three supplied card records; Blocks 3 and 4 remain absent.
    records = {
        0: bytes.fromhex("1B 02 3F 00 35 53 02 FD 00 00 16 0B 00 00 0B 00"),
        1: bytes.fromhex("1B 02 3F 00 35 53 02 FD 00 00 02 0B 00 00 0A 00"),
        2: bytes.fromhex("1B 02 3F 00 35 41 02 FD 00 00 EE 0A 00 00 09 00"),
    }
    idm = bytes.fromhex("0139FDB5BA07E6F5")
    parts = ["[=] IDm: 01 39 FD B5 BA 07 E6 F5"]

    def frame(service: str, block: int, payload: bytes) -> str:
        request = bytes([6]) + idm + bytes([1]) + bytes.fromhex(service) + bytes([1, 0x80, block])
        response = bytes.fromhex("B2 4D 1D 07") + idm + bytes([0, 0, 1]) + payload + bytes([0, 0])
        return ("[=] Send raw command - Frame: " + request.hex(" ").upper() + "\n"
                "[+] (33) " + response.hex(" ").upper() + "\n")

    parts.append(frame("8B00", 0, bytes.fromhex("00 00 00 00 00 00 00 00 20 00 00 16 0B 00 00 0C")))
    for block in range(5):
        if block in records:
            parts.append(frame("0F09", block, records[block]))
        else:
            request = bytes([6]) + idm + bytes.fromhex("01 0F 09 01 80") + bytes([block])
            parts.append("[=] Send raw command - Frame: " + request.hex(" ").upper() + "\n")
            parts.append("[!] FeliCa command failed (-7)\n")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> None:
    # Translate --help too, without changing the CLI argument names.
    argv = sys.argv[1:] if argv is None else argv
    language = "en"
    for index, arg in enumerate(argv):
        if arg == "--lang" and index + 1 < len(argv):
            language = argv[index + 1]
        elif arg.startswith("--lang="):
            language = arg.partition("=")[2]
    if language not in TEXT:
        language = "en"
    t = TEXT[language]
    parser = argparse.ArgumentParser(description=t["help_description"])
    parser.add_argument("--lang", choices=("en", "ja"), default="en", help=t["help_lang"])
    parser.add_argument("--pm3", default="pm3", help=t["help_pm3"])
    parser.add_argument("--port", help=t["help_port"])
    parser.add_argument("--timeout", type=int, default=90, help=t["help_timeout"])
    parser.add_argument("--raw", action="store_true", help=t["help_raw"])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help=t["help_demo"])
    mode.add_argument("--from-log", type=Path, help=t["help_log"])
    args = parser.parse_args(argv)

    if args.demo:
        output = make_demo()
    elif args.from_log:
        try:
            output = args.from_log.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            parser.error(tr(args.lang, "err_read_log", error=exc))
    else:
        cmd = [args.pm3]
        if args.port:
            cmd += ["-p", args.port]
        cmd += ["-c", commands()]
        print("[PM3] " + tr(args.lang, "cmd_start"), flush=True)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=args.timeout)
        except FileNotFoundError:
            parser.error(tr(args.lang, "err_pm3_missing", exe=args.pm3))
        except subprocess.TimeoutExpired:
            parser.error(tr(args.lang, "err_timeout"))
        output = proc.stdout + "\n" + proc.stderr
        if proc.returncode:
            print("[PM3] " + tr(args.lang, "cmd_nonzero", code=proc.returncode), file=sys.stderr)
    sys.exit(report(output, lang=args.lang, raw=args.raw))


if __name__ == "__main__":
    main()
