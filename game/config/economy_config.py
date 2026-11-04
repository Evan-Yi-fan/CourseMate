"""灵玉经济系统的全部可调参数。

规矩：数值只放这里，系统代码里不出现魔法数字，
方便试玩后调平衡而不动逻辑。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 答题奖励
INITIAL_JADE = 30               # 每局初始灵玉
REWARD_PER_CORRECT = 10         # 每答对一题，仅按答对题数发奖
WRONG_PENALTY = 0               # 答错不扣

# ---------------------------------------------------------------- 局内规模
BOARD_SIZE = 5                  # 5×5 棋盘
SLOT_CAPACITY_BASE = 5          # 初始卡槽
SLOT_CAPACITY_MAX = 7           # 扩充上限
START_HP = 3                    # 皇的生命值
WAVES = 3                       # 本关卡波数
# 每波需要的战力。原设 [8,14,20] 经实测无法通关（12 张卡的期望战力约 13），
# 按文档"数值为 V1 初始参数、试玩后调"的要求下调为 [5,9,13]。
WAVE_STRENGTH = [5, 9, 13]
CARD_POOL_SIZE = 12             # 卡片池张数
CARD_MAX_LEVEL = 4

# 元素战力系数：只影响战斗数值，不影响经济规则
ELEMENT_POWER = {"金": 1.2, "木": 1.0, "水": 1.1, "火": 1.3, "土": 1.0}
ELEMENTS = list(ELEMENT_POWER)

# 预设封锁格（行, 列），点亮棋盘只能解锁这些格，且每格一次
LOCKED_CELLS = [(0, 0), (0, 4), (4, 0), (4, 4), (2, 2)]
INITIAL_UNLOCKED = [(2, 2)]     # 关卡开始就开放的格（(2,2) 需从封锁里移除）
LOCKED_CELLS = [c for c in LOCKED_CELLS if c not in INITIAL_UNLOCKED]

# ---------------------------------------------------------------- 商店
# limit: 每局购买次数上限；per_cell: 是否按格计次
SHOP_ITEMS = {
    "slot_expand": {
        "name": "扩充卡槽",
        "price": 30,
        "limit": 2,
        "desc": "卡槽容量 5 → 6 → 7，仅本局有效",
    },
    "unlock_cell": {
        "name": "点亮棋盘",
        "price": 20,
        "limit": 99,          # 实际上限由封锁格数量决定
        "per_cell": True,
        "desc": "解锁一个预设封锁格，每格仅一次",
    },
    "refresh_slots": {
        "name": "刷新卡槽",
        "price": 15,
        "limit": 2,
        "confirm": True,
        "desc": "清空当前卡槽卡片并重新发牌",
    },
    "refresh_pool": {
        "name": "刷新卡片池",
        "price": 25,
        "limit": 3,
        "desc": "只替换尚未取出的卡片，不影响卡槽与棋盘",
    },
    "revive": {
        "name": "紧急救援",
        "price": 40,
        "limit": 1,
        "enabled": False,     # V1 不实现，架构留位（见文档「可选功能」）
        "desc": "皇的生命值恢复 1 点",
    },
}


def item_price(item_id: str) -> int:
    return int(SHOP_ITEMS[item_id]["price"])


def item_limit(item_id: str) -> int:
    return int(SHOP_ITEMS[item_id]["limit"])


def enabled_items() -> list[str]:
    return [k for k, v in SHOP_ITEMS.items() if v.get("enabled", True)]


def reward_rules_text() -> list[str]:
    """给界面展示规则用，避免文案和配置脱节。"""
    return [
        f"每答对 1 题 +{REWARD_PER_CORRECT}",
        f"每局初始灵玉 {INITIAL_JADE}",
        "答错不扣灵玉",
    ]


# ---------------------------------------------------------------- 局内玩法（JS 与 Python 共用）
# 这些数值会被 game/view.py 注入到页面的 window.CM_CONFIG 里，
# 保证"界面里的数字"和"测试里的数字"来自同一处。
GAME_SETTINGS = {
    "hp": 3,                    # 皇后生命
    "waves": 12,                  # 关卡波数
    "enemies_per_wave": [6, 8, 10, 10, 12, 12, 14, 14, 16, 16, 18, 20],
    # 开局随机开放"连在一起"的 N 格（偏向左侧，靠近妖怪来路）
    "unlock_count": 5,
    "beast_cards_max": 2,
    "beast_eat_chance": 0.55,
    "beast_max_stars": 5,
    "beast_star_buff_step": 0.15,
    "slot_capacity": 5,
}

# 游戏内商店（与上面的 SHOP_ITEMS 是同一套经济，只是这里给界面用）
GAME_SHOP = [
    {"id": "slot", "name": "扩充卡槽", "price": 30, "limit": 2},
    {"id": "shovel", "name": "铲子 ×1", "price": 20, "limit": 3},
    {"id": "shuffle", "name": "打乱", "price": 15, "limit": 3},
    {"id": "refresh", "name": "刷新卡池", "price": 30, "limit": 3},
    {"id": "heal", "name": "紧急修复", "price": 40, "limit": 1},
]
