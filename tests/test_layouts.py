# -*- coding: utf-8 -*-
"""真实目录布局的夹具测试。

这些布局不是凭空想的，来源有两类：

1. **训练器的官方约定**——kohya 的 `train_data_dir` 要求"文件夹必须命名为 `5_角色名`"
   （重复次数前缀），sidecar 扩展名由 `caption_extension` 指定（默认 `.txt`，也支持
   `.caption`）；ai-toolkit 是"一个文件夹，图 + 同名 txt"，身份描述走 `default_caption.txt`。
2. **一个真实的第三方公开数据集**——`Otarilaz/my_lora_project` 的 `dataset/`：
   9 个平铺文件、`.png` 扩展名**实际全是 WebP**、零 caption。
   本文件不下载它（版权与体积），但把它的两个特征做成夹具：
   扩展名与实际格式不符、以及"先把图糊进一个文件夹"的零 caption 现场。

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lora_audit.imagesize import detect_format, read_size   # noqa: E402
from lora_audit.rules import audit                          # noqa: E402
from lora_audit.scan import scan                            # noqa: E402
from lora_audit.scan import extract_trigger                 # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples"))
import make_example                                         # noqa: E402


def w(path, text=None, size=64):
    """写一张图（PNG 字节）+ 可选同名 sidecar。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    make_example.write_png(path, size, size)
    if text is not None:
        with open(os.path.splitext(path)[0] + ".txt", "w", encoding="utf-8") as fh:
            fh.write(text)


class LayoutBase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="lora-layout-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def p(self, *parts):
        return os.path.join(self.root, *parts)

    def findings(self):
        ds = scan(self.root)
        return ds, {f.id: f for f in audit(ds)}


class TestKohyaFlat(LayoutBase):
    """最朴素的 kohya 布局：图 + 同名 .txt 平铺。"""

    def test_flat_pairs(self):
        for i in range(16):
            w(self.p(f"img{i:03d}.png"), f"mychan, view {i}, neutral pose")
        ds, f = self.findings()
        self.assertEqual(len(ds.images), 16)
        self.assertTrue(all(x.cap_source == "sidecar" for x in ds.images))
        self.assertEqual({x.trigger for x in ds.images}, {"mychan"})
        self.assertNotIn("E001", f)
        self.assertNotIn("W006", f)
        self.assertTrue(any("平铺" in n for n in ds.notes))


class TestKohyaRepeatDirs(LayoutBase):
    """kohya 的 `N_名称` 重复次数目录——官方配置里明确要求这个命名。"""

    def test_repeat_dirs_are_recognized(self):
        w(self.p("10_mychar", "a.png"), "whatisit, full body, front view")
        w(self.p("10_mychar", "b.png"), "whatisit, full body, side view")
        w(self.p("5_style", "c.png"), "whatisit, headshot, smile")
        ds, f = self.findings()
        self.assertEqual(len(ds.images), 3)
        self.assertEqual(ds.groups, ["10_mychar", "5_style"])
        self.assertTrue(any("kohya" in n and "重复次数" in n for n in ds.notes),
                        f"应识别出 kohya 重复次数目录：{ds.notes}")
        self.assertNotIn("E001", f)

    def test_repeat_dir_without_captions(self):
        """有目录结构但没有 sidecar：仍应逐图报 E001，而不是报孤儿。"""
        w(self.p("10_mychar", "a.png"))
        w(self.p("10_mychar", "b.png"))
        ds, f = self.findings()
        self.assertEqual(sorted(f["E001"].items), ["10_mychar/a.png", "10_mychar/b.png"])
        self.assertNotIn("W006", f)


class TestAiToolkit(LayoutBase):
    """ai-toolkit：img/ 放图 + 同名 txt 写变量，身份块走 default_caption.txt。"""

    def test_default_caption_plus_per_image(self):
        os.makedirs(self.p("img"), exist_ok=True)
        with open(self.p("default_caption.txt"), "w", encoding="utf-8") as fh:
            fh.write("mychan, 3d cartoon character, plain white background")
        for i in range(16):
            w(self.p("img", f"{i:03d}.png"), f"mychan, view {i}")
        ds, f = self.findings()
        self.assertEqual(len(ds.images), 16)
        self.assertTrue(all(x.cap_source == "sidecar" for x in ds.images))
        self.assertTrue(any("ai-toolkit" in n for n in ds.notes), ds.notes)
        self.assertNotIn("E001", f)
        self.assertNotIn("W004", f, "逐图变量齐全时不该报'只有 default 兜底'")

    def test_images_without_sidecar_fall_back_to_default(self):
        os.makedirs(self.p("img"), exist_ok=True)
        with open(self.p("default_caption.txt"), "w", encoding="utf-8") as fh:
            fh.write("mychan, 3d cartoon character")
        for i in range(16):
            w(self.p("img", f"{i:03d}.png"))          # 刻意不写 sidecar
        ds, f = self.findings()
        self.assertTrue(all(x.cap_source == "default" for x in ds.images))
        self.assertNotIn("E001", f, "有 default_caption 兜底就不算缺 caption")
        self.assertIn("W004", f, "但必须提醒：没有逐图变量")


class TestCaptionExtensionAndMetaFiles(LayoutBase):
    """`.caption` 扩展名，以及不能被误当成 caption 的数据集级元文件。"""

    def test_caption_extension_is_a_sidecar(self):
        for i in range(16):
            stem = self.p(f"img{i:03d}")
            make_example.write_png(stem + ".png", 64, 64)
            with open(stem + ".caption", "w", encoding="utf-8") as fh:
                fh.write(f"mychan, view {i}")
        ds, f = self.findings()
        self.assertTrue(all(x.cap_source == "sidecar" for x in ds.images))
        self.assertNotIn("E001", f)
        self.assertNotIn("W006", f)

    def test_dataset_config_toml_is_not_a_caption(self):
        """kohya 的 dataset_config.toml / train.txt 是元文件，不是孤儿 caption。"""
        for i in range(16):
            w(self.p("train", f"{i:03d}.png"), f"mychan, view {i}")
        with open(self.p("dataset_config.toml"), "w", encoding="utf-8") as fh:
            fh.write('[general]\ncaption_extension = ".txt"\n')
        with open(self.p("train.txt"), "w", encoding="utf-8") as fh:
            fh.write("train/000.png\n")
        ds, f = self.findings()
        self.assertNotIn("W006", f, f"元文件不该被当成孤儿 caption：{ds.orphans}")
        roles = {m.role for m in ds.meta}
        self.assertTrue(roles & {"toml", "train list"}, f"元文件应被登记：{roles}")


class TestZeroCaptionRealCase(LayoutBase):
    """复刻那个真实第三方数据集的现场：平铺、零 caption。"""

    def test_flat_no_captions(self):
        for i in range(9):
            w(self.p(f"anticybervamp__{i}.png"))
        ds, f = self.findings()
        self.assertEqual(len(ds.images), 9)
        self.assertTrue(all(x.cap_source == "none" for x in ds.images))
        self.assertEqual(len(f["E001"].items), 9)
        self.assertNotIn("W006", f, "没有 caption 文件就不该报孤儿")
        self.assertIn("W009", f)              # 9 张 < 15


class TestExtensionMismatch(LayoutBase):
    """扩展名与实际格式不符——真实数据集里 `.png` 其实是 WebP。"""

    def test_png_named_as_jpg_is_still_readable(self):
        """按文件头分派解析器：扩展名错了也要读得出尺寸，否则 W007/W008 变盲区。"""
        p = self.p("mislabeled.jpg")
        make_example.write_png(p, 96, 96)          # 内容是 PNG，名字是 .jpg
        self.assertEqual(detect_format(p), "png")
        self.assertEqual(read_size(p), (96, 96))

    def test_w013_fires(self):
        for i in range(15):
            w(self.p(f"{i:03d}.png"), f"mychan, view {i}")
        p = self.p("016_mislabeled.jpg")
        make_example.write_png(p, 96, 96)          # PNG 字节 + .jpg 扩展名
        with open(self.p("016_mislabeled.txt"), "w", encoding="utf-8") as fh:
            fh.write("mychan, view 16")
        ds, f = self.findings()
        self.assertIn("W013", f, f"应报扩展名与实际格式不符：{sorted(f)}")
        self.assertIn("016_mislabeled.jpg", f["W013"].items)

    def test_w013_silent_when_consistent(self):
        for i in range(15):
            w(self.p(f"{i:03d}.png"), f"mychan, view {i}")
        _, f = self.findings()
        self.assertNotIn("W013", f, "格式一致时不许误报")


class TestMixedLayout(LayoutBase):
    def test_flat_plus_subdir(self):
        w(self.p("a.png"), "mychan, view a")
        w(self.p("sub", "b.png"), "mychan, view b")
        ds, _ = self.findings()
        self.assertTrue(any("混合布局" in n for n in ds.notes), ds.notes)
        self.assertEqual(ds.groups, ["sub"])


class TestTriggerExtraction(unittest.TestCase):
    def test_first_token_before_comma(self):
        self.assertEqual(extract_trigger("mychan, view 1, smile"), "mychan")
        self.assertEqual(extract_trigger("  mychan ,x"), "mychan")
        self.assertEqual(extract_trigger("single-token"), "single-token")
        self.assertIsNone(extract_trigger(""))
        self.assertIsNone(extract_trigger("   "))

    def test_first_word_when_no_comma(self):
        self.assertEqual(extract_trigger("mychan full body view"), "mychan")


if __name__ == "__main__":
    unittest.main(verbosity=2)
