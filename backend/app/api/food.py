"""頻用食品マスタ・食事パターン・推定/サジェストの API。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import session_scope
from app.models import FoodItem, MealPattern

router = APIRouter()

Slot = Literal["breakfast", "lunch", "dinner", "snack"]
Frequency = Literal["daily", "often", "sometimes"]


def _food_out(f: FoodItem) -> dict[str, Any]:
    return {
        "id": f.id, "name": f.name, "kcal": f.kcal, "protein_g": f.protein_g,
        "fat_g": f.fat_g, "carb_g": f.carb_g, "unit_label": f.unit_label,
        "category": f.category, "is_protein_source": f.is_protein_source,
    }


# ---- 頻用食品マスタ ----


@router.get("/api/foods")
async def list_foods() -> dict[str, Any]:
    with session_scope() as session:
        foods = session.execute(select(FoodItem).order_by(FoodItem.name)).scalars().all()
        return {"items": [_food_out(f) for f in foods]}


class FoodEstimateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    qty_text: str | None = Field(default=None, max_length=40)


@router.post("/api/foods/estimate")
async def estimate_food(body: FoodEstimateIn) -> dict[str, Any]:
    """LLM で食品名+量からマクロを推定 (保存しない)。登録UIのプリフィル用。"""
    from app.llm.food import estimate_food_macros

    out = await estimate_food_macros(body.name, body.qty_text)
    if out is None:
        return {"available": False, "reason": "推定できませんでした (LLM未設定か失敗)。手入力してください。"}
    return {"available": True, **out}


class FoodIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kcal: float = Field(ge=0, le=5000)
    protein_g: float = Field(ge=0, le=500)
    fat_g: float = Field(default=0.0, ge=0, le=500)
    carb_g: float = Field(default=0.0, ge=0, le=1000)
    unit_label: str = Field(default="1食", max_length=20)
    category: str | None = Field(default=None, max_length=20)
    is_protein_source: bool = False


@router.post("/api/foods")
async def create_food(body: FoodIn) -> dict[str, Any]:
    with session_scope() as session:
        f = FoodItem(**body.model_dump())
        session.add(f)
        session.flush()
        return _food_out(f)


@router.put("/api/foods/{food_id}")
async def update_food(food_id: int, body: FoodIn) -> dict[str, Any]:
    with session_scope() as session:
        f = session.get(FoodItem, food_id)
        if f is None:
            raise HTTPException(status_code=404, detail="not found")
        for k, v in body.model_dump().items():
            setattr(f, k, v)
        session.flush()
        return _food_out(f)


@router.delete("/api/foods/{food_id}")
async def delete_food(food_id: int) -> dict[str, Any]:
    with session_scope() as session:
        f = session.get(FoodItem, food_id)
        if f is None:
            raise HTTPException(status_code=404, detail="not found")
        # この食品を使うパターンも消す
        for mp in session.execute(
            select(MealPattern).where(MealPattern.food_id == food_id)
        ).scalars().all():
            session.delete(mp)
        session.delete(f)
        return {"deleted": food_id}


# ---- 食事パターン (スロット別) ----


@router.get("/api/meal-patterns")
async def list_patterns() -> dict[str, Any]:
    with session_scope() as session:
        rows = session.execute(
            select(MealPattern, FoodItem).join(FoodItem, MealPattern.food_id == FoodItem.id)
        ).all()
        by_slot: dict[str, list[dict[str, Any]]] = {"breakfast": [], "lunch": [], "dinner": [], "snack": []}
        for mp, f in rows:
            by_slot.setdefault(mp.slot, []).append({
                "id": mp.id, "food_id": f.id, "name": f.name, "qty": mp.qty,
                "frequency": mp.frequency, "kcal": f.kcal, "protein_g": f.protein_g,
                "unit_label": f.unit_label,
            })
        return {"slots": by_slot}


class MealPatternIn(BaseModel):
    slot: Slot
    food_id: int
    qty: float = Field(default=1.0, gt=0, le=50)
    frequency: Frequency = "daily"


@router.post("/api/meal-patterns")
async def add_pattern(body: MealPatternIn) -> dict[str, Any]:
    with session_scope() as session:
        if session.get(FoodItem, body.food_id) is None:
            raise HTTPException(status_code=400, detail="unknown food_id")
        mp = MealPattern(**body.model_dump())
        session.add(mp)
        session.flush()
        return {"id": mp.id, **body.model_dump()}


@router.delete("/api/meal-patterns/{pattern_id}")
async def delete_pattern(pattern_id: int) -> dict[str, Any]:
    with session_scope() as session:
        mp = session.get(MealPattern, pattern_id)
        if mp is None:
            raise HTTPException(status_code=404, detail="not found")
        session.delete(mp)
        return {"deleted": pattern_id}


# ---- 推定 + サジェスト ----


@router.get("/api/meal-plan")
async def meal_plan() -> dict[str, Any]:
    from app.scoring.meal_estimate import meal_suggestions
    from app.scoring.timewindow import app_today

    return meal_suggestions(app_today())
