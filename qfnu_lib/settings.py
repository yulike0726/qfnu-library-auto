# -*- coding: utf-8 -*-
"""Configuration + shared helpers.

Multiple library accounts are supported through a *profile*:
  QFNU_PROFILE=qzm / --profile qzm  ->  config.qzm.json  +  .qfnu-state/qzm/
  (no profile)                      ->  config.json      +  .qfnu-state/
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = ""
STATE = os.path.join(ROOT, ".qfnu-state")
CONFIG_PATH = os.path.join(ROOT, "config.json")


def apply_profile(name):
    """Switch the active account profile (safe to call after import)."""
    global PROFILE, STATE, CONFIG_PATH
    PROFILE = (name or "").strip()
    STATE = (os.path.join(ROOT, ".qfnu-state", PROFILE) if PROFILE
             else os.path.join(ROOT, ".qfnu-state"))
    CONFIG_PATH = (os.path.join(ROOT, "config.%s.json" % PROFILE) if PROFILE
                   else os.path.join(ROOT, "config.json"))
    return PROFILE


apply_profile(os.environ.get("QFNU_PROFILE", ""))

DEFAULTS = {
    "account": "",
    "password": "",
    "lib_base": "http://libyy.qfnu.edu.cn",
    "cas_base": "https://ids.qfnu.edu.cn",
    "service": "http://libyy.qfnu.edu.cn/api/cas/cas",
    "edge_exe": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "edge_profile": os.path.join(ROOT, "tools", "edge-profile-clean"),
    "cdp_port": 9222,
    "checkin_advance_sec": 5,
    "checkin_retry_sec": 60,
    "checkin_max_minutes": 40,
}


def load():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        cfg.update(json.load(open(CONFIG_PATH, encoding="utf-8")))
    # account/password fall back to the shared .qfnu-state/config.json
    legacy = os.path.join(STATE, "config.json")
    if os.path.exists(legacy):
        old = json.load(open(legacy, encoding="utf-8"))
        cfg["account"] = cfg["account"] or old.get("account", "")
        cfg["password"] = cfg["password"] or old.get("password", "")
    return cfg


def session_file():
    return os.path.join(STATE, "lib_session.json")