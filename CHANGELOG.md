# Changelog

本文件记录值得让使用者知道的变更。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- `examples/demo-dataset/`：13 张自制合成图 + caption，随仓库分发（**不含任何第三方素材**）
- **可点开看的真实报告**（GitHub Pages）：`examples/demo-dataset/_lora_audit/report.html`
- `tools/make_demo_report.sh`：示例报告的可复现生成脚本

### Fixed
- `.nojekyll`：GitHub Pages 的 Jekyll 会忽略 `_` 开头的目录（报告落在 `_lora_audit/`），没有它会 404
- `docs/screenshot.png` 重拍：原图右上角印有开发机的**绝对路径**（含用户名与内部目录）

暂无。

## [0.1.0] - 2026-09-20

首个版本。定位从第一天就收窄：**不做 DAM，只做"拿你已有的训练文件夹，吐一个只读审计页"**，零必需依赖、不起服务、不改你的目录结构。

### 新增

- `lora-audit scan <dataset>` —— 扫描一个训练文件夹，生成**单个自包含 HTML** 报告（默认落在 `<dataset>/_lora_audit/report.html`）
- `lora-audit verify <report.html>` —— 检查产物是否真的离线可用（远程资源 / ES Module / 运行时请求 / 图片可达性）
- `lora-audit --version`
- **17 条规则**：1 错误 + 13 警告 + 3 信息
  - `E001` 图片没有 caption
  - `W001` caption 文件是空的 ｜ `W002` 逐图 caption 完全重复 ｜ `W003` 触发词不一致
  - `W004` 只有 `default_caption` 兜底，没有逐图变量 ｜ `W005` 文件名不规范 ｜ `W006` 有 caption 文件但没有对应图片
  - `W007` 分辨率偏小 ｜ `W008` 分辨率不统一 ｜ `W009` 数据集规模偏离常见区间 ｜ `W010` 混入系统杂物文件
  - `W011` `train.txt` / `val.txt` 指向不存在的文件 ｜ `W012` 验证集没有分层
  - `W013` 扩展名与实际格式不符（例如 `.png` 里其实是 WebP）
  - `I001`–`I003` 识别到的布局 / 分组分布 / 推定触发词
  - 每条规则都带一句「怎么办」
- **零必需依赖**（纯标准库）：自己实现 PNG/JPEG/GIF/BMP/WebP 的图片头解析，不为读一个宽高背上 Pillow
- **输入契约为零**：不读 manifest、不读任何配置文件、不要求你先整理目录
- 支持的目录布局：kohya 平铺 / 按子目录分组 / ai-toolkit 的 `img/` + `default_caption.txt` / **双 caption profile（`cap_kohya/` 镜像树）** / 混合
- `--json`（机读输出，可进 CI）· `--strict`（警告也返回退出码 1）· `--open` · `-o` · `--title` · `-q`
- 退出码：`0` 通过 / `1` 发现问题 / `2` 参数或 IO 错误
- 报告页：问题卡（按严重度配色、多列排布）、图片网格、按问题筛图、搜索、图详情抽屉（含「复制 caption」）、页内看大图、深浅色切换
- 示例数据集生成器（`examples/make_example.py`，标准库现写 PNG，刻意做进 6 类缺陷）
- **可选的豁免声明 `.lora-audit-ignore`**：一行一个规则 ID，`#` 后写理由。
  **豁免 ≠ 隐藏**——被豁免的规则降级为「信息」、标题标注「已豁免」、理由原样展示，摘要行也会显示。文件缺席时行为与过去完全一致
- 开发工具：`tools/browser_check.mjs`（CDP 驱动真实 Chrome 的 15 项断言，零第三方依赖）
- 文档：`docs/PRD.md`（要什么 / 给谁 / **不做什么**）、`docs/DESIGN.md`（为什么这么做 / 代价）、
  `CONTRIBUTING.md`（什么样的规则我们收）、`CHANGELOG.md`；PRD 与 SDD 均有英文版

### 修掉的缺陷（开发期间实测发现）

这一版发出去之前，四个缺陷是"拿真实文件夹跑"和"拿真浏览器跑"才暴露的——列在这里是因为它们解释了为什么仓库里同时存在 `verify` 和 `browser_check` 两道验证：

- **镜像 caption 树被误判为孤儿**：`cap_kohya/`（同一批图的第二套 caption）天然没有同名图片，首跑就在一个 47 张图的数据集上报出 **47 个孤儿**。现按"路径不同但同名 → 另一套 caption profile"处理，并在报告的「识别到的布局」里说出来
- **带空格的文件名永久破图**：Python 侧 `quote()` 与 JS 侧 `encodeURI()` 各编一次，`010 jump.png` 变成 `%2520` → `ERR_FILE_NOT_FOUND`。**`verify` 报的是 OK**（它只解码一次，路径仍可达），只有真浏览器能抓
- **问题多时图片区被推到 3000px 之下**：问题卡原为单列长条，14 条问题就把正文推到首屏之外；改多列后页高 3053 → 1992
- **路径类规则渲染出筛图按钮**：`W006`/`W010` 的条目是路径不是图片，早期版本给它们也画了「只看这 N 张」，点了得到空网格。现引入 `kind`（`image` / `file` / `none`）区分

另修两处噪声：`file://` 页面缺 favicon 会在控制台留下一条 `ERR_FILE_NOT_FOUND`（已加 `data:,` 空图标）；sticky 顶栏高度原先写死 148px 与真实高度不符（改为运行期回写 CSS 变量）。

### 拿真实第三方数据集验证（2026-09-20）

在公开仓里找了一个真实的 LoRA 项目数据集（9 张图）跑，当场掉了两个问题——**这两个都不是靠合成夹具能发现的**：

- **所有图都读不出尺寸**：那 9 个文件扩展名是 `.png`，**实际全是 WebP（VP8L）**。解析器按扩展名分派 → 一律返回"读不出" → `W007`（分辨率偏小）和 `W008`（分辨率不统一）**直接变成盲区**。已改为**按文件头嗅探格式**，并新增 `W013` 把这类"扩展名骗人"报出来——它会让任何按扩展名取尺寸/生成缩略图的流程失效，换台机器还可能静默丢图。
- **`--json -` 的 stdout 被污染**：人类可读摘要和 JSON 一起打到 stdout，`lora-audit scan --json - | jq` 直接解析失败——而这正是 README 自己推荐的 CI 用法。现在摘要走 stderr，stdout 是纯 JSON。

同时补了 15 个**真实目录布局**夹具（`tests/test_layouts.py`）：kohya 平铺、kohya 的 `N_名称` 重复次数目录、ai-toolkit 的 `img/` + `default_caption.txt`、`.caption` 扩展名、`dataset_config.toml` 之类的元文件不能被误当 caption、以及扩展名误标。

### 由真实使用驱动的改进（实例 01）

拿它审自己角色库的 47 张训练集，报出 2 条警告，人工复核后判定 **1 条真、1 条误报**：

- `W010` `.DS_Store` → 真问题（现已由生成器在构建时清理）
- `W008` 分辨率不统一 → **误报**：那 6 张 2048×2048 是方形细节特写，与标准格 1773×2364 并存是**分桶训练的既定设计**

`W008` 的告警文案本身就写着"如果这不是你有意为之"——**它承认自己可能是误报，而用户却没有任何地方能说"我就是有意的"。** 于是加上了 `.lora-audit-ignore`。

完整记录（含 before/after 与"这个实例证明了什么、没证明什么"）见 [docs/INSTANCES.md](docs/INSTANCES.md)。

### 已知限制

完整清单见 [docs/DESIGN.md](docs/DESIGN.md) §8，最主要的四条：

- 看图走原图，**没有缩略图通道**（上千张时首屏会慢；`[thumbs]` extras 已声明但通道未实现）
- **报告不能单独挪走**（图片是相对路径）
- `W008` 在**有意分桶**时是噪声，没有"我已知晓，别报"的抑制机制
- **只在 1 个真实第三方公开数据集上验证过**（9 张、零 caption、`.png` 实为 WebP）＋ 15 个按训练器官方约定构造的布局夹具；还没经受「大量真实目录」的考验

[Unreleased]: https://github.com/PolinniZhong/lora-audit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/PolinniZhong/lora-audit/releases/tag/v0.1.0
