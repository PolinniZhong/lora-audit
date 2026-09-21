# -*- coding: utf-8 -*-
"""审计规则：把"文件夹里有什么"变成"这里有几处问题"。

规则的取舍原则（写给别人用的工具，不是给自己看的报告）：
  - **只报能一眼验证的事**：缺 caption、重复、触发词漂移、杂物文件、分辨率。
    不猜意图，不评价画风，不要求用户按我们的目录规范组织。
  - **每条都要给"怎么办"**：只说有问题不给出口，用户下次就不跑了。
  - **宁可少报也不要误报**：噪声会让人关掉告警。阈值不足时闭嘴（见 TriggerConsensus）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .scan import Dataset, ImageEntry

#: 数据集规模的经验区间（社区共识：15–30 张精修可用，20–40 更鲁棒，>50 收益很小）
MIN_IMAGES = 15
MAX_IMAGES = 150
#: 短边低于此值认为分辨率偏小（SDXL 训练常规 ≥768，SD1.5 系 ≥512）
MIN_SHORT_SIDE = 512
#: 触发词共识至少要覆盖这么多比例才敢报"漂移"
TRIGGER_CONSENSUS = 0.6
#: 单条 finding 里最多列多少个条目（HTML 体积与可读性）
MAX_ITEMS = 200

OK_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: 扩展名 → 它**应该**代表的格式
EXT_FORMAT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".jpe": "jpeg",
              ".jfif": "jpeg", ".gif": "gif", ".bmp": "bmp", ".webp": "webp"}


@dataclass
class Finding:
    id: str
    sev: str                    # error | warn | info
    title: str
    detail: str
    items: List[str] = field(default_factory=list)
    action: str = ""
    truncated: int = 0          # 被截掉的条目数
    #: items 的类型：image（可据此筛图）/ file（只是路径，不能筛图）/ none
    kind: str = "none"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "sev": self.sev, "title": self.title, "detail": self.detail,
            "items": self.items, "action": self.action, "count": len(self.items),
            "truncated": self.truncated, "kind": self.kind,
        }


@dataclass
class TriggerConsensus:
    value: Optional[str] = None
    coverage: float = 0.0
    counts: Dict[str, int] = field(default_factory=dict)
    total: int = 0

    def to_dict(self) -> dict:
        return {"value": self.value, "coverage": round(self.coverage, 4),
                "counts": self.counts, "total": self.total}


def _cap(items: List[str]):
    if len(items) > MAX_ITEMS:
        return items[:MAX_ITEMS], len(items) - MAX_ITEMS
    return items, 0


def _norm_caption(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def consensus_of(images: List[ImageEntry]) -> TriggerConsensus:
    counts: Dict[str, int] = {}
    total = 0
    for img in images:
        if img.trigger:
            total += 1
            counts[img.trigger] = counts.get(img.trigger, 0) + 1
    if not counts:
        return TriggerConsensus()
    value, hits = max(counts.items(), key=lambda kv: kv[1])
    return TriggerConsensus(value=value, coverage=hits / total if total else 0.0,
                            counts=dict(sorted(counts.items(), key=lambda kv: -kv[1])),
                            total=total)


def audit(ds: Dataset) -> List[Finding]:
    """跑全部规则，返回 findings（已按严重度排序）。"""
    out: List[Finding] = []
    images = ds.images
    by_rel = {img.rel: img for img in images}
    total = len(images)

    # ---------------------------------------------------------------- ERROR
    missing = [img.rel for img in images if img.cap_source == "none"]
    if missing:
        items, cut = _cap(missing)
        all_missing = len(missing) == total and total > 0
        out.append(Finding(
            id="E001", sev="error",
            title="图片没有 caption", kind="image",
            detail=("整个数据集没有找到任何 caption 文件（既没有同名 .txt，"
                    "也没有可继承的 default_caption.txt）。") if all_missing else
                   (f"{len(missing)} / {total} 张图既没有同名 caption 文件，"
                    "也没有 default_caption.txt 可以兜底。这些图在训练时要么被跳过，"
                    "要么被当成无标注样本，模型学到的就是噪声。"),
            items=items, truncated=cut,
            action="为每张图补一个同名 .txt；若整套图共享同一段身份描述，"
                   "再放一个 default_caption.txt 让逐图 .txt 只写变量。",
        ))

    # ----------------------------------------------------------------- WARN
    empty = [img.rel for img in images
             if img.cap_source == "sidecar" and not img.has_caption]
    if empty:
        items, cut = _cap(empty)
        out.append(Finding(
            id="W001", sev="warn", title="caption 文件是空的", kind="image",
            detail=f"{len(empty)} 张图的同名 caption 文件存在，但内容为空或只有空白字符。"
                   "空文件比缺文件更隐蔽——文件计数对得上，训练时却是空的。",
            items=items, truncated=cut,
            action="补上内容，或删掉空文件让它落回 default_caption 兜底。"))

    sidecar_caps: Dict[str, List[str]] = {}
    for img in images:
        if img.cap_source == "sidecar" and img.has_caption:
            sidecar_caps.setdefault(_norm_caption(img.caption or ""), []).append(img.rel)
    dupes = {k: v for k, v in sidecar_caps.items() if len(v) > 1}
    if dupes:
        rels: List[str] = []
        for key in sorted(dupes, key=lambda k: -len(dupes[k])):
            rels.extend(dupes[key])
        items, cut = _cap(rels)
        sample = next(iter(sorted(dupes, key=lambda k: -len(dupes[k]))))
        out.append(Finding(
            id="W002", sev="warn", title="逐图 caption 完全重复", kind="image",
            detail=f"{len(dupes)} 组、共 {len(rels)} 张图的 caption 一字不差。"
                   "如果这些图内容确实不同，说明变量没写进 caption——"
                   f"模型学不到它们的区别。例如：{sample[:80]}{'…' if len(sample) > 80 else ''}",
            items=items, truncated=cut,
            action="给重复的图补上各自的变量描述（视角 / 取景 / 表情 / 动作）。"))

    cons = consensus_of(images)
    if cons.value and cons.total >= 3 and cons.coverage >= TRIGGER_CONSENSUS:
        drift = [img.rel for img in images
                 if img.trigger and img.trigger != cons.value]
        if drift:
            items, cut = _cap(drift)
            others = ", ".join(f"`{k}`×{v}" for k, v in cons.counts.items() if k != cons.value)
            out.append(Finding(
                id="W003", sev="warn", title="触发词不一致", kind="image",
                detail=f"主流触发词是 `{cons.value}`（{cons.total} 张里占 "
                       f"{cons.coverage * 100:.0f}%），但有 {len(drift)} 张的首词不是它"
                       f"（其它：{others}）。触发词不统一会让身份绑定被稀释——"
                       "同一张脸被拆到多个 token 上。",
                items=items, truncated=cut,
                action=f"把这些图的 caption 首词统一改成 `{cons.value}`。"))

    inherited = [img.rel for img in images if img.cap_source == "default"]
    if inherited:
        items, cut = _cap(inherited)
        out.append(Finding(
            id="W004", sev="warn", title="只有 default_caption 兜底，没有逐图变量", kind="image",
            detail=f"{len(inherited)} 张图继承的是 default_caption.txt，自己没有同名 .txt。"
                   "default_caption 机制的正确用法是「身份块写一次 + 每张图写变量」；"
                   "只有身份块意味着这些图在训练时彼此完全一样，"
                   "模型无从区分它们的视角与表情。",
            items=items, truncated=cut,
            action="为这些图补各自的变量 .txt，只写会变的部分。"))

    bad_names = [img.rel for img in images if not OK_NAME.match(img.name)]
    if bad_names:
        items, cut = _cap(bad_names)
        out.append(Finding(
            id="W005", sev="warn", title="文件名不规范", kind="image",
            detail=f"{len(bad_names)} 个文件名含空格、非 ASCII 字符或非常规符号。"
                   "这类名字在跨平台拷贝、命令行参数、脚本拼接时最容易出问题，"
                   "而且很多训练器的 sidecar 配对是按文件名严格匹配的。",
            items=items, truncated=cut,
            action="改为字母 / 数字 / 下划线 / 连字符，并让同名 .txt 跟着一起改。"))

    if ds.orphans:
        items, cut = _cap(ds.orphans)
        out.append(Finding(
            id="W006", sev="warn", title="有 caption 文件但没有对应图片", kind="file",
            detail=f"{len(ds.orphans)} 个 caption 文件找不到同名图片。"
                   "通常来自改名、删图或扩展名写错，是「账对不上」的第一信号。",
            items=items, truncated=cut,
            action="确认这些图是删了还是改名了：删了就一并删掉 caption，"
                   "改名了就把 caption 一起改。"))

    tiny = [img.rel for img in images
            if img.short_side is not None and img.short_side < MIN_SHORT_SIDE]
    if tiny:
        items, cut = _cap(tiny)
        smallest = min(images, key=lambda i: i.short_side or 10 ** 9)
        out.append(Finding(
            id="W007", sev="warn", title="分辨率偏小", kind="image",
            detail=f"{len(tiny)} 张图的短边小于 {MIN_SHORT_SIDE}px"
                   f"（最小 {smallest.width}×{smallest.height}）。"
                   "低分辨率图混在高分辨率集里，会在训练时被放大插值，"
                   "等于给模型喂模糊样本。",
            items=items, truncated=cut,
            action="把这些图剔出训练集，或先做一次超分再放回来。"))

    sizes = {(img.width, img.height) for img in images if img.width and img.height}
    if len(sizes) >= 2:
        dist: Dict[str, int] = {}
        for img in images:
            if img.width and img.height:
                key = f"{img.width}×{img.height}"
                dist[key] = dist.get(key, 0) + 1
        top = ", ".join(f"{k} · {v} 张" for k, v in
                        sorted(dist.items(), key=lambda kv: -kv[1])[:6])
        out.append(Finding(
            id="W008", sev="warn", title="分辨率不统一", kind="none",
            detail=f"出现 {len(sizes)} 种尺寸：{top}。"
                   "尺寸不统一本身不一定错（分桶训练就要求多样），"
                   "但如果这不是你有意为之，多半是选图时混进了不同来源的图。",
            action="确认是有意分桶还是误混；误混则统一到目标分辨率。"))

    if total and (total < MIN_IMAGES or total > MAX_IMAGES):
        if total < MIN_IMAGES:
            detail = (f"只有 {total} 张图，低于常见的 {MIN_IMAGES} 张下限。"
                      "角色 LoRA 的社区经验是 15–30 张精修即可，"
                      "但过少时模型容易把构图和身份一起背下来（过拟合到姿势）。")
            action = "再补几张不同视角/表情的图，优先补变化大的。"
        else:
            detail = (f"有 {total} 张图，超过常见的 {MAX_IMAGES} 张。"
                      "数量继续增加对质量的提升很小，但会拉长训练时间并放大脏样本的影响。")
            action = "优先「无情精选」而不是继续加量。"
        out.append(Finding(id="W009", sev="warn", title="数据集规模偏离常见区间", kind="none",
                           detail=detail, action=action))

    mismatched = [img.rel for img in images
                  if img.actual_format and EXT_FORMAT.get(img.ext)
                  and EXT_FORMAT[img.ext] != img.actual_format]
    if mismatched:
        items, cut = _cap(mismatched)
        kinds = sorted({f"{img.ext} → {img.actual_format}" for img in images
                        if img.rel in set(mismatched)})
        out.append(Finding(
            id="W013", sev="warn", title="扩展名与实际格式不符", kind="image",
            detail=f"{len(mismatched)} 个文件的扩展名和真实内容不是一回事（{'、'.join(kinds)}）。"
                   "多数训练器按扩展名交给图像库解码，装了对应解码器时还能读，"
                   "但换一台机器、换一个工具链就可能静默丢图——而「文件数」看起来还是对的。"
                   "它也会让任何按扩展名取尺寸/生成缩略图的流程失效。",
            items=items, truncated=cut,
            action="把扩展名改成实际格式；如果确实要 PNG，就先转码再入库。"))

    if ds.junk:
        items, cut = _cap(ds.junk)
        out.append(Finding(
            id="W010", sev="warn", title="混入了系统杂物文件", kind="file",
            detail=f"{len(ds.junk)} 个系统生成的文件（macOS 的 .DS_Store、"
                   "Windows 的 Thumbs.db 等）躺在数据集里。它们不会被当图片读，"
                   "但会把「文件数」这个指标弄脏，也容易被误打包进发布。",
            items=items, truncated=cut,
            action="删掉，或加进 .gitignore。"))

    lists = {m.role: m for m in ds.meta if m.role in ("train list", "val list")}
    known = set(by_rel) | {img.name for img in images}
    for role, mf in lists.items():
        referenced = [ln.replace("\\", "/").lstrip("./") for ln in mf.lines]
        dangling = [ln for ln in referenced
                    if ln not in known and ln.split("/")[-1] not in known]
        if dangling:
            items, cut = _cap(dangling)
            out.append(Finding(
                id="W011", sev="warn", title=f"{role} 指向不存在的文件", kind="file",
                detail=f"{mf.rel} 里有 {len(dangling)} 行找不到对应图片。"
                       "清单和实际文件对不上时，训练器会静默少读几张图。",
                items=items, truncated=cut,
                action="重新生成清单，或修掉被改名/删掉的那几张。"))

    val = lists.get("val list")
    if val and images:
        groups = ds.groups
        val_groups = set()
        for ln in val.lines:
            norm = ln.replace("\\", "/").lstrip("./")
            img = by_rel.get(norm)
            if img is None:
                img = next((i for i in images if i.name == norm.split("/")[-1]), None)
            if img is not None and img.group:
                val_groups.add(img.group)
        if len(groups) >= 2 and len(val_groups) == 1:
            out.append(Finding(
                id="W012", sev="warn", title="验证集没有分层", kind="none",
                detail=f"数据集分了 {len(groups)} 组（{', '.join(groups)}），"
                       f"但 val 清单里的图全部来自同一组（{next(iter(val_groups))}）。"
                       "验证集只覆盖一种取景时，验证损失无法反映其它取景的过拟合程度。",
                action="让 val 从每组里各抽几张。"))

    # ----------------------------------------------------------------- INFO
    if ds.notes:
        out.append(Finding(id="I001", sev="info", title="识别到的布局", kind="none",
                           detail=" / ".join(ds.notes)))
    if ds.groups:
        parts = []
        for g in ds.groups:
            n = sum(1 for img in images if img.group == g)
            parts.append(f"{g} {n} 张")
        flat = sum(1 for img in images if not img.group)
        if flat:
            parts.append(f"（根目录）{flat} 张")
        out.append(Finding(id="I002", sev="info", title="分组分布", kind="none",
                           detail=" · ".join(parts)))
    if cons.value:
        others = ", ".join(f"`{k}`×{v}" for k, v in cons.counts.items() if k != cons.value) or "无"
        out.append(Finding(
            id="I003", sev="info", title="触发词", kind="none",
            detail=f"推定触发词 `{cons.value}`，覆盖 {cons.total} 张中的 "
                   f"{cons.coverage * 100:.0f}%；其它：{others}"))
    return _apply_ignores(out, ds)


def _apply_ignores(findings, ds):
    """套用用户的豁免声明。

    **豁免 ≠ 隐藏。** 被豁免的规则在报告里**降级为 info 并标注「已豁免」**，理由原样展示。
    静默隐藏会变成自欺——审计工具最不能干的就是这个。
    """
    if not ds.ignored:
        return findings
    for f in findings:
        if f.id in ds.ignored:
            why = ds.ignored[f.id]
            f.sev = "info"
            f.title = f.title + "（已豁免）"
            f.detail = (f.detail + "\n\n已按 `.lora-audit-ignore` 豁免"
                        + (f"：{why}" if why else "（未写理由）"))
            f.action = ""
    return findings


def summarize(ds: Dataset, findings: List[Finding]) -> dict:
    images = ds.images
    return {
        "images": len(images),
        "sidecar": sum(1 for i in images if i.cap_source == "sidecar"),
        "default": sum(1 for i in images if i.cap_source == "default"),
        "none": sum(1 for i in images if i.cap_source == "none"),
        "empty": sum(1 for i in images
                     if i.cap_source == "sidecar" and not i.has_caption),
        "groups": len(ds.groups),
        "bytes": ds.total_bytes,
        "errors": sum(1 for f in findings if f.sev == "error"),
        "warnings": sum(1 for f in findings if f.sev == "warn"),
        "infos": sum(1 for f in findings if f.sev == "info"),
    }
