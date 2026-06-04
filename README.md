# RE User3 JSON 工具

这个仓库用于解析 RE Engine 游戏的 `.user.3` 数据库文件，并在 `.user.3` 与 JSON 之间双向转换。核心能力已经封装到 [re_user3](./re_user3) 包中，可以作为网页工具、命令行工具使用，也可以在其他项目里直接导入调用。

## 文档导航

- [从 0 开始准备模板并导出数据](./docs/tutorial.md)：保留原有逆向、dump、RE_RSZ 模板生成、pak 解包教程，并把最终执行仓库代码的部分更新为新的命令行和库调用方式。
- [通用使用手册](./docs/usage.md)：集中说明 `re_user3` 包结构、Web 入口、`main.py export/pack` 命令、`REUser3Converter` API、callback 修改流程、JSON 格式约定和 magic 配置。

## 当前能力

- `.user.3 -> JSON`：按显式传入的 RE_RSZ 模板解析二进制数据库。
- `JSON -> .user.3`：将本项目导出的 JSON 重新封回游戏可读取的 `.user.3`。
- callback 修改流程：解析指定 `.user.3` 为完整实例表 JSON，交给用户函数修改，再自动封包输出。
- 通用化参数：模板、`il2cpp_dump.json`、magic 均由调用方显式传入或配置。
- `.msg.23` 批量导出：通过 `main.py export` 调用 `REMSG_Converter` 子模块完成。
- 本地 Web UI：`web.py` 复用 `re_user3.web` 提供 `.user.3` 解包导出页面，并在根脚本中额外提供 `.msg.23` 转 JSON 页面；网页不提供封包功能。
- Rich 批处理输出：底部固定显示当前进度条，上方滚动输出文件级执行日志。

## 快速开始

需要 Python 3.9 或更高版本。

```bash
conda activate rersz
pip install -r requirements.txt
pip install -r REMSG_Converter/requirements.txt
```

如果只在其他项目中导入 `re_user3` 库，不需要安装整仓库依赖，可只安装库内依赖：

```bash
pip install -r re_user3/requirements.txt
```

启动本地网页：

```bash
python web.py
```

也可以直接启动库内入口；这个入口只包含 `.user.3` 解包导出 Web 功能：

```bash
python -m re_user3.web
```

默认地址为 <http://127.0.0.1:8765/>。网页不会预填或自动使用项目根目录；所有文件和目录路径都需要在页面里点击选择按钮指定。
端口可通过 `python web.py --port 9000` 修改；如果只需要库内 `.user.3` 解包导出 Web 入口，也可在外部代码中调用 `run_server(WebSettings(port=9000))`。
根目录 `web.py` 还提供 `.msg.23` 转换页面：<http://127.0.0.1:8765/msg>。它可以和 `.user.3` 导出使用同一个输出目录，不会清空输出目录，只会写入或覆盖对应的 `.msg.23.json` 文件。

命令行导出 `.user.3` 和 `.msg.23`：

```bash
python main.py export -i <解包后的数据根目录> -s <RE_RSZ模板.json> -o <JSON输出目录> -p <il2cpp_dump.json>
```

将 JSON 封回 `.user.3`：

```bash
python main.py pack -j <JSON文件或目录> -s <RE_RSZ模板.json> -o <user3输出目录> -p <il2cpp_dump.json>
```

作为库调用：

```python
from re_user3 import REUser3Converter

converter = REUser3Converter(
    schema_path="D:/schema/rsz_example.json",
    il2cpp_dump_path="D:/game/il2cpp_dump.json",
)

converter.export_file("input/OtomonData.user.3", "json/OtomonData.user.3.json")
converter.pack_file("json/OtomonData.user.3.json", "mod/OtomonData.user.3")
```

普通导出始终保持便于阅读的 readable JSON。需要修改后稳定封回时，库内的
`parse_pack_file()` 和 `patch_file()` 会使用 `_format: "re_user3_pack_v1"` 的完整实例表结构。

## 重要约定

- `-s/--schema-path` 必须传具体的 RE_RSZ 模板 JSON 文件，不能传目录。
- 程序不会自动寻找 `rsz*.json`、`il2cpp_dump.json` 或 `Enums_Internal.json`。
- 默认 magic 为 `USR_MAGIC = 0x00525355`、`RSZ_MAGIC = 0x005A5352`，可通过命令行或类参数覆盖。
- 旧的 `user3_exporter.py` 和 `mhst3_json` 兼容入口已经移除，新代码请统一从 `re_user3` 导入。
