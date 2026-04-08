from __future__ import annotations

import json
import re
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tqdm.rich import tqdm


USR_MAGIC = 5395285
RSZ_MAGIC = 5919570
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
ENUM_UNUSED_KEY = "value__"


class ParseError(RuntimeError):
    pass


def align(value: int, alignment: int) -> int:
    """Align integer value to the given boundary.

    @param value Current position.
    @param alignment Alignment size.
    @return Aligned position.
    """
    if alignment <= 1:
        return value
    return (value + (alignment - 1)) & ~(alignment - 1)


def murmur3_32(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    """Compute MurmurHash3 32-bit hash.

    @param data Input bytes.
    @param seed Hash seed.
    @return 32-bit hash.
    """
    c1 = 0xCC9E2D51
    c2 = 0x1B873593
    h1 = seed & 0xFFFFFFFF
    length = len(data)
    rounded_end = length & ~0x3

    for i in range(0, rounded_end, 4):
        k1 = int.from_bytes(data[i : i + 4], "little")
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1
        h1 = ((h1 << 13) | (h1 >> 19)) & 0xFFFFFFFF
        h1 = (h1 * 5 + 0xE6546B64) & 0xFFFFFFFF

    k1 = 0
    tail = data[rounded_end:]
    if len(tail) == 3:
        k1 ^= tail[2] << 16
    if len(tail) >= 2:
        k1 ^= tail[1] << 8
    if len(tail) >= 1:
        k1 ^= tail[0]
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1

    h1 ^= length
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85EBCA6B) & 0xFFFFFFFF
    h1 ^= h1 >> 13
    h1 = (h1 * 0xC2B2AE35) & 0xFFFFFFFF
    h1 ^= h1 >> 16
    return h1 & 0xFFFFFFFF


def format_guid_text_from_hex32(hex32: str) -> str:
    """Format 32 hex chars into canonical GUID text.

    @param hex32 32-hex string.
    @return Canonical GUID text.
    """
    h = hex32.lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def normalize_guid_candidate_text(text: str) -> str:
    """Normalize guid-like text when possible.

    @param text Source text.
    @return Normalized GUID text if recognized.
    """
    stripped = text.strip().strip("{}")
    compact = stripped.replace("-", "")
    if HEX32_RE.fullmatch(compact):
        return format_guid_text_from_hex32(compact)
    return text


class BinaryReader:
    """Read primitive values from a bytes buffer safely.

    @return Binary reader instance.
    """

    def __init__(self, data: bytes):
        """Initialize reader with raw bytes.

        @param data Source byte buffer.
        @return None.
        """
        self.data = data
        self.pos = 0

    @property
    def size(self) -> int:
        """Get total buffer size.

        @return Buffer size in bytes.
        """
        return len(self.data)

    def tell(self) -> int:
        """Get current cursor position.

        @return Current cursor offset.
        """
        return self.pos

    def seek(self, pos: int) -> None:
        """Move cursor to absolute position.

        @param pos Absolute target position.
        @return None.
        """
        if pos < 0 or pos > self.size:
            raise ParseError(f"seek out of range: {pos}")
        self.pos = pos

    def read(self, n: int) -> bytes:
        """Read bytes and advance cursor.

        @param n Number of bytes to read.
        @return Read bytes.
        """
        end = self.pos + n
        if end > self.size:
            raise ParseError(f"read out of range: {self.pos}+{n}")
        out = self.data[self.pos : end]
        self.pos = end
        return out

    def read_struct(self, fmt: str) -> Any:
        """Read and unpack one struct value.

        @param fmt Struct format string.
        @return Unpacked value.
        """
        size = struct.calcsize(fmt)
        raw = self.read(size)
        return struct.unpack(fmt, raw)[0]

    def read_u8(self) -> int:
        """Read unsigned 8-bit integer.

        @return Unsigned 8-bit value.
        """
        return self.read_struct("<B")

    def read_s8(self) -> int:
        """Read signed 8-bit integer.

        @return Signed 8-bit value.
        """
        return self.read_struct("<b")

    def read_u16(self) -> int:
        """Read unsigned 16-bit integer.

        @return Unsigned 16-bit value.
        """
        return self.read_struct("<H")

    def read_s16(self) -> int:
        """Read signed 16-bit integer.

        @return Signed 16-bit value.
        """
        return self.read_struct("<h")

    def read_u32(self) -> int:
        """Read unsigned 32-bit integer.

        @return Unsigned 32-bit value.
        """
        return self.read_struct("<I")

    def read_s32(self) -> int:
        """Read signed 32-bit integer.

        @return Signed 32-bit value.
        """
        return self.read_struct("<i")

    def read_u64(self) -> int:
        """Read unsigned 64-bit integer.

        @return Unsigned 64-bit value.
        """
        return self.read_struct("<Q")

    def read_s64(self) -> int:
        """Read signed 64-bit integer.

        @return Signed 64-bit value.
        """
        return self.read_struct("<q")

    def read_f32(self) -> float:
        """Read 32-bit float.

        @return Float32 value.
        """
        return self.read_struct("<f")

    def read_f64(self) -> float:
        """Read 64-bit float.

        @return Float64 value.
        """
        return self.read_struct("<d")

    def read_wstring_null(self, offset: int) -> str:
        """Read UTF-16 null-terminated string at absolute offset.

        @param offset Absolute offset in buffer.
        @return Decoded UTF-16 string.
        """
        if offset < 0 or offset >= self.size:
            return ""
        out: list[int] = []
        i = offset
        while i + 1 < self.size:
            ch = struct.unpack_from("<H", self.data, i)[0]
            i += 2
            if ch == 0:
                break
            out.append(ch)
        return normalize_guid_candidate_text("".join(chr(c) for c in out))


@dataclass
class FieldDef:
    name: str
    field_type: str
    original_type: str
    size: int
    align: int
    is_array: bool


@dataclass
class ClassDef:
    name: str
    crc: int
    fields: list[FieldDef]


class TypeDB:
    """Provide class/type metadata lookups.

    @return Type database instance.
    """

    def __init__(self, classes: dict[int, ClassDef]):
        """Initialize type database.

        @param classes Hash-indexed class definitions.
        @return None.
        """
        self.classes = classes
        self.name_to_hash = {c.name: h for h, c in classes.items()}

    @classmethod
    def load(cls, json_path: Path) -> "TypeDB":
        """Load type database from schema json.

        @param json_path Schema file path.
        @return Loaded TypeDB.
        """
        with json_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        classes: dict[int, ClassDef] = {}
        for key, value in raw.items():
            try:
                class_hash = int(key, 16)
            except ValueError:
                continue
            fields: list[FieldDef] = []
            for field in value.get("fields", []):
                fields.append(
                    FieldDef(
                        name=field.get("name", ""),
                        field_type=field.get("type", "Data"),
                        original_type=field.get("original_type", ""),
                        size=int(field.get("size", 0)),
                        align=int(field.get("align", 1)),
                        is_array=bool(field.get("array", False)),
                    )
                )
            crc_raw = value.get("crc", "0")
            crc = int(crc_raw, 16) if isinstance(crc_raw, str) else int(crc_raw)
            classes[class_hash] = ClassDef(
                name=value.get("name", ""), crc=crc, fields=fields
            )
        return cls(classes)

    def get_class(self, class_hash: int) -> ClassDef | None:
        """Lookup class definition by hash.

        @param class_hash Type hash.
        @return Class definition or None.
        """
        return self.classes.get(class_hash)

    def resolve_struct_hash(self, original_type: str) -> int | None:
        """Resolve struct type name to class hash.

        @param original_type Struct type name.
        @return Resolved class hash or None.
        """
        if not original_type:
            return None
        known = self.name_to_hash.get(original_type)
        if known is not None:
            return known
        maybe = murmur3_32(original_type.encode("utf-8"), seed=0xFFFFFFFF)
        if maybe in self.classes:
            return maybe
        return None


def read_len_utf16(reader: BinaryReader) -> str:
    """Read length-prefixed UTF-16 string from stream.

    @param reader Binary reader.
    @return Decoded UTF-16 string.
    """
    reader.seek(align(reader.tell(), 4))
    length = reader.read_u32()
    if length == 0:
        return ""
    remaining_chars = (reader.size - reader.tell()) // 2
    if length > remaining_chars or length > 2_000_000:
        return ""
    raw = reader.read(length * 2)
    decoded = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    return normalize_guid_candidate_text(decoded)


def read_len_c8(reader: BinaryReader) -> str:
    """Read length-prefixed UTF-8/C8 string from stream.

    @param reader Binary reader.
    @return Decoded UTF-8 string.
    """
    reader.seek(align(reader.tell(), 4))
    length = reader.read_u32()
    if length == 0:
        return ""
    remaining = reader.size - reader.tell()
    if length > remaining or length > 2_000_000:
        return ""
    raw = reader.read(length)
    decoded = raw.decode("utf-8", errors="replace").rstrip("\x00")
    return normalize_guid_candidate_text(decoded)


def read_guid_like(reader: BinaryReader) -> str:
    """Read 16-byte GUID-like payload and normalize text.

    @param reader Binary reader.
    @return Canonical GUID-like text.
    """
    raw = reader.read(16)
    try:
        return str(uuid.UUID(bytes_le=raw))
    except Exception:
        return format_guid_text_from_hex32(raw.hex())


class User3Exporter:
    """Export `.user.3` binary files into JSON trees.

    @return Exporter instance.
    """

    def __init__(
        self,
        user3_root: str | Path,
        schema_dir: str | Path,
        output_root: str | Path,
        tree_depth: int | str = "auto",
        exclude_regexes: list[str] | None = None,
        il2cpp_dump_path: str | Path = "",
    ):
        """Initialize exporter configuration and runtime state.

        @param user3_root Input root directory or single `.user.3` file.
        @param schema_dir Schema file path or directory containing schema json.
        @param output_root Output root directory.
        @param tree_depth Tree depth integer or `"auto"`.
        @param exclude_regexes Optional regex list used to exclude files.
        @param il2cpp_dump_path Required explicit path to `il2cpp_dump.json`.
        @return None.
        """
        self.user3_root = Path(user3_root)
        self.schema_dir = Path(schema_dir)
        self.output_root = Path(output_root)
        self.il2cpp_dump_path = Path(il2cpp_dump_path)
        if not self.il2cpp_dump_path.is_file():
            raise FileNotFoundError(
                f"il2cpp_dump.json not found: {self.il2cpp_dump_path}"
            )
        self.tree_depth = self._normalize_tree_depth(tree_depth)
        self.exclude_regexes = exclude_regexes or []
        self._exclude_patterns = [re.compile(p) for p in self.exclude_regexes]
        self.schema_path = self._resolve_schema_path(self.schema_dir)
        self.typedb = TypeDB.load(self.schema_path)
        self.enum_lookup = self._load_enum_lookup()
        self.class_field_fixed_types: dict[str, dict[str, str]] = {}
        self.serializable_to_fixed: dict[str, str] = {}
        self.generic_container_rules: dict[str, tuple[str, str]] = {}
        self.param_type_default_enum: dict[str, str] = {}
        self.enum_member_to_types: dict[str, list[str]] = {}

    @staticmethod
    def export_enums_internal(dump_json: dict) -> dict:
        """Extract internal enum tables from il2cpp dump.

        @param dump_json Parsed il2cpp dump object.
        @return Mapping: enum type -> {member -> value}.
        """
        enums_internal = {}
        for key, value in dump_json.items():
            if isinstance(value, dict):
                obj = dump_json[key]
                if "parent" in obj and obj["parent"] == "System.Enum":
                    val = {}
                    for _k, _v in obj["fields"].items():
                        if _k != ENUM_UNUSED_KEY:
                            val[_k] = _v["default"]
                    enums_internal[key] = val
        return enums_internal

    @staticmethod
    def export_enum_context_internal(dump_json: dict) -> dict:
        """Extract enum context metadata from il2cpp dump.

        @param dump_json Parsed il2cpp dump object.
        @return Context metadata for enum inference.
        """

        def extract_fixed_enum_type(type_name: Any) -> str | None:
            """Extract unique `*_Fixed` type from a type expression.

            @param type_name Type expression string.
            @return Extracted fixed enum type or None.
            """
            if not isinstance(type_name, str):
                return None
            matches = re.findall(r"[A-Za-z0-9_.]+_Fixed", type_name)
            if not matches:
                return None
            unique = list(dict.fromkeys(matches))
            if len(unique) == 1:
                return unique[0]
            return None

        class_field_fixed_types: dict[str, dict[str, str]] = {}
        serializable_to_fixed: dict[str, str] = {}
        generic_container_rules: dict[str, dict[str, str]] = {}

        for class_name, obj in dump_json.items():
            if not isinstance(class_name, str) or not isinstance(obj, dict):
                continue

            field_map: dict[str, str] = {}
            fields_obj = obj.get("fields")
            if isinstance(fields_obj, dict):
                for field_name, field_info in fields_obj.items():
                    if not isinstance(field_name, str) or not isinstance(
                        field_info, dict
                    ):
                        continue
                    fixed_type = extract_fixed_enum_type(field_info.get("type"))
                    if fixed_type is not None:
                        field_map[field_name] = fixed_type

            # RSZ is another authoritative source for field->type relationship.
            rsz_fields = obj.get("RSZ")
            if isinstance(rsz_fields, list):
                for rsz_field in rsz_fields:
                    if not isinstance(rsz_field, dict):
                        continue
                    potential_name = rsz_field.get("potential_name")
                    fixed_type = extract_fixed_enum_type(rsz_field.get("type"))
                    if isinstance(potential_name, str) and fixed_type is not None:
                        field_map.setdefault(potential_name, fixed_type)

            # Reflection metadata may carry element-type info for array fields.
            reflection_props = obj.get("reflection_properties")
            if isinstance(reflection_props, dict):
                for prop_name, prop_info in reflection_props.items():
                    if not isinstance(prop_name, str) or not isinstance(
                        prop_info, dict
                    ):
                        continue
                    fixed_type = extract_fixed_enum_type(prop_info.get("type"))
                    if fixed_type is not None:
                        field_map.setdefault(prop_name, fixed_type)

            if field_map:
                class_field_fixed_types[class_name] = field_map

            if class_name.endswith("_Serializable"):
                fixed_types: set[str] = set()
                methods_obj = obj.get("methods")
                if isinstance(methods_obj, dict):
                    for method in methods_obj.values():
                        if not isinstance(method, dict):
                            continue
                        params = method.get("params")
                        if isinstance(params, list):
                            for param in params:
                                if not isinstance(param, dict):
                                    continue
                                fixed_type = extract_fixed_enum_type(param.get("type"))
                                if fixed_type is not None:
                                    fixed_types.add(fixed_type)
                        returns = method.get("returns")
                        if isinstance(returns, dict):
                            fixed_type = extract_fixed_enum_type(returns.get("type"))
                            if fixed_type is not None:
                                fixed_types.add(fixed_type)
                if len(fixed_types) == 1:
                    serializable_to_fixed[class_name] = next(iter(fixed_types))

            generic_args = obj.get("generic_arg_types")
            if isinstance(generic_args, list) and len(generic_args) >= 2:
                enum_arg = generic_args[0]
                param_arg = generic_args[1]
                enum_type = (
                    extract_fixed_enum_type(enum_arg.get("type"))
                    if isinstance(enum_arg, dict)
                    else None
                )
                param_type = (
                    param_arg.get("type") if isinstance(param_arg, dict) else None
                )
                if isinstance(enum_type, str) and isinstance(param_type, str):
                    generic_container_rules[class_name] = {
                        "param_type": param_type,
                        "enum_type": enum_type,
                    }

        return {
            "class_field_fixed_types": class_field_fixed_types,
            "serializable_to_fixed": serializable_to_fixed,
            "generic_container_rules": generic_container_rules,
        }

    @staticmethod
    def _id_formatter(key: str, value: int) -> str:
        """Format enum mapping output text.

        @param key Enum member name.
        @param value Fixed enum id.
        @return Formatted display string.
        """
        return f"[{value}] {key}"

    @staticmethod
    def _to_u32(value: int) -> int:
        """Convert integer to unsigned 32-bit range.

        @param value Integer value.
        @return Unsigned 32-bit value.
        """
        return value & 0xFFFFFFFF

    @staticmethod
    def _to_s32(value: int) -> int:
        """Convert integer to signed 32-bit representation.

        @param value Integer value.
        @return Signed 32-bit value.
        """
        u32 = value & 0xFFFFFFFF
        return u32 if u32 < 0x80000000 else u32 - 0x100000000

    def _resolve_enums_internal_path(self) -> Path | None:
        """Resolve `Enums_Internal.json` location.

        @return Existing `Enums_Internal.json` path or None.
        """
        path = self.output_root / "Enums_Internal.json"
        return path if path.is_file() else None

    def _load_enum_lookup(self) -> dict[str, dict[int, tuple[str, int]]]:
        """Load fixed enum lookup tables from `Enums_Internal.json`.

        @return Mapping: fixed enum type -> {serialized/int32 variants -> (name, fixed_value)}.
        """
        source_path = self._resolve_enums_internal_path()
        if source_path is None:
            return {}
        try:
            with source_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return {}

        lookup: dict[str, dict[int, tuple[str, int]]] = {}
        if not isinstance(raw, dict):
            return lookup

        for enum_type, members in raw.items():
            if (
                not isinstance(enum_type, str)
                or not isinstance(members, dict)
                or not enum_type.endswith("_Fixed")
            ):
                continue
            value_map: dict[int, tuple[str, int]] = {}
            for member_name, raw_value in members.items():
                if not isinstance(member_name, str) or not isinstance(raw_value, int):
                    continue
                # Build map from Serializable-id (signed) to Fixed-id/name.
                serializable_value = self._to_s32(raw_value)
                entry = (member_name, raw_value)
                value_map[serializable_value] = entry
                # Some files may carry unsigned representation directly.
                value_map[self._to_u32(raw_value)] = entry
            if value_map:
                lookup[enum_type] = value_map
        return lookup

    def _resolve_il2cpp_dump_path(self) -> Path | None:
        """Resolve `il2cpp_dump.json` path from input root.

        @return Existing il2cpp dump path or None.
        """
        return self.il2cpp_dump_path if self.il2cpp_dump_path.is_file() else None

    def _ensure_internal_metadata_files(self) -> None:
        """Generate `Enums_Internal.json` under output root from required il2cpp dump.

        @return None.
        """
        dump_path = self._resolve_il2cpp_dump_path()
        if dump_path is None:
            raise FileNotFoundError(
                f"il2cpp_dump.json not found: {self.il2cpp_dump_path}"
            )
        try:
            with dump_path.open("r", encoding="utf-8") as f:
                il2cpp_dump = json.load(f)
        except Exception as exc:
            raise ParseError(f"failed to read il2cpp dump: {dump_path}") from exc

        self.output_root.mkdir(parents=True, exist_ok=True)
        enums_out = self.output_root / "Enums_Internal.json"
        enums_internal = self.export_enums_internal(il2cpp_dump)
        with enums_out.open("w", encoding="utf-8") as f:
            json.dump(enums_internal, f, ensure_ascii=False, indent=2)

    def _rebuild_enum_member_index(self) -> None:
        """Build reverse index: enum member name -> possible fixed enum types."""
        self.enum_member_to_types = {}
        for enum_type, value_map in self.enum_lookup.items():
            if not isinstance(enum_type, str) or not isinstance(value_map, dict):
                continue
            for member_name, _entry in value_map.values():
                if not isinstance(member_name, str):
                    continue
                types = self.enum_member_to_types.setdefault(member_name, [])
                if enum_type not in types:
                    types.append(enum_type)

    def _infer_enum_type_from_member_and_value(
        self, member_name: str, value: int
    ) -> str | None:
        """Infer enum type from member name and concrete numeric value."""
        candidates = self.enum_member_to_types.get(member_name)
        if not candidates:
            return None
        matched: list[str] = []
        for enum_type in candidates:
            value_map = self.enum_lookup.get(enum_type)
            if value_map is None:
                continue
            if (
                value in value_map
                or self._to_s32(value) in value_map
                or self._to_u32(value) in value_map
            ):
                matched.append(enum_type)
        if len(matched) == 1:
            return matched[0]
        return None

    def _apply_enum_context(self, raw: dict) -> None:
        """Apply parsed enum context to in-memory indices.

        @param raw Enum context object extracted from il2cpp dump.
        @return None.
        """
        self.class_field_fixed_types = {}
        self.serializable_to_fixed = {}
        self.generic_container_rules = {}
        self.param_type_default_enum = {}

        class_field_fixed_types = raw.get("class_field_fixed_types")
        if isinstance(class_field_fixed_types, dict):
            for cls_name, field_map in class_field_fixed_types.items():
                if not isinstance(cls_name, str) or not isinstance(field_map, dict):
                    continue
                cleaned: dict[str, str] = {}
                for field_name, enum_type in field_map.items():
                    if (
                        isinstance(field_name, str)
                        and isinstance(enum_type, str)
                        and enum_type.endswith("_Fixed")
                    ):
                        cleaned[field_name] = enum_type
                if cleaned:
                    self.class_field_fixed_types[cls_name] = cleaned

        serializable_to_fixed = raw.get("serializable_to_fixed")
        if isinstance(serializable_to_fixed, dict):
            for serializable_name, fixed_name in serializable_to_fixed.items():
                if (
                    isinstance(serializable_name, str)
                    and isinstance(fixed_name, str)
                    and fixed_name.endswith("_Fixed")
                ):
                    self.serializable_to_fixed[serializable_name] = fixed_name

        generic_container_rules = raw.get("generic_container_rules")
        param_to_enum_sets: dict[str, set[str]] = {}
        if isinstance(generic_container_rules, dict):
            for container_name, rule in generic_container_rules.items():
                if not isinstance(container_name, str) or not isinstance(rule, dict):
                    continue
                param_type = rule.get("param_type")
                enum_type = rule.get("enum_type")
                if (
                    isinstance(param_type, str)
                    and isinstance(enum_type, str)
                    and enum_type.endswith("_Fixed")
                ):
                    self.generic_container_rules[container_name] = (
                        param_type,
                        enum_type,
                    )
                    param_to_enum_sets.setdefault(param_type, set()).add(enum_type)

        for param_type, enum_types in param_to_enum_sets.items():
            if len(enum_types) == 1:
                self.param_type_default_enum[param_type] = next(iter(enum_types))

    def _load_enum_context_from_il2cpp_dump(self) -> bool:
        """Load enum context directly from il2cpp dump.

        @return True when context loading succeeds.
        """
        dump_path = self._resolve_il2cpp_dump_path()
        if dump_path is None:
            return False
        try:
            with dump_path.open("r", encoding="utf-8") as f:
                il2cpp_dump = json.load(f)
        except Exception:
            return False
        context = self.export_enum_context_internal(il2cpp_dump)
        self._apply_enum_context(context)
        return True

    def _ensure_enum_lookup(self) -> None:
        """Validate enum/context readiness and print warnings.

        @return None.
        """
        if self.enum_lookup:
            self._rebuild_enum_member_index()
            return
        self.enum_lookup = self._load_enum_lookup()
        self._rebuild_enum_member_index()
        if not self.enum_lookup:
            source = str(self.output_root / "Enums_Internal.json")
            print(
                f"[warn] Enums_Internal not loaded, enum value formatting disabled (source: {source})"
            )
        if not self.class_field_fixed_types and not self.serializable_to_fixed:
            context_source = str(self._resolve_il2cpp_dump_path() or "not found")
            print(
                "[warn] Enum context not loaded, enum conversion may be incomplete "
                f"(source: {context_source})"
            )

    def _fixed_type_candidates(self, type_name: str) -> list[str]:
        """Generate candidate fixed enum type names.

        @param type_name Source type name.
        @return Candidate fixed enum type names.
        """
        candidates = [type_name]
        if type_name.endswith("_Serializable"):
            candidates.append(f"{type_name[:-13]}_Fixed")
        if "Serializable" in type_name:
            candidates.append(type_name.replace("Serializable", "Fixed"))
        out: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                out.append(candidate)
        return out

    def _normalize_to_fixed_enum_type(self, type_name: str) -> str:
        """Normalize type name to known fixed enum type when possible.

        @param type_name Source type name.
        @return Normalized fixed enum type, or original value.
        """
        if not type_name or not self.enum_lookup:
            return type_name
        direct = self.serializable_to_fixed.get(type_name)
        if direct is not None and direct in self.enum_lookup:
            return direct
        for candidate in self._fixed_type_candidates(type_name):
            if candidate in self.enum_lookup:
                return candidate
        return type_name

    def _format_enum_value(self, fixed_enum_type: str, value: int) -> Any:
        """Map numeric value to formatted fixed enum label.

        @param fixed_enum_type Fixed enum type name.
        @param value Numeric value.
        @return Formatted enum label or original value.
        """
        if not fixed_enum_type or not self.enum_lookup:
            return value
        value_map = self.enum_lookup.get(fixed_enum_type)
        if value_map is None:
            return value
        matched = value_map.get(value)
        if matched is None:
            matched = value_map.get(self._to_s32(value))
        if matched is None:
            matched = value_map.get(self._to_u32(value))
        if matched is None:
            return value
        member_name, fixed_value = matched
        return self._id_formatter(member_name, fixed_value)

    @staticmethod
    def _looks_like_class_name(text: str) -> bool:
        """Check whether a dict key looks like a class name.

        @param text Object key text.
        @return True when key likely is class name.
        """
        return "." in text and not text.startswith("_")

    @staticmethod
    def _class_name_variants(class_name: str | None) -> list[str]:
        """Build class-name aliases used across dumps.

        @param class_name Class name.
        @return Alias variants (`cData` / `cParam`).
        """
        if not class_name:
            return []
        variants = [class_name]
        if class_name.endswith(".cData"):
            variants.append(f"{class_name[:-6]}.cParam")
        elif class_name.endswith(".cParam"):
            variants.append(f"{class_name[:-7]}.cData")
        return variants

    def _resolve_field_enum_hint(
        self, current_class: str | None, field_name: str
    ) -> str | None:
        """Resolve fixed enum type hint for a field.

        @param current_class Current class context.
        @param field_name Field name.
        @return Fixed enum type hint or None.
        """
        for class_variant in self._class_name_variants(current_class):
            class_fields = self.class_field_fixed_types.get(class_variant, {})
            fixed_field_type = class_fields.get(field_name)
            if fixed_field_type:
                return fixed_field_type
        return None

    def _resolve_class_default_enum(self, class_name: str | None) -> str | None:
        """Resolve default enum type for generic param container class.

        @param class_name Class name.
        @return Default fixed enum type or None.
        """
        for class_variant in self._class_name_variants(class_name):
            enum_type = self.param_type_default_enum.get(class_variant)
            if enum_type is not None:
                return enum_type
        return None

    @staticmethod
    def _is_enum_value_field(field_name: str | None) -> bool:
        """Check whether field name is enum-value-like.

        @param field_name Field name.
        @return True when field looks enum-like.
        """
        if not field_name:
            return False
        key = field_name.strip("_").lower()
        return key in {"value", "enumvalue", "fixedid"} or key.endswith("id")

    def _postprocess_enum_nodes(
        self,
        value: Any,
        current_class: str | None = None,
        scalar_enum_hint: str | None = None,
        class_default_enum: str | None = None,
        container_param_rule: tuple[str, str] | None = None,
        field_name: str | None = None,
    ) -> Any:
        """Recursively normalize keys and convert fixed enum values.

        @param value Current node value.
        @param current_class Current class context.
        @param scalar_enum_hint Enum hint for scalar conversion.
        @param class_default_enum Default enum for class-scoped values.
        @param container_param_rule Generic container enum rule.
        @param field_name Current field name.
        @return Transformed node value.
        """
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            dict_level_enum_hint: str | None = None
            enum_name = value.get("_EnumName")
            fixed_id = value.get("_FixedID")
            if isinstance(enum_name, str) and isinstance(fixed_id, int):
                dict_level_enum_hint = self._infer_enum_type_from_member_and_value(
                    enum_name, fixed_id
                )
            for k, v in value.items():
                if (
                    isinstance(k, str)
                    and self._looks_like_class_name(k)
                    and isinstance(v, dict)
                ):
                    normalized_class = self._normalize_to_fixed_enum_type(k)
                    key_out = (
                        normalized_class
                        if normalized_class != k and k.endswith("_Serializable")
                        else k
                    )
                    next_scalar_hint = (
                        normalized_class
                        if normalized_class in self.enum_lookup
                        else None
                    )
                    next_container_rule = self.generic_container_rules.get(k)
                    if next_container_rule is None:
                        next_container_rule = self.generic_container_rules.get(
                            normalized_class
                        )
                    next_default_enum = self._resolve_class_default_enum(
                        normalized_class
                    )
                    if (
                        container_param_rule is not None
                        and normalized_class == container_param_rule[0]
                    ):
                        next_default_enum = container_param_rule[1]

                    out[key_out] = self._postprocess_enum_nodes(
                        v,
                        current_class=normalized_class,
                        scalar_enum_hint=next_scalar_hint,
                        class_default_enum=next_default_enum,
                        container_param_rule=next_container_rule,
                        field_name=None,
                    )
                    continue

                field_hint: str | None = None
                if current_class is not None:
                    fixed_field_type = (
                        self._resolve_field_enum_hint(current_class, k)
                        if isinstance(k, str)
                        else None
                    )
                    if fixed_field_type:
                        field_hint = fixed_field_type
                if (
                    field_hint is None
                    and class_default_enum is not None
                    and isinstance(k, str)
                    and self._is_enum_value_field(k)
                ):
                    field_hint = class_default_enum
                if (
                    field_hint is None
                    and scalar_enum_hint is not None
                    and isinstance(k, str)
                    and self._is_enum_value_field(k)
                ):
                    field_hint = scalar_enum_hint
                if (
                    field_hint is None
                    and dict_level_enum_hint is not None
                    and isinstance(k, str)
                    and k.strip("_").lower() == "fixedid"
                ):
                    field_hint = dict_level_enum_hint

                out[k] = self._postprocess_enum_nodes(
                    v,
                    current_class=current_class,
                    scalar_enum_hint=field_hint,
                    class_default_enum=class_default_enum,
                    container_param_rule=container_param_rule,
                    field_name=k if isinstance(k, str) else None,
                )
            return out

        if isinstance(value, list):
            return [
                self._postprocess_enum_nodes(
                    item,
                    current_class=current_class,
                    scalar_enum_hint=scalar_enum_hint,
                    class_default_enum=class_default_enum,
                    container_param_rule=container_param_rule,
                    field_name=field_name,
                )
                for item in value
            ]
        if isinstance(value, int) and scalar_enum_hint is not None:
            return self._format_enum_value(scalar_enum_hint, value)
        return value

    def _finalize_export_tree(self, value: Any) -> Any:
        """Finalize exported JSON by removing `index` and flattening `value` wrappers."""
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if k == "index":
                    continue
                out[k] = self._finalize_export_tree(v)
            if len(out) == 1:
                only_key = next(iter(out))
                if only_key == "value":
                    return out[only_key]
                if isinstance(only_key, str) and only_key in self.enum_lookup:
                    return out[only_key]
            return out
        if isinstance(value, list):
            return [self._finalize_export_tree(item) for item in value]
        return value

    def run(self) -> dict[str, int]:
        """Run export pipeline for all discovered files.

        @return Export statistics with total/success/failed counts.
        """
        files = self._discover_user3_files()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self._ensure_internal_metadata_files()
        self.enum_lookup = self._load_enum_lookup()
        self._load_enum_context_from_il2cpp_dump()
        self._ensure_enum_lookup()

        success = 0
        failed = 0
        with tqdm(total=len(files), desc="Exporting user3", unit="file") as pbar:
            for user3_file in files:
                pbar.set_description(user3_file.name.replace(".user.3", ""))
                if self._export_one_file(user3_file):
                    success += 1
                else:
                    failed += 1
                pbar.update(1)

        return {"total": len(files), "success": success, "failed": failed}

    def _export_one_file(self, user3_file: Path) -> bool:
        """Export a single `.user.3` file.

        @param user3_file Source `.user.3` file path.
        @return True on success.
        """
        try:
            tree = self._parse_user3(user3_file)
            tree = self._postprocess_enum_nodes(tree)
            tree = self._finalize_export_tree(tree)
            output_path = self._output_path_for(user3_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(tree, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _resolve_schema_path(self, schema_dir: Path) -> Path:
        """Resolve schema file path.

        @param schema_dir Schema file path or directory.
        @return Resolved schema file path.
        """
        if schema_dir.is_file():
            return schema_dir
        path = schema_dir / "rszmhst3.json"
        if not path.is_file():
            raise FileNotFoundError(f"rszmhst3.json not found: {path}")
        return path

    def _normalize_tree_depth(self, tree_depth: int | str) -> int | str:
        """Normalize tree depth input value.

        @param tree_depth Requested tree depth.
        @return Normalized depth integer or `"auto"`.
        """
        if isinstance(tree_depth, str):
            value = tree_depth.strip().lower()
            if value != "auto":
                raise ValueError("tree_depth must be a non-negative integer or 'auto'")
            return "auto"
        if isinstance(tree_depth, int):
            if tree_depth < 0:
                raise ValueError("tree_depth must be >= 0")
            return tree_depth
        raise TypeError("tree_depth must be int or str")

    def _count_reference_links(self, value: Any) -> int:
        """Count reference links in nested structure.

        @param value Nested value.
        @return Count of `ref_instance_id` links.
        """
        if isinstance(value, dict):
            if "ref_instance_id" in value and isinstance(value["ref_instance_id"], int):
                return 1
            total = 0
            for child in value.values():
                total += self._count_reference_links(child)
            return total
        if isinstance(value, list):
            return sum(self._count_reference_links(child) for child in value)
        return 0

    def _collect_reference_ids(self, value: Any, out: set[int]) -> None:
        """Collect referenced instance IDs from nested structure.

        @param value Nested value.
        @param out Output set for collected IDs.
        @return None.
        """
        if isinstance(value, dict):
            if "ref_instance_id" in value and isinstance(value["ref_instance_id"], int):
                out.add(value["ref_instance_id"])
                return
            for child in value.values():
                self._collect_reference_ids(child, out)
            return
        if isinstance(value, list):
            for child in value:
                self._collect_reference_ids(child, out)

    def _infer_roots_when_object_table_empty(
        self,
        idx_map: dict[int, dict[str, Any]],
        parsed_instances: list[dict[str, Any]],
    ) -> list[int]:
        """Infer root indices when object table is empty.

        @param idx_map Parsed instances indexed by instance ID.
        @param parsed_instances Ordered parsed instance list.
        @return Inferred root indices.
        """
        candidates = sorted(
            idx
            for idx, inst in idx_map.items()
            if idx > 0 and isinstance(inst.get("data", {}).get("fields"), dict)
        )
        if not candidates:
            return []

        referenced: set[int] = set()
        for inst in parsed_instances:
            fields = inst.get("data", {}).get("fields")
            if isinstance(fields, dict):
                self._collect_reference_ids(fields, referenced)

        inferred = [idx for idx in candidates if idx not in referenced]
        if inferred:
            return inferred
        return candidates

    def _auto_pick_tree_depth(
        self, parsed_instances: list[dict[str, Any]], object_roots: list[int]
    ) -> int:
        """Auto-pick compact-tree depth from content complexity.

        @param parsed_instances Parsed instance list.
        @param object_roots Root instance indices.
        @return Auto-selected depth.
        """
        ref_links = 0
        for inst in parsed_instances:
            fields = inst.get("data", {}).get("fields")
            if isinstance(fields, dict):
                ref_links += self._count_reference_links(fields)

        complexity = max(len(parsed_instances), ref_links, len(object_roots) * 10)
        if complexity <= 1500:
            return 4
        if complexity <= 8000:
            return 3
        if complexity <= 30000:
            return 2
        return 1

    def _discover_user3_files(self) -> list[Path]:
        """Discover input `.user.3` files and apply excludes.

        @return Discovered `.user.3` files after exclude filtering.
        """
        if self.user3_root.is_file():
            files = [self.user3_root]
        else:
            if not self.user3_root.is_dir():
                raise FileNotFoundError(f"user3 root not found: {self.user3_root}")
            files = sorted(self.user3_root.rglob("*.user.3"))
            if not files:
                raise FileNotFoundError(f"no *.user.3 found under: {self.user3_root}")
        if not self._exclude_patterns:
            return files

        kept: list[Path] = []
        for file_path in files:
            if self.user3_root.is_file():
                rel_path = file_path.name
            else:
                rel_path = file_path.relative_to(self.user3_root).as_posix()
            if any(pattern.search(rel_path) for pattern in self._exclude_patterns):
                continue
            kept.append(file_path)
        if not kept:
            raise FileNotFoundError("all *.user.3 files were excluded by regex filters")
        return kept

    def _output_path_for(self, user3_file: Path) -> Path:
        """Build output json path for one source file.

        @param user3_file Source file path.
        @return Output json path.
        """
        if self.user3_root.is_file():
            relative_parent = Path()
        else:
            relative_parent = user3_file.relative_to(self.user3_root).parent
        output_name = f"{user3_file.name}.json"
        return self.output_root / relative_parent / output_name

    def _parse_scalar(
        self, reader: BinaryReader, field: FieldDef, depth: int = 0
    ) -> Any:
        """Parse one scalar field value from binary stream.

        @param reader Binary reader.
        @param field Field definition.
        @param depth Struct recursion depth.
        @return Parsed scalar value.
        """
        t = field.field_type
        if t == "Bool":
            return bool(reader.read_u8())
        if t == "S8":
            return reader.read_s8()
        if t == "U8":
            return reader.read_u8()
        if t == "S16":
            return reader.read_s16()
        if t == "U16":
            return reader.read_u16()
        if t in ("S32", "Sfix"):
            return reader.read_s32()
        if t == "Enum":
            return reader.read_s32()
        if t == "U32":
            return reader.read_u32()
        if t == "S64":
            return reader.read_s64()
        if t == "U64":
            return reader.read_u64()
        if t == "F32":
            return reader.read_f32()
        if t == "F64":
            return reader.read_f64()
        if t in ("Object", "UserData"):
            return {"ref_instance_id": reader.read_s32()}
        if t in ("String", "Resource"):
            return read_len_utf16(reader)
        if t == "C8":
            return read_len_c8(reader)
        if t in ("Guid", "GameObjectRef", "Uri"):
            return read_guid_like(reader)
        if t == "Struct":
            if depth >= 4:
                to_read = max(0, min(field.size, reader.size - reader.tell()))
                return {"raw": reader.read(to_read).hex(), "truncated": True}
            struct_hash = self.typedb.resolve_struct_hash(field.original_type)
            if struct_hash is None:
                to_read = max(0, min(field.size, reader.size - reader.tell()))
                return {
                    "raw": reader.read(to_read).hex(),
                    "unknown_struct": field.original_type,
                }
            struct_cls = self.typedb.get_class(struct_hash)
            if struct_cls is None:
                to_read = max(0, min(field.size, reader.size - reader.tell()))
                return {
                    "raw": reader.read(to_read).hex(),
                    "unknown_struct": field.original_type,
                }
            start = reader.tell()
            out: dict[str, Any] = {}
            for sf in struct_cls.fields:
                reader.seek(
                    align(reader.tell(), 4 if sf.is_array else max(sf.align, 1))
                )
                out[sf.name or "unnamed"] = self._parse_field_value(
                    reader, sf, depth=depth + 1
                )
            consumed = reader.tell() - start
            if field.size > consumed:
                reader.seek(reader.tell() + (field.size - consumed))
            return out
        if t in {
            "Float2",
            "Float3",
            "Float4",
            "Vec2",
            "Vec3",
            "Vec4",
            "Quaternion",
            "Color",
            "AABB",
            "Capsule",
            "OBB",
            "Mat3",
            "Mat4",
            "Position",
        }:
            count = max(field.size // 4, 1)
            return [reader.read_f32() for _ in range(count)]

        if field.size <= 0:
            return None
        to_read = max(0, min(field.size, reader.size - reader.tell()))
        return {"raw": reader.read(to_read).hex(), "type": t}

    def _parse_field_value(
        self, reader: BinaryReader, field: FieldDef, depth: int = 0
    ) -> Any:
        """Parse scalar or array field value.

        @param reader Binary reader.
        @param field Field definition.
        @param depth Struct recursion depth.
        @return Parsed field value.
        """
        if field.is_array:
            count = reader.read_u32()
            if count > 1_000_000:
                return []
            items = []
            for _ in range(count):
                if reader.tell() >= reader.size:
                    break
                reader.seek(align(reader.tell(), max(field.align, 1)))
                non_array = FieldDef(
                    name=field.name,
                    field_type=field.field_type,
                    original_type=field.original_type,
                    size=field.size,
                    align=field.align,
                    is_array=False,
                )
                items.append(self._parse_scalar(reader, non_array, depth=depth))
            return items
        return self._parse_scalar(reader, field, depth=depth)

    def _estimate_min_instance_size(self, cls: ClassDef) -> int:
        """Estimate minimum byte size for one instance.

        @param cls Class definition.
        @return Estimated minimum instance size.
        """
        pos = 0
        for field in cls.fields:
            align_to = 4 if field.is_array else max(field.align, 1)
            pos = align(pos, align_to)
            t = field.field_type
            if field.is_array:
                pos += 4
            elif t in ("String", "Resource", "C8"):
                pos += 4
            elif t in ("Object", "UserData"):
                pos += 4
            elif t in ("Guid", "GameObjectRef", "Uri"):
                pos += 16
            elif t in ("S8", "U8", "Bool"):
                pos += 1
            elif t in ("S16", "U16"):
                pos += 2
            elif t in ("S32", "U32", "Enum", "Sfix", "F32"):
                pos += 4
            elif t in ("S64", "U64", "F64"):
                pos += 8
            else:
                pos += max(field.size, 0)
        return max(pos, 1)

    def _parse_instance(self, reader: BinaryReader, class_hash: int) -> dict[str, Any]:
        """Parse one class instance payload.

        @param reader Binary reader.
        @param class_hash Class hash.
        @return Parsed instance dictionary.
        """
        cls = self.typedb.get_class(class_hash)
        if cls is None:
            raise ParseError(f"class hash 0x{class_hash:08x} not found in schema")
        out: dict[str, Any] = {"_class": cls.name, "fields": {}}
        for field in cls.fields:
            reader.seek(
                align(reader.tell(), 4 if field.is_array else max(field.align, 1))
            )
            out["fields"][field.name or "unnamed"] = self._parse_field_value(
                reader, field, depth=0
            )
        return out

    def _simplify_value_object(self, value: Any) -> Any:
        """Simplify wrapper objects containing only `_Value`.

        @param value Input value.
        @return Simplified value when wrapper shape matches.
        """
        if isinstance(value, dict) and len(value) == 1 and "_Value" in value:
            return value["_Value"]
        return value

    def _resolve_compact_value(
        self,
        value: Any,
        idx_map: dict[int, dict[str, Any]],
        depth: int,
        visited: set[int],
    ) -> Any:
        """Resolve compact value with reference expansion.

        @param value Input value.
        @param idx_map Instance map.
        @param depth Remaining depth.
        @param visited Visited indices.
        @return Compact resolved value.
        """
        if isinstance(value, dict):
            if "ref_instance_id" in value and isinstance(value["ref_instance_id"], int):
                target_idx = value["ref_instance_id"]
                if depth <= 0:
                    return {"ref_instance_id": target_idx}
                return self._build_compact_tree(
                    target_idx, idx_map, depth - 1, set(visited)
                )
            out: dict[str, Any] = {}
            for k, v in value.items():
                out[k] = self._resolve_compact_value(v, idx_map, depth, set(visited))
            return out
        if isinstance(value, list):
            return [
                self._resolve_compact_value(v, idx_map, depth, set(visited))
                for v in value
            ]
        return value

    def _build_compact_tree(
        self,
        idx: int,
        idx_map: dict[int, dict[str, Any]],
        depth: int,
        instance_info_map: dict[int, dict[str, Any]] | None = None,
        visited: set[int] | None = None,
    ) -> dict[str, Any]:
        """Build compact tree node for one root index.

        @param idx Root instance index.
        @param idx_map Parsed instance map.
        @param depth Remaining depth.
        @param instance_info_map Optional instance metadata map.
        @param visited Optional visited-index set.
        @return Compact tree node.
        """
        if visited is None:
            visited = set()
        if idx in visited:
            return {"Ref": {"ref_instance_id": idx, "cycle": True}}
        visited.add(idx)

        inst = idx_map.get(idx)
        if inst is None:
            if instance_info_map is not None and idx in instance_info_map:
                class_name = instance_info_map[idx].get("class_name", "Unknown Class")
                class_name = self._normalize_to_fixed_enum_type(class_name)
                return {class_name: {"ref_instance_id": idx, "unparsed": True}}
            return {"Ref": {"ref_instance_id": idx, "missing": True}}

        if inst.get("is_userdata_reference"):
            class_name = inst.get("class_name", "Unknown Class")
            class_name = self._normalize_to_fixed_enum_type(class_name)
            return {
                class_name: {
                    "ref_instance_id": idx,
                    "path": inst.get("path", ""),
                }
            }

        data = inst.get("data", {})
        class_name = data.get("_class", inst.get("class_name", "Unknown Class"))
        class_name = self._normalize_to_fixed_enum_type(class_name)
        fields = data.get("fields", {})
        if not isinstance(fields, dict):
            fields = {}

        resolved = self._resolve_compact_value_with_info(
            fields, idx_map, depth, instance_info_map, visited
        )
        resolved = self._simplify_value_object(resolved)

        if isinstance(resolved, dict):
            node_value: Any = resolved
        else:
            node_value = {"value": resolved}

        return {class_name: node_value}

    def _resolve_compact_value_with_info(
        self,
        value: Any,
        idx_map: dict[int, dict[str, Any]],
        depth: int,
        instance_info_map: dict[int, dict[str, Any]] | None,
        visited: set[int],
    ) -> Any:
        """Resolve compact value using instance metadata.

        @param value Input value.
        @param idx_map Parsed instance map.
        @param depth Remaining depth.
        @param instance_info_map Optional instance metadata map.
        @param visited Visited indices.
        @return Compact resolved value.
        """
        if isinstance(value, dict):
            if "ref_instance_id" in value and isinstance(value["ref_instance_id"], int):
                target_idx = value["ref_instance_id"]
                if depth <= 0:
                    return {"ref_instance_id": target_idx}
                return self._build_compact_tree(
                    target_idx,
                    idx_map,
                    depth - 1,
                    instance_info_map=instance_info_map,
                    visited=set(visited),
                )
            out: dict[str, Any] = {}
            for k, v in value.items():
                out[k] = self._resolve_compact_value_with_info(
                    v, idx_map, depth, instance_info_map, set(visited)
                )
            return out
        if isinstance(value, list):
            return [
                self._resolve_compact_value_with_info(
                    v, idx_map, depth, instance_info_map, set(visited)
                )
                for v in value
            ]
        return value

    def _parse_user3(self, user3_path: Path) -> list[dict[str, Any]]:
        """Parse full `.user.3` file into compact object trees.

        @param user3_path Source `.user.3` file path.
        @return Compact object tree list.
        """
        reader = BinaryReader(user3_path.read_bytes())

        magic = reader.read_u32()
        if magic != USR_MAGIC:
            raise ParseError(f"not a user file: magic={magic}")

        usr_header = {
            "signature": magic,
            "resource_count": reader.read_s32(),
            "userdata_count": reader.read_s32(),
            "info_count": reader.read_s32(),
            "resource_info_tbl": reader.read_u64(),
            "userdata_info_tbl": reader.read_u64(),
            "data_offset": reader.read_u64(),
        }
        header_userdata_infos: list[dict[str, Any]] = []
        if usr_header["userdata_count"] > 0 and usr_header["userdata_info_tbl"] > 0:
            try:
                reader.seek(usr_header["userdata_info_tbl"])
                for idx in range(usr_header["userdata_count"]):
                    class_hash = reader.read_u32()
                    _crc = reader.read_u32()
                    path_offset = reader.read_u64()
                    class_name = (
                        self.typedb.get_class(class_hash).name
                        if self.typedb.get_class(class_hash)
                        else "Unknown Class"
                    )
                    header_userdata_infos.append(
                        {
                            "index": idx,
                            "class_hash": class_hash,
                            "class_name": class_name,
                            "path": reader.read_wstring_null(path_offset),
                        }
                    )
            except Exception:
                header_userdata_infos = []

        rsz_start = usr_header["data_offset"]

        reader.seek(rsz_start)
        rsz_header = {
            "magic": reader.read_u32(),
            "version": reader.read_u32(),
            "object_count": reader.read_s32(),
            "instance_count": reader.read_s32(),
            "userdata_count": reader.read_s32(),
            "reserved": reader.read_s32(),
            "instance_offset": reader.read_s64(),
            "data_offset": reader.read_s64(),
            "userdata_offset": reader.read_s64(),
        }
        if rsz_header["magic"] != RSZ_MAGIC:
            raise ParseError(
                f"RSZ magic mismatch at data_offset: {rsz_header['magic']}"
            )

        reader.seek(rsz_start + 48)
        object_table = [
            reader.read_s32() for _i in range(max(rsz_header["object_count"], 0))
        ]
        object_table_set = set(object_table)

        instance_infos: list[dict[str, Any]] = []
        reader.seek(rsz_start + rsz_header["instance_offset"])
        for idx in range(max(rsz_header["instance_count"], 0)):
            class_hash = reader.read_u32()
            crc = reader.read_u32()
            class_def = self.typedb.get_class(class_hash)
            instance_infos.append(
                {
                    "index": idx,
                    "hash": class_hash,
                    "class_name": class_def.name if class_def else "Unknown Class",
                    "crc": crc,
                    "is_object": idx in object_table_set,
                }
            )
        instance_info_map = {item["index"]: item for item in instance_infos}

        rsz_userdata_instance_ids: list[int] = []
        rsz_userdata_path_by_instance: dict[int, str] = {}
        if rsz_header["userdata_count"] > 0 and rsz_header["userdata_offset"] > 0:
            try:
                reader.seek(rsz_start + rsz_header["userdata_offset"])
                for _i in range(rsz_header["userdata_count"]):
                    instance_id = reader.read_s32()
                    _type_hash = reader.read_u32()
                    path_offset = reader.read_u64()
                    if instance_id >= 0:
                        rsz_userdata_instance_ids.append(instance_id)
                        path = ""
                        if path_offset > 0 and rsz_start + path_offset < reader.size:
                            path = reader.read_wstring_null(rsz_start + path_offset)
                        rsz_userdata_path_by_instance[instance_id] = path
            except Exception:
                rsz_userdata_instance_ids = []
                rsz_userdata_path_by_instance = {}
        rsz_userdata_instance_set = set(rsz_userdata_instance_ids)

        parsed_instances: list[dict[str, Any]] = []
        reader.seek(rsz_start + rsz_header["data_offset"])
        for idx, info in enumerate(instance_infos):
            class_hash = int(info["hash"])
            if idx == 0:
                parsed_instances.append(
                    {
                        "index": idx,
                        "class_name": info["class_name"],
                        "note": "null instance slot",
                    }
                )
                continue
            if idx in rsz_userdata_instance_set:
                parsed_instances.append(
                    {
                        "index": idx,
                        "class_name": info["class_name"],
                        "is_userdata_reference": True,
                        "path": rsz_userdata_path_by_instance.get(idx, ""),
                    }
                )
                continue
            cls = self.typedb.get_class(class_hash)
            if cls is None:
                parsed_instances.append(
                    {
                        "index": idx,
                        "class_name": info["class_name"],
                        "unparsed": True,
                        "reason": "class_not_found_in_schema",
                    }
                )
                continue
            if cls.fields:
                first = cls.fields[0]
                reader.seek(
                    align(reader.tell(), 4 if first.is_array else max(first.align, 1))
                )
            start_pos = reader.tell()
            try:
                parsed_instances.append(
                    {"index": idx, "data": self._parse_instance(reader, class_hash)}
                )
            except Exception as exc:
                parsed_instances.append(
                    {
                        "index": idx,
                        "class_name": info["class_name"],
                        "unparsed": True,
                        "reason": str(exc),
                    }
                )
                min_skip = self._estimate_min_instance_size(cls)
                next_pos = min(reader.size, start_pos + min_skip)
                if next_pos <= start_pos:
                    break
                reader.seek(next_pos)

        idx_map = {
            inst["index"]: inst
            for inst in parsed_instances
            if isinstance(inst.get("index"), int)
        }
        object_roots = sorted(
            set(i for i in object_table if isinstance(i, int) and i >= 0)
        )
        if not object_roots:
            object_roots = self._infer_roots_when_object_table_empty(
                idx_map, parsed_instances
            )
        if not object_roots and rsz_userdata_instance_ids:
            object_roots = sorted(
                set(
                    i
                    for i in rsz_userdata_instance_ids
                    if i in instance_info_map and i > 0
                )
            )
        if not object_roots:
            object_roots = sorted(i for i in instance_info_map.keys() if i > 0)
        depth = (
            self._auto_pick_tree_depth(parsed_instances, object_roots)
            if self.tree_depth == "auto"
            else self.tree_depth
        )
        object_trees = [
            self._build_compact_tree(
                root_idx,
                idx_map,
                depth=depth,
                instance_info_map=instance_info_map,
            )
            for root_idx in object_roots
            if root_idx in instance_info_map
        ]
        if not object_trees and header_userdata_infos:
            return [
                {
                    item["class_name"]: {
                        "ref_instance_id": item["index"],
                        "path": item["path"],
                    }
                }
                for item in header_userdata_infos
            ]
        return object_trees
