import copy
import json
from pathlib import Path

from feedgrab.fetchers.feishu import (
    _decode_sheet_client_vars,
    _merge_sheet_snapshot_blocks,
)


FIXTURE_DIR = Path("output")


def _load_merged_client_vars() -> dict:
    base = json.loads(
        (FIXTURE_DIR / "debug_feishu_req558.json").read_text(encoding="utf-8")
    )["data"]
    merged = copy.deepcopy(base)
    blocks = dict(merged.get("snapshot", {}).get("blocks") or {})
    for name in ("debug_feishu_req600.json", "debug_feishu_req601.json"):
        payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        blocks.update(payload.get("data", {}).get("blocks", {}))
    merged["snapshot"]["blocks"] = blocks
    return merged


def test_decode_sheet_client_vars_keeps_repeated_vendor_cells_aligned():
    cv_data = _load_merged_client_vars()
    cv_data["sheetId"] = "zcYBOU"

    table_md = _decode_sheet_client_vars(cv_data)

    assert table_md is not None
    assert (
        "| gpt-4.1-nano | OpenAI | $0.1 入 / $0.4 出 | 极致性价比 |"
        in table_md
    )
    assert (
        "| nova-micro | AWS | $0.035 入 / $0.14 出 | 最便宜之一 |"
        in table_md
    )


def test_decode_sheet_client_vars_keeps_repeated_type_cells_aligned():
    cv_data = _load_merged_client_vars()
    cv_data["sheetId"] = "eQHT0Y"

    table_md = _decode_sheet_client_vars(cv_data)

    assert table_md is not None
    assert (
        "| gemini-3-pro-image-preview | 图像生成 | Google | $2 入 / $12 出 |"
        in table_md
    )
    assert (
        "| whisper-1 | 语音识别 | OpenAI | $0.006/分钟 |" in table_md
    )


def test_merge_sheet_snapshot_blocks_combines_lazy_loaded_block_payloads():
    cv_data = json.loads(
        (FIXTURE_DIR / "debug_feishu_req558.json").read_text(encoding="utf-8")
    )["data"]
    extra_blocks = {}
    for name in ("debug_feishu_req600.json", "debug_feishu_req601.json"):
        payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        extra_blocks.update(payload.get("data", {}).get("blocks", {}))

    merged = _merge_sheet_snapshot_blocks(cv_data, extra_blocks)

    assert len(merged["snapshot"]["blocks"]) == 32
    assert (
        "block_7626611716637428929_3871632008_144"
        in merged["snapshot"]["blocks"]
    )
