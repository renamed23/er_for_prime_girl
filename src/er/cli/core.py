import os

from er.core import text_hook
from er.core import config
from er.core.config import FEATURES
from er.core.gal_json import GalJson
from er.core.pipeline import packer, textract
from er.processor.mapping import ReplacementPoolBuilder
from er.utils import fs
from er.utils.console import console


def extract() -> None:
    """提取(extract)相关逻辑"""
    console.print("执行提取...", style="info")

    packer.unpack("workspace/p_girl.scr", "workspace/raw/p_girl.json")

    gal_json = GalJson()
    textract.extract("workspace/raw", gal_json)

    (
        gal_json
        .apply_remove_fullwidth_spaces()
        # .apply_transform(lambda s: s.replace("\\n", ""))
        # .apply_escape_backslashes()
        .apply_current_to_raw_fields()
        .apply_add_tags()
        .save_to_path("workspace/raw_json/game_text.json")
    )

    # exe_gal_json = GalJson()
    # exe_textract.extract("workspace/anos3_raw.exe", exe_gal_json)
    # exe_gal_json.save_to_path("workspace/raw_json/exe_text.json")

    console.print("提取完成", style="info")


def replace(check: bool = True) -> None:
    """替换(replace)相关逻辑"""
    console.print("执行替换...", style="info")

    # exe_gal_json = GalJson.load_from_path("workspace/translated_json/exe_text.json")
    gal_json = GalJson.load_from_path("workspace/translated_json/game_text.json")
    gal_json.apply_remove_tags()

    if check:
        (
            gal_json
            .check_pua_characters()
            .check_korean_characters()
            .check_japanese_characters()
            .check_duplicate_quotes()
            .check_length_discrepancy()
            .check_quote_consistency()
            .check_invisible_characters()
            .check_forbidden_words()
            .check_unpaired_quotes()
            .check_max_text_len(28 * 4)
            .check_angle_brackets()
            # .check_font_glyphs("assets/font/ZiYueYingYinSong-2.ttf")
            # .check_per_line_limit()
            .ok_or_print_error_and_exit()
        )

    (
        gal_json
        # .apply_unescape_backslashes()
        .apply_restore_whitespace()
        .apply_replace_rare_characters()
        .apply_replace_nested_brackets()
        .apply_replace_quotation_marks()
        # .apply_map_gbk_unsupported_chars()
        .apply_fullwidth(r"(<[^>]+>)")
    )

    pool = (
        ReplacementPoolBuilder()
        .exclude_from_gal_text(gal_json)
        # .exclude_from_gal_text(exe_gal_json)
        .build()
    )
    gal_json.apply_mapping(pool)
    # exe_gal_json.apply_mapping(pool)
    pool.save_mapping_to_path("workspace/generated/mapping.json")

    # if check:
    #     exe_gal_json.check_keep_len_limit().ok_or_print_error_and_exit()

    textract.apply("workspace/raw", gal_json, "workspace/generated/translated")

    packer.pack(
        "workspace/generated/translated/p_girl.json",
        "workspace/generated/dist/p_girl_chs.scr",
    )

    fs.merge_dir("assets/dist_extra", "workspace/generated/dist", overwrite=True)
    config.generate_config_files()

    fs.copy_entry("assets/raw_text", "workspace/generated/raw_text", overwrite=True)
    fs.copy_entry(
        "assets/translated_text", "workspace/generated/translated_text", overwrite=True
    )

    text_hook.TextHookBuilder(os.environ["TEXT_HOOK_PROJECT_PATH"]).build(
        FEATURES, panic="immediate-abort", output_name="p_girl_chs.dll"
    )

    console.print("替换完成", style="info")


def fix_translated() -> None:
    """修复翻译JSON(fix_translated)的逻辑"""
    gal_json = GalJson.load_from_path("workspace/translated_json/game_text.json")
    (
        gal_json
        .apply_fullwidth(r"(<[^>]+>)")
        .apply_replace_standard_quotes()
        .apply_align_leading_whitespace()
        .apply_align_brackets_closure()
        .save_to_path("workspace/translated_json/game_text.json")
    )
