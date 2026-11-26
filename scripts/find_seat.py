# -*- coding: utf-8 -*-
"""Find the area that owns seat no '005' (default) for tomorrow."""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qfnu_lib import settings
from qfnu_lib.cli import login

cfg = settings.load()
c = login(cfg)

build_id = int(cfg.get("book_build_id", 39))
code, j = c.seat_dates(build_id)
dates = j.get("data") or []
print("code:", code, "days:", [(d.get("day"), [(t.get("id"), t.get("start"), t.get("end")) for t in d.get("times") or []]) for d in dates])

tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
seg = None
for d in dates:
    if d.get("day") == tomorrow:
        seg = (d.get("times") or [None])[0]
if not seg:
    sys.exit("no segment for " + tomorrow)
print("segment:", seg)

want = sys.argv[1] if len(sys.argv) > 1 else "005"
hits = []
for area in list(range(1, 61)) + [100, 101, 102]:
    try:
        code, j = c.seat_list(area, seg["id"], tomorrow, seg["start"], seg["end"])
    except Exception:
        continue
    rows = (j.get("data") or []) if code in (1, 200) else []
    if not rows:
        continue
    name = rows[0].get("area_name", "?")
    print("area %-4s %-34s seats=%d" % (area, name, len(rows)))
    for r in rows:
        if str(r.get("no")) == want:
            hits.append({"area": area, "area_name": name, "seat_id": r.get("id"),
                         "no": r.get("no"), "status": r.get("status"),
                         "status_name": r.get("status_name")})
print("\nhits for no=%s: %s" % (want, json.dumps(hits, ensure_ascii=False)))
