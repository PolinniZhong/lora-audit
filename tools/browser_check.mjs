#!/usr/bin/env node
/**
 * 浏览器实测：用 CDP 驱动真实 Chrome 打开生成的报告页，确认它真的能看。
 *
 * 为什么需要它：`verify` 只能证明"没有远程资源、图片路径可达"，证明不了
 * "脚本没报错、瓦片真的渲染了、抽屉和灯箱点得开"。这三件事只能让浏览器自己说。
 *
 *   node tools/browser_check.mjs examples/demo-dataset/_lora_audit/report.html
 *   node tools/browser_check.mjs report.html --shot /tmp/shot.png
 *
 * 只用 Node 内置模块（child_process / http / fs + 全局 fetch、WebSocket，需 Node ≥ 22）。
 * 本机没装 Chrome 时**跳过**（退出码 0），不让它成为贡献者的门槛。
 *
 * 两个实现细节是实测踩出来的，别改：
 *   1. 走 **browser 级连接 + Target.attachToTarget(flatten) + sessionId**。
 *      Chrome 153 下直连 page 级 WebSocket 时，renderer 域的请求不返回。
 *   2. 加 `--no-sandbox`。在受限进程环境（容器 / 沙箱）里 Chrome 自己的 renderer
 *      沙箱起不来，表现为连接正常、事件能收、但所有 renderer 域命令石沉大海。
 *      本脚本只打开本地 file:// 页面、不访问网络，故可接受。
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const argv = process.argv.slice(2);
const report = argv.find((a) => !a.startsWith("--"));
const shotIdx = argv.indexOf("--shot");
const shotPath = shotIdx >= 0 ? argv[shotIdx + 1] : null;

if (!report) {
  console.error("用法: node tools/browser_check.mjs <report.html> [--shot out.png]");
  process.exit(2);
}
const reportAbs = path.resolve(report);
if (!fs.existsSync(reportAbs)) {
  console.error(`找不到报告文件: ${reportAbs}`);
  process.exit(2);
}

const CANDIDATES = [
  process.env.CHROME,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);
const chrome = CANDIDATES.find((p) => { try { return fs.existsSync(p); } catch { return false; } });
if (!chrome) {
  console.log("SKIP: 本机没有找到 Chrome/Chromium，跳过浏览器实测（设置 CHROME= 可指定路径）");
  process.exit(0);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fileUrl = "file://" + reportAbs.split("/").map(encodeURIComponent).join("/");
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), "lora-audit-chrome-"));
const failures = [];
const notes = [];

const child = spawn(chrome, [
  "--headless=new", "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
  "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--hide-scrollbars", "--force-device-scale-factor=1", "--window-size=1440,1080",
  "--remote-debugging-port=0", `--user-data-dir=${profileDir}`, fileUrl,
], { stdio: ["ignore", "ignore", "pipe"] });

/** Chrome 在 stderr 上打印 "DevTools listening on ws://127.0.0.1:PORT/devtools/browser/…" */
function waitForDevTools() {
  return new Promise((resolve, reject) => {
    let buf = "";
    const timer = setTimeout(() => reject(new Error("Chrome 15s 内没有报告 DevTools 端口")), 15000);
    child.stderr.on("data", (chunk) => {
      buf += chunk.toString();
      const m = buf.match(/ws:\/\/127\.0\.0\.1:(\d+)\/devtools\/browser\//);
      if (m) { clearTimeout(timer); resolve(Number(m[1])); }
    });
    child.on("exit", (code) => { clearTimeout(timer); reject(new Error(`Chrome 提前退出，code=${code}`)); });
  });
}

/** 极简 CDP 客户端（browser 级连接 + flatten session） */
class CDP {
  constructor(ws, sessionId) {
    this.ws = ws; this.sessionId = sessionId;
    this.id = 0; this.pending = new Map(); this.events = [];
  }

  static async attach(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => {
      ws.addEventListener("open", res, { once: true });
      ws.addEventListener("error", () => rej(new Error("WebSocket 连接失败")), { once: true });
    });
    const client = new CDP(ws, null);
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && client.pending.has(msg.id)) {
        const { resolve, reject } = client.pending.get(msg.id);
        client.pending.delete(msg.id);
        msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
      } else if (msg.method) {
        client.events.push(msg);
      }
    });

    const targets = await client.send("Target.getTargets");
    const page = targets.targetInfos.find(
      (t) => t.type === "page" && t.url.startsWith("file:"));
    if (!page) throw new Error("找不到报告页 target");
    const attached = await client.send("Target.attachToTarget",
      { targetId: page.targetId, flatten: true });
    client.sessionId = attached.sessionId;
    return client;
  }

  send(method, params = {}) {
    const id = ++this.id;
    const payload = { id, method, params };
    if (this.sessionId) payload.sessionId = this.sessionId;
    this.ws.send(JSON.stringify(payload));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }

  async eval(expression) {
    const r = await this.send("Runtime.evaluate",
      { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) {
      throw new Error(r.exceptionDetails.text + " " +
        (r.exceptionDetails.exception?.description || ""));
    }
    return r.result.value;
  }

  close() { try { this.ws.close(); } catch { /* 已断开 */ } }
}

let cdp = null;
try {
  const port = await waitForDevTools();
  const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
  cdp = await CDP.attach(version.webSocketDebuggerUrl);
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Page.enable");

  // 等图全部落定（成功或失败都算落定），最多 10s
  await cdp.eval(`new Promise((done) => {
    const t0 = Date.now();
    const tick = () => {
      const imgs = [...document.images].filter((i) => i.getAttribute('src'));
      const settled = imgs.length > 0 && imgs.every((i) => i.complete);
      if (settled || Date.now() - t0 > 10000) done(true);
      else setTimeout(tick, 200);
    };
    tick();
  })`);

  const m = await cdp.eval(`(() => {
    const imgs = [...document.querySelectorAll('.la-frame img')];
    return {
      title: document.title,
      tiles: document.querySelectorAll('.la-tile').length,
      chips: document.querySelectorAll('.la-chip').length,
      findings: document.querySelectorAll('.la-finding').length,
      filters: document.querySelectorAll('[data-filter-id]').length,
      images: imgs.length,
      broken: imgs.filter((i) => i.complete && i.naturalWidth === 0).length,
      gridCount: (document.querySelector('[data-bind="grid-count"]') || {}).textContent,
      findingsVisible: (() => {
        const f = document.querySelector('.la-finding');
        if (!f) return false;
        const r = f.getBoundingClientRect();
        return r.top < window.innerHeight && r.bottom > 0;
      })(),
      firstTileTop: (() => {
        const t = document.querySelector('.la-tile');
        return t ? Math.round(t.getBoundingClientRect().top + window.scrollY) : -1;
      })(),
      viewportH: window.innerHeight,
      bodyHeight: document.body.scrollHeight,
    };
  })()`);

  for (const [k, v] of Object.entries(m)) console.log(`  ${k}: ${v}`);
  if (m.tiles === 0) failures.push("一张图瓦片都没渲染");
  if (m.broken > 0) failures.push(`${m.broken} 张图破了（naturalWidth=0）`);
  if (m.chips === 0) failures.push("摘要芯片没渲染");
  if (m.findings === 0) failures.push("检查结果没渲染");
  // 审计页的主内容是"问题"，所以首屏该看到的是问题卡；图片区只要不是远得离谱
  if (!m.findingsVisible) failures.push("首屏看不到检查结果");
  if (m.firstTileTop > m.viewportH * 2.5) {
    failures.push(`图片区被推到第一屏下方 ${m.firstTileTop}px（超过 2.5 屏）`);
  }

  // 交互：点第一张瓦片 → 抽屉；抽屉里点「看大图」→ 灯箱；Esc 关闭
  const drawerOpened = await cdp.eval(`(() => {
    document.querySelector('.la-tile').click();
    return !document.getElementById('la-drawer').hidden;
  })()`);
  console.log(`  抽屉可打开: ${drawerOpened}`);
  if (!drawerOpened) failures.push("点瓦片没打开抽屉");

  const captionShown = await cdp.eval(
    `document.querySelector('.la-cap-box').textContent.trim().length > 0`);
  if (!captionShown) failures.push("抽屉里没有 caption 内容");

  const lightboxOpened = await cdp.eval(`(() => {
    const b = [...document.querySelectorAll('#la-drawer .alc-btn')]
      .find((x) => x.textContent.includes('看大图'));
    if (!b) return false;
    b.click();
    return !document.getElementById('la-lightbox').hidden;
  })()`);
  console.log(`  灯箱可打开: ${lightboxOpened}`);
  if (!lightboxOpened) failures.push("抽屉里点「看大图」没打开灯箱");

  await cdp.eval(`document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape'}))`);
  const closed = await cdp.eval(
    `document.getElementById('la-lightbox').hidden && document.getElementById('la-drawer').hidden`);
  console.log(`  Esc 可关闭: ${closed}`);
  if (!closed) failures.push("Esc 关不掉抽屉/灯箱");

  // 筛选：点一条「只看这 N 张」。
  // ★ 必须挑一条**真子集**的问题：E001 这类规则可能覆盖全部图片，
  //   点了之后瓦片数当然不变——那是我这套判据的假失败，不是工具的缺陷。
  const filtered = await cdp.eval(`(() => {
    const btns = [...document.querySelectorAll('[data-focus-finding]')];
    const num = (el) => Number((el.textContent.match(/(\\d+)/) || [0, 0])[1]);
    const totalText = document.querySelector('[data-filter-id=""]');
    const total = totalText ? num(totalText) : 0;
    const b = btns.filter((x) => num(x) < total).sort((a, z) => num(a) - num(z))[0];
    if (!b) return { skip: true, total, candidates: btns.length };
    const before = document.querySelectorAll('.la-tile').length;
    b.click();
    return { before, after: document.querySelectorAll('.la-tile').length,
             want: num(b), total };
  })()`);
  if (filtered.skip) {
    notes.push(`没有真子集可筛（${filtered.candidates} 条问题都覆盖全部 ${filtered.total} 张）`);
  } else {
    console.log(`  按问题筛选: ${filtered.before} → ${filtered.after} 张（该问题 ${filtered.want}/${filtered.total}）`);
    if (filtered.after !== filtered.want) {
      failures.push(`按问题筛选结果不对：期望 ${filtered.want} 张，实际 ${filtered.after} 张`);
    }
  }

  // 搜索
  const searched = await cdp.eval(`(() => {
    const btn = document.querySelector('[data-filter-id=""]');
    if (btn) btn.click();                       // 先复位筛选
    const input = document.getElementById('la-q');
    input.value = 'zzz-no-such-thing';
    input.dispatchEvent(new Event('input', {bubbles: true}));
    return new Promise((done) => setTimeout(() => {
      const empty = document.querySelector('[data-bind="empty"]');
      done({ tiles: document.querySelectorAll('.la-tile').length, emptyShown: !empty.hidden });
    }, 300));
  })()`);
  console.log(`  搜索无结果: 瓦片 ${searched.tiles} · 空态提示 ${searched.emptyShown}`);
  if (searched.tiles !== 0 || !searched.emptyShown) failures.push("搜索过滤或空态提示不对");

  // 主题切换
  const themed = await cdp.eval(`(() => {
    const before = document.documentElement.getAttribute('data-alc-theme');
    document.getElementById('la-theme').click();
    return { before, after: document.documentElement.getAttribute('data-alc-theme') };
  })()`);
  console.log(`  主题切换: ${themed.before} → ${themed.after}`);
  if (themed.before === themed.after) failures.push("主题切换无效");

  // 控制台错误
  const errors = cdp.events
    .filter((e) => e.method === "Runtime.exceptionThrown" ||
      (e.method === "Log.entryAdded" &&
        ["error", "warning"].includes(e.params?.entry?.level)))
    .map((e) => e.method === "Runtime.exceptionThrown"
      ? (e.params.exceptionDetails?.exception?.description ||
         e.params.exceptionDetails?.text)
      : (e.params.entry.text + "  ← " + (e.params.entry.url || "无 URL")));
  console.log(`  控制台错误/警告: ${errors.length}`);
  errors.forEach((e) => failures.push("控制台报错: " + String(e).split("\n")[0]));

  if (shotPath) {
    await cdp.eval(`(() => {
      document.getElementById('la-q').value = '';
      document.getElementById('la-q').dispatchEvent(new Event('input', {bubbles:true}));
      document.documentElement.setAttribute('data-alc-theme', 'light');
      window.scrollTo(0, 0);   // 不回顶的话，全页截图会把 sticky 顶栏画在滚动位置
    })()`);
    await sleep(400);
    const { data } = await cdp.send("Page.captureScreenshot",
      { format: "png", captureBeyondViewport: !argv.includes("--viewport-only") });
    fs.writeFileSync(path.resolve(shotPath), Buffer.from(data, "base64"));
    console.log(`  截图: ${path.resolve(shotPath)}`);
  }
} catch (err) {
  failures.push(err.message);
} finally {
  cdp?.close();
  child.kill("SIGKILL");
  // Chrome 被杀后还会往 profile 目录里写一小会儿，直接 rmSync 会 ENOTEMPTY。
  // 清不掉就算了——留个临时目录无所谓，但**绝不能因此把退出码带成失败**。
  try {
    fs.rmSync(profileDir, { recursive: true, force: true, maxRetries: 10, retryDelay: 120 });
  } catch { /* 忽略：临时目录由系统回收 */ }
}

notes.forEach((n) => console.log("  注: " + n));
if (failures.length) {
  console.error("\n浏览器实测不通过：");
  failures.forEach((f) => console.error("  ✗ " + f));
  process.exit(1);
}
console.log("\n浏览器实测通过：渲染、抽屉、灯箱、筛选、搜索、主题、控制台全部正常。");
