import ast

import pytest

from algonote.inference import infer


def test_python_solution_and_nested_vectors():
    result = infer("python", """from typing import List
class Solution:
    def transpose(self, matrix: List[List[int]]) -> List[List[int]]:
        return list(map(list, zip(*matrix)))
""")
    assert result["mode"] == "function"
    assert result["signature"]["parameters"] == [{"name": "matrix", "type": "int[][]"}]
    assert result["signature"]["returns"] == "int[][]"
    assert "zip" not in result["template"]  # A practice template must not leak the reference.
    ast.parse(result["template"])


@pytest.mark.parametrize("annotation", ["Optional[ListNode]", "ListNode | None", '"ListNode"'])
def test_python_linked_list_annotations(annotation):
    result = infer("python", f"class Solution:\n    def reverseList(self, head: {annotation}) -> {annotation}:\n        return head\n")
    assert result["signature"]["parameters"][0]["type"] == "ListNode"
    assert result["signature"]["returns"] == "ListNode"


def test_python_missing_types_stay_editable_and_are_not_claimed_certain():
    result = infer("python", "class Solution:\n    def twoSum(self, numbers, target):\n        return [1, 2]\n")
    assert result["signature"]["name"] == "twoSum"
    assert len(result["warnings"]) == 3
    assert any("numbers" in message for message in result["warnings"])


def test_python_main_is_stdin_even_with_helper_functions():
    result = infer("python", "def add(a: int, b: int) -> int:\n    return a+b\ndef main():\n    print(add(1, 2))\n")
    assert result["mode"] == "stdin"
    assert result["signature"] is None


def test_python_syntax_error_and_no_eval():
    result = infer("python", "class Solution:\n    def solve(:\n")
    assert result["warnings"]
    result = infer("python", "raise RuntimeError('must never execute')\n")
    assert result["mode"] == "stdin"


def test_python_inplace_capture():
    result = infer("python", "class Solution:\n    def reverse(self, chars: list[str]) -> None:\n        chars.reverse()\n")
    assert result["signature"]["returns"] == "void"
    assert result["signature"]["capture_argument"] == 0
    assert result["warnings"]


def test_cpp_actual_nowcoder_style_signature():
    result = infer("cpp", """class Solution {
public:
    /** @param numbers int整型vector */
    vector<int> twoSum(vector<int>& numbers, int target) {
        return {1, 2};
    }
};""")
    assert result["signature"]["name"] == "twoSum"
    assert result["signature"]["class_name"] == "Solution"
    assert result["signature"]["parameters"] == [{"name": "numbers", "type": "int[]"}, {"name": "target", "type": "int"}]
    assert "return {1, 2}" not in result["template"]


def test_cpp_int64_nested_vectors_and_const():
    result = infer("cpp", "class Solution { public: long long count(const std::vector<std::vector<int>>& grid, long long target) const { return 0; } };")
    assert result["signature"]["parameters"] == [{"name": "grid", "type": "int[][]"}, {"name": "target", "type": "int64"}]
    assert result["signature"]["returns"] == "int64"


def test_cpp_global_helper_vs_solution_selection():
    result = infer("cpp", "int helper(int x) { return x; } class Solution { public: TreeNode* invertTree(TreeNode* root) { return root; } };")
    assert result["signature"]["name"] == "invertTree"
    assert result["signature"]["returns"] == "TreeNode"


def test_cpp_comments_and_strings_cannot_invent_main():
    result = infer("cpp", '/* int main() {} */\nclass Solution { public: string echo(string text) { string marker = "int main() {}"; return text; } };')
    assert result["mode"] == "function"
    assert result["signature"]["returns"] == "str"


def test_cpp_full_program_keeps_io_mode():
    result = infer("cpp", "int add(int a, int b) { return a+b; } int main() { return 0; }")
    assert result["mode"] == "stdin"


def test_cpp_character_vector_preserves_char_semantics():
    result = infer("cpp", "class Solution { public: void reverseString(vector<char>& chars) { reverse(chars.begin(), chars.end()); } };")
    assert result["signature"]["parameters"] == [{"name": "chars", "type": "char[]"}]
    assert result["signature"]["returns"] == "void"
    assert "vector<char>& chars" in result["template"]


def test_unrecognized_cpp_container_warns():
    result = infer("cpp", "class Solution { public: int count(std::map<int, int>& values) { return 0; } };")
    assert any("values" in warning for warning in result["warnings"])


def test_cpp_float_container_compatibility_is_not_silent():
    result = infer("cpp", "class Solution { public: float sum(vector<float>& values) { return 0; } };")
    assert result["signature"]["parameters"][0]["type"] == "float[]"
    assert any("vector<float>" in warning for warning in result["warnings"])


@pytest.mark.parametrize("language", ["java", "javascript", "bash"])
def test_unsupported_language_rejected(language):
    with pytest.raises(ValueError):
        infer(language, "")
