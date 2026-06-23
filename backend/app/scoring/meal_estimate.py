"""普段の食事の推定と、目標ギャップを埋める置換/追加サジェスト。

推定はフォールバック式: ①直近14日の食事記録(HAE/Apple Health栄養)の平均 →
②無ければ頻用食品パターンからの期待値 → ③それも無ければ推定なし。
不足分・収支は決定的に計算する (LLM に算術はさせない)。提案はユーザー登録食品から。
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import FoodItem, MealPattern
from app.scoring.profile import resolve_profile

# 頻度 → 1日あたりの期待回数の重み
FREQ_WEIGHT = {"daily": 1.0, "often": 0.6, "sometimes": 0.3}
SLOT_LABEL = {"breakfast": "朝", "lunch": "昼", "dinner": "夜", "snack": "間食"}
SLOT_ORDER = ["breakfast", "lunch", "dinner", "snack"]
# タンパク質の換算目安 (置換の手がかり)
PROTEIN_HINTS = "肉/魚 手のひら1枚≈25-30g, 卵1個6g, 納豆1P 7g, 豆腐半丁10g, プロテイン1杯20g"


def _pattern_daily(rows: list[tuple[str, float, float, float, float, float]]) -> dict[str, float]:
    """rows: (frequency, qty, kcal, protein_g, fat_g, carb_g) のタプル列 (session 外で安全)。"""
    acc = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
    for freq, qty, kcal, protein, fat, carb in rows:
        w = FREQ_WEIGHT.get(freq, 1.0) * (qty or 1.0)
        acc["kcal"] += kcal * w
        acc["protein_g"] += protein * w
        acc["fat_g"] += (fat or 0.0) * w
        acc["carb_g"] += (carb or 0.0) * w
    return {k: round(v, 1) for k, v in acc.items()}


# 普段の推定に使う履歴窓。Apple Health の食事記録は疎なことが多いので広めに取る。
USUAL_WINDOW_DAYS = 90


def estimate_usual_macros(target: date_type) -> dict[str, Any]:
    """普段の1日マクロを推定する。

    優先: ①Apple Health/HAE の食事記録 (直近90日の記録日平均) →②固定パターン →③無し。
    記録キーは実際の HAE 名 (protein/dietary_energy/total_fat/carbohydrates)。
    """
    from datetime import datetime as _dt

    from sqlalchemy import func

    from app.models import MetricSample
    from app.scoring.nutrition import _avg_daily

    with session_scope() as session:
        avg_p, n_days = _avg_daily(session, "protein", target, USUAL_WINDOW_DAYS, min_value=20.0)
        avg_k, _ = _avg_daily(session, "dietary_energy", target, USUAL_WINDOW_DAYS, min_value=600.0)
        avg_f, _ = _avg_daily(session, "total_fat", target, USUAL_WINDOW_DAYS, min_value=5.0)
        avg_c, _ = _avg_daily(session, "carbohydrates", target, USUAL_WINDOW_DAYS, min_value=20.0)
        last_ts = session.execute(
            select(func.max(MetricSample.ts)).where(MetricSample.metric_key == "protein")
        ).scalar()
        days_since_log = (_dt.combine(target, _dt.min.time()) - last_ts).days if last_ts else None
        rows = session.execute(
            select(
                MealPattern.slot, MealPattern.frequency, MealPattern.qty,
                FoodItem.kcal, FoodItem.protein_g, FoodItem.fat_g, FoodItem.carb_g,
            ).join(FoodItem, MealPattern.food_id == FoodItem.id)
        ).all()
        n_patterns = len(rows)

    # スロット別に集計 (登録枠=固定、空の枠=ランダム)
    by_slot: dict[str, list[tuple]] = {}
    for slot, freq, qty, kcal, p, fat, carb in rows:
        by_slot.setdefault(slot, []).append((freq, qty, kcal, p, fat, carb))
    registered_slots = [s for s in SLOT_ORDER if s in by_slot]
    variable_slots = [s for s in SLOT_ORDER if s not in by_slot]
    # 固定枠の合計 (= 確実に分かっている分。全日ではない場合がある)
    pattern = _pattern_daily([t for rs in by_slot.values() for t in rs]) if rows else None

    # protein を主軸に「過去の実績」を組む (kcal は記録が更に疎なことがあるので任意)
    logged = None
    if avg_p is not None:
        logged = {
            "kcal": round(avg_k) if avg_k is not None else None,
            "protein_g": round(avg_p, 1),
            "fat_g": round(avg_f, 1) if avg_f is not None else None,
            "carb_g": round(avg_c, 1) if avg_c is not None else None,
        }

    fixed_p = round(pattern["protein_g"], 1) if pattern else 0.0
    fixed_kcal = round(pattern["kcal"]) if pattern else 0

    # 「普段(実績) − 固定(朝)」= 残り(昼夜間食)の推定。これが "間食とかはこう" の正体。
    inferred_variable = None
    if logged is not None and pattern is not None and logged["protein_g"] > fixed_p:
        inferred_variable = {
            "protein_g": round(logged["protein_g"] - fixed_p, 1),
            "kcal": (round(logged["kcal"] - fixed_kcal) if logged["kcal"] is not None else None),
        }

    if logged is not None:
        estimate, source = logged, "logged"
        complete = True
        # 記録が古い/少ないほど確度を下げて正直に
        confidence = "high" if (n_days >= 7 and (days_since_log or 0) <= 30) else "medium"
    elif pattern is not None:
        estimate, source = pattern, "pattern"
        complete = len(variable_slots) == 0
        confidence = "medium" if complete else "partial"
    else:
        estimate, source, confidence, complete = None, "none", "none", False

    return {
        "estimate": estimate,  # logged=過去の実績(全日) / pattern=固定枠の合計
        "logged": logged,
        "pattern": pattern,
        "inferred_variable": inferred_variable,  # 実績−固定 = 昼夜間食の推定
        "source": source,
        "confidence": confidence,
        "n_patterns": n_patterns,
        "logged_days": n_days,  # 推定に使った記録日数
        "days_since_log": days_since_log,  # 最後の記録からの経過日数
        "complete": complete,
        "registered_slots": registered_slots,
        "variable_slots": variable_slots,
        "fixed_protein_g": fixed_p,
        "fixed_kcal": fixed_kcal,
    }


def _targets(target: date_type) -> dict[str, Any]:
    """タンパク質・カロリー目標と方向を physique プラン (単一の真実) から取得。"""
    from app.scoring.physique_plan import recomposition_plan

    plan = recomposition_plan(target)
    if plan.get("available"):
        return {
            "protein_g": plan["macros"]["protein_g"],
            "calorie": plan["energy"]["calorie_target"],
            "direction": plan["direction"],
        }
    prof = resolve_profile()
    return {
        "protein_g": round(prof.protein_g_per_kg * prof.target_weight_kg),
        "calorie": None,
        "direction": "maintain",
    }


def meal_suggestions(target: date_type) -> dict[str, Any]:
    """目標と普段の差を、登録食品からの置換/追加に翻訳する。"""
    tg = _targets(target)
    usual = estimate_usual_macros(target)
    est = usual["estimate"]

    with session_scope() as session:
        foods = session.execute(select(FoodItem)).scalars().all()
        pat_rows = session.execute(
            select(MealPattern, FoodItem).join(FoodItem, MealPattern.food_id == FoodItem.id)
        ).all()
        # detach 用に必要な値を取り出す
        food_dicts = [{
            "id": f.id, "name": f.name, "kcal": f.kcal, "protein_g": f.protein_g,
            "fat_g": f.fat_g, "carb_g": f.carb_g, "unit_label": f.unit_label,
            "category": f.category, "is_protein_source": f.is_protein_source,
        } for f in foods]
        snack_patterns = [{
            "slot": mp.slot, "name": f.name, "kcal": f.kcal, "protein_g": f.protein_g,
            "unit_label": f.unit_label,
        } for mp, f in pat_rows if mp.slot == "snack" or f.category == "間食"]

    suggestions: list[dict[str, Any]] = []
    protein_target = tg["protein_g"]

    if not food_dicts:
        suggestions.append({
            "kind": "setup",
            "text": "頻用食品を登録すると、あなたの食品から具体的な置換・追加案を出せます。",
        })
        return {"targets": tg, "usual": usual, "protein_gap": None, "suggestions": suggestions}

    prot_foods = sorted(food_dicts, key=lambda x: x["protein_g"], reverse=True)
    best_protein = next((x for x in prot_foods if x["is_protein_source"]), prot_foods[0])

    # --- 部分登録 (朝だけ固定など): ランダムな枠の目標を案内する (でっち上げない) ---
    if usual["source"] == "pattern" and not usual["complete"]:
        fixed_p = usual["fixed_protein_g"]
        fixed_labels = "・".join(SLOT_LABEL[s] for s in usual["registered_slots"])
        var_labels = "・".join(SLOT_LABEL[s] for s in usual["variable_slots"])
        remaining = round(protein_target - fixed_p)
        protein_gap = remaining
        if remaining <= 5:
            suggestions.append({
                "kind": "ok",
                "text": (f"固定の{fixed_labels}だけでP{round(fixed_p)}gを確保でき、ほぼ目標"
                         f"({protein_target}g)。{var_labels}は自由でOK。"),
            })
        else:
            # ランダムな主食事の枠数で割って1食あたりの目安に
            main_vars = [s for s in usual["variable_slots"] if s != "snack"] or usual["variable_slots"]
            per_meal = round(remaining / max(1, len(main_vars)))
            suggestions.append({
                "kind": "variable_target",
                "text": (f"固定の{fixed_labels}でP{round(fixed_p)}g。残り{remaining}gを"
                         f"ランダムな{var_labels}で確保 → 1食あたり~{per_meal}g。"
                         f"目安: {PROTEIN_HINTS}"),
                "delta_protein_g": remaining,
            })
            # 固定枠にタンパク質の弱い食品があれば、置換も提案
            weak = [f for f in food_dicts if not f["is_protein_source"] and f["protein_g"] < 3]
            if weak and best_protein["protein_g"] >= 10:
                suggestions.append({
                    "kind": "add",
                    "text": (f"固定枠を強化するなら {best_protein['name']} を "
                             f"{best_protein['unit_label']} 足す → P+{round(best_protein['protein_g'])}g"),
                    "delta_protein_g": round(best_protein["protein_g"]),
                    "delta_kcal": round(best_protein["kcal"]),
                })
        return {"targets": tg, "usual": usual, "protein_gap": protein_gap, "suggestions": suggestions}

    # --- 全日が分かる (記録あり or 全枠登録) → 不足分を追加/置換 ---
    protein_gap = None
    if est is not None and est.get("protein_g") is not None:
        protein_gap = round(protein_target - est["protein_g"])

    # 過去の実績ベースなら、まず「普段これくらい」を提示 (+固定/残りの分解)
    if usual["source"] == "logged":
        days = usual.get("logged_days") or 0
        stale = f"・{usual['days_since_log']}日前まで" if usual.get("days_since_log") else ""
        line = f"過去の実績: 普段 P{round(est['protein_g'])}g/日"
        if est.get("kcal"):
            line += f"・{round(est['kcal'])}kcal"
        line += f"（{days}日分の記録{stale}）"
        iv = usual.get("inferred_variable")
        if iv and usual["fixed_protein_g"] > 0:
            line += (f"。うち固定の{'・'.join(SLOT_LABEL[s] for s in usual['registered_slots'])}で"
                     f"P{round(usual['fixed_protein_g'])}g、残り(昼夜間食)で~P{round(iv['protein_g'])}g")
        suggestions.append({"kind": "usual", "text": line})

    if protein_gap is not None and protein_gap > 10:
        # 朝が固定なら「残り(昼夜間食)で+gap」と案内
        fixed_note = ""
        if usual["fixed_protein_g"] > 0 and usual["variable_slots"]:
            fixed_note = f"固定の朝は変えず、{'・'.join(SLOT_LABEL[s] for s in usual['variable_slots'])}で"
        suggestions.append({
            "kind": "add",
            "text": (f"目標まであと {protein_gap}g。{fixed_note}{best_protein['name']} を "
                     f"{best_protein['unit_label']} 追加 → P+{round(best_protein['protein_g'])}g "
                     f"(+{round(best_protein['kcal'])}kcal)。または主菜を手のひら1枚増やす(P+25-30g)"),
            "delta_protein_g": round(best_protein["protein_g"]),
            "delta_kcal": round(best_protein["kcal"]),
        })
        if snack_patterns:
            worst = max(snack_patterns, key=lambda s: s["kcal"] - s["protein_g"] * 4)
            if worst["protein_g"] < best_protein["protein_g"]:
                dp = round(best_protein["protein_g"] - worst["protein_g"])
                dk = round(best_protein["kcal"] - worst["kcal"])
                suggestions.append({
                    "kind": "swap",
                    "text": (f"{SLOT_LABEL.get(worst['slot'], '間食')}の {worst['name']} を "
                             f"{best_protein['name']} に置換 → P+{dp}g・kcal{dk:+d}"),
                    "delta_protein_g": dp,
                    "delta_kcal": dk,
                })
    elif protein_gap is not None:
        suggestions.append({"kind": "ok", "text": f"タンパク質は目標({protein_target}g)にほぼ到達。維持を。"})
    else:
        suggestions.append({
            "kind": "info",
            "text": (f"目標タンパク質 {protein_target}g/日。食事を記録するか頻用食品パターンを"
                     "設定すると、不足分から具体的な置換案を出せます。"),
        })

    return {"targets": tg, "usual": usual, "protein_gap": protein_gap, "suggestions": suggestions}
