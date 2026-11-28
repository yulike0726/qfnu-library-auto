# -*- coding: utf-8 -*-
"""钉钉群机器人提醒：出问题时推到手机。

配置（config.json）：
  dingtalk_webhook   群机器人的 Webhook 地址（必填，留空则不发）
  dingtalk_secret    安全设置选「加签」时填的密钥（推荐）
  dingtalk_keyword   安全设置选「自定义关键词」时填关键词，默认「图书馆」，
                     发消息时会自动带上，保证不被钉钉拦掉
  dingtalk_at_mobiles  需要 @ 的手机号列表，例如 ["13800000000"]
  dingtalk_at_all    是否 @ 所有人（默认 false）

只用 requests，不引入其它依赖。
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.parse

import requests

DEFAULT_KEYWORD = "图书馆"


def _signed_url(webhook, secret):
    """加签：timestamp + "\\n" + secret 做 HmacSHA256，base64 后 urlencode。"""
    if not secret:
        return webhook
    ts = str(round(time.time() * 1000))
    string_to_sign = ts + "\n" + secret
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                      hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest))
    sep = "&" if "?" in webhook else "?"
    return webhook + sep + "timestamp=" + ts + "&sign=" + sign


def send(cfg, text, timeout=10):
    """发一条文本消息。返回 (ok, detail)；未配置 webhook 时返回 (False, "not configured")。"""
    webhook = str(cfg.get("dingtalk_webhook") or "").strip()
    if not webhook:
        return False, "not configured"
    keyword = str(cfg.get("dingtalk_keyword") or DEFAULT_KEYWORD)
    if keyword and keyword not in text:
        text = "【" + keyword + "】" + text
    payload = {
        "msgtype": "text",
        "text": {"content": text},
        "at": {
            "atMobiles": [str(m) for m in (cfg.get("dingtalk_at_mobiles") or []) if m],
            "isAtAll": bool(cfg.get("dingtalk_at_all")),
        },
    }
    try:
        r = requests.post(_signed_url(webhook, str(cfg.get("dingtalk_secret") or "").strip()),
                          json=payload, timeout=timeout)
        j = r.json()
    except Exception as e:  # 网络问题、非 JSON 响应都不该影响主流程
        return False, "%s %s" % (type(e).__name__, e)
    ok = j.get("errcode") == 0
    return ok, json.dumps(j, ensure_ascii=False)[:200]