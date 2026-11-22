"""按 Telegram Bot API 规范 mock 适配器：校验出站请求的参数形状与长度上限。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("nonebot.adapters.telegram")

from nonebot.adapters.telegram import Bot as TelegramBot
from nonebot.adapters.telegram.config import BotConfig
from nonebot.adapters.telegram.model import Message as TgMessage

from amrita.platform.dto import GROUP, Part, Scope
from amrita.platform.impl.telegram import TelegramPort

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
ALBUM_MAX = 10
MEDIA_APIS = {
    "send_photo",
    "send_document",
    "send_video",
    "send_audio",
    "send_voice",
    "send_animation",
    "send_sticker",
    "send_video_note",
}
CHAT_ACTIONS = {
    "typing",
    "upload_photo",
    "record_video",
    "upload_video",
    "record_voice",
    "upload_voice",
    "upload_document",
    "choose_sticker",
    "find_location",
    "record_video_note",
    "upload_video_note",
}


class SpecViolation(AssertionError):
    """mock 侧断言：出站请求不符合 Bot API 规范。"""


def _check_chat_id(value: object) -> None:
    if not isinstance(value, int | str) or isinstance(value, bool):
        raise SpecViolation(f"chat_id 必须是 int 或 str，收到 {value!r}")
    if isinstance(value, str) and not value:
        raise SpecViolation("chat_id 不能是空串")


def _check_thread(value: object) -> None:
    if value is not None and not isinstance(value, int):
        raise SpecViolation(f"message_thread_id 必须是 int，收到 {value!r}")


def _check_reply(value: object) -> None:
    if value is None:
        return
    message_id = getattr(value, "message_id", None)
    if not isinstance(message_id, int):
        raise SpecViolation(f"reply_parameters.message_id 必须是 int，收到 {value!r}")


def _check_text(text: object, *, limit: int, field: str) -> None:
    if not isinstance(text, str) or not text:
        raise SpecViolation(f"{field} 必须是非空字符串，收到 {text!r}")
    if len(text) > limit:
        raise SpecViolation(f"{field} 超过 {limit} 字符上限：{len(text)}")


class SpecAdapter:
    """BaseBot.call_api 走的是 adapter._call_api，校验器挂在适配器这一层。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def _call_api(self, bot: object, api: str, **data: Any) -> Any:
        self.calls.append((api, dict(data)))
        _check_chat_id(data.get("chat_id"))
        _check_thread(data.get("message_thread_id"))
        _check_reply(data.get("reply_parameters"))
        if api == "send_message":
            _check_text(data.get("text"), limit=TEXT_LIMIT, field="text")
            entities = data.get("entities")
            if entities is not None and not isinstance(entities, list):
                raise SpecViolation(f"entities 必须是 list，收到 {type(entities)!r}")
            return self._message(data["chat_id"], len(self.calls))
        if api in MEDIA_APIS:
            field = api.removeprefix("send_")
            media = data.get(field)
            if not isinstance(media, str) or not media:
                raise SpecViolation(f"{field} 必须是非空字符串，收到 {media!r}")
            caption = data.get("caption")
            if caption is not None:
                _check_text(caption, limit=CAPTION_LIMIT, field="caption")
            return self._message(data["chat_id"], len(self.calls))
        if api == "send_media_group":
            media = data.get("media")
            if not isinstance(media, list) or not 2 <= len(media) <= ALBUM_MAX:
                raise SpecViolation(f"相册条目数必须在 2~{ALBUM_MAX}：{media!r}")
            for item in media:
                if not getattr(item, "media", None):
                    raise SpecViolation(f"相册条目缺少 media：{item!r}")
            return [
                self._message(data["chat_id"], len(self.calls) * 100 + index)
                for index in range(len(media))
            ]
        if api == "delete_message":
            if not isinstance(data.get("message_id"), int):
                raise SpecViolation(f"delete_message_id 必须是 int：{data!r}")
            return True
        if api == "edit_message_text":
            _check_text(data.get("text"), limit=TEXT_LIMIT, field="text")
            if not isinstance(data.get("message_id"), int):
                raise SpecViolation(f"edit message_id 必须是 int：{data!r}")
            return True
        if api == "send_chat_action":
            if data.get("action") not in CHAT_ACTIONS:
                raise SpecViolation(f"非法 chat action：{data.get('action')!r}")
            return True
        raise SpecViolation(f"未预期的 API：{api}")

    @staticmethod
    def _message(chat_id: int | str, message_id: int) -> TgMessage:
        return TgMessage(
            message_id=message_id,
            date=1700000000,
            chat={"id": chat_id if isinstance(chat_id, int) else 0, "type": "private"},
        )

    def apis(self) -> list[str]:
        return [name for name, _ in self.calls]

    def payloads(self, api: str) -> list[dict[str, Any]]:
        return [data for name, data in self.calls if name == api]


class SpecBot(TelegramBot):
    """真实 Bot 负责分段与参数拼装，SpecAdapter 负责按规范校验。"""

    def __init__(self) -> None:
        self.spec = SpecAdapter()
        super().__init__(
            adapter=self.spec,  # type: ignore[arg-type]
            self_id="42",
            config=BotConfig(token="42:TEST"),
        )

    @property
    def calls(self) -> list[tuple[str, dict[str, Any]]]:
        return self.spec.calls

    def apis(self) -> list[str]:
        return self.spec.apis()

    def payloads(self, api: str) -> list[dict[str, Any]]:
        return self.spec.payloads(api)


def _sender() -> tuple[SpecBot, object]:
    bot = SpecBot()
    scope = Scope(platform="telegram", kind=GROUP, id="-100123", thread="12")
    return bot, TelegramPort().sender(bot, scope)


def test_mock_text_reply_and_thread():
    bot, sender = _sender()

    assert asyncio.run(sender.send_text("收到", reply_to="54")) == "1"
    (payload,) = bot.payloads("send_message")
    assert payload["text"] == "收到"
    assert payload["chat_id"] == -100123
    assert payload["message_thread_id"] == 12
    assert payload["reply_parameters"].message_id == 54
    # 纯文本不该带实体
    assert not payload.get("entities")


def test_mock_long_text_is_split_within_limit():
    bot, sender = _sender()
    text = "字" * (TEXT_LIMIT * 2 + 100)

    asyncio.run(sender.send_text(text))

    payloads = bot.payloads("send_message")
    assert len(payloads) == 3
    assert all(len(item["text"]) <= TEXT_LIMIT for item in payloads)
    assert "".join(item["text"] for item in payloads) == text
    # 引用只挂在第一条
    assert payloads[0]["reply_parameters"] is None
    assert all(item["reply_parameters"] is None for item in payloads[1:])


def test_mock_single_photo_uses_caption():
    bot, sender = _sender()

    asyncio.run(sender.send_parts([Part("text", "看图"), Part("image", "FILE1")]))

    (payload,) = bot.payloads("send_photo")
    assert payload["photo"] == "FILE1"
    assert payload["caption"] == "看图"


def test_mock_album_stays_a_media_group():
    bot, sender = _sender()

    asyncio.run(
        sender.send_parts(
            [
                Part("text", "两图"),
                Part("image", "A"),
                Part("image", "B"),
            ]
        )
    )

    (payload,) = bot.payloads("send_media_group")
    assert [item.media for item in payload["media"]] == ["A", "B"]
    assert payload["media"][0].caption == "两图"


def test_mock_sticker_is_a_separate_request():
    bot, sender = _sender()

    asyncio.run(sender.send_parts([Part("text", "贴纸"), Part("sticker", "STK")]))

    assert bot.apis() == ["send_message", "send_sticker"]
    (sticker,) = bot.payloads("send_sticker")
    assert sticker["sticker"] == "STK"
    assert "caption" not in sticker or sticker["caption"] is None


def test_mock_numeric_mention_produces_no_entities():
    bot, sender = _sender()

    asyncio.run(sender.send_parts([Part("text", "hi "), Part("at", "888")]))

    (payload,) = bot.payloads("send_message")
    assert payload["text"] == "hi "
    assert not payload.get("entities")


def test_mock_edit_and_recall_and_typing():
    bot, sender = _sender()

    async def run() -> tuple[bool, bool, bool]:
        edited = await sender.edit("7", [Part("text", "改过")])
        too_long = await sender.edit("7", [Part("text", "字" * (TEXT_LIMIT + 1))])
        recalled = await sender.recall("7")
        await sender.typing()
        return edited, too_long, recalled

    edited, too_long, recalled = asyncio.run(run())
    assert (edited, too_long, recalled) == (True, False, True)
    (edit_payload,) = bot.payloads("edit_message_text")
    assert edit_payload["message_id"] == 7
    (delete_payload,) = bot.payloads("delete_message")
    assert delete_payload["message_id"] == 7
    (action_payload,) = bot.payloads("send_chat_action")
    assert action_payload["action"] == "typing"
