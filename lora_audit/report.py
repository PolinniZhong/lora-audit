# -*- coding: utf-8 -*-
"""把审计结果渲染成**一个自包含的 HTML 文件**。

为什么是单文件：
  - 用户拿到的是一个能双击、能发微信、能丢进 issue 的东西，不是一棵目录树；
  - 没有 css/ js/ 相对引用，就不会有"拷漏一个文件就白屏"的事故；
  - 图片仍然走**相对路径引原图**（零拷贝、秒出），所以报告要放在数据集附近才不会
    断图——这一点在页脚明确写出来。

产物里没有远程资源、没有 ES Module、没有 fetch：`file://` 直接打开即可。
`lora-audit verify <html>` 会把这三条当不变量检查一遍。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Dict, List
from urllib.parse import quote

from . import __version__
from .rules import Finding, TriggerConsensus, summarize
from .scan import Dataset

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

#: 生成物里出现的远程地址白名单（空 = 一个都不许有）
REMOTE_ALLOWLIST: tuple = ()


def _read_static(name: str) -> str:
    with open(os.path.join(STATIC_DIR, name), "r", encoding="utf-8") as fh:
        return fh.read()


def _img_src(abs_path: str, out_dir: str) -> str:
    """相对输出目录算图片地址；跨盘符退化成本地 file:// URI。"""
    try:
        rel = os.path.relpath(abs_path, out_dir).replace(os.sep, "/")
    except ValueError:
        from pathlib import Path
        return Path(abs_path).as_uri()
    return quote(rel, safe="/~@:")


def build_payload(ds: Dataset, findings: List[Finding], cons: TriggerConsensus,
                  out_dir: str, title: str = "") -> dict:
    images = []
    for img in ds.images:
        item = img.to_dict()
        item["src"] = _img_src(os.path.join(ds.root, img.rel), out_dir)
        images.append(item)

    finding_dicts = [f.to_dict() for f in findings]
    # 每张图挂了哪些规则（前端按规则筛图用）
    by_rel: Dict[str, List[str]] = {}
    for f in finding_dicts:
        for rel in f["items"]:
            by_rel.setdefault(rel, []).append(f["id"])
    for item in images:
        item["findings"] = by_rel.get(item["rel"], [])

    return {
        "tool": "lora-audit",
        "version": __version__,
        "generated": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "title": title or f"{ds.name} · 训练集审计",
        "dataset": {"root": ds.root, "name": ds.name},
        "summary": summarize(ds, findings),
        "layout": ds.notes,
        "trigger": cons.to_dict(),
        "ignored": ds.ignored,
        "groups": [{"name": g, "count": sum(1 for i in ds.images if i.group == g)}
                   for g in ds.groups],
        "meta": [m.to_dict() for m in ds.meta],
        "images": images,
        "findings": finding_dicts,
    }


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))


def render(ds: Dataset, findings: List[Finding], cons: TriggerConsensus,
           out_dir: str, title: str = "") -> str:
    payload = build_payload(ds, findings, cons, out_dir, title)
    # `</` 必须转义：否则 caption 里出现 "</script>" 会把数据块提前截断
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_json = data_json.replace("</", "<\\/")

    css = _read_static("report.css")
    js = _read_static("report.js")

    return f"""<!doctype html>
<html lang="zh-CN" data-alc-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<meta name="theme-color" content="#0D0F13">
<meta name="generator" content="lora-audit {__version__}">
<meta name="robots" content="noindex, nofollow">
<!-- data: 空图标：避免 Chrome 为 file:// 页面去请求 favicon.ico 而在控制台留下一条
     ERR_FILE_NOT_FOUND —— 那条噪声会掩盖真正该看的问题 -->
<link rel="icon" href="data:,">
<title>{_esc(payload["title"])}</title>
<style>
{css}
</style>
</head>
<body>
<a class="alc-skip" href="#la-main">跳到主内容</a>
<div class="alc-app">
  <div class="alc-topbar">
    <header class="alc-head">
      <div class="alc-head-main">
        <h1 class="alc-brand">
          <span class="alc-brand-mark" aria-hidden="true"></span>
          <span data-bind="title"></span>
        </h1>
        <div class="alc-head-right">
          <span class="alc-head-meta" data-bind="root"></span>
          <button class="alc-icon-btn" type="button" id="la-theme" title="切换深浅色"
                  aria-label="切换深浅色">◐</button>
        </div>
      </div>
    </header>
    <div class="alc-metabar">
      <div class="la-chips" data-bind="summary" role="list"></div>
    </div>
    <div class="alc-toolbar">
      <div class="la-search">
        <input type="search" id="la-q" placeholder="搜文件名或 caption…"
               aria-label="搜索文件名或 caption" autocomplete="off" spellcheck="false">
      </div>
      <div class="la-filters" data-bind="filters" role="group" aria-label="按问题筛选"></div>
    </div>
  </div>

  <main id="la-main" class="alc-main">
    <section class="la-section" aria-labelledby="la-findings-h">
      <h2 id="la-findings-h" class="la-h2">检查结果 <span class="la-h2-note" data-bind="finding-count"></span></h2>
      <div class="la-findings" data-bind="findings"></div>
    </section>

    <section class="la-section" aria-labelledby="la-grid-h">
      <h2 id="la-grid-h" class="la-h2">图片 <span class="la-h2-note" data-bind="grid-count"></span></h2>
      <div class="la-grid" data-bind="grid"></div>
      <p class="la-empty" data-bind="empty" hidden>没有匹配的图片。</p>
    </section>
  </main>

  <footer class="alc-foot">
    <span>由 <strong>lora-audit {__version__}</strong> 生成于 <span data-bind="generated"></span> · 只读页面，不会修改你的数据集</span>
    <span class="alc-foot-hint">图片按相对路径引用：移动本报告时请与数据集一起移动，否则会断图</span>
  </footer>
</div>

<div class="alc-drawer" id="la-drawer" hidden>
  <div class="alc-drawer-panel" role="dialog" aria-modal="true" aria-labelledby="la-drawer-title">
    <div class="alc-drawer-head">
      <span class="alc-drawer-title" id="la-drawer-title">图片详情</span>
      <button class="alc-icon-btn" type="button" data-close="drawer" aria-label="关闭">✕</button>
    </div>
    <div class="alc-drawer-body" data-bind="drawer-body"></div>
  </div>
</div>

<div class="alc-lightbox" id="la-lightbox" hidden>
  <button class="alc-icon-btn alc-lb-close" type="button" data-close="lightbox" aria-label="关闭">✕</button>
  <img alt="" data-bind="lb-img">
  <div class="alc-lb-cap" data-bind="lb-cap"></div>
</div>

<script type="application/json" id="la-data">{data_json}</script>
<script>
{js}
</script>
</body>
</html>
"""
