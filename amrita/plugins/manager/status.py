import os
import platform
import shutil
import sys
from datetime import datetime
from io import BytesIO

import psutil
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageSegment
from nonebot.matcher import Matcher
from nonebot.permission import Permission
from PIL import Image, ImageDraw, ImageFont

from amrita.config import get_amrita_config
from amrita.plugins.menu.models import MatcherData
from amrita.plugins.perm.API.admin import is_lp_admin
from amrita.plugins.perm.API.rules import any_has_permission
from amrita.utils.utils import get_amrita_version, get_core_version

from .models import get_usage


async def generate_info(bot: Bot) -> list[str]:
    # 动态导入

    system_name = platform.system()
    python_version = sys.version
    memory = psutil.virtual_memory()
    cpu_usage = psutil.cpu_percent(interval=1)
    logical_cores = psutil.cpu_count(logical=True)
    disk_usage_origin = shutil.disk_usage(os.getcwd())
    disk_usage = (disk_usage_origin.used / disk_usage_origin.total) * 100
    msg_status_all = await get_usage(bot.self_id)
    status_list = [
        f"System type: {system_name}\n",
        f"CPU Cores: {logical_cores}\n",
        f"CPU Used: {cpu_usage}%\n",
        f"Memory Used: {memory.percent}%\n",
        f"Disk Used: {disk_usage:.2f}%\n",
        f"Python {python_version}\n",
    ]
    for i in msg_status_all:
        if i.created_at == datetime.now().strftime("%Y-%m-%d"):
            msg_status = i
            msg_received = msg_status.msg_received
            msg_sent = msg_status.msg_sent
            status_list.append(
                f"Message: (Received:{msg_received}, Sent:{msg_sent})\n",
            )
    return status_list


def create_system_info_image(system_info: list[str]):
    width, height = 800, 600
    image = Image.new("RGB", (width, height), color="#1a1a2e")
    draw = ImageDraw.Draw(image)

    # 颜色定义
    colors = {
        "background": "#1a1a2e",
        "primary": "#16213e",
        "accent": "#0f3460",
        "text": "#e6e6e6",
        "highlight": "#4592e9",
        "title": "#ffffff",
    }

    draw.rectangle([0, 0, width, 80], fill=colors["accent"])
    draw.rectangle([0, 80, width, height], fill=colors["background"])

    try:
        title_font = ImageFont.truetype("arialbd.ttf", 40)
        header_font = ImageFont.truetype("arial.ttf", 24)
        content_font = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        title_font = ImageFont.load_default(40)
        header_font = ImageFont.load_default(24)
        content_font = ImageFont.load_default(20)

    title = f"{get_amrita_config().bot_name}@Amrita[BOT]"
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (width - title_width) // 2
    draw.text((title_x, 25), title, fill=colors["title"], font=title_font)

    info_box_y = 120
    box_height = 350

    draw.rounded_rectangle(
        [50, info_box_y, width - 50, info_box_y + box_height],
        radius=15,
        fill=colors["primary"],
        outline=colors["accent"],
        width=2,
    )

    info_title = "System Information"
    title_bbox = draw.textbbox((0, 0), info_title, font=header_font)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(
        ((width - title_width) // 2, info_box_y + 15),
        info_title,
        fill=colors["highlight"],
        font=header_font,
    )

    draw.line(
        [70, info_box_y + 60, width - 70, info_box_y + 60],
        fill=colors["accent"],
        width=2,
    )

    line_height = 40
    current_y = info_box_y + 80

    for info in system_info:
        draw.text((70, current_y), info, fill=colors["text"], font=content_font)
        current_y += line_height

    # 绘制底部版本信息
    version_info = (
        f"Powered by Amrita {get_amrita_version()}(Core: {get_core_version()})"
    )
    version_bbox = draw.textbbox((0, 0), version_info, font=content_font)
    version_width = version_bbox[2] - version_bbox[0]
    version_x = (width - version_width) // 2

    # 底部背景
    draw.rectangle([0, height - 50, width, height], fill=colors["accent"])
    draw.text(
        (version_x, height - 40), version_info, fill=colors["text"], font=content_font
    )

    return image


@on_command(
    "status",
    state=MatcherData(
        description="查看系统状态",
        name="查看系统状态",
        usage="/status",
        show_if="amrita.status",
    ).model_dump(),
    permission=Permission(any_has_permission("amrita.status"), is_lp_admin),
).handle()
async def _(matcher: Matcher, bot: Bot):
    img = create_system_info_image(await generate_info(bot=bot))
    btio = BytesIO()
    btio.seek(0)
    img.save(btio, format="png")
    await matcher.finish(MessageSegment.image(btio))
