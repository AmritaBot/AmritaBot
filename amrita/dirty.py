"""脏标记Pydantic模型，用于数据库ORM等场景，自动跟踪属性的修改状态。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, SupportsIndex, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class DirtyList(list):
    def __init__(self, *args, parent: DirtyAwareModel, attr: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._parent = parent
        self._attr = attr

    def _mark_dirty(self):
        self._parent._mark_dirty(self._attr)

    def _wrap_value(self, value: Any) -> Any:
        if isinstance(value, (list, dict, set)) and not hasattr(value, "_parent"):
            return _wrap_container(value, self._parent, self._attr)
        return value

    def append(self, item):
        item = self._wrap_value(item)
        super().append(item)
        self._mark_dirty()

    def extend(self, iterable):
        iterable = [self._wrap_value(i) for i in iterable]
        super().extend(iterable)
        self._mark_dirty()

    def insert(self, index, item):
        item = self._wrap_value(item)
        super().insert(index, item)
        self._mark_dirty()

    def remove(self, item):
        super().remove(item)
        self._mark_dirty()

    def pop(self, index: SupportsIndex = -1):
        result = super().pop(index)
        self._mark_dirty()
        return result

    def clear(self):
        super().clear()
        self._mark_dirty()

    def __setitem__(self, index, item):
        if isinstance(index, slice):
            item = [self._wrap_value(i) for i in item]
        else:
            item = self._wrap_value(item)
        super().__setitem__(index, item)
        self._mark_dirty()

    def __delitem__(self, index):
        super().__delitem__(index)
        self._mark_dirty()

    def __iadd__(self, other):
        other = [self._wrap_value(i) for i in other]
        super().__iadd__(other)
        self._mark_dirty()
        return self

    def __imul__(self, other):
        super().__imul__(other)
        self._mark_dirty()
        return self

    def __getitem__(self, index):
        value = super().__getitem__(index)
        if isinstance(index, slice):
            return value
        return self._wrap_value(value)


class DirtyDict(dict):
    def __init__(self, *args, parent: DirtyAwareModel, attr: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._parent = parent
        self._attr = attr

    def _mark_dirty(self):
        self._parent._mark_dirty(self._attr)

    def _wrap_value(self, value: Any) -> Any:
        if isinstance(value, (list, dict, set)) and not hasattr(value, "_parent"):
            return _wrap_container(value, self._parent, self._attr)
        return value

    def __setitem__(self, key, value):
        value = self._wrap_value(value)
        super().__setitem__(key, value)
        self._mark_dirty()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._mark_dirty()

    def pop(self, key, default=None):
        result = super().pop(key, default)
        self._mark_dirty()
        return result

    def popitem(self):
        result = super().popitem()
        self._mark_dirty()
        return result

    def clear(self):
        super().clear()
        self._mark_dirty()

    def update(self, *args, **kwargs):
        other = dict(*args, **kwargs)
        for k, v in other.items():
            other[k] = self._wrap_value(v)
        super().update(other)
        self._mark_dirty()

    def setdefault(self, key, default=None):
        default = self._wrap_value(default)
        result = super().setdefault(key, default)
        if key not in self:
            self._mark_dirty()
        return self._wrap_value(result)

    def __getitem__(self, key):
        value = super().__getitem__(key)
        return self._wrap_value(value)


class DirtySet(set):
    def __init__(self, *args, parent: DirtyAwareModel, attr: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._parent = parent
        self._attr = attr

    def _mark_dirty(self):
        self._parent._mark_dirty(self._attr)

    def add(self, element):
        super().add(element)
        self._mark_dirty()

    def remove(self, element):
        super().remove(element)
        self._mark_dirty()

    def discard(self, element):
        super().discard(element)
        self._mark_dirty()

    def pop(self):
        result = super().pop()
        self._mark_dirty()
        return result

    def clear(self):
        super().clear()
        self._mark_dirty()

    def __ior__(self, other):
        super().__ior__(other)
        self._mark_dirty()
        return self

    def __iand__(self, other):
        super().__iand__(other)
        self._mark_dirty()
        return self

    def __isub__(self, other):
        super().__isub__(other)
        self._mark_dirty()
        return self

    def __ixor__(self, other):
        super().__ixor__(other)
        self._mark_dirty()
        return self


def _wrap_container(obj: list | dict | set, parent: DirtyAwareModel, attr: str):
    if isinstance(obj, list):
        return DirtyList(obj, parent=parent, attr=attr)
    if isinstance(obj, dict):
        return DirtyDict(obj, parent=parent, attr=attr)
    if isinstance(obj, set):
        return DirtySet(obj, parent=parent, attr=attr)
    return obj


class DirtyAwareModel(BaseModel):
    dirtyvars__: set[str] = Field(default_factory=set, init=False, exclude=True)

    def model_post_init(self, __context, /):
        del __context
        for name, value in self.__dict__.items():
            if name.startswith("__") or name == "dirtyvars__":
                continue
            wrapped = self._wrap_if_needed(name, value)
            if wrapped is not value:
                object.__setattr__(self, name, wrapped)

    if not TYPE_CHECKING:  # 我们在 if not TYPE_CHECKING 定义的方法，以解决静态类型检查器无法正确判断实际的属性是否存在。

        def __setattr__(self, name, value):
            if name in ("dirtyvars__",):
                object.__setattr__(self, name, value)
                return

            wrapped = self._wrap_if_needed(name, value)
            super().__setattr__(name, wrapped)
            self._mark_dirty(name)

        def __getattribute__(self, name: str) -> Any:
            value = super().__getattribute__(name)
            if name.startswith("__") or name == "dirtyvars__" or name.endswith("__"):
                return value

            if hasattr(value, "_parent"):
                return value

            if isinstance(value, (list, dict, set)):
                wrapped = _wrap_container(value, self, name)
                object.__setattr__(self, name, wrapped)
                return wrapped
            elif isinstance(
                value, BaseModel
            ):  # 也不会有人在ORM模型里嵌套好几层吧，就简单地处理一下吧
                self._mark_dirty(name)

            return value

    def _wrap_if_needed(self, name: str, value: Any) -> Any:
        if isinstance(value, (list, dict, set)) and not hasattr(value, "_parent"):
            return _wrap_container(value, self, name)
        return value

    def _mark_dirty(self, name: str):
        exclude: tuple[str, ...] | None
        if exclude := getattr(self, "dirty_exclude__", None):
            if name in exclude:
                return
        dirty_vars: set[str] | None = getattr(self, "dirtyvars__", None)
        if dirty_vars is None:
            return
        dirty_vars.add(name)

    def is_dirty(self, name: str | None = None) -> bool:
        if name:
            return name in self.dirtyvars__
        return len(self.dirtyvars__) > 0

    def get_dirty_vars(self) -> set[str]:
        return set(self.dirtyvars__)

    def clean(self):
        self.dirtyvars__.clear()
