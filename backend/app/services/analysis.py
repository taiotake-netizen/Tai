"""検証レポートの生成。

- 確認できた事実(confirmed_facts): 数値比較から機械的に導けること。出所が未検証なら verified=False。
- AIの仮説(hypotheses): 原因に関する推測。ルールエンジン（常時）と LLM（APIキー設定時）が作る。
"""

import json
import logging

from ..config import settings
from ..models import Event, Evaluation, Outcome

log = logging.getLogger(__name__)

DIR_JA = {"up": "上昇", "down": "下落", "flat": "横ばい", None: "不明"}


def _fmt(v, unit="ドル"):
    if v is None:
        return "不明"
    return f"{v:+.1f}{unit}" if isinstance(v, (int, float)) else str(v)


def primary_forecast(event: Event):
    """発表前の最終バージョン（検証の主対象）。"""
    return event.forecasts[-1] if event.forecasts else None


def best_outcome(event: Event) -> Outcome | None:
    bars = [o for o in event.outcomes if o.kind == "price_bars" and o.base_price is not None]
    if bars:
        return bars[0]
    return event.outcomes[0] if event.outcomes else None


def rule_based_analysis(event: Event, outcome: Outcome, evals: list[Evaluation]) -> dict:
    verified = outcome.verified
    facts: list[dict] = []
    hyps: list[dict] = []
    imps: list[str] = []

    def fact(text):
        facts.append({"text": text, "verified": verified, "source": outcome.source})

    if outcome.base_price is not None:
        fact(f"発表直前価格 {outcome.base_price:,.2f}ドル")
    for n in (1, 5, 15, 30, 60):
        v = getattr(outcome, f"d{n}")
        if v is not None:
            fact(f"{n}分後終着地 {_fmt(v)}")
    if outcome.max_up_5m is not None or outcome.max_down_5m is not None:
        mag = lambda v: "不明" if v is None else f"{v:.1f}ドル"  # noqa: E731
        fact(f"5分間の最大上昇幅 {mag(outcome.max_up_5m)} / 最大下落幅 {mag(outcome.max_down_5m)}")
    if outcome.range_5m is not None:
        fact(f"5分間の高値安値レンジ {outcome.range_5m:.1f}ドル")
    if outcome.headline_move is not None:
        fact(f"観測された値動き（時間幅不明） {_fmt(outcome.headline_move)}")
    for ob in outcome.observations or []:
        fact(f"{ob.get('label')}: {ob.get('value')}")
    for ind in event.indicators:
        if ind.actual is not None:
            state = "公式照合済み" if ind.actual_verified else "未照合"
            facts.append({"text": f"{ind.name} 実績 {ind.actual}{ind.unit}（{state}）",
                          "verified": ind.actual_verified, "source": ind.actual_source or "不明"})

    ev_main = evals[-1] if evals else None
    mm = ev_main.metrics if ev_main else {}

    # 最大変動幅と終着地の乖離
    if outcome.max_excursion_5m is not None and outcome.d5 is not None:
        gap = outcome.max_excursion_5m - abs(outcome.d5)
        if gap >= max(10.0, 0.4 * outcome.max_excursion_5m):
            fact(f"5分間の最大到達幅({outcome.max_excursion_5m:.1f}ドル)と5分後終着地({_fmt(outcome.d5)})に{gap:.1f}ドルの差。初動後に戻している。")
            imps.append("最大変動幅と終着地を別モデルで予測し、往復（初動→反転）の確率を明示する。")
    elif outcome.max_down_5m is not None and outcome.d5 is not None and outcome.max_down_5m - abs(outcome.d5) >= 10:
        fact(f"最大下落幅{outcome.max_down_5m:.1f}ドルに対し5分後は{_fmt(outcome.d5)}。初動で下落後に戻している。")
        imps.append("最大変動幅と終着地を別モデルで予測し、往復（初動→反転）の確率を明示する。")

    d = mm.get("direction")
    if d:
        if d["hit"]:
            hyps.append({"text": f"方向（{DIR_JA[d['pred']]}）は的中（判定基準: {d['basis']}）。", "basis": "direction"})
        else:
            hyps.append({"text": f"方向予測は{DIR_JA[d['pred']]}優勢だったが実際は{DIR_JA[d['actual']]}。"
                         "指標結果の解釈、または市場の織り込み度合いを誤った可能性。", "basis": "direction_miss"})
            imps.append("指標サプライズ（実績−市場予想）の符号と大きさから方向を条件付きで予測し、数値予測の誤差に依存しすぎない構造にする。")

    if "max_excursion_5m" in mm:
        e = mm["max_excursion_5m"]
        ratio = e["actual"] / e["pred"] if e["pred"] else None
        if ratio and ratio > 1.3:
            hyps.append({"text": f"5分間の最大到達幅を過小評価（予測{e['pred']:.0f} vs 実績{e['actual']:.0f}ドル）。直前ボラティリティや重要度に応じた値幅の拡大が不足した可能性。", "basis": "excursion_under"})
            imps.append("直前30〜60分のATRと過去同種イベントの値幅分布で最大到達幅をスケーリングする。")
        elif ratio and ratio < 0.7:
            hyps.append({"text": f"5分間の最大到達幅を過大評価（予測{e['pred']:.0f} vs 実績{e['actual']:.0f}ドル）。内容が織り込み済みだった可能性。", "basis": "excursion_over"})
            imps.append("事前の織り込み度合い（金利先物・直前の値動き）を値幅予測の縮小要因として加える。")

    for n in (5, 30, 60):
        e = mm.get(f"d{n}")
        if e and e["abs_error"] >= 15:
            hyps.append({"text": f"{n}分後終着地の誤差 {e['error']:+.1f}ドル（予測{_fmt(e['pred'])} / 実績{_fmt(e['actual'])}）。", "basis": f"d{n}"})

    if outcome.d60 is not None and outcome.d5 is not None and abs(outcome.d60) > 2 * max(abs(outcome.d5), 5) and \
            (outcome.d60 > 0) == (outcome.d5 > 0):
        hyps.append({"text": "発表後60分にかけて同方向へ継続した。初動後の継続トレンドを別途予測する必要がある。", "basis": "continuation"})
        imps.append("初動（〜5分）と継続（15〜60分）を分けた予測を作る。FOMCは声明と会見で分ける。")

    if outcome.reversed_:
        f = ev_main.forecast if ev_main else None
        if f is None or f.reversal_prob is None or f.reversal_prob < 40:
            hyps.append({"text": "初動からの反転が発生したが、予測では反転確率を十分に見込んでいなかった。", "basis": "reversal"})
            imps.append("反転確率を独立に予測し、過去の同種イベントの反転率をベースラインにする。")

    for row in mm.get("indicators", []):
        state = "" if row["actual_verified"] else "（実績未照合）"
        txt = f"{row['name']}: 予測{row['pred']}{row['unit']} vs 実績{row['actual']}{row['unit']}、誤差{row['error']:+g}{state}"
        if "beat_consensus" in row:
            txt += "。市場予想より" + ("近かった" if row["beat_consensus"] else "遠かった")
        hyps.append({"text": txt, "basis": "indicator"})
    for row in mm.get("scenarios", []):
        if row.get("triggered") and "reaction_in_range" in row:
            ok = "範囲内" if row["reaction_in_range"] else "範囲外"
            note = "" if row.get("comparable") else "（時間幅未確認）"
            hyps.append({"text": f"条件付きシナリオ「{row['label']}」が成立し、観測値動き{_fmt(row['observed'])}は想定反応の{ok}{note}。", "basis": "scenario"})
            if row["reaction_in_range"] and not (d and d["hit"]):
                imps.append("数値予測が外れても、条件付き反応予測は機能していた。数値予測と反応予測を分けて評価・改善する。")

    rm = outcome.related_markets or {}
    if "DXY" in rm and rm["DXY"].get("d5") is not None and outcome.d5 is not None:
        if (rm["DXY"]["d5"] > 0) == (outcome.d5 > 0) and abs(outcome.d5) > settings.flat_band_usd:
            hyps.append({"text": "金とDXYが同方向に動いた。ドル以外の要因（リスク回避、別ニュース等）が影響した可能性。", "basis": "dxy"})
    elif not rm:
        imps.append("DXY・米2年/10年債利回りの価格データを取り込み、金利・ドルの反応と合わせて検証する。")

    if len(evals) > 1:
        scored = [(ev.forecast.version_no, ev.metrics["d5"]["abs_error"]) for ev in evals if "d5" in ev.metrics]
        if len(scored) > 1:
            best = min(scored, key=lambda x: x[1])
            hyps.append({"text": f"5分後終着地はVer.{best[0]}が最も近かった（誤差{best[1]:.1f}ドル）。", "basis": "versions"})

    if not verified:
        imps.append("TradingView CSVで1分足を取り込み、公式の指標実績と照合してから確定検証する。")

    summary_parts = []
    if d:
        summary_parts.append(f"方向{'的中' if d['hit'] else '外れ'}")
    if "d5" in mm:
        summary_parts.append(f"5分後誤差{mm['d5']['error']:+.1f}ドル")
    if "max_excursion_5m" in mm:
        summary_parts.append(f"最大到達幅誤差{mm['max_excursion_5m']['error']:+.1f}ドル")
    if "headline_move" in mm:
        summary_parts.append(f"一点予想と観測値動きの差{mm['headline_move']['error']:+.0f}ドル（時間幅未確認）")
    for row in mm.get("indicators", [])[:2]:
        summary_parts.append(f"{row['name']}予測誤差{row['error']:+g}{row['unit']}")
    if not evals:
        summary = "事前予測の記録がないため、値動きの記録のみ保存しています。"
    else:
        summary = "、".join(summary_parts) if summary_parts else "比較可能な定量項目が不足しています。"
    if not verified:
        summary = "【暫定】" + summary

    # 重複除去（順序維持）
    imps = list(dict.fromkeys(imps))
    return {"summary": summary, "confirmed_facts": facts, "hypotheses": hyps, "improvements": imps}


LLM_SYSTEM = (
    "あなたはXAUUSD（金）の経済指標発表時の値動きを研究するアナリストです。"
    "与えられた事前予測・実績・誤差データだけを根拠に、予測が外れた/当たった原因の仮説と、次回の改善点を日本語で示してください。"
    "データにない事実（ニュース、URL、数値）を作らないこと。実績が未検証の場合はその前提を明記すること。"
    '出力はJSONのみ: {"hypotheses":[{"text":"...","basis":"..."}],"improvements":["..."]}'
)


def llm_analysis(payload: dict) -> dict | None:
    """ANTHROPIC_API_KEY が設定されている場合のみ実行。失敗時は None（成功扱いしない）。"""
    if not settings.anthropic_api_key:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.llm_model,
            max_tokens=4000,
            system=LLM_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}],
        )
        if resp.stop_reason == "refusal":
            log.warning("LLM refused analysis")
            return None
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        data = json.loads(text)
        return {
            "hypotheses": [{"text": h["text"], "basis": h.get("basis", "llm"), "by": f"llm:{settings.llm_model}"}
                           for h in data.get("hypotheses", []) if h.get("text")],
            "improvements": [str(x) for x in data.get("improvements", [])],
        }
    except Exception as e:  # noqa: BLE001
        log.warning("LLM analysis failed: %s", e)
        return None
