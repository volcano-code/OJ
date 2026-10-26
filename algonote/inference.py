"""Conservative signature assistance, never an arbitrary-code evaluator.

Inference is a convenience. Every returned signature remains editable. Python
uses AST; C++ recognizes common judge signatures rather than pretending to be a
complete C++ parser. Uncertain parameter types are explicitly reported.
"""
from __future__ import annotations

import ast
import re
from typing import Any


SCALARS = {"int", "int64", "float", "bool", "str", "char"}
SUPPORTED = SCALARS | {t + "[]" for t in SCALARS} | {t + "[][]" for t in SCALARS} | {"ListNode", "TreeNode", "void"}


def _python_type(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        if node.value is None:
            return "void"
        if isinstance(node.value, str):
            try:
                return _python_type(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                return None
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = node.id if isinstance(node, ast.Name) else node.attr
        return name if name in SCALARS | {"ListNode", "TreeNode"} else None
    if isinstance(node, ast.Subscript):
        base = node.value.id if isinstance(node.value, ast.Name) else node.value.attr if isinstance(node.value, ast.Attribute) else ""
        if base in {"List", "list"}:
            inner = _python_type(node.slice)
            result = inner + "[]" if inner else None
            return result if result in SUPPORTED else None
        if base in {"Optional"}:
            return _python_type(node.slice)
        if base == "Union" and isinstance(node.slice, ast.Tuple):
            values = [_python_type(v) for v in node.slice.elts]
            nonvoid = [v for v in values if v != "void"]
            return nonvoid[0] if len(nonvoid) == 1 and "void" in values else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left, right = _python_type(node.left), _python_type(node.right)
        if left == "void":
            return right
        if right == "void":
            return left
    return None


def _python_annotation(typ: str) -> str:
    if typ.endswith("[]"):
        return f"list[{_python_annotation(typ[:-2])}]"
    return {"int64": "int", "char": "str", "void": "None"}.get(typ, typ)


def _cpp_type(typ: str) -> str | None:
    cleaned = re.sub(r"\b(const|volatile)\b", "", typ)
    cleaned = cleaned.replace("std::", "").replace("&", "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned.replace(" ", "") in {"ListNode*", "TreeNode*"}:
        return cleaned.replace(" ", "")[:-1]
    m = re.fullmatch(r"vector\s*<\s*(.+)\s*>", cleaned)
    if m:
        inner = _cpp_type(m.group(1))
        result = inner + "[]" if inner else None
        return result if result in SUPPORTED else None
    return {"int": "int", "long long": "int64", "long long int": "int64", "int64_t": "int64", "double": "float", "float": "float", "bool": "bool", "string": "str", "char": "char", "void": "void"}.get(cleaned)


def _cpp_annotation(typ: str) -> str:
    if typ.endswith("[]"):
        return f"vector<{_cpp_annotation(typ[:-2])}>"
    return {"int64": "long long", "float": "double", "str": "string", "ListNode": "ListNode*", "TreeNode": "TreeNode*"}.get(typ, typ)


def make_template(language: str, mode: str, signature: dict[str, Any] | None) -> str:
    if mode == "stdin" or not signature:
        if language == "cpp":
            return "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    ios::sync_with_stdio(false);\n    cin.tie(nullptr);\n    // 在这里读取输入并输出结果\n    return 0;\n}\n"
        return "import sys\n\n\ndef main():\n    # 在这里读取输入并输出结果\n    pass\n\n\nif __name__ == \"__main__\":\n    main()\n"
    params = signature["parameters"]
    class_name = signature.get("class_name", "")
    if language == "python":
        declarations = [f"{p['name']}: {_python_annotation(p['type'])}" for p in params]
        if class_name:
            declarations.insert(0, "self")
        indent = "    " if class_name else ""
        prefix = f"class {class_name}:\n" if class_name else ""
        return "from __future__ import annotations\n\n" + prefix + f"{indent}def {signature['name']}({', '.join(declarations)}) -> {_python_annotation(signature['returns'])}:\n{indent}    # 在这里完成解答\n{indent}    raise NotImplementedError(\"请完成解答\")\n"
    declarations = [f"{_cpp_annotation(p['type'])}{'&' if p['type'].endswith('[]') or p['type'] == 'str' else ''} {p['name']}" for p in params]
    indent = "    " if class_name else ""
    prefix = f"class {class_name} {{\npublic:\n" if class_name else ""
    suffix = "};\n" if class_name else ""
    body = "" if signature["returns"] == "void" else f"{indent}    throw runtime_error(\"Please complete the solution\");\n"
    return "#include <bits/stdc++.h>\nusing namespace std;\n\n" + prefix + f"{indent}{_cpp_annotation(signature['returns'])} {signature['name']}({', '.join(declarations)}) {{\n{indent}    // 在这里完成解答\n{body}{indent}}}\n" + suffix


def _result(language: str, mode: str, signature: dict[str, Any] | None, warnings: list[str]) -> dict[str, Any]:
    return {"mode": mode, "signature": signature, "template": make_template(language, mode, signature), "warnings": warnings}


def _infer_python(code: str) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return _result("python", "stdin", None, ["Python 代码尚不能解析，请检查语法后重新识别，或手动选择执行模式。"])
    solution = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Solution"), None)
    candidates: list[ast.FunctionDef] = []
    class_name = ""
    if solution:
        class_name = "Solution"
        candidates = [n for n in solution.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
    else:
        candidates = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name != "main" and not n.name.startswith("_")]
        has_entrypoint = any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body)
        has_entrypoint = has_entrypoint or any(isinstance(n, ast.If) and "__name__" in ast.unparse(n.test) for n in tree.body)
        if has_entrypoint:
            return _result("python", "stdin", None, warnings)
    if not candidates:
        return _result("python", "stdin", None, ["未识别到 Solution 方法或独立解题函数，已按标准输入输出模式准备模板；可以手动修改。"])
    if len(candidates) > 1:
        warnings.append(f"检测到多个函数，暂选 {candidates[0].name}；请确认这是题目指定入口。")
    fn = candidates[0]
    if fn.args.vararg or fn.args.kwarg or fn.args.kwonlyargs:
        warnings.append("检测到可变参数或仅关键字参数，首版测试驱动按固定位置参数调用；请手动调整入口。")
    params = []
    all_args = list(fn.args.posonlyargs) + list(fn.args.args)
    if class_name and all_args and all_args[0].arg in {"self", "cls"}:
        if all_args[0].arg == "cls":
            warnings.append("检测到类方法，请核对类装饰器与调用方式。")
        all_args = all_args[1:]
    for param in all_args:
        typ = _python_type(param.annotation)
        if typ not in SUPPORTED or typ == "void":
            warnings.append(f"参数 {param.arg} 的类型不明确，暂填 int；请按题目改成实际类型。")
            typ = "int"
        params.append({"name": param.arg, "type": typ})
    returns = _python_type(fn.returns)
    if returns is None:
        warnings.append("返回类型不明确，暂填 int；请按题目确认（原地修改题可用 void）。")
        returns = "int"
    signature = {"name": fn.name, "class_name": class_name, "parameters": params, "returns": returns, "capture_argument": 0}
    if returns == "void":
        warnings.append("原地修改题默认检查第一个参数，必要时修改 capture_argument。")
    return _result("python", "function", signature, warnings)


def _split_params(text: str) -> list[str]:
    parts, start, level = [], 0, 0
    for i, char in enumerate(text):
        if char in "<([{":
            level += 1
        elif char in ">)]}":
            level -= 1
        elif char == "," and level == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    if text[start:].strip():
        parts.append(text[start:].strip())
    return parts


def _strip_cpp_literals(code: str) -> str:
    pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
    return re.sub(pattern, lambda m: "".join("\n" if c == "\n" else " " for c in m.group()), code)


def _class_ranges(code: str) -> list[tuple[int, int, str]]:
    ranges = []
    for match in re.finditer(r"\bclass\s+(\w+)\s*(?:final\s*)?\{", code):
        level, end = 1, match.end()
        while end < len(code) and level:
            if code[end] == "{":
                level += 1
            elif code[end] == "}":
                level -= 1
            end += 1
        ranges.append((match.end(), end, match.group(1)))
    return ranges


def _infer_cpp(code: str) -> dict[str, Any]:
    warnings: list[str] = []
    clean = _strip_cpp_literals(code)
    if re.search(r"\b(?:int|signed|auto)\s+main\s*\(", clean):
        return _result("cpp", "stdin", None, warnings)
    pattern = re.compile(r"(?:^|[;{}])\s*(?:(?:public|private|protected)\s*:\s*)?(?:(?:virtual|static|inline)\s+)*(?P<return>[\w:\s<>,*&]+?)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*(?:const\s*)?(?:noexcept\s*)?\{", re.MULTILINE)
    candidates = list(pattern.finditer(clean))
    candidates = [m for m in candidates if m.group("name") not in {"if", "for", "while", "switch", "catch"}]
    ranges = _class_ranges(clean)
    solution_candidates = [m for m in candidates if any(start <= m.start("name") < end and name == "Solution" for start, end, name in ranges)]
    if solution_candidates:
        candidates = solution_candidates
    if not candidates:
        return _result("cpp", "stdin", None, ["暂未识别出常见 C++ 函数签名，请手动选择模式并填写函数入口。"])
    candidate = candidates[0]
    if len(candidates) > 1:
        warnings.append(f"检测到多个函数，暂选 {candidate.group('name')}；请确认题目指定入口。")
    class_name = next((name for start, end, name in ranges if start <= candidate.start("name") < end), "")
    return_raw = candidate.group("return").strip()
    returns = _cpp_type(return_raw)
    if returns is None:
        returns = "int"
        warnings.append(f"暂不支持自动识别返回类型 {return_raw}，暂填 int，请手动核对。")
    params = []
    for index, raw in enumerate(_split_params(candidate.group("params"))):
        if raw == "void":
            continue
        raw = raw.split("=", 1)[0].strip()
        match = re.fullmatch(r"(.+?)([A-Za-z_]\w*)", raw)
        if not match:
            warnings.append(f"第 {index + 1} 个参数格式未识别，请手动填写。")
            params.append({"name": f"arg{index}", "type": "int"})
            continue
        raw_type, name = match.groups()
        typ = _cpp_type(raw_type.strip())
        if typ is None or typ == "void":
            typ = "int"
            warnings.append(f"参数 {name} 的类型 {raw_type.strip()} 暂未识别，暂填 int，请手动核对。")
        if "int64_t" in raw_type and "vector" in raw_type:
            warnings.append(f"参数 {name} 使用 int64_t 容器别名，需核对它与运行环境 long long 容器的兼容性。")
        if re.search(r"vector\s*<\s*float\s*>", raw_type):
            warnings.append(f"参数 {name} 使用 vector<float>，当前浮点容器模板采用 vector<double>，请核对实际类型兼容性。")
        params.append({"name": name, "type": typ})
    signature = {"name": candidate.group("name"), "class_name": class_name, "parameters": params, "returns": returns, "capture_argument": 0}
    if returns == "void":
        warnings.append("原地修改题默认检查第一个参数，必要时修改 capture_argument。")
    warnings.append("C++ 签名为辅助识别，请核对参数类型与函数入口。")
    return _result("cpp", "function", signature, warnings)


def infer(language: str, code: str) -> dict[str, Any]:
    if language not in {"cpp", "python"}:
        raise ValueError("只支持 C++ 与 Python。")
    if not isinstance(code, str) or len(code) > 100000:
        raise ValueError("参考代码长度不能超过 100000 字符。")
    return _infer_python(code) if language == "python" else _infer_cpp(code)
