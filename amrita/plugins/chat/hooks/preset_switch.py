from amrita_core.hook.event import FallbackContext
from amrita_core.hook.on import on_preset_fallback

from amrita.plugins.chat.config import config_manager as dm
from amrita.plugins.chat.utils.preset import resolve_preset


@on_preset_fallback(block=False).handle()
async def _(ctx: FallbackContext):
    config = await dm.safe_get_config()
    count = ctx.term
    if count > len(config.preset_extension.backup_preset_list):
        ctx.fail("No more preset available!")
    ctx.preset = await resolve_preset(
        config.preset_extension.backup_preset_list[count - 1]
    )
