import shutil

from nonebot import get_driver, logger

from amrita.config_manager import UniConfigManager
from amrita.plugins.perm.config import Config, search_perm
from amrita.plugins.perm.config import DataManager as DT

from .models import PermissionStorage

banner_template = """\033[34m▗▖   ▗▄▄▖
▐▌   ▐▌ ▐▌  \033[96mLitePerm\033[34m  \033[1;4;34mV2-Amrita\033[0m\033[34m
▐▌   ▐▛▀▘   is initializing...
▐▙▄▄▖▐▌\033[0m"""


@get_driver().on_startup
async def load():
    config = await DT().safe_get_config()
    print(banner_template)
    store = PermissionStorage()
    if (config).update_from_json:
        logger.info("Migrating from JSON...")
        from .legacy import Data_Manager, GroupData, PermissionGroupData, UserData
        from .models import (
            MemberPermissionPydantic,
            PermissionGroupPydantic,
        )

        dm = Data_Manager()

        await dm.init()
        count = 0
        logger.info("Migrating permission groups...")
        for file in dm.permission_groups_path.iterdir():
            count += 1
            if file.is_file():
                data = PermissionGroupData.model_validate_json(file.read_text("utf-8"))
                await store.update_permission_group(
                    PermissionGroupPydantic(
                        permissions=search_perm(data.permissions), group_name=file.stem
                    )
                )
        logger.info("Migrating chat group data to database...")
        for file in dm.group_data_path.iterdir():
            count += 1
            if file.is_file():
                group_data = GroupData.model_validate_json(file.read_text("utf-8"))
                await store.update_member_permission(
                    MemberPermissionPydantic(
                        permissions=search_perm(group_data.permissions),
                        member_id=file.stem,
                        type="group",
                    )
                )
                for g in group_data.permission_groups:
                    count += 1
                    logger.info(
                        f"Add member related permission group for {file.stem}@group on {g}"
                    )
                    try:
                        await store.add_member_related_permission_group(
                            file.stem, "group", g
                        )
                    except Exception as e:
                        logger.opt(colors=True, exception=e).error(e)
        logger.info("Migrating user data to database...")
        for file in dm.user_data_path.iterdir():
            count += 1
            if file.is_file():
                user_data = UserData.model_validate_json(file.read_text("utf-8"))
                await store.update_member_permission(
                    MemberPermissionPydantic(
                        permissions=search_perm(user_data.permissions),
                        member_id=file.stem,
                        type="user",
                    )
                )
                for g in user_data.permission_groups:
                    count += 1
                    logger.info(
                        f"Add member related permission group for {file.stem}@user on {g}"
                    )
                    try:
                        await store.add_member_related_permission_group(
                            file.stem, "user", g
                        )
                    except Exception as e:
                        logger.opt(colors=True, exception=e).error(e)
        logger.info(f"更新权限成功，共{count}条数据完成迁移。")
        shutil.rmtree(dm.plugin_data_dir)
        conf: Config = await UniConfigManager().get_config()
        conf.update_from_json = False
        await UniConfigManager().save_config()
    await store.init_cache_from_database()
    await store.get_permission_group("default", True)  # 隐式创建默认组
    await store.get_permission_group("default_group", True)
