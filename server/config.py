"""服务运行期配置：端口、token、可写目录。

全部集中在 `ServerConfig` 里，方便 `__main__` 组装、测试直接构造。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path

from core.paths import OUTPUT_DIR, SETTINGS_PATH


def new_token() -> str:
    """一次性访问 token。每次启动重新生成，不落盘。"""
    return secrets.token_urlsafe(32)


@dataclass(slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    # 0 表示交给 OS 分配；测试里也可以指定固定端口
    port: int = 0
    token: str = field(default_factory=new_token)
    # 是否把旧 Gradio 界面挂到 /legacy。阶段 7 之后关掉并删除依赖。
    legacy: bool = False
    output_dir: Path = OUTPUT_DIR
    # 应用设置（启用的引擎 / 自动代理）。测试里指向 tmp_path，避免污染仓库。
    settings_path: Path = SETTINGS_PATH
    # 允许的媒体根目录。桌面端导入的是任意本地文件，这里默认放开；
    # 保留字段是为了将来做「只允许拖进窗口的文件」收紧策略。
    media_roots: tuple[Path, ...] = ()

    def media_roots_or_default(self) -> tuple[Path, ...]:
        return self.media_roots or (Path.home(),)
