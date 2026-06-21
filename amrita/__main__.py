"""Amrita 废弃入口提示

该命令已废弃，请使用 amctl 代替。
"""

import sys


def main():
    """输出废弃提示并退出"""
    print(
        "This command `amrita` is no longer used, use `amctl` instead.\n"
        "See repo at 'https://github.com/AmritaBot/Amctl' for more help."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
