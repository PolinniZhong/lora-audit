# -*- coding: utf-8 -*-
"""扫描一个普通训练文件夹，产出结构化的审计输入。

**这一步不做任何判断**，只负责把"文件夹里到底有什么"如实读出来：
哪些图、每张图的 caption 从哪来、触发词是什么、有没有分组、有没有清单文件。
判断全在 rules.py。分开的好处是规则可以单独演进、单独测试。

支持的现实布局（都能读，不要求用户改结构）：

    dataset/                      dataset/
    ├── img001.png                ├── img/
    ├── img001.txt                │   ├── 01_face/ a.png + a.txt
    └── img002.png (无 caption)   │   └── 03_full/ b.png + b.txt
                                  ├── cap_kohya/ ...     ← 双 profile
    （kohya 平铺）                 └── default_caption.txt
                                  （ai-toolkit / 带身份块）
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .imagesize import detect_format, read_size

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif"}
CAPTION_EXTS = (".txt", ".caption", ".tags")

#: 这些 .txt 不是"逐图 caption sidecar"，而是数据集级别的元文件
META_STEMS = {
    "default_caption", "train", "val", "valid", "validation", "test",
    "smoke_test_prompts", "readme", "license", "notes", "trigger", "triggers",
}
META_PREFIXES = ("train", "val", "test")

#: 明确要报出来的系统杂物
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "icon\r", ".localized"}
JUNK_PREFIXES = ("._",)

SKIP_DIRS = {"__pycache__", "__macosx", "node_modules"}

#: 可选的豁免声明：一行一个规则 ID，`#` 之后是理由。**缺席 = 一条都不豁免**。
#: 豁免不是隐藏——被豁免的规则在报告里降级为 info 并标注「已豁免」，理由一并展示。
IGNORE_NAME = ".lora-audit-ignore"

#: kohya 的 `10_name` / `5_name` 重复次数目录
REPEAT_DIR = re.compile(r"^\d+_.+")


@dataclass
class ImageEntry:
    """一张训练图，以及它的 caption 从哪来。"""

    rel: str                      # 相对数据集根，posix 风格
    name: str
    ext: str
    group: str                    # 相对子目录，根下为 ""
    size_bytes: int
    width: Optional[int] = None
    height: Optional[int] = None
    #: 按文件头判出的**实际**格式（与扩展名可能不符，见 W013）
    actual_format: Optional[str] = None
    #: "sidecar"（逐图文件）| "default"（继承 default_caption）| "none"
    cap_source: str = "none"
    caption: Optional[str] = None
    caption_rel: Optional[str] = None
    trigger: Optional[str] = None

    @property
    def has_caption(self) -> bool:
        return bool(self.caption and self.caption.strip())

    @property
    def short_side(self) -> Optional[int]:
        if self.width and self.height:
            return min(self.width, self.height)
        return None

    def to_dict(self) -> dict:
        return {
            "rel": self.rel, "name": self.name, "ext": self.ext, "group": self.group,
            "bytes": self.size_bytes, "w": self.width, "h": self.height,
            "fmt": self.actual_format,
            "capSource": self.cap_source, "caption": self.caption,
            "captionRel": self.caption_rel, "trigger": self.trigger,
        }


@dataclass
class MetaFile:
    rel: str
    role: str
    lines: List[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {"rel": self.rel, "role": self.role, "lines": self.lines, "note": self.note}


@dataclass
class Dataset:
    root: str
    name: str
    images: List[ImageEntry] = field(default_factory=list)
    meta: List[MetaFile] = field(default_factory=list)
    junk: List[str] = field(default_factory=list)
    orphans: List[str] = field(default_factory=list)     # 有 caption 没图
    notes: List[str] = field(default_factory=list)       # 布局识别结论
    default_captions: Dict[str, str] = field(default_factory=dict)  # rel -> 文本
    #: 规则 ID → 豁免理由（来自可选的 .lora-audit-ignore）
    ignored: Dict[str, str] = field(default_factory=dict)

    @property
    def groups(self) -> List[str]:
        seen: List[str] = []
        for img in self.images:
            if img.group and img.group not in seen:
                seen.append(img.group)
        return sorted(seen)

    @property
    def total_bytes(self) -> int:
        return sum(img.size_bytes for img in self.images)


def _is_junk(name: str) -> bool:
    low = name.lower()
    if low in JUNK_NAMES:
        return True
    return any(name.startswith(p) for p in JUNK_PREFIXES)


def _is_meta_txt(stem: str) -> bool:
    low = stem.lower()
    if low in META_STEMS:
        return True
    return any(low.startswith(p + "_") or low == p for p in META_PREFIXES)


def _relpath(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _read_text(path: str) -> Optional[str]:
    """读 caption。编码不确定，按常见顺序试；失败返回 None（不要猜）。"""
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                return fh.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError:
            return None
    return None


def extract_trigger(caption: Optional[str]) -> Optional[str]:
    """触发词 = caption 的第一个逗号分段。没有逗号就取首个词。

    这是社区事实约定（kohya / ai-toolkit 都把触发词放句首），不是我们的发明。
    """
    if not caption:
        return None
    first = caption.strip().split(",")[0].strip()
    if not first:
        return None
    if " " in first:
        first = first.split()[0]
    return first or None


def _walk(root: str):
    """遍历数据集，跳过隐藏目录、我们自己的产物目录和依赖目录。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in sorted(dirnames)
            if not d.startswith(".") and d.lower() not in SKIP_DIRS and d != "_lora_audit"
        ]
        yield dirpath, filenames


def scan(root: str) -> Dataset:
    """扫描 ``root``，返回结构化结果。只读，不改动任何文件。"""
    root = os.path.abspath(root)
    ds = Dataset(root=root, name=os.path.basename(root.rstrip(os.sep)) or root)

    # 可选豁免声明。它是**用户**写的，工具只读；缺席时行为与过去完全一致。
    ignore_path = os.path.join(root, IGNORE_NAME)
    if os.path.isfile(ignore_path):
        for line in (_read_text(ignore_path) or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rule_id, _, why = line.partition("#")
            rule_id = rule_id.strip().upper()
            if rule_id:
                ds.ignored[rule_id] = why.strip()

    image_paths: List[str] = []
    caption_files: Dict[str, str] = {}   # 无扩展名键：同目录同 stem
    list_files: List[str] = []
    defaults: Dict[str, str] = {}        # 目录绝对路径 -> default_caption 文本

    for dirpath, filenames in _walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if _is_junk(name):
                ds.junk.append(_relpath(root, path))
                continue
            stem, ext = os.path.splitext(name)
            low_ext = ext.lower()
            if low_ext in IMAGE_EXTS:
                image_paths.append(path)
            elif low_ext in CAPTION_EXTS:
                if stem.lower() == "default_caption":
                    text = _read_text(path)
                    if text is not None:
                        defaults[dirpath] = text
                        ds.meta.append(MetaFile(
                            rel=_relpath(root, path), role="default_caption",
                            note="身份块/兜底 caption"))
                        continue
                if _is_meta_txt(stem):
                    list_files.append(path)
                    continue
                caption_files[os.path.join(dirpath, stem)] = path
            elif low_ext in (".json", ".jsonl", ".yaml", ".yml"):
                ds.meta.append(MetaFile(rel=_relpath(root, path), role=low_ext.lstrip("."),
                                        note="数据集元文件（本工具只登记，不解析）"))

    ds.default_captions = {_relpath(root, d): t for d, t in defaults.items()}

    def _find_default(dirpath: str) -> Optional[str]:
        """就近向上找 default_caption.txt，最远到数据集根。"""
        current = dirpath
        while True:
            if current in defaults:
                return defaults[current]
            if os.path.normpath(current) == os.path.normpath(root):
                return None
            parent = os.path.dirname(current)
            if parent == current or not current.startswith(root):
                return None
            current = parent

    used_captions = set()
    for path in sorted(image_paths):
        dirpath = os.path.dirname(path)
        name = os.path.basename(path)
        stem, ext = os.path.splitext(name)
        entry = ImageEntry(
            rel=_relpath(root, path),
            name=name,
            ext=ext.lower(),
            group=_relpath(root, dirpath) if dirpath != root else "",
            size_bytes=os.path.getsize(path),
        )
        entry.actual_format = detect_format(path)
        size = read_size(path)
        if size:
            entry.width, entry.height = size

        sidecar = caption_files.get(os.path.join(dirpath, stem))
        if sidecar:
            entry.cap_source = "sidecar"
            entry.caption = _read_text(sidecar)
            entry.caption_rel = _relpath(root, sidecar)
            used_captions.add(os.path.join(dirpath, stem))
        else:
            inherited = _find_default(dirpath)
            if inherited is not None:
                entry.cap_source = "default"
                entry.caption = inherited
                entry.caption_rel = next(
                    (rel for rel, t in ds.default_captions.items() if t is inherited), None)
            else:
                entry.cap_source = "none"

        entry.trigger = extract_trigger(entry.caption)
        ds.images.append(entry)

    ds.orphans = sorted(
        _relpath(root, p) for key, p in caption_files.items() if key not in used_captions
    )

    # 「镜像 caption 树」：cap_kohya/、captions/ 这类目录装的是同一批图的**另一套**
    # caption（例如 kohya 全量句 vs 逐图变量）。它们天然没有同名图片，
    # 按"找不到同名图"直接判孤儿会是满屏误报——这正是拿真实文件夹跑出来的教训。
    image_stems = {os.path.splitext(img.name)[0] for img in ds.images}
    mirrored: Dict[str, int] = {}
    real_orphans: List[str] = []
    for rel in ds.orphans:
        stem = os.path.splitext(os.path.basename(rel))[0]   # rel 带扩展名，比较要去掉
        if stem in image_stems:                        # 路径不同但同名 → 另一套 caption
            top = rel.split("/")[0] if "/" in rel else ""
            mirrored[top] = mirrored.get(top, 0) + 1
        else:
            real_orphans.append(rel)
    ds.orphans = sorted(real_orphans)
    for top, n in sorted(mirrored.items()):
        if top:
            ds.notes.append(f"检测到镜像 caption 树 {top}/：{n} 张图的另一套 caption")
            ds.meta.append(MetaFile(rel=f"{top}/", role="caption profile",
                                    note=f"与图片树平行的 {n} 个 caption 文件"))
        else:
            ds.notes.append(f"检测到另一套扩展名的 caption：{n} 个")

    for path in sorted(list_files):
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        role = "train list" if stem.startswith("train") else (
            "val list" if stem.startswith("val") else (
                "test list" if stem.startswith("test") else "meta text"))
        text = _read_text(path) or ""
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln and not ln.startswith("#")]
        ds.meta.append(MetaFile(rel=_relpath(root, path), role=role, lines=lines))

    # ---- 布局识别（只描述观察到的事实，不下"你错了"的判断）----
    depths = {img.group.count("/") + 1 if img.group else 0 for img in ds.images}
    if depths == {0}:
        ds.notes.append("图片全部平铺在数据集根目录")
    elif 0 in depths:
        ds.notes.append("图片既有平铺的、也有放在子目录里的（混合布局）")
    else:
        ds.notes.append("图片按子目录分组")

    top_dirs = {img.group.split("/")[0] for img in ds.images if img.group}
    if "img" in top_dirs:
        ds.notes.append("检测到 img/ 目录：ai-toolkit 风格的数据集组织")
    if any(_is_repeat_dir(d) for d in top_dirs):
        ds.notes.append("检测到 `N_名称` 形式的子目录：kohya 的重复次数目录约定")
    if any(_relpath(root, d).startswith("cap_kohya") for d in defaults) or \
            any(m.rel.startswith("cap_kohya") for m in ds.meta) or \
            _has_dir(root, "cap_kohya"):
        ds.notes.append("检测到 cap_kohya/：双 caption profile（现代底模 + kohya 全量）")
    if defaults:
        ds.notes.append(f"检测到 {len(defaults)} 个 default_caption.txt")
    return ds


def _is_repeat_dir(name: str) -> bool:
    return bool(REPEAT_DIR.match(name))


def _has_dir(root: str, target: str) -> bool:
    for dirpath, dirnames, _ in os.walk(root):
        if target in dirnames:
            return True
        if dirpath.count(os.sep) - root.count(os.sep) >= 2:
            dirnames[:] = []
    return False
