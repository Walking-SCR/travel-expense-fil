"""
utils.py — 工具函数
"""
from pathlib import Path


def norm_city(c):
    """城市名标准化：去「市/区/县」后缀，去空格。"""
    if not c:
        return ""
    return c.replace("市", "").replace("区", "").replace("县", "").strip()


def get_skill_root():
    """返回本 skill 的根目录。"""
    return Path(__file__).parent.parent


def get_template(template_name):
    """返回模板文件路径。"""
    root = get_skill_root()
    path = root / "templates" / template_name
    if not path.exists():
        raise FileNotFoundError(f"模板文件不存在: {path}")
    return str(path)
