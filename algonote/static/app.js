'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const app = $('app');
  const LANG = { python: 'Python 3', cpp: 'C++17' };
  const SOURCE = { leetcode: 'LeetCode', nowcoder: '牛客' };
  const DIFFICULTY = { easy: '简单', medium: '中等', hard: '困难' };
  const MASTERY = { new: '待练习', review: '需复习', mastered: '已掌握' };
  const STATUS = { accepted: '通过已有测试', wrong_answer: '结果不一致', compile_error: '编译错误', runtime_error: '运行错误', time_limit: '运行超时', output_limit: '输出超出限制', runner_unavailable: '执行服务未就绪', no_tests: '还没有可运行的测试', infrastructure_error: '执行服务异常' };
  const TYPES = ['int', 'int64', 'float', 'bool', 'str', 'char', 'char[]', 'char[][]', 'int[]', 'int64[]', 'float[]', 'bool[]', 'str[]', 'int[][]', 'int64[][]', 'float[][]', 'bool[][]', 'str[][]', 'ListNode', 'TreeNode'];
  const state = { health: null, problem: null, route: '', ticket: 0, editDirty: false, practice: null, leaving: false };
  let token = sessionStorage.getItem('algonote-token') || '';
  let toastId = 0;
  const draftScope = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'value') node.value = value;
      else if (key === 'checked' || key === 'disabled' || key === 'hidden' || key === 'required' || key === 'readOnly') node[key] = !!value;
      else node.setAttribute(key, String(value));
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }
  function button(text, style, fn, attrs = {}) { return el('button', { type: 'button', class: `button ${style || 'button-secondary'}`, onclick: fn ? () => attempt(fn) : undefined, ...attrs }, text); }
  function select(options, value, attrs = {}) {
    const node = el('select', attrs, Object.entries(options).map(([key, label]) => el('option', { value: key }, label)));
    node.value = value || Object.keys(options)[0];
    return node;
  }
  function field(label, control, help, required = false) {
    if (!control.id) control.id = `field-${Math.random().toString(36).slice(2, 10)}`;
    return el('div', { class: 'field' }, el('label', { class: 'field-label', for: control.id }, label, required ? el('span', { class: 'required' }, ' *') : null), control, help ? el('p', { class: 'field-help' }, help) : null);
  }
  function notice(text, type = '') { return el('div', { class: `notice ${type}`, role: type === 'error' ? 'alert' : 'note' }, text); }
  function toast(text, type = '') {
    const item = el('div', { class: `toast ${type}`, id: `toast-${++toastId}` }, text);
    item.append(el('button', { type: 'button', 'aria-label': '关闭提示', onclick: () => item.remove() }, '×'));
    $('toast-region').append(item);
    setTimeout(() => item.remove(), type === 'error' ? 11000 : 5000);
  }
  async function attempt(fn) { try { return await fn(); } catch (err) { toast(err.message || '操作失败，请稍后重试。', 'error'); } }
  async function busy(btn, label, fn) {
    const oldText = btn.textContent;
    btn.disabled = true; btn.textContent = label;
    try { return await fn(); } finally { btn.disabled = false; btn.textContent = oldText; }
  }
  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (token) headers.set('Authorization', `Bearer ${token}`);
    let body = options.body;
    if (body !== undefined && typeof body !== 'string' && !(body instanceof Blob)) { headers.set('Content-Type', 'application/json'); body = JSON.stringify(body); }
    let response;
    try { response = await fetch(`/api${path}`, { ...options, headers, body }); }
    catch (_) { throw new Error('暂时无法连接服务。请确认 AlgoNote 已启动，再试一次。'); }
    if (!response.ok) {
      let data = {};
      try { data = await response.json(); } catch (_) {}
      let message = data.detail || data.message || `请求失败（${response.status}）。`;
      if (Array.isArray(message)) message = message.slice(0, 4).map((e) => `${(e.loc || []).filter((x) => x !== 'body').join(' · ')}：${e.msg || '格式不正确'}`).join('\n');
      if (typeof message !== 'string') message = JSON.stringify(message);
      if (response.status === 401) { showSettings(true); message = '需要正确的访问口令，请在设置中连接。'; }
      if (response.status === 409) message = `内容已发生变化，请重新打开题目后再修改。\n${message}`;
      const error = new Error(message); error.status = response.status; throw error;
    }
    if (options.blob) return response.blob();
    if (response.status === 204) return null;
    return response.json();
  }
  function dateText(iso, full = false) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString('zh-CN', full ? { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' } : { month: '2-digit', day: '2-digit' });
  }
  function jsonText(value) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
  function sourceLabel(p) { return el('span', { class: 'source-label' }, el('span', { class: `source-dot ${p.source}` }), SOURCE[p.source] || p.source); }
  function badge(text, cls = '') { return el('span', { class: `badge ${cls}` }, text); }
  function statusNode(status) { return el('span', {}, el('span', { class: `status-dot ${status === 'accepted' ? 'good' : ['runner_unavailable', 'no_tests', 'infrastructure_error'].includes(status) ? 'warn' : 'bad'}` }), STATUS[status] || status); }
  function segmented(value, onChange) {
    const box = el('div', { class: 'segmented', role: 'group', 'aria-label': '编程语言' });
    for (const [key, label] of Object.entries(LANG)) box.append(el('button', { type: 'button', class: `segment ${key === value ? 'active' : ''}`, 'aria-pressed': key === value, onclick: () => attempt(async () => {
      if (key === box.dataset.value) return;
      const result = await onChange(key);
      if (result === false || !box.isConnected) return;
      box.dataset.value = key;
      [...box.children].forEach((b, i) => { const active = Object.keys(LANG)[i] === key; b.classList.toggle('active', active); b.setAttribute('aria-pressed', String(active)); });
    }) }, label));
    box.dataset.value = value;
    return box;
  }
  function codeEditing(textarea) {
    textarea.spellcheck = false;
    textarea.autocapitalize = 'off';
    textarea.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab') return;
      e.preventDefault();
      const start = textarea.selectionStart, end = textarea.selectionEnd;
      if (e.shiftKey) {
        const lineStart = textarea.value.lastIndexOf('\n', start - 1) + 1;
        const spaces = Math.min(4, (textarea.value.slice(lineStart).match(/^ */) || [''])[0].length);
        if (!spaces) return;
        textarea.setRangeText('', lineStart, lineStart + spaces, 'preserve');
      } else textarea.setRangeText('    ', start, end, 'end');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });
    return textarea;
  }
  // Small Markdown subset. Every piece is constructed as text; raw HTML is never interpreted.
  function inlineText(parent, text) {
    const parts = String(text).split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
    for (const part of parts) {
      if (part.startsWith('`') && part.endsWith('`')) parent.append(el('code', {}, part.slice(1, -1)));
      else if (part.startsWith('**') && part.endsWith('**')) parent.append(el('strong', {}, part.slice(2, -2)));
      else parent.append(document.createTextNode(part));
    }
    return parent;
  }
  function markdown(text) {
    const container = el('div', { class: 'prose' });
    const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
    let paragraph = [], code = null, list = null;
    const flush = () => { if (paragraph.length) container.append(inlineText(el('p'), paragraph.join('\n'))); paragraph = []; list = null; };
    for (const line of lines) {
      if (/^\s*```/.test(line)) { if (code !== null) { container.append(el('pre', {}, code.join('\n'))); code = null; } else { flush(); code = []; } continue; }
      if (code !== null) { code.push(line); continue; }
      const heading = line.match(/^(#{1,4})\s+(.+)$/);
      const bullet = line.match(/^\s*[-*+]\s+(.+)$/);
      const number = line.match(/^\s*\d+[.)]\s+(.+)$/);
      if (heading) { flush(); container.append(inlineText(el(`h${heading[1].length}`), heading[2])); }
      else if (bullet || number) {
        if (paragraph.length) flush();
        const tag = bullet ? 'UL' : 'OL';
        if (!list || list.tagName !== tag) { list = el(tag.toLowerCase()); container.append(list); }
        list.append(inlineText(el('li'), (bullet || number)[1]));
      } else if (/^>\s?/.test(line)) { flush(); container.append(inlineText(el('blockquote'), line.replace(/^>\s?/, ''))); }
      else if (!line.trim()) flush();
      else { list = null; paragraph.push(line); }
    }
    if (code !== null) container.append(el('pre', {}, code.join('\n')));
    flush();
    return container;
  }
  function safeExternalLink(url, label) {
    try { const parsed = new URL(url); if (!['http:', 'https:'].includes(parsed.protocol)) return null; return el('a', { href: parsed.href, target: '_blank', rel: 'noopener noreferrer', class: 'link-line' }, label, ' ↗'); } catch (_) { return null; }
  }

  function showSettings(open) { $('settings-panel').hidden = !open; $('settings-toggle').setAttribute('aria-expanded', String(open)); }
  function renderHealth() {
    const h = state.health;
    const root = $('service-status'); root.replaceChildren();
    if (!h) { root.append(notice('暂未连接到服务，请检查应用是否已启动。', 'warning')); return; }
    root.append(el('div', { class: 'service-item' }, '题库保存', badge('已连接', 'mastered')));
    root.append(el('div', { class: 'service-item' }, '代码运行', badge(h.runner?.available ? '已就绪' : '待配置', h.runner?.available ? 'mastered' : 'review')));
    if (!h.runner?.available) root.append(el('p', { class: 'service-detail' }, h.runner?.detail || '执行服务尚未启动；题库、题解与草稿仍然可以使用。'));
    root.append(el('div', { class: 'service-item' }, 'AI 题解', badge(h.ai?.configured ? '已配置' : '待配置', h.ai?.configured ? 'mastered' : 'review')));
    if (!h.ai?.configured) root.append(el('p', { class: 'service-detail' }, '在服务端配置模型与 API Key 后可生成解析，也可以直接编写自己的题解。'));
  }
  async function refreshHealth() { try { state.health = await api('/health'); } catch (_) { state.health = null; } renderHealth(); }
  function loading() { app.classList.remove('practice-width'); app.replaceChildren(el('div', { class: 'loading-state' }, el('span', { class: 'spinner' }), el('p', {}, '正在打开…'))); }
  function setActiveNav(route) { $('nav-library').classList.toggle('active', route !== 'new' && !route.startsWith('edit/')); $('nav-new').classList.toggle('active', route === 'new' || route.startsWith('edit/')); }
  async function navigate(route, { replace = false, fromHistory = false } = {}) {
    if (state.leaving) return;
    state.leaving = true;
    try {
      if (state.editDirty && !window.confirm('当前修改还没有保存。离开此页会丢失这些修改，确定离开吗？')) {
        if (fromHistory) history.replaceState(null, '', `#${state.route || 'library'}`);
        return;
      }
      if (state.practice) {
        try { await flushDraft(state.practice); }
        catch (error) {
          if (fromHistory) history.replaceState(null, '', `#${state.route || 'library'}`);
          toast(`草稿尚未保存，请先处理编辑区中的提示。${error.message}`, 'error'); return;
        }
      }
      state.editDirty = false;
      if (state.practice) clearTimeout(state.practice.timer);
      state.practice = null;
      state.route = route || 'library';
      if (!fromHistory) history[replace ? 'replaceState' : 'pushState'](null, '', `#${state.route}`);
      setActiveNav(state.route); showSettings(false);
      const ticket = ++state.ticket;
      loading();
      window.scrollTo(0, 0);
      const [view, id] = state.route.split('/');
      if (view === 'new') renderForm(null);
      else if (['problem', 'edit', 'practice'].includes(view) && id) {
        const problem = await api(`/problems/${encodeURIComponent(id)}`);
        if (ticket !== state.ticket) return;
        state.problem = problem;
        if (view === 'edit') renderForm(problem);
        else if (view === 'practice') await renderPractice(problem, ticket);
        else await renderDetail(problem, ticket);
      } else await renderLibrary(ticket);
    } catch (err) {
      if (err.status === 401) renderAuth();
      else app.replaceChildren(el('div', { class: 'empty-state' }, el('h2', {}, '暂时无法打开'), el('p', {}, err.message), button('返回题库', 'button-primary', () => navigate('library'))));
    } finally { state.leaving = false; }
  }
  function renderAuth() {
    const input = el('input', { type: 'password', placeholder: '输入个人访问口令', 'aria-label': '访问口令', autocomplete: 'off' });
    const submit = el('button', { type: 'submit', class: 'button button-primary' }, '打开题库');
    const form = el('form', { onsubmit: (e) => { e.preventDefault(); attempt(() => busy(submit, '连接中…', async () => { token = input.value.trim(); sessionStorage.setItem('algonote-token', token); $('access-token').value = token; await navigate(state.route || 'library', { replace: true }); })); } }, input, submit);
    app.replaceChildren(el('div', { class: 'auth-state' }, el('div', { class: 'empty-graphic' }, 'a·'), el('h2', {}, '打开你的刷题手记'), el('p', {}, '这个题库设置了个人访问口令。输入后即可继续。'), form));
  }

  async function renderLibrary(ticket) {
    let filterTimer, requestNo = 0;
    const search = el('input', { type: 'search', placeholder: '搜索题目、标签或关键词…', 'aria-label': '搜索题目' });
    const source = select({ '': '全部来源', leetcode: 'LeetCode', nowcoder: '牛客' }, '', { 'aria-label': '按来源筛选' });
    const mastery = select({ '': '全部状态', ...MASTERY }, '', { 'aria-label': '按掌握状态筛选' });
    const tag = el('input', { type: 'text', placeholder: '标签', 'aria-label': '按标签筛选', class: 'tag-filter' });
    const list = el('div', { class: 'problem-list' });
    const count = el('p', {}, '正在读取题目');
    const totalStat = el('strong', {}, '—');
    const hero = el('section', { class: 'hero' }, el('div', {}, el('p', { class: 'eyebrow' }, 'YOUR ALGORITHM NOTEBOOK'), el('h1', {}, '把做过的题，真正学会。'), el('p', { class: 'hero-copy' }, '留下自己的解法，理清思路，再独立做一次。')), el('div', { class: 'hero-side' }, el('div', { class: 'hero-stat' }, totalStat, el('span', {}, '道题目，慢慢积累')), button('＋ 录入题目', 'button-primary', () => navigate('new'))));
    app.replaceChildren(hero, el('div', { class: 'toolbar' }, el('div', { class: 'search-box' }, search), source, mastery, tag), el('div', { class: 'list-heading' }, el('h2', {}, '我的题库'), count), list);
    async function refresh() {
      const current = ++requestNo;
      const qs = new URLSearchParams();
      if (search.value.trim()) qs.set('q', search.value.trim());
      if (source.value) qs.set('source', source.value);
      if (mastery.value) qs.set('mastery', mastery.value);
      if (tag.value.trim()) qs.set('tag', tag.value.trim());
      const data = await api(`/problems?${qs}`);
      if (ticket !== state.ticket || current !== requestNo) return;
      const items = data.items || [];
      totalStat.textContent = data.total ?? items.length;
      count.textContent = `${items.length} 道题目 · C++ / Python`;
      list.replaceChildren();
      if (!items.length) {
        list.className = '';
        const filtered = !!qs.size;
        list.append(el('div', { class: 'empty-state' }, el('div', { class: 'empty-graphic', 'aria-hidden': 'true' }, '{ }'), el('h2', {}, filtered ? '还没有匹配的题目' : '从一道题开始'), el('p', {}, filtered ? '试试其他关键词，或调整筛选条件。' : '粘贴题目和你的参考代码，给每一次思考留一个位置。'), button(filtered ? '清除筛选' : '录入第一道题', 'button-primary', () => { if (!filtered) return navigate('new'); search.value = ''; source.value = ''; mastery.value = ''; tag.value = ''; return refresh(); })));
      } else {
        list.className = 'problem-list';
        for (const p of items) {
          const tags = (p.tags || []).slice(0, 4).map((t) => el('span', { class: 'tag' }, t));
          const langs = p.languages || Object.keys(p.references || {});
          const excerpt = p.excerpt || p.statement || (p.mode === 'stdin' ? '标准输入输出 · 完整程序练习' : '函数模式 · 专注核心算法');
          list.append(el('article', { class: 'problem-card' }, el('div', { class: 'card-top' }, sourceLabel(p), badge(DIFFICULTY[p.difficulty] || '中等', p.difficulty)), el('button', { type: 'button', class: 'problem-title', onclick: () => attempt(() => navigate(`problem/${p.id}`)) }, p.title), el('p', { class: 'card-excerpt' }, excerpt.replace(/[#*`\n]/g, ' ')), el('div', { class: 'card-tags' }, tags), el('div', { class: 'card-footer' }, el('div', { class: 'card-meta' }, badge(MASTERY[p.mastery] || '待练习', p.mastery), el('span', {}, langs.map((l) => l === 'cpp' ? 'C++' : 'Python').join(' / ')), el('span', {}, dateText(p.updated_at))), button('再做一次 ↗', 'button-quiet button-sm', () => navigate(`practice/${p.id}`), { 'aria-label': `重做 ${p.title}` }))));
        }
      }
    }
    const deferredRefresh = () => { clearTimeout(filterTimer); filterTimer = setTimeout(() => attempt(refresh), 230); };
    search.addEventListener('input', deferredRefresh); tag.addEventListener('input', deferredRefresh);
    source.addEventListener('change', () => attempt(refresh)); mastery.addEventListener('change', () => attempt(refresh));
    await refresh();
  }

  function breadcrumb(label) { return el('div', { class: 'breadcrumb' }, el('button', { type: 'button', onclick: () => attempt(() => navigate('library')) }, '我的题库'), el('span', {}, '/'), el('span', {}, label)); }
  function showTests(tests) {
    if (!tests.length) return el('div', { class: 'empty-inline' }, '还没有测试用例。编辑题目后可补充。');
    return el('div', { class: 'test-list' }, tests.map((t, i) => el('div', { class: 'test-card' }, el('h4', {}, t.name || `测试 ${i + 1}`, badge(t.sample ? '样例' : '扩展测试')), el('div', { class: 'test-values' }, el('div', { class: 'test-value' }, el('small', {}, '输入'), el('pre', {}, jsonText(t.input))), el('div', { class: 'test-value' }, el('small', {}, '预期结果'), el('pre', {}, jsonText(t.expected)))))));
  }
  async function renderDetail(p, ticket) {
    const [explanationData, attemptData] = await Promise.all([api(`/problems/${p.id}/explanations`), api(`/problems/${p.id}/attempts`)]);
    if (ticket !== state.ticket) return;
    let explanations = explanationData.items || [], attempts = attemptData.items || [];
    let language = p.references?.python ? 'python' : 'cpp', currentTab = 'statement', generating = false;
    const content = el('div', { class: 'panel-body' });
    const tabs = el('div', { class: 'tab-bar' });
    const sideMastery = select(MASTERY, p.mastery, { 'aria-label': '掌握状态' });
    sideMastery.addEventListener('change', () => attempt(async () => {
      try { const updated = await api(`/problems/${p.id}`, { method: 'PUT', body: { ...editable(p), revision: p.revision, mastery: sideMastery.value } }); Object.assign(p, updated); toast('掌握状态已保存。'); }
      catch (err) { sideMastery.value = p.mastery; throw err; }
    }));
    const mainPanel = el('section', { class: 'panel' }, tabs, content);
    const heading = el('div', { class: 'page-heading' }, el('div', {}, sourceLabel(p), el('h1', {}, p.title), el('div', { class: 'page-subtitle' }, badge(DIFFICULTY[p.difficulty], p.difficulty), el('span', {}, p.mode === 'function' ? '函数模式' : '标准输入输出'), el('span', {}, `版本 ${p.revision}`), ...(p.tags || []).map((t) => el('span', { class: 'tag' }, t)))), el('div', { class: 'button-row' }, button('编辑题目', 'button-secondary', () => navigate(`edit/${p.id}`)), button('再做一次 →', 'button-primary', () => navigate(`practice/${p.id}`))));
    const aside = el('aside', { class: 'detail-aside' }, el('div', { class: 'panel side-panel' }, el('h3', {}, '我的掌握情况'), sideMastery, el('p', { class: 'field-help' }, '能独立写出并解释思路，再标记为已掌握。')), el('div', { class: 'panel side-panel' }, el('h3', {}, '个人笔记'), el('p', { class: 'note-content' }, p.notes || '暂时没有笔记。编辑题目时，可以记下自己的卡点。'), safeExternalLink(p.source_url, '回到原题'), el('p', { class: 'field-help' }, `更新于 ${dateText(p.updated_at, true)}`)), el('div', { class: 'panel side-panel' }, el('h3', {}, '保存与版本'), el('p', { class: 'field-help no-margin' }, '修改题面与参考答案会保留版本。旧题解会提示是否需要更新。'), button('查看版本记录', 'button-quiet button-sm', async () => { const data = await api(`/problems/${p.id}/versions`); showVersions(data.items || []); })));
    app.replaceChildren(breadcrumb(p.title), heading, el('div', { class: 'detail-grid' }, el('div', {}, mainPanel), aside));
    function showVersions(versions) {
      setTab('versions');
      content.replaceChildren(el('h3', { class: 'no-margin' }, '题目版本'), el('p', { class: 'field-help' }, '版本记录保留当时的题面、代码和测试，便于回看。'), el('div', { class: 'version-list' }, versions.map((v) => el('details', { class: 'version-item' }, el('summary', {}, `版本 ${v.revision} · ${dateText(v.created_at, true)}`), el('pre', {}, JSON.stringify(v.snapshot, null, 2))))));
    }
    function setTab(tab) {
      if (state.editDirty && !window.confirm('题解修改还未保存，确定切换吗？')) return false;
      state.editDirty = false; currentTab = tab;
      [...tabs.children].forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
      return true;
    }
    function drawTab(tab) {
      if (!setTab(tab)) return;
      if (tab === 'statement') content.replaceChildren(markdown(p.statement), el('div', { class: 'mt' }, el('h3', {}, '样例与测试'), el('p', { class: 'field-help' }, '函数模式中的输入按参数顺序排列。'), showTests((p.tests || []).filter((t) => t.sample))));
      if (tab === 'reference') drawReference();
      if (tab === 'explanation') drawExplanation();
      if (tab === 'history') drawHistory();
    }
    function drawReference() {
      const code = p.references?.[language];
      const output = el('div');
      const verify = button('检查参考答案', 'button-secondary button-sm', () => busy(verify, '正在运行…', async () => {
        if (!code) return;
        const a = await api(`/problems/${p.id}/run`, { method: 'POST', body: { language, code, scope: 'all', purpose: 'reference', revision: p.revision } });
        if (ticket !== state.ticket) return;
        attempts.unshift(a); output.replaceChildren(resultView(a));
      }), { disabled: !code });
      content.replaceChildren(el('div', { class: 'explanation-toolbar' }, segmented(language, (lang) => { language = lang; drawReference(); }), verify), code ? el('div', { class: 'panel' }, el('pre', { class: 'code-display' }, code), el('div', { class: 'code-meta' }, LANG[language], '原始参考代码')) : el('div', { class: 'empty-inline' }, `还没有 ${LANG[language]} 参考代码，编辑题目后可添加。`), el('p', { class: 'field-help mt' }, '原始答案完整保留。检查结果仅针对本题已配置的测试。'), output);
    }
    function drawExplanation() {
      const explanation = explanations.find((x) => x.language === language);
      const main = el('div');
      const generate = button(explanation ? '重新生成' : '生成中文题解', 'button-primary button-sm', () => busy(generate, '正在理解你的解法…', async () => {
        if (state.editDirty && !window.confirm('当前题解还有未保存的修改，生成新题解会替换编辑内容，继续吗？')) return;
        const requestedLanguage = language;
        generating = true;
        try {
        const item = await api(`/problems/${p.id}/explanations`, { method: 'POST', body: { language: requestedLanguage, revision: p.revision } });
        explanations = [...explanations.filter((x) => x.language !== requestedLanguage), item];
        if (ticket !== state.ticket) { toast('题解已生成并保存。'); return; }
        state.editDirty = false;
        if (ticket === state.ticket && currentTab === 'explanation') drawExplanation();
        toast('题解已生成并保存。');
        } finally { generating = false; }
      }), { disabled: !p.references?.[language] || !state.health?.ai?.configured });
      const editButton = button(explanation ? '编辑题解' : '自己写题解', 'button-secondary button-sm', () => { if (generating) { toast('题解正在生成，请稍后编辑。'); return; } editExplanation(explanation, main); }, { disabled: !p.references?.[language] });
      content.replaceChildren(el('div', { class: 'explanation-toolbar' }, segmented(language, (lang) => { if (generating) return false; if (state.editDirty && !window.confirm('题解还未保存，确定切换语言吗？')) return false; state.editDirty = false; language = lang; drawExplanation(); }), el('div', { class: 'button-row' }, editButton, generate)), main);
      if (!state.health?.ai?.configured) main.append(notice('AI 题解尚未配置。可以先编写自己的题解；配置模型后，再根据参考代码自动生成。'));
      if (explanation) {
        if (explanation.stale) main.append(notice('题面或参考代码已有修改，这份题解对应较早的版本。建议检查后更新。', 'warning'));
        main.append(markdown(explanation.content), el('p', { class: 'field-help mt' }, `${explanation.origin === 'ai' ? 'AI 生成' : '手动编写'} · ${LANG[language]} · ${dateText(explanation.created_at, true)}`));
      } else main.append(el('div', { class: 'empty-inline' }, el('h3', {}, '把代码，变成自己的理解'), el('p', {}, '题解会围绕你的参考答案，梳理核心思路、关键步骤、复杂度和易错点。')));
    }
    function editExplanation(explanation, mount) {
      const input = el('textarea', { placeholder: '## 核心思路\n\n写下你为什么选择这个方法…', 'aria-label': '题解内容', value: explanation?.content || '' });
      input.addEventListener('input', () => { state.editDirty = true; });
      const save = button('保存题解', 'button-primary', () => busy(save, '保存中…', async () => {
        if (!input.value.trim()) throw new Error('请先填写题解内容。');
        const savedLanguage = language;
        input.disabled = true;
        try {
          const result = await api(`/problems/${p.id}/explanations/${savedLanguage}`, { method: 'PUT', body: { content: input.value, revision: p.revision } });
          explanations = [...explanations.filter((x) => x.language !== savedLanguage), result];
          if (ticket === state.ticket && language === savedLanguage && input.isConnected) {
            state.editDirty = false; drawExplanation();
          }
          toast('题解已保存。');
        } finally { input.disabled = false; }
      }));
      mount.replaceChildren(el('div', { class: 'explanation-form' }, input, el('div', { class: 'button-row' }, save, button('取消', 'button-quiet', () => { if (!state.editDirty || window.confirm('放弃尚未保存的题解修改吗？')) { state.editDirty = false; drawExplanation(); } }))));
      input.focus();
    }
    function drawHistory() {
      content.replaceChildren(el('p', { class: 'field-help' }, '保留每一次尝试，参考答案检查与独立练习分别记录。'), attempts.length ? el('div', { class: 'history-list' }, attempts.map((a) => historyItem(a))) : el('div', { class: 'empty-inline' }, '还没有提交记录，试着独立做一次吧。'));
    }
    for (const [key, label] of [['statement', '题目'], ['reference', '参考代码'], ['explanation', '思路解析'], ['history', '提交记录']]) tabs.append(el('button', { type: 'button', class: 'tab-button', 'data-tab': key, onclick: () => drawTab(key) }, label));
    drawTab('statement');
  }
  function historyItem(a) {
    return el('details', { class: 'history-item' }, el('summary', {}, statusNode(a.status), badge(a.purpose === 'reference' ? '参考检查' : '独立练习'), el('span', { class: 'history-meta' }, `${LANG[a.language] || a.language} · v${a.problem_revision} · ${dateText(a.created_at, true)}`)), el('pre', { class: 'code-display' }, a.code || ''), resultView(a));
  }
  function resultView(a) {
    const neutral = ['runner_unavailable', 'no_tests', 'infrastructure_error'].includes(a.status);
    const result = el('div', { class: 'results-panel panel' }, el('div', { class: `result-header ${a.status === 'accepted' ? 'accepted' : neutral ? 'failed' : 'error'}` }, statusNode(a.status)));
    const body = el('div', { class: 'result-body' }, el('p', { class: 'result-summary' }, a.summary || STATUS[a.status] || '运行完成'));
    if (a.compile_output) body.append(el('pre', { class: 'result-stderr' }, a.compile_output));
    for (const [i, c] of (a.results || []).entries()) {
      const actual = c.actual !== undefined ? c.actual : c.stdout;
      const details = el('details', { class: 'result-case', open: c.status !== 'accepted' }, el('summary', {}, el('span', {}, c.name || `测试 ${i + 1}`), el('span', {}, STATUS[c.status] || c.status, c.time_ms === undefined || c.time_ms === null ? '' : ` · ${Math.round(c.time_ms)} ms`)), el('div', { class: 'test-values' }, el('div', { class: 'test-value' }, el('small', {}, '实际结果'), el('pre', {}, jsonText(actual) ?? '无输出')), el('div', { class: 'test-value' }, el('small', {}, '预期结果'), el('pre', {}, jsonText(c.expected) ?? '—'))));
      if (c.stderr) details.append(el('pre', { class: 'result-stderr' }, c.stderr));
      if (c.stdout && a.status !== 'accepted' && c.stdout !== actual) details.append(el('pre', { class: 'result-stderr' }, `标准输出\n${c.stdout}`));
      body.append(details);
    }
    if (a.status === 'accepted') body.append(el('p', { class: 'field-help mt no-margin' }, '此结果仅代表通过本题已有测试，不等同于原平台的全部测试通过。'));
    result.append(body); return result;
  }

  function editable(p) {
    const keys = ['title', 'source', 'source_url', 'difficulty', 'tags', 'statement', 'mode', 'references', 'templates', 'signature', 'comparison', 'tests', 'notes', 'mastery'];
    return Object.fromEntries(keys.map((k) => [k, p[k]]));
  }
  function renderForm(p) {
    const formTicket = state.ticket;
    let formGeneration = 0, savingForm = false;
    let language = p?.references?.python ? 'python' : p?.references?.cpp ? 'cpp' : 'python';
    const refValues = { python: p?.references?.python || '', cpp: p?.references?.cpp || '' };
    const templateValues = { python: p?.templates?.python || '', cpp: p?.templates?.cpp || '' };
    const title = el('input', { type: 'text', value: p?.title || '', placeholder: '例如：两数之和', required: true, maxlength: '120' });
    const source = select(SOURCE, p?.source || 'leetcode');
    const difficulty = select(DIFFICULTY, p?.difficulty || 'easy');
    const url = el('input', { type: 'url', value: p?.source_url || '', placeholder: 'https://leetcode.cn/problems/…' });
    const tags = el('input', { type: 'text', value: (p?.tags || []).join('，'), placeholder: '哈希表，数组' });
    const statement = el('textarea', { class: 'statement-input', value: p?.statement || '', placeholder: '粘贴题目描述、数据范围与样例。支持 Markdown。', required: true });
    const reference = codeEditing(el('textarea', { class: 'form-code', value: refValues[language], 'aria-label': '参考代码', placeholder: '粘贴你在原平台提交的参考答案…' }));
    const template = codeEditing(el('textarea', { class: 'form-code', value: templateValues[language], 'aria-label': '初始代码模板', placeholder: '可选：重做时只显示函数签名和待填写的函数体。', 'data-template': 'true' }));
    const mode = select({ function: '函数模式（Solution / 指定函数）', stdin: '标准输入输出（完整程序）' }, p?.mode || 'function');
    const functionName = el('input', { type: 'text', value: p?.signature?.name || '', placeholder: 'twoSum' });
    const className = el('input', { type: 'text', value: p?.signature?.class_name ?? 'Solution', placeholder: '独立函数请留空' });
    const params = el('textarea', { value: (p?.signature?.parameters || []).map((param) => `${param.name}: ${param.type}`).join('\n'), placeholder: 'nums: int[]\ntarget: int', class: 'parameter-input' });
    const returnType = select(Object.fromEntries([...TYPES, 'void'].map((t) => [t, t])), p?.signature?.returns || 'int');
    const capture = el('input', { type: 'number', min: '0', value: p?.signature?.capture_argument ?? 0 });
    const comparison = select({ exact: '精确比较', unordered: '最外层数组无序比较', tokens: '忽略空白的文本比较', float: '浮点数近似比较' }, p?.comparison || 'exact');
    const notes = el('textarea', { value: p?.notes || '', placeholder: '这道题卡在哪里？下次重做时需要记住什么？', class: 'notes-input' });
    const mastery = select(MASTERY, p?.mastery || 'new');
    const form = el('form', { class: 'panel' });
    const errorMount = el('div');
    let testRows = [];
    let testMode = mode.value;
    const modeTests = { function: [], stdin: [] };
    const modeComparison = { function: 'exact', stdin: 'tokens', [mode.value]: comparison.value };
    const testMount = el('div');
    const functionFields = el('div', {}, el('div', { class: 'field-row' }, field('函数名称', functionName), field('类名', className, '独立函数可留空；通常为 Solution。')), field('参数与类型', params, '每行一个参数，例如 nums: int[]。支持 int / int64 / float / bool / str / char、数组，以及 ListNode / TreeNode。'), el('div', { class: 'field-row' }, field('返回类型', returnType), field('原地修改时检查第几个参数', capture, '仅 void 返回类型使用，从 0 开始。')));
    const testHelp = el('p', { class: 'field-help' });
    const modeNotice = el('div');
    function updateMode() {
      if (testMode !== mode.value) {
        modeTests[testMode] = testRows.map((r) => ({ name: r.name.value, input: r.input.value, expected: r.expected.value, sample: r.sample.checked }));
        modeComparison[testMode] = comparison.value;
        testMode = mode.value;
        testRows = []; testMount.replaceChildren();
        for (const test of modeTests[testMode]) addTest(test, true);
        comparison.value = modeComparison[testMode];
        modeNotice.replaceChildren(notice('两种执行模式的测试分开保留在当前编辑页。切回原模式可继续编辑原来的测试，保存时仅保存当前模式。'));
      }
      functionFields.hidden = mode.value !== 'function';
      testHelp.textContent = mode.value === 'function' ? '输入填写按参数顺序排列的 JSON 数组，例如 [[2,7,11,15],9]；预期结果也使用 JSON，例如 [0,1]。' : '输入与预期输出按原题格式直接填写，保留需要的换行。';
    }
    mode.addEventListener('change', updateMode);
    function addTest(test = { name: `测试 ${testRows.length + 1}`, input: mode.value === 'function' ? [] : '', expected: mode.value === 'function' ? null : '', sample: true }, raw = false) {
      const name = el('input', { type: 'text', value: test.name || `测试 ${testRows.length + 1}`, 'aria-label': '测试名称' });
      const sample = el('input', { type: 'checkbox', checked: !!test.sample, 'aria-label': '属于题目样例' });
      const input = el('textarea', { value: raw ? test.input : mode.value === 'function' ? JSON.stringify(test.input, null, 2) : String(test.input ?? ''), 'aria-label': '测试输入', spellcheck: 'false' });
      const expected = el('textarea', { value: raw ? test.expected : mode.value === 'function' ? JSON.stringify(test.expected, null, 2) : String(test.expected ?? ''), 'aria-label': '预期结果', spellcheck: 'false' });
      const row = { name, sample, input, expected };
      row.node = el('div', { class: 'test-editor' }, el('div', { class: 'test-editor-head' }, name, el('label', { class: 'checkbox-label' }, sample, '题目样例'), el('button', { type: 'button', class: 'icon-button danger', 'aria-label': '移除此测试', onclick: () => { testRows = testRows.filter((r) => r !== row); row.node.remove(); state.editDirty = true; formGeneration++; } }, '×')), el('div', { class: 'field-row' }, field('输入', input), field('预期结果', expected)));
      testRows.push(row); testMount.append(row.node);
    }
    const inferResult = el('div');
    const infer = button('识别函数与模板', 'button-secondary button-sm', () => busy(infer, '识别中…', async () => {
      if (!reference.value.trim()) throw new Error('请先粘贴当前语言的参考代码。');
      const requestedLanguage = language, requestedCode = reference.value, generation = formGeneration;
      const data = await api('/infer', { method: 'POST', body: { language: requestedLanguage, code: requestedCode } });
      if (formTicket !== state.ticket) return;
      if (requestedLanguage !== language || requestedCode !== reference.value || generation !== formGeneration) {
        inferResult.replaceChildren(notice('识别期间代码、语言或设置已有修改，本次识别结果未应用。请按需要重新识别。', 'warning'));
        return;
      }
      mode.value = data.mode || mode.value;
      if (data.signature) {
        functionName.value = data.signature.name || '';
        className.value = data.signature.class_name ?? '';
        params.value = (data.signature.parameters || []).map((param) => `${param.name}: ${param.type}`).join('\n');
        returnType.value = data.signature.returns || 'int';
        capture.value = data.signature.capture_argument ?? 0;
      }
      const keptTemplate = !!template.value.trim();
      if (data.template && !keptTemplate) { templateValues[requestedLanguage] = data.template; template.value = data.template; }
      updateMode(); state.editDirty = true;
      const messages = [...(data.warnings || [])];
      if (keptTemplate) messages.push('已保留现有初始代码模板，请核对它是否与当前函数签名一致。');
      inferResult.replaceChildren(notice(messages.length ? messages.join('\n') : '已识别代码结构。请核对下方运行方式、参数类型，并补充测试用例。', (data.warnings || []).length ? 'warning' : ''));
      runtimeDetails.open = true;
    }));
    const langSwitch = segmented(language, (next) => {
      formGeneration++;
      refValues[language] = reference.value; templateValues[language] = template.value;
      language = next; reference.value = refValues[next]; template.value = templateValues[next];
    });
    const runtimeDetails = el('details', { class: 'form-details', open: !!p }, el('summary', {}, '运行方式与测试用例'), el('div', { class: 'form-details-body' }, field('题目执行模式', mode), functionFields, field('结果比较规则', comparison, '例如“两数之和”允许返回下标顺序不同，可选择最外层数组无序比较。'), el('h3', {}, '测试用例'), testHelp, modeNotice, testMount, button('＋ 添加测试', 'button-quiet button-sm mt', () => { addTest(); state.editDirty = true; formGeneration++; })));
    const templateDetails = el('details', { class: 'form-details' }, el('summary', {}, '重做时的初始代码（可选）'), el('div', { class: 'form-details-body' }, el('p', { class: 'field-help' }, '当前语言的空白模板。识别代码时会尝试提取；重做时不会自动填入参考答案。'), template));
    function section(number, name, children) { return el('section', { class: 'form-section' }, el('div', { class: 'form-section-heading' }, el('span', { class: 'step-number' }, number), el('h2', {}, name)), children); }
    form.append(section('01', '题目内容', [field('题目名称', title, null, true), el('div', { class: 'field-row' }, field('题目来源', source), field('难度', difficulty)), field('原题链接', url), field('算法标签', tags, '用逗号分隔，方便以后按题型查找。'), field('题目描述', statement, null, true)]), section('02', '你的参考答案', [el('div', { class: 'explanation-toolbar' }, langSwitch, infer), el('p', { class: 'field-help' }, '至少填写一种语言的参考代码。保存原始写法，解析会围绕这份答案生成。'), reference, el('div', { class: 'mt' }, inferResult), runtimeDetails, templateDetails]), section('03', '留给下次的笔记', [field('个人笔记', notes), field('掌握状态', mastery)]), errorMount);
    const save = el('button', { type: 'submit', class: 'button button-primary' }, p ? '保存修改' : '保存题目');
    const saveAside = button(p ? '保存修改' : '保存题目', 'button-primary', () => form.requestSubmit());
    form.append(el('div', { class: 'form-actions' }, button('取消', 'button-quiet', () => navigate(p ? `problem/${p.id}` : 'library')), save));
    form.addEventListener('input', () => { state.editDirty = true; formGeneration++; }); form.addEventListener('change', () => { state.editDirty = true; formGeneration++; });
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (savingForm) return;
      savingForm = true;
      attempt(() => busy(save, '保存中…', async () => {
      const controls = [...form.querySelectorAll('input,textarea,select,button')].map((node) => [node, node.disabled]);
      controls.forEach(([node]) => { node.disabled = true; });
      saveAside.disabled = true;
      try {
        errorMount.replaceChildren();
        refValues[language] = reference.value; templateValues[language] = template.value;
        const references = Object.fromEntries(Object.entries(refValues).filter(([, code]) => code.trim()));
        if (!Object.keys(references).length) throw new Error('请至少填写一份 C++ 或 Python 参考答案。');
        let signature = null;
        if (mode.value === 'function') {
          if (!functionName.value.trim()) throw new Error('请点击“识别函数与模板”，或在运行方式中填写函数名称。');
          const parameters = params.value.split('\n').filter((line) => line.trim()).map((line) => {
            const match = line.match(/^\s*([A-Za-z_]\w*)\s*:\s*(\S+)\s*$/);
            if (!match || !TYPES.includes(match[2])) throw new Error(`参数格式不正确：${line}。例如 nums: int[]。`);
            return { name: match[1], type: match[2] };
          });
          signature = { name: functionName.value.trim(), class_name: className.value.trim(), parameters, returns: returnType.value, capture_argument: Number(capture.value || 0) };
        }
        const tests = testRows.map((r, i) => {
          let input = r.input.value, expected = r.expected.value;
          if (mode.value === 'function') {
            try { input = JSON.parse(input); } catch (_) { throw new Error(`测试 ${i + 1} 的输入不是有效 JSON。`); }
            if (!Array.isArray(input)) throw new Error(`测试 ${i + 1} 的输入应是参数数组，例如 [[2,7],9]。`);
            try { expected = JSON.parse(expected); } catch (_) { throw new Error(`测试 ${i + 1} 的预期结果不是有效 JSON。`); }
          }
          return { name: r.name.value.trim() || `测试 ${i + 1}`, input, expected, sample: r.sample.checked };
        });
        const payload = { title: title.value.trim(), source: source.value, source_url: url.value.trim(), difficulty: difficulty.value, tags: [...new Set(tags.value.split(/[,，]/).map((t) => t.trim()).filter(Boolean))], statement: statement.value, mode: mode.value, references, templates: Object.fromEntries(Object.entries(templateValues).filter(([, code]) => code.trim())), signature, comparison: comparison.value, tests, notes: notes.value, mastery: mastery.value };
        if (p) payload.revision = p.revision;
        const saved = await api(p ? `/problems/${p.id}` : '/problems', { method: p ? 'PUT' : 'POST', body: payload });
        if (formTicket !== state.ticket) { toast('题目已保存。'); return; }
        state.editDirty = false; toast(p ? '修改已保存，历史版本也已保留。' : '题目已保存。可以查看解析或开始重做。');
        await navigate(`problem/${saved.id}`);
      } catch (err) { const error = notice(err.message, 'error'); error.classList.add('form-error'); errorMount.replaceChildren(error); runtimeDetails.open = true; error.scrollIntoView({ block: 'center', behavior: 'smooth' }); throw err; }
      finally {
        controls.forEach(([node, wasDisabled]) => { node.disabled = wasDisabled; });
        saveAside.disabled = false; savingForm = false;
      }
    })); });
    for (const test of p?.tests || []) addTest(test);
    updateMode();
    app.replaceChildren(breadcrumb(p ? '编辑题目' : '录入题目'), el('div', { class: 'page-heading' }, el('div', {}, el('p', { class: 'eyebrow' }, p ? 'KEEP YOUR THINKING' : 'ONE PROBLEM AT A TIME'), el('h1', {}, p ? '完善这道题的手记' : '留下一道值得再做的题'), el('p', { class: 'hero-copy' }, '保存题目与自己的解法，给下次练习做好准备。'))), el('div', { class: 'form-layout' }, el('div', { class: 'form-main' }, form), el('aside', { class: 'form-aside' }, el('div', { class: 'panel' }, el('h3', {}, '简单录入，完整保留'), el('p', {}, '题目与参考代码是这份手记的起点。测试与模板可以现在补充，也可以以后完善。'), saveAside, el('div', { class: 'aside-tip' }, '建议录入顺序', el('ol', { class: 'help-list' }, el('li', {}, '粘贴题目与数据范围'), el('li', {}, '粘贴自己的参考代码'), el('li', {}, '识别函数，填写样例'), el('li', {}, '保存后生成思路解析')))))));
    state.editDirty = false;
  }

  function fallbackTemplate(language, p) {
    if (p.templates?.[language]) return p.templates[language];
    if (p.mode === 'stdin') return language === 'python' ? 'import sys\n\n\ndef main():\n    # 从标准输入读取数据，完成你的解法\n    pass\n\n\nif __name__ == "__main__":\n    main()\n' : '#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    ios::sync_with_stdio(false);\n    cin.tie(nullptr);\n    // 读取输入，完成你的解法\n    return 0;\n}\n';
    const s = p.signature;
    if (!s) return '';
    if (language === 'python') {
      const args = (s.parameters || []).map((x) => x.name).join(', ');
      return s.class_name ? `class ${s.class_name}:\n    def ${s.name}(self${args ? ', ' + args : ''}):\n        # 在这里完成你的解法\n        pass\n` : `def ${s.name}(${args}):\n    # 在这里完成你的解法\n    pass\n`;
    }
    const cppType = (type) => {
      if (type.endsWith('[]')) return `vector<${cppType(type.slice(0, -2))}>`;
      return { int: 'int', int64: 'long long', float: 'double', bool: 'bool', str: 'string', char: 'char', ListNode: 'ListNode*', TreeNode: 'TreeNode*', void: 'void' }[type] || 'int';
    };
    const args = (s.parameters || []).map((x) => `${cppType(x.type)} ${x.name}`).join(', ');
    const fun = `${cppType(s.returns)} ${s.name}(${args}) {\n    // 在这里完成你的解法\n}`;
    return `#include <bits/stdc++.h>\nusing namespace std;\n\n${s.class_name ? `class ${s.class_name} {\npublic:\n    ${fun.split('\n').join('\n    ')}\n};` : fun}\n`;
  }
  function draftCachePrefix(ctx) { return `algonote-draft:${ctx.problem.id}:${ctx.language}`; }
  function draftCacheKey(ctx) { return `${draftCachePrefix(ctx)}:${draftScope}`; }
  function cacheDraft(ctx) {
    try {
      const key = draftCacheKey(ctx);
      localStorage.setItem(key, JSON.stringify({ code: ctx.code, revision: ctx.problem.revision, base_updated_at: ctx.serverUpdatedAt ?? null, savedAt: Date.now() }));
      sessionStorage.setItem(`${draftCachePrefix(ctx)}:last`, key);
      ctx.cached = true;
    } catch (_) { ctx.cached = false; }
    return ctx.cached;
  }
  function clearDraftCache(ctx) {
    try {
      const key = draftCacheKey(ctx);
      const saved = JSON.parse(localStorage.getItem(key) || 'null');
      if (saved?.code === ctx.code) localStorage.removeItem(key);
      if (sessionStorage.getItem(`${draftCachePrefix(ctx)}:last`) === key) sessionStorage.removeItem(`${draftCachePrefix(ctx)}:last`);
    } catch (_) {}
  }
  function draftConflictError() {
    const error = new Error('另一处已更新此草稿。你的代码仍在编辑区，请选择载入服务器草稿，或确认保存当前代码。');
    error.status = 409; return error;
  }
  async function flushDraft(ctx) {
    clearTimeout(ctx.timer);
    if (ctx.conflict) throw draftConflictError();
    if (ctx.saving) { await ctx.saving; if (ctx.dirty) return flushDraft(ctx); return; }
    if (!ctx.dirty) return;
    const operation = (async () => {
      // A navigation or language switch must wait for edits made during an earlier request too.
      while (ctx.dirty) {
        const code = ctx.code, generation = ctx.generation;
        ctx.status.textContent = '保存中…'; ctx.status.className = 'draft-status pending';
        try {
          const saved = await api(`/problems/${ctx.problem.id}/drafts/${ctx.language}`, {
            method: 'PUT', body: { code, problem_revision: ctx.problem.revision, expected_updated_at: ctx.serverUpdatedAt ?? null }
          });
          ctx.serverUpdatedAt = saved.updated_at;
          if (generation === ctx.generation) {
            ctx.dirty = false; ctx.conflict = false;
            ctx.status.textContent = '草稿已保存'; ctx.status.className = 'draft-status';
            clearDraftCache(ctx);
          } else cacheDraft(ctx);
        } catch (err) {
          cacheDraft(ctx);
          if (err.status === 409) {
            ctx.conflict = true;
            ctx.status.textContent = '草稿有冲突 · 请先处理';
            ctx.onConflict?.();
          } else ctx.status.textContent = ctx.cached ? '保存失败 · 已保留本机草稿' : '保存失败 · 请勿关闭此页';
          ctx.status.className = 'draft-status error';
          throw err;
        }
      }
    })();
    ctx.saving = operation;
    try { await operation; } finally { if (ctx.saving === operation) ctx.saving = null; }
  }
  async function loadPracticeDraft(ctx) {
    const draft = await api(`/problems/${ctx.problem.id}/drafts/${ctx.language}`);
    let local = null;
    try {
      const previous = sessionStorage.getItem(`${draftCachePrefix(ctx)}:last`);
      local = JSON.parse(localStorage.getItem(draftCacheKey(ctx)) || (previous ? localStorage.getItem(previous) : null) || localStorage.getItem(draftCachePrefix(ctx)) || 'null');
    } catch (_) {}
    const isExisting = !!draft.updated_at;
    ctx.serverUpdatedAt = draft.updated_at ?? null;
    ctx.code = isExisting ? draft.code : fallbackTemplate(ctx.language, ctx.problem);
    ctx.dirty = false; ctx.conflict = false;
    if (local && typeof local.code === 'string' && local.code !== draft.code) {
      ctx.code = local.code; ctx.dirty = true; ctx.generation++;
      // An unsaved copy is only eligible for autosave when its server base still matches.
      // Client wall-clock timestamps are deliberately not used for conflict decisions.
      const hasBase = Object.prototype.hasOwnProperty.call(local, 'base_updated_at');
      ctx.conflict = hasBase ? local.base_updated_at !== ctx.serverUpdatedAt : isExisting;
      if (ctx.conflict) {
        ctx.serverUpdatedAt = hasBase ? local.base_updated_at : null;
        ctx.status.textContent = '已恢复本机草稿 · 需要处理冲突'; ctx.status.className = 'draft-status error';
      } else { ctx.status.textContent = '已恢复本机草稿'; ctx.status.className = 'draft-status pending'; }
      cacheDraft(ctx);
    } else {
      if (local?.code === draft.code) {
        try { sessionStorage.removeItem(`${draftCachePrefix(ctx)}:last`); localStorage.removeItem(draftCachePrefix(ctx)); } catch (_) {}
      }
      ctx.status.textContent = isExisting ? '已恢复上次草稿' : '新练习，慢慢来'; ctx.status.className = 'draft-status';
    }
    return { draft, local };
  }
  async function renderPractice(p, ticket) {
    let language = p.references?.python ? 'python' : 'cpp';
    const status = el('span', { class: 'draft-status' }, '正在读取草稿…');
    const ctx = { problem: p, language, code: '', dirty: false, saving: null, timer: null, status, generation: 0 };
    state.practice = ctx;
    await loadPracticeDraft(ctx);
    if (ctx.dirty && !ctx.conflict) ctx.timer = setTimeout(() => attempt(() => flushDraft(ctx)), 700);
    if (ticket !== state.ticket) return;
    const editor = codeEditing(el('textarea', { class: 'practice-code', value: ctx.code, 'aria-label': '练习代码' }));
    const lineCount = el('span');
    const codeHint = el('span', {}, 'Tab 缩进 · Ctrl / ⌘ + Enter 运行样例');
    const resultMount = el('div');
    const revealMount = el('div');
    const warningMount = el('div');
    const conflictMount = el('div'); warningMount.append(conflictMount);
    const lineUpdate = () => { lineCount.textContent = `${editor.value.split('\n').length} lines · UTF-8`; };
    editor.addEventListener('input', () => {
      ctx.code = editor.value; ctx.dirty = true; ctx.generation++;
      status.textContent = ctx.conflict ? '本机代码已保留 · 请处理冲突' : '正在记录…';
      status.className = ctx.conflict ? 'draft-status error' : 'draft-status pending';
      cacheDraft(ctx); lineUpdate(); clearTimeout(ctx.timer);
      if (!ctx.conflict) ctx.timer = setTimeout(() => attempt(() => flushDraft(ctx)), 850);
    });
    lineUpdate();
    let executing = false, languageChanging = false;
    const switcher = segmented(language, async (next) => {
      if (languageChanging || executing) return false;
      languageChanging = true; editor.disabled = true;
      try {
        await flushDraft(ctx);
        const newCtx = { ...ctx, language: next, code: '', dirty: false, saving: null, timer: null, generation: 0 };
        await loadPracticeDraft(newCtx);
        if (ticket !== state.ticket) return false;
        language = next; Object.assign(ctx, newCtx);
        if (ctx.dirty && !ctx.conflict) ctx.timer = setTimeout(() => attempt(() => flushDraft(ctx)), 700);
        editor.value = ctx.code; lineUpdate();
        if (ctx.conflict) drawConflict(); else conflictMount.replaceChildren();
        resultMount.replaceChildren(); revealMount.replaceChildren(); reveal.removeAttribute('open');
        toast(`已切换到 ${LANG[next]}，两种语言的草稿分别保存。`);
      } finally { languageChanging = false; editor.disabled = false; }
    });
    const run = button('▷ 运行样例', 'button-secondary', () => execute('samples'));
    const submit = button('提交测试 →', 'button-primary', () => execute('all'));
    async function execute(scope) {
      if (executing || languageChanging) return;
      if (!editor.value.trim()) throw new Error('先写下你的代码，再运行试试。');
      executing = true; run.disabled = true; submit.disabled = true;
      const active = scope === 'samples' ? run : submit, oldText = active.textContent; active.textContent = '运行中…';
      try {
        await flushDraft(ctx);
        const a = await api(`/problems/${p.id}/run`, { method: 'POST', body: { language: ctx.language, code: editor.value, scope, purpose: 'practice', revision: p.revision } });
        if (ticket !== state.ticket) return;
        resultMount.replaceChildren(resultView(a));
        if (window.innerWidth < 760) resultMount.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } finally { executing = false; run.disabled = false; submit.disabled = false; active.textContent = oldText; }
    }
    editor.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); attempt(() => execute('samples')); } });
    const clear = el('button', { type: 'button', class: 'icon-button', 'aria-label': '重置为初始模板', title: '重置为初始模板', onclick: () => {
      if (languageChanging || executing) return;
      if (!window.confirm('将当前练习代码重置为初始模板？之前的提交记录会保留。')) return;
      editor.value = fallbackTemplate(ctx.language, p); editor.dispatchEvent(new Event('input', { bubbles: true })); editor.focus();
    } }, '↺');
    const reveal = el('details', { class: 'answer-reveal' }, el('summary', {}, '想过之后，再查看参考答案与解析'), revealMount);
    reveal.addEventListener('toggle', () => {
      if (!reveal.open || revealMount.childNodes.length) return;
      const code = p.references?.[ctx.language];
      revealMount.append(code ? el('pre', { class: 'code-display' }, code) : el('p', { class: 'field-help' }, `尚未保存 ${LANG[ctx.language]} 参考答案。`));
      const currentLanguage = ctx.language;
      attempt(async () => {
        const data = await api(`/problems/${p.id}/explanations`);
        if (ticket !== state.ticket || currentLanguage !== ctx.language) return;
        const explanation = (data.items || []).find((x) => x.language === currentLanguage);
        if (explanation?.stale) revealMount.append(notice('这份题解对应较早版本，请结合最新代码核对。', 'warning'));
        if (explanation) revealMount.append(markdown(explanation.content));
      });
    });
    function drawConflict() {
      const preview = el('details', { class: 'mt' }, el('summary', {}, '查看服务器上的草稿'));
      const previewBody = el('pre', { class: 'code-display' }); preview.append(previewBody);
      preview.addEventListener('toggle', () => {
        if (!preview.open) return;
        attempt(async () => {
          const latest = await api(`/problems/${p.id}/drafts/${ctx.language}`);
          if (ticket === state.ticket && ctx.conflict) previewBody.textContent = latest.code || '服务器上还没有草稿。';
        });
      });
      const loadServer = button('载入服务器草稿', 'button-secondary button-sm', () => busy(loadServer, '读取中…', async () => {
        const latest = await api(`/problems/${p.id}/drafts/${ctx.language}`);
        if (ticket !== state.ticket || !window.confirm('将编辑区切换为服务器草稿。需要保留当前代码时，请先下载副本。继续吗？')) return;
        clearDraftCache(ctx);
        ctx.serverUpdatedAt = latest.updated_at ?? null;
        ctx.code = latest.updated_at ? latest.code : fallbackTemplate(ctx.language, p);
        ctx.dirty = false; ctx.conflict = false; ctx.generation++;
        editor.value = ctx.code; lineUpdate();
        status.textContent = '已载入服务器草稿'; status.className = 'draft-status';
        conflictMount.replaceChildren();
      }));
      const keepLocal = button('确认保存当前代码', 'button-secondary button-sm', () => busy(keepLocal, '保存中…', async () => {
        const latest = await api(`/problems/${p.id}/drafts/${ctx.language}`);
        if (ticket !== state.ticket || !window.confirm('将用当前编辑区的代码替换服务器草稿。确定保留当前代码吗？')) return;
        ctx.serverUpdatedAt = latest.updated_at ?? null; ctx.conflict = false;
        cacheDraft(ctx);
        await flushDraft(ctx);
        if (ticket === state.ticket) conflictMount.replaceChildren();
      }));
      const copy = button('下载我的代码', 'button-quiet button-sm', () => {
        const objectUrl = URL.createObjectURL(new Blob([editor.value], { type: 'text/plain;charset=utf-8' }));
        const link = el('a', { href: objectUrl, download: `algonote-draft.${ctx.language === 'cpp' ? 'cpp' : 'py'}` });
        document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
      });
      conflictMount.replaceChildren(el('div', { class: 'notice warning', role: 'alert' },
        el('p', {}, '另一处更新了这份草稿。当前代码仍保留在编辑区，自动保存已暂停。先比较内容，再决定保留哪一份。'),
        preview, el('div', { class: 'button-row mt' }, loadServer, keepLocal, copy)));
    }
    ctx.onConflict = drawConflict;
    if (ctx.conflict) drawConflict();
    if (!state.health?.runner?.available) warningMount.append(notice('代码执行服务还未就绪。你可以先练习并保存草稿；启动执行服务后即可运行测试。', 'warning'));
    const statementPanel = el('section', { class: 'panel practice-statement' }, el('div', { class: 'panel-header' }, el('h2', {}, '题目'), el('div', { class: 'button-row' }, sourceLabel(p), badge(DIFFICULTY[p.difficulty], p.difficulty))), el('div', { class: 'panel-body' }, markdown(p.statement), el('div', { class: 'mt' }, showTests((p.tests || []).filter((t) => t.sample))), reveal));
    const editorPanel = el('section', { class: 'panel' }, el('div', { class: 'editor-toolbar' }, switcher, el('div', { class: 'editor-toolbar-right' }, status, clear)), el('div', { class: 'editor-wrap' }, editor), el('div', { class: 'editor-footer' }, lineCount, codeHint), el('div', { class: 'run-toolbar' }, el('span', { class: 'small muted' }, p.mode === 'function' ? '函数模式' : '标准输入输出'), el('div', { class: 'button-row' }, run, submit)));
    app.classList.add('practice-width');
    app.replaceChildren(el('div', { class: 'practice-head' }, el('div', { class: 'practice-title' }, el('button', { type: 'button', class: 'icon-button', 'aria-label': '返回题目', onclick: () => attempt(() => navigate(`problem/${p.id}`)) }, '←'), el('h1', {}, p.title)), el('span', { class: 'small muted' }, '先自己想一想，再与上次的解法相遇。'), button('查看提交记录', 'button-quiet button-sm', async () => { const data = await api(`/problems/${p.id}/attempts`); if (ticket !== state.ticket) return; resultMount.replaceChildren(el('section', { class: 'panel' }, el('div', { class: 'panel-header' }, el('h2', {}, '提交记录')), el('div', { class: 'panel-body' }, (data.items || []).length ? el('div', { class: 'history-list' }, data.items.map((a) => historyItem(a))) : el('p', { class: 'muted small' }, '还没有提交记录。')))); })), el('div', { class: 'practice-layout' }, statementPanel, el('div', { class: 'practice-editor' }, warningMount, editorPanel, el('p', { class: 'practice-help' }, '草稿按题目和语言自动保存。测试结果以当前题库中的用例为准。'), resultMount)));
  }

  $('brand-link').addEventListener('click', (e) => { e.preventDefault(); attempt(() => navigate('library')); });
  $('nav-library').addEventListener('click', () => attempt(() => navigate('library')));
  $('nav-new').addEventListener('click', () => attempt(() => navigate('new')));
  $('settings-toggle').addEventListener('click', () => { showSettings($('settings-panel').hidden); if (!$('settings-panel').hidden) attempt(refreshHealth); });
  $('settings-close').addEventListener('click', () => showSettings(false));
  $('access-token').value = token;
  $('token-form').addEventListener('submit', (event) => { event.preventDefault(); attempt(async () => { token = $('access-token').value.trim(); sessionStorage.setItem('algonote-token', token); await api('/problems'); toast('连接成功。'); showSettings(false); await navigate(state.route || 'library', { replace: true }); }); });
  $('export-button').addEventListener('click', () => attempt(() => busy($('export-button'), '打包中…', async () => {
    if (state.practice) await flushDraft(state.practice);
    const blob = await api('/export', { blob: true });
    const url = URL.createObjectURL(blob), link = el('a', { href: url, download: `algonote-backup-${new Date().toISOString().slice(0, 10)}.zip` });
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000); toast('备份已开始下载。');
  })));
  $('import-button').addEventListener('click', () => $('import-file').click());
  $('import-file').addEventListener('change', (event) => attempt(async () => {
    const file = event.target.files?.[0]; if (!file) return;
    try {
      if (file.size > 16 * 1024 * 1024) throw new Error('文件大于 16 MB，请拆分题目后导入。');
      let data; try { data = JSON.parse(await file.text()); } catch (_) { throw new Error('请选择有效的 JSON 备份文件。ZIP 请先解压并选择 backup.json。'); }
      if (!Array.isArray(data.problems)) throw new Error('备份文件中没有 problems 题目列表。');
      if (!window.confirm(`将导入 ${data.problems.length} 道题目及文件中的关联记录。继续吗？`)) return;
      const result = await busy($('import-button'), '导入中…', () => api('/import', { method: 'POST', body: data }));
      const count = result.imported ?? result.problems ?? result.created ?? data.problems.length;
      toast(`导入完成：${typeof count === 'number' ? count : data.problems.length} 道题目。`);
      await navigate('library');
    } finally { $('import-file').value = ''; }
  }));
  window.addEventListener('beforeunload', (event) => {
    if (state.practice?.dirty) cacheDraft(state.practice);
    if (state.editDirty || state.practice?.dirty || state.practice?.saving) { event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('pagehide', () => { if (state.practice?.dirty) cacheDraft(state.practice); });
  window.addEventListener('popstate', () => attempt(() => navigate(location.hash.slice(1) || 'library', { fromHistory: true })));
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') showSettings(false); });
  refreshHealth().then(() => navigate(location.hash.slice(1) || 'library', { replace: true }));
})();
