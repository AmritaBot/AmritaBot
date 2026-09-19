"""不可信资源引用的护栏（SSRF / 路径穿越 / 资源耗尽）。

多模态采集面对的是**完全不可信**的输入：消息段里的 ``url`` / ``file`` 字段由客户端
（或伪造的协议端实现）决定，因此不能直接交给 ``aiohttp`` 或 ``Path`` 使用。
本模块为所有取二进制数据的路径提供统一护栏：

远程地址（:func:`fetch_remote_bytes`）
    - 协议白名单（仅 ``http`` / ``https``），拒绝 URL 内嵌用户信息（``user:pass@``）；
    - DNS 解析后要求**全部**结果为公网地址（拒绝回环、私网、链路本地、保留段、
      IPv4-mapped / 6to4 / Teredo 内嵌地址），阻断 ``127.0.0.1``、
      ``169.254.169.254``（云元数据）、``10.0.0.0/8`` 等内网探测；
    - 连接阶段使用 :class:`_PinnedResolver` 固定到已校验的 IP，防止
      "校验时解析到公网、连接时解析到内网" 的 DNS 重绑定（TOCTOU）；
    - 关闭代理环境变量（``trust_env=False``），手工逐跳跟随重定向并重新校验（≤3 跳）；
    - ``Content-Length`` 预检 + 流式分块累加，超限立即中止，不把超大响应读进内存。

本地路径（:func:`read_local_bytes`）
    - 必须落在显式配置的白名单目录（``context.local_media_dirs``）内，默认**空=禁止**；
    - 先 ``resolve(strict=True)`` 解析符号链接再判定是否在目录内，防止
      ``../../etc/passwd`` 之类的穿越与"白名单目录里的软链接"绕过；
    - 以 ``O_NOFOLLOW`` 打开并 ``fstat`` 校验常规文件与体积，消除校验后替换的 TOCTOU。

内联数据（:func:`decode_inline_bytes`）
    - 只接受 ``base64://`` 与 ``data:<mime>;base64,``，线性切分解析（无正则回溯风险），
      解码前先按体积上限校验编码长度。

设计原则：默认拒绝。所有拒绝路径只写 debug 日志并返回带 ``reason`` 的失败结果，
调用方按"该资源不可用"处理，不影响主流程。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import os
import socket
import stat as stat_module
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult
from nonebot import logger

__all__ = [
    "FetchResult",
    "UnsafeUrlError",
    "decode_inline_bytes",
    "fetch_remote_bytes",
    "file_url_to_path",
    "is_public_ip",
    "read_local_bytes",
]

#  仅允许这两种协议访问远程资源
_ALLOWED_SCHEMES = frozenset({"http", "https"})
#  视为重定向的状态码
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
#  最多跟随的重定向跳数（每跳都会重新做完整校验）
_MAX_REDIRECTS = 3
#  单次 DNS 解析的超时（秒）
_DNS_TIMEOUT_SECONDS = 5.0
#  流式读取的分块大小
_CHUNK_SIZE = 64 * 1024
#  base64 编码长度换算时允许的填充余量
_BASE64_PADDING_SLACK = 8


class UnsafeUrlError(ValueError):
    """URL 未通过校验（协议不支持、含用户信息，或解析到非公网地址）。"""


@dataclass(frozen=True, slots=True)
class FetchResult:
    """二进制获取结果。

    成功时 ``data`` 非空；失败时 ``reason`` 是一句可直接展示给模型/运维的简短说明，
    便于调用方在跳过该资源的同时把失败原因回写到上下文（而不是静默丢一段内容）。
    """

    data: bytes | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        """是否成功取到非空二进制。"""
        return self.data is not None


def _unwrap_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """展开 IPv6 中内嵌的 IPv4 地址，避免用内嵌私网地址绕过公网判断。"""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip.sixtofour is not None:
            return ip.sixtofour
    return ip


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """该地址是否为可访问的公网地址。

    ``is_global`` 之外再显式排除私网 / 回环 / 链路本地 / 组播 / 保留 / 未指定 /
    站点本地，避免不同 Python 版本 ``is_global`` 实现差异带来的漏判。
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.teredo is not None:
        #  Teredo 可封装任意 IPv4，直接拒绝
        return False
    target = _unwrap_ip(ip)
    return bool(
        target.is_global
        and not target.is_private
        and not target.is_loopback
        and not target.is_link_local
        and not target.is_multicast
        and not target.is_reserved
        and not target.is_unspecified
        and not getattr(target, "is_site_local", False)
    )


async def _resolve_host(host: str, port: int) -> list[tuple[int, str]]:
    """解析主机名，返回去重后的 ``(family, ip)`` 列表；超时抛 ``asyncio.TimeoutError``。"""
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(
        loop.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP),
        timeout=_DNS_TIMEOUT_SECONDS,
    )
    resolved: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for family, _type, _proto, _canonname, sockaddr in infos:
        ip = str(sockaddr[0])
        key = (family, ip)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(key)
    if not resolved:
        raise UnsafeUrlError(f"主机名 {host} 未解析到任何地址")
    return resolved


async def _validate_remote_url(url: str) -> tuple[str, int, list[tuple[int, str]]]:
    """校验远程 URL 并返回 ``(host, port, 已校验的解析结果)``。

    任一解析结果不是公网地址即整体拒绝（不做"择优选取"），
    避免攻击者用"公网 + 内网"混合解析结果试探。
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"不支持的协议: {scheme or '(空)'}")
    if parts.username or parts.password:
        raise UnsafeUrlError("URL 中不允许包含用户信息")
    host = parts.hostname
    if not host:
        raise UnsafeUrlError("URL 缺少主机名")
    try:
        port = parts.port
    except ValueError as e:
        raise UnsafeUrlError(f"端口不合法: {e}") from e
    port = port or (443 if scheme == "https" else 80)

    #  字面量 IP 直接判定，省去一次 DNS 往返
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not is_public_ip(literal):
            raise UnsafeUrlError(f"拒绝访问非公网地址: {host}")
        family = socket.AF_INET6 if literal.version == 6 else socket.AF_INET
        return host, port, [(family, str(literal))]

    resolved = await _resolve_host(host, port)
    for _family, ip in resolved:
        address = ipaddress.ip_address(ip)
        if not is_public_ip(address):
            raise UnsafeUrlError(f"主机名 {host} 解析到非公网地址: {ip}")
    return host, port, resolved


class _PinnedResolver(AbstractResolver):
    """固定到已校验 IP 的解析器，用于阻断 DNS 重绑定（TOCTOU）。

    校验与实际连接之间存在时间差，攻击者控制的 DNS 可以在这段时间内把记录改到
    内网地址。这里直接让连接阶段复用校验结果，不再发起新的 DNS 查询。
    """

    def __init__(self, host: str, port: int, addrs: Sequence[tuple[int, str]]) -> None:
        self._host = host
        self._port = port
        self._addrs = tuple(addrs)

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        if host != self._host:
            raise OSError(f"解析器已固定到 {self._host}，拒绝解析 {host}")
        results: list[ResolveResult] = []
        for addr_family, ip in self._addrs:
            if family != socket.AF_UNSPEC and addr_family != family:
                continue
            results.append(
                ResolveResult(
                    hostname=self._host,
                    host=ip,
                    port=self._port,
                    family=addr_family,
                    proto=socket.IPPROTO_TCP,
                    flags=0,
                )
            )
        return results

    async def close(self) -> None:
        return None


async def _read_capped(resp: aiohttp.ClientResponse, max_bytes: int) -> FetchResult:
    """流式读取响应体，累计超过 ``max_bytes`` 时立即放弃。"""
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.content.iter_chunked(_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            return FetchResult(reason=f"响应体积超出上限 {max_bytes} 字节")
        chunks.append(chunk)
    if not chunks:
        return FetchResult(reason="响应内容为空")
    return FetchResult(data=b"".join(chunks))


async def fetch_remote_bytes(
    url: str, *, max_bytes: int, timeout: float
) -> FetchResult:
    """下载远程资源。

    每一跳（含重定向目标）都会重新做协议、主机与解析结果校验；
    体积超过 ``max_bytes``、状态码非 200、重定向超过 :data:`_MAX_REDIRECTS` 跳
    或任何网络异常均返回带 ``reason`` 的失败结果。
    """
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        try:
            host, port, addrs = await _validate_remote_url(current)
        except UnsafeUrlError as e:
            logger.debug(f"已拒绝不符合访问策略的图片地址 {current!r}: {e}")
            return FetchResult(reason=f"地址被安全策略拒绝（{e}）")
        except (OSError, asyncio.TimeoutError) as e:
            logger.debug(f"图片地址解析失败 {current!r}: {e}")
            return FetchResult(reason="域名解析失败或超时")

        #  use_dns_cache=False + 固定解析器：连接时不再查询 DNS
        connector = aiohttp.TCPConnector(
            resolver=_PinnedResolver(host, port, addrs), use_dns_cache=False
        )
        try:
            async with aiohttp.ClientSession(
                connector=connector,
                trust_env=False,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as session:
                async with session.get(current, allow_redirects=False) as resp:
                    if resp.status in _REDIRECT_STATUS:
                        location = resp.headers.get("Location")
                        if not location:
                            logger.debug(
                                f"图片地址返回 {resp.status} 但缺少 Location，已放弃"
                            )
                            return FetchResult(reason="重定向响应缺少 Location 头")
                        current = urljoin(current, location)
                        continue
                    if resp.status != 200:
                        logger.debug(f"下载图片失败（HTTP {resp.status}），已跳过")
                        return FetchResult(reason=f"服务端返回 HTTP {resp.status}")
                    declared = resp.content_length
                    if declared is not None and declared > max_bytes:
                        logger.debug(
                            f"图片声明体积 {declared} 字节超出上限 {max_bytes} 字节，已丢弃"
                        )
                        return FetchResult(
                            reason=f"体积 {declared} 字节超出上限 {max_bytes} 字节"
                        )
                    result = await _read_capped(resp, max_bytes)
                    if not result.ok:
                        logger.debug(f"图片读取失败：{result.reason}")
                    return result
        except Exception as e:
            logger.opt(exception=True).debug(f"下载图片失败: {current!r}")
            return FetchResult(reason=f"网络请求失败（{type(e).__name__}）")
        finally:
            await connector.close()
    logger.debug(f"图片地址重定向超过 {_MAX_REDIRECTS} 跳，已放弃")
    return FetchResult(reason=f"重定向超过 {_MAX_REDIRECTS} 跳")


def file_url_to_path(value: str) -> str | None:
    """把 ``file://`` URL 转成本地路径；其它形式返回 ``None``。

    只接受空 netloc 或 ``localhost``，避免 ``file://evil-host/share`` 这类 UNC 访问。
    """
    if not value.startswith("file://"):
        return None
    parts = urlsplit(value)
    if parts.netloc not in ("", "localhost"):
        logger.debug(f"拒绝访问非本机的 file URL: {value!r}")
        return None
    return unquote(parts.path) or None


def _is_within(target: Path, allowed_dirs: Sequence[str]) -> bool:
    """``target``（已 resolve）是否位于任一白名单目录内。"""
    for raw in allowed_dirs:
        if not raw:
            continue
        try:
            base = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError) as e:
            logger.debug(f"忽略无法解析的白名单目录 {raw!r}: {e}")
            continue
        if target == base or target.is_relative_to(base):
            return True
    return False


def _read_regular_file(target: Path, max_bytes: int) -> bytes | None:
    """以 ``O_NOFOLLOW`` 打开并校验常规文件与体积后读取。"""
    fd = -1
    try:
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        if not stat_module.S_ISREG(info.st_mode):
            logger.debug(f"本地图片 {target} 不是常规文件，已拒绝读取")
            return None
        if info.st_size > max_bytes:
            logger.debug(
                f"本地图片 {target} 体积 {info.st_size} 字节超出上限 {max_bytes} 字节，已丢弃"
            )
            return None
        with os.fdopen(fd, "rb") as fp:
            fd = -1  #  所有权已交给文件对象
            raw = fp.read(max_bytes + 1)
    except OSError as e:
        logger.debug(f"读取本地图片 {target} 失败: {e}")
        return None
    finally:
        if fd >= 0:
            os.close(fd)
    if not raw or len(raw) > max_bytes:
        logger.debug(f"本地图片 {target} 内容为空或超出上限，已丢弃")
        return None
    return raw


def read_local_bytes(
    path: str, *, allowed_dirs: Sequence[str], max_bytes: int
) -> bytes | None:
    """在白名单目录内读取本地文件（阻塞 IO，调用方请用 ``asyncio.to_thread``）。

    ``allowed_dirs`` 为空表示禁止读取任何本地文件——这是默认值，
    因为消息段里的 ``file`` 字段完全由客户端控制，不加约束等于开放任意文件读取。
    """
    if not allowed_dirs:
        logger.debug(
            "未配置本地图片目录白名单（context.local_media_dirs），已拒绝读取本地文件"
        )
        return None
    try:
        target = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as e:
        logger.debug(f"本地图片路径无法解析: {path!r} ({e})")
        return None
    if not _is_within(target, allowed_dirs):
        logger.debug(f"本地文件 {target} 不在允许的目录内，已拒绝读取")
        return None
    return _read_regular_file(target, max_bytes)


def _max_encoded_length(max_bytes: int) -> int:
    """解码后不超过 ``max_bytes`` 时，base64 文本的最大长度。"""
    return (max_bytes // 3 + 1) * 4 + _BASE64_PADDING_SLACK


def decode_inline_bytes(value: str, *, max_bytes: int) -> bytes | None:
    """解码 ``base64://`` / ``data:<mime>;base64,`` 形式的内联二进制。

    先按体积上限校验编码长度再解码，避免超长负载造成内存与 CPU 消耗。
    """
    payload: str | None = None
    if value.startswith("base64://"):
        payload = value[len("base64://") :]
    elif value.startswith("data:"):
        _prefix, sep, rest = value.partition(";base64,")
        payload = rest if sep else None
    if payload is None:
        return None
    payload = payload.strip()
    if not payload or len(payload) > _max_encoded_length(max_bytes):
        logger.debug("内联图片数据为空或超出体积上限，已丢弃")
        return None
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError, TypeError) as e:
        logger.debug(f"内联图片数据解码失败: {e}")
        return None
    if not raw or len(raw) > max_bytes:
        logger.debug("内联图片数据为空或超出体积上限，已丢弃")
        return None
    return raw
