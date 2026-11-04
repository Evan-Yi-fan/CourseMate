"""把 game/web 下的 html/css/js 组装成一个自包含页面，注入配置。

为什么内联而不是让浏览器去取资源：Streamlit 的 components.html 是一个沙箱 iframe，
没有静态路由，内联是唯一稳妥的方式（也方便离线演示）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from game.config import economy_config as cfg

WEB_DIR = Path(__file__).resolve().parent / "web"


def _read(name: str) -> str:
    return (WEB_DIR / name).read_text(encoding="utf-8")


def build_config(jade: int, *, course_name: str = "") -> dict[str, Any]:
    """游戏参数一律来自 economy_config，避免"界面一套数、测试另一套数"。"""
    g = cfg.GAME_SETTINGS
    return {
        "jade": int(jade),
        "initialJade": cfg.INITIAL_JADE,
        "hp": g["hp"],
        "boardSize": cfg.BOARD_SIZE,
        "slots": g["slot_capacity"],
        "waves": g["waves"],
        "enemiesPerWave": g["enemies_per_wave"],
        "randomUnlock": True,
        "initialLayout": "edge",
        "unlockCount": g.get("unlock_count", 5),
        "beastCardsMax": g["beast_cards_max"],
        "cardMaxLevel": cfg.CARD_MAX_LEVEL,
        "beastEatChance": g["beast_eat_chance"],
        "beastMaxStars": g["beast_max_stars"],
        "beastStarBuffStep": g["beast_star_buff_step"],
        "shop": cfg.GAME_SHOP,
        "courseName": course_name,
    }


def build_html(config: dict[str, Any]) -> str:
    """返回可直接塞进 st.components.v1.html 的完整 HTML。"""
    css = _read("game.css")
    js = _read("game.js")
    tpl = _read("index.html")
    cfg = json.dumps(config, ensure_ascii=False).replace("<", chr(92) + "u003c")
    # 用 replace 而不是 format，避免 CSS/JS 里的 {} 被当成占位符
    return (tpl
            .replace("__SCENE__", _read("scene.svg"))
            .replace("__CSS__", css)
            .replace("__CONFIG__", cfg)
            .replace("__JS__", js))
