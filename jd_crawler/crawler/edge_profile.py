"""
Edge Profile 管理器

从用户现有的 Edge 配置复制登录状态，不影响正常使用 Edge
"""
import shutil
from pathlib import Path
from loguru import logger


def get_default_edge_user_data_dir() -> Path:
    """获取系统默认 Edge 用户数据目录"""
    return Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data"


def get_crawler_edge_profile_dir() -> Path:
    """获取爬虫专用的 Edge Profile 目录"""
    return Path.home() / ".job_hunter" / "edge_profile"


def setup_edge_profile(force_copy: bool = False) -> Path:
    """
    设置 Edge Profile（从现有配置复制）

    Args:
        force_copy: 强制重新复制

    Returns:
        爬虫专用的 Edge Profile 路径
    """
    source_dir = get_default_edge_user_data_dir()
    target_dir = get_crawler_edge_profile_dir()

    # 检查源目录是否存在
    if not source_dir.exists():
        raise FileNotFoundError(
            f"找不到 Edge 配置目录: {source_dir}\n"
            "请确认已安装 Microsoft Edge"
        )

    # 如果目标目录已存在且不强制复制，直接返回
    if target_dir.exists() and not force_copy:
        logger.info(f"使用现有 Edge Profile: {target_dir}")
        return target_dir

    # 复制配置
    logger.info(f"正在复制 Edge 配置...")
    logger.info(f"源: {source_dir}")
    logger.info(f"目标: {target_dir}")

    # 创建目标目录
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    # 复制配置（排除一些大文件/锁文件）
    exclude_patterns = ["lockfile", "SingletonLock", "SingletonSocket", "SingletonCookie"]

    try:
        _copytree_ignore_locks(source_dir, target_dir, exclude_patterns)
        logger.success(f"Edge 配置复制完成: {target_dir}")
        return target_dir
    except Exception as e:
        logger.warning(f"完整复制失败，尝试只复制 Default Profile: {e}")
        # 失败的话，只复制 Default 目录
        return _copy_default_profile_only(source_dir, target_dir)


def _copytree_ignore_locks(src: Path, dst: Path, exclude: list):
    """复制目录树，忽略锁文件"""
    dst.mkdir(exist_ok=True)

    for item in src.iterdir():
        # 检查是否排除
        if any(pattern in item.name for pattern in exclude):
            logger.debug(f"跳过: {item.name}")
            continue

        try:
            if item.is_dir():
                _copytree_ignore_locks(item, dst / item.name, exclude)
            else:
                shutil.copy2(item, dst / item.name)
        except Exception as e:
            logger.debug(f"跳过 {item.name}: {e}")


def _copy_default_profile_only(source_dir: Path, target_dir: Path) -> Path:
    """只复制 Default Profile（最小化复制）"""
    logger.info("尝试只复制 Default Profile...")

    default_src = source_dir / "Default"
    default_dst = target_dir / "Default"

    if not default_src.exists():
        raise FileNotFoundError(f"找不到 Default Profile: {default_src}")

    # 复制 Default 目录
    _copytree_ignore_locks(default_src, default_dst,
                          ["lockfile", "SingletonLock", "SingletonSocket", "SingletonCookie", "Cache", "Code Cache", "GPUCache"])

    logger.success(f"Default Profile 复制完成: {default_dst}")
    return target_dir


if __name__ == "__main__":
    profile_dir = setup_edge_profile()
    print(f"Profile 目录: {profile_dir}")
