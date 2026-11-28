# -*- coding: utf-8 -*-
"""HTTP client for the library H5 API (libyy.qfnu.edu.cn).

The web app encrypts some bodies with AES-CBC/PKCS7:
  key = YYYYMMDD + reverse(YYYYMMDD)   (16 chars)
  iv  = "ZZWBKJ_ZHIHUAWEI"
and wraps them as {"aesjson": "<base64>"}.
"""
import base64
import json
from datetime import datetime

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from . import settings

IV = b"ZZWBKJ_ZHIHUAWEI"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")


def _key():
    d = datetime.now().strftime("%Y%m%d")
    return (d + d[::-1]).encode()


def encrypt_body(obj):
    padder = PKCS7(128).padder()
    raw = padder.update(json.dumps(obj, ensure_ascii=False).encode()) + padder.finalize()
    enc = Cipher(algorithms.AES(_key()), modes.CBC(IV)).encryptor()
    return base64.b64encode(enc.update(raw) + enc.finalize()).decode()


class Client:
    def __init__(self, cfg=None, token=""):
        self.cfg = cfg or settings.load()
        self.base = self.cfg["lib_base"]
        self.token = token
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "lang": "zh",
                               "Referer": self.base + "/h5/index.html",
                               "Origin": self.base})

    def post(self, path, payload=None, encrypted=False, timeout=20):
        body = {"aesjson": encrypt_body(payload)} if encrypted else (payload or {})
        headers = {"authorization": "bearer" + self.token} if self.token else {}
        try:
            r = self.s.post(self.base + path, json=body, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            # 网络抖动/超时：当成一次可重试的失败返回，别让上层任务崩掉
            return 0, {"code": 0, "msg": "network error: %s %s" % (type(e).__name__, e)}
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text[:400]}

    # --- auth -----------------------------------------------------------------
    def exchange_cas(self, cas):
        _, j = self.post("/api/cas/user", {"cas": cas})
        if j.get("code") == 1 and j.get("member"):
            self.token = j["member"].get("token", "")
            return j["member"]
        return None

    # --- business -------------------------------------------------------------
    def my_seat(self):
        return self.post("/api/Member/seat", {"page": 1, "limit": 20})

    def seat_dates(self, build_id):
        """Days/times that can be booked for a building, e.g. [{day, times:[{id,start,end,status}]}]."""
        return self.post("/api/Seat/date", {"build_id": build_id})

    def seat_list(self, area, segment, day, start, end, label_id=""):
        p = {"area": area, "segment": segment, "day": day,
             "startTime": start, "endTime": end}
        if label_id:
            p["label_id"] = label_id
        return self.post("/api/Seat/seat", p)

    def book(self, seat_id, segment):
        return self.post("/api/Seat/confirm", {"seat_id": seat_id, "segment": segment},
                         encrypted=True)

    def cancel(self, booking_id):
        return self.post("/api/Space/cancel", {"id": booking_id})

    def checkin(self):
        return self.post("/api/Seat/touch_qr_books", {"method": "checkin"}, encrypted=True)

    def checkout(self):
        return self.post("/api/Seat/touch_qr_books", {"method": "checkout"}, encrypted=True)

    def bookings(self):
        _, j = self.my_seat()
        return (j.get("data") or {}).get("data") or []