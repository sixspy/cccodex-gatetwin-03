from app.db import 连接
from app.seed import 此刻


def _有效点(conn, 行程键: str) -> list:
    return list(
        conn.execute(
            "SELECT * FROM 换乘点 WHERE 行程键=? AND 状态='有效' ORDER BY 编号",
            (行程键,),
        )
    )


def _同键刷卡(conn, 行程键: str) -> list:
    return list(
        conn.execute(
            "SELECT * FROM 刷卡点 WHERE 行程键=? ORDER BY 事件时, 事件编号",
            (行程键,),
        )
    )


def 跑贯验() -> dict:
    """行程账与刷卡点互证：成对刷卡 ↔ 行程笔数 ↔ 旁路命运互证；换乘拼接须整段同键。

    换乘拼接口径：一段拼接链 = 首进站 → (出站,进站)* → 末出站，全部同挂一键；
    换乘点两笔刷卡必须同键且方向为 出站→进站；拼接链不得出现无换乘点凭据的后置进站（半挂）。
    """
    conn = 连接()
    try:
        问题 = []
        刷卡数 = conn.execute("SELECT COUNT(*) FROM 刷卡点").fetchone()[0]
        全部行程 = list(conn.execute("SELECT * FROM 行程账"))
        开腿数 = conn.execute("SELECT COUNT(*) FROM 开腿账 WHERE 状态='在途'").fetchone()[0]
        旁路数 = conn.execute("SELECT COUNT(*) FROM 旁路匣").fetchone()[0]

        期望成对刷卡 = 0
        拼接片数 = 0
        for t in 全部行程:
            行程键 = t["行程键"]
            点 = _有效点(conn, 行程键)
            段数 = int(t["换乘段数"] or 1)
            if 段数 != len(点) + 1:
                问题.append(f"行程{行程键}段数{段数}≠有效换乘点{len(点)}+1")
            拼接片数 += len(点)

            进 = conn.execute(
                "SELECT * FROM 刷卡点 WHERE 事件编号=?", (t["进站事件编号"],)
            ).fetchone()
            出 = conn.execute(
                "SELECT * FROM 刷卡点 WHERE 事件编号=?", (t["出站事件编号"],)
            ).fetchone()
            if not 进 or not 出:
                问题.append(f"行程{行程键}缺刷卡点")
                continue
            if 进["方向"] != "进站" or 出["方向"] != "出站":
                问题.append(f"行程{行程键}方向不配对")
            if 进["卡号"] != t["卡号"] or 出["卡号"] != t["卡号"]:
                问题.append(f"行程{行程键}卡号不一致")
            for s in (进, 出):
                if s["行程键"] != 行程键:
                    问题.append(f"行程{行程键}首尾刷卡行程键不一致")
                if s["命运"] != "已成对":
                    问题.append(f"行程{行程键}首尾刷卡命运非已成对")

            本链 = _同键刷卡(conn, 行程键)
            在途 = t["状态"] == "换乘中"
            应有 = 2 + 2 * len(点) - (1 if 在途 and 点 else 0)
            if len(本链) != 应有:
                问题.append(f"行程{行程键}同键刷卡{len(本链)}≠应有{应有}")

            if 点:
                for i, p in enumerate(点):
                    for evid, 应方向 in ((p["出站事件编号"], "出站"), (p["进站事件编号"], "进站")):
                        s = conn.execute(
                            "SELECT * FROM 刷卡点 WHERE 事件编号=?", (evid,)
                        ).fetchone()
                        if not s:
                            问题.append(f"换乘点#{p['编号']}刷卡{evid}缺失")
                            continue
                        if s["方向"] != 应方向:
                            问题.append(f"换乘点#{p['编号']}刷卡{evid}方向应为{应方向}")
                        if s["行程键"] != 行程键:
                            问题.append(f"换乘点#{p['编号']}刷卡{evid}未同挂行程键{行程键}")
                        if i < len(点) - 1 or not 在途:
                            if s["命运"] != "已成对":
                                问题.append(f"换乘点#{p['编号']}刷卡{evid}命运非已成对")
                        elif 应方向 == "进站":
                            if s["命运"] != "已开腿":
                                问题.append(f"在途换乘点#{p['编号']}进站命运非已开腿")
                    if not (0 <= int(p["间隔秒"]) <= int(p["换乘窗秒"])):
                        问题.append(f"换乘点#{p['编号']}间隔{int(p['间隔秒'])}秒越出窗{int(p['换乘窗秒'])}秒")
                    if not p["前线路键"] or not p["后线路键"] or p["前线路键"] == p["后线路键"]:
                        问题.append(f"换乘点#{p['编号']}非异线")

            # 半挂防线：同键后置进站必须有换乘点凭据；凭据数为有效换乘点数。
            悬 = conn.execute(
                """SELECT COUNT(*) FROM 刷卡点
                   WHERE 行程键=? AND 方向='进站' AND 事件编号<>? AND 事件时 >= ?""",
                (行程键, t["进站事件编号"], t["出站事件时"]),
            ).fetchone()[0]
            # 在途换乘点进站晚于当前出站；已成对行程无后置进站。
            允许后置 = len(点)
            if 悬 > 允许后置:
                问题.append(f"行程{行程键}存在未凭换乘点的后置进站(半挂)")

            if not 在途:
                期望成对刷卡 += 2 + 2 * len(点)
            else:
                期望成对刷卡 += 2 + 2 * max(0, len(点) - 1)

        # 任何挂键刷卡必须指向存在的行程（不得一刷卡挂两个键；列为单值，此处查野键）。
        野键 = conn.execute(
            """SELECT COUNT(*) FROM 刷卡点 s LEFT JOIN 行程账 t ON s.行程键=t.行程键
               WHERE s.行程键<>'' AND t.行程键 IS NULL"""
        ).fetchone()[0]
        if 野键:
            问题.append(f"存在挂键刷卡指向不存在的行程{野键}笔")

        # 换乘点进站事件必须唯一，且其刷卡只此一键。
        复点 = conn.execute(
            """SELECT 进站事件编号, COUNT(*) c FROM 换乘点 WHERE 状态='有效'
               GROUP BY 进站事件编号 HAVING c>1"""
        ).fetchall()
        for r in 复点:
            问题.append(f"换乘进站{r['进站事件编号']}被重复拼入{c}次")

        成对刷 = conn.execute("SELECT COUNT(*) FROM 刷卡点 WHERE 命运='已成对'").fetchone()[0]
        if 成对刷 != 期望成对刷卡:
            问题.append(f"已成对刷卡{成对刷} ≠ 应有{期望成对刷卡}")

        开腿刷 = conn.execute(
            "SELECT COUNT(*) FROM 刷卡点 WHERE 命运='已开腿'"
        ).fetchone()[0]
        if 开腿刷 != 开腿数:
            问题.append(f"已开腿刷卡{开腿刷} ≠ 在途开腿{开腿数}")

        通过 = 1 if not 问题 else 0
        说明 = "行程账与刷卡点互证通过" if 通过 else "；".join(问题)[:800]
        conn.execute(
            """INSERT INTO 行程贯验(时刻,刷卡数,行程数,开腿数,旁路数,是否通过,说明)
               VALUES (?,?,?,?,?,?,?)""",
            (此刻(), 刷卡数, len(全部行程), 开腿数, 旁路数, 通过, 说明),
        )
        conn.commit()
        return {
            "是否通过": bool(通过),
            "刷卡数": 刷卡数,
            "行程数": len(全部行程),
            "开腿数": 开腿数,
            "旁路数": 旁路数,
            "拼接片数": 拼接片数,
            "说明": 说明,
            "问题": 问题,
        }
    finally:
        conn.close()
