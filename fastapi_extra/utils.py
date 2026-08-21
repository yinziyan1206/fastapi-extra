__author__ = "ziyan.yin"
__date__ = "2024-12-25"


import os


def get_machine_seed() -> int:
    """获取生成id的机器码, 可以覆盖该方法替换

    Returns:
        int: 机器码
    """
    ppid, pid = os.getppid(), os.getpid()
    try:
        return (pid - ppid) % 0x10
    except ValueError:
        return 0
