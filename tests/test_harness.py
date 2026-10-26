"""Execute only fixed, trusted developer fixtures to check generated adapters.

This does not validate Docker isolation. Production uploaded code never follows
this helper's host execution path.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from algonote.harness import build_source, validate_signature


def signature(name, parameters, returns, class_name="Solution", capture_argument=0):
    return {"name": name, "class_name": class_name,
            "parameters": [{"name": f"arg{i}", "type": t} for i, t in enumerate(parameters)],
            "returns": returns, "capture_argument": capture_argument}


def execute_fixture(tmp_path, language, code, function_signature, arguments):
    """The arguments come solely from constants in this test file."""
    source = build_source(language, code, "function", function_signature)
    result_file = tmp_path / "result.json"
    env = {**os.environ, "ALGONOTE_RESULT_PATH": str(result_file)}
    if language == "python":
        program = tmp_path / "program.py"
        program.write_text(source, encoding="utf-8")
        command = [sys.executable, "-I", str(program)]
    else:
        if not shutil.which("g++"):
            pytest.skip("g++ not available; actual C++ harness execution not tested")
        program = tmp_path / "program.cpp"
        program.write_text(source, encoding="utf-8")
        command = ["g++", "-std=c++17", "-O0", str(program), "-o", str(tmp_path / "program")]
        try:
            import nlohmann_json
            command.extend(["-I", str(nlohmann_json.get_include())])
        except ImportError:
            if not Path("/usr/include/nlohmann/json.hpp").is_file():
                pytest.skip("nlohmann-json header not available")
        built = subprocess.run(command, text=True, capture_output=True, timeout=40)
        assert built.returncode == 0, built.stderr
        command = [str(tmp_path / "program")]
    completed = subprocess.run(command, input=json.dumps(arguments), text=True,
                               capture_output=True, env=env, cwd=tmp_path, timeout=5)
    result = json.loads(result_file.read_text()) if result_file.exists() else None
    return completed, result


@pytest.mark.parametrize("language,code", [
    ("python", "class Solution:\n    def twoSum(self, nums, target):\n        print('debug')\n        seen = {}\n        for i, x in enumerate(nums):\n            if target-x in seen: return [seen[target-x], i]\n            seen[x] = i"),
    ("cpp", "class Solution { public: vector<int> twoSum(vector<int>& nums, int target) { cout << \"debug\"; unordered_map<int,int> seen; for (int i=0;i<(int)nums.size();++i) {if(seen.count(target-nums[i]))return {seen[target-nums[i]],i};seen[nums[i]]=i;}return {};} };")
])
def test_two_sum_and_debug_stdout(tmp_path, language, code):
    completed, actual = execute_fixture(tmp_path, language, code,
                                       signature("twoSum", ["int[]", "int"], "int[]"), [[3, 3], 6])
    assert completed.returncode == 0, completed.stderr
    assert actual == [0, 1]
    assert "debug" in completed.stdout


@pytest.mark.parametrize("language,code", [
    ("python", "class Solution:\n    def reverseList(self, head):\n        previous=None\n        while head:\n            following=head.next\n            head.next=previous\n            previous=head\n            head=following\n        return previous"),
    ("cpp", "class Solution {public: ListNode* reverseList(ListNode* head) {ListNode* p=nullptr;while(head){auto* n=head->next;head->next=p;p=head;head=n;}return p;}};")
])
def test_linked_list(tmp_path, language, code):
    completed, actual = execute_fixture(tmp_path, language, code, signature("reverseList", ["ListNode"], "ListNode"), [[1, 2, 3]])
    assert completed.returncode == 0, completed.stderr
    assert actual == [3, 2, 1]


@pytest.mark.parametrize("language,code", [
    ("python", "class Solution:\n    def invertTree(self, root):\n        if root:\n            root.left,root.right=self.invertTree(root.right),self.invertTree(root.left)\n        return root"),
    ("cpp", "class Solution {public: TreeNode* invertTree(TreeNode* root){if(root){auto* t=invertTree(root->left);root->left=invertTree(root->right);root->right=t;}return root;}};")
])
def test_tree_level_order(tmp_path, language, code):
    completed, actual = execute_fixture(tmp_path, language, code, signature("invertTree", ["TreeNode"], "TreeNode"), [[1, 2, 3, None, 4]])
    assert completed.returncode == 0, completed.stderr
    assert actual == [1, 3, 2, None, None, 4]


@pytest.mark.parametrize("language,code", [
    ("python", "class Solution:\n    def change(self, nums):\n        nums.reverse()"),
    ("cpp", "class Solution {public: void change(vector<int>& nums){reverse(nums.begin(),nums.end());}};")
])
def test_void_captures_mutated_argument(tmp_path, language, code):
    completed, actual = execute_fixture(tmp_path, language, code, signature("change", ["int[]"], "void"), [[1, 4, 9]])
    assert completed.returncode == 0, completed.stderr
    assert actual == [9, 4, 1]


@pytest.mark.parametrize("language,code", [
    ("python", "def total(nums):\n    return sum(nums)"),
    ("cpp", "long long total(vector<long long>& nums){long long result=0;for(auto value:nums) result+=value;return result;}")
])
def test_global_function_int64(tmp_path, language, code):
    completed, actual = execute_fixture(tmp_path, language, code, signature("total", ["int64[]"], "int64", class_name=""), [[4000000000, 7000000000]])
    assert completed.returncode == 0, completed.stderr
    assert actual == 11000000000


@pytest.mark.parametrize("language,code", [
    ("python", "class Solution:\n    def copy(self, matrix):\n        return matrix"),
    ("cpp", "class Solution{public: vector<vector<string>> copy(vector<vector<string>>& m){return m;}};")
])
def test_nested_strings_with_unicode_and_escapes(tmp_path, language, code):
    value = [["中文", "a\"b", "\\n"], []]
    completed, actual = execute_fixture(tmp_path, language, code, signature("copy", ["str[][]"], "str[][]"), [value])
    assert completed.returncode == 0, completed.stderr
    assert actual == value


def test_python_future_annotations_and_user_node(tmp_path):
    code = "from __future__ import annotations\nclass ListNode:\n    def __init__(self, val):\n        self.val=val\n        self.next=None\nclass Solution:\n    def unchanged(self, x: ListNode|None):\n        return x\n"
    completed, actual = execute_fixture(tmp_path, "python", code, signature("unchanged", ["ListNode"], "ListNode"), [[8]])
    assert completed.returncode == 0, completed.stderr
    assert actual == [8]


@pytest.mark.parametrize("prefix", [
    "from __future__ import annotations; LIMIT = 3",
    '"""中文说明"""; from __future__ import (\n    annotations,\n); LIMIT = 3',
])
def test_future_import_preserves_neighboring_statements(tmp_path, prefix):
    code = prefix + "\nclass Solution:\n    def answer(self) -> int:\n        return LIMIT\n"
    completed, actual = execute_fixture(tmp_path, "python", code, signature("answer", [], "int"), [])
    assert completed.returncode == 0, completed.stderr
    assert actual == 3


@pytest.mark.parametrize("language,code", [
    ("python", "class Solution:\n    def reverseString(self, s):\n        s.reverse()"),
    ("cpp", "class Solution {public: void reverseString(vector<char>& s){reverse(s.begin(),s.end());}};")
])
def test_character_arrays_serialize_as_strings(tmp_path, language, code):
    completed, actual = execute_fixture(tmp_path, language, code, signature("reverseString", ["char[]"], "void"), [["h", "i", "!"]])
    assert completed.returncode == 0, completed.stderr
    assert actual == ["!", "i", "h"]


def test_cycle_is_reported_instead_of_hanging(tmp_path):
    code = "class Solution:\n    def cycle(self, head):\n        head.next=head\n        return head"
    completed, _ = execute_fixture(tmp_path, "python", code, signature("cycle", ["ListNode"], "ListNode"), [[1]])
    assert completed.returncode != 0
    assert "环" in completed.stderr


def test_cpp_rejects_int32_overflow(tmp_path):
    completed, _ = execute_fixture(tmp_path, "cpp", "int identity(int value){return value;}", signature("identity", ["int"], "int", class_name=""), [2**40])
    assert completed.returncode != 0
    assert "32-bit" in completed.stderr


def test_signature_validation_and_stdin_passthrough():
    with pytest.raises(ValueError):
        validate_signature(signature("f;system", ["int"], "int"))
    with pytest.raises(ValueError):
        validate_signature(signature("f", [], "void"))
    with pytest.raises(ValueError):
        validate_signature(signature("f", ["arbitrary_cpp_type"], "int"))
    assert build_source("python", "print(input())", "stdin", None) == "print(input())"
