# PM3 FeliCa History Viewer — English / 日本語

Read the last five available transaction records and show the balance trend as a **text-only ASCII line graph**. Display language is selected with `--lang en` or `--lang ja` (default: English). **Python 3.10+**, with no additional Python dependencies.

## English

### Quick start

Run this in your computer's terminal, **not** in the interactive `pm3 -->` prompt. Close any other PM3 session first.

```bash
# English output (default)
python3 pm3_felica_history.py --lang en --pm3 pm3

# Japanese output
python3 pm3_felica_history.py --lang ja --pm3 pm3

# Offline preview: uses only the three blocks supplied in the conversation
python3 pm3_felica_history.py --demo --lang en
python3 pm3_felica_history.py --demo --lang ja

# Read an existing PM3 session log without hardware
python3 pm3_felica_history.py --from-log pm3-session.log --lang ja
```

If your client is called `proxmark3`, use `--pm3 proxmark3`. A serial port may be specified with `--port /dev/ttyACM0` or `--port COM3`:

```bash
python3 pm3_felica_history.py --pm3 proxmark3 --port /dev/ttyACM0 --lang en
```

Windows PowerShell example:

```powershell
py -3 .\pm3_felica_history.py --pm3 "C:\path\to\proxmark3.exe" --port COM3 --lang ja
```

For Japanese text on Windows, use a terminal configured for UTF-8 and a font that supports Japanese. If needed, switch the console code page with `chcp 65001` before running the command.

### Options

| Argument | Description |
| --- | --- |
| `--lang en` | English labels and messages (default) |
| `--lang ja` | Japanese labels and messages |
| `--pm3 PATH` | PM3 client executable (default `pm3`) |
| `--port PORT` | Serial port if auto-discovery is unavailable |
| `--timeout 90` | PM3 timeout in seconds |
| `--demo` | Offline preview; no hardware |
| `--from-log FILE` | Parse an existing PM3 log |
| `--raw` | Include raw PM3 output for troubleshooting |
| `--help` | Show usage; respects `--lang` |

### What the script reads

It starts **one PM3 client session** and runs `hf felica reader`, `hf felica info`, `hf felica rqsyscode`, `hf felica rdbl` for **8B00 Block 0**, and `hf felica rdbl` for **0F09 Blocks 0–4**. It displays available IDm, PMm, System Code, history date/type/sequence, balance and changes. It validates response framing, IDm matching and success flags before using block data.

The balance chart plots oldest → newest by **transaction order, not time spacing**, using `*` for records and `/`, `\`, or `-` for connecting lines. It does not connect gaps in block indexes. Missing or unreadable blocks are reported rather than made up.

### Data interpretation and safety

The 0F09 and 8B00 layouts are interpreted **conditionally as Suica/PASMO-style data**; other FeliCa cards can use different formats. A `0003` System Code is useful evidence but **is not proof of issuer, currency, or authoritative current balance**. The 0F09 balance is balance *after a recorded transaction*; it is not automatically a live bank account balance.

This script only reads data and performs no authentication, write operation, payment or emulation. It does not save dumps itself; PM3 may still create logs according to its own settings. Only use cards you own or are authorized to read, and protect exported logs.

## 日本語

### 実行方法

PM3 の対話プロンプト `pm3 -->` ではなく、パソコンのターミナルから実行してください。すでに PM3 クライアントを起動している場合は先に終了してください。

```bash
# 日本語表示
python3 pm3_felica_history.py --lang ja --pm3 pm3

# 英語表示（既定値）
python3 pm3_felica_history.py --lang en --pm3 pm3

# オフラインで表示を確認（提供済みの3件のみ使用）
python3 pm3_felica_history.py --demo --lang ja

# 保存済みの PM3 ログを解析
python3 pm3_felica_history.py --from-log pm3-session.log --lang ja
```

Windows PowerShell の例：

```powershell
py -3 .\pm3_felica_history.py --pm3 "C:\path\to\proxmark3.exe" --port COM3 --lang ja
```

日本語が文字化けする場合は、UTF-8 に対応したターミナルと日本語フォントを使用してください。必要に応じて `chcp 65001` を実行してください。

### 表示内容

- IDm、PMm、System Code（取得できた場合）と読み取りサービス情報
- `8B00` の Block 0 にある残高候補
- `0F09` の Block 0–4 にある直近5件の取引履歴（読み取り可能な範囲）
- 日付、取引種別、取引後残高、前の履歴からの増減額、連番
- **ASCII の折れ線グラフ**：横軸は古い記録から新しい記録への順序、縦軸は取引後残高
- 失敗したブロックの理由と、`8B00` の残高候補との比較

### 注意事項

`0F09` や `8B00` のデータ構造は、**Suica/PASMO 互換形式であると仮定して**解釈しています。すべての FeliCa カードで同じ形式が使われているわけではありません。System Code `0003` が見つかっても、発行者や通貨、現在の実際の残高を完全に証明するものではありません。

本スクリプトは**読み取り専用**です。認証・書き込み・決済・カードエミュレーションは行いません。カードのダンプファイルを保存しませんが、PM3 クライアント側でログが残る場合があります。所有カードまたは許可されたカードにのみ使用してください。
