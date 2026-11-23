import json
from app.seed import 此刻
from app.services import 时间


def 扫缺腿超时(conn, 最大行程秒: int, 水位事件时: str, 处理时: str) -> int:
    """水位推进后，把超最大行程秒仍在途的开腿打进旁路。"""
    from app.services import 换乘

    n = 0
    rows = list(conn.execute("SELECT * FROM 开腿账 WHERE 状态='在途'"))
    for leg in rows:
        if 时间.差秒(leg["进站事件时"], 水位事件时) < 最大行程秒:
            continue
        conn.execute(
            "UPDATE 开腿账 SET 状态='已旁路', 更新处理时=? WHERE 开腿键=?",
            (处理时, leg["开腿键"]),
        )
        conn.execute(
            "UPDATE 刷卡点 SET 命运=? WHERE 事件编号=?",
            ("已旁路", leg["进站事件编号"]),
        )
        # 换乘续腿超时：必须整体撤销延伸，禁止半挂已结第一程。
        已撤销 = 换乘.撤销延伸(conn, leg, 处理时, "缺腿超时")
        conn.execute(
            "INSERT INTO 旁路匣(原因, 卡号, 事件编号, 载荷, 时刻) VALUES (?,?,?,?,?)",
            (
                "缺腿超时",
                leg["卡号"],
                leg["进站事件编号"],
                json.dumps(
                    {
                        "开腿键": leg["开腿键"],
                        "进站事件时": leg["进站事件时"],
                        "水位": 水位事件时,
                        "最大行程秒": 最大行程秒,
                        "撤销换乘延伸": bool(已撤销),
                    },
                    ensure_ascii=False,
                ),
                处理时,
            ),
        )
        n += 1
    return n


def 成对写出站(conn, 开腿, 出站事件编号: str, 出站站点键: str, 出站事件时: str, 处理时: str) -> str:
    行程键 = 开腿["行程键"] or ""
    续腿 = (开腿["换乘标记"] or "无") == "换乘续腿"

    if 行程键 and 续腿:
        # 换乘续腿出站：延伸已有行程，不新开行程键；四笔刷卡同挂一键。
        行程 = conn.execute("SELECT * FROM 行程账 WHERE 行程键=?", (行程键,)).fetchone()
        if not 行程:
            raise RuntimeError(f"换乘续腿找不到行程:{行程键}")
        历时 = max(0, 时间.差秒(行程["进站事件时"], 出站事件时))
        conn.execute(
            """UPDATE 行程账 SET 出站事件编号=?, 出站站点键=?, 出站事件时=?, 历时秒=?,
                 状态='已成对', 换乘标记='拼接', 版本=版本+1, 处理时=?
               WHERE 行程键=?""",
            (出站事件编号, 出站站点键, 出站事件时, 历时, 处理时, 行程键),
        )
        conn.execute(
            "UPDATE 开腿账 SET 状态='已成对', 行程键=?, 更新处理时=? WHERE 开腿键=?",
            (行程键, 处理时, 开腿["开腿键"]),
        )
        conn.execute(
            "UPDATE 刷卡点 SET 命运=?, 行程键=? WHERE 事件编号 IN (?,?)",
            ("已成对", 行程键, 开腿["进站事件编号"], 出站事件编号),
        )
        return 行程键

    行程键 = f"行-{开腿['进站事件编号']}-{出站事件编号}"
    历时 = max(0, 时间.差秒(开腿["进站事件时"], 出站事件时))
    conn.execute(
        """INSERT INTO 行程账(行程键,卡号,进站事件编号,出站事件编号,进站站点键,出站站点键,
           进站事件时,出站事件时,历时秒,状态,版本,处理时,换乘标记,换乘段数,换乘点)
           VALUES (?,?,?,?,?,?,?,?,?,'已成对',1,?,'无',1,'')""",
        (
            行程键,
            开腿["卡号"],
            开腿["进站事件编号"],
            出站事件编号,
            开腿["进站站点键"],
            出站站点键,
            开腿["进站事件时"],
            出站事件时,
            历时,
            处理时,
        ),
    )
    conn.execute(
        "UPDATE 开腿账 SET 状态='已成对', 行程键=?, 更新处理时=? WHERE 开腿键=?",
        (行程键, 处理时, 开腿["开腿键"]),
    )
    conn.execute(
        "UPDATE 刷卡点 SET 命运=?, 行程键=? WHERE 事件编号 IN (?,?)",
        ("已成对", 行程键, 开腿["进站事件编号"], 出站事件编号),
    )
    return 行程键
