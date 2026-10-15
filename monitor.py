#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站 UP 主更新监控
------------------------------------------------
原理：定时拉取指定 UP 主的「空间动态」，与本地记录比对，
      发现新内容就通过 Server酱 推送到微信。
可运行于：本地电脑 / GitHub Actions / 任意可联网环境。

运行：python monitor.py
配置：同目录 config.json
密钥：
  SERVERCHAN_SENDKEY  —— Server酱 SendKey（必填才推送）
  BILI_COOKIE         —— 可选，填你自己的 B站 Cookie（含 SESSDATA），
                         加上后能显著降低被风控的概率（详见 README）
"""

import json
import os
import random
import time
from datetime import datetime, timezone, timedelta

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")

FEED_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

DEFAULT_TYPES = [
    "DYNAMIC_TYPE_AV",       # 投稿视频
    "DYNAMIC_TYPE_DRAW",     # 图文动态
    "DYNAMIC_TYPE_WORD",     # 纯文字动态
    "DYNAMIC_TYPE_ARTICLE",  # 专栏
]

MAX_RETRIES = 12          # 单个 UP 每轮最多请求次数（B站风控较严，需多次重试）
REBUILD_EVERY = 3         # 连续失败几次后更换会话/凭证


def log(*args):
    print("[%s]" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def new_session(cookie=""):
    """新建会话：带上 buvid3/buvid4，可选叠加用户自己的 Cookie。"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://www.bilibili.com",
    })
    try:
        spi = s.get(SPI_URL, timeout=15).json()
        d = spi.get("data") or {}
        if d.get("b_3"):
            s.cookies.set("buvid3", d["b_3"])
        if d.get("b_4"):
            s.cookies.set("buvid4", d["b_4"])
    except Exception as e:
        log("  获取 buvid 失败（继续尝试）:", e)

    # 叠加用户 Cookie（形如 "SESSDATA=xxx; bili_jct=xxx"）
    if cookie:
        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                s.cookies.set(k.strip(), v.strip())
    return s


def fetch_dynamics(mid, cookie="", retries=MAX_RETRIES):
    """
    带重试地拉取某 UP 的最新动态。
    返回 list(成功) / None(失败)。返回空列表代表确实没有动态。
    """
    params = {"host_mid": mid, "timezone_offset": -480}
    sess = new_session(cookie)
    last_err = None
    for i in range(retries):
        if i > 0 and i % REBUILD_EVERY == 0:
            log("  → 更换会话与凭证后重试")
            sess = new_session(cookie)
        try:
            r = sess.get(FEED_URL, params=params, timeout=20)
            if r.status_code == 200:
                j = r.json()
                code = j.get("code")
                items = (j.get("data") or {}).get("items") or []
                if code == 0 and items:
                    return items
                # 返回空数据也是一种软风控，继续重试
                last_err = "code=%s items=%d" % (code, len(items))
            else:
                last_err = "http=%s" % r.status_code
        except Exception as e:
            last_err = str(e)
        wait = random.uniform(1.5, 4.0)
        log("  请求未成功（%s），%.1fs 后重试 %d/%d" % (last_err, wait, i + 1, retries))
        time.sleep(wait)
    log("  重试 %d 次仍失败：%s" % (retries, last_err))
    return None


def parse_item(it):
    """把一条动态整理成统一结构。"""
    md = it.get("modules") or {}
    author = md.get("module_author") or {}
    major = (md.get("module_dynamic") or {}).get("major") or {}
    d = {
        "id": it.get("id_str"),
        "type": it.get("type"),
        "pub_ts": int(author.get("pub_ts") or 0) or None,
        "author": author.get("name") or "",
        "title": "",
        "desc": "",
        "url": "https://t.bilibili.com/%s" % it.get("id_str"),
    }
    arch = major.get("archive")
    if arch:
        d["title"] = arch.get("title") or ""
        d["desc"] = arch.get("desc") or ""
        jump = arch.get("jump_url") or ""
        if jump:
            d["url"] = "https:" + jump if jump.startswith("//") else jump
        return d

    draw = major.get("draw")
    if draw:
        txt = draw.get("title") or ""
        if not txt:
            nodes = draw.get("items") or []
            if nodes:
                txt = nodes[0].get("description") or ""
        d["title"] = txt or "[图文动态]"
        return d

    opus = major.get("opus")
    if opus:
        d["title"] = opus.get("title") or "[图文动态]"
        return d

    d["title"] = "[%s]" % (it.get("type") or "动态")
    return d


def push_serverchan(sendkey, title, desp):
    url = "https://sctapi.ftqq.com/%s.send" % sendkey
    try:
        r = requests.post(url, data={"title": title, "desp": desp}, timeout=20)
        try:
            ok = r.json().get("code") == 0
        except Exception:
            ok = r.status_code == 200
        log("  Server酱推送:", r.status_code, r.text[:200])
        return ok
    except Exception as e:
        log("  Server酱推送异常:", e)
        return False


def main():
    cfg = load_json(CONFIG_PATH, {})
    ups = cfg.get("ups") or []
    allow_types = set(cfg.get("allow_types") or DEFAULT_TYPES)
    sendkey = os.environ.get("SERVERCHAN_SENDKEY") or cfg.get("serverchan_sendkey") or ""
    cookie = os.environ.get("BILI_COOKIE") or cfg.get("bili_cookie") or ""

    if not ups:
        log("config.json 里没有配置任何 UP 主，退出。")
        return
    if not sendkey:
        log("警告：未配置 Server酱 SendKey（环境变量 SERVERCHAN_SENDKEY 或 config.json），本次只检测不推送。")
    if not cookie:
        log("提示：未配置 B站 Cookie（环境变量 BILI_COOKIE），风控较严时成功率偏低，可参考 README 配置。")

    state = load_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}

    log("本次监控 %d 个 UP 主" % len(ups))
    pending = []

    for up in ups:
        mid = str(up.get("mid") or "").strip()
        name = up.get("name") or mid
        if not mid or mid == "None":
            continue
        log("检查 %s (mid=%s)" % (name, mid))

        items = fetch_dynamics(mid, cookie=cookie)
        if items is None:
            log("  → 获取失败，跳过（下次再试）")
            continue

        rec = state.setdefault(mid, {"seen": [], "initialized": False})
        seen_ids = set(rec.get("seen") or [])

        if not rec.get("initialized"):
            rec["seen"] = [x.get("id_str") for x in items if x.get("id_str")][:50]
            rec["initialized"] = True
            log("  → 首次运行，记录 %d 条基线（不推送）" % len(rec["seen"]))
            continue

        fresh = []
        for it in items:
            if it.get("type") not in allow_types:
                continue
            d = parse_item(it)
            if d["id"] and d["id"] not in seen_ids:
                fresh.append(d)

        if fresh:
            fresh.sort(key=lambda x: x.get("pub_ts") or 0)
            log("  → 发现 %d 条更新" % len(fresh))
            for d in fresh:
                pending.append((name, d))
            all_ids = [x.get("id_str") for x in items if x.get("id_str")]
            rec["seen"] = list(dict.fromkeys(all_ids + list(seen_ids)))[:50]

    if pending:
        if sendkey:
            lines = []
            for name, d in pending:
                tstr = ""
                if d.get("pub_ts"):
                    tstr = datetime.fromtimestamp(
                        int(d["pub_ts"]), tz=timezone(timedelta(hours=8))
                    ).strftime("%m-%d %H:%M")
                lines.append("- 【%s】%s %s\n  %s" % (name, tstr, d.get("title") or "", d.get("url")))
            push_serverchan(sendkey, "B站更新提醒（%d 条）" % len(pending), "\n".join(lines))
        else:
            log("检测到 %d 条更新，但未配置 SendKey：" % len(pending))
            for name, d in pending:
                log("   -", name, d.get("title"), d.get("url"))

    save_json(STATE_PATH, state)
    log("完成。共推送 %d 条更新。" % (len(pending) if sendkey else 0))


if __name__ == "__main__":
    main()
