"""图片归一化：把不可信的原始字节规整成模型 API 可接受、尺寸可控的图片。

消息段里的图片完全由客户端控制，可能是不被模型接受的格式（avif / heic / bmp），
也可能是几千像素的超大图。本模块在入库前统一处理：

- 用 Pillow **真正解码一次**：既是尺寸探测，也是内容真实性校验——文件头嗅探可以被
  伪造（在文本文件前面贴 8 个字节的 PNG 魔数即可），只有解码才能识破；
- 输入格式走白名单，避免把 Pillow 的全部解码器暴露给不可信数据；
- 尺寸超出配置上限时等比缩放；
- 输出格式收敛到模型明确支持的 png / jpeg / gif / webp；
- 体积超出 ``max_bytes`` 时先降质、再降尺寸地反复压缩，直到达标；
- **已经合格的图片原样返回**，不做重编码：既避免无谓的画质损失，也省掉一次编码开销。

只做缩小不做放大，因此不会因为配置把图片"拉大"。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Final

from nonebot import logger
from PIL import Image, UnidentifiedImageError

__all__ = ["NormalizeResult", "normalize_image"]

#  模型 API 明确接受的格式。其余格式一律转码，否则请求会被服务端以 400 拒绝。
_SUPPORTED_MIMES: Final[frozenset[str]] = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp"}
)

#  允许 Pillow 解码的输入格式白名单：只收常见的真实图片格式，不放任全部解码器
_ACCEPTED_FORMATS: Final[frozenset[str]] = frozenset(
    {"PNG", "JPEG", "MPO", "GIF", "WEBP", "BMP", "AVIF"}
)

#  Pillow 的 format 名 -> MIME（MPO 是手机的连拍 JPEG，按 jpeg 处理）
_FORMAT_MIMES: Final[dict[str, str]] = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "MPO": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
    "AVIF": "image/avif",
}

#  解码后允许的最大像素数（约 32MP；6000×4000 的单反照片约 24MP），拦住解压炸弹。
#  纯色 PNG 可以用几十 KB 声明上亿像素，不设这道闸就是一次内存放大攻击。
_MAX_PIXELS: Final[int] = 32_000_000
#  可按比例降采样解码的格式：JPEG 能直接跳到 1/2、1/4、1/8 尺度，省掉大部分解码开销
_DRAFTABLE_FORMATS: Final[frozenset[str]] = frozenset({"JPEG", "MPO"})
#  有损格式：体积超标时可以靠降质换体积
_LOSSY_MIMES: Final[frozenset[str]] = frozenset({"image/jpeg", "image/webp"})
#  转码为有损格式时的默认质量
_JPEG_QUALITY: Final[int] = 85
_WEBP_QUALITY: Final[int] = 85
#  为达标而逐步尝试的质量档（仅对有损格式有意义）
_FIT_QUALITY_LADDER: Final[tuple[int, ...]] = (85, 70, 55, 40)
#  压缩到达标的最大轮数（每轮先降质，再降尺寸）
_FIT_MAX_ROUNDS: Final[int] = 4
#  按面积比估算缩放系数时留出的余量，避免刚好卡在边界反复重试
_FIT_SAFETY: Final[float] = 0.9
#  缩放系数下限，避免为了达标把图缩成马赛克
_FIT_MIN_SCALE: Final[float] = 0.25


@dataclass(frozen=True, slots=True)
class NormalizeResult:
    """归一化结果。成功时 ``raw`` / ``mime`` 有值，失败时 ``reason`` 是一句简短说明。"""

    raw: bytes = b""
    mime: str = ""
    reason: str = ""

    @property
    def ok(self) -> bool:
        """是否得到了可用的图片二进制与 MIME。"""
        return bool(self.raw) and bool(self.mime)


def _resize_box(
    width: int, height: int, max_width: int, max_height: int
) -> tuple[int, int] | None:
    """计算等比缩放的目标框；无需缩放时返回 ``None``。"""
    box_width = max_width if max_width > 0 else width
    box_height = max_height if max_height > 0 else height
    if width <= box_width and height <= box_height:
        return None
    return box_width, box_height


def _has_alpha(img: Image.Image) -> bool:
    """判断图片是否带透明通道（决定转码为 PNG 还是 JPEG）。"""
    if img.mode in ("RGBA", "LA", "PA"):
        return True
    return img.mode == "P" and "transparency" in img.info


def _pick_mime(img: Image.Image, source_mime: str) -> str:
    """决定输出格式。

    源格式本身受支持时保留原格式：把无损截图硬转成有损 JPEG 往往**又大又糊**
    （纯色块 PNG 转 JPEG 后体积反而可能变大）。其余格式（bmp/avif/gif/mpo）
    按透明通道落到 PNG 或 JPEG。
    """
    if source_mime in _SUPPORTED_MIMES and source_mime != "image/gif":
        return source_mime
    return "image/png" if _has_alpha(img) else "image/jpeg"


def _encode_bytes(img: Image.Image, mime: str, quality: int | None) -> bytes:
    """按指定格式编码为字节；``quality`` 仅对有损格式有效。

    走这条路径说明图片已被改动（缩放 / 转码 / 压缩），因此动图只保留当前帧；
    未经改动的动图会在 :func:`normalize_image` 里原样返回，不受影响。
    """
    alpha = _has_alpha(img)
    buffer = io.BytesIO()
    if mime == "image/jpeg":
        jpeg_quality = _JPEG_QUALITY if quality is None else quality
        img.convert("RGB").save(
            buffer, format="JPEG", quality=jpeg_quality, optimize=True
        )
    elif mime == "image/webp":
        webp_quality = _WEBP_QUALITY if quality is None else quality
        img.convert("RGBA" if alpha else "RGB").save(
            buffer, format="WEBP", quality=webp_quality
        )
    else:
        img.convert("RGBA" if alpha else "RGB").save(
            buffer, format="PNG", optimize=True
        )
    return buffer.getvalue()


def _fit(img: Image.Image, source_mime: str, max_bytes: int) -> NormalizeResult:
    """把图片压缩到 ``max_bytes`` 以内：先降质，再降尺寸，反复尝试。

    编码体积大致与像素数成正比，所以尺寸缩放系数按面积比估算，并留出余量。
    PNG 这类无损格式没有质量旋钮，只能靠降尺寸。
    """
    mime = _pick_mime(img, source_mime)
    qualities: tuple[int | None, ...] = (
        _FIT_QUALITY_LADDER if mime in _LOSSY_MIMES else (None,)
    )
    work = img
    encoded = b""
    for _ in range(_FIT_MAX_ROUNDS):
        for quality in qualities:
            encoded = _encode_bytes(work, mime, quality)
            if len(encoded) <= max_bytes:
                return NormalizeResult(raw=encoded, mime=mime)
        ratio = max_bytes / len(encoded)
        scale = max(_FIT_MIN_SCALE, (ratio * _FIT_SAFETY) ** 0.5)
        resized = (max(1, int(work.size[0] * scale)), max(1, int(work.size[1] * scale)))
        if resized == work.size:
            break
        work = work.resize(resized, Image.Resampling.LANCZOS)
        logger.debug(f"图片压缩未达标，继续缩放至 {work.size[0]}×{work.size[1]}")
    return NormalizeResult(reason=f"压缩后仍超出上限 {max_bytes / 1024:.1f}KB")


def normalize_image(
    raw: bytes, *, max_width: int, max_height: int, max_bytes: int = 0
) -> NormalizeResult:
    """把原始字节规整成模型可用的图片（同步、CPU 密集，调用方应放进线程执行）。

    Args:
        raw: 原始图片字节。
        max_width: 允许的最大宽度（像素），``<=0`` 表示不限制。
        max_height: 允许的最大高度（像素），``<=0`` 表示不限制。
        max_bytes: 允许的最大体积（字节），``<=0`` 表示不限制；超出时反复压缩到达标。

    Returns:
        归一化结果。已经合格（格式受支持、尺寸与体积均合规）时原样返回 ``raw``。
    """
    if not raw:
        return NormalizeResult(reason="图片内容为空")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            fmt = (img.format or "").upper()
            if fmt not in _ACCEPTED_FORMATS:
                return NormalizeResult(reason=f"不支持的图片格式（{fmt or '未知'}）")
            width, height = img.size
            if width <= 0 or height <= 0:
                return NormalizeResult(reason="图片尺寸非法")
            if width * height > _MAX_PIXELS:
                return NormalizeResult(reason=f"图片像素数过大（{width}×{height}）")
            mime = _FORMAT_MIMES[fmt]
            box = _resize_box(width, height, max_width, max_height)
            needs_resize = box is not None
            if needs_resize and fmt in _DRAFTABLE_FORMATS:
                #  JPEG 允许按比例降采样解码：大图能省掉大部分解码时间与内存
                img.draft("RGB", box)
            #  open() 只读文件头，必须 load() 才真正解码，也才能识破伪装成图片的数据
            img.load()
            within_bytes = max_bytes <= 0 or len(raw) <= max_bytes
            if not needs_resize and mime in _SUPPORTED_MIMES and within_bytes:
                return NormalizeResult(raw=raw, mime=mime)
            if needs_resize:
                img.thumbnail(box, Image.Resampling.LANCZOS)
                logger.debug(f"图片已等比缩放至 {img.size[0]}×{img.size[1]}")
            elif mime not in _SUPPORTED_MIMES:
                logger.debug(f"图片格式 {mime} 不被模型支持，已转码")
            else:
                logger.debug(f"图片体积 {len(raw) / 1024:.1f}KB 超出上限，重新压缩")
            if max_bytes <= 0:
                out_mime = _pick_mime(img, mime)
                return NormalizeResult(
                    raw=_encode_bytes(img, out_mime, None), mime=out_mime
                )
            return _fit(img, mime, max_bytes)
    except Image.DecompressionBombError as err:
        return NormalizeResult(reason=f"图片尺寸过大（{err}）")
    except (UnidentifiedImageError, OSError, ValueError, MemoryError) as err:
        logger.debug(f"图片解码失败：{type(err).__name__}: {err}")
        return NormalizeResult(reason="内容不是可解析的图片")
