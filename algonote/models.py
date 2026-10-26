from __future__ import annotations

import json
import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Language = Literal["cpp", "python"]
TYPES = {t + suffix for t in ("int", "int64", "float", "bool", "str", "char") for suffix in ("", "[]", "[][]")} | {"ListNode", "TreeNode"}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")


class Parameter(BaseModel):
    name: str
    type: str

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not IDENTIFIER.fullmatch(value):
            raise ValueError("参数名称必须是有效的代码标识符")
        return value

    @field_validator("type")
    @classmethod
    def valid_type(cls, value: str) -> str:
        if value not in TYPES:
            raise ValueError("不支持这个参数类型，请选择表单中的类型")
        return value


class Signature(BaseModel):
    name: str
    class_name: str = "Solution"
    parameters: list[Parameter] = Field(default_factory=list, max_length=16)
    returns: str = "int"
    capture_argument: int = Field(default=0, ge=0, le=15)

    @field_validator("name", "class_name")
    @classmethod
    def valid_identifier(cls, value: str, info) -> str:
        if info.field_name == "class_name" and value == "":
            return value
        if not IDENTIFIER.fullmatch(value):
            raise ValueError("类名或函数名不是有效的代码标识符")
        return value

    @field_validator("returns")
    @classmethod
    def valid_return(cls, value: str) -> str:
        if value not in TYPES | {"void"}:
            raise ValueError("不支持这个返回值类型")
        return value

    @model_validator(mode="after")
    def unique_parameters(self):
        if len({p.name for p in self.parameters}) != len(self.parameters):
            raise ValueError("参数名称不能重复")
        if self.returns == "void" and self.capture_argument >= len(self.parameters):
            raise ValueError("无返回值函数必须指定一个实际存在的参数来检查修改结果")
        return self


class TestCase(BaseModel):
    name: str = Field(default="测试", max_length=100)
    input: Any
    expected: Any
    sample: bool = True

    @model_validator(mode="after")
    def finite_json(self):
        for value in (self.input, self.expected):
            try:
                encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
            except (ValueError, TypeError, RecursionError) as exc:
                raise ValueError("测试数据必须是合法 JSON，不能含 NaN 或 Infinity") from exc
            if len(encoded.encode("utf-8")) > 100_000:
                raise ValueError("单条测试数据过大（上限 100 KB）")
        return self


class ProblemInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(min_length=1, max_length=160)
    source: Literal["leetcode", "nowcoder"] = "leetcode"
    source_url: str = Field(default="", max_length=2000)
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    tags: list[str] = Field(default_factory=list, max_length=16)
    statement: str = Field(min_length=1, max_length=100_000)
    mode: Literal["function", "stdin"] = "function"
    references: dict[Language, str] = Field(default_factory=dict)
    templates: dict[Language, str] = Field(default_factory=dict)
    signature: Signature | None = None
    comparison: Literal["exact", "unordered", "tokens", "float"] = "exact"
    tests: list[TestCase] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=30_000)
    mastery: Literal["new", "review", "mastered"] = "new"

    @field_validator("title", "statement")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("题目名称和题面不能为空")
        return value

    @field_validator("source_url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        if value and (urlsplit(value).scheme not in ("http", "https") or not urlsplit(value).hostname):
            raise ValueError("原题链接需要使用 http:// 或 https://")
        return value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(v.strip()[:40] for v in values if v.strip()))

    @field_validator("references", "templates")
    @classmethod
    def bounded_code(cls, values: dict[str, str]) -> dict[str, str]:
        if any(len(code) > 60_000 for code in values.values()):
            raise ValueError("单份代码长度不能超过 60000 字符")
        return values

    @model_validator(mode="after")
    def validate_problem(self):
        if not any(code.strip() for code in self.references.values()):
            raise ValueError("请至少提供一份 C++ 或 Python 参考答案")
        if self.mode == "function":
            if self.signature is None:
                raise ValueError("函数题需要填写函数签名，可先使用识别代码功能")
            for case in self.tests:
                if not isinstance(case.input, list) or len(case.input) != len(self.signature.parameters):
                    raise ValueError(f"{case.name} 的输入需要是包含全部函数参数的 JSON 数组")
            if self.comparison == "tokens":
                raise ValueError("按空白分隔比较用于标准输入输出题")
        else:
            self.signature = None
            for case in self.tests:
                if not isinstance(case.input, str) or not isinstance(case.expected, str):
                    raise ValueError("标准输入输出题的输入与预期输出需要使用文本")
        return self


class ProblemUpdate(ProblemInput):
    revision: int = Field(ge=1)


class InferRequest(BaseModel):
    language: Language
    code: str = Field(min_length=1, max_length=60_000)


class ExplanationRequest(BaseModel):
    language: Language
    revision: int = Field(ge=1)


class ManualExplanation(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)
    revision: int = Field(ge=1)


class DraftInput(BaseModel):
    code: str = Field(default="", max_length=60_000)
    problem_revision: int = Field(ge=1)
    expected_updated_at: str | None = Field(default=None, max_length=100)


class RunRequest(BaseModel):
    language: Language
    code: str = Field(default="", max_length=60_000)
    scope: Literal["samples", "all"] = "samples"
    purpose: Literal["practice", "reference"] = "practice"
    revision: int = Field(ge=1)


class Settings(BaseModel):
    data_dir: str = "data"
    notebook_dir: str = "notebook"
    token: str = ""
    runner_image: str = "algonote-runner:0.1"
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    @classmethod
    def from_env(cls) -> "Settings":
        import os
        from dotenv import load_dotenv
        load_dotenv()
        return cls(**{k: os.environ.get("ALGONOTE_" + k.upper(), field.default) for k, field in cls.model_fields.items()})
