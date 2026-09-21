#!/usr/bin/env bash
# 重新生成 examples/ 里的示例报告（可复现，不要手改产物）。
#
# 为什么需要这一步：报告会记录**扫描目录的绝对路径**（方便你确认审的是哪个文件夹）。
# 仓库里的示例不应暴露开发机的路径，所以在生成后把「仓库根绝对路径」剥掉，
# 报告里就只剩 examples/demo-dataset 这样的相对路径。
#
# 已知缺口：这个"剥路径"目前只在本脚本里做，工具本身还没有开关。
#           工具用户分享报告前请自行注意；v0.1.1 计划加 --root-label。
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

rm -rf examples/demo-dataset/_lora_audit
# 注意：scan 在发现问题时返回非 0（这是有意的，方便 CI 判失败），所以这里不能让它中断脚本
python3 -m lora_audit scan examples/demo-dataset >/dev/null || true

python3 - "$ROOT" <<'PY'
import io, sys, pathlib
root = sys.argv[1]
report = pathlib.Path("examples/demo-dataset/_lora_audit/report.html")
t = io.open(report, encoding="utf-8").read()
before = t.count(root)
t = t.replace(root + "/", "").replace(root, "")
io.open(report, "w", encoding="utf-8").write(t)
print(f"  剥掉仓库绝对路径 {before} 处")
PY

python3 -m lora_audit verify examples/demo-dataset/_lora_audit/report.html
