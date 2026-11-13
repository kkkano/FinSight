"""仅接收有限尺寸的本轮PNG；不读取用户URL或宿主路径。"""
from __future__ import annotations
import base64
import struct
import zlib


def validate_png_data_url(value: str) -> tuple[int, int]:
    prefix = "data:image/png;base64,"
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) > 2_800_000:
        raise ValueError("仅支持2MiB以内的PNG图片")
    try:
        raw = base64.b64decode(value[len(prefix):], validate=True)
    except (ValueError, base64.binascii.Error):
        raise ValueError("图片编码无效") from None
    if (len(raw) > 2 * 1024 * 1024 or len(raw) < 33 or raw[:8] != b"\x89PNG\r\n\x1a\n"
            or raw[12:16] != b"IHDR" or struct.unpack(">I", raw[8:12])[0] != 13
            or zlib.crc32(raw[12:29]) & 0xffffffff != struct.unpack(">I", raw[29:33])[0]):
        raise ValueError("PNG头部无效")
    width, height = struct.unpack(">II", raw[16:24])
    if not width or not height or width * height > 8_000_000 or max(width, height) > 8192:
        raise ValueError("图片尺寸超过限制")
    return width, height

