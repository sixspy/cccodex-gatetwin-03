from datetime import datetime, timezone

from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 站规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 线路 (
  线路键 TEXT PRIMARY KEY,
  名称 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 站点 (
  站点键 TEXT PRIMARY KEY,
  线路键 TEXT NOT NULL REFERENCES 线路(线路键),
  站名 TEXT NOT NULL,
  站序 INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS 刷卡点 (
  事件编号 TEXT PRIMARY KEY,
  卡号 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  方向 TEXT NOT NULL,
  事件时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已入流',
  行程键 TEXT NOT NULL DEFAULT '',
  批次编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 开腿账 (
  开腿键 TEXT PRIMARY KEY,
  卡号 TEXT NOT NULL,
  进站事件编号 TEXT NOT NULL,
  进站站点键 TEXT NOT NULL,
  进站事件时 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '在途',
  更新处理时 TEXT NOT NULL,
  行程键 TEXT NOT NULL DEFAULT '',
  换乘标记 TEXT NOT NULL DEFAULT '无'
);
CREATE TABLE IF NOT EXISTS 行程账 (
  行程键 TEXT PRIMARY KEY,
  卡号 TEXT NOT NULL,
  进站事件编号 TEXT NOT NULL,
  出站事件编号 TEXT NOT NULL,
  进站站点键 TEXT NOT NULL,
  出站站点键 TEXT NOT NULL,
  进站事件时 TEXT NOT NULL,
  出站事件时 TEXT NOT NULL,
  历时秒 INTEGER NOT NULL DEFAULT 0,
  状态 TEXT NOT NULL DEFAULT '已成对',
  版本 INTEGER NOT NULL DEFAULT 1,
  处理时 TEXT NOT NULL,
  换乘标记 TEXT NOT NULL DEFAULT '无',
  换乘段数 INTEGER NOT NULL DEFAULT 1,
  换乘点 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 换乘点 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  卡号 TEXT NOT NULL,
  行程键 TEXT NOT NULL,
  出站事件编号 TEXT NOT NULL,
  出站站点键 TEXT NOT NULL DEFAULT '',
  进站事件编号 TEXT NOT NULL,
  进站站点键 TEXT NOT NULL DEFAULT '',
  前线路键 TEXT NOT NULL DEFAULT '',
  后线路键 TEXT NOT NULL DEFAULT '',
  出站事件时 TEXT NOT NULL DEFAULT '',
  进站事件时 TEXT NOT NULL DEFAULT '',
  间隔秒 INTEGER NOT NULL DEFAULT 0,
  换乘窗秒 INTEGER NOT NULL DEFAULT 0,
  状态 TEXT NOT NULL DEFAULT '有效',
  时刻 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_换乘点_行程 ON 换乘点(行程键);
-- 并发抢跑防线：同一出站只能被拼接一次；同一进站只能被拼入一次。
CREATE UNIQUE INDEX IF NOT EXISTS ux_换乘点_出站有效 ON 换乘点(出站事件编号) WHERE 状态='有效';
CREATE UNIQUE INDEX IF NOT EXISTS ux_换乘点_进站有效 ON 换乘点(进站事件编号) WHERE 状态='有效';
-- 一笔刷卡只挂一个行程键：刷卡点行程键为单值列，另以触发式约束防同事件跨键（见下）。
CREATE TRIGGER IF NOT EXISTS trg_刷卡点_一键
BEFORE UPDATE OF 行程键 ON 刷卡点
WHEN NEW.行程键<>'' AND NEW.行程键<>OLD.行程键 AND OLD.命运='已成对'
BEGIN
  SELECT RAISE(ABORT, '焊死：已成对刷卡不得改挂其他行程键');
END;
CREATE TABLE IF NOT EXISTS 旁路匣 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  原因 TEXT NOT NULL,
  卡号 TEXT NOT NULL DEFAULT '',
  事件编号 TEXT NOT NULL DEFAULT '',
  载荷 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 行程贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  刷卡数 INTEGER NOT NULL,
  行程数 INTEGER NOT NULL,
  开腿数 INTEGER NOT NULL,
  旁路数 INTEGER NOT NULL,
  是否通过 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
"""

默认站规 = {
    "站名": "闸对",
    "最大行程秒": "7200",
    "同站进出": "允许",
    "重复进站策略": "旧腿旁路并开新腿",
    "配对策略": "同卡先进后出",
    "换乘窗秒": "300",
    "换乘架构": "窗内拼一程（拼接：一键含换乘点）",
    "换乘判定": "同卡出站后换乘窗秒内异线再进站，延伸同一行程键并写换乘点",
    "换乘超窗": "窗外再进站只开新腿新行程键（与拼/分段架构正交）",
    "骨架": "刷卡点装载→同卡进站出站成对物化→换乘窗内异线拼接→缺腿异向超时旁路→行程账与刷卡点互证",
}

默认线路 = [
    (
        "线1",
        "一号线",
        [("站A", "城东站", 1), ("站B", "中心站", 2), ("站C", "河西站", 3)],
    ),
    (
        "线2",
        "二号线",
        [("站D", "中心站", 1), ("站E", "桥北站", 2), ("站F", "机场站", 3)],
    ),
]


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _补列(conn, 表: str, 列: str, 定义: str) -> None:
    """老库升级：缺列则补列，保住既有数据。"""
    列名 = {r["name"] for r in conn.execute(f"PRAGMA table_info({表})")}
    if 列 not in 列名:
        conn.execute(f"ALTER TABLE {表} ADD COLUMN {列} {定义}")


def _升级旧库(conn) -> None:
    _补列(conn, "开腿账", "行程键", "TEXT NOT NULL DEFAULT ''")
    _补列(conn, "开腿账", "换乘标记", "TEXT NOT NULL DEFAULT '无'")
    _补列(conn, "行程账", "换乘标记", "TEXT NOT NULL DEFAULT '无'")
    _补列(conn, "行程账", "换乘段数", "INTEGER NOT NULL DEFAULT 1")
    _补列(conn, "行程账", "换乘点", "TEXT NOT NULL DEFAULT ''")


def 初始化库() -> None:
    conn = 连接()
    try:
        conn.executescript(建表)
        _升级旧库(conn)

        # 逐键补齐，不覆盖已改过的站规（便于老库平滑升级到换乘口径）。
        for k, v in 默认站规.items():
            conn.execute("INSERT OR IGNORE INTO 站规(键, 值) VALUES (?, ?)", (k, v))

        for 线路键, 名称, 站点列表 in 默认线路:
            conn.execute(
                "INSERT OR IGNORE INTO 线路(线路键, 名称) VALUES (?, ?)",
                (线路键, 名称),
            )
            for 站点键, 站名, 站序 in 站点列表:
                conn.execute(
                    "INSERT OR IGNORE INTO 站点(站点键, 线路键, 站名, 站序) VALUES (?,?,?,?)",
                    (站点键, 线路键, 站名, 站序),
                )
        conn.commit()
    finally:
        conn.close()
