"""Generate small, deterministic adapters for ordinary interview functions.

These adapters must only be executed inside the sandbox.  They are source
generation utilities, not a mechanism for evaluating uploaded code on the host.
"""
from __future__ import annotations

import ast
import json
import re


SCALARS = {"int", "int64", "float", "bool", "str", "char"}
TYPES = SCALARS | {t + suffix for t in SCALARS for suffix in ("[]", "[][]")} | {"ListNode", "TreeNode"}
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")


def validate_signature(signature: dict) -> dict:
    if not isinstance(signature, dict):
        raise ValueError("函数模式需要函数签名。")
    if not _IDENTIFIER.fullmatch(signature.get("name", "")):
        raise ValueError("函数名需要是普通标识符。")
    class_name = signature.get("class_name", "Solution")
    if class_name and not _IDENTIFIER.fullmatch(class_name):
        raise ValueError("类名需要是普通标识符，或留空表示全局函数。")
    parameters = signature.get("parameters", [])
    if not isinstance(parameters, list) or len(parameters) > 20:
        raise ValueError("函数参数数量必须介于 0 与 20 之间。")
    names = []
    for parameter in parameters:
        if not isinstance(parameter, dict) or not _IDENTIFIER.fullmatch(parameter.get("name", "")):
            raise ValueError("参数名需要是普通标识符。")
        if parameter.get("type") not in TYPES:
            raise ValueError("函数参数包含暂不支持的类型。")
        names.append(parameter["name"])
    if len(names) != len(set(names)):
        raise ValueError("函数参数名不能重复。")
    if signature.get("returns") not in TYPES | {"void"}:
        raise ValueError("函数返回类型暂不支持。")
    capture = signature.get("capture_argument", 0)
    if signature["returns"] == "void" and (not isinstance(capture, int) or isinstance(capture, bool) or not 0 <= capture < len(parameters)):
        raise ValueError("原地修改函数需要指定有效的检查参数下标。")
    return signature


_PY_HELPERS = r'''
import json as _an_json
import os as _an_os
import sys as _an_sys
import math as _an_math
from typing import *
from collections import deque, defaultdict, Counter

def _an_decode(value, kind):
    if kind.endswith("[]"):
        if not isinstance(value, list):
            raise ValueError("函数参数需要数组")
        return [_an_decode(v, kind[:-2]) for v in value]
    if kind in ("int", "int64"):
        if type(value) is not int:
            raise ValueError("函数参数需要整数")
        if kind == "int64" and not -(2**63) <= value < 2**63:
            raise ValueError("int64 参数超出有符号 64 位范围")
        return value
    if kind == "float":
        if type(value) not in (int, float) or not _an_math.isfinite(value):
            raise ValueError("函数参数需要有限数值")
        return float(value)
    if kind == "bool":
        if type(value) is not bool:
            raise ValueError("函数参数需要布尔值")
        return value
    if kind == "str":
        if type(value) is not str:
            raise ValueError("函数参数需要字符串")
        return value
    if kind == "char":
        if type(value) is not str or len(value) != 1:
            raise ValueError("char 参数需要单个字符的字符串")
        return value
    if kind == "ListNode":
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("链表输入需要 JSON 数组")
        head = previous = None
        for item in value:
            node = ListNode(_an_decode(item, "int"))
            if previous is None:
                head = node
            else:
                previous.next = node
            previous = node
        return head
    if kind == "TreeNode":
        if value is None or value == []:
            return None
        if not isinstance(value, list):
            raise ValueError("二叉树输入需要层序 JSON 数组")
        if value[0] is None:
            if any(v is not None for v in value[1:]):
                raise ValueError("二叉树根节点为空，但仍提供了非空节点")
            return None
        root = TreeNode(_an_decode(value[0], "int"))
        queue = deque([root])
        cursor = 1
        while queue and cursor < len(value):
            node = queue.popleft()
            for attribute in ("left", "right"):
                if cursor >= len(value):
                    break
                if value[cursor] is not None:
                    child = TreeNode(_an_decode(value[cursor], "int"))
                    setattr(node, attribute, child)
                    queue.append(child)
                cursor += 1
        if any(v is not None for v in value[cursor:]):
            raise ValueError("层序数组中存在无法连接到根节点的元素")
        return root
    raise ValueError("不支持的函数类型")

def _an_encode(value, kind):
    if kind == "ListNode":
        result, seen = [], set()
        while value is not None:
            if id(value) in seen or len(seen) >= 50000:
                raise ValueError("返回链表包含环或超过 50000 个节点")
            seen.add(id(value))
            result.append(value.val)
            value = value.next
        return result
    if kind == "TreeNode":
        if value is None:
            return []
        result, seen, queue = [], set(), deque([value])
        while queue:
            node = queue.popleft()
            if node is None:
                result.append(None)
                continue
            if id(node) in seen or len(seen) >= 50000:
                raise ValueError("返回二叉树包含环、重复节点或超过 50000 个节点")
            seen.add(id(node))
            result.append(node.val)
            queue.extend((node.left, node.right))
        while result and result[-1] is None:
            result.pop()
        return result
    return value
'''


def python_harness(code: str, signature: dict) -> str:
    signature = validate_signature(signature)
    tree = None
    try:
        tree = ast.parse(code)
        defined = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    except SyntaxError:
        defined = set()  # The submitted code will retain its useful syntax error.
    nodes = ""
    if "ListNode" not in defined:
        nodes += "\nclass ListNode:\n    def __init__(self, val=0, next=None):\n        self.val, self.next = val, next\n"
    if "TreeNode" not in defined:
        nodes += "\nclass TreeNode:\n    def __init__(self, val=0, left=None, right=None):\n        self.val, self.left, self.right = val, left, right\n"
    # Lift only the future-import statement, not the entire physical line: a
    # legal import may share its line with a constant or another statement.
    # AST columns are UTF-8 byte offsets, rather than Python character offsets.
    future_lines, replacements = [], []
    if tree is not None:
        offsets = [0]
        for line in code.encode("utf-8").splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                future_lines.append(ast.get_source_segment(code, node))
                replacements.append((offsets[node.lineno - 1] + node.col_offset,
                                     offsets[node.end_lineno - 1] + node.end_col_offset))
        source_bytes = code.encode("utf-8")
        for start, end in reversed(replacements):
            source_bytes = source_bytes[:start] + b"pass" + source_bytes[end:]
        code = source_bytes.decode("utf-8")
    types = [p["type"] for p in signature.get("parameters", [])]
    target = (signature.get("class_name", "Solution") + "()." if signature.get("class_name", "Solution") else "") + signature["name"]
    call = f"{target}(*_an_arguments)"
    if signature["returns"] == "void":
        capture = signature.get("capture_argument", 0)
        result = f"    {call}\n    _an_answer = _an_encode(_an_arguments[{capture}], {types[capture]!r})"
    else:
        result = f"    _an_answer = _an_encode({call}, {signature['returns']!r})"
    suffix = f'''

if __name__ == "__main__":
    _an_input = _an_json.load(_an_sys.stdin)
    _an_types = {types!r}
    if not isinstance(_an_input, list) or len(_an_input) != len(_an_types):
        raise ValueError("输入参数数量与函数签名不匹配")
    _an_arguments = [_an_decode(v, t) for v, t in zip(_an_input, _an_types)]
{result}
    with open(_an_os.environ.get("ALGONOTE_RESULT_PATH", "algonote-result.json"), "w", encoding="utf-8") as _an_file:
        _an_json.dump(_an_answer, _an_file, ensure_ascii=False, allow_nan=False)
'''
    return "\n".join(future_lines) + "\n" + _PY_HELPERS + nodes + "\n# Submitted source\n" + code + suffix


_CPP_HELPERS = r'''
#include <bits/stdc++.h>
#include <nlohmann/json.hpp>
using namespace std;
namespace algonote_internal {
using Json = nlohmann::json;
template <class T> T read(const Json& value) {
    if constexpr (is_same_v<T, int>) {
        if (!value.is_number_integer() || value.is_boolean()) throw runtime_error("Expected integer");
        if (value.is_number_unsigned()) {
            auto n = value.get<unsigned long long>();
            if (n > INT_MAX) throw runtime_error("C++ int input is outside 32-bit range");
            return static_cast<int>(n);
        }
        auto n = value.get<long long>();
        if (n < INT_MIN || n > INT_MAX) throw runtime_error("C++ int input is outside 32-bit range");
        return static_cast<int>(n);
    } else if constexpr (is_same_v<T, long long>) {
        if (!value.is_number_integer() || value.is_boolean()) throw runtime_error("Expected 64-bit integer");
        if (value.is_number_unsigned() && value.get<unsigned long long>() > LLONG_MAX) throw runtime_error("int64 input is outside signed 64-bit range");
        return value.get<long long>();
    } else if constexpr (is_same_v<T, double>) {
        if (!value.is_number()) throw runtime_error("Expected number");
        double n = value.get<double>();
        if (!isfinite(n)) throw runtime_error("Expected finite number");
        return n;
    } else if constexpr (is_same_v<T, char>) {
        if (!value.is_string()) throw runtime_error("char expects a one-character ASCII string");
        auto text = value.get<string>();
        if (text.size()!=1 || static_cast<unsigned char>(text[0])>127) throw runtime_error("C++ char expects one ASCII character");
        return text[0];
    } else if constexpr (is_same_v<T, bool>) {
        if (!value.is_boolean()) throw runtime_error("Expected boolean");
        return value.get<bool>();
    } else if constexpr (is_same_v<T, string>) {
        if (!value.is_string()) throw runtime_error("Expected string");
        return value.get<string>();
    } else {
        if (!value.is_array()) throw runtime_error("Expected array");
        T result;
        for (const auto& item : value) result.push_back(read<typename T::value_type>(item));
        return result;
    }
}
Json encode_char(char value) {
    if (static_cast<unsigned char>(value)>127) throw runtime_error("C++ char output must be ASCII");
    return string(1,value);
}
template<class T> Json encode_char(const vector<T>& values) {
    Json result=Json::array();
    for(const auto& value : values) result.push_back(encode_char(value));
    return result;
}
}
'''

_CPP_LIST_HELPERS = r'''
namespace algonote_internal {
ListNode* read_list(const Json& value) {
    if (value.is_null()) return nullptr;
    if (!value.is_array()) throw runtime_error("ListNode expects JSON array");
    ListNode *head = nullptr, *previous = nullptr;
    for (const auto& item : value) {
        auto* node = new ListNode(read<int>(item));
        if (previous) previous->next = node; else head = node;
        previous = node;
    }
    return head;
}
Json encode(ListNode* node) {
    Json result = Json::array();
    unordered_set<ListNode*> seen;
    while (node) {
        if (seen.size() >= 50000 || !seen.insert(node).second) throw runtime_error("List contains cycle or too many nodes");
        result.push_back(node->val);
        node = node->next;
    }
    return result;
}
}
'''

_CPP_TREE_HELPERS = r'''
namespace algonote_internal {
TreeNode* read_tree(const Json& value) {
    if (value.is_null() || (value.is_array() && value.empty())) return nullptr;
    if (!value.is_array()) throw runtime_error("TreeNode expects level-order JSON array");
    if (value[0].is_null()) {
        for (size_t i=1; i<value.size(); ++i) if (!value[i].is_null()) throw runtime_error("Invalid tree root");
        return nullptr;
    }
    auto* root = new TreeNode(read<int>(value[0]));
    queue<TreeNode*> queue;
    queue.push(root);
    size_t cursor=1;
    while (!queue.empty() && cursor < value.size()) {
        auto* node = queue.front(); queue.pop();
        for (TreeNode** child : {&node->left, &node->right}) {
            if (cursor >= value.size()) break;
            if (!value[cursor].is_null()) {
                *child = new TreeNode(read<int>(value[cursor]));
                queue.push(*child);
            }
            ++cursor;
        }
    }
    for (; cursor<value.size(); ++cursor) if (!value[cursor].is_null()) throw runtime_error("Unreachable tree node");
    return root;
}
Json encode(TreeNode* node) {
    Json result = Json::array();
    if (!node) return result;
    queue<TreeNode*> queue;
    unordered_set<TreeNode*> seen;
    queue.push(node);
    while (!queue.empty()) {
        auto* next = queue.front(); queue.pop();
        if (!next) { result.push_back(nullptr); continue; }
        if (seen.size() >= 50000 || !seen.insert(next).second) throw runtime_error("Tree contains cycle or too many nodes");
        result.push_back(next->val);
        queue.push(next->left); queue.push(next->right);
    }
    while (!result.empty() && result.back().is_null()) result.erase(result.size()-1);
    return result;
}
}
'''


def _cpp_type(kind: str) -> str:
    if kind.endswith("[]"):
        return "vector<" + _cpp_type(kind[:-2]) + ">"
    return {"int": "int", "int64": "long long", "float": "double", "bool": "bool", "str": "string", "char": "char", "ListNode": "ListNode*", "TreeNode": "TreeNode*"}[kind]


def cpp_harness(code: str, signature: dict) -> str:
    signature = validate_signature(signature)
    used = {p["type"] for p in signature.get("parameters", [])} | {signature["returns"]}
    declarations = ""
    helpers = ""
    # Avoid class names inside comments incorrectly suppressing supplied nodes.
    plain_code = re.sub(r"/\*.*?\*/|//[^\n]*", "", code, flags=re.S)
    if "ListNode" in used:
        if not re.search(r"\b(?:struct|class)\s+ListNode\s*(?::[^{};]+)?\{", plain_code):
            declarations += "\nstruct ListNode { int val; ListNode* next; ListNode(int x=0, ListNode* n=nullptr): val(x),next(n) {} };\n"
        helpers += _CPP_LIST_HELPERS
    if "TreeNode" in used:
        if not re.search(r"\b(?:struct|class)\s+TreeNode\s*(?::[^{};]+)?\{", plain_code):
            declarations += "\nstruct TreeNode { int val; TreeNode *left, *right; TreeNode(int x=0, TreeNode* l=nullptr, TreeNode* r=nullptr):val(x),left(l),right(r) {} };\n"
        helpers += _CPP_TREE_HELPERS
    parameters = signature.get("parameters", [])
    arguments = []
    names = []
    for i, parameter in enumerate(parameters):
        name, kind = f"_an_arg_{i}", parameter["type"]
        names.append(name)
        convert = {"ListNode": "read_list", "TreeNode": "read_tree"}.get(kind, f"read<{_cpp_type(kind)}>")
        arguments.append(f"        auto {name} = algonote_internal::{convert}(_an_input.at({i}));")
    target = ""
    if signature.get("class_name", "Solution"):
        target = f"        {signature.get('class_name', 'Solution')} _an_solution;\n"
        call = "_an_solution." + signature["name"]
    else:
        call = signature["name"]
    call += "(" + ", ".join(names) + ")"
    if signature["returns"] == "void":
        i = signature.get("capture_argument", 0)
        result_kind = parameters[i]["type"]
        result_name = names[i]
        target += f"        {call};\n"
    else:
        result_kind, result_name = signature["returns"], "_an_answer"
        target += f"        auto _an_answer = {call};\n"
    encoded = f"algonote_internal::encode({result_name})" if result_kind in ("ListNode", "TreeNode") else f"algonote_internal::Json({result_name})"
    if result_kind in ("char", "char[]", "char[][]"):
        encoded = f"algonote_internal::encode_char({result_name})"
    suffix = "\n" + helpers + f'''
int main() {{
    try {{
        algonote_internal::Json _an_input;
        cin >> _an_input;
        if (!_an_input.is_array() || _an_input.size() != {len(parameters)}) throw runtime_error("Input argument count does not match signature");
{chr(10).join(arguments)}
{target}
        auto _an_json = {encoded};
        const char* _an_path = getenv("ALGONOTE_RESULT_PATH");
        ofstream _an_file(_an_path ? _an_path : "algonote-result.json");
        if (!_an_file) throw runtime_error("Cannot write function result");
        _an_file << _an_json.dump();
        if (!_an_file) throw runtime_error("Cannot finish function result");
        return 0;
    }} catch (const exception& error) {{
        cerr << "Function adapter: " << error.what() << endl;
        return 1;
    }}
}}
'''
    return _CPP_HELPERS + declarations + "\n// Submitted source\n" + code + suffix


def build_source(language: str, code: str, mode: str, signature: dict | None) -> str:
    if language not in ("cpp", "python"):
        raise ValueError("仅支持 C++ 和 Python。")
    if mode == "stdin":
        return code
    if mode != "function":
        raise ValueError("未知执行模式。")
    return cpp_harness(code, signature) if language == "cpp" else python_harness(code, signature)
