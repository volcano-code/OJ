'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('algonote/static/problem-importer.js', 'utf8');
const context = { window: {} };
vm.runInNewContext(source, context);
const parse = context.window.AlgoNoteImporter.parse;

const leetcode = parse(`1. 两数之和
简单
相关标签
数组 哈希表
相关企业
premium lock icon
提示
给定一个整数数组 nums 和一个整数目标值 target，请你在该数组中找出和为目标值的那两个整数。

示例 1：
输入：nums = [2,7,11,15], target = 9
输出：[0,1]
解释：因为 nums[0] + nums[1] == 9，返回 [0, 1]。

示例 2：
输入：nums = [3,2,4], target = 6
输出：[1,2]

提示：
2 <= nums.length <= 10^4

进阶：你可以想出一个时间复杂度小于 O(n²) 的算法吗？`, 'leetcode');
assert.equal(leetcode.title, '两数之和');
assert.equal(leetcode.difficulty, 'easy');
assert.deepEqual(Array.from(leetcode.tags), ['数组', '哈希表']);
assert.match(leetcode.statement, /给定一个整数数组/);
assert.match(leetcode.statement, /### 示例 1/);
assert.match(leetcode.statement, /\*\*输入：\*\*/);
assert.doesNotMatch(leetcode.statement, /premium lock icon|相关企业/);
assert.match(leetcode.statement, /示例 2/);
assert.match(leetcode.statement, /进阶/);
assert.match(leetcode.statement, /2 <= nums\\.length/);

const english = parse(`1. Two Sum
Easy
Topics
Array Hash Table
Companies
premium lock icon

Description

Given an array of integers nums and an integer target, return indices of the two numbers that add up to target.

Example 1:
Input: nums = [2,7,11,15], target = 9
Output: [0,1]

Constraints:
2 <= nums.length <= 10^4`, 'leetcode');
assert.equal(english.title, 'Two Sum');
assert.equal(english.difficulty, 'easy');
assert.match(english.statement, /Given an array of integers/);
assert.match(english.statement, /### 示例 1/);
assert.match(english.statement, /Constraints:/);
assert.doesNotMatch(english.statement, /premium lock icon|Companies/);

const nowcoder = parse(`题目描述
给定 n 个整数，请输出它们的和。
输入描述：
第一行包含整数 n。
输出描述：
输出这些整数的和。
示例：
输入：
3
输出：
6`, 'nowcoder');
assert.notEqual(nowcoder.title, '题目描述');
assert.match(nowcoder.statement, /输入描述/);
assert.match(nowcoder.statement, /输出描述/);
assert.match(nowcoder.statement, /给定 n 个整数/);
assert.match(nowcoder.statement, /3/);
console.log('problem importer tests passed');
