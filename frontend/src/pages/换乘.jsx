import React, { useEffect, useState } from "react";
import { 取 } from "../api.js";

const 徽 = (v) => (
  <span className={`徽章 ${v ? "通" : "败"}`}>{v ? "有效" : "失配"}</span>
);

export default function 换乘页() {
  const [卡, 设卡] = useState([]);
  const [点, 设点] = useState([]);
  const [讯, 设讯] = useState("");
  const 刷 = async () => {
    try {
      const [视图, 换乘点] = await Promise.all([取("/换乘"), 取("/换乘点?状态=有效")]);
      设卡(视图);
      设点(换乘点);
    } catch (e) {
      设讯(String(e.message || e));
    }
  };
  useEffect(() => { 刷(); }, []);
  const 拼 = 卡.filter((c) => c.已拼接);
  const 分 = 卡.filter((c) => !c.已拼接 && c.行程数 > 1);
  return (
    <div>
      <h1 className="题">换乘拼接</h1>
      <p className="述">
        口径：<strong>窗内拼一程</strong>。同卡出站后换乘窗秒内异线再进站 → 延伸同一行程键并写换乘点；
        窗外再进站按新行程。拼接三写（换乘点/行程账/续腿）同事务，第二进站不得半挂已结第一程。
      </p>
      <div className="阶条" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
        <div className="阶"><div className="序">有效换乘点</div><b>{点.length}</b><span>窗内异线再进</span></div>
        <div className="阶"><div className="序">已拼接卡</div><b>{拼.length}</b><span>一键含换乘点</span></div>
        <div className="阶"><div className="序">多程卡</div><b>{分.length}</b><span>窗外再进/分段</span></div>
        <div className="阶"><div className="序">换乘窗</div><b>{卡[0]?.换乘窗秒 ?? "—"}</b><span>秒</span></div>
      </div>
      <div className="行"><button className="次" onClick={刷}>刷新</button></div>
      {讯 && <p className="讯">{讯}</p>}
      {!卡.length ? <div className="空态">暂无换乘视图。先在刷卡流灌「换乘窗内样例」。</div> : (
        <table>
          <thead>
            <tr><th>卡号</th><th>行程键列表</th><th>拼接或分段标记</th><th>已拼接</th><th>换乘点</th><th>valid</th><th>问题</th></tr>
          </thead>
          <tbody>
            {卡.map((r) => (
              <tr key={r.卡号}>
                <td>{r.卡号}</td>
                <td style={{ wordBreak: "break-all" }}>{r.行程键列表.join("，") || "—"}</td>
                <td>{r.拼接或分段标记}</td>
                <td>{r.已拼接 ? "拼接" : "普通"}</td>
                <td>{r.换乘点数 ? r.换乘点.map((p) => `${p.出站站点键}→${p.进站站点键}(${p.间隔秒}s)`).join("；") : "—"}</td>
                <td>{徽(r.valid)}</td>
                <td style={{ maxWidth: 320, wordBreak: "break-all" }}>{r.问题.join("；") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h2 className="题" style={{ fontSize: "1.02rem", marginTop: "1.4rem" }}>有效换乘点</h2>
      {!点.length ? <div className="空态">暂无换乘点。</div> : (
        <table>
          <thead>
            <tr><th>#</th><th>卡号</th><th>行程键</th><th>出站→进站</th><th>前/后线</th><th>间隔秒</th><th>窗秒</th><th>状态</th></tr>
          </thead>
          <tbody>
            {点.map((p) => (
              <tr key={p.编号}>
                <td>{p.编号}</td><td>{p.卡号}</td><td>{p.行程键}</td>
                <td>{p.出站站点键}→{p.进站站点键}</td>
                <td>{p.前线路键}/{p.后线路键}</td>
                <td>{p.间隔秒}</td><td>{p.换乘窗秒}</td><td>{p.状态}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
