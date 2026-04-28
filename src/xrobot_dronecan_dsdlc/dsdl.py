"""DSDL 加载和依赖处理辅助函数。

DSDL loading and dependency helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import dronecan
from dronecan import dsdl
from dronecan.dsdl import ArrayType, CompoundType, Type


@dataclass(frozen=True)
class DsdlSet:
    types: tuple[CompoundType, ...]

    @property
    def by_name(self) -> dict[str, CompoundType]:
        return {item.full_name: item for item in self.types}

    def select_with_dependencies(self, names: Iterable[str]) -> list[CompoundType]:
        by_name = self.by_name
        requested = list(names)
        if not requested:
            requested = sorted(by_name)

        missing = [name for name in requested if name not in by_name]
        if missing:
            known = ", ".join(sorted(by_name)[:20])
            raise ValueError(f"Unknown DSDL type(s): {', '.join(missing)}. Known examples: {known}")

        seen: set[str] = set()
        ordered: list[CompoundType] = []

        def visit(compound: CompoundType) -> None:
            if compound.full_name in seen:
                return
            seen.add(compound.full_name)
            for dep in compound_dependencies(compound):
                visit(dep)
            ordered.append(compound)

        for name in requested:
            visit(by_name[name])
        return ordered


def builtin_dsdl_roots() -> list[Path]:
    root = Path(dronecan.__file__).resolve().parent / "dsdl_specs"
    return [path for path in root.iterdir() if path.is_dir()]


def load_dsdl(
    source_dirs: Iterable[Path],
    lookup_dirs: Iterable[Path] = (),
    include_builtin: bool = False,
) -> DsdlSet:
    sources = [Path(item).resolve() for item in source_dirs]
    lookups = [Path(item).resolve() for item in lookup_dirs]
    if include_builtin:
        lookups.extend(builtin_dsdl_roots())

    if not sources and include_builtin:
        sources = builtin_dsdl_roots()
        lookups = []

    if not sources:
        raise ValueError("At least one DSDL source directory is required, or use --builtin-dsdl")

    parsed = dsdl.parse_namespaces([str(item) for item in sources], [str(item) for item in lookups])
    return DsdlSet(tuple(parsed))


def compound_dependencies(compound: CompoundType) -> list[CompoundType]:
    deps: list[CompoundType] = []

    def add_from_type(type_obj: Type) -> None:
        if type_obj.category == Type.CATEGORY_COMPOUND:
            deps.append(type_obj)
        elif type_obj.category == Type.CATEGORY_ARRAY:
            array = type_obj
            assert isinstance(array, ArrayType)
            add_from_type(array.value_type)

    for field in fields_for(compound):
        add_from_type(field.type)
    return deps


def fields_for(compound: CompoundType):
    if compound.kind == CompoundType.KIND_MESSAGE:
        return list(compound.fields)
    return list(compound.request_fields) + list(compound.response_fields)


def type_max_payload_bytes(compound: CompoundType, part: str = "message") -> int:
    if compound.kind == CompoundType.KIND_MESSAGE:
        return (compound.get_max_bitlen() + 7) // 8
    if part == "request":
        return (compound.get_max_bitlen_request() + 7) // 8
    if part == "response":
        return (compound.get_max_bitlen_response() + 7) // 8
    raise ValueError(f"Invalid service part: {part}")

