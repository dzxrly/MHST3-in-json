"""JSON 到 RSZ 实例表的规划逻辑。"""

from __future__ import annotations

from typing import Any

from .models import PACK_JSON_FORMAT, InstanceRef, InstanceSpec, PackError, StructValue
from ..core import ClassDef, FieldDef


class PackerPlanMixin:
    """负责把 JSON 树转换成待写入的实例和字段值。"""

    def _is_pack_document(self, data: Any) -> bool:
        """判断输入是否为完整实例表封包文档。"""
        return (
            isinstance(data, dict)
            and data.get("_format") == PACK_JSON_FORMAT
            and isinstance(data.get("_instances"), dict)
        )

    def _plan_pack_document(self, data: dict[str, Any]) -> list[int]:
        """按完整实例表文档规划实例，保持原实例编号稳定。"""
        unsupported = data.get("_unsupported", [])
        if unsupported:
            if not isinstance(unsupported, list):
                raise PackError("pack JSON _unsupported must be an array")
            raise PackError(
                "pack JSON contains original data sections that the current "
                f"writer cannot rebuild: {unsupported}"
            )

        instances_raw = data.get("_instances")
        if not isinstance(instances_raw, dict):
            raise PackError("pack JSON must contain an _instances object")

        ids = self._parse_pack_instance_ids(instances_raw)
        if not ids or ids[0] != 0:
            raise PackError("pack JSON _instances must include null instance 0")
        expected = list(range(ids[-1] + 1))
        if ids != expected:
            missing = sorted(set(expected) - set(ids))
            raise PackError(f"pack JSON instance ids must be dense; missing: {missing}")

        roots = self._parse_pack_roots(data.get("_roots"), set(ids))
        self._validate_pack_references(instances_raw, set(ids))
        self.instances = [None for _ in ids]

        for idx in ids[1:]:
            entry = instances_raw[str(idx)]
            if not isinstance(entry, dict):
                raise PackError(f"instance {idx} must be an object")
            if entry.get("_unparsed"):
                reason = entry.get("reason", "unparsed")
                raise PackError(
                    f"instance {idx} is unparsed and cannot be packed: {reason}"
                )
            if entry.get("_kind") == "userdata_reference":
                raise PackError(
                    f"instance {idx} is an external userdata reference; "
                    "the current writer cannot rebuild RSZ userdata tables"
                )
            class_name = entry.get("_class")
            if not isinstance(class_name, str) or not class_name:
                raise PackError(f"instance {idx} is missing _class")
            class_hash = self.typedb.name_to_hash.get(class_name)
            if class_hash is None:
                raise PackError(
                    f"class not found in schema for instance {idx}: {class_name}"
                )
            class_def = self.typedb.get_class(class_hash)
            if class_def is None:
                raise PackError(
                    f"class hash not found in schema for instance {idx}: {class_name}"
                )
            self._validate_declared_hash(idx, entry, class_hash, class_def.crc)
            self.instances[idx] = InstanceSpec(
                class_hash=class_hash, class_def=class_def
            )

        for idx in ids[1:]:
            entry = instances_raw[str(idx)]
            spec = self.instances[idx]
            if spec is None:
                continue
            fields = entry.get("fields", {})
            if not isinstance(fields, dict):
                raise PackError(f"instance {idx} fields must be an object")
            self._validate_known_fields(idx, spec.class_def, fields)
            before_count = len(self.instances)
            spec.fields = self._prepare_fields(spec.class_def, fields)
            if len(self.instances) != before_count:
                raise PackError(
                    f"instance {idx} contains embedded object data; "
                    "pack JSON object fields must use ref_instance_id"
                )
        return roots

    def _parse_pack_instance_ids(self, instances_raw: dict[str, Any]) -> list[int]:
        """解析并排序完整实例表中的实例编号。"""
        ids: list[int] = []
        for key in instances_raw:
            try:
                idx = int(key)
            except (TypeError, ValueError) as exc:
                raise PackError(f"invalid instance id: {key!r}") from exc
            if idx < 0:
                raise PackError(f"instance id must be non-negative: {idx}")
            ids.append(idx)
        return sorted(ids)

    def _parse_pack_roots(self, raw_roots: Any, known_ids: set[int]) -> list[int]:
        """解析并校验完整实例表中的根实例编号。"""
        if not isinstance(raw_roots, list):
            raise PackError("pack JSON must contain a _roots array")
        roots: list[int] = []
        for raw_root in raw_roots:
            if not isinstance(raw_root, int):
                raise PackError(f"root instance id must be int: {raw_root!r}")
            if raw_root not in known_ids:
                raise PackError(f"root references missing instance: {raw_root}")
            roots.append(raw_root)
        return roots

    def _validate_pack_references(
        self, instances_raw: dict[str, Any], known_ids: set[int]
    ) -> None:
        """校验所有 ref_instance_id 是否能在完整实例表中找到。"""
        for idx, entry in instances_raw.items():
            self._validate_ref_value(entry, known_ids, f"_instances.{idx}")

    def _validate_ref_value(self, value: Any, known_ids: set[int], path: str) -> None:
        """递归校验引用对象，避免静默写入悬空引用。"""
        if isinstance(value, dict):
            if "ref_instance_id" in value:
                ref_id = value.get("ref_instance_id")
                if not isinstance(ref_id, int):
                    raise PackError(f"{path}.ref_instance_id must be int")
                extra = sorted(k for k in value if k != "ref_instance_id")
                if extra:
                    raise PackError(
                        f"{path} has ref_instance_id plus ignored keys: {extra}"
                    )
                if ref_id not in known_ids:
                    raise PackError(f"{path} references missing instance: {ref_id}")
                return
            for key, child in value.items():
                self._validate_ref_value(child, known_ids, f"{path}.{key}")
            return
        if isinstance(value, list):
            for i, child in enumerate(value):
                self._validate_ref_value(child, known_ids, f"{path}[{i}]")

    def _validate_declared_hash(
        self, idx: int, entry: dict[str, Any], class_hash: int, crc: int
    ) -> None:
        """如果 pack JSON 中带有 hash/crc，则与模板解析结果比对。"""
        declared_hash = self._parse_optional_u32(entry.get("_hash"))
        if declared_hash is not None and declared_hash != class_hash:
            raise PackError(
                f"instance {idx} _hash does not match schema class: "
                f"0x{declared_hash:08x} != 0x{class_hash:08x}"
            )
        declared_crc = self._parse_optional_u32(entry.get("_crc"))
        if declared_crc is not None and declared_crc != (crc & 0xFFFFFFFF):
            raise PackError(
                f"instance {idx} _crc does not match schema class: "
                f"0x{declared_crc:08x} != 0x{crc & 0xFFFFFFFF:08x}"
            )

    def _parse_optional_u32(self, value: Any) -> int | None:
        """解析可选十六进制/十进制 32 位整数。"""
        if value is None:
            return None
        if isinstance(value, int):
            return value & 0xFFFFFFFF
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            return int(text, 0) & 0xFFFFFFFF
        raise PackError(f"expected integer or hex string, got {value!r}")

    def _validate_known_fields(
        self, idx: int, class_def: ClassDef, raw_fields: dict[str, Any]
    ) -> None:
        """在完整实例表模式下拒绝会被静默忽略的未知字段。"""
        allowed = {field.name or "unnamed" for field in class_def.fields}
        unknown = sorted(key for key in raw_fields if key not in allowed)
        if unknown:
            raise PackError(
                f"instance {idx} ({class_def.name}) contains unknown fields: {unknown}"
            )

    def _normalize_roots(self, data: Any) -> list[Any]:
        """把顶层 JSON 统一成根对象列表。"""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        raise PackError("top-level JSON must be an object or a list of objects")

    def _plan_node(self, node: Any, expected_class: str | None = None) -> int:
        """把一个 JSON 节点规划为 RSZ 实例，并返回实例编号。"""
        class_name, fields = self._unwrap_node(node, expected_class)
        class_hash = self.typedb.name_to_hash.get(class_name)
        if class_hash is None:
            raise PackError(f"class not found in schema: {class_name}")
        class_def = self.typedb.get_class(class_hash)
        if class_def is None:
            raise PackError(f"class hash not found in schema: {class_name}")

        spec = InstanceSpec(class_hash=class_hash, class_def=class_def)
        spec.fields = self._prepare_fields(class_def, fields)
        instance_id = len(self.instances)
        # 先加入实例表，再由字段准备阶段递归规划子对象，保持引用编号稳定。
        self.instances.append(spec)
        return instance_id

    def _unwrap_node(self, node: Any, expected_class: str | None) -> tuple[str, Any]:
        """从类名包裹对象中取出类名和字段对象。"""
        if isinstance(node, dict):
            class_keys = [
                k
                for k in node.keys()
                if isinstance(k, str) and k in self.typedb.name_to_hash
            ]
            if len(class_keys) == 1 and len(node) == 1:
                key = class_keys[0]
                return key, node[key]
        if expected_class:
            # 对象字段有明确声明类型时，允许用户直接传字段值而不再包一层类名。
            return expected_class, node
        raise PackError(f"cannot infer class for node: {node!r}")

    def _prepare_fields(self, class_def: ClassDef, raw_fields: Any) -> dict[str, Any]:
        """按模板字段顺序准备一个实例的字段值。"""
        if not isinstance(raw_fields, dict):
            value_fields = [
                f for f in class_def.fields if f.name in {"_Value", "value__"}
            ]
            if len(value_fields) == 1:
                # 枚举或简单包装类型经常导出为纯值，这里还原到真实字段名。
                raw_fields = {value_fields[0].name: raw_fields}
            else:
                raise PackError(f"class {class_def.name} expects object fields")

        prepared: dict[str, Any] = {}
        for field_def in class_def.fields:
            key = field_def.name or "unnamed"
            # JSON 中缺失的字段按类型填默认值，避免手工编辑后无法封包。
            raw_value = raw_fields.get(key, self._default_value(field_def))
            prepared[key] = self._prepare_field_value(field_def, raw_value)
        return prepared

    def _prepare_field_value(self, field_def: FieldDef, raw_value: Any) -> Any:
        """把 JSON 字段值转换为写入器需要的中间表示。"""
        if field_def.is_array:
            items = raw_value if isinstance(raw_value, list) else []
            non_array = FieldDef(
                name=field_def.name,
                field_type=field_def.field_type,
                original_type=field_def.original_type,
                size=field_def.size,
                align=field_def.align,
                is_array=False,
            )
            return [self._prepare_field_value(non_array, item) for item in items]

        if field_def.field_type in {"Object", "UserData"}:
            # 对象字段需要先规划目标实例，再写入引用编号。
            return self._prepare_object_ref(field_def, raw_value)
        if field_def.field_type == "Struct":
            # 结构体按自己的 ClassDef 递归准备字段。
            return self._prepare_struct_value(field_def, raw_value)
        return raw_value

    def _prepare_object_ref(self, field_def: FieldDef, raw_value: Any) -> InstanceRef:
        """把对象字段值转换为实例引用。"""
        if raw_value is None:
            return InstanceRef(0)
        if isinstance(raw_value, dict) and isinstance(
            raw_value.get("ref_instance_id"), int
        ):
            # 用户保留导出的引用编号时直接复用，不展开新实例。
            return InstanceRef(raw_value["ref_instance_id"])

        expected_class = self._resolve_object_class(field_def.original_type)
        if isinstance(raw_value, dict):
            class_keys = [
                k
                for k in raw_value.keys()
                if isinstance(k, str) and k in self.typedb.name_to_hash
            ]
            if len(class_keys) == 1 and len(raw_value) == 1:
                # 已经是 `{类名: 字段}` 形状时直接规划该子对象。
                return InstanceRef(self._plan_node(raw_value))
            if expected_class:
                return InstanceRef(self._plan_node(raw_value, expected_class))

        if expected_class:
            return InstanceRef(self._plan_node(raw_value, expected_class))
        raise PackError(
            f"cannot encode object field {field_def.name!r} of type {field_def.original_type!r}"
        )

    def _resolve_object_class(self, original_type: str) -> str | None:
        """根据字段原始类型推断对象字段应使用的类名。"""
        if original_type in self.typedb.name_to_hash:
            return original_type
        if original_type.endswith("_Fixed"):
            # 固定枚举字段常对应一个 `xxx_Serializable` 包装类型。
            candidate = f"{original_type[:-6]}_Serializable"
            if candidate in self.typedb.name_to_hash:
                return candidate
        return None

    def _prepare_struct_value(self, field_def: FieldDef, raw_value: Any) -> Any:
        """准备结构体字段的中间表示。"""
        if isinstance(raw_value, dict) and isinstance(raw_value.get("raw"), str):
            # 导出器在结构体过深或模板缺失时会保留原始字节；
            # 这里直接交给 writer 原样写回，避免默认字段覆盖未知内容。
            return raw_value
        struct_hash = self.typedb.resolve_struct_hash(field_def.original_type)
        if struct_hash is None:
            # 模板无法解析结构体时，尽量按原始字节原样写回。
            return StructValue(
                class_def=ClassDef(field_def.original_type, 0, []),
                fields={"raw": raw_value},
                declared_size=field_def.size,
            )
        class_def = self.typedb.get_class(struct_hash)
        if class_def is None:
            raise PackError(f"struct class not found: {field_def.original_type}")
        fields = raw_value if isinstance(raw_value, dict) else {}
        return StructValue(
            class_def, self._prepare_fields(class_def, fields), field_def.size
        )

    def _default_value(self, field_def: FieldDef) -> Any:
        """根据字段类型生成缺省值。"""
        if field_def.is_array:
            return []
        if field_def.field_type in {"Bool"}:
            return False
        if field_def.field_type in {"F32", "F64"}:
            return 0.0
        if field_def.field_type in {"String", "Resource", "C8"}:
            return ""
        if field_def.field_type in {"Guid", "GameObjectRef", "Uri"}:
            return "00000000-0000-0000-0000-000000000000"
        if field_def.field_type in {"Object", "UserData"}:
            return None
        if field_def.field_type in {
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
            return [0.0 for _ in range(max(field_def.size // 4, 1))]
        return 0
