from pathlib import Path
import re

from er.core.gal_json import GalJson
from er.utils.console import console
from er.utils.fs import PathLike, collect_files, to_path
from er.utils.misc import ensure_str, read_json, write_json


def should_ignore(s: str) -> bool:
    if s is None:
        return True
    s = s.strip()
    if s == "":
        return True
    if s.isascii():
        return True
    # 检查Unicode私有区域字符和半角日语字符
    for char in s:
        code_point = ord(char)
        # 私有使用区: U+E000 - U+F8FF
        if 0xE000 <= code_point <= 0xF8FF:
            return True
        # 补充私有使用区-A: U+F0000 - U+FFFFF
        if 0xF0000 <= code_point <= 0xFFFFF:
            return True
        # 补充私有使用区-B: U+100000 - U+10FFFF
        if 0x100000 <= code_point <= 0x10FFFF:
            return True
        # 半角日语字符(标点+片假名): U+FF61 - U+FF9F
        if 0xFF61 <= code_point <= 0xFF9F:
            return True

        # 控制字符: C0 (0-31, 127) 和 C1 (128-159)
        if code_point < 32 and char not in ("\n", "\r", "\t"):
            return True
        if code_point == 127 or (128 <= code_point <= 159):
            return True
    return False


def _extract_from_script(
    script_path: Path,
    gal_json: GalJson,
) -> None:
    """
    从单个脚本中提取可翻译条目。

    Args:
        script_path: 输入脚本路径。
        gal_json: 原文容器。

    Returns:
        None
    """
    script: dict = read_json(script_path)

    for item in script["bytecode"]:
        if "string" not in item:
            continue

        s = ensure_str(item["string"])

        # 匹配 【名字】正文 的格式
        match = re.match(r"^【(.*?)】(.*)$", s)
        if match:
            name = match.group(1)
            message = match.group(2)
            gal_json.add_item({"name": name, "message": message})
        else:
            # 无名字对话或纯文本
            gal_json.add_item({"message": s})


def _apply_translation_to_script(
    script_path: Path,
    gal_json: GalJson,
    output_root: Path,
    base_root: Path,
) -> None:
    """
    将译文应用到单个脚本。

    Args:
        script_path: 输入脚本路径。
        gal_json: 译文数据容器。
        output_root: 输出目录。
        base_root: 输入根目录，用于计算相对路径。

    Returns:
        None
    """
    script: dict = read_json(script_path)

    for item in script["bytecode"]:
        if "string" not in item:
            continue

        trans_item = gal_json.pop_next_item()
        name = trans_item.get("name")
        message = ensure_str(trans_item.get("message"))

        if name:
            # 翻译并重新构造 【姓名】正文 格式
            translated_name = ensure_str(name)
            item["string"] = f"【{translated_name}】{message}"
        else:
            # 直接替换正文
            item["string"] = message

    output_path = output_root / script_path.relative_to(base_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, script)


def extract(input_dir: PathLike, gal_json: GalJson) -> None:
    """
    提取目录下脚本文本到容器中。

    Args:
        input_dir: 反汇编后的脚本目录（json）。
        gal_json: 原文容器。

    Returns:
        None
    """
    source_root = to_path(input_dir)
    files = collect_files(source_root, "json")

    for file in files:
        _extract_from_script(file, gal_json)

    console.print(
        f"[OK] 文本提取完成: {source_root} ({len(files)} files, {gal_json.total_count()} items)",
        style="info",
    )


def apply(input_dir: PathLike, gal_json: GalJson, output_dir: PathLike) -> None:
    """
    将 GalJson 中的译文应用到原始脚本，新文件输出到新目录中

    Args:
        input_dir: 原始脚本目录（json）。
        gal_json: 译文容器。
        output_dir: 替换后脚本输出目录。

    Returns:
        None
    """
    source_root = to_path(input_dir)
    output_root = to_path(output_dir)

    files = collect_files(source_root, "json")
    gal_json.reset_cursor()

    for file in files:
        _apply_translation_to_script(
            script_path=file,
            gal_json=gal_json,
            output_root=output_root,
            base_root=source_root,
        )

    if not gal_json.is_ran_out():
        raise ValueError(
            "替换完成但仍有未消费译文条目："
            f"remaining={gal_json.remaining_count()}, consumed={gal_json.consumed_count()}, "
            f"total={gal_json.total_count()}"
        )

    console.print(
        f"[OK] 文本替换完成: {source_root} -> {output_root} ({len(files)} files)",
        style="info",
    )
