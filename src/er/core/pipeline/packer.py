from typing import cast

from er.core.pipeline.textract import should_ignore
from er.utils.binary import U32, BinaryReader, BinaryWriter, Bytes, de, se
from er.utils.console import console
from er.utils.fs import PathLike, to_path
from er.utils.misc import is_cp932_lead_byte, read_json, write_json

LINE_CHARS = 21  # 每行建议的最大字符数
MAX_LINES = 4  # 最大换行数


def invert_bytes(b: bytes) -> bytes:
    """将字节按位取反"""
    return bytes((~byte_value) & 0xFF for byte_value in b)


def wrap_text_to_list(text: str, limit: int, max_lines: int) -> list[str]:
    """
    处理换行逻辑并返回字符串列表（对应原格式中的 \x00 分隔）：
    1. 【姓名】作为独立的一项。
    2. <> 内的内容不可分割。
    3. 根据 limit 进行分段，且总行数不超过 max_lines。
    """
    if not text:
        return []

    sections = []
    current_pos = 0

    # 1. 处理姓名：如果以【开头，拆分出姓名部分
    if text.startswith("【"):
        bracket_end = text.find("】")
        if bracket_end != -1:
            sections.append(text[: bracket_end + 1])
            current_pos = bracket_end + 1

    remaining_text = text[current_pos:]
    if not remaining_text:
        return sections

    # 2. Tokenize 逻辑
    i = 0
    tokens = []
    while i < len(remaining_text):
        if remaining_text[i] == "<":
            end = remaining_text.find(">", i)
            if end != -1:
                tokens.append(remaining_text[i : end + 1])
                i = end + 1
                continue
        tokens.append(remaining_text[i])
        i += 1

    # 3. Word Wrap 逻辑分段，加入 max_lines 约束
    current_line = ""
    current_count = 0

    for token in tokens:
        token_len = len(token)

        # 判断是否需要换行：
        # 1. 超过字符限制
        # 2. 当前行不为空
        # 3. 当前已分配的段数还没达到 max_lines - 1 (留一个位置给最后一行)
        if (
            current_count + token_len > limit
            and current_line != ""
            and len(sections) < max_lines - 1
        ):
            sections.append(current_line)
            current_line = ""
            current_count = 0

        current_line += token
        current_count += token_len

    if current_line:
        sections.append(current_line)

    return sections


def unpack(input_path: PathLike, out_path: PathLike) -> None:
    """
    解包。

    Args:
        input_path: 输入包路径。
        out_path: 解包输出目录。

    Returns:
        None
    """
    source = to_path(input_path)
    output_path = to_path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. 初始字节翻转处理
    raw_bytes = source.read_bytes()
    b = invert_bytes(raw_bytes)

    # import pathlib
    # pathlib.Path("workspace/decodeed.scr").write_bytes(b)

    reader = BinaryReader(b)

    data_json = {}

    data_json["magic"] = se(reader.read_u16())  
    data_json["ver"] = se(reader.read_u16()) 

    data_json["ctrl"] = []
    for i in range(26):
        data_json["ctrl"].append(se(reader.read_u32()))

    ctrl = lambda i: cast(U32, de(data_json["ctrl"][i]))


    data_json["active_states_init"] = []
    for _ in range(ctrl(0)):
        data_json["active_states_init"].append([
            se(reader.read_u32()),
            se(reader.read_u32())
        ])

    data_json["jump_table"] = []
    for _ in range(ctrl(21)):
        data_json["jump_table"].append(
            se(reader.read_u32())
        )

    data_json["var_pool_init"] = []
    for _ in range(ctrl(1)):
        data_json["var_pool_init"].append(se(reader.read_u32()))

    data_json["var_pool_ext_init"] = []
    for _ in range(ctrl(2)):
        data_json["var_pool_ext_init"].append(se(reader.read_u32()))

    data_json["resource_info"] = []
    for _ in range(ctrl(3)):
        data_json["resource_info"].append([
            se(reader.read_u32()),
            se(reader.read_u32()),
            se(reader.read_u16()),
            se(reader.read_u16())
        ])

    data_json["sprite_frames"] = []
    for _ in range(ctrl(4)):
        data_json["sprite_frames"].append([
            se(reader.read_u32()),
            se(reader.read_u16()),
            se(reader.read_u16()) 
        ])

    data_json["anim_sequences"] = []
    for _ in range(ctrl(5)):
        data_json["anim_sequences"].append([
            se(reader.read_u32()), 
            se(reader.read_u16()), 
            se(reader.read_u16()), 
            se(reader.read_u16()), 
            se(reader.read_u16()), 
            se(reader.read_u16()), 
            se(reader.read_u16()), 
            se(reader.read_u16()), 
            se(reader.read_u16()), 
        ])

    if ctrl(6) > 0:
        str_len = reader.read_u16()
        data_json["res_path_a"] = se(reader.read_bytes(str_len))

    if ctrl(7) > 0:
        res_len = reader.read_u16()
        data_json["res_path_b"] = se(reader.read_bytes(res_len))

    has_meta = reader.read_u32()
    data_json["has_meta"] = se(has_meta)
    assert has_meta == 0

    bytecode_len = reader.read_u32()
    data_json["bytecode_len"] = se(bytecode_len)
    bytecode = reader.read_bytes(bytecode_len)

    assert reader.is_eof()
    data_json["bytecode"] = []

    last_push_offset = 0
    i = 0
    total_len = len(bytecode)

    while i < total_len:
        byte = bytecode[i]

        # 情况 1: 遇到 0x23 (#)
        if byte == 0x23:
            # 将上一个块（从上次压入位置到当前 0x23 之前）压入
            data_json["bytecode"].append({
                "offset": last_push_offset,
                "data": se(Bytes(bytecode[last_push_offset:i])),
            })
            # 更新偏移量，跳过当前 0x23
            last_push_offset = i
            i += 1
            continue

        # 情况 2: 符合 CP932 首字节或为 0x3C (<)
        elif is_cp932_lead_byte(byte) or byte == 0x3C:
            # 寻找以 \x00 结尾的字符串边界
            null_pos = bytecode.find(b"\x00", i)

            if null_pos != -1:
                potential_bytes = bytecode[i:null_pos]
                try:
                    # 尝试以 CP932 解码
                    decoded_str = potential_bytes.decode("cp932")

                    if not should_ignore(decoded_str):
                        if i > last_push_offset:
                            data_json["bytecode"].append({
                                "offset": last_push_offset,
                                "data": se(Bytes(bytecode[last_push_offset:i])),
                            })

                        if (
                            data_json["bytecode"]
                            and "string" in data_json["bytecode"][-1]
                        ):
                            data_json["bytecode"][-1]["string"] += decoded_str
                        else:
                            data_json["bytecode"].append({
                                "offset": i,
                                "string": decoded_str,
                            })

                        # 更新索引：跳过字符串内容和 null 终止符
                        # 同时更新 last_push_offset 避免 0x23 逻辑重复切分已处理区域
                        i = null_pos + 1
                        last_push_offset = i
                        continue
                except UnicodeDecodeError:
                    # 解码失败，忽略，继续作为普通字节扫描
                    pass

        # 默认步进
        i += 1

    if last_push_offset < total_len:
        data_json["bytecode"].append({
            "offset": last_push_offset ,
            "data": se(Bytes(bytecode[last_push_offset:])),
        })

    write_json(out_path, data_json)

    console.print(
        f"[OK] unpack 完成: {source} -> {output_path}",
        style="info",
    )


def pack(input_path: PathLike, out_path: PathLike) -> None:
    """
    将目录内容重新打包。

    Args:
        input_path: 输入json路径。
        out_path: 输出包路径
    """
    input_file = to_path(input_path)
    output_path = to_path(out_path)
    data_json = read_json(input_file)

    # --- 1. 预处理：重新组装 Bytecode 并计算偏移映射 ---
    new_bytecode_body = bytearray()
    old_to_new = {}
    current_new_offset = 0

    for item in data_json["bytecode"]:
        old_offset = item["offset"]
        old_to_new[old_offset] = current_new_offset

        if "string" in item:
            # 使用 wrap_text_to_list 处理换行逻辑
            segments = wrap_text_to_list(item["string"], LINE_CHARS, MAX_LINES)
            for seg in segments:
                content = seg.encode("CP932") + b"\x00"
                new_bytecode_body.extend(content)
                current_new_offset += len(content)
        else:
            # 原始数据块（包含 0x23 开头的块或无法解码的块）
            content = cast(Bytes, de(item["data"]))
            new_bytecode_body.extend(content)
            current_new_offset += len(content)

    # --- 2. 映射更新工具 ---
    def remap_ptr(old_ptr: int) -> int:
        if old_ptr in old_to_new:
            return old_to_new[old_ptr]
        raise ValueError(f"检测到非法指针偏移: {old_ptr}，无法在字节码映射中找到对应的起始地址。")

    # --- 3. 序列化二进制数据 ---
    writer = BinaryWriter()

    # Magic (U16) & Version (U16)
    writer.write_u16(int(de(data_json["magic"])))
    writer.write_u16(int(de(data_json["ver"])))

    # Ctrl (固定 26 个 U32)
    ctrl_values = [int(de(v)) for v in data_json["ctrl"]]
    if len(ctrl_values) != 26:
        raise ValueError(f"Ctrl 列表长度错误：期望 26，实际得到 {len(ctrl_values)}")
    
    for v in ctrl_values:
        writer.write_u32(v)

    # 快捷访问函数
    ctrl = lambda i: ctrl_values[i]

    # Active States Init (ctrl[0] 组 U32, U32)
    # 第一个值是字节码指针，需要重映射
    for pair in data_json["active_states_init"]:
        old_ptr = int(de(pair[0]))
        writer.write_u32(remap_ptr(old_ptr))
        writer.write_u32(int(de(pair[1])))

    # Jump Table (ctrl[21] 个 U32 指针)
    for entry in data_json["jump_table"]:
        old_ptr = int(de(entry))
        writer.write_u32(remap_ptr(old_ptr))

    # Var Pools
    for v in data_json["var_pool_init"]:
        writer.write_u32(int(de(v)))
    for v in data_json["var_pool_ext_init"]:
        writer.write_u32(int(de(v)))

    # Resource Info (ctrl[3] 组 U32, U32, U16, U16)
    for res in data_json["resource_info"]:
        writer.write_u32(int(de(res[0])))
        writer.write_u32(int(de(res[1])))
        writer.write_u16(int(de(res[2])))
        writer.write_u16(int(de(res[3])))

    # Sprite Frames (ctrl[4] 组 U32, U16, U16)
    for frame in data_json["sprite_frames"]:
        writer.write_u32(int(de(frame[0])))
        writer.write_u16(int(de(frame[1])))
        writer.write_u16(int(de(frame[2])))

    # Anim Sequences (ctrl[5] 组 U32 + 8个 U16)
    for anim in data_json["anim_sequences"]:
        writer.write_u32(int(de(anim[0])))
        for i in range(1, 9):
            writer.write_u16(int(de(anim[i])))

    # Resource Paths
    if ctrl(6) > 0:
        res_a = cast(Bytes, de(data_json["res_path_a"]))
        writer.write_u16(len(res_a))
        writer.write_bytes(res_a)

    if ctrl(7) > 0:
        res_b = cast(Bytes, de(data_json["res_path_b"]))
        writer.write_u16(len(res_b))
        writer.write_bytes(res_b)

    # Meta Data (根据 unpack，目前 has_meta 必须为 0)
    has_meta = int(de(data_json["has_meta"]))
    writer.write_u32(has_meta)
    assert has_meta == 0

    # Bytecode (U32 长度 + 内容)
    writer.write_u32(len(new_bytecode_body))
    writer.write_bytes(bytes(new_bytecode_body))

    # --- 4. 最终加密与持久化 ---
    raw_output = writer.to_bytes()
    final_data = invert_bytes(raw_output)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(final_data)

    console.print(
        f"[OK] pack 完成: {input_file} -> {output_path}",
        style="info",
    )