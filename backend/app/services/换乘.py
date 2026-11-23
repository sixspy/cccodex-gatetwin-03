"""跨线换乘拼接：窗内异线再进 → 延伸同一行程键（拼接口径）。

全局口径（唯一）：
- 以「窗内拼一程」为准：同卡出站后换乘窗秒内异线再进站，延伸同一行程键并写换乘点；
  禁止两程口径下共用一键。
- 窗外再进站按新行程处理（与拼/分段架构正交）。
- 拼接（改行程账 + 写换乘点 + 开续腿）必须同一事务；第二进站不得半挂已结第一程；
  一笔刷卡只挂一个行程键。

本模块给出：判定、延伸、撤销延伸、只读换乘视图。
"""

from app.db import 连接
from app.services import 时间

NAME = "跨线换乘拼接"

# 架构标记：全局只贯彻一种。改口径必须整体切换，不能只改一半。
架构 = "拼接"
架构说明 = "窗内拼一程：出站即结第一程，窗内异线再进延伸同一行程键并写换乘点"


def 站线路(conn, 站点键: str) -> str:
    row = conn.execute("SELECT 线路键 FROM 站点 WHERE 站点键=?", (站点键,)).fetchone()
    return row["线路键"] if row else ""


def 取换乘窗秒(conn) -> int:
    row = conn.execute("SELECT 值 FROM 站规 WHERE 键='换乘窗秒'").fetchone()
    try:
        return int(row["值"]) if row else 300
    except (TypeError, ValueError):
        return 300


def 有效换乘点(conn, 行程键: str) -> list:
    return list(
        conn.execute(
            "SELECT * FROM 换乘点 WHERE 行程键=? AND 状态='有效' ORDER BY 编号",
            (行程键,),
        )
    )


def 找可延伸行程(conn, 卡号: str, 进站站点键: str, 进站事件时: str):
    """返回可延伸的已成对行程行；不适配返回 None。

    条件：该卡最近一笔已成对行程；出站后 0..换乘窗秒 内；异线；
    该出站尚未被别的换乘点占用。
    """
    窗秒 = 取换乘窗秒(conn)
    行程 = conn.execute(
        "SELECT * FROM 行程账 WHERE 卡号=? AND 状态='已成对' ORDER BY 出站事件时 DESC, 处理时 DESC LIMIT 1",
        (卡号,),
    ).fetchone()
    if not 行程:
        return None
    间 = 时间.差秒(行程["出站事件时"], 进站事件时)
    if 间 < 0 or 间 > 窗秒:
        return None
    前线路 = 站线路(conn, 行程["出站站点键"])
    后线路 = 站线路(conn, 进站站点键)
    if not 前线路 or not 后线路 or 前线路 == 后线路:
        return None
    if conn.execute(
        "SELECT 1 FROM 换乘点 WHERE 出站事件编号=? AND 状态='有效'",
        (行程["出站事件编号"],),
    ).fetchone():
        return None
    return 行程


def 延伸(conn, 行程, 进站事件编号: str, 进站站点键: str, 进站事件时: str, 处理时: str) -> str:
    """在调用方事务内延伸行程：写换乘点 + 改行程账 + 开续腿。返回开腿键。

    不做 commit；失败由调用方 savepoint 回滚。
    """
    行程键 = 行程["行程键"]
    卡号 = 行程["卡号"]
    窗秒 = 取换乘窗秒(conn)
    间隔 = max(0, 时间.差秒(行程["出站事件时"], 进站事件时))
    前线路 = 站线路(conn, 行程["出站站点键"])
    后线路 = 站线路(conn, 进站站点键)

    conn.execute(
        """INSERT INTO 换乘点(卡号,行程键,出站事件编号,出站站点键,进站事件编号,进站站点键,
             前线路键,后线路键,出站事件时,进站事件时,间隔秒,换乘窗秒,状态,时刻)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?, '有效', ?)""",
        (
            卡号,
            行程键,
            行程["出站事件编号"],
            行程["出站站点键"],
            进站事件编号,
            进站站点键,
            前线路,
            后线路,
            行程["出站事件时"],
            进站事件时,
            间隔,
            窗秒,
            处理时,
        ),
    )

    段数 = int(行程["换乘段数"] or 1) + 1
    点摘要 = f"{行程['出站站点键']}→{进站站点键}"
    旧点 = 行程["换乘点"] or ""
    新点 = f"{旧点},{点摘要}" if 旧点 else 点摘要
    conn.execute(
        """UPDATE 行程账 SET 状态='换乘中', 换乘标记='拼接', 换乘段数=?, 换乘点=?,
             版本=版本+1, 处理时=? WHERE 行程键=?""",
        (段数, 新点, 处理时, 行程键),
    )

    开腿键 = f"腿-{进站事件编号}"
    conn.execute(
        """INSERT INTO 开腿账(开腿键,卡号,进站事件编号,进站站点键,进站事件时,状态,更新处理时,行程键,换乘标记)
           VALUES (?,?,?,?,?,'在途',?,?,'换乘续腿')""",
        (开腿键, 卡号, 进站事件编号, 进站站点键, 进站事件时, 处理时, 行程键),
    )
    conn.execute(
        "UPDATE 刷卡点 SET 命运='已开腿', 行程键=? WHERE 事件编号=?",
        (行程键, 进站事件编号),
    )
    return 开腿键


def 撤销延伸(conn, 开腿, 处理时: str, 原因: str) -> bool:
    """撤销某条续腿带来的延伸：作废换乘点、还原行程账、摘掉该刷卡点的行程键。

    用于续腿被重复进站旁路 / 缺腿超时。返回是否确有延伸被撤销。
    """
    行程键 = 开腿["行程键"] or ""
    if not 行程键 or (开腿["换乘标记"] or "无") != "换乘续腿":
        return False
    点 = conn.execute(
        "SELECT * FROM 换乘点 WHERE 进站事件编号=? AND 状态='有效'",
        (开腿["进站事件编号"],),
    ).fetchone()
    行程 = conn.execute("SELECT * FROM 行程账 WHERE 行程键=?", (行程键,)).fetchone()
    if not 行程:
        return False
    if 点:
        conn.execute("UPDATE 换乘点 SET 状态='作废', 时刻=? WHERE 编号=?", (处理时, 点["编号"]))
    剩余 = [
        r["编号"]
        for r in conn.execute(
            "SELECT 编号 FROM 换乘点 WHERE 行程键=? AND 状态='有效' ORDER BY 编号", (行程键,)
        )
    ]
    段数 = len(剩余) + 1
    # 摘要按剩余有效换乘点重算
    摘要 = []
    for r in conn.execute(
        "SELECT 出站站点键, 进站站点键 FROM 换乘点 WHERE 行程键=? AND 状态='有效' ORDER BY 编号",
        (行程键,),
    ):
        摘要.append(f"{r['出站站点键']}→{r['进站站点键']}")
    conn.execute(
        """UPDATE 行程账 SET 状态='已成对', 换乘段数=?, 换乘点=?, 版本=版本+1, 处理时=?
           WHERE 行程键=?""",
        (段数, ",".join(摘要), 处理时, 行程键),
    )
    conn.execute(
        "UPDATE 刷卡点 SET 行程键='' WHERE 事件编号=?",
        (开腿["进站事件编号"],),
    )
    return True


def _卡行程键(conn, 卡号: str) -> list:
    return [
        r["行程键"]
        for r in conn.execute(
            "SELECT 行程键 FROM 行程账 WHERE 卡号=? ORDER BY 进站事件时, 行程键", (卡号,)
        )
    ]


def _判定有效(conn, 卡号: str) -> list[str]:
    """只读判定：拼接口径下卡内换乘账是否自洽。返回问题列表（空=有效）。"""
    问题 = []
    窗秒 = 取换乘窗秒(conn)
    行程 = list(conn.execute("SELECT * FROM 行程账 WHERE 卡号=?", (卡号,)))
    for t in 行程:
        点 = 有效换乘点(conn, t["行程键"])
        if len(点) != max(0, int(t["换乘段数"] or 1) - 1):
            问题.append(f"行程{t['行程键']}段数{int(t['换乘段数'] or 1)}≠有效换乘点{len(点)}+1")
        for p in 点:
            if not p["出站事件编号"] or not p["进站事件编号"]:
                问题.append(f"换乘点#{p['编号']}缺刷卡事件")
                continue
            if not (0 <= int(p["间隔秒"]) <= int(p["换乘窗秒"])):
                问题.append(f"换乘点#{p['编号']}间隔{p['间隔秒']}秒越出窗{p['换乘窗秒']}秒")
            if not p["前线路键"] or not p["后线路键"] or p["前线路键"] == p["后线路键"]:
                问题.append(f"换乘点#{p['编号']}非异线")
            if int(p["换乘窗秒"]) != 窗秒:
                问题.append(f"换乘点#{p['编号']}窗秒与站规不一致")
            出 = conn.execute(
                "SELECT * FROM 刷卡点 WHERE 事件编号=?", (p["出站事件编号"],)
            ).fetchone()
            进 = conn.execute(
                "SELECT * FROM 刷卡点 WHERE 事件编号=?", (p["进站事件编号"],)
            ).fetchone()
            if not 出 or not 进:
                问题.append(f"换乘点#{p['编号']}刷卡点缺失")
                continue
            if 出["行程键"] != t["行程键"] or 进["行程键"] != t["行程键"]:
                问题.append(f"换乘点#{p['编号']}刷卡未同挂行程键{t['行程键']}")
            if 出["方向"] != "出站" or 进["方向"] != "进站":
                问题.append(f"换乘点#{p['编号']}方向不符换乘")
        # 半挂防线：同键后置进站（晚于本程出站）必须有换乘点凭据，否则即「第二进站硬挂已结第一程」。
        后置 = conn.execute(
            """SELECT COUNT(*) FROM 刷卡点
               WHERE 行程键=? AND 方向='进站' AND 事件编号<>? AND 事件时 >= ?""",
            (t["行程键"], t["进站事件编号"], t["出站事件时"]),
        ).fetchone()[0]
        if 后置 > len(点):
            问题.append(f"行程{t['行程键']}存在未凭换乘点的后置进站(半挂)")
    # 一键一卡内唯一；一笔刷卡只挂一键（列单值），另查无跨键复挂
    键 = [t["行程键"] for t in 行程]
    if len(键) != len(set(键)):
        问题.append("卡内行程键重复")
    return 问题


def 卡换乘视图(卡号: str) -> dict:
    conn = 连接()
    try:
        return _视图(conn, 卡号)
    finally:
        conn.close()


def 全卡换乘视图() -> list:
    conn = 连接()
    try:
        卡号表 = [
            r["卡号"]
            for r in conn.execute(
                "SELECT DISTINCT 卡号 FROM 行程账 ORDER BY 卡号"
            )
        ]
        for r in conn.execute("SELECT DISTINCT 卡号 FROM 开腿账 ORDER BY 卡号"):
            if r["卡号"] not in 卡号表:
                卡号表.append(r["卡号"])
        卡号表.sort()
        return [_视图(conn, k) for k in 卡号表]
    finally:
        conn.close()


def _视图(conn, 卡号: str) -> dict:
    窗秒 = 取换乘窗秒(conn)
    键 = _卡行程键(conn, 卡号)
    行程 = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM 行程账 WHERE 卡号=? ORDER BY 进站事件时, 行程键", (卡号,)
        )
    ]
    点 = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM 换乘点 WHERE 卡号=? AND 状态='有效' ORDER BY 编号", (卡号,)
        )
    ]
    # 拼接标记：卡内存在有效换乘点，或任一程段数>1 → 拼接；否则仍按拼接口径（全局唯一）标记。
    拼接 = bool(点) or any(int(t["换乘段数"] or 1) > 1 for t in 行程)
    有效判定问题 = _判定有效(conn, 卡号)
    # valid = 卡内换乘账自洽。空卡（无行程、无在途腿，仅旁路）视为平凡有效。
    在途 = conn.execute(
        "SELECT COUNT(*) FROM 开腿账 WHERE 卡号=? AND 状态='在途'", (卡号,)
    ).fetchone()[0]
    return {
        "卡号": 卡号,
        "换乘窗秒": 窗秒,
        "行程键列表": 键,
        "行程数": len(键),
        "拼接或分段标记": 架构,
        "已拼接": 拼接,
        "换乘点": 点,
        "换乘点数": len(点),
        "valid": len(有效判定问题) == 0,
        "在途开腿": 在途,
        "问题": 有效判定问题,
    }
