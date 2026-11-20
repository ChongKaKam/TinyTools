// Build review content with DOM nodes so Markdown and code remain inert text.
(() => {
  'use strict';

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  const linesOf = source => source.split(/\r\n|\n|\r/);
  const unescapeText = text => text.replace(/\\([!-/:-@\[-`{-~])/g, '$1');

  // Find a delimiter outside backslash escapes, respecting nested labels and URLs.
  function balancedEnd(text, start, opening, closing) {
    let depth = 1;
    for (let pos = start + 1; pos < text.length; pos++) {
      const char = text[pos];
      if (char === '\\') pos++;
      else if (char === opening) depth++;
      else if (char === closing && --depth === 0) return pos;
    }
    return -1;
  }

  function linkAt(text, start) {
    const image = text.startsWith('![', start);
    const open = start + (image ? 1 : 0);
    const close = balancedEnd(text, open, '[', ']');
    if (close < 0 || text[close + 1] !== '(') return null;
    const end = balancedEnd(text, close + 1, '(', ')');
    if (end < 0) return null;
    const label = text.slice(open + 1, close);
    const target = text.slice(close + 2, end).trim();
    const parts = target.match(/^(?:<([^>\n]*)>|(\S*?))(?:\s+(?:"([^"]*)"|'([^']*)'|\(([^()]*)\)))?$/);
    if (!parts) return null;
    return {
      image, label, end: end + 1,
      href: unescapeText(parts[1] ?? parts[2]),
      title: unescapeText(parts[3] ?? parts[4] ?? parts[5] ?? '')
    };
  }

  function safeHref(value) {
    if (/[\u0000-\u0020\u007f]/.test(value)) return null;
    if (value.startsWith('#')) return value;
    if (!/^(?:https?:\/\/|mailto:)/i.test(value)) return null;
    try {
      return new URL(value).href;
    } catch {
      return null;
    }
  }

  function inline(parent, text, depth = 0) {
    if (depth >= 12) {
      parent.append(text);
      return;
    }
    // Only inspect characters that can start inline markup.
    const tokens = /\\(?:[!-/:-@\[-`{-~]|\r\n|\n|\r)| {2,}(?:\r\n|\n|\r)|`+|!?\[|\*{1,3}|_{1,3}|~~/g;
    let last = 0;
    for (let match; (match = tokens.exec(text));) {
      const marker = match[0];
      const start = match.index;
      let end = tokens.lastIndex;
      let node;
      if (/[\r\n]/.test(marker)) {
        node = element('br');
      } else if (marker.startsWith('\\')) {
        node = marker[1];
      } else if (marker.startsWith('`')) {
        const tail = /`+/g;
        tail.lastIndex = end;
        let close;
        while ((close = tail.exec(text)) && close[0] !== marker) { /* Match the opening run exactly. */ }
        if (!close) continue;
        let value = text.slice(end, close.index).replace(/\r\n|\r|\n/g, ' ');
        if (value.startsWith(' ') && value.endsWith(' ') && /[^ ]/.test(value)) value = value.slice(1, -1);
        node = element('code', '', value);
        end = tail.lastIndex;
      } else if (marker.endsWith('[')) {
        const link = linkAt(text, start);
        if (!link) continue;
        const href = !link.image && safeHref(link.href);
        if (href) {
          node = element('a');
          node.href = href;
          if (!href.startsWith('#')) {
            node.rel = 'noopener noreferrer';
            node.target = '_blank';
          }
          if (link.title) node.title = link.title;
          inline(node, link.label, depth + 1);
        } else {
          node = document.createDocumentFragment();
          inline(node, link.label || (link.image ? '图片' : link.href), depth + 1);
        }
        end = link.end;
      } else {
        if (!text[end] || /\s/.test(text[end])) continue;
        if (marker.startsWith('_') && /[\p{L}\p{N}]/u.test(text[start - 1] || '')) continue;
        let close = text.indexOf(marker, end);
        while (close !== -1 && (close === end || /[\\\s]/.test(text[close - 1]))) {
          close = text.indexOf(marker, close + marker.length);
        }
        if (close === -1) continue;
        if (marker.startsWith('_') && /[\p{L}\p{N}]/u.test(text[close + marker.length] || '')) continue;
        const tag = marker === '~~' ? 'del' : marker.length >= 2 ? 'strong' : 'em';
        node = element(tag);
        const inner = marker.length === 3 ? element('em') : node;
        if (inner !== node) node.append(inner);
        inline(inner, text.slice(end, close), depth + 1);
        end = close + marker.length;
      }
      parent.append(text.slice(last, start), node);
      last = end;
      tokens.lastIndex = end;
    }
    parent.append(text.slice(last));
  }

  function heading(source) {
    const firstLine = linesOf(source)[0];
    const atx = /^ {0,3}(#{1,6})(?:[ \t]+|$)(.*)$/.exec(firstLine);
    const level = atx ? atx[1].length : /(?:\r\n|\r|\n) {0,3}=+[ \t]*$/.test(source.trimEnd()) ? 1 : 2;
    const node = element('h' + level);
    inline(node, atx ? atx[2].replace(/(?:^|[ \t]+)#+[ \t]*$/, '').trim() : firstLine.trim());
    return node;
  }

  function figure(block) {
    const node = element('figure');
    const link = linkAt(block.source.trim(), 0);
    const alt = unescapeText(link?.label || '');
    if (/^[a-f0-9]{64}$/.test(block.asset || '')) {
      const img = element('img');
      img.alt = alt;
      img.src = '/asset/' + block.asset;
      img.loading = 'lazy';
      img.addEventListener('error', () => img.replaceWith(element('span', 'figure-placeholder', '图片未能加载')));
      node.append(img);
    } else {
      node.append(element('span', 'figure-placeholder', '未收录此图片'));
    }
    if (link?.title || alt) node.append(element('figcaption', '', link?.title || alt));
    return node;
  }

  function rowCells(line) {
    const cells = [];
    let cell = '';
    const trimmed = line.trim();
    for (let pos = trimmed.startsWith('|') ? 1 : 0; pos < trimmed.length; pos++) {
      const char = trimmed[pos];
      if (char === '\\' && pos + 1 < trimmed.length) {
        const next = trimmed[++pos];
        cell += next === '|' ? next : char + next;
      } else if (char === '|') {
        cells.push(cell.trim());
        cell = '';
        if (pos === trimmed.length - 1) return cells;
      } else {
        cell += char;
      }
    }
    cells.push(cell.trim());
    return cells;
  }

  function table(source) {
    const [header = '', spec = '', ...rows] = linesOf(source.trimEnd());
    const heads = rowCells(header);
    const alignment = rowCells(spec).map(cell => cell.startsWith(':')
      ? (cell.endsWith(':') ? 'align-center' : 'align-left')
      : (cell.endsWith(':') ? 'align-right' : ''));
    const node = element('table');
    const thead = element('thead');
    const tbody = element('tbody');
    function addRow(parent, cells, isHeader) {
      const tr = element('tr');
      heads.forEach((_, index) => {
        const cell = element(isHeader ? 'th' : 'td', alignment[index]);
        if (isHeader) cell.scope = 'col';
        inline(cell, cells[index] || '');
        tr.append(cell);
      });
      parent.append(tr);
    }
    addRow(thead, heads, true);
    rows.forEach(row => addRow(tbody, rowCells(row), false));
    node.append(thead, tbody);
    const wrapper = element('div', 'table-scroll');
    wrapper.append(node);
    return wrapper;
  }

  function list(source) {
    const root = element('div');
    const stack = [];
    for (const line of linesOf(source)) {
      const marker = /^(\s*)([-+*]|\d{1,9}[.)])[ \t]+(.*)$/.exec(line);
      if (!marker) {
        if (stack.length && line.trim()) {
          const item = stack[stack.length - 1].item;
          item.append(' ');
          inline(item, line.trim());
        }
        continue;
      }
      const indent = marker[1].replace(/\t/g, '    ').length;
      const tag = /^\d/.test(marker[2]) ? 'ol' : 'ul';
      while (stack.length && stack[stack.length - 1].indent > indent) stack.pop();
      let level = stack[stack.length - 1];
      if (level && level.indent === indent && level.tag !== tag) {
        stack.pop();
        level = stack[stack.length - 1];
      }
      if (!level || level.indent < indent) {
        const node = element(tag);
        if (tag === 'ol') node.start = parseInt(marker[2], 10);
        (level ? level.item : root).append(node);
        level = { indent, tag, node };
        stack.push(level);
      }
      level.item = element('li');
      level.node.append(level.item);
      const task = /^\[([ xX])\]\s+(.*)$/.exec(marker[3]);
      if (task) {
        const label = element('label');
        const check = element('input');
        check.type = 'checkbox';
        check.checked = task[1].toLowerCase() === 'x';
        check.disabled = true;
        label.append(check, ' ');
        inline(label, task[2]);
        level.item.append(label);
      } else {
        inline(level.item, marker[3]);
      }
    }
    return root.childElementCount === 1 ? root.firstElementChild : root;
  }

  function quote(source) {
    const node = element('blockquote');
    const body = linesOf(source).map(line => line.replace(/^ {0,3}>[ \t]?/, '')).join('\n');
    for (const part of body.split(/\n\s*\n/)) {
      const paragraph = element('p');
      inline(paragraph, part);
      node.append(paragraph);
    }
    return node;
  }

  const groups = [
    ['python py', 'and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case'],
    ['javascript js jsx typescript ts tsx mjs cjs', 'as async await break case catch class const continue debugger declare default delete do else enum export extends finally for from function get if implements import in instanceof interface let new of private protected public readonly return set static super switch throw try type typeof var void while with yield'],
    ['java c cpp c++ cs csharp go golang rs rust kotlin swift', 'abstract as auto await bool break case catch chan char class const constexpr continue crate default defer do double else enum extern fallthrough float fn for func go goto if impl import int interface let long match mod mut namespace new package pub public range return select self short signed sizeof static string struct switch template throw trait try type typedef union unsigned use using var void volatile where while'],
    ['sh bash zsh shell fish', 'case do done elif else esac export fi for function if in local return set then until while'],
    ['sql mysql sqlite postgresql', 'add all alter and as asc begin between by case create delete desc distinct drop else end exists from group having in index inner insert into is join left like limit not null on or order outer primary right select set table then union unique update values when where with']
  ];
  const words = new Map();
  for (const [aliases, keywords] of groups) {
    const set = new Set(keywords.split(' '));
    aliases.split(' ').forEach(alias => words.set(alias, set));
  }
  const genericWords = new Set(groups.flatMap(([, keys]) => keys.split(' ')));
  const literals = new Set(['true', 'false', 'null', 'none', 'undefined', 'nan', 'infinity', 'nil']);

  // Scan the entire body so multiline comments and strings retain color across line numbers.
  function highlight(body, language, emit) {
    if (/^(text|plaintext|plain|txt|log|output)$/.test(language)) {
      emit('', body);
      return;
    }
    const markup = /^(html?|xml|svg|vue|jsx-html)$/.test(language);
    const sql = /^(sql|mysql|sqlite|postgresql)$/.test(language);
    const python = /^(py|python)$/.test(language);
    const hash = python || /^(bash|sh|zsh|shell|fish|ya?ml|toml|rb|ruby|r|ini|conf|dockerfile)$/.test(language);
    const json = /^(json|jsonc|json5)$/.test(language);
    const css = /^(css|scss|less)$/.test(language);
    const fragments = [];
    if (markup) {
      fragments.push(['comment', /<!--[\s\S]*?(?:-->|$)/], ['tag', /<\/?[\w:.-]+/]);
    } else {
      if (!hash && !json || language === 'jsonc' || language === 'json5') {
        fragments.push(['comment', /\/\*[\s\S]*?(?:\*\/|$)/]);
      }
      if (sql) fragments.push(['comment', /--[^\r\n]*/]);
      else if (hash) fragments.push(['comment', /#[^\r\n]*/]);
      else if (!css && language !== 'json') fragments.push(['comment', /\/\/[^\r\n]*/]);
    }
    if (python) fragments.push(['string', /"""(?:\\[\s\S]|(?!""")[^\\])*?(?:"""|$)|'''(?:\\[\s\S]|(?!''')[^\\])*?(?:'''|$)/]);
    fragments.push(['string', /"(?:\\[^\r\n]|[^"\\\r\n])*"?|'(?:\\[^\r\n]|[^'\\\r\n])*'?/]);
    if (!markup && !json && !python) fragments.push(['string', /`(?:\\[\s\S]|[^`\\])*`?/]);
    fragments.push(
      ['number', /\b(?:0[xX][0-9A-Fa-f_]+|0[bB][01_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)/],
      ['word', /[\p{L}_$][\p{L}\p{N}_$]*/],
      ['operator', /[=+*/!<>%&|?:~-]+/]
    );
    const pattern = new RegExp(fragments.map(([, re]) => '(' + re.source + ')').join('|'), 'gu');
    const keywords = words.get(language) || genericWords;
    let last = 0;
    for (let match; (match = pattern.exec(body));) {
      const at = match.index;
      const value = match[0];
      let kind = fragments[match.findIndex((group, index) => index > 0 && group !== undefined) - 1][0];
      if (kind === 'word') {
        const key = sql ? value.toLowerCase() : value;
        if (literals.has(value.toLowerCase())) kind = 'literal';
        else if (keywords.has(key)) kind = 'keyword';
        else if (/^[ \t]*\(/.test(body.slice(pattern.lastIndex, pattern.lastIndex + 40))) kind = 'name';
        else if ((css || markup || /^(ya?ml|toml)$/.test(language)) && /^[ \t]*[:=]/.test(body.slice(pattern.lastIndex, pattern.lastIndex + 40))) kind = 'name';
        else continue;
      } else if (kind === 'string' && json && /^[ \t]*:/.test(body.slice(pattern.lastIndex, pattern.lastIndex + 40))) {
        kind = 'name';
      } else if (kind === 'tag') {
        kind = 'keyword';
      }
      if (at > last) emit('', body.slice(last, at));
      emit(kind, value);
      last = pattern.lastIndex;
    }
    if (last < body.length) emit('', body.slice(last));
  }

  function codeParts(source) {
    const opening = /^ {0,3}(`{3,}|~{3,})([^\r\n]*)(?:\r\n|\n|\r|$)/.exec(source);
    if (!opening) return { language: '', body: source };
    const fence = opening[1];
    const content = source.slice(opening[0].length);
    const closing = new RegExp('(?:^|(?<=[\\r\\n])) {0,3}' + fence[0] + '{' + fence.length + ',}[ \\t]*(?:\\r\\n|\\n|\\r)?$');
    const match = closing.exec(content);
    return {
      language: opening[2].trim().split(/\s+/, 1)[0],
      body: match ? content.slice(0, match.index) : content
    };
  }

  async function copyText(value) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        return;
      }
    } catch { /* Embedded previews can disable the async clipboard. */ }
    const focus = document.activeElement;
    const field = element('textarea', 'clipboard-buffer');
    field.readOnly = true;
    field.value = value;
    document.body.append(field);
    try {
      field.select();
      if (!document.execCommand('copy')) throw new Error('clipboard unavailable');
    } finally {
      field.remove();
      focus?.focus({ preventScroll: true });
    }
  }

  function code(source) {
    const { language, body } = codeParts(source);
    const node = element('div', 'code-block');
    const toolbar = element('div', 'code-toolbar');
    const copy = element('button', 'copy-code', '复制代码');
    copy.type = 'button';
    copy.setAttribute('aria-live', 'polite');
    let reset;
    copy.addEventListener('click', async () => {
      clearTimeout(reset);
      try {
        await copyText(body);
        copy.textContent = '已复制';
      } catch {
        copy.textContent = '复制失败，请重试';
      }
      reset = setTimeout(() => { copy.textContent = '复制代码'; }, 2200);
    });
    toolbar.append(element('span', 'code-lang', language || '代码'), copy);
    const pre = element('pre', 'code-scroll');
    const codeLines = element('code', 'code-lines');
    let current = null;
    let number = 0;
    function startLine() {
      const line = element('span', 'code-line');
      const gutter = element('span', 'line-number', String(++number));
      gutter.setAttribute('aria-hidden', 'true');
      current = element('span', 'line-text');
      line.append(gutter, current);
      codeLines.append(line);
    }
    highlight(body, language.toLowerCase(), (kind, value) => {
      const pieces = linesOf(value);
      pieces.forEach((piece, index) => {
        if (index) current = null;
        if (!current && (piece || index < pieces.length - 1)) startLine();
        if (piece) current.append(kind ? element('span', 'tok-' + kind, piece) : piece);
      });
    });
    if (!number) startLine();
    pre.append(codeLines);
    node.append(toolbar, pre);
    return node;
  }

  function renderBlock(block) {
    switch (block.kind) {
      case 'heading': return heading(block.source);
      case 'figure': return figure(block);
      case 'table': return table(block.source);
      case 'code': return code(block.source);
      case 'list': return list(block.source);
      case 'quote': return quote(block.source);
      case 'divider': return element('hr');
      default: {
        const node = element('p');
        inline(node, block.source);
        return node;
      }
    }
  }

  window.DocReviewHelperRender = Object.freeze({ renderBlock, headingText: source => heading(source).textContent });
})();
