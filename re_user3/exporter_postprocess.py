"""导出 JSON 的枚举后处理和展示清理逻辑。"""

from __future__ import annotations

from typing import Any


class ExporterPostprocessMixin:
    """负责把原始解析结果整理成人类更容易修改的 JSON。"""

    def _fixed_type_candidates(self, type_name: str) -> list[str]:
        """根据类型名生成可能的固定枚举类型名。

        Args:
            type_name: 源类型名。

        Returns:
            去重后的候选固定枚举类型名。
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
        """在可能时把类型名规范化为已知固定枚举类型。

        Args:
            type_name: 源类型名。

        Returns:
            已知固定枚举类型；无法匹配时返回原值。
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
        """把数值映射成固定枚举的可读标签。

        Args:
            fixed_enum_type: 固定枚举类型名。
            value: 原始数值。

        Returns:
            能匹配时返回 `[值] 名称`，否则返回原数值。
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
        """判断字典键是否像完整类名。

        Args:
            text: 字典键文本。

        Returns:
            类名通常包含命名空间点号且不是字段名。
        """
        return "." in text and not text.startswith("_")

    @staticmethod
    def _class_name_variants(class_name: str | None) -> list[str]:
        """生成不同 dump 中常见的类名别名。

        Args:
            class_name: 当前类名。

        Returns:
            包含 `cData` / `cParam` 互换别名的列表。
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
        """解析字段对应的固定枚举类型提示。

        Args:
            current_class: 当前类上下文。
            field_name: 字段名。

        Returns:
            固定枚举类型名；无法推断时返回 `None`。
        """
        for class_variant in self._class_name_variants(current_class):
            class_fields = self.class_field_fixed_types.get(class_variant, {})
            fixed_field_type = class_fields.get(field_name)
            if fixed_field_type:
                return fixed_field_type
        return None

    def _resolve_class_default_enum(self, class_name: str | None) -> str | None:
        """解析泛型参数容器类的默认枚举类型。

        Args:
            class_name: 类名。

        Returns:
            默认固定枚举类型；无法推断时返回 `None`。
        """
        for class_variant in self._class_name_variants(class_name):
            enum_type = self.param_type_default_enum.get(class_variant)
            if enum_type is not None:
                return enum_type
        return None

    @staticmethod
    def _is_enum_value_field(field_name: str | None) -> bool:
        """判断字段名是否像枚举值字段。

        Args:
            field_name: 字段名。

        Returns:
            看起来像 `value`、`fixedid` 或 `xxxid` 时返回 `True`。
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
        """递归规范化类名，并把固定枚举数值转成可读标签。

        Args:
            value: 当前节点。
            current_class: 当前类上下文。
            scalar_enum_hint: 当前标量值可使用的枚举类型提示。
            class_default_enum: 当前类作用域的默认枚举类型。
            container_param_rule: 泛型容器推断出的参数与枚举类型关系。
            field_name: 当前字段名。

        Returns:
            转换后的节点。
        """
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            dict_level_enum_hint: str | None = None
            enum_name = value.get("_EnumName")
            fixed_id = value.get("_FixedID")
            if isinstance(enum_name, str) and isinstance(fixed_id, int):
                # 一些对象同时保存 `_EnumName` 和 `_FixedID`，可用二者反推
                # 字段所属的固定枚举类型。
                dict_level_enum_hint = self._infer_enum_type_from_member_and_value(
                    enum_name, fixed_id
                )
            for k, v in value.items():
                if (
                    isinstance(k, str)
                    and self._looks_like_class_name(k)
                    and isinstance(v, dict)
                ):
                    # 类名节点是紧凑 JSON 的边界，进入子对象时刷新类上下文。
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
                        # 泛型容器的参数类型命中时，参数对象内部默认使用容器枚举。
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
                    # 优先使用 il2cpp/RSZ 上下文明确指出的字段枚举类型。
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
        """移除内部索引并拍平仅包含 `value` 的包装对象。"""
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

    def _round_export_floats(self, value: Any) -> Any:
        """递归圆整浮点数，让导出的 JSON 更适合人工阅读。

        Args:
            value: 任意嵌套值。

        Returns:
            浮点数被圆整到 4 位后的值。
        """
        if isinstance(value, dict):
            return {k: self._round_export_floats(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._round_export_floats(item) for item in value]
        if isinstance(value, float):
            return round(value, 4)
        return value
