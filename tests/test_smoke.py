# -*- coding: utf-8 -*-
"""端到端自测：只用标准库的 unittest，不引入 pytest。

    python3 -m unittest discover -s tests -v

覆盖：图片头解析 → 扫描 → 规则命中 → 单文件报告生成 → verify 不变量。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lora_audit import cli                       # noqa: E402
from lora_audit.imagesize import read_size       # noqa: E402
from lora_audit.rules import audit, consensus_of, summarize  # noqa: E402
from lora_audit.scan import scan                 # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples"))
import make_example                              # noqa: E402


class FixtureMixin:
    """用 examples/make_example.py 造一份带已知缺陷的数据集。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lora-audit-test-")
        cls.root = os.path.join(cls.tmp, "demo-dataset")
        os.makedirs(cls.root)
        for name, w, h, caption in make_example.IMAGES:
            make_example.write_png(os.path.join(cls.root, name), w, h)
            if caption is not None:
                make_example.write_text(
                    os.path.join(cls.root, os.path.splitext(name)[0] + ".txt"), caption)
        sub = os.path.join(cls.root, "extra")
        os.makedirs(sub)
        shutil.move(os.path.join(cls.root, "012_full.png"),
                    os.path.join(sub, "012_full.png"))
        make_example.write_text(os.path.join(sub, "default_caption.txt"),
                                make_example.IDENTITY)
        make_example.write_text(os.path.join(cls.root, "013_deleted.txt"), "orphan")
        make_example.write_text(os.path.join(cls.root, ".DS_Store"), "junk")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestImageSize(unittest.TestCase):
    def test_reads_png_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.png")
            make_example.write_png(path, 320, 480)
            self.assertEqual(read_size(path), (320, 480))

    def test_unknown_and_broken_files_never_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt = os.path.join(tmp, "a.txt")
            with open(txt, "w") as fh:
                fh.write("not an image")
            self.assertIsNone(read_size(txt))          # 不支持的扩展名
            broken = os.path.join(tmp, "broken.png")
            with open(broken, "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\n")
            self.assertIsNone(read_size(broken))       # 截断的 PNG
            self.assertIsNone(read_size(os.path.join(tmp, "nope.png")))


class TestScan(FixtureMixin, unittest.TestCase):
    def test_counts_and_layout(self):
        ds = scan(self.root)
        self.assertEqual(len(ds.images), len(make_example.IMAGES))
        self.assertEqual(ds.groups, ["extra"])
        self.assertTrue(any(".DS_Store" in j for j in ds.junk))
        self.assertTrue(any(o.endswith("013_deleted.txt") for o in ds.orphans))

    def test_caption_sources(self):
        ds = scan(self.root)
        by_name = {i.name: i for i in ds.images}
        self.assertEqual(by_name["001_front.png"].cap_source, "sidecar")
        self.assertEqual(by_name["001_front.png"].trigger, "demochan")
        self.assertEqual(by_name["011_face.png"].cap_source, "none")
        self.assertEqual(by_name["012_full.png"].cap_source, "default")

    def test_does_not_ingest_its_own_output_dir(self):
        ds = scan(self.root)
        self.assertFalse(any("_lora_audit" in i.rel for i in ds.images))


class TestRules(FixtureMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ds = scan(cls.root)
        cls.findings = {f.id: f for f in audit(cls.ds)}

    def test_expected_rules_fire(self):
        for rule in ("E001", "W001", "W002", "W003", "W004",
                     "W005", "W006", "W007", "W010"):
            self.assertIn(rule, self.findings, f"{rule} 没触发")

    def test_error_points_at_the_right_files(self):
        items = self.findings["E001"].items
        self.assertIn("011_face.png", items)
        self.assertNotIn("012_full.png", items)   # 这张有 default_caption 兜底

    def test_duplicate_caption_pair(self):
        items = self.findings["W002"].items
        self.assertIn("001_front.png", items)
        self.assertIn("005_front.png", items)

    def test_trigger_drift_is_the_typo(self):
        self.assertIn("006_think.png", self.findings["W003"].items)

    def test_no_false_positive_on_clean_sample(self):
        cons = consensus_of(self.ds.images)
        self.assertEqual(cons.value, "demochan")

    def test_summary_counts(self):
        s = summarize(self.ds, list(self.findings.values()))
        self.assertEqual(s["images"], len(make_example.IMAGES))
        self.assertEqual(s["none"], 1)
        self.assertEqual(s["default"], 1)
        self.assertEqual(s["errors"], 1)


class TestReportAndVerify(FixtureMixin, unittest.TestCase):
    def test_report_is_single_file_and_offline(self):
        out = os.path.join(self.root, "_lora_audit", "report.html")
        with redirect_stdout(io.StringIO()):
            rc = cli.main(["scan", self.root, "-o", out, "--json", "-", "-q"])
        self.assertEqual(rc, 1)                     # 有 E001，退出码必须是 1

        self.assertTrue(os.path.isfile(out))
        with open(out, encoding="utf-8") as fh:
            html = fh.read()
        for bad in ('type="module"', "fetch(", "XMLHttpRequest"):
            self.assertNotIn(bad, html)
        self.assertNotIn('src="http', html)

        # 数据块可解析，且每张图都有相对路径
        self.assertIn('id="la-data"', html)
        data = json.loads(html.split('id="la-data">', 1)[1].split("</script>", 1)[0]
                          .replace("<\\/", "</"))
        self.assertEqual(len(data["images"]), len(make_example.IMAGES))
        self.assertTrue(all(not i["src"].startswith("http") for i in data["images"]))

    def test_filenames_are_encoded_exactly_once(self):
        """回归：带空格的图片名被双重编码成 %2520 → 浏览器 ERR_FILE_NOT_FOUND。

        verify 查不出这个（它只解一次码，路径仍然可达），只有真浏览器会报。
        见 tools/browser_check.mjs。只查数据块里的 src，不查整页源码
        （源码注释里也会出现 %2520 这个字样）。
        """
        out = os.path.join(self.root, "_lora_audit", "report.html")
        with redirect_stdout(io.StringIO()):
            cli.main(["scan", self.root, "-o", out, "-q"])
        with open(out, encoding="utf-8") as fh:
            html = fh.read()
        data = json.loads(html.split('id="la-data">', 1)[1]
                          .split("</script>", 1)[0].replace("<\\/", "</"))
        srcs = [i["src"] for i in data["images"]]
        space_src = [s for s in srcs if "jump" in s]
        self.assertEqual(space_src, ["../010%20jump.png"], "带空格的路径必须只编码一次")
        self.assertFalse([s for s in srcs if "%25" in s], "出现了双重编码")

    def test_json_stdout_is_pure_json(self):
        """`--json -` 的 stdout 必须是**纯 JSON**。

        README 把 `lora-audit scan ./dataset --json -` 当 CI 用法推荐（管道进 jq 之类），
        所以人类可读摘要必须走 stderr——曾经混在一起，管道直接解析失败。
        """
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(["scan", self.root, "--json", "-"])
        self.assertEqual(rc, 1)                      # 合成夹具里有 E001
        data = json.loads(out.getvalue())            # 解析失败即证明 stdout 被污染
        self.assertEqual(len(data["images"]), len(make_example.IMAGES))
        self.assertIn("数据集", err.getvalue())      # 摘要确实在 stderr

    def test_no_favicon_request(self):
        """file:// 页面若没有图标，Chrome 会请求 favicon.ico 报错，掩盖真问题。"""
        out = os.path.join(self.root, "_lora_audit", "report.html")
        with redirect_stdout(io.StringIO()):
            cli.main(["scan", self.root, "-o", out, "-q"])
        with open(out, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('rel="icon"', html)

    def test_verify_passes_on_generated_report(self):
        out = os.path.join(self.root, "_lora_audit", "report.html")
        with redirect_stdout(io.StringIO()):
            cli.main(["scan", self.root, "-o", out, "-q"])
            rc = cli.main(["verify", out])
        self.assertEqual(rc, 0)

    def test_verify_catches_remote_resource(self):
        out = os.path.join(self.root, "_lora_audit", "report.html")
        with redirect_stdout(io.StringIO()):
            cli.main(["scan", self.root, "-o", out, "-q"])
        with open(out, encoding="utf-8") as fh:
            html = fh.read()
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html.replace("<body>", '<body><img src="https://example.com/x.png">', 1))
        with redirect_stdout(io.StringIO()):
            rc = cli.main(["verify", out])
        self.assertEqual(rc, 1)

    def test_strict_escalates_warnings(self):
        with redirect_stdout(io.StringIO()):
            rc = cli.main(["scan", self.root, "-q", "--strict", "--json", "-"])
        self.assertEqual(rc, 1)

    def test_empty_directory_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()), \
                    __import__("contextlib").redirect_stderr(io.StringIO()):
                rc = cli.main(["scan", tmp, "-q"])
        self.assertEqual(rc, 2)

    def test_clean_dataset_exits_zero(self):
        """把缺陷全部修掉后，必须干净通过——否则告警就是噪声。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "clean")
            os.makedirs(root)
            for i in range(16):
                name = f"{i:03d}_front.png"
                make_example.write_png(os.path.join(root, name), 1024, 1024)
                make_example.write_text(
                    os.path.join(root, os.path.splitext(name)[0] + ".txt"),
                    f"demochan, full body, view {i}, neutral A-pose")
            with redirect_stdout(io.StringIO()):
                rc = cli.main(["scan", root, "-q", "--strict", "--json", "-"])
            self.assertEqual(rc, 0)


class TestIgnoreDeclaration(unittest.TestCase):
    """可选豁免声明：`.lora-audit-ignore`。

    设计红线：**豁免 ≠ 隐藏**——被豁免的规则降级为 info 并在报告里明示理由。
    这条来自一次真实使用：审我们自己的 47 张训练集时报了 `W008 分辨率不统一`，
    而那 6 张 2048×2048 是**有意的方形细节图**——是误报，但用户当时无处说"我知道"。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lora-ignore-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for i in range(15):
            make_example.write_png(os.path.join(self.tmp, f"{i:03d}.png"), 64, 64)
            with open(os.path.join(self.tmp, f"{i:03d}.txt"), "w", encoding="utf-8") as fh:
                fh.write(f"mychan, view {i}")
        # 混进一张不同尺寸 → 触发 W008
        make_example.write_png(os.path.join(self.tmp, "999_square.png"), 32, 32)
        with open(os.path.join(self.tmp, "999_square.txt"), "w", encoding="utf-8") as fh:
            fh.write("mychan, square detail")

    def _findings(self, ignore_text=None):
        if ignore_text is not None:
            with open(os.path.join(self.tmp, ".lora-audit-ignore"), "w",
                      encoding="utf-8") as fh:
                fh.write(ignore_text)
        ds = scan(self.tmp)
        return ds, {f.id: f for f in audit(ds)}

    def test_w008_is_warn_without_declaration(self):
        _, f = self._findings()
        self.assertIn("W008", f)
        self.assertEqual(f["W008"].sev, "warn")

    def test_declaration_downgrades_to_info_and_shows_reason(self):
        _, f = self._findings("# 豁免说明\nW008 # 方形细节图是有意为之，不是混入\n")
        self.assertEqual(f["W008"].sev, "info", "豁免后必须降级为 info")
        self.assertIn("已豁免", f["W008"].title, "标题必须标注已豁免（不许静默隐藏）")
        self.assertIn("方形细节图是有意为之", f["W008"].detail, "理由必须原样展示")

    def test_declaration_file_is_not_junk_or_caption(self):
        ds, f = self._findings("W008 # 有意\n")
        self.assertNotIn("W010", f, "豁免声明本身不能被当成系统杂物")
        self.assertEqual(ds.orphans, [], "豁免声明不能被当成孤儿 caption")
        self.assertNotIn(".lora-audit-ignore",
                         [i for i in f.get("W006", type("x", (), {"items": []})).items])

    def test_exempted_rule_no_longer_counts_as_warning(self):
        """豁免后警告数**恰好少 1**（不是归零——这个夹具里还有 W007 分辨率偏小）。"""
        from lora_audit.rules import summarize
        ds0, f0 = self._findings()
        before = summarize(ds0, list(f0.values()))["warnings"]
        ds1, f1 = self._findings("W008 # 有意\n")
        after = summarize(ds1, list(f1.values()))["warnings"]
        self.assertEqual(after, before - 1, f"警告数应恰好减 1（{before} → {after}）")

    def test_bad_declaration_lines_are_ignored(self):
        _, f = self._findings("\n# 整行注释\n   \nW008\n")
        self.assertEqual(f["W008"].sev, "info")
        self.assertIn("未写理由", f["W008"].detail)


class TestMirrorCaptionTree(unittest.TestCase):
    """回归：`cap_kohya/` 这类镜像 caption 树不能被当成孤儿 caption。

    这是拿真实数据集（img/ + cap_kohya/ 双 profile）跑出来的误报，
    当时 47 张图报了 47 个孤儿。
    """

    def test_mirror_tree_is_not_orphans(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "ds")
            img_dir = os.path.join(root, "img", "01_face")
            cap_dir = os.path.join(root, "cap_kohya", "01_face")
            os.makedirs(img_dir)
            os.makedirs(cap_dir)
            for i in range(16):
                stem = f"{i:03d}_face"
                make_example.write_png(os.path.join(img_dir, stem + ".png"), 1024, 1024)
                make_example.write_text(os.path.join(img_dir, stem + ".txt"),
                                        f"demochan, headshot, view {i}")
                make_example.write_text(os.path.join(cap_dir, stem + ".txt"),
                                        f"demochan, 3d cartoon character, view {i}")
            make_example.write_text(os.path.join(root, "default_caption.txt"),
                                    make_example.IDENTITY)

            ds = scan(root)
            self.assertEqual(ds.orphans, [], "镜像 caption 树被误判成孤儿")
            self.assertTrue(any("镜像 caption 树" in n for n in ds.notes))

            findings = {f.id: f for f in audit(ds)}
            self.assertNotIn("W006", findings)
            # 图片本身的逐图 caption 仍然读得到
            self.assertEqual(sum(1 for i in ds.images if i.cap_source == "sidecar"), 16)


if __name__ == "__main__":
    unittest.main(verbosity=2)
