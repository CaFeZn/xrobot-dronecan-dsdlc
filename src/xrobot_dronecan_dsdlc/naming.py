"""生成 C++ 和 XRobot 模块文件时使用的命名转换辅助函数。

Name conversion helpers for generated C++ and XRobot module files.
"""

from __future__ import annotations

import re


_WORD_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)")


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


def namespace_components(full_name: str) -> list[str]:
    return [sanitize_identifier(part) for part in full_name.split(".")[:-1]]


def short_type_name(full_name: str) -> str:
    return sanitize_identifier(full_name.split(".")[-1])


def type_alias_name(full_name: str, suffix: str = "") -> str:
    return "".join(to_pascal(part) for part in full_name.split(".")) + suffix

