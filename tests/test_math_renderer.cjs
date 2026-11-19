'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class FakeNode {
  constructor(tagName, text = '') {
    this.tagName = tagName.toUpperCase();
    this.text = text;
    this.children = [];
    this.className = '';
  }
  append(...nodes) { this.children.push(...nodes); }
  get textContent() {
    return this.text + this.children.map(node => node.textContent).join('');
  }
  find(tag) {
    const wanted = tag.toUpperCase();
    return this.children.flatMap(node => [
      ...(node.tagName === wanted ? [node] : []),
      ...(typeof node.find === 'function' ? node.find(wanted) : [])
    ]);
  }
}

const document = {
  createElement: tag => new FakeNode(tag),
  createTextNode: text => new FakeNode('#text', String(text)),
};
const context = { window: {}, document };
vm.runInNewContext(fs.readFileSync('algonote/static/math-renderer.js', 'utf8'), context);
const math = context.window.AlgoNoteMath;

function renderInline(value) {
  const parent = new FakeNode('p');
  math.appendInline(parent, value);
  return parent;
}

const bounds = renderInline('2 <= nums.length <= 10^4');
assert.match(bounds.textContent, /2\s*≤\s*nums\.length\s*≤\s*104/);
assert.equal(bounds.find('sup').length, 1);
assert.equal(bounds.find('sup')[0].textContent, '4');

const arrayBounds = renderInline('-109 <= nums[i] <= 109');
assert.match(arrayBounds.textContent, /-109\s*≤\s*nums\[i\]\s*≤\s*109/);
assert.ok(arrayBounds.find('span').some(node => node.className === 'math-inline'));

const complexity = renderInline('时间复杂度小于 O(n2) 的算法吗？');
assert.match(complexity.textContent, /O\(n2\)/);
assert.equal(complexity.find('sup').length, 1);
assert.equal(complexity.find('sup')[0].textContent, '2');

const equation = renderInline('满足 $x^2 + y^2 = z^2$。');
assert.equal(equation.find('sup').length, 3);
assert.match(equation.textContent, /x2 \+ y2 = z2/);

const fraction = new FakeNode('div');
math.renderDisplay(fraction, "\\frac{n(n-1)}{2} \\le 10^4");
assert.equal(fraction.find('span').filter(node => node.className === 'math-fraction').length, 1);
assert.equal(fraction.find('sup').length, 1);
assert.ok(fraction.find('span').some(node => node.className === 'math-display'));

const safe = renderInline('$\\text{<img src=x onerror=alert(1)>}
assert.equal(safe.find('img').length, 0);
assert.match(safe.textContent, /<img src=x/);

console.log('math renderer tests passed');
);
assert.equal(safe.find('img').length, 0);
assert.match(safe.textContent, /<img src=x/);

console.log('math renderer tests passed');
