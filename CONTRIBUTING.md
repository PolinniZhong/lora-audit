# 贡献指南

先谢过。这个工具的目标很窄，所以"收什么"比"做什么"更重要——**下面第 2 节是本文档的核心**，其余都是流程。

## 1. 本地跑起来

```bash
git clone <repo> && cd lora-audit
python3 -m unittest discover -s tests -v      # 35 个用例，纯标准库，无网络
python3 examples/make_example.py              # 造一份带 7 类已知缺陷的数据集
python3 -m lora_audit scan examples/demo-dataset --open
```

改前端（`lora_audit/static/`）或 `report.py` 之后，**必须再跑真浏览器实测**：

```bash
python3 -m lora_audit verify examples/demo-dataset/_lora_audit/report.html
node tools/browser_check.mjs examples/demo-dataset/_lora_audit/report.html
```

第二条命令需要本机有 Chrome/Chromium；没有会自动跳过。**它不是可选项**——`verify` 在结构上查不出 JS 报错和 URL 双重编码（本仓库历史上真的漏过一次），详见 [docs/DESIGN.md](docs/DESIGN.md) §5.2。

## 2. 什么样的新规则我们会收

规则是给**别人**看的告警。噪声一多，用户下次就不打开了——所以门槛定得偏高。

| # | 判据 | 说明 |
|---|---|---|
| R1 | **能一眼验证** | 只看文件本身就能判断。**凡是要读图内容、要调模型、要"感觉一下"的，一律不收** |
| R2 | **不猜意图** | 不评价画风、不判断"这张图好不好"、不推断用户"本来想干嘛" |
| R3 | **有明确出口** | 每条规则必须能写出一句具体的「怎么办」。写不出出口的问题，用户看了也做不了什么 |
| R4 | **宁可漏报，不误报** | 证据不足时**闭嘴**（例：触发词漂移要求 ≥3 张且主流词覆盖 ≥60%） |
| R5 | **不引入必需依赖** | 需要新依赖的能力只能进 `[project.optional-dependencies]`，默认安装必须仍是零依赖 |
| R6 | **不改变输入** | 任何形式的写回数据集都直接拒 |

**一个具体的反例**，免得抽象：有人提"检测 caption 里有没有错别字"——**不收**。它违反 R1（要判断语义）和 R3（错别字改不改取决于用户想表达什么，我们给不出出口）。

**一个通过的例子**：`W011`（`train.txt` 指向不存在的文件）——只看文件系统就能验证（R1），不猜意图（R2），出口是"重新生成清单"（R3），阈值天然精确不会误报（R4），不需要新依赖（R5）。

### 规则分级怎么选

| 级别 | 什么时候用 |
|---|---|
| `error` | 训练**一定**出问题，没有例外 |
| `warn` | 很可能有问题，但**可能是有意为之**（措辞要带让步，例:"如果这不是你有意为之……"） |
| `info` | 只是把识别到的事实说出来，不构成问题 |

拿不准就往低了放。`error` 会让默认退出码变 1，是有代价的。

## 3. 加一条规则要同时改哪些地方

缺一项的 PR 会被要求补齐：

1. `lora_audit/rules.py` —— 规则本体（**不要碰文件系统**，输入 `Dataset`、输出 `Finding`）
2. `tests/test_smoke.py` —— **该报的**和**不该报的**都要有用例。只测"会报"是不够的，误报才是更大的风险
3. `README.md` 与 `README.en.md` 的规则表
4. `CHANGELOG.md` 的 `Unreleased`

如果需要新的扫描事实（比如某类文件），改 `lora_audit/scan.py`——但记住它**只记录、不判断**。

## 4. 代码约定（这几条不是风格偏好，是设计约束）

| 约定 | 为什么 |
|---|---|
| `scan` 不做判断、`rules` 不碰文件系统 | 规则才能是纯函数、才能用合成夹具穷举测试 |
| 用户数据只走 `textContent` / `createElement` | caption 里完全可能含 `<`、`&`、`</script>` |
| 产物里禁远程资源、禁 `type="module"`、禁 `fetch` | `file://` 离线可用是核心承诺，`verify` 会检查 |
| 组件 CSS 只用 `--alc-*` 令牌，不写死颜色 | 深浅色只改令牌层 |
| 中文界面文案 | 与 README.md 一致；英文界面见 [docs/DESIGN.md](docs/DESIGN.md) §9 的触发条件 |
| 不新增必需依赖 | 见 R5 |

## 5. 提 issue 之前

先自己跑一遍，附上材料：

```bash
python3 -m lora_audit --version
python3 -m lora_audit scan <你的数据集> --json - | head -40
```

规则类问题（误报/漏报）请在 issue 里给**目录树 + caption 原文**——[模板](.github/ISSUE_TEMPLATE/bug-report.yml)里也是这么要求的。**不需要附带图片内容**：这个工具的判断只依赖文件名、目录结构和 caption 文本。

## 6. 明确不做的事

提了也会被礼貌拒绝，先写在这里省你时间：

- 本地服务 / 数据库 / 桌面 App / Docker 镜像
- 视频、音频、任何非图像资产
- 团队协作、权限控制、语义搜索
- 训练能力（它只读数据，不碰 kohya / ai-toolkit / OneTrainer）
- 任何需要联网的功能（包括"顺手查一下这个模型"）

理由见 [docs/DESIGN.md](docs/DESIGN.md) §2 的决策表——每一条都写了当初为什么否掉它。

## 7. 许可

提交即表示你同意以 [MIT](LICENSE) 许可发布你的贡献。
