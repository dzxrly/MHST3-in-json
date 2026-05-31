"""完整 `.user.3` 文件结构解析逻辑。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core import BinaryReader, ParseError, align


class ExporterUser3ParserMixin:
    """负责读取 USR/RSZ 头、实例表和根对象列表。"""

    def _parse_user3(self, user3_path: Path) -> list[dict[str, Any]]:
        """解析完整 `.user.3` 文件并构造成紧凑对象树。

        参数：
            user3_path: 源 `.user.3` 文件路径。

        返回：
            以类名包裹的紧凑对象树列表。
        """
        reader = BinaryReader(user3_path.read_bytes())

        # `.user.3` 最外层是 USR 头，magic 可由用户覆盖以兼容不同游戏。
        magic = reader.read_u32()
        if magic != self.user_magic:
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
                # 部分文件在 USR 头中带有外部 userdata 路径表。
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
                # 路径表解析失败不影响主 RSZ 数据块，降级为空列表。
                header_userdata_infos = []

        rsz_start = usr_header["data_offset"]

        # 数据偏移指向内嵌 RSZ 块；后续偏移大多是相对 RSZ 起点。
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
        if rsz_header["magic"] != self.rsz_magic:
            raise ParseError(
                f"RSZ magic mismatch at data_offset: {rsz_header['magic']}"
            )

        # 对象表保存根对象实例编号，是构造最终 JSON 根节点的首选来源。
        reader.seek(rsz_start + 48)
        object_table = [
            reader.read_s32() for _i in range(max(rsz_header["object_count"], 0))
        ]
        object_table_set = set(object_table)

        instance_infos: list[dict[str, Any]] = []
        reader.seek(rsz_start + rsz_header["instance_offset"])
        for idx in range(max(rsz_header["instance_count"], 0)):
            # 实例表只保存类型哈希和 CRC，真正字段数据在数据偏移后连续存放。
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
                # RSZ 用户数据表表示对其他用户数据文件的引用。
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
                # 用户数据表异常时仍尝试解析内联实例，避免整文件失败。
                rsz_userdata_instance_ids = []
                rsz_userdata_path_by_instance = {}
        rsz_userdata_instance_set = set(rsz_userdata_instance_ids)

        parsed_instances: list[dict[str, Any]] = []
        reader.seek(rsz_start + rsz_header["data_offset"])
        for idx, info in enumerate(instance_infos):
            class_hash = int(info["hash"])
            if idx == 0:
                # RSZ 实例 0 是固定空槽，引用 0 表示空引用。
                parsed_instances.append(
                    {
                        "index": idx,
                        "class_name": info["class_name"],
                        "note": "null instance slot",
                    }
                )
                continue
            if idx in rsz_userdata_instance_set:
                # 外部用户数据引用不在当前数据段内展开，只记录路径和实例编号。
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
                # 模板不认识的类型无法解析字段，但保留元数据方便定位。
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
                # 实例数据没有显式尺寸，读取前按首字段对齐来同步游标。
                reader.seek(
                    align(reader.tell(), 4 if first.is_array else max(first.align, 1))
                )
            start_pos = reader.tell()
            try:
                parsed_instances.append(
                    {"index": idx, "data": self._parse_instance(reader, class_hash)}
                )
            except Exception as exc:
                # 某个实例解析失败时，尽量按估算最小尺寸跳过，继续解析后续实例。
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
            # 某些文件对象表为空，需要从引用关系推断根节点。
            object_roots = self._infer_roots_when_object_table_empty(
                idx_map, parsed_instances
            )
        if not object_roots and rsz_userdata_instance_ids:
            # 如果只存在用户数据引用，也可把这些引用作为根节点导出。
            object_roots = sorted(
                set(
                    i
                    for i in rsz_userdata_instance_ids
                    if i in instance_info_map and i > 0
                )
            )
        if not object_roots:
            # 最后兜底：导出所有非空实例，保证信息尽可能不丢失。
            object_roots = sorted(i for i in instance_info_map.keys() if i > 0)
        depth = (
            self._auto_pick_tree_depth(parsed_instances, object_roots)
            if self.tree_depth == "auto"
            else self.tree_depth
        )
        object_trees = [
            # 从根实例开始展开引用，生成更适合人工修改的嵌套 JSON。
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
            # 对只包含头部用户数据信息的文件，仍返回可读的引用列表。
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
