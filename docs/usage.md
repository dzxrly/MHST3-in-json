# RE User3 JSON 工具

这个项目用于在 RE Engine 游戏的 `.user.3` 数据库文件和 JSON 之间互相转换。核心代码已经整理为可复用的 `pyreuser3` 软件包，方便在不同 RE Engine 游戏或其他项目中直接调用。

当前能力：

- `.user.3 -> JSON`：按 RE_RSZ 模板解析二进制数据库；
- `JSON -> .user.3`：将本项目导出的 JSON 重新封回游戏可读取的 `.user.3`；
- callback 修改流程：找到指定 `.user.3` 后，解析成完整实例表 JSON 传给 callback，由 callback 修改并返回，再自动封包到指定目录；
- 本地 Web UI：`pyreuser3.web` 提供 `.user.3` 解包导出页面；根目录 `web.py` 复用它，并额外扩展当前项目专属的 `.msg.23` 转 JSON 页面；网页不提供封包功能；
- CLI 批处理：`main.py export` 批量导出 `.user.3`，并可同时调用 `REMSG_Converter` 转换 `.msg.23`；
- Rich 批处理输出：底部固定显示当前进度条，上方滚动输出发现文件、开始处理、成功和失败等日志；
- 可配置 magic：`user_magic` 和 `rsz_magic` 都可通过类参数或命令行参数覆盖，默认保留当前项目使用的值；
- 显式依赖：不会自动寻找 `rsz*.json`、`il2cpp_dump.json` 或 `Enums_Internal.json`，调用方必须明确传入所需文件路径。

## 目录结构

```text
main.py            # 命令行入口：export / pack，调用已安装的 pyreuser3
web.py             # 项目 Web 启动器：复用 pyreuser3.web，并额外提供 /msg
msg_converter.py   # .msg.23 转 JSON 的子模块包装
REMSG_Converter/   # .msg.23 转换所需子模块
requirements.txt   # 主项目依赖，包含 pyreuser3、chardet、mmh3
```

核心 `.user.3` 转换代码已经移到 PyPI 包 PyREUser3 中。本仓库不再内置 `pyreuser3` 源码目录；旧的 `user3_exporter.py` 和 `mhst3_json` 兼容入口也已经移除。新项目请直接从 `pyreuser3` 导入。

## 环境与依赖

推荐使用你已经配置好的 conda 环境：

```bash
conda activate rersz
pip install -r requirements.txt
```

如果只把 `pyreuser3` 当作库导入使用，可以直接安装 PyREUser3：

```bash
pip install pyreuser3
```

如果需要用 `main.py export` 或根目录 `web.py` 的 `/msg` 页面转换 `.msg.23`，还需要初始化子模块并安装 `REMSG_Converter` 的依赖：

```bash
git submodule update --init --recursive
pip install -r REMSG_Converter/requirements.txt
```

运行 `.user.3` 转换时，需要你自己准备并显式传入：

- RE_RSZ 模板 JSON，例如 `rszmhst3.json`。它必须是具体文件路径，不能传目录；
- `il2cpp_dump.json`，由 REFramework 导出；
- 从游戏 pak 中解包得到的 `.user.3` 文件或目录。

## 依赖文件准备

不同游戏需要使用对应游戏生成的 RE_RSZ 模板和 `il2cpp_dump.json`。本项目不再绑定 MHST3，也不会按文件名自动搜索模板。

常见准备流程：

1. 使用 REFramework 的 Object Explorer 导出 `il2cpp_dump.json`。
2. 使用 REFramework `reversing/rsz` 目录下的工具，基于游戏 exe dump 和 `il2cpp_dump.json` 生成该游戏的 `rsz*.json` 模板。
3. 使用 `ree-pak-rs` 或其他 RE Engine pak 工具解包目标游戏资源，得到 `.user.3` 文件。

只要模板、dump 和 `.user.3` 属于同一个游戏版本，`pyreuser3` 就可以按这些显式路径工作。

## 本地 Web 使用

根目录的 `web.py` 是当前项目的 Web 启动器：

```bash
python web.py
```

它提供两个页面：

- <http://127.0.0.1:8765/>：复用 `pyreuser3.web` 的 `.user.3` 解包导出页面；
- <http://127.0.0.1:8765/msg>：根目录脚本额外提供的 `.msg.23` 转 JSON 页面。

也可以直接调用库内入口；这个入口只包含 `.user.3` 解包导出功能，不包含 `/msg` 页面：

```bash
python -m pyreuser3.web
```

默认监听地址是 <http://127.0.0.1:8765/>。网页不会预填或自动使用项目根目录；所有文件和目录路径都需要在页面里点击选择按钮指定。`.user.3` 页面只提供解包导出任务：输入数据目录或单个 `.user.3` 文件，填写 RE_RSZ 模板、JSON 输出目录和 `il2cpp_dump.json`。

`/msg` 页面只转换 `.msg.23`。它可以和 `.user.3` 导出使用同一个输出目录，输出形如 `abc.msg.23.json`，不会清空目录，也不会写入或修改 `Enums_Internal.json`。

网页会把任务提交到本地 JSON API 后在后台线程运行，并在右侧显示任务状态、统计结果和日志。单个任务失败不会影响服务本身，错误会显示在任务日志里。

常用启动参数：

```bash
python web.py --host 127.0.0.1 --port 8765 --max-jobs 50
```

| 参数 | 说明 |
| --- | --- |
| `--host` | 监听主机，默认 `127.0.0.1` |
| `--port` | 监听端口，默认 `8765` |
| `--root-dir` | 兼容配置；网页路径仍需通过选择按钮提供绝对路径 |
| `--max-jobs` | 内存中保留的任务数量，默认 `50` |

混合输出目录可以同时包含：

```text
xxx.user.3.json
xxx.msg.23.json
Enums_Internal.json
```

如果后续使用命令行或库 API 封包 `.user.3`，建议选择确实包含 `.user.3.json` 的目录或子目录；网页本身不提供封包任务。

因为 `.user.3` 页面直接加载 Vue 3 和 TypeScript CDN，浏览器需要能访问这些 CDN；后端转换任务仍然只访问本机文件。`/msg` 页面使用内嵌脚本，不依赖额外前端库。

外部 Python 代码也可以直接调用库内入口并修改端口：

```python
from pyreuser3.web import WebSettings, run_server

run_server(WebSettings(port=9000))
```

## 命令行使用

`main.py` 支持两个子命令：

- `export`：导出 `.user.3` 为 JSON，并同时尝试转换输入目录中的 `.msg.23`；
- `pack`：将 `.user.3.json` 或普通 `.json` 封回 `.user.3`。

为了兼容旧用法，不写子命令时默认等同于 `export`。

### 导出 `.user.3` 为 JSON

```bash
python main.py export ^
  -i <解包后的数据根目录> ^
  -s <RE_RSZ模板.json> ^
  -o <JSON输出目录> ^
  -p <il2cpp_dump.json>
```

旧写法也可继续使用：

```bash
python main.py -i <解包后的数据根目录> -s <RE_RSZ模板.json> -o <JSON输出目录> -p <il2cpp_dump.json>
```

参数说明：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `-i`, `--input-dir` | 是 | 输入根目录或单个输入文件，递归查找 `.user.3`；`main.py export` 也会递归查找 `.msg.23` |
| `-s`, `--schema-path`, `--schema-dir` | 是 | RE_RSZ 模板 JSON 文件路径；`--schema-dir` 只是历史别名，实际不能传目录 |
| `-o`, `--output-dir` | 是 | JSON 输出根目录，目录结构会按输入相对路径保留 |
| `-p`, `--il2cpp-dump-path` | 是 | `il2cpp_dump.json` 路径，用于在输出目录生成 `Enums_Internal.json`，并辅助推断枚举上下文 |
| `-d`, `--tree-depth` | 否 | 对象树展开深度，默认 `auto`，也可以传非负整数 |
| `-x`, `--exclude-regex` | 否 | 排除路径的正则，可重复传多次，匹配相对路径 |
| `--user-magic` | 否 | USR 文件 magic，支持十进制或 `0x` 十六进制，默认 `0x00525355` |
| `--rsz-magic` | 否 | RSZ 块 magic，支持十进制或 `0x` 十六进制，默认 `0x005A5352` |

示例：

```bash
python main.py export ^
  -i "D:/game_dump/natives" ^
  -s "D:/schema/rsz_example.json" ^
  -o "D:/json_out" ^
  -p "D:/game/il2cpp_dump.json" ^
  -x "(^|/)Voxel(/|$)"
```

导出结果：

- `abc.user.3 -> abc.user.3.json`
- `abc.msg.23 -> abc.msg.23.json`
- 输出目录会保留输入目录的相对路径。

### 将 JSON 封回 `.user.3`

```bash
python main.py pack ^
  -j <JSON文件或JSON目录> ^
  -s <RE_RSZ模板.json> ^
  -o <user3输出目录>
```

带枚举名反查的写法：

```bash
python main.py pack ^
  -j "D:/json_out" ^
  -s "D:/schema/rsz_example.json" ^
  -o "D:/mod_natives" ^
  -p "D:/game/il2cpp_dump.json"
```

参数说明：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `-j`, `--input-json` | 是 | 单个 JSON 文件或 JSON 根目录 |
| `-s`, `--schema-path`, `--schema-dir` | 是 | RE_RSZ 模板 JSON 文件路径；必须显式传具体文件 |
| `-o`, `--output-dir` | 是 | 封包后的 `.user.3` 输出根目录 |
| `-p`, `--il2cpp-dump-path` | 否 | 用于枚举成员名反查；不传时仍可封包数值型枚举 |
| `-x`, `--exclude-regex` | 否 | 排除 JSON 路径的正则，可重复传多次 |
| `--user-magic` | 否 | 写入 `.user.3` 文件头的 magic，默认 `0x00525355` |
| `--rsz-magic` | 否 | 写入 RSZ 块头的 magic，默认 `0x005A5352` |

输出命名规则：

- `xxx.user.3.json -> xxx.user.3`
- `xxx.json -> xxx.user.3`
- 输入目录会保持相对目录结构输出。

## 作为库调用

最推荐使用 `REUser3Converter`。它封装了导出、解析、封包和 callback 修改流程。

```python
from pyreuser3 import REUser3Converter

converter = REUser3Converter(
    schema_path="D:/schema/rsz_example.json",
    il2cpp_dump_path="D:/game/il2cpp_dump.json",
    tree_depth="auto",
    user_magic=0x00525355,
    rsz_magic=0x005A5352,
)
```

构造参数：

| 参数 | 说明 |
| --- | --- |
| `schema_path` | 必填，RE_RSZ 模板 JSON 文件路径 |
| `il2cpp_dump_path` | 导出、解析、callback 修改时必填；封包时可选，但建议传入 |
| `tree_depth` | 解析对象树深度，默认 `auto` |
| `user_magic` | `.user.3` 文件头 magic，默认 `0x00525355` |
| `rsz_magic` | RSZ 块 magic，默认 `0x005A5352` |

### 单文件和目录转换

```python
# 单文件导出
converter.export_file(
    "D:/game_dump/OtomonData.user.3",
    "D:/json_out/OtomonData.user.3.json",
)

# 单文件封包
converter.pack_file(
    "D:/json_out/OtomonData.user.3.json",
    "D:/mod_natives/OtomonData.user.3",
)

# 批量导出
export_stats = converter.export_directory(
    user3_root="D:/game_dump/natives",
    output_root="D:/json_out",
    exclude_regexes=[r"(^|/)Voxel(/|$)"],
)

# 批量封包
pack_stats = converter.pack_directory(
    json_root="D:/json_out",
    output_root="D:/mod_natives",
)
```

返回值：

- `export_file()`、`pack_file()` 返回输出文件路径；
- `export_directory()`、`pack_directory()` 返回统计字典，例如 `{"total": 10, "success": 10, "failed": 0}`。

### 直接解析或直接得到二进制

```python
data = converter.parse_file("D:/game_dump/OtomonData.user.3")

# 修改 data 后直接得到 .user.3 bytes
binary = converter.pack(data)
```

`parse_file(..., round_floats=True)` 默认会把浮点数四舍五入到 4 位，便于阅读。普通导出和 `parse_file()` 都保持 readable JSON 格式。

如果要修改后再封回，推荐使用完整实例表格式：

```python
data = converter.parse_pack_file("D:/game_dump/OtomonData.user.3")
data["_instances"]["2"]["fields"]["_Value"] = 100
binary = converter.pack(data)
```

完整实例表格式以 `_instances` 为真实数据源，`ref_instance_id` 表示跳转到同一个 `_instances` 编号，而不是“未解析数据”。

### callback 修改并自动封回

`patch_file()` 会执行：

1. 读取 `.user.3`；
2. 解析为完整实例表 JSON；
3. 调用你的 callback；
4. 将 callback 返回的 JSON，或原地修改后的 JSON，封回 `.user.3`；
5. 写入指定输出路径。

callback 可以接收一个参数：

```python
def edit(data):
    data["_instances"]["2"]["fields"]["_Value"] = 100
    return data
```

也可以接收两个参数，第二个参数是源文件路径：

```python
from pathlib import Path
from pyreuser3 import REUser3Converter

converter = REUser3Converter(
    schema_path="D:/schema/rsz_example.json",
    il2cpp_dump_path="D:/game/il2cpp_dump.json",
)

def edit_basic_param(data, source_path: Path):
    root = data["_instances"]["1"]["fields"]
    root["_BodyScale"] = 1.0
    return data

converter.patch_file(
    user3_path="D:/game_dump/natives/STM/GameDesign/Otomon/Ot0160_BasicParam.user.3",
    output_path="D:/mod_natives/STM/GameDesign/Otomon/Ot0160_BasicParam.user.3",
    callback=edit_basic_param,
)
```

如果 callback 原地修改 `data`，可以返回 `None`：

```python
def edit_in_place(data, source_path):
    data["_instances"]["2"]["fields"]["_Flag"] = True
    # 返回 None 表示使用原地修改后的 data
```

### 批量 callback 修改

`patch_directory()` 会递归扫描 `.user.3`，用正则筛选相对路径，并把处理后的文件写入输出根目录下的对应相对位置。

```python
stats = converter.patch_directory(
    user3_root="D:/game_dump/natives",
    output_root="D:/mod_natives",
    include_regexes=[r"Ot0160_BasicParam\.user\.3$"],
    exclude_regexes=[r"(^|/)Backup(/|$)"],
    callback=edit_basic_param,
)

print(stats)
# {"total": 1, "success": 1, "failed": 0, "skipped": 1200}
```

`include_regexes` 和 `exclude_regexes` 都匹配相对路径，并统一使用 `/` 作为路径分隔符。

## 底层类

如果你需要更细的控制，也可以直接使用底层类：

```python
from pyreuser3 import User3Exporter, User3Packer

exporter = User3Exporter(
    user3_root="D:/game_dump/natives",
    schema_dir="D:/schema/rsz_example.json",
    output_root="D:/json_out",
    il2cpp_dump_path="D:/game/il2cpp_dump.json",
)
exporter.run()

packer = User3Packer(
    schema_dir="D:/schema/rsz_example.json",
    il2cpp_dump_path="D:/game/il2cpp_dump.json",
    output_root="D:/mod_natives",
)
packer.pack_directory("D:/json_out", "D:/mod_natives")
```

注意：`schema_dir` 是历史参数名，现在实际含义是“显式 schema JSON 文件路径”，不能传目录。

## JSON 格式约定

导出的 JSON 顶层通常是一个数组，每个元素是一个“类名包裹对象”：

```json
[
  {
    "app.user_data.SomeClass": {
      "_SomeField": 123,
      "_SomeArray": [1, 2, 3]
    }
  }
]
```

封包器支持的常见输入形式：

- 顶层可以是对象或对象数组；
- 类实例通常需要保留 `{ "完整类名": { ...字段... } }` 结构；
- 对象引用可以保留导出的嵌套对象，也可以使用 `{ "ref_instance_id": 1 }`；
- 枚举字段可以使用整数、`"0x10"` 这样的数字字符串、导出的 `"[16] MemberName"` 字符串；
- 如果传入了 `il2cpp_dump_path`，部分枚举字段也可以直接使用成员名字符串；
- 缺失字段会按字段类型写入默认值，例如 `False`、`0`、`0.0`、空字符串、空数组或空引用。

为了提高封回成功率，建议以本项目导出的 JSON 为基础修改，不要手写完整结构。

需要可靠封回时，`parse_pack_file()` 和 callback 修改流程会使用完整实例表格式：

```json
{
  "_format": "re_user3_pack_v1",
  "_roots": [1],
  "_unsupported": [],
  "_instances": {
    "0": {
      "_class": null,
      "_kind": "null"
    },
    "1": {
      "_class": "app.user_data.SomeClass",
      "_hash": "0x12345678",
      "_crc": "0x9abcdef0",
      "fields": {
        "_Child": {
          "ref_instance_id": 2
        }
      }
    },
    "2": {
      "_class": "app.user_data.ChildClass",
      "fields": {
        "_Value": 100
      }
    }
  }
}
```

这种格式下，封包器会校验 `_roots` 和所有 `ref_instance_id` 是否存在于 `_instances`，并拒绝会被静默忽略的未知字段。如果原文件包含当前写入器还不能重建的资源表或 userdata 表，`_unsupported` 会记录原因，封包时会明确失败而不是静默丢数据。

## magic 配置

默认 magic 定义在 `pyreuser3.core`：

```python
USR_MAGIC = 0x00525355
RSZ_MAGIC = 0x005A5352
```

如果目标游戏或文件版本不同，可以在命令行覆盖：

```bash
python main.py export -i <输入> -s <模板.json> -o <输出> -p <il2cpp_dump.json> --user-magic 0x00525355 --rsz-magic 0x005A5352

python main.py pack -j <JSON> -s <模板.json> -o <输出> --user-magic 0x00525355 --rsz-magic 0x005A5352
```

也可以在库调用时覆盖：

```python
converter = REUser3Converter(
    schema_path="D:/schema/rsz_example.json",
    il2cpp_dump_path="D:/game/il2cpp_dump.json",
    user_magic=0x00525355,
    rsz_magic=0x005A5352,
)
```

## `.msg.23` 说明

`pyreuser3` 的核心导出/封包类只处理 `.user.3`。`.msg.23` 的转换由根目录的 `msg_converter.py` 调用 `REMSG_Converter` 子模块完成。

只有使用 `main.py export` 或根目录 `web.py` 的 `/msg` 页面时，程序才会扫描并转换 `.msg.23`。`pyreuser3.web` 库内入口和 `pyreuser3` 的核心转换类都不会触发 `.msg.23` 逻辑，也不需要依赖 `REMSG_Converter`。

## 常见问题

### 为什么传目录给 `-s` 会报错？

新的逻辑要求所有依赖文件都由调用方显式提供，因此 `-s` 必须是具体的 RE_RSZ 模板 JSON 文件。`--schema-dir` 只是旧参数名别名，不代表可以传目录。

### 封包时一定要传 `il2cpp_dump.json` 吗？

不一定。封包器可以只根据 JSON 中的数值写回枚举。但如果 JSON 中使用了枚举成员名，建议传 `-p/--il2cpp-dump-path`，这样可以进行成员名反查。

### 为什么批量封包目录里没有 `.user.3.json` 也会处理 `.json`？

`User3Packer.pack_directory()` 会优先搜索 `*.user.3.json`。如果找不到，再退回搜索普通 `*.json`，并输出为同名 `.user.3`。

### 这个库能兼容所有 RE Engine 游戏吗？

它的目标是尽量通用，但前提是你提供的 RE_RSZ 模板、`il2cpp_dump.json` 和 `.user.3` 来自同一个游戏版本。不同游戏的 RSZ 类型、字段布局和 magic 可能不同，需要用对应游戏生成的依赖文件，并在必要时覆盖 magic。

