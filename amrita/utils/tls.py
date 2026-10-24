"""出站 TLS 的信任锚收敛。

certifi 在 2026.10.18 之前把 ``emSign ECC Root CA - G3`` 打进随包 CA 库，而该根签发的
8 张中间 CA 私钥已被证明可推导（GHSA-6q48-6c7w-9gw2）。httpx / requests / aiohttp 默认
都从 certifi 取信任锚，等于整套出站 HTTPS 都信任一条可被伪造的链。

这里不改依赖版本（Python 3.10 支线升不上去），改为在运行期把 certifi 的 bundle 过滤成
一份剔除 emSign 的副本，并把 :func:`ssl_context` 交给各 aiohttp 客户端使用。

.. note::
   匹配在 **DER** 上做：PEM 是 base64，明文的厂商名不会出现。解出 DER 后按 subject 的
   可打印串匹配 ``emSign`` / ``eMudhra``，不引入 cryptography 依赖，避免为一次剔除把新包
   拖进运行期。
"""

from __future__ import annotations

import base64
import binascii
import re
import ssl
from functools import lru_cache
from pathlib import Path
from tempfile import gettempdir

import certifi
from nonebot import logger

__all__ = ["filtered_bundle_path", "patch_certifi", "ssl_context"]

#  需要从信任锚里剔除的厂商标记（emSign 各根的 subject 都带其中之一）
_BLOCKED_MARKERS: tuple[bytes, ...] = (b"emSign", b"eMudhra")

#  PEM 证书块切分；CA 库结构固定，线性匹配足够
_PEM_BLOCK = re.compile(
    rb"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", re.DOTALL
)


def _is_blocked(pem_body: bytes) -> bool:
    """判断一段 PEM 正文（不含头尾）是否属于要剔除的厂商。"""
    try:
        der = base64.b64decode(re.sub(rb"\s+", b"", pem_body), validate=True)
    except (binascii.Error, ValueError):
        #  解不开就保守剔除：这份库只用于信任锚，少一张不会放宽校验
        return True
    return any(m in der for m in _BLOCKED_MARKERS)


def _filter_bundle(source: str) -> tuple[bytes, int, int]:
    """读取 ``source`` 指向的 PEM 库，剔除含厂商标记的证书。"""
    text = Path(source).read_bytes()
    bodies = _PEM_BLOCK.findall(text)
    kept: list[bytes] = []
    for body in bodies:
        if _is_blocked(body):
            continue
        kept.append(
            b"-----BEGIN CERTIFICATE-----" + body + b"-----END CERTIFICATE-----\n"
        )
    return b"".join(kept), len(bodies), len(kept)


@lru_cache(maxsize=1)
def filtered_bundle_path() -> str:
    """返回剔除 emSign 之后的 CA 库路径（进程内只生成一次）。

    写进临时目录而非仓库或安装目录：包目录可能只读，且这样不会污染 certifi 自身。
    """
    source = certifi.where()
    filtered, total, kept = _filter_bundle(source)
    if kept == total:
        return source
    target = Path(gettempdir()) / f"amrita-ca-{abs(hash(source)) & 0xFFFFFFFF:x}.pem"
    if not target.exists() or target.read_bytes() != filtered:
        target.write_bytes(filtered)
    logger.info(f"CA 库已剔除不受信根证书：{total - kept} 张（{target}）")
    return str(target)


def patch_certifi() -> None:
    """让 ``certifi.where()`` 返回过滤后的库，覆盖直接调用 certifi 的第三方库。

    幂等；在 :func:`amrita.utils.bot_utils.init` 里调用一次即可。
    """
    target = filtered_bundle_path()
    original = certifi.where
    if getattr(original, "_amrita_patched", False):
        return
    if target == original():
        return

    def where() -> str:
        return target

    where._amrita_patched = True  # type: ignore[attr-defined]
    certifi.where = where  # type: ignore[assignment]
    logger.debug("certifi.where 已重定向到过滤后的 CA 库")


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """出站请求用的 SSLContext：默认校验行为不变，只是信任锚换成过滤后的库。"""
    return ssl.create_default_context(cafile=filtered_bundle_path())


#  TODO(310EOF)：Python 3.10 支持结束后升 certifi>=2026.10.19，并删除本模块与 patch_certifi 调用。
