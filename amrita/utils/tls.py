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
import hashlib
import os
import re
import ssl
import sys
import tempfile
from contextlib import suppress
from functools import lru_cache
from pathlib import Path

import certifi
from nonebot import logger

__all__ = ["filtered_bundle_path", "patch_certifi", "ssl_context"]

#  需要从信任锚里剔除的厂商标记（emSign 各根的 subject 都带其中之一）
_BLOCKED_MARKERS: tuple[bytes, ...] = (b"emSign", b"eMudhra")

#  PEM 证书块切分；CA 库结构固定，线性匹配足够
_PEM_BLOCK = re.compile(
    rb"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", re.DOTALL
)

#  显式指定的 CA 库优先于 certifi：容器 / 企业内网用它是常规做法，OpenSSL 自己也认这个变量
_ENV_BUNDLE = "SSL_CERT_FILE"

#  过滤结果的私有目录名，建在系统临时目录下
_CACHE_DIRNAME = "amrita-ca"

#  各库在导入期就把 ``certifi.where()`` 的返回值缓存成模块级字符串，重定向函数对它们无效，
#  必须把这些常量一并改掉，否则早于 patch 导入的 requests 仍在用未过滤的库
_CACHED_PATH_ATTRS: tuple[tuple[str, str], ...] = (
    ("requests.utils", "DEFAULT_CA_BUNDLE_PATH"),
    ("requests.adapters", "DEFAULT_CA_BUNDLE_PATH"),
    ("requests.sessions", "DEFAULT_CA_BUNDLE_PATH"),
)


def _filter_bundle(sources: list[str]) -> tuple[bytes, int, int]:
    """读取若干 PEM 库，剔除含厂商标记的证书并按 DER 去重。

    Returns:
        ``(过滤后的 PEM, 读到总数, 剔除数)``。
    """
    kept: list[bytes] = []
    seen: set[bytes] = set()
    total = 0
    dropped = 0
    for source in sources:
        try:
            text = Path(source).read_bytes()
        except OSError as err:
            logger.warning(f"CA 库 {source} 读取失败，已跳过：{err}")
            continue
        for body in _PEM_BLOCK.findall(text):
            total += 1
            try:
                der = base64.b64decode(re.sub(rb"\s+", b"", body), validate=True)
            except (binascii.Error, ValueError):
                #  解不开就保守剔除：这份库只用于信任锚，少一张不会放宽校验
                dropped += 1
                continue
            if any(marker in der for marker in _BLOCKED_MARKERS):
                dropped += 1
                continue
            if der in seen:
                continue
            seen.add(der)
            kept.append(
                b"-----BEGIN CERTIFICATE-----\n"
                + re.sub(rb"\s+", b"", body)
                + b"\n-----END CERTIFICATE-----\n"
            )
    return b"".join(kept), total, dropped


def _trust_sources() -> list[str]:
    """列出需要过滤的库。

    ``SSL_CERT_FILE`` 一旦设置就是 OpenSSL 认定的唯一默认库，此时以它取代 certifi；
    否则在 certifi 之外补上平台默认库，避免 ``cafile`` 参数把系统信任锚整体顶掉。
    """
    override = os.environ.get(_ENV_BUNDLE)
    if override and Path(override).is_file():
        return [override]
    sources = [certifi.where()]
    default_cafile = ssl.get_default_verify_paths().cafile
    if default_cafile and Path(default_cafile).is_file():
        if Path(default_cafile).resolve() != Path(sources[0]).resolve():
            sources.append(default_cafile)
    return sources


def _private_dir() -> Path | None:
    """准备一个只有本进程可写的目录；不可用返回 ``None``。

    临时目录所有用户共享，别人可以提前把同名路径建成符号链接。这里要求目录属主是
    自己、且不带组/其他人权限；不满足就退到 :func:`_write_bundle` 里的随机文件名。
    """
    directory = Path(tempfile.gettempdir()) / _CACHE_DIRNAME
    try:
        directory.mkdir(mode=0o700, exist_ok=True)
    except FileExistsError:
        pass
    except OSError as err:
        logger.warning(f"无法创建 CA 库目录 {directory}：{err}")
        return None
    if not directory.is_dir():
        logger.warning(f"CA 库路径 {directory} 不是普通目录，跳过复用")
        return None
    try:
        stat = directory.stat()
    except OSError:
        return None
    if os.name == "posix" and (stat.st_uid != os.getuid() or stat.st_mode & 0o077):
        logger.warning(f"CA 库目录 {directory} 的属主或权限可疑，跳过复用")
        return None
    return directory


def _write_bundle(data: bytes, key: str) -> str | None:
    """把过滤结果落盘，返回路径；任何写入失败返回 ``None``（调用方回退原库）。

    先写 ``mkstemp`` 生成的临时文件再 :func:`os.replace`：``O_EXCL`` 保证不会顺着别人
    预置的符号链接写出去，原子替换保证并发启动时没有进程读到半截 PEM。
    """
    directory = _private_dir()
    target_dir = directory if directory is not None else Path(tempfile.gettempdir())
    target = target_dir / f"ca-{key}.pem"
    try:
        fd, tmp = tempfile.mkstemp(prefix="bundle-", suffix=".tmp", dir=target_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, target)
        except OSError:
            with suppress(OSError):
                os.unlink(tmp)
            raise
    except OSError as err:
        #  只读 / 写满的临时目录不该让 bot 起不来：退回原库至少还能出站
        logger.warning(f"过滤后的 CA 库写入失败，已回退到原始信任锚：{err}")
        return None
    return str(target)


@lru_cache(maxsize=1)
def filtered_bundle_path() -> str:
    """返回剔除 emSign 之后的 CA 库路径（进程内只生成一次）。

    写进私有临时目录而非仓库或安装目录：包目录可能只读，且这样不会污染 certifi 自身。
    任何一种写入失败都退回原始库——过滤是加固，不是功能前提。
    """
    sources = _trust_sources()
    if not sources:
        return certifi.where()
    filtered, total, dropped = _filter_bundle(sources)
    if dropped == 0 and len(sources) == 1:
        return sources[0]
    if not filtered:
        logger.warning("过滤后的 CA 库为空，已回退到原始信任锚")
        return sources[0]
    key = hashlib.sha256("\0".join(sources).encode()).hexdigest()[:12]
    target = _write_bundle(filtered, key)
    if target is None:
        return sources[0]
    logger.info(f"CA 库已剔除不受信根证书 {dropped} 张（共 {total} 张，{target}）")
    return target


def _refresh_cached_paths(original: str, target: str) -> None:
    """改写各库在导入期缓存下来的库路径。

    ``requests.utils`` 里有 ``DEFAULT_CA_BUNDLE_PATH = certifi.where()``，缓存的是字符串
    而不是函数调用；只重定向 ``certifi.where`` 对这份常量没有作用。
    """
    for module_name, attr in _CACHED_PATH_ATTRS:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        if getattr(module, attr, None) == original:
            setattr(module, attr, target)
            logger.debug(f"{module_name}.{attr} 已指向过滤后的 CA 库")


def patch_certifi() -> None:
    """让 ``certifi.where()`` 返回过滤后的库，覆盖直接调用 certifi 的第三方库。

    幂等；在 :func:`amrita.utils.bot_utils.init` 里调用一次即可。已经导入的库若缓存过
    旧路径，由 :func:`_refresh_cached_paths` 就地修正。
    """
    target = filtered_bundle_path()
    original_where = certifi.where
    if getattr(original_where, "_amrita_patched", False):
        return
    original = original_where()
    if target == original:
        return

    def where() -> str:
        return target

    where._amrita_patched = True  # type: ignore[attr-defined]
    certifi.where = where  # type: ignore[assignment]
    _refresh_cached_paths(original, target)
    logger.debug("certifi.where 已重定向到过滤后的 CA 库")


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """出站请求用的 SSLContext：校验行为不变，只是信任锚换成过滤后的库。

    显式传 ``cafile`` 会让 OpenSSL 不再加载默认信任路径，因此 :func:`_trust_sources`
    先把平台默认库并进过滤副本，这里再补上 hash 目录 ``capath``。
    """
    context = ssl.create_default_context(cafile=filtered_bundle_path())
    capath = ssl.get_default_verify_paths().capath
    if capath and Path(capath).is_dir():
        with suppress(OSError, ssl.SSLError):
            context.load_verify_locations(capath=capath)
    return context


#  TODO(310EOF)：Python 3.10 支持结束后升 certifi>=2026.10.19，并删除本模块与 patch_certifi 调用。
