#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一个**合成的小数据集**，用来当场看到审计效果。

刻意做进 6 种真实会犯的错，每一种都对应报告里的一条规则：
  - 2 张图没有 caption                → E001
  - 1 个 caption 文件是空的           → W001
  - 2 张图 caption 一字不差           → W002
  - 1 张图触发词写错                  → W003
  - 1 张图只有 default_caption 兜底   → W004
  - 1 个文件名带空格                  → W005
  - 1 个孤儿 caption                  → W006
  - 1 张 256×256 的小图               → W007
  - 1 个 .jpg 里其实装着 PNG          → W013
  - 混入 .DS_Store                    → W010

图片用标准库现写 PNG（不装 Pillow），所以这个脚本在裸机上也能跑。

    python3 examples/make_example.py
    lora-audit scan examples/demo-dataset --open
"""
from __future__ import annotations

import os
import shutil
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "demo-dataset")

TRIGGER = "demochan"
IDENTITY = ("demochan, 3d cartoon character, plain white studio background, "
            "soft even lighting")


def write_png(path: str, width: int, height: int, rgb=(210, 226, 245)) -> None:
    """写一张纯色 PNG。只用标准库 —— 生成 fixture 不该引入依赖。"""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


#: (文件名, 宽, 高, caption 或 None 表示不写)
IMAGES = [
    ("001_front.png", 1024, 1365, f"{TRIGGER}, full body, front view, neutral A-pose"),
    ("002_side.png", 1024, 1365, f"{TRIGGER}, full body, side view, neutral A-pose"),
    ("003_back.png", 1024, 1365, f"{TRIGGER}, full body, back view, neutral A-pose"),
    ("004_smile.png", 1024, 1365, f"{TRIGGER}, headshot, gentle smile"),
    ("005_front.png", 1024, 1365, f"{TRIGGER}, full body, front view, neutral A-pose"),  # 与 001 重复
    ("006_think.png", 1024, 1365, f"demochar, headshot, thinking expression"),           # 触发词漂移
    ("007_sit.png", 1024, 1365, ""),                                                     # 空 caption
    ("008_walk.png", 1024, 1365, f"{TRIGGER}, full body, walking pose"),
    ("009_tiny.png", 256, 256, f"{TRIGGER}, headshot, surprised expression"),            # 分辨率偏小
    ("010 jump.png", 1024, 1365, f"{TRIGGER}, full body, jumping pose"),                 # 文件名带空格
    ("011_face.png", 1024, 1365, None),
    # PNG 字节 + .jpg 扩展名：真实数据集里"扩展名骗人"很常见（拿真数据跑出来的）
    ("013_mislabeled.jpg", 1024, 1365, f"{TRIGGER}, full body, three-quarter view, relaxed arms"),                                                  # 无 caption
    ("012_full.png", 1024, 1365, None),                                                  # 无 caption（靠 default 兜底）
]


def main() -> int:
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    for name, w, h, caption in IMAGES:
        write_png(os.path.join(OUT, name), w, h)
        if caption is not None:
            write_text(os.path.join(OUT, os.path.splitext(name)[0] + ".txt"), caption)

    # 只有 012 能继承到它：放在子目录里，default_caption 就近向上找
    sub = os.path.join(OUT, "extra")
    os.makedirs(sub)
    shutil.move(os.path.join(OUT, "012_full.png"), os.path.join(sub, "012_full.png"))
    write_text(os.path.join(sub, "default_caption.txt"), IDENTITY)

    # 孤儿 caption：有 .txt 没有同名图
    write_text(os.path.join(OUT, "013_deleted.txt"), f"{TRIGGER}, was removed by hand")

    # 系统杂物
    write_text(os.path.join(OUT, ".DS_Store"), "not really a DS_Store, just a fixture\n")

    exts = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
    count = len([n for n in os.listdir(OUT) if n.lower().endswith(exts)]) + 1
    print(f"已生成示例数据集：{OUT}")
    print(f"  图片 {count} 张 · 触发词 {TRIGGER} · caption 错误 6 种")
    print("\n下一步：")
    print(f"  lora-audit scan {os.path.relpath(OUT)} --open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
