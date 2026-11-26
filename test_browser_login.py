# -*- coding: utf-8 -*-
"""Test the browser slider fallback on a throwaway profile (port 9223)."""
import os
import sys

from qfnu_lib import cas, settings

cfg = settings.load()
cfg["cdp_port"] = 9223
cfg["edge_profile"] = os.path.join(settings.ROOT, "tools", "edge-profile-test")

print("launching edge on 9223 ...", flush=True)
cas.launch_edge(cfg)
print("port up:", cas.wait_port(9223, 40), flush=True)
tok = cas.browser_login(cfg, tries=3)
print("CASTGC:", (tok[:40] + "...") if tok else "NONE", flush=True)
if tok:
    ticket = cas.ticket_from_castgc(cfg, tok)
    print("ticket:", (ticket[:40] + "...") if ticket else "NONE", flush=True)
    code = cas.exchange(cfg, ticket) if ticket else ""
    print("cas code:", code or "NONE", flush=True)