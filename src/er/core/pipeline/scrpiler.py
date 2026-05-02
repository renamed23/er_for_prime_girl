from er.utils.console import console
from er.utils.instructions import (
    Instruction,
    assemble_one_inst,
    byte_slice,
    fix_offset,
    h,
    parse_data,
    string,
    u8,
    u16,
    u32,
)
from er.utils.binary import BinaryReader
from er.utils.fs import PathLike, collect_files, to_path
from er.utils.misc import read_json, write_json


FIX_INST_MAP = {
    "06": [0],  # TODO: 示例修复索引
}

INST_MAP = {
    # TODO: 示例OP
    h("01"): [u8, u16, u16, u32, u8],
    h("06"): [u32, u8.eq(0x0)],
    h("48"): [u8, u16.repeat(2), u32, u8, string],
    h("4A"): [byte_slice.args(4)],
}


def decompile(input_path: PathLike, output_path: PathLike) -> None:
    """反编译：将二进制文件转换为JSON"""
    input_root = to_path(input_path)
    output_root = to_path(output_path)
    files = collect_files(input_root)

    for file in files:
        reader = BinaryReader(file.read_bytes())

        insts = parse_data(
            {
                "file_name": str(file),
                "offset": 0,
            },
            reader,
            INST_MAP,
        )

        assert reader.is_eof()

        # 保存为JSON
        rel_path = file.relative_to(input_root)
        out_file = output_root / f"{rel_path.as_posix()}.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)

        write_json(out_file, insts)

    console.print(f"[OK] decompile 完成: {input_path} -> {output_path}", style="info")


def compile(input_path: PathLike, output_path: PathLike) -> None:
    """编译：将JSON转换回二进制文件"""
    input_root = to_path(input_path)
    output_root = to_path(output_path)
    files = collect_files(input_root, "json")

    for file in files:
        insts: list[Instruction] = read_json(file)

        # ========= 第一步：assemble instruction，计算新 offset =========
        old2new = {}  # old_offset -> new_offset
        cursor = 0

        for inst in insts:
            old_offset = inst["offset"]
            b = assemble_one_inst(inst)

            old2new[old_offset] = cursor
            cursor += len(b)

        # ========= 第二步：修复指令的偏移 =========
        insts = fix_offset(str(file), insts, old2new, FIX_INST_MAP)

        # ========= 第三步：assemble 修复过偏移的指令 =========
        new_blob = b"".join([assemble_one_inst(inst) for inst in insts])

        # 保存二进制文件
        rel_path = file.relative_to(input_root)
        out_file = output_root / rel_path.with_suffix("")
        out_file.parent.mkdir(parents=True, exist_ok=True)

        out_file.write_bytes(new_blob)

    console.print(f"[OK] compile 完成: {input_path} -> {output_path}", style="info")
