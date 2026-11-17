/* AlgoNote pasted-problem importer.
 * Parses user-provided copied text only; it does not fetch platform pages.
 * Output is plain Markdown and is rendered by AlgoNote's safe text-based renderer.
 */
(() => {
  'use strict';

  const NOISE = new Set([
    'premium lock icon', '相关企业', 'companies', 'company tags',
    '收藏', '分享', '提交记录', '运行结果', '题解', '讨论', '笔记',
    'description', 'editorial', 'solutions', 'submissions', 'discuss'
  ]);
  const DIFFICULTY = new Map([
    ['简单', 'easy'], ['easy', 'easy'],
    ['中等', 'medium'], ['medium', 'medium'],
    ['困难', 'hard'], ['hard', 'hard']
  ]);
  const SECTION_HEADINGS = [
    [/^(?:示例|example)\s*(\d+)\s*[:：]?$/i, (_, n) => `### 示例 ${n}`],
    [/^(?:提示|约束|constraints?)\s*[:：]?$/i, () => '### 提示'],
    [/^(?:进阶|follow[- ]?up)\s*[:：]?$/i, () => '### 进阶'],
    [/^(?:输入|input)\s*[:：]?$/i, () => '**输入：**'],
    [/^(?:输出|output)\s*[:：]?$/i, () => '**输出：**'],
    [/^(?:解释|explanation)\s*[:：]?$/i, () => '**解释：**']
  ];

  function cleanLines(raw) {
    return String(raw || '')
      .replace(/\r\n?/g, '\n')
      .replace(/[\u00a0\u2007\u202f]/g, ' ')
      .replace(/[\t ]+$/gm, '')
      .split('\n')
      .map(line => line.trim());
  }

  function parse(raw, source = 'leetcode') {
    const original = String(raw || '');
    const lines = cleanLines(original);
    const nonempty = lines.filter(Boolean);
    if (!nonempty.length) return { title: '', difficulty: null, tags: [], statement: '', original, warnings: ['没有检测到可导入的文本。'] };

    let title = '';
    let difficulty = null;
    const tags = [];
    let inTags = false;
    let inCompanies = false;
    const body = [];

    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      if (!line) { if (body.length && body[body.length - 1] !== '') body.push(''); inTags = false; continue; }
      const lower = line.toLowerCase();

      if (!title) {
        const titleMatch = line.match(/^(?:题目\s*)?(?:\d+\s*[.、．]\s*)?(.{2,100})$/);
        if (titleMatch && !DIFFICULTY.has(lower) && !/^(?:题目描述|description|相关标签|相关企业|提示|示例|example|给定|请你|输入描述|输出描述|输入|输出|constraints?)(?:\s|$)/i.test(line)) {
          title = titleMatch[1].replace(/^题目\s*/, '').trim();
          continue;
        }
      }

      if (DIFFICULTY.has(lower)) { difficulty = DIFFICULTY.get(lower); continue; }
      if (/^(?:相关标签|相关话题|topics?|tags?)\s*[:：]?$/i.test(line)) { inTags = true; inCompanies = false; continue; }
      if (/^(?:相关企业|companies)\s*[:：]?$/i.test(line)) { inTags = false; inCompanies = true; continue; }
      if (inCompanies) {
        if (/^(?:提示|给定|你需要|请你|示例|example|输入|input|constraints?)\b/i.test(line)) inCompanies = false;
        else continue;
      }
      if (inTags) {
        if (/^(?:premium lock icon|相关企业|提示|给定|你需要|请你|示例|example)\b/i.test(line)) inTags = false;
        else {
          const candidates = line.split(/[，,、|｜\s]+/).map(x => x.trim()).filter(Boolean);
          for (const tag of candidates) if (tag.length <= 24 && !NOISE.has(tag.toLowerCase()) && !tags.includes(tag)) tags.push(tag);
          continue;
        }
      }
      if (NOISE.has(lower)) continue;
      if (/^(?:premium\s+lock\s+icon|lock\s+icon)$/i.test(line)) continue;
      if (/^(?:related companies|相关企业)\b/i.test(line)) { inCompanies = true; continue; }

      let converted = line;
      for (const [pattern, render] of SECTION_HEADINGS) {
        const match = line.match(pattern);
        if (match) { converted = render(...match); break; }
      }
      if (/^(?:示例|example)\s*\d+\s*[:：]/i.test(line)) {
        converted = line.replace(/^(?:示例|example)\s*(\d+)\s*[:：]?/i, (_, n) => `### 示例 ${n}\n`);
      } else if (/^(?:输入|input)\s*[:：]/i.test(line)) {
        converted = line.replace(/^(?:输入|input)\s*[:：]\s*/i, '**输入：** ');
      } else if (/^(?:输出|output)\s*[:：]/i.test(line)) {
        converted = line.replace(/^(?:输出|output)\s*[:：]\s*/i, '**输出：** ');
      }
      body.push(converted);
    }

    while (body.length && !body[0]) body.shift();
    while (body.length && !body[body.length - 1]) body.pop();
    const normalized = body.join('\n').replace(/\n{3,}/g, '\n\n').trim();
    const warnings = [];
    if (!title) warnings.push('未能可靠识别题目标题，请手动填写。');
    if (!normalized) warnings.push('未能识别正文，请检查原文并手动整理。');
    if (source === 'nowcoder' && !/示例|输入|输出|样例/i.test(normalized)) warnings.push('未检测到常见样例结构，牛客题面可能需要手动检查。');
    return { title, difficulty, tags, statement: normalized, original, warnings };
  }

  window.AlgoNoteImporter = Object.freeze({ parse });
})();
