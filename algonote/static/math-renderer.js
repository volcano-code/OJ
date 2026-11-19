/* Lightweight, dependency-free math rendering for AlgoNote.
 * Uses DOM text nodes and semantic sup/sub/fraction elements; never injects HTML.
 * Supports common copied LeetCode constraints, inline TeX, and display-math blocks.
 */
(() => {
  'use strict';

  const SYMBOLS = Object.freeze({
    le: '≤', leq: '≤', ge: '≥', geq: '≥', neq: '≠',
    times: '×', cdot: '·', div: '÷', pm: '±', mp: '∓',
    pi: 'π', theta: 'θ', alpha: 'α', beta: 'β', gamma: 'γ',
    lambda: 'λ', mu: 'μ', sigma: 'σ', infinity: '∞',
    infty: '∞', sum: '∑', prod: '∏', int: '∫',
    in: '∈', notin: '∉', subset: '⊂', subseteq: '⊆',
    union: '∪', cap: '∩', emptyset: '∅', approx: '≈',
    equiv: '≡', to: '→', rightarrow: '→', leftarrow: '←',
    mapsto: '↦', ldots: '…', cdots: '⋯', forall: '∀',
    exists: '∃', neg: '¬', land: '∧', lor: '∨'
  });

  const TERM = '[A-Za-z_]\\w*(?:\\s*\\^\\s*(?:\\{[^}]+\\}|-?\\d+))?(?:\\[[^\\]]+\\])?';
  const POWER = '-?\\d+\\s*\\^\\s*(?:\\{[^}]+\\}|-?\\d+)';
  const COMPLEXITY = '\\bO\\(\\s*[A-Za-z][A-Za-z0-9]*(?:\\s*\\^\\s*(?:\\{[^}]+\\}|-?\\d+))?\\s*\\)';
  const CHAINED = '-?\\d+(?:\\s*\\^\\s*(?:\\{[^}]+\\}|-?\\d+))?\\s*(?:<=|>=|<|>|==|!=)\\s*[A-Za-z_]\\w*(?:\\.[A-Za-z_]\\w*)?(?:\\[[^\\]]+\\])?(?:\\s*(?:<=|>=|<|>|==|!=)\\s*-?\\d+(?:\\s*\\^\\s*(?:\\{[^}]+\\}|-?\\d+))?)?';
  const COMPARISON = '(?:[A-Za-z_]\\w*(?:\\.[A-Za-z_]\\w*)?(?:\\[[^\\]]+\\])?)\\s*(?:==|!=|<=|>=|=|<|>)\\s*-?\\d+(?:\\s*\\^\\s*(?:\\{[^}]+\\}|-?\\d+))?';
  const ARITHMETIC = TERM + '(?:\\s*[+*/-]\\s*' + TERM + ')+\\s*(?:==|!=|<=|>=|=|<|>)\\s*(?:-?\\d+(?:\\s*\\^\\s*(?:\\{[^}]+\\}|-?\\d+))?|' + TERM + ')';
  const MATH_PATTERN = new RegExp('(?:' + COMPLEXITY + ')|(?:' + CHAINED + ')|(?:' + ARITHMETIC + ')|(?:' + COMPARISON + ')|(?:\\b' + POWER + ')', 'g');

  function normalizeMath(source) {
    return String(source)
      .replace(/\bO\(\s*([a-z])([2-9])\s*\)/gi, 'O($1^$2)')
      .replace(/\s*<=\s*/g, ' ≤ ')
      .replace(/\s*>=\s*/g, ' ≥ ')
      .replace(/\s*!=\s*/g, ' ≠ ')
      .replace(/\s*==\s*/g, ' = ')
      .replace(/\s*->\s*/g, ' → ');
  }

  function readArgument(source, index) {
    while (index < source.length && /\s/.test(source[index])) index += 1;
    if (index >= source.length) return { value: '', next: index };
    if (source[index] !== '{') return { value: source[index], next: index + 1 };
    let depth = 1;
    let cursor = index + 1;
    const start = cursor;
    while (cursor < source.length && depth > 0) {
      if (source[cursor] === '\\' && cursor + 1 < source.length) { cursor += 2; continue; }
      if (source[cursor] === '{') depth += 1;
      else if (source[cursor] === '}') depth -= 1;
      cursor += 1;
    }
    return { value: source.slice(start, depth === 0 ? cursor - 1 : cursor), next: cursor };
  }

  function appendText(parent, text) {
    if (text) parent.append(document.createTextNode(text));
  }

  function renderSequence(parent, source) {
    let buffer = '';
    const flush = () => {
      appendText(parent, buffer.replace(/<=/g, '≤').replace(/>=/g, '≥').replace(/!=/g, '≠').replace(/==/g, '='));
      buffer = '';
    };

    for (let i = 0; i < source.length;) {
      const char = source[i];
      if (char === '^' || char === '_') {
        flush();
        const argument = readArgument(source, i + 1);
        if (!argument.value) { buffer += char; i += 1; continue; }
        const node = document.createElement(char === '^' ? 'sup' : 'sub');
        node.className = char === '^' ? 'math-sup' : 'math-sub';
        renderSequence(node, argument.value);
        parent.append(node);
        i = argument.next;
        continue;
      }
      if (char === '{') {
        flush();
        const argument = readArgument(source, i);
        renderSequence(parent, argument.value);
        i = argument.next;
        continue;
      }
      if (char === '\\') {
        flush();
        if (i + 1 >= source.length) { buffer += char; i += 1; continue; }
        if (source[i + 1] === ' ' || source[i + 1] === ',' || source[i + 1] === ';') {
          buffer += ' ';
          i += 2;
          continue;
        }
        const match = source.slice(i + 1).match(/^([A-Za-z]+)|^(.)/s);
        const command = match ? match[1] || match[2] : '';
        i += 1 + command.length;
        if (command === 'left' || command === 'right') continue;
        if (command === 'frac' || command === 'dfrac' || command === 'tfrac') {
          const numerator = readArgument(source, i); i = numerator.next;
          const denominator = readArgument(source, i); i = denominator.next;
          const fraction = document.createElement('span');
          fraction.className = 'math-fraction';
          const top = document.createElement('span'); top.className = 'math-numerator';
          const bottom = document.createElement('span'); bottom.className = 'math-denominator';
          renderSequence(top, numerator.value); renderSequence(bottom, denominator.value);
          fraction.append(top, bottom); parent.append(fraction);
          continue;
        }
        if (command === 'sqrt') {
          const radicand = readArgument(source, i); i = radicand.next;
          const root = document.createElement('span'); root.className = 'math-root';
          appendText(root, '√');
          const content = document.createElement('span'); content.className = 'math-radicand';
          renderSequence(content, radicand.value);
          root.append(content); parent.append(root);
          continue;
        }
        if (command === 'text' || command === 'mathrm' || command === 'operatorname') {
          const argument = readArgument(source, i); i = argument.next;
          const upright = document.createElement('span'); upright.className = 'math-upright';
          renderSequence(upright, argument.value); parent.append(upright);
          continue;
        }
        if (command === '{' || command === '}' || command === '%' || command === '_' || command === '$') {
          buffer += command;
          continue;
        }
        buffer += SYMBOLS[command] || command;
        continue;
      }
      buffer += char;
      i += 1;
    }
    flush();
  }

  function render(parent, source, display = false) {
    const wrapper = document.createElement('span');
    wrapper.className = display ? 'math-display' : 'math-inline';
    renderSequence(wrapper, normalizeMath(source));
    parent.append(wrapper);
    return wrapper;
  }

  function appendPlainText(parent, text) {
    const source = String(text);
    MATH_PATTERN.lastIndex = 0;
    let match;
    let offset = 0;
    while ((match = MATH_PATTERN.exec(source))) {
      if (match.index > offset) appendText(parent, source.slice(offset, match.index));
      render(parent, match[0], false);
      offset = match.index + match[0].length;
      if (!match[0].length) MATH_PATTERN.lastIndex += 1;
    }
    if (offset < source.length) appendText(parent, source.slice(offset));
  }

  function appendInline(parent, source) {
    const text = String(source);
    const tokenPattern = /\$[^$\n]+\$|\\\([^\n]+?\\\)/g;
    let match;
    let offset = 0;
    while ((match = tokenPattern.exec(text))) {
      if (match.index > offset) appendPlainText(parent, text.slice(offset, match.index));
      const token = match[0];
      const content = token.startsWith('$') ? token.slice(1, -1) : token.slice(2, -2);
      render(parent, content, false);
      offset = match.index + token.length;
    }
    if (offset < text.length) appendPlainText(parent, text.slice(offset));
  }

  function renderDisplay(parent, source) {
    return render(parent, source, true);
  }

  window.AlgoNoteMath = Object.freeze({
    render,
    renderDisplay,
    appendInline,
    appendPlainText,
    normalizeMath
  });
})();
