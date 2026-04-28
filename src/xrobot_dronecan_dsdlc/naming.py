"""生成 C++ 和 XRobot 模块文件时使用的命名转换辅助函数。

Name conversion helpers for generated C++ and XRobot module files.
"""

from __future__ import annotations

import re


_WORD_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)")
_CPP_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CPP_KEYWORDS = {
    "alignas",
    "alignof",
    "and",
    "and_eq",
    "asm",
    "auto",
    "bitand",
    "bitor",
    "bool",
    "break",
    "case",
    "catch",
    "char",
    "char16_t",
    "char32_t",
    "class",
    "compl",
    "const",
    "constexpr",
    "const_cast",
    "continue",
    "decltype",
    "default",
    "delete",
    "do",
    "double",
    "dynamic_cast",
    "else",
    "enum",
    "explicit",
    "export",
    "extern",
    "false",
    "float",
    "for",
    "friend",
    "goto",
    "if",
    "inline",
    "int",
    "long",
    "mutable",
    "namespace",
    "new",
    "noexcept",
    "not",
    "not_eq",
    "nullptr",
    "operator",
    "or",
    "or_eq",
    "private",
    "protected",
    "public",
    "register",
    "reinterpret_cast",
    "return",
    "short",
    "signed",
    "sizeof",
    "static",
    "static_assert",
    "static_cast",
    "struct",
    "switch",
    "template",
    "this",
    "thread_local",
    "throw",
    "true",
    "try",
    "typedef",
    "typeid",
    "typename",
    "union",
    "unsigned",
    "using",
    "virtual",
    "void",
    "volatile",
    "wchar_t",
    "while",
    "xor",
    "xor_eq",
}


def split_words(value: str) -> list[str]:
    words: list[str] = []
    for chunk in re.split(r"[^A-Za-z0-9]+", value):
        if not chunk:
            continue
        words.extend(match.group(0) for match in _WORD_RE.finditer(chunk))
    return words or [value]


def to_snake(value: str) -> str:
    return "_".join(word.lower() for word in split_words(value))


def to_pascal(value: str) -> str:
    return "".join(word[:1].upper() + word[1:] for word in split_words(value))


def sanitize_identifier(value: str) -> str:
    out = re.sub(r"\W", "_", value)
    if not out or out[0].isdigit():
        out = "_" + out
    return out


def is_cpp_identifier(value: str) -> bool:
    if not _CPP_IDENTIFIER_RE.fullmatch(value) or value in _CPP_KEYWORDS:
        return False
    return not (value.startswith("_") or "__" in value)


def is_cpp_qualified_identifier(value: str) -> bool:
    return all(is_cpp_identifier(part) for part in value.split("::"))


def namespace_components(full_name: str) -> list[str]:
    return [sanitize_identifier(part) for part in full_name.split(".")[:-1]]


def short_type_name(full_name: str) -> str:
    return sanitize_identifier(full_name.split(".")[-1])


def type_alias_name(full_name: str, suffix: str = "") -> str:
    return "".join(to_pascal(part) for part in full_name.split(".")) + suffix

