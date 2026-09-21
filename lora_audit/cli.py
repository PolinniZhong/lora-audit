# -*- coding: utf-8 -*-
"""命令行入口。

    lora-audit scan ./dataset              # 生成审计页（默认 <dataset>/_lora_audit/report.html）
    lora-audit scan ./dataset --open       # 顺手打开
    lora-audit scan ./dataset --json -     # 机读结果打到 stdout，可进 CI
    lora-audit scan ./dataset --strict     # 有警告也返回退出码 1
    lora-audit verify report.html          # 检查产物是否真的离线可用

退出码：0 通过 / 1 发现问题 / 2 参数或 IO 错误。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import List, Optional, Tuple

from . import __version__
from .report import REMOTE_ALLOWLIST, build_payload, render
from .rules import audit, consensus_of, summarize
from .scan import scan

DEFAULT_OUT_DIR = "_lora_audit"
DEFAULT_OUT_NAME = "report.html"

SEV_ORDER = {"error": 0, "warn": 1, "info": 2}
SEV_MARK = {"error": "✗", "warn": "!", "info": "·"}


def _print_findings(findings, out=None) -> None:
    """把 findings 打到指定流（`--json -` 时要走 stderr，别污染 stdout 的 JSON）。"""
    out = out or sys.stdout
    for f in sorted(findings, key=lambda x: SEV_ORDER.get(x.sev, 9)):
        mark = SEV_MARK.get(f.sev, "·")
        count = f" [{len(f.items)} 张]" if f.items else ""
        print(f"  {mark} {f.id} {f.title}{count}", file=out)
        if f.sev != "info":
            print(f"      {f.detail}", file=out)


def _resolve_out(dataset_root: str, out: Optional[str]) -> str:
    if out:
        # 给的是目录就以默认名落进去
        if os.path.isdir(out) or out.endswith(os.sep):
            return os.path.join(os.path.abspath(out), DEFAULT_OUT_NAME)
        return os.path.abspath(out)
    return os.path.join(dataset_root, DEFAULT_OUT_DIR, DEFAULT_OUT_NAME)


def cmd_scan(args) -> int:
    root = os.path.abspath(args.dataset or os.getcwd())
    if not os.path.isdir(root):
        print(f"lora-audit: 不是一个目录：{root}", file=sys.stderr)
        return 2

    ds = scan(root)
    if not ds.images:
        print(f"lora-audit: 在 {root} 里没找到任何图片"
              "（支持 png / jpg / jpeg / webp / bmp / gif / tif / avif）", file=sys.stderr)
        return 2

    findings = audit(ds)
    cons = consensus_of(ds.images)
    summary = summarize(ds, findings)

    out_path = _resolve_out(root, args.out)
    out_dir = os.path.dirname(out_path)
    try:
        os.makedirs(out_dir, exist_ok=True)
        html = render(ds, findings, cons, out_dir, title=args.title or "")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(html)
    except OSError as exc:
        print(f"lora-audit: 写报告失败：{exc}", file=sys.stderr)
        return 2

    payload = build_payload(ds, findings, cons, out_dir, title=args.title or "")
    if args.json:
        blob = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.json == "-":
            print(blob)
        else:
            try:
                with open(args.json, "w", encoding="utf-8") as fh:
                    fh.write(blob + "\n")
            except OSError as exc:
                print(f"lora-audit: 写 JSON 失败：{exc}", file=sys.stderr)
                return 2

    # ★ `--json -` 时人类摘要必须走 stderr：否则 stdout 是"JSON + 摘要"，
    #   `lora-audit scan --json - | jq` 直接解析失败 —— 而这正是 README 推荐的 CI 用法。
    say = (lambda *a, **k: print(*a, file=sys.stderr, **k)) if args.json == "-" else print
    STDERR = sys.stderr
    if not args.quiet:
        say(f"数据集　{root}")
        say(f"图片　　{summary['images']} 张 · "
              f"逐图 caption {summary['sidecar']} · "
              f"default 兜底 {summary['default']} · "
              f"无 caption {summary['none']} · "
              f"分组 {summary['groups']}")
        if cons.value:
            say(f"触发词　{cons.value}（覆盖 {cons.coverage * 100:.0f}%）")
        say(f"结果　　{summary['errors']} 错误 · {summary['warnings']} 警告")
        _print_findings(findings, out=STDERR if args.json == "-" else None)
        say(f"\n报告　　{out_path}")
        say("　　　　双击打开即可（只读页面，不会改动数据集）")

    if args.open:
        import webbrowser
        webbrowser.open("file://" + out_path)

    if summary["errors"]:
        return 1
    if args.strict and summary["warnings"]:
        return 1
    return 0


# ---------------------------------------------------------------- verify

#: 产物里绝对不该出现的东西：远程资源、ES Module、运行时请求
FORBIDDEN = [
    (re.compile(r"""\b(?:src|href)\s*=\s*["']https?://""", re.I), "远程资源引用"),
    (re.compile(r"""url\(\s*["']?https?://""", re.I), "CSS 远程资源"),
    (re.compile(r"""@import\b""", re.I), "CSS @import"),
    (re.compile(r"""type\s*=\s*["']module["']""", re.I), "ES Module（file:// 下会被 CORS 拦掉）"),
    (re.compile(r"""\bfetch\s*\("""), "fetch 调用"),
    (re.compile(r"""\bXMLHttpRequest\b"""), "XMLHttpRequest"),
]


def _images_reachable(html_path: str, srcs: List[str]) -> Tuple[int, int]:
    base = os.path.dirname(os.path.abspath(html_path))
    missing = 0
    from urllib.parse import unquote
    for src in srcs:
        if src.startswith("file://"):
            continue
        if not os.path.exists(os.path.join(base, unquote(src))):
            missing += 1
    return len(srcs), missing


def cmd_verify(args) -> int:
    path = os.path.abspath(args.report)
    if not os.path.isfile(path):
        print(f"lora-audit: 找不到报告文件：{path}", file=sys.stderr)
        return 2
    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()

    problems: List[str] = []
    for pattern, label in FORBIDDEN:
        m = pattern.search(html)
        if m and not any(a in m.group(0) for a in REMOTE_ALLOWLIST):
            line = html.count("\n", 0, m.start()) + 1
            problems.append(f"{label}（第 {line} 行）")

    data_match = re.search(
        r'<script type="application/json" id="la-data">(.*?)</script>', html, re.S)
    srcs: List[str] = []
    if not data_match:
        problems.append("找不到内联数据块 #la-data")
    else:
        raw = data_match.group(1).replace("<\\/", "</")
        try:
            data = json.loads(raw)
            srcs = [i["src"] for i in data.get("images", [])]
            print(f"数据块　　OK（{len(data.get('images', []))} 张图 · "
                  f"{len(data.get('findings', []))} 条检查结果）")
        except ValueError as exc:
            problems.append(f"内联数据块不是合法 JSON：{exc}")

    if srcs:
        total, missing = _images_reachable(path, srcs)
        if missing:
            problems.append(f"{missing} / {total} 张图按相对路径找不到"
                            "（报告被移动过？把它放回数据集旁边）")
        else:
            print(f"图片引用　OK（{total} 张全部可达）")

    print(f"文件大小　{os.path.getsize(path) / 1024:.0f} KB")
    if problems:
        print("\n不通过：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("不变量　　OK（无远程资源 · 无 ES Module · 无运行时请求）")
    print("\n通过：这个报告可以离线双击打开。")
    return 0


# ---------------------------------------------------------------- 入口

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="lora-audit",
        description="LoRA 训练资产的只读审计视图：不用起服务、不用改你的文件夹结构。",
    )
    ap.add_argument("--version", action="version", version=f"lora-audit {__version__}")
    sub = ap.add_subparsers(dest="command")

    scan_p = sub.add_parser("scan", help="扫描一个训练文件夹并生成审计页")
    scan_p.add_argument("dataset", nargs="?", default=".",
                        help="数据集目录（默认当前目录）")
    scan_p.add_argument("-o", "--out", default=None,
                        help=f"输出 HTML 路径或目录（默认 <数据集>/{DEFAULT_OUT_DIR}/{DEFAULT_OUT_NAME}）")
    scan_p.add_argument("--json", default=None, metavar="PATH",
                        help="同时输出机读 JSON；用 - 打到 stdout")
    scan_p.add_argument("--title", default=None, help="报告标题（默认取目录名）")
    scan_p.add_argument("--strict", action="store_true", help="有警告也返回退出码 1")
    scan_p.add_argument("--open", action="store_true", help="生成后用浏览器打开")
    scan_p.add_argument("-q", "--quiet", action="store_true", help="只在终端打印报告路径")
    scan_p.set_defaults(func=cmd_scan)

    ver_p = sub.add_parser("verify", help="检查报告是否真的离线可用（远程资源 / ES Module / 图片可达）")
    ver_p.add_argument("report", help="要检查的 HTML 文件")
    ver_p.set_defaults(func=cmd_verify)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "command", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
