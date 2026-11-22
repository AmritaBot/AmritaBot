"""实现发现与命名空间布局：base 不依赖实现，impl 无 __init__。"""

from __future__ import annotations

import pathlib

from amrita.platform import loader, registry


def test_impl_is_namespace_package():
    import amrita.platform.impl as impl

    roots = [pathlib.Path(path) for path in impl.__path__]
    # 一旦放进 __init__.py，外部发行版就无法把实现合并到同一路径下
    assert all(not (root / "__init__.py").exists() for root in roots)


def test_load_ports_discovers_both_platforms():
    loader.load_ports()

    assert set(registry.platforms()) == {"qq", "telegram"}
    assert {port.adapter for port in registry.all_for("qq")} == {"onebot11", "milky"}
    assert {port.adapter for port in registry.all_for("telegram")} == {"telegram"}


def test_load_ports_is_idempotent():
    loader.load_ports()
    before = len(registry.all_for("qq"))
    loader.load_ports()

    assert len(registry.all_for("qq")) == before


def test_broken_implementation_does_not_block_others(tmp_path, monkeypatch):
    import amrita.platform.impl as impl

    broken = tmp_path / "broken_impl"
    broken.mkdir()
    (broken / "__init__.py").write_text("raise RuntimeError('boom')\n", "utf-8")

    monkeypatch.setattr(impl, "__path__", [*impl.__path__, str(tmp_path)])
    monkeypatch.setattr(loader, "_loaded", False)

    loader.load_ports()

    # 坏掉的那个只留下日志，其它平台照常注册
    assert {port.adapter for port in registry.all_for("qq")} == {"onebot11", "milky"}
