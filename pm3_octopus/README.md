# PM3 Octopus Viewer — English / 日本語

A **read-only**, standard-library Python CLI for a Proxmark3 (RRG/Iceman) and a Hong Kong Octopus FeliCa card, including Apple Wallet Octopus. It reads the card's public balance block, displays basic information, and optionally plots a **last-five-transactions ASCII line chart** from a manually prepared CSV.

**Important limitation:** The last five transactions are **not read from the Octopus chip**. On the tested Apple Wallet Octopus, the `1701` balance service has one readable block, `0B10` provides only two zero-filled blocks, and a publicly readable transaction history was **not identified**. History and the line graph use an external CSV instead; any entries shown are explicitly identified as external data.

## Contents

- `pm3_octopus.py` — self-contained CLI script (Python 3.10+ recommended)
- `octopus_history_example.csv` — **fictional** five-entry transaction history for demo
- `pm3_octopus_README.md` — this guide

## Quick start

First **exit the interactive** `pm3 -->` prompt. Place your own Octopus card on the PM3 HF antenna and run these in your operating-system terminal:

```bash
python3 pm3_octopus.py --lang en
python3 pm3_octopus.py --lang ja
```

To target a USB serial port or specific client:

```bash
python3 pm3_octopus.py --pm3 /path/to/pm3 --port /dev/ttyACM0 --lang en
```

By default the script calls PM3 with one `-c` command string containing these **read-only** commands:

```text
hf search
hf felica info
hf felica rqsyscode
hf felica rdbl --sn 01 --scl 1701 --bn 01 --ble 8000
```

The Proxmark3 client supports semicolon-separated commands with `-c`. If yours is different, use the next section's saved-log mode.

## Demo / CSV transactions

Preview the output **without PM3 hardware**:

```bash
python3 pm3_octopus.py --demo --lang en --history-csv octopus_history_example.csv
python3 pm3_octopus.py --demo --lang ja --history-csv octopus_history_example.csv
```

Create your own `history.csv` based on transactions shown by the **Octopus App** / Apple Wallet. Use this format, **oldest first**, with a balance *after* each transaction:

```csv
date,description,balance
2026-10-01,Bus,86.00
2026-10-05,Top up,136.00
2026-10-09,MTR,124.00
2026-10-18,Shop,112.00
2026-10-21,Bus,100.00
```

Example amounts are made up and do not represent your transactions. Dates must be valid `YYYY-MM-DD` dates in ascending order; on the same date, keep the transactions in their actual chronological order. The CSV is in HK dollars, with at most 2 decimal places. `description` is optional. The **five newest** CSV rows are displayed; changes are calculated from the adjacent entries. The first displayed entry has no earlier comparison if no additional older entry is included.

Then run:

```bash
python3 pm3_octopus.py --lang en --history-csv history.csv
python3 pm3_octopus.py --lang ja --history-csv history.csv
```

The script compares the latest CSV balance with the current NFC balance and warns if they differ. It may differ because the CSV is incomplete or stale; it does not automatically sync with Wallet or Octopus servers.

## Offline parser and debugging

To parse a PM3 terminal transcript from a file instead of using USB:

```bash
python3 pm3_octopus.py --from-log my_pm3_log.txt --lang en
```

Optional parameters:

```text
--lang en|ja        CLI language, English by default
--pm3 FILE          Path to PM3 executable, default "pm3"
--port PORT         Pass -p PORT to PM3 client
--history-csv FILE  External transaction history
--from-log FILE     Parse an existing text transcript instead of accessing PM3
--demo              Simulated Octopus card; no hardware needed
--offset 500|350    Balance offset, 500 by default
--discover          Also run read-only service discovery
--save-log FILE     Save PM3 text output locally
--raw               Display the entire PM3 response
--timeout SECONDS   PM3 client timeout; default 120
```

Be careful with `--raw` and `--save-log`; PM3 logs contain card identifiers (IDm). There is no card-writing, cloning, authentication bypass, or emulation in this tool.

## Verified Octopus balance decoding

The user-confirmed Apple Wallet Octopus read returned `1701` Block 0:

```text
00 00 05 DC 00 00 00 00 00 00 00 00 00 00 00 00
```

First four bytes are a big-endian unsigned integer `1500`. With the modern Octopus offset:

```text
HKD = (1500 - 500) / 10 = HK$100.00
```

The user confirmed that the result matched Apple Wallet. Legacy cards may need `--offset 350`, as described in the public Octopus format. This method uses the FeliCa balance service (`--scl 1701`, numeric `0x0117`); it **does not** recover transaction history.

## Known limitations

- Actual live PM3 hardware execution has not been tested in this environment. Both language modes and valid/error response parsing can be checked offline.
- The card must be properly positioned on the reader during all commands. If another card is selected, the IDm check should prevent accepting a response from a different card.
- Saved PM3 logs and CSV histories are private data; protect them accordingly.
- FeliCa status `01 A8` indicates an invalid/inaccessible block, not a valid empty record.

## References

- [Metrodroid Octopus format](https://github-wiki-see.page/m/metrodroid/metrodroid/wiki/Octopus)
- [Proxmark3 client command-line parameters](https://www.kali.org/tools/proxmark3/)
