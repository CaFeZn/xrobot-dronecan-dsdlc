"""DroneCAN DSDL 类型的 C++ 代码生成。

C++ code generation for DroneCAN DSDL types.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from dronecan.dsdl import ArrayType, CompoundType, Constant, Field, PrimitiveType, Type, VoidType

from .dsdl import type_max_payload_bytes
from .naming import namespace_components, short_type_name


def _bits_to_bytes(bits: int) -> int:
    return (bits + 7) // 8


def _length_bits(max_size: int) -> int:
    return max_size.bit_length()


def _indent(text: str, level: int = 1) -> str:
    pad = "  " * level
    return "\n".join(pad + line if line else line for line in text.splitlines())


def _hex64(value: int) -> str:
    return f"0x{value:016X}ULL"


def _uint_literal(value: int, bits: int) -> str:
    if bits > 32:
        return f"{value}ULL"
    return f"{value}U"


@dataclass(frozen=True)
class StructSpec:
    compound: CompoundType
    name: str
    fields: list[Field]
    constants: list[Constant]
    is_union: bool
    max_bitlen: int
    min_bitlen: int
    service_part: str | None = None

    @property
    def max_payload_bytes(self) -> int:
        return _bits_to_bytes(self.max_bitlen)


class CppTypeRenderer:
    def __init__(self, root_namespace: str, types: Iterable[CompoundType]):
        self.root_namespace = root_namespace
        self.types = list(types)

    def render(self) -> str:
        parts = [
            "#pragma once",
            "",
            "#include <algorithm>",
            "#include <array>",
            "#include <cstddef>",
            "#include <cstdint>",
            "#include <cstring>",
            "",
            'extern "C"',
            "{",
            '#include "canard.h"',
            "}",
            "",
            f"namespace {self.root_namespace}",
            "{",
            self._render_detail_helpers(),
            "}",
            "",
        ]
        for compound in self.types:
            parts.append(self._render_compound(compound))
            parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    def qualified_struct(self, compound: CompoundType, part: str | None = None) -> str:
        ns = "::".join([self.root_namespace, *namespace_components(compound.full_name)])
        return f"::{ns}::{self.struct_name(compound, part)}"

    @staticmethod
    def struct_name(compound: CompoundType, part: str | None = None) -> str:
        base = short_type_name(compound.full_name)
        if part == "request":
            return f"{base}Request"
        if part == "response":
            return f"{base}Response"
        return base

    def _render_detail_helpers(self) -> str:
        return _indent(
            """namespace detail
{
inline bool DecodeScalar(const CanardRxTransfer& transfer,
                         std::uint32_t bit_offset,
                         std::uint8_t bit_length,
                         bool is_signed,
                         void* out_value) noexcept
{
  return canardDecodeScalar(&transfer, bit_offset, bit_length, is_signed, out_value) == bit_length;
}

inline std::uint32_t PayloadBitLength(const CanardRxTransfer& transfer) noexcept
{
  return static_cast<std::uint32_t>(transfer.payload_len) * 8U;
}

template <typename T>
inline T Clamp(T value, T low, T high) noexcept
{
  return std::min(std::max(value, low), high);
}
}  // namespace detail""",
            0,
        )

    def _render_compound(self, compound: CompoundType) -> str:
        namespace = "::".join([self.root_namespace, *namespace_components(compound.full_name)])
        specs = self._struct_specs(compound)
        body: list[str] = [f"namespace {namespace}", "{"]
        for spec in specs:
            body.append(self._render_struct_decl(spec))
            body.append("")
        for spec in specs:
            body.append(self._render_struct_impl(spec))
            body.append("")
        body.append(f"}}  // namespace {namespace}")
        return "\n".join(body).rstrip()

    def _struct_specs(self, compound: CompoundType) -> list[StructSpec]:
        if compound.kind == CompoundType.KIND_MESSAGE:
            return [
                StructSpec(
                    compound=compound,
                    name=self.struct_name(compound),
                    fields=list(compound.fields),
                    constants=list(compound.constants),
                    is_union=compound.union,
                    max_bitlen=compound.get_max_bitlen(),
                    min_bitlen=compound.get_min_bitlen(),
                )
            ]
        return [
            StructSpec(
                compound=compound,
                name=self.struct_name(compound, "request"),
                fields=list(compound.request_fields),
                constants=list(compound.request_constants),
                is_union=compound.request_union,
                max_bitlen=compound.get_max_bitlen_request(),
                min_bitlen=compound.get_min_bitlen_request(),
                service_part="request",
            ),
            StructSpec(
                compound=compound,
                name=self.struct_name(compound, "response"),
                fields=list(compound.response_fields),
                constants=list(compound.response_constants),
                is_union=compound.response_union,
                max_bitlen=compound.get_max_bitlen_response(),
                min_bitlen=compound.get_min_bitlen_response(),
                service_part="response",
            ),
        ]

    def _render_struct_decl(self, spec: StructSpec) -> str:
        lines = [f"struct {spec.name}", "{"]
        lines.append(f"  static constexpr const char* kFullName = \"{spec.compound.full_name}\";")
        if spec.compound.default_dtid is not None:
            lines.append(f"  static constexpr std::uint16_t kDataTypeId = {spec.compound.default_dtid}U;")
        lines.append(f"  static constexpr std::uint64_t kDataTypeSignature = {_hex64(spec.compound.get_data_type_signature())};")
        lines.append(f"  static constexpr std::size_t kMaxBitLength = {spec.max_bitlen}U;")
        lines.append(f"  static constexpr std::size_t kMinBitLength = {spec.min_bitlen}U;")
        lines.append(f"  static constexpr std::size_t kMaxPayloadSize = {spec.max_payload_bytes}U;")
        if spec.service_part:
            lines.append(f"  static constexpr bool kIsService = true;")
            lines.append(f"  static constexpr const char* kServicePart = \"{spec.service_part}\";")
        else:
            lines.append(f"  static constexpr bool kIsService = false;")
        if spec.is_union:
            tag_bits = max(len([f for f in spec.fields if f.name]) - 1, 1).bit_length()
            lines.append(f"  static constexpr std::uint8_t kUnionTagBitLength = {tag_bits}U;")
            lines.append("  std::uint8_t union_tag = 0U;")

        for const in spec.constants:
            rendered = self._render_constant(const)
            if rendered:
                lines.append(f"  {rendered}")

        for field in spec.fields:
            rendered = self._render_field_decl(field)
            if rendered:
                lines.append(f"  {rendered}")

        lines.extend(
            [
                "",
                f"  static std::size_t Encode(const {spec.name}& msg, std::uint8_t* buffer, std::size_t buffer_size, bool tao = true) noexcept;",
                f"  static bool EncodeTo(const {spec.name}& msg, std::uint8_t* buffer, std::size_t buffer_size, std::uint32_t& bit_offset, bool tao = true) noexcept;",
                f"  static bool Decode(const CanardRxTransfer& transfer, {spec.name}& out, bool tao = true) noexcept;",
                f"  static bool DecodeFrom(const CanardRxTransfer& transfer, std::uint32_t& bit_offset, {spec.name}& out, bool tao = true) noexcept;",
            ]
        )
        lines.append("};")
        return "\n".join(lines)

    def _render_constant(self, const: Constant) -> str | None:
        if const.type.category != Type.CATEGORY_PRIMITIVE:
            return None
        cpp_type = self._cpp_value_type(const.type)
        value = self._constant_value_literal(const)
        return f"static constexpr {cpp_type} {const.name} = {value};"

    def _constant_value_literal(self, const: Constant) -> str:
        primitive = const.type
        assert isinstance(primitive, PrimitiveType)
        if primitive.kind == PrimitiveType.KIND_BOOLEAN:
            return "true" if bool(const.value) else "false"
        if primitive.kind == PrimitiveType.KIND_FLOAT:
            suffix = "F" if primitive.bitlen <= 32 else ""
            return f"{float(const.value)!r}{suffix}"
        if primitive.kind == PrimitiveType.KIND_UNSIGNED_INT:
            return _uint_literal(int(const.value), primitive.bitlen)
        return str(int(const.value))

    def _render_field_decl(self, field: Field) -> str | None:
        if field.type.category == Type.CATEGORY_VOID:
            return None
        if field.type.category == Type.CATEGORY_ARRAY:
            array = field.type
            assert isinstance(array, ArrayType)
            elem = self._cpp_value_type(array.value_type)
            if array.mode == ArrayType.MODE_DYNAMIC:
                return f"std::array<{elem}, {array.max_size}U> {field.name}{{}}; std::size_t {field.name}_size = 0U;"
            return f"std::array<{elem}, {array.max_size}U> {field.name}{{}};"
        return f"{self._cpp_value_type(field.type)} {field.name}{{}};"

    def _render_struct_impl(self, spec: StructSpec) -> str:
        lines: list[str] = [
            f"inline std::size_t {spec.name}::Encode(const {spec.name}& msg, std::uint8_t* buffer, std::size_t buffer_size, bool tao) noexcept",
            "{",
            "  if ((buffer == nullptr) || (buffer_size < kMaxPayloadSize))",
            "  {",
            "    return 0U;",
            "  }",
            "  std::memset(buffer, 0, buffer_size);",
            "  std::uint32_t bit_offset = 0U;",
            "  if (!EncodeTo(msg, buffer, buffer_size, bit_offset, tao))",
            "  {",
            "    return 0U;",
            "  }",
            "  return static_cast<std::size_t>((bit_offset + 7U) / 8U);",
            "}",
            "",
            f"inline bool {spec.name}::Decode(const CanardRxTransfer& transfer, {spec.name}& out, bool tao) noexcept",
            "{",
            "  std::uint32_t bit_offset = 0U;",
            "  return DecodeFrom(transfer, bit_offset, out, tao);",
            "}",
            "",
            f"inline bool {spec.name}::EncodeTo(const {spec.name}& msg, std::uint8_t* buffer, std::size_t buffer_size, std::uint32_t& bit_offset, bool tao) noexcept",
            "{",
            "  (void)buffer_size;",
        ]
        lines.extend(_indent(self._render_encode_fields(spec), 1).splitlines())
        lines.append("  return true;")
        lines.append("}")
        lines.append("")
        lines.extend(
            [
                f"inline bool {spec.name}::DecodeFrom(const CanardRxTransfer& transfer, std::uint32_t& bit_offset, {spec.name}& out, bool tao) noexcept",
                "{",
                "  const std::uint32_t payload_bit_length = detail::PayloadBitLength(transfer);",
            ]
        )
        lines.extend(_indent(self._render_decode_fields(spec), 1).splitlines())
        lines.append("  return bit_offset <= payload_bit_length;")
        lines.append("}")
        return "\n".join(lines)

    def _render_encode_fields(self, spec: StructSpec) -> str:
        fields = [field for field in spec.fields if field.type.category != Type.CATEGORY_VOID]
        if not fields and not spec.is_union:
            return "(void)msg;\n(void)buffer;\n(void)tao;"
        if spec.is_union:
            tag_bits = max(len(fields) - 1, 1).bit_length()
            cases = [
                f"case {idx}U:\n{_indent(self._encode_field(field, is_tail=True), 1)}\n  break;"
                for idx, field in enumerate(fields)
            ]
            return "\n".join(
                [
                    "{",
                    f"  std::uint8_t tag = static_cast<std::uint8_t>(std::min<std::uint8_t>(msg.union_tag, {max(len(fields)-1, 0)}U));",
                    f"  canardEncodeScalar(buffer, bit_offset, {tag_bits}U, &tag);",
                    f"  bit_offset += {tag_bits}U;",
                    "  switch (tag)",
                    "  {",
                    _indent("\n".join(cases), 2),
                    "  default:",
                    "    break;",
                    "  }",
                    "}",
                ]
            )

        chunks = []
        for idx, field in enumerate(spec.fields):
            chunks.append(self._encode_field(field, is_tail=idx == len(spec.fields) - 1))
        return "\n".join(chunk for chunk in chunks if chunk)

    def _render_decode_fields(self, spec: StructSpec) -> str:
        fields = [field for field in spec.fields if field.type.category != Type.CATEGORY_VOID]
        if not fields and not spec.is_union:
            return "(void)out;\n(void)tao;"
        if spec.is_union:
            tag_bits = max(len(fields) - 1, 1).bit_length()
            cases = [
                f"case {idx}U:\n{_indent(self._decode_field(field, is_tail=True), 1)}\n  break;"
                for idx, field in enumerate(fields)
            ]
            return "\n".join(
                [
                    "{",
                    "  std::uint8_t tag = 0U;",
                    f"  if (!detail::DecodeScalar(transfer, bit_offset, {tag_bits}U, false, &tag))",
                    "  {",
                    "    return false;",
                    "  }",
                    f"  bit_offset += {tag_bits}U;",
                    f"  if (tag > {max(len(fields)-1, 0)}U)",
                    "  {",
                    "    return false;",
                    "  }",
                    "  out.union_tag = tag;",
                    "  switch (tag)",
                    "  {",
                    _indent("\n".join(cases), 2),
                    "  default:",
                    "    return false;",
                    "  }",
                    "}",
                ]
            )

        chunks = []
        for idx, field in enumerate(spec.fields):
            chunks.append(self._decode_field(field, is_tail=idx == len(spec.fields) - 1))
        return "\n".join(chunk for chunk in chunks if chunk)

    def _encode_field(self, field: Field, is_tail: bool) -> str:
        if field.type.category == Type.CATEGORY_VOID:
            void = field.type
            assert isinstance(void, VoidType)
            return f"bit_offset += {void.bitlen}U;"
        if field.type.category == Type.CATEGORY_ARRAY:
            return self._encode_array(field, field.type, is_tail)
        return self._encode_value(field.type, f"msg.{field.name}")

    def _decode_field(self, field: Field, is_tail: bool) -> str:
        if field.type.category == Type.CATEGORY_VOID:
            void = field.type
            assert isinstance(void, VoidType)
            return f"bit_offset += {void.bitlen}U;"
        if field.type.category == Type.CATEGORY_ARRAY:
            return self._decode_array(field, field.type, is_tail)
        return self._decode_value(field.type, f"out.{field.name}")

    def _encode_array(self, field: Field, array: ArrayType, is_tail: bool) -> str:
        elem_ref = f"msg.{field.name}[i]"
        if array.mode == ArrayType.MODE_DYNAMIC:
            len_bits = _length_bits(array.max_size)
            write_len = f"!(tao && {str(is_tail).lower()})"
            return "\n".join(
                [
                    "{",
                    f"  const std::size_t count = std::min<std::size_t>(msg.{field.name}_size, {array.max_size}U);",
                    f"  if ({write_len})",
                    "  {",
                    f"    std::uint64_t encoded_length = static_cast<std::uint64_t>(count);",
                    f"    canardEncodeScalar(buffer, bit_offset, {len_bits}U, &encoded_length);",
                    f"    bit_offset += {len_bits}U;",
                    "  }",
                    "  for (std::size_t i = 0U; i < count; ++i)",
                    "  {",
                    _indent(self._encode_value(array.value_type, elem_ref), 2),
                    "  }",
                    "}",
                ]
            )
        return "\n".join(
            [
                "{",
                f"  for (std::size_t i = 0U; i < {array.max_size}U; ++i)",
                "  {",
                _indent(self._encode_value(array.value_type, elem_ref), 2),
                "  }",
                "}",
            ]
        )

    def _decode_array(self, field: Field, array: ArrayType, is_tail: bool) -> str:
        elem_ref = f"out.{field.name}[i]"
        if array.mode == ArrayType.MODE_DYNAMIC:
            len_bits = _length_bits(array.max_size)
            elem_bits = array.value_type.get_max_bitlen()
            read_len_lines = [
                f"std::size_t count = 0U;",
                f"if (tao && {str(is_tail).lower()})",
                "{",
                f"  const std::uint32_t remaining_bits = (payload_bit_length > bit_offset) ? (payload_bit_length - bit_offset) : 0U;",
                f"  count = std::min<std::size_t>({array.max_size}U, remaining_bits / {max(elem_bits, 1)}U);",
                "}",
                "else",
                "{",
                "  std::uint64_t encoded_length = 0U;",
                f"  if (!detail::DecodeScalar(transfer, bit_offset, {len_bits}U, false, &encoded_length))",
                "  {",
                "    return false;",
                "  }",
                f"  bit_offset += {len_bits}U;",
                f"  if (encoded_length > {array.max_size}U)",
                "  {",
                "    return false;",
                "  }",
                "  count = static_cast<std::size_t>(encoded_length);",
                "}",
                f"out.{field.name}_size = count;",
            ]
            return "\n".join(
                [
                    "{",
                    _indent("\n".join(read_len_lines), 1),
                    "  for (std::size_t i = 0U; i < count; ++i)",
                    "  {",
                    _indent(self._decode_value(array.value_type, elem_ref), 2),
                    "  }",
                    "}",
                ]
            )
        return "\n".join(
            [
                "{",
                f"  for (std::size_t i = 0U; i < {array.max_size}U; ++i)",
                "  {",
                _indent(self._decode_value(array.value_type, elem_ref), 2),
                "  }",
                "}",
            ]
        )

    def _encode_value(self, type_obj: Type, expr: str) -> str:
        if type_obj.category == Type.CATEGORY_PRIMITIVE:
            primitive = type_obj
            assert isinstance(primitive, PrimitiveType)
            return self._encode_primitive(primitive, expr)
        if type_obj.category == Type.CATEGORY_COMPOUND:
            compound = type_obj
            assert isinstance(compound, CompoundType)
            return f"if (!{self.qualified_struct(compound)}::EncodeTo({expr}, buffer, buffer_size, bit_offset, tao))\n{{\n  return false;\n}}"
        raise TypeError(f"Unsupported value type: {type_obj}")

    def _decode_value(self, type_obj: Type, expr: str) -> str:
        if type_obj.category == Type.CATEGORY_PRIMITIVE:
            primitive = type_obj
            assert isinstance(primitive, PrimitiveType)
            return self._decode_primitive(primitive, expr)
        if type_obj.category == Type.CATEGORY_COMPOUND:
            compound = type_obj
            assert isinstance(compound, CompoundType)
            return f"if (!{self.qualified_struct(compound)}::DecodeFrom(transfer, bit_offset, {expr}, tao))\n{{\n  return false;\n}}"
        raise TypeError(f"Unsupported value type: {type_obj}")

    def _encode_primitive(self, primitive: PrimitiveType, expr: str) -> str:
        if primitive.kind == PrimitiveType.KIND_BOOLEAN:
            return "\n".join(
                [
                    "{",
                    f"  const bool value = ({expr} != false);",
                    "  canardEncodeScalar(buffer, bit_offset, 1U, &value);",
                    "  bit_offset += 1U;",
                    "}",
                ]
            )
        if primitive.kind == PrimitiveType.KIND_FLOAT:
            if primitive.bitlen == 16:
                return "\n".join(
                    [
                        "{",
                        f"  const std::uint16_t value = canardConvertNativeFloatToFloat16(static_cast<float>({expr}));",
                        "  canardEncodeScalar(buffer, bit_offset, 16U, &value);",
                        "  bit_offset += 16U;",
                        "}",
                    ]
                )
            if primitive.bitlen == 32:
                return "\n".join(
                    [
                        "{",
                        "  std::uint32_t value = 0U;",
                        f"  const float native = static_cast<float>({expr});",
                        "  std::memcpy(&value, &native, sizeof(value));",
                        "  canardEncodeScalar(buffer, bit_offset, 32U, &value);",
                        "  bit_offset += 32U;",
                        "}",
                    ]
                )
            return "\n".join(
                [
                    "{",
                    "  std::uint64_t value = 0U;",
                    f"  const double native = static_cast<double>({expr});",
                    "  std::memcpy(&value, &native, sizeof(value));",
                    "  canardEncodeScalar(buffer, bit_offset, 64U, &value);",
                    "  bit_offset += 64U;",
                    "}",
                ]
            )

        cpp_type = self._cpp_storage_type(primitive)
        lo, hi = primitive.value_range
        if primitive.cast_mode == PrimitiveType.CAST_MODE_SATURATED and primitive.bitlen < self._storage_bits(primitive):
            if primitive.kind == PrimitiveType.KIND_UNSIGNED_INT:
                value_expr = f"detail::Clamp<std::uint64_t>(static_cast<std::uint64_t>({expr}), {int(lo)}ULL, {int(hi)}ULL)"
            else:
                value_expr = f"detail::Clamp<std::int64_t>(static_cast<std::int64_t>({expr}), {int(lo)}LL, {int(hi)}LL)"
            assign = f"const {cpp_type} value = static_cast<{cpp_type}>({value_expr});"
        else:
            assign = f"const {cpp_type} value = static_cast<{cpp_type}>({expr});"
        return "\n".join(
            [
                "{",
                f"  {assign}",
                f"  canardEncodeScalar(buffer, bit_offset, {primitive.bitlen}U, &value);",
                f"  bit_offset += {primitive.bitlen}U;",
                "}",
            ]
        )

    def _decode_primitive(self, primitive: PrimitiveType, expr: str) -> str:
        if primitive.kind == PrimitiveType.KIND_BOOLEAN:
            return "\n".join(
                [
                    "{",
                    "  bool value = false;",
                    "  if (!detail::DecodeScalar(transfer, bit_offset, 1U, false, &value))",
                    "  {",
                    "    return false;",
                    "  }",
                    "  bit_offset += 1U;",
                    f"  {expr} = value;",
                    "}",
                ]
            )
        if primitive.kind == PrimitiveType.KIND_FLOAT:
            if primitive.bitlen == 16:
                return "\n".join(
                    [
                        "{",
                        "  std::uint16_t value = 0U;",
                        "  if (!detail::DecodeScalar(transfer, bit_offset, 16U, false, &value))",
                        "  {",
                        "    return false;",
                        "  }",
                        "  bit_offset += 16U;",
                        f"  {expr} = canardConvertFloat16ToNativeFloat(value);",
                        "}",
                    ]
                )
            if primitive.bitlen == 32:
                return "\n".join(
                    [
                        "{",
                        "  std::uint32_t value = 0U;",
                        "  if (!detail::DecodeScalar(transfer, bit_offset, 32U, false, &value))",
                        "  {",
                        "    return false;",
                        "  }",
                        "  bit_offset += 32U;",
                        "  float native = 0.0F;",
                        "  std::memcpy(&native, &value, sizeof(native));",
                        f"  {expr} = native;",
                        "}",
                    ]
                )
            return "\n".join(
                [
                    "{",
                    "  std::uint64_t value = 0U;",
                    "  if (!detail::DecodeScalar(transfer, bit_offset, 64U, false, &value))",
                    "  {",
                    "    return false;",
                    "  }",
                    "  bit_offset += 64U;",
                    "  double native = 0.0;",
                    "  std::memcpy(&native, &value, sizeof(native));",
                    f"  {expr} = native;",
                    "}",
                ]
            )

        cpp_type = self._cpp_storage_type(primitive)
        is_signed = "true" if primitive.kind == PrimitiveType.KIND_SIGNED_INT else "false"
        return "\n".join(
            [
                "{",
                f"  {cpp_type} value = 0;",
                f"  if (!detail::DecodeScalar(transfer, bit_offset, {primitive.bitlen}U, {is_signed}, &value))",
                "  {",
                "    return false;",
                "  }",
                f"  bit_offset += {primitive.bitlen}U;",
                f"  {expr} = value;",
                "}",
            ]
        )

    def _cpp_value_type(self, type_obj: Type) -> str:
        if type_obj.category == Type.CATEGORY_PRIMITIVE:
            primitive = type_obj
            assert isinstance(primitive, PrimitiveType)
            if primitive.kind == PrimitiveType.KIND_BOOLEAN:
                return "bool"
            if primitive.kind == PrimitiveType.KIND_FLOAT:
                return "double" if primitive.bitlen == 64 else "float"
            return self._cpp_storage_type(primitive)
        if type_obj.category == Type.CATEGORY_COMPOUND:
            compound = type_obj
            assert isinstance(compound, CompoundType)
            return self.qualified_struct(compound)
        if type_obj.category == Type.CATEGORY_ARRAY:
            array = type_obj
            assert isinstance(array, ArrayType)
            return self._cpp_value_type(array.value_type)
        raise TypeError(f"Unsupported field type: {type_obj}")

    @staticmethod
    def _storage_bits(primitive: PrimitiveType) -> int:
        if primitive.bitlen <= 8:
            return 8
        if primitive.bitlen <= 16:
            return 16
        if primitive.bitlen <= 32:
            return 32
        return 64

    def _cpp_storage_type(self, primitive: PrimitiveType) -> str:
        signed = primitive.kind == PrimitiveType.KIND_SIGNED_INT
        bits = self._storage_bits(primitive)
        prefix = "int" if signed else "uint"
        return f"std::{prefix}{bits}_t"


def render_types_header(root_namespace: str, types: Iterable[CompoundType]) -> str:
    return CppTypeRenderer(root_namespace, types).render()

