# -*- coding: utf-8 -*-
"""Command line interface:  python -m qfnu_lib.cli <command>

commands:
  login    sign in and cache the library token
  seat     show current bookings
  in       check in now
  out      check out now
  run      wait for the booking to become valid, then check in (used by Task Scheduler)
  book     book tomorrow's seat (retry loop until the 19:20 opening)
  cancel   cancel today's booking (or check out when cancel is refused)
  daily    resident scheduler: 19:20 book / 21:40 cancel / 08:01 check in / 08:25 verify
  verify   check today's sign-in (08:25 job): emergency check-in + alert when missing
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

from . import api, cas, settings


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.join(settings.ROOT, "logs"), exist_ok=True)
        with open(os.path.join(settings.ROOT, "logs", "checkin.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _alert(msg):
    """Durable alert line (logs/alert.log) for things the user must know about."""
    log("ALERT: " + msg)
    try:
        os.makedirs(os.path.join(settings.ROOT, "logs"), exist_ok=True)
        with open(os.path.join(settings.ROOT, "logs", "alert.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


def login(cfg, allow_browser=True):
    """Return an authenticated Client (cached token first, then CASTGC, then browser)."""
    sf = settings.session_file()
    if os.path.exists(sf):
        try:
            tok = json.load(open(sf, encoding="utf-8")).get("token", "")
        except ValueError:
            tok = ""
        if tok:
            c = api.Client(cfg, tok)
            code, j = c.my_seat()
            if code == 200 and j.get("code") == 1:
                return c
    try:
        castgc = cas.castgc_from_edge(cfg)
    except Exception:
        castgc = ""
    if castgc:
        try:
            ticket = cas.ticket_from_castgc(cfg, castgc)
            if ticket:
                code = cas.exchange(cfg, ticket)
                if code:
                    c = api.Client(cfg)
                    if c.exchange_cas(code):
                        _save(c.token)
                        log(f"login ok (castgc): {cfg['account']}")
                        return c
        except Exception as e:
            log(f"castgc login failed: {type(e).__name__} {e}")
    if not allow_browser:
        return None
    log("CASTGC missing/expired -> solving the slide captcha in Edge")
    castgc = ""
    for attempt in (1, 2):
        try:
            castgc = cas.browser_login(cfg)
        except Exception as e:
            log(f"browser login attempt {attempt} failed: {e}")
        if castgc:
            break
        if attempt == 1:
            log("resetting the Edge instance and retrying")
            cas.reset_edge(cfg)
    if not castgc:
        log("browser login failed")
        return None
    try:
        ticket = cas.ticket_from_castgc(cfg, castgc)
        code = cas.exchange(cfg, ticket) if ticket else ""
        c = api.Client(cfg) if code else None
        if c and c.exchange_cas(code):
            _save(c.token)
            log(f"login ok (browser): {cfg['account']}")
            return c
    except Exception as e:
        log(f"browser login token exchange failed: {type(e).__name__} {e}")
    log("token exchange failed")
    return None


def _save(token):
    os.makedirs(settings.STATE, exist_ok=True)
    with open(settings.session_file(), "w", encoding="utf-8") as f:
        json.dump({"token": token, "saved": datetime.now().isoformat(timespec="seconds")}, f)


def _today_booking(c, statuses=("2",)):
    """Today's booking. statuses: "2"=预约成功, "3"=使用中 (already signed in).

    The 21:40 job must also see status 3, otherwise it reports
    "no active booking today" for a seat that is currently in use and the
    account never gets 签退 (which costs a 违规).
    """
    now = datetime.now()
    for b in c.bookings():
        if str(b.get("status")) not in statuses:
            continue
        try:
            begin = datetime.strptime(b["beginTime"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            continue
        if begin.date() == now.date():
            return b, begin
    return None, None


def cmd_seat(cfg):
    c = login(cfg)
    if not c:
        return 1
    for b in c.bookings():
        log(f"{b.get('beginTime')} ~ {b.get('endTime')}  {b.get('nameMerge')} {b.get('name')}"
            f"  status={b.get('status')}({b.get('statusName')}) signIn={b.get('signInTime')}")
    return 0


def cmd_touch(cfg, method):
    c = login(cfg)
    if not c:
        return 1
    code, j = c.checkin() if method == "checkin" else c.checkout()
    log(f"{method}: {code} {json.dumps(j, ensure_ascii=False)[:300]}")
    return 0 if j.get("code") == 1 else 1


def cmd_run(cfg, dry=False):
    """Wait for today's booking to become valid, then check in (retries for a while)."""
    c = login(cfg)
    if not c:
        return 2
    booking, begin = _today_booking(c)
    if not booking:
        log("no active booking for today")
        return 3
    advance = int(cfg.get("checkin_advance_sec", 5))
    fire = begin - timedelta(seconds=advance)
    now = datetime.now()
    if now < fire:
        wait = (fire - now).total_seconds()
        log(f"booking {booking['beginTime']} at {booking.get('nameMerge')} {booking.get('name')};"
            f" sleeping {wait:.0f}s")
        if not dry:
            time.sleep(wait)
    if dry:
        log("dry run: would check in now")
        return 0
    # the cached token may be hours old by now: sign in again right before
    c = login(cfg, allow_browser=False) or c
    max_minutes = int(cfg.get("checkin_max_minutes", 40))
    retry = int(cfg.get("checkin_retry_sec", 60))
    deadline = datetime.now() + timedelta(minutes=max_minutes)
    attempt = 0
    while datetime.now() < deadline:
        attempt += 1
        try:
            code, j = c.checkin()
        except Exception as e:
            log(f"attempt {attempt} crashed: {type(e).__name__} {e}")
            time.sleep(retry)
            continue
        msg = j.get("msg", "")
        data = j.get("data") or {}
        if j.get("code") == 1:
            log(f"CHECK-IN OK after {attempt} attempt(s): {json.dumps(j, ensure_ascii=False)[:300]}")
            return 0
        if any(k in msg for k in ("已经签到", "已签到", "重复签到", "不用重复签到")):
            log(f"already signed in: {msg}")
            return 0
        log(f"attempt {attempt}: {msg} {json.dumps(data, ensure_ascii=False)[:200]}")
        if "未生效" not in msg and "网络" not in msg:
            # unknown error: try a fresh login once, then keep retrying
            c2 = login(cfg, allow_browser=False)
            if c2:
                c = c2
        time.sleep(retry)
    log("gave up: check-in window elapsed")
    _alert(f"签到失败：{cfg.get('account')} 在 {max_minutes} 分钟内没能签到，今天很可能记 1 次违规")
    return 4


def _tomorrow():
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def _find_seat(c, area, segment, day, start, end, seat_no):
    """Return the seat id whose number is `seat_no` in `area`."""
    code, j = c.seat_list(area, segment, day, start, end)
    if j.get("code") != 1:
        return None, j.get("msg")
    for s in j.get("data") or []:
        if str(s.get("no")) == str(seat_no):
            return s.get("id"), s.get("status_name")
    return None, "seat %s not found" % seat_no


def _open_dt(hhmm):
    h, m = [int(x) for x in str(hhmm).split(":")[:2]]
    return datetime.combine(datetime.now().date(), datetime.min.time()).replace(hour=h, minute=m)


def cmd_book(cfg, dry=False, catchup=False):
    """Pre-login and resolve the seat early, then hammer confirm from the 19:20 opening."""
    area = int(cfg.get("book_area", 39))
    build_id = int(cfg.get("book_build_id", 39))
    seat_no = str(cfg.get("book_seat_no", "043"))
    window = int(cfg.get("book_window_minutes", 10))
    retry = int(cfg.get("book_retry_sec", 2))
    open_at = cfg.get("book_at", "19:20")
    open_dt = _open_dt(open_at)
    day = _tomorrow()

    # 1) log in while the site is still quiet (cached token -> CASTGC -> Edge)
    c = login(cfg, allow_browser=False) or login(cfg)
    if not c:
        return 2
    log(f"book: logged in as {cfg['account']} for {seat_no} (opening {open_at})")

    # 2) resolve segment + seat id before the rush so confirm is the only request left
    seg = None
    seat_id = str(cfg.get("book_seat_id", "") or "")
    while datetime.now() < max(open_dt, datetime.now() + timedelta(minutes=window)):
        if seg is None:
            code, j = c.seat_dates(build_id)
            for d in j.get("data") or []:
                if d.get("day") == day and d.get("times"):
                    seg = d["times"][0]
                    break
            if seg is None:
                log("book: no time slot yet, retrying")
                time.sleep(retry)
                continue
        if not seat_id:
            seat_id, info = _find_seat(c, area, seg["id"], day, seg["start"], seg["end"], seat_no)
            if not seat_id:
                log(f"book: cannot locate seat {seat_no}: {info}")
                time.sleep(retry)
                continue
        log(f"book: prepared {day} {seg['start']}-{seg['end']} seat {seat_no} (id {seat_id}, segment {seg['id']})")
        break

    if dry:
        log(f"dry run: would book {day} {seg['start']}-{seg['end']} seat {seat_no} "
            f"(id {seat_id}, segment {seg['id']})")
        return 0
    if not seg or not seat_id:
        log("book: could not prepare segment/seat before the window")
        return 3

    # 3) wait for the opening (no network calls, so the first confirm is the fastest possible)
    fire_at = open_dt - timedelta(seconds=0.5)
    while datetime.now() < fire_at:
        left = (fire_at - datetime.now()).total_seconds()
        if left > 30:
            time.sleep(min(left - 30, 60))
        elif left > 1:
            time.sleep(0.5)
        else:
            time.sleep(0.05)
    log("book: opening reached, firing confirm")

    deadline = (datetime.now() + timedelta(minutes=window)) if catchup else (open_dt + timedelta(minutes=window))
    attempt = 0
    while datetime.now() < deadline:
        attempt += 1
        code, r = c.book(seat_id, seg["id"])
        msg = r.get("msg") or r.get("message") or ""
        if r.get("code") == 1:
            log(f"BOOK OK after {attempt} attempt(s): {day} {seg['start']}-{seg['end']} seat {seat_no} :: {msg}")
            return 0
        log(f"attempt {attempt}: {msg}")
        if "已预约" in msg or "存在预约" in msg:
            return 0
        if "其他设备" in msg or "未登录" in msg:
            c = login(cfg, allow_browser=False) or c
        elif "开放预约时间" not in msg and "不可预约" not in msg and attempt % 5 == 0:
            c = login(cfg, allow_browser=False) or c
        time.sleep(retry)
    log("gave up: booking window elapsed")
    return 4


def cmd_cancel(cfg, dry=False):
    """Cancel today's active booking, or 签退 if the seat is already in use (the 21:40 job)."""
    c = login(cfg, allow_browser=False) or login(cfg)
    if not c:
        return 2
    booking, begin = _today_booking(c, statuses=("2", "3"))
    if not booking:
        log("cancel: no active booking today")
        return 0
    in_use = str(booking.get("status")) == "3" or bool(booking.get("signInTime"))
    if dry:
        log(f"dry run: would {'checkout' if in_use else 'cancel'} booking {booking.get('id')} "
            f"{booking.get('nameMerge')} {booking.get('name')}")
        return 0
    if in_use:
        # Seat is (or was) occupied -> cancelling is refused by the server; 签退 is
        # what actually frees it and avoids the "未签退" 违规. Retry for a while:
        # 21:40 leaves ~20 minutes before the 22:00 deadline.
        retry = int(cfg.get("cancel_retry_sec", 30))
        deadline = datetime.now() + timedelta(minutes=int(cfg.get("cancel_max_minutes", 15)))
        attempt = 0
        while True:
            attempt += 1
            code, k = c.checkout()
            log(f"checkout attempt {attempt}: {code} {json.dumps(k, ensure_ascii=False)[:300]}")
            if k.get("code") == 1:
                return 0
            msg = k.get("msg") or ""
            if any(w in msg for w in ("已经离开", "已离开", "不用重复", "未生效", "未签到")):
                log(f"nothing to sign out: {msg}")
                return 0
            if datetime.now() >= deadline:
                log("gave up: checkout window elapsed")
                return 1
            c = login(cfg, allow_browser=False) or c
            time.sleep(retry)
    code, j = c.cancel(booking.get("id"))
    log(f"cancel booking {booking.get('id')}: {code} {json.dumps(j, ensure_ascii=False)[:300]}")
    if j.get("code") == 1:
        return 0
    # Already checked in / cancellation is not allowed any more -> sign out instead,
    # which is what actually frees the seat and avoids the 违规.
    if booking.get("signInTime") or "禁止取消" in (j.get("msg") or ""):
        code, k = c.checkout()
        log(f"cancel refused -> checkout: {code} {json.dumps(k, ensure_ascii=False)[:300]}")
        return 0 if k.get("code") == 1 else 1
    return 1


def cmd_checkin_window(cfg):
    """Check in with retries (the 08:01 job)."""
    retry = int(cfg.get("checkin_retry_sec", 60))
    deadline = datetime.now() + timedelta(minutes=int(cfg.get("checkin_max_minutes", 40)))
    attempt = 0
    c = None
    while datetime.now() < deadline:
        attempt += 1
        if not c:
            try:
                c = login(cfg, allow_browser=False) or login(cfg)
            except Exception as e:
                log(f"check-in login failed: {type(e).__name__} {e}")
                c = None
        if not c:
            time.sleep(retry)
            continue
        try:
            code, j = c.checkin()
        except Exception as e:
            log(f"check-in attempt {attempt} crashed: {type(e).__name__} {e}")
            c = None
            time.sleep(retry)
            continue
        msg = j.get("msg", "")
        if j.get("code") == 1:
            log(f"CHECK-IN OK after {attempt} attempt(s): {json.dumps(j, ensure_ascii=False)[:300]}")
            return 0
        if any(k in msg for k in ("已经签到", "已签到", "重复签到", "不用重复签到")):
            log(f"already signed in: {msg}")
            return 0
        log(f"check-in attempt {attempt}: {msg}")
        if "未生效" not in msg and "network error" not in msg:
            c = login(cfg, allow_browser=False) or c
        time.sleep(retry)
    log("gave up: check-in window elapsed")
    _alert(f"签到失败：{cfg.get('account')} 在 {int(cfg.get('checkin_max_minutes', 40))} 分钟内没能签到，"
           f"今天很可能记 1 次违规")
    return 4


def _catchup(cfg):
    """If the scheduler was started after a slot, do the missed work once."""
    hhmm = datetime.now().strftime("%H:%M")
    if "19:20" <= hhmm <= "22:00":
        c = login(cfg, allow_browser=False)
        if c:
            day = _tomorrow()
            if not any(str(b.get("status")) == "2" and str(b.get("beginTime", ""))[:10] == day
                       for b in c.bookings()):
                log("catch-up: nothing booked for %s -> booking now" % day)
                cfg2 = dict(cfg)
                cfg2["book_window_minutes"] = 2
                cmd_book(cfg2, catchup=True)
    if "08:00" <= hhmm <= "08:25":
        c = login(cfg, allow_browser=False)
        if c:
            booking, _ = _today_booking(c)
            if booking and not booking.get("signInTime"):
                log("catch-up: today's booking is not signed in -> check in now")
                cmd_checkin_window(cfg)
    if "08:25" < hhmm <= "08:29":
        log("catch-up: inside the 08:25 verify window -> checking today's check-in")
        cmd_verify(cfg)


def _desktop_alert(msg):
    """Drop a hard-to-miss txt on the desktop (this box has no IM/邮件通道)."""
    body = (msg + "\n\n"
            f"时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"日志: {os.path.join(settings.ROOT, 'logs', 'task.log')}\n")
    name = f"图书馆签到失败-{datetime.now():%Y-%m-%d}.txt"
    env = os.environ.get("QFNU_ALERT_DIR")
    if env:
        dirs = [env]
    else:
        home = os.path.expanduser("~")
        dirs = [os.path.join(home, d) for d in ("Desktop", "OneDrive/Desktop")]
        dirs = [d for d in dirs if os.path.isdir(d)] or [home]
    for d in dirs:
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, name), "w", encoding="utf-8-sig") as f:
                f.write(body)
            log(f"desktop alert written: {os.path.join(d, name)}")
        except OSError as e:
            log(f"desktop alert failed ({d}): {e}")


def _clear_desktop_alert():
    name = f"图书馆签到失败-{datetime.now():%Y-%m-%d}.txt"
    env = os.environ.get("QFNU_ALERT_DIR")
    home = os.path.expanduser("~")
    dirs = [env] if env else [os.path.join(home, d) for d in ("Desktop", "OneDrive/Desktop")]
    for d in dirs:
        p = os.path.join(d, name)
        if d and os.path.exists(p):
            try:
                os.remove(p)
                log(f"stale desktop alert removed: {p}")
            except OSError:
                pass


def cmd_verify(cfg):
    """08:25 自查：今天到底签到没有？没签就在 08:30 判定前最后抢救一次并报警。"""
    c = None
    try:
        c = login(cfg, allow_browser=False) or login(cfg)
    except Exception as e:
        log(f"verify: login failed: {type(e).__name__} {e}")
    if not c:
        _alert(f"自查失败：{cfg.get('account')} 08:25 登录不上，无法确认今天是否签到")
        _desktop_alert(f"图书馆签到自查失败：{cfg.get('account')} 连接不上图书馆，请手动确认！")
        return 2
    booking, _ = _today_booking(c, statuses=("2", "3", "8"))
    if not booking:
        log("verify: no active booking today, nothing to check")
        return 0
    if booking.get("signInTime"):
        log(f"verify OK: {booking.get('nameMerge')} {booking.get('name')} "
            f"signed in at {booking.get('signInTime')}")
        _clear_desktop_alert()
        return 0
    log(f"verify: {booking.get('nameMerge')} {booking.get('name')} 没有签到记录 -> 紧急补签")
    now = datetime.now()
    stop = now + timedelta(minutes=float(cfg.get("verify_max_minutes", 4)))
    cap = now.replace(hour=8, minute=29, second=30, microsecond=0)
    if stop > cap:
        stop = cap
    if stop <= now:
        stop = now + timedelta(seconds=30)
    attempt = 0
    while datetime.now() < stop:
        attempt += 1
        try:
            code, j = c.checkin()
        except Exception as e:
            log(f"emergency attempt {attempt} crashed: {type(e).__name__} {e}")
            time.sleep(15)
            continue
        msg = j.get("msg") or ""
        if j.get("code") == 1:
            log(f"EMERGENCY CHECK-IN OK after {attempt} attempt(s): "
                f"{json.dumps(j, ensure_ascii=False)[:300]}")
            _clear_desktop_alert()
            return 0
        if any(k in msg for k in ("已经签到", "已签到", "重复签到", "不用重复签到")):
            log(f"verify: already signed in ({msg})")
            return 0
        log(f"emergency attempt {attempt}: {msg}")
        if "未生效" not in msg and "network error" not in msg:
            c = login(cfg, allow_browser=False) or c
        time.sleep(15)
    msg = (f"图书馆签到失败：{cfg.get('account')} 今天"
           f"{booking.get('nameMerge')} {booking.get('name')} 没有签到成功，"
           f"08:30 后会记 1 次违规，请立即手动处理！")
    _alert(msg)
    _desktop_alert(msg)
    return 4


def cmd_daily(cfg):
    """Long-running scheduler: 19:20 book tomorrow, 21:40 cancel today, 08:01 check in."""
    book_at = cfg.get("book_at", "19:20")
    book_start = cfg.get("book_start_at", "19:15")
    cancel_at = cfg.get("cancel_at", "21:40")
    checkin_at = cfg.get("checkin_at", "08:01")
    verify_at = cfg.get("verify_at", "08:25")
    # (从, 到, 名字, 函数) —— 起止相同表示只在该分钟触发；verify 给一段窗口，
    # 这样即使 08:01 的签到任务卡到 08:25 之后，自查也不会被错过。
    plan = [(book_start, book_start, "book", cmd_book),
            (cancel_at, cancel_at, "cancel", cmd_cancel),
            (checkin_at, checkin_at, "checkin", cmd_checkin_window),
            (verify_at, "08:29", "verify", cmd_verify)]
    log(f"daily scheduler up: pre-login {book_start} -> book {book_at} seat {cfg.get('book_seat_no', '043')}, "
        f"cancel {cancel_at}, checkin {checkin_at}, verify {verify_at}")
    try:
        _catchup(cfg)
    except Exception as e:  # 网络异常不该把常驻进程带走
        log(f"catch-up crashed: {type(e).__name__} {e}")
    done = set()        # 当天已处理过（成功或彻底放弃）
    retry_at = {}       # (date, name) -> 下次重试时间
    crashes = {}        # (date, name) -> 连续崩溃次数
    retry_interval = int(cfg.get("job_retry_sec", 30))
    max_crashes = int(cfg.get("job_max_crashes", 40))
    while True:
        now = datetime.now()
        slot = now.strftime("%Y-%m-%d %H:%M")
        today = now.date().isoformat()
        due = []
        hhmm = slot[-5:]
        for start, end, name, fn in plan:
            key = (today, name)
            if key in done:
                continue
            if start <= hhmm <= end or (key in retry_at and now >= retry_at[key]):
                due.append((key, name, fn))
        for key, name, fn in due:
            if key in done:
                continue
            if key in retry_at:
                log(f"--- job {name} (retry {crashes.get(key, 0)}) ---")
            else:
                log(f"--- job {name} ---")
            try:
                fn(cfg)
                done.add(key)
                retry_at.pop(key, None)
                crashes.pop(key, None)
            except Exception as e:  # keep the daemon alive and retry
                n = crashes.get(key, 0) + 1
                crashes[key] = n
                if n >= max_crashes:
                    done.add(key)
                    retry_at.pop(key, None)
                    log(f"job {name}: giving up after {n} crashes: {type(e).__name__} {e}")
                    _alert(f"任务 {name} 连续崩溃 {n} 次已放弃：{type(e).__name__} {e}")
                else:
                    retry_at[key] = now + timedelta(seconds=retry_interval)
                    log(f"job {name} crashed ({n}/{max_crashes}), retry in {retry_interval}s: "
                        f"{type(e).__name__} {e}")
        if len(done) > 30:
            done = {k for k in done if k[0] == today}
            retry_at = {k: v for k, v in retry_at.items() if k[0] == today}
            crashes = {k: v for k, v in crashes.items() if k[0] == today}
        time.sleep(20)


def main(argv):
    argv = list(argv)
    if "--profile" in argv:
        i = argv.index("--profile")
        if i + 1 < len(argv):
            settings.apply_profile(argv[i + 1])
            del argv[i:i + 2]
    cfg = settings.load()
    cmd = argv[1] if len(argv) > 1 else "run"
    if cmd == "login":
        return 0 if login(cfg) else 1
    if cmd == "seat":
        return cmd_seat(cfg)
    if cmd == "in":
        return cmd_touch(cfg, "checkin")
    if cmd == "out":
        return cmd_touch(cfg, "checkout")
    if cmd == "run":
        return cmd_run(cfg, dry="--dry" in argv)
    if cmd == "book":
        return cmd_book(cfg, dry="--dry" in argv)
    if cmd == "cancel":
        return cmd_cancel(cfg, dry="--dry" in argv)
    if cmd == "daily":
        return cmd_daily(cfg)
    if cmd == "verify":
        return cmd_verify(cfg)
    print(__doc__)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))