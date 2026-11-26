# -*- coding: utf-8 -*-
"""Repair the damaged multi-account section at the end of README.md."""
import io, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = os.path.join(ROOT, "README.md")
lines = io.open(p, encoding="utf-8").read().splitlines()

# keep everything up to the line before "## 澶氳处鍙凤紙profile锛?
cut = None
for i, ln in enumerate(lines):
    if ln.startswith("## 澶氳处鍙?):
        cut = i
        break
if cut is None:
    sys.exit("marker not found")
head = lines[:cut]
# drop trailing blank lines of head
while head and not head[-1].strip():
    head.pop()

section = r'''
## 澶氳处鍙凤紙profile锛?
`QFNU_PROFILE` 鐜鍙橀噺鍒囨崲璐﹀彿锛屼袱濂楅厤缃拰鐘舵€佸畬鍏ㄩ殧绂伙細

| profile | 璐﹀彿 | 閰嶇疆鏂囦欢 | 鐘舵€佺洰褰?| 搴т綅 | 鍚姩鑴氭湰 |
|---|---|---|---|---|---|
| 锛堢┖锛?| 账号A学号 | `config.json` | `.qfnu-state\` | 鍥涘眰 042 | `run_daily.bat` |
| `qzm` | 账号B学号 | `config.qzm.json` | `.qfnu-state\qzm\` | 鍥涘眰 043 | `run_daily2.bat` |

```bat
set QFNU_PROFILE=qzm
python -m qfnu_lib.cli login      :: 棣栨锛氳窇涓€娆℃祻瑙堝櫒婊戝潡锛宼oken 瀛?.qfnu-state\qzm\lib_session.json
python -m qfnu_lib.cli daily
```

姣忎釜 profile 鐢ㄧ嫭绔嬬殑 `edge_profile` 鍜?`cdp_port`锛?024413595 鐢?9222 / `tools\edge-profile-clean`锛?账号B学号 鐢?9223 / `tools\edge-profile-qzm`锛夛紝鍚﹀垯涓や釜璐﹀彿浼氭姠鍚屼竴涓?Edge 鐢ㄦ埛鐩綍銆?鍔犵涓変釜璐﹀彿锛氱収鎶勪竴浠?`config.<name>.json`銆佸鍒?`run_daily2.bat` 鏀规垚瀵瑰簲 profile锛?鍐嶅湪鍚姩椤归噷鍔犱竴琛?`start "" /min run_dailyN.bat`銆?'''

out = "\n".join(head) + "\n" + section
io.open(p, "w", encoding="utf-8", newline="\n").write(out)
print("rewritten, tail:")
print(out[-600:])