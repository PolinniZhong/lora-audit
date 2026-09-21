/* ============================================================================
   lora-audit · 报告页脚本
   ----------------------------------------------------------------------------
   经典 <script>（不是 module）：file:// 下 ES Module 会被 CORS 拦掉。
   不 fetch、不 XHR、不请求任何远程资源 —— 数据由构建期内联在
   <script type="application/json" id="la-data"> 里。
   用户数据一律走 textContent / createElement，不拼 innerHTML。
   ========================================================================== */
(function () {
  "use strict";

  var DATA_EL = document.getElementById("la-data");
  if (!DATA_EL) return;
  var D;
  try {
    D = JSON.parse(DATA_EL.textContent);
  } catch (err) {
    document.body.insertAdjacentHTML(
      "afterbegin",
      '<p style="padding:20px;color:#F87171">报告数据损坏，无法解析。</p>'
    );
    return;
  }

  /* 小工具：建元素，属性白名单式赋值，子节点只接字符串/节点 */
  function el(tag, props, kids) {
    var node = document.createElement(tag);
    if (props) {
      for (var k in props) {
        if (!Object.prototype.hasOwnProperty.call(props, k)) continue;
        var v = props[k];
        if (v === null || v === undefined || v === false) continue;
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = v;
        else if (k === "html") node.innerHTML = v; // 仅用于本文件内的固定标记
        else if (k === "dataset") { for (var d in v) node.dataset[d] = v[d]; }
        else if (v === true) node.setAttribute(k, "");
        else node.setAttribute(k, v);
      }
    }
    if (kids) {
      for (var i = 0; i < kids.length; i++) {
        var kid = kids[i];
        if (kid === null || kid === undefined || kid === false) continue;
        node.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
      }
    }
    return node;
  }

  function q(sel) { return document.querySelector(sel); }

  /* 把 `反引号` 段落渲染成 <code>；其余保持纯文本（不解析 HTML） */
  function richText(text) {
    var frag = document.createDocumentFragment();
    var parts = String(text).split("`");
    for (var i = 0; i < parts.length; i++) {
      if (!parts[i]) continue;
      if (i % 2 === 1) frag.appendChild(el("code", { text: parts[i] }));
      else frag.appendChild(document.createTextNode(parts[i]));
    }
    return frag;
  }

  function humanBytes(n) {
    if (n < 1024) return n + " B";
    var u = ["KB", "MB", "GB"], v = n / 1024, i = 0;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return v.toFixed(1) + " " + u[i];
  }

  /* 图片地址在 Python 侧已经做过一次 URL 编码（quote），这里**绝不能再编码**：
     再 encodeURI 一次会把 `010 jump.png` 的 %20 变成 %2520 → ERR_FILE_NOT_FOUND。
     这个 bug verify 查不出来（它只解码一次，路径仍然可达），只有真浏览器能发现。 */
  function srcUrl(src) { return src; }

  /* ------------------------------------------------------------------ 头部 */
  q('[data-bind="title"]').textContent = D.title;
  q('[data-bind="root"]').textContent = D.dataset.root;
  q('[data-bind="root"]').title = D.dataset.root;
  q('[data-bind="generated"]').textContent = D.generated;
  document.title = D.title;

  /* -------------------------------------------------------------- 摘要芯片 */
  var S = D.summary;
  var chips = [];
  function chip(text, value, cls) {
    return el("span", { class: "la-chip" + (cls ? " " + cls : ""), role: "listitem" },
      [text, el("b", { text: String(value) })]);
  }
  chips.push(chip("图片", S.images));
  chips.push(chip("有逐图 caption", S.sidecar));
  if (S.default) chips.push(chip("靠 default 兜底", S.default, "is-warn"));
  if (S.none) chips.push(chip("无 caption", S.none, "is-error"));
  if (S.groups) chips.push(chip("分组", S.groups));
  chips.push(chip("体积", humanBytes(S.bytes)));
  if (S.errors) chips.push(chip("错误", S.errors, "is-error"));
  if (S.warnings) chips.push(chip("警告", S.warnings, "is-warn"));
  // 豁免情况必须明示：豁免 ≠ 隐藏，用户在报告里要能一眼看到"我豁免了什么"
  var ignoredIds = Object.keys(D.ignored || {});
  if (ignoredIds.length) chips.push(chip("已豁免", ignoredIds.join(" "), "is-ok"));
  if (!S.errors && !S.warnings) chips.push(chip("未发现问题", "✓", "is-ok"));
  var chipBox = q('[data-bind="summary"]');
  chips.forEach(function (c) { chipBox.appendChild(c); });

  /* -------------------------------------------------------------- 检查结果 */
  var findingsBox = q('[data-bind="findings"]');
  var findings = D.findings || [];
  // 只有 items 指向**图片**的规则才能拿来筛图。
  // 杂物文件、孤儿 caption 的 items 是路径，不是图——拿它们筛图只会得到空网格。
  var relevant = findings.filter(function (f) {
    return f.kind === "image" && f.items && f.items.length;
  });
  var allClear = !findings.some(function (f) { return f.sev === "error" || f.sev === "warn"; });

  q('[data-bind="finding-count"]').textContent = allClear
    ? "未发现 caption 层面的问题"
    : findings.length + " 条";

  if (!findings.length) {
    findingsBox.appendChild(el("div", { class: "la-finding is-ok" }, [
      el("div", { class: "la-f-head" }, [
        el("span", { class: "la-f-title", text: "没有发现问题" }),
        el("span", { class: "la-f-detail", text: "每张图都有 caption，没有重复、没有触发词漂移、没有杂物文件。" })
      ])
    ]));
  }

  findings.forEach(function (f) {
    var head = el("div", { class: "la-f-head" }, [
      el("span", { class: "la-f-id", text: f.id }),
      el("span", { class: "la-f-title", text: f.title }),
      f.count ? el("span", { class: "la-f-count", text: f.count + " 张" + (f.truncated ? "（另 " + f.truncated + " 张未列出）" : "") }) : null
    ]);
    var kids = [head, el("p", { class: "la-f-detail" }, [richText(f.detail)])];
    if (f.action) kids.push(el("p", { class: "la-f-action" }, [richText(f.action)]));
    if (f.kind === "image" && f.items && f.items.length) {
      kids.push(el("div", { class: "la-f-links" }, [
        el("button", {
          class: "alc-btn", type: "button", dataset: { focusFinding: f.id },
          text: "只看这 " + f.items.length + " 张"
        })
      ]));
    } else if (f.items && f.items.length) {
      // 路径类条目（杂物文件 / 孤儿 caption / 清单里的死链）：给清单，不给筛图按钮
      var list = el("ul", { class: "la-f-files" });
      f.items.forEach(function (p) { list.appendChild(el("li", { text: p })); });
      if (f.truncated) {
        list.appendChild(el("li", { class: "la-f-more", text: "…还有 " + f.truncated + " 个" }));
      }
      kids.push(el("details", { class: "la-f-more-box" }, [
        el("summary", { text: "列出这 " + f.items.length + " 个路径" }), list
      ]));
    }
    findingsBox.appendChild(el("div", { class: "la-finding sev-" + f.sev }, kids));
  });

  /* ------------------------------------------------------------------ 筛选 */
  var filtersBox = q('[data-bind="filters"]');
  var state = { q: "", find: null };
  var filterBtns = [];

  function makeFilter(id, label, cls, count) {
    var btn = el("button", {
      class: "alc-btn" + (cls ? " " + cls : ""), type: "button",
      "aria-pressed": "false", dataset: { filterId: id === null ? "" : id }
    }, [
      cls ? el("span", { class: "la-dot" }) : null,
      label, count !== undefined ? " (" + count + ")" : null
    ]);
    filterBtns.push(btn);
    filtersBox.appendChild(btn);
    return btn;
  }

  makeFilter(null, "全部", null, D.images.length);
  relevant.forEach(function (f) {
    makeFilter(f.id, f.id + " " + f.title, "is-" + f.sev, f.items.length);
  });

  filtersBox.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-filter-id]");
    if (!btn) return;
    var id = btn.dataset.filterId || null;
    state.find = (state.find === id) ? null : id;
    syncFilters();
    scheduleRender(true);
  });

  function syncFilters() {
    filterBtns.forEach(function (b) {
      var id = b.dataset.filterId || null;
      b.setAttribute("aria-pressed", String(id === state.find));
    });
  }

  findingsBox.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-focus-finding]");
    if (!btn) return;
    state.find = btn.dataset.focusFinding;
    syncFilters();
    scheduleRender(true);
    document.getElementById("la-grid-h").scrollIntoView({ block: "start" });
  });

  /* ------------------------------------------------------------------ 搜索 */
  var qInput = document.getElementById("la-q");
  var searchTimer = null;
  qInput.addEventListener("input", function () {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      state.q = qInput.value.trim().toLowerCase();
      scheduleRender(true);
    }, 120);
  });

  /* ------------------------------------------------------------------ 网格 */
  var grid = q('[data-bind="grid"]');
  var emptyMsg = q('[data-bind="empty"]');
  var gridCount = q('[data-bind="grid-count"]');
  var CHUNK = 240;          // 小数据集一次渲染完；大数据集分批，避免首屏卡顿
  var CHUNK_AT = 400;       // 超过这个数量才启用分批
  var rendered = 0;
  var matched = [];         // 命中筛选的图片下标（存下标，避免 indexOf 的 O(n²)）

  function match(img) {
    if (state.find && img.findings.indexOf(state.find) === -1) return false;
    if (state.q) {
      var hay = (img.rel + " " + (img.caption || "") + " " + (img.trigger || "")).toLowerCase();
      if (hay.indexOf(state.q) === -1) return false;
    }
    return true;
  }

  function makeTile(idx) {
    var img = D.images[idx];
    var imgEl = el("img", {
      src: srcUrl(img.src), alt: img.name, loading: "lazy", decoding: "async"
    });
    imgEl.addEventListener("error", function () {
      imgEl.replaceWith(el("span", {
        class: "la-tile-cap", text: "图片读不出来（已被移动或删除）"
      }));
    });
    var badges = [];
    if (img.capSource === "none") badges.push(el("span", { class: "la-badge none", text: "无 caption" }));
    else if (img.capSource === "default") badges.push(el("span", { class: "la-badge w", text: "default 兜底" }));
    img.findings.slice(0, 4).forEach(function (id) {
      badges.push(el("span", {
        class: "la-badge " + (id.charAt(0) === "E" ? "e" : "w"), text: id
      }));
    });
    var capText = img.caption ? img.caption.trim() : "（没有 caption）";
    return el("button", {
      class: "la-tile", type: "button", dataset: { idx: String(idx) }, title: img.rel
    }, [
      el("span", { class: "la-frame" }, [imgEl]),
      el("span", { class: "la-tile-body" }, [
        el("span", { class: "la-tile-name", text: img.name }),
        el("span", { class: "la-tile-cap", text: capText }),
        badges.length ? el("span", { class: "la-tile-badges" }, badges) : null
      ])
    ]);
  }

  function appendChunk() {
    var chunked = matched.length > CHUNK_AT;
    var size = chunked ? CHUNK : matched.length;
    var end = Math.min(rendered + size, matched.length);
    var frag = document.createDocumentFragment();
    for (var i = rendered; i < end; i++) frag.appendChild(makeTile(matched[i]));
    grid.appendChild(frag);
    rendered = end;
    if (chunked) grid.appendChild(sentinel);   // 哨兵始终留在末尾
    gridCount.textContent = "显示 " + rendered + " / 共 " + matched.length + " 张"
      + (matched.length !== D.images.length ? "（已按筛选）" : "");
  }

  var sentinel = el("div", { class: "la-sentinel", "aria-hidden": "true" });
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting && rendered < matched.length) appendChunk();
    }, { rootMargin: "600px" }).observe(sentinel);
  }

  function scheduleRender(reset) {
    if (reset) {
      grid.textContent = "";
      rendered = 0;
    }
    matched = [];
    for (var i = 0; i < D.images.length; i++) {
      if (match(D.images[i])) matched.push(i);
    }
    emptyMsg.hidden = matched.length > 0;
    appendChunk();
  }

  /* ------------------------------------------------------------ 抽屉 / 灯箱 */
  var drawer = document.getElementById("la-drawer");
  var lb = document.getElementById("la-lightbox");
  var lastFocus = null;

  function kv(dt, dd, mono) {
    return [el("dt", { text: dt }),
            el("dd", { class: mono ? "alc-mono" : null, text: dd })];
  }

  function openDrawer(img) {
    lastFocus = document.activeElement;
    var body = q('[data-bind="drawer-body"]');
    body.textContent = "";
    q("#la-drawer-title").textContent = img.name;

    var dl = el("dl", { class: "la-kv" });
    kv("路径", img.rel, true).forEach(function (n) { dl.appendChild(n); });
    kv("分组", img.group || "（根目录）").forEach(function (n) { dl.appendChild(n); });
    kv("尺寸", (img.w && img.h) ? img.w + " × " + img.h : "读不出").forEach(function (n) { dl.appendChild(n); });
    kv("体积", humanBytes(img.bytes)).forEach(function (n) { dl.appendChild(n); });
    kv("caption 来源", img.capSource === "sidecar" ? "同名文件" :
      (img.capSource === "default" ? "继承 default_caption" : "无")).forEach(function (n) { dl.appendChild(n); });
    if (img.captionRel) kv("caption 文件", img.captionRel, true).forEach(function (n) { dl.appendChild(n); });
    kv("触发词", img.trigger || "（没有）", true).forEach(function (n) { dl.appendChild(n); });
    if (img.findings.length) kv("命中规则", img.findings.join(" · "), true).forEach(function (n) { dl.appendChild(n); });
    body.appendChild(dl);

    body.appendChild(el("div", {
      class: "la-cap-box" + (img.caption ? "" : " is-empty"),
      text: img.caption ? img.caption.trim() : "这张图没有 caption"
    }));

    var actions = el("div", { class: "la-drawer-actions" });
    if (img.caption) {
      var copyBtn = el("button", { class: "alc-btn", type: "button", text: "复制 caption" });
      copyBtn.addEventListener("click", function () { copyText(img.caption, copyBtn); });
      actions.appendChild(copyBtn);
    }
    var openBtn = el("button", { class: "alc-btn", type: "button", text: "看大图" });
    openBtn.addEventListener("click", function () { openLightbox(img); });
    actions.appendChild(openBtn);
    body.appendChild(actions);

    body.appendChild(el("div", { class: "la-preview" }, [
      el("img", { src: srcUrl(img.src), alt: img.name, loading: "lazy" })
    ]));

    drawer.hidden = false;
    var closeBtn = drawer.querySelector('[data-close="drawer"]');
    if (closeBtn) closeBtn.focus();
  }

  function copyText(text, btn) {
    var done = function (ok) {
      var old = btn.textContent;
      btn.textContent = ok ? "已复制 ✓" : "复制失败";
      setTimeout(function () { btn.textContent = old; }, 1400);
    };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); },
          function () { done(fallbackCopy(text)); });
      } else {
        done(fallbackCopy(text));
      }
    } catch (e) { done(fallbackCopy(text)); }
  }

  function fallbackCopy(text) {
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (e) { return false; }
  }

  function openLightbox(img) {
    q('[data-bind="lb-img"]').src = srcUrl(img.src);
    q('[data-bind="lb-img"]').alt = img.name;
    var cap = q('[data-bind="lb-cap"]');
    cap.textContent = "";
    cap.appendChild(el("div", { text: img.rel }));
    if (img.caption) cap.appendChild(el("div", { text: img.caption.trim() }));
    lb.hidden = false;
    lb.querySelector('[data-close="lightbox"]').focus();
  }

  function closeAll() {
    drawer.hidden = true;
    lb.hidden = true;
    q('[data-bind="lb-img"]').removeAttribute("src");
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  grid.addEventListener("click", function (ev) {
    var tile = ev.target.closest(".la-tile");
    if (!tile) return;
    var img = D.images[Number(tile.dataset.idx)];
    if (img) openDrawer(img);
  });

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-close]");
    if (btn) closeAll();
    if (ev.target === drawer || ev.target === lb) closeAll();
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") closeAll();
  });

  /* ------------------------------------------------------------------ 主题 */
  var themeBtn = document.getElementById("la-theme");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-alc-theme");
      var next = cur === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-alc-theme", next);
      var meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.setAttribute("content", next === "light" ? "#FFFFFF" : "#0D0F13");
    });
  }

  /* 顶栏高多少，focus 的 scroll-margin 就留多少——不写死数字。
     （踩过的坑：三处写死 top 值 → 2px 缝隙 + 导航被压住。所以这里算，不写死。） */
  var topbar = document.querySelector(".alc-topbar");
  function syncStickyHeight() {
    if (topbar) {
      document.documentElement.style.setProperty(
        "--la-sticky-h", topbar.offsetHeight + "px");
    }
  }
  syncStickyHeight();
  window.addEventListener("resize", syncStickyHeight);

  scheduleRender(true);
  syncStickyHeight();
})();
