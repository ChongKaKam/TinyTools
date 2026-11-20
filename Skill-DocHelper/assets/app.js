"use strict";

(() => {
  const byId = id => document.getElementById(id);
  const url = new URL(location.href);
  const blocks = new Map();
  const dirtyEditors = new Set();
  const outline = [];
  let view;
  let versions;
  let activeLink;
  let scrollFrame = 0;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function button(text, className) {
    const node = element("button", className, text);
    node.type = "button";
    return node;
  }

  async function api(path, params, body) {
    const endpoint = new URL(path, location.origin);
    for (const [name, value] of Object.entries(params || {})) {
      if (value !== null && value !== undefined) endpoint.searchParams.set(name, value);
    }
    const response = await fetch(endpoint, body === undefined ? {cache: "no-store"} : {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
    });
    if (!response.ok) {
      let message = '请求失败（' + response.status + '）';
      try { message = (await response.json()).error || message; } catch { /* Keep HTTP status. */ }
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return response.json();
  }

  function option(value, label) {
    const node = element("option", null, label);
    node.value = String(value);
    return node;
  }

  function loadTheme(id) {
    byId("theme-sheet").href = "/themes/" + encodeURIComponent(id) + ".css";
  }

  function setupThemes(config) {
    const select = byId("theme-select");
    select.replaceChildren(...config.themes.map(theme => option(theme.id, theme.label)));
    if (!config.themes.length) return;
    const theme = config.themes.find(item => item.id === url.searchParams.get("theme"))
      || config.themes.find(item => item.id === config.default) || config.themes[0];
    select.value = theme.id;
    loadTheme(theme.id);
    byId("theme-picker").hidden = false;
    select.addEventListener("change", () => {
      loadTheme(select.value);
      const next = new URL(location.href);
      next.searchParams.set("theme", select.value);
      history.replaceState(null, "", next);
    });
  }

  function navigate(doc, version) {
    const next = new URL(location.href);
    next.searchParams.set("doc", doc);
    if (version === null) next.searchParams.delete("version");
    else next.searchParams.set("version", version);
    next.hash = "";
    location.assign(next);
  }

  function setupDocs(docs, selected) {
    const select = byId("doc-select");
    select.replaceChildren(...docs.map(doc => option(doc.id, doc.title + " · " + doc.id)));
    select.value = selected;
    select.addEventListener("change", () => {
      const target = select.value;
      select.value = selected;
      navigate(target, null);
    });
    byId("doc-picker").hidden = false;
  }

  function versionLabel(version) {
    const suffix = version.version === versions[0].version ? " · 最新" : "";
    return "v" + version.version + suffix + " · " + version.notes + " 条批注";
  }

  function summarize() {
    const noted = view.blocks.reduce((total, block) => total + (block.note ? 1 : 0), 0);
    byId("totals").textContent = view.blocks.length + " 个内容块 · " + noted + " 条批注";
    const selected = versions.find(version => version.version === view.version);
    if (selected) selected.notes = noted;
    const picker = byId("version-select");
    picker.replaceChildren(...versions.map(version => option(version.version, versionLabel(version))));
    picker.value = String(view.version);
  }

  function setupCover() {
    document.title = view.title + " · v" + view.version + " · DocHelper";
    byId("doc-title").textContent = view.title;
    const time = byId("published");
    time.dateTime = view.created;
    const date = new Date(view.created);
    time.textContent = Number.isNaN(date.valueOf()) ? view.created : date.toLocaleString("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
    });
    summarize();
    const picker = byId("version-select");
    picker.addEventListener("change", () => {
      const target = picker.value;
      picker.value = String(view.version);
      navigate(view.doc, target);
    });
  }

  function updateFilter() {
    const filtered = byId("only-noted").checked;
    let visible = 0;
    for (const entry of blocks.values()) {
      const hidden = filtered && !entry.block.note && !entry.editing;
      // The cover always identifies the document, including in a notes-only view.
      if (entry.isTitle) entry.cell.hidden = hidden;
      else entry.row.hidden = hidden;
      if (!hidden) visible++;
    }
    byId("empty-filter").hidden = !filtered || visible > 0;
    scheduleOutlineUpdate();
  }

  function beforeUnload(event) {
    event.preventDefault();
    event.returnValue = "";
  }

  function setDirty(id, dirty) {
    if (dirty) dirtyEditors.add(id);
    else dirtyEditors.delete(id);
    if (dirtyEditors.size) window.addEventListener("beforeunload", beforeUnload);
    else window.removeEventListener("beforeunload", beforeUnload);
  }

  function blockLink(block) {
    const link = element("a", "block-link", "#" + block.id);
    link.href = "#block-" + block.id;
    link.title = "第 " + block.id + " 块的永久链接";
    link.setAttribute("aria-label", link.title);
    return link;
  }

  function showNote(entry, focus = false) {
    const {cell, block} = entry;
    entry.editing = false;
    setDirty(block.id, false);
    const edit = button(block.note ? "编辑批注" : "添加批注", block.note ? "edit-note" : "add-note");
    edit.setAttribute("aria-label", edit.textContent + "，第 " + block.id + " 块");
    edit.addEventListener("click", () => editNote(entry));
    const tools = element("div", "note-tools");
    tools.append(edit, blockLink(block));
    if (block.note) {
      const card = element("div", "saved-card");
      card.append(element("p", "saved-text", block.note), tools);
      cell.replaceChildren(card);
    } else {
      cell.replaceChildren(tools);
    }
    if (focus) {
      updateFilter();
      (entry.row.hidden || entry.cell.hidden ? byId("only-noted") : edit).focus({preventScroll: true});
    }
  }

  function editNote(entry) {
    if (entry.editing) return;
    entry.editing = true;
    const {block, cell} = entry;
    const form = element("form", "note-form");
    const label = element("label", "note-label", "第 " + block.id + " 块的批注");
    const input = element("textarea");
    input.id = "editor-" + block.id;
    label.htmlFor = input.id;
    input.value = block.note;
    const actions = element("div", "note-actions");
    const save = element("button", "save-note", "保存");
    save.type = "submit";
    save.title = "保存批注（Ctrl / ⌘ + Enter）";
    const cancel = button("取消", "cancel-note");
    actions.append(save, cancel);
    const conflict = element("div", "conflict-info");
    conflict.hidden = true;
    const status = element("span", "note-status");
    status.setAttribute("role", "status");
    form.append(label, input, conflict, actions, status);
    cell.replaceChildren(form);
    input.focus();

    let busy = false;
    function track() {
      const edited = input.value !== block.note;
      setDirty(block.id, busy || edited);
      return edited;
    }
    input.addEventListener("input", () => {
      status.textContent = track() ? "待保存" : "";
    });
    function abandon() {
      if (busy) return;
      if (track() && !window.confirm("放弃这条未保存的批注草稿？")) return;
      showNote(entry, true);
    }
    cancel.addEventListener("click", abandon);
    form.addEventListener("keydown", event => {
      if (event.isComposing) return;
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        form.requestSubmit();
      } else if (event.key === "Escape") {
        event.preventDefault();
        abandon();
      }
    });
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (busy) return;
      if (input.value === block.note) {
        showNote(entry, true);
        return;
      }
      busy = true;
      setDirty(block.id, true);
      save.disabled = cancel.disabled = true;
      input.readOnly = true;
      status.textContent = "正在保存…";
      try {
        const result = await api("/api/note", null, {
          doc: view.doc, version: view.version, block: block.id, text: input.value, rev: block.rev,
        });
        Object.assign(block, {note: result.note, rev: result.rev});
        summarize();
        showNote(entry, true);
      } catch (error) {
        status.textContent = "保存失败，草稿已保留。" + error.message;
        if (error.status === 409) {
          try {
            const fresh = await api("/api/view", {doc: view.doc, version: view.version});
            const record = fresh.blocks.find(other => other.id === block.id);
            if (!record) throw new Error("此内容块不可用");
            Object.assign(block, {note: record.note, rev: record.rev});
            summarize();
            conflict.hidden = false;
            conflict.replaceChildren(
              element("p", null, "其他窗口已修改此批注，当前已保存的内容为"),
              element("p", "server-text", record.note || "（空）"),
            );
            save.textContent = "采用我的草稿";
            cancel.textContent = "采用已保存内容";
            status.textContent = "请核对两个版本后选择，也可以继续修改草稿。";
          } catch (reloadError) {
            status.textContent = "批注已变更，读取最新内容失败。请再按保存重试。" + reloadError.message;
          }
        }
      } finally {
        busy = false;
        if (entry.editing) {
          input.readOnly = save.disabled = cancel.disabled = false;
          track();
        }
      }
    });
  }

  function updateOutline() {
    scrollFrame = 0;
    const headings = byId("only-noted").checked ? outline.filter(item => !item.row.hidden && !item.row.querySelector(".note-cell").hidden) : outline;
    let low = 0;
    let high = headings.length;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      if (headings[middle].row.getBoundingClientRect().top <= 30) low = middle + 1;
      else high = middle;
    }
    const current = headings[Math.max(0, low - 1)]?.link;
    if (activeLink !== current) {
      activeLink?.removeAttribute("aria-current");
      current?.setAttribute("aria-current", "location");
      activeLink = current;
    }
  }

  function scheduleOutlineUpdate() {
    if (!scrollFrame) scrollFrame = window.requestAnimationFrame(updateOutline);
  }

  function setupOutline(headings) {
    const nav = byId("outline-nav");
    if (headings.length) {
      const list = element("ol");
      const firstLevel = headings.reduce((min, item) => Math.min(min, item.level), 6);
      headings.forEach(({row, text, level}) => {
        const depth = Math.min(3, level - firstLevel);
        const link = element("a", "depth-" + depth, text);
        link.href = "#" + row.id;
        link.addEventListener("click", () => {
          if (row.hidden || row.querySelector(".note-cell").hidden) {
            byId("only-noted").checked = false;
            updateFilter();
          }
          document.querySelector(".mobile-outline").setAttribute("aria-expanded", "false");
        });
        const item = element("li");
        item.append(link);
        list.append(item);
        outline.push({link, row});
      });
      nav.append(list);
    } else {
      nav.append(element("p", "outline-empty", "本文没有分节标题"));
    }
    const toggle = document.querySelector(".mobile-outline");
    toggle.addEventListener("click", () => {
      toggle.setAttribute("aria-expanded", String(toggle.getAttribute("aria-expanded") === "false"));
    });
    window.addEventListener("scroll", scheduleOutlineUpdate, {passive: true});
    window.addEventListener("resize", scheduleOutlineUpdate);
  }

  function renderBlocks() {
    const rows = document.createDocumentFragment();
    const headings = [];
    for (const block of view.blocks) {
      const node = window.DocHelperRender.renderBlock(block);
      const heading = block.kind === "heading" ? window.DocHelperRender.headingText(block.source) : null;
      const isTitle = block === view.blocks[0] && node.tagName === "H1" && heading === view.title;
      const row = isTitle ? document.querySelector(".cover-row") : element("div");
      row.classList.add("columns", "review-row");
      row.id = "block-" + block.id;
      if (isTitle) {
        byId("doc-title").replaceChildren(...node.childNodes);
      } else {
        const content = element("div", "block-content");
        content.append(node);
        row.append(content);
        rows.append(row);
      }
      if (heading !== null) {
        headings.push({row, level: Number(node.tagName.slice(1)) || 1, text: heading});
      }
      const cell = element("aside", "note-cell");
      cell.setAttribute("aria-label", "第 " + block.id + " 块的批注");
      const entry = {row, cell, block, isTitle, editing: false};
      blocks.set(block.id, entry);
      showNote(entry);
      row.append(cell);
    }
    byId("blocks").replaceChildren(rows);
    setupOutline(headings);
    byId("only-noted").addEventListener("change", updateFilter);
    byId("show-all").addEventListener("click", () => {
      byId("only-noted").checked = false;
      updateFilter();
      byId("only-noted").focus();
    });
  }

  function scrollToHash() {
    const row = byId(location.hash.slice(1));
    if (!row || !row.classList.contains("review-row")) return;
    if (row.hidden || row.querySelector(".note-cell").hidden) {
      byId("only-noted").checked = false;
      updateFilter();
    }
    row.scrollIntoView();
  }

  async function init() {
    const [config, catalog] = await Promise.all([api("/api/themes"), api("/api/docs")]);
    setupThemes(config);
    if (!catalog.docs.length) {
      byId("message").textContent = "此工作目录还没有已发布的审阅文档。";
      return;
    }
    const doc = url.searchParams.get("doc") || catalog.docs[0].id;
    setupDocs(catalog.docs, doc);
    const selected = url.searchParams.get("version");
    const historyResult = await api("/api/history", {doc});
    versions = historyResult.versions;
    const number = selected || versions[0]?.version;
    view = await api("/api/view", {doc, version: number});
    // Pin even a "latest" link before emitting per-block permalinks.
    const pinned = new URL(location.href);
    pinned.searchParams.set("doc", view.doc);
    pinned.searchParams.set("version", view.version);
    history.replaceState(null, "", pinned);
    setupCover();
    renderBlocks();
    byId("message").hidden = true;
    byId("cover").hidden = false;
    byId("desk").hidden = false;
    window.addEventListener("hashchange", scrollToHash);
    window.requestAnimationFrame(() => { scrollToHash(); updateOutline(); });
  }

  init().catch(error => {
    const message = byId("message");
    message.hidden = false;
    message.textContent = "无法载入审阅文档。" + error.message + " ";
    const link = element("a", null, "打开工作目录中的文档");
    link.href = "/";
    message.append(link);
  });
})();
