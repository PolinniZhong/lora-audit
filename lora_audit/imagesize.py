# -*- coding: utf-8 -*-
"""纯标准库的图片尺寸读取（PNG / JPEG / GIF / BMP / WebP）。

为什么不用 Pillow：审计页要显示分辨率分布，这是"看一眼就能发现的问题"之一
（训练集里混进 512 的小图很常见）。但为了读一个宽高就背上 Pillow 这个依赖，
对一个只想 `pip install` 一下的用户不划算。

原则：**任何不确定都返回 None，绝不抛异常**。读不出尺寸只是少一条信息，
不能让整个审计失败。
"""
from __future__ import annotations

import os
import struct
from typing import Optional, Tuple

Size = Tuple[int, int]

# 只读文件头这么多字节，够覆盖除 JPEG 外所有格式；JPEG 需要扫描段。
HEAD_BYTES = 65536


def _png(fh) -> Optional[Size]:
    if fh.read(8) != b"\x89PNG\r\n\x1a\n":
        return None
    head = fh.read(8)  # 4 字节长度 + "IHDR"
    if head[4:8] != b"IHDR":
        return None
    w, h = struct.unpack(">II", fh.read(8))
    return int(w), int(h)


def _gif(fh) -> Optional[Size]:
    if fh.read(6) not in (b"GIF87a", b"GIF89a"):
        return None
    w, h = struct.unpack("<HH", fh.read(4))
    return int(w), int(h)


def _bmp(fh) -> Optional[Size]:
    if fh.read(2) != b"BM":
        return None
    fh.read(16)  # 跳过文件头
    w, h = struct.unpack("<ii", fh.read(8))
    return abs(int(w)), abs(int(h))


def _webp(fh) -> Optional[Size]:
    header = fh.read(12)
    if len(header) < 12 or header[0:4] != b"RIFF" or header[8:12] != b"WEBP":
        return None
    chunk = fh.read(4 + 10)
    if len(chunk) < 14:
        return None
    fourcc = chunk[0:4]
    if fourcc == b"VP8X":
        w = int.from_bytes(chunk[8:11], "little") + 1
        h = int.from_bytes(chunk[11:14], "little") + 1
        return w, h
    if fourcc == b"VP8 ":
        # 有损：跳过 3 字节 frame tag + 3 字节起始码，然后 16 位宽高（各 14 位有效）
        body = chunk[8:14]
        if len(body) < 6:
            return None
        w = int.from_bytes(body[3:5], "little") & 0x3FFF
        h = int.from_bytes(body[5:7], "little") & 0x3FFF
        return (w, h) if w and h else None
    if fourcc == b"VP8L":
        body = chunk[8:14]
        if len(body) < 5 or body[0] != 0x2F:
            return None
        bits = int.from_bytes(body[1:5], "little")
        w = (bits & 0x3FFF) + 1
        h = ((bits >> 14) & 0x3FFF) + 1
        return w, h
    return None


def _jpeg(fh) -> Optional[Size]:
    if fh.read(2) != b"\xff\xd8":
        return None
    # SOF0..SOF15 中除 DHT(C4) / JPG(C8) / DAC(CC) 外都带尺寸
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
           0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while True:
        byte = fh.read(1)
        if not byte:
            return None
        if byte != b"\xff":
            continue
        marker = fh.read(1)
        while marker == b"\xff":  # 填充字节
            marker = fh.read(1)
        if not marker:
            return None
        code = marker[0]
        if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:
            continue  # 无长度字段
        if code == 0xD9:  # EOI
            return None
        raw = fh.read(2)
        if len(raw) < 2:
            return None
        seg_len = struct.unpack(">H", raw)[0]
        if seg_len < 2:
            return None
        if code in sof:
            body = fh.read(5)
            if len(body) < 5:
                return None
            h, w = struct.unpack(">HH", body[1:5])
            return int(w), int(h)
        fh.seek(seg_len - 2, os.SEEK_CUR)


_BY_FORMAT = {
    "png": _png, "jpeg": _jpeg, "gif": _gif, "bmp": _bmp, "webp": _webp,
}


def _sniff(head: bytes) -> Optional[str]:
    """按**文件头**判格式。"""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8"):
        return "jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head.startswith(b"BM"):
        return "bmp"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def detect_format(path: str) -> Optional[str]:
    """返回**实际**格式（png / jpeg / gif / bmp / webp），认不出返回 None。永不抛异常。"""
    try:
        with open(path, "rb") as fh:
            return _sniff(fh.read(12))
    except OSError:
        return None


def read_size(path: str) -> Optional[Size]:
    """返回 (宽, 高)；读不出返回 None。永不抛异常。

    ★ 按**文件头**分派解析器，不看扩展名。真实数据集里"`.png` 其实是 WebP"很常见
      （生成/导出工具改了名或直接存了 WebP），按扩展名分派会一律读不出尺寸，
      让 W007（分辨率偏小）与 W008（分辨率不统一）变成盲区。
      —— 这条是拿一个真实第三方公开数据集跑出来的（9 张 .png 全是 VP8L WebP）。
    """
    try:
        with open(path, "rb") as fh:
            fmt = _sniff(fh.read(12))
            if fmt is None:
                return None
            fh.seek(0)
            size = _BY_FORMAT[fmt](fh)
    except (OSError, struct.error, ValueError):
        return None
    if not size:
        return None
    w, h = size
    if w <= 0 or h <= 0 or w > 100000 or h > 100000:
        return None
    return w, h


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
