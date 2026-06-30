"""資産リバランス + 購入ROIランキング API。手入力 + CSV/スクショ取込。"""

from __future__ import annotations

import csv
import io
import re
from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db import session_scope
from app.llm.finance_ocr import extract_assets
from app.models.health import AssetHolding, CashflowTx, RoiCandidate
from app.scoring.finance import compute_cashflow, compute_finance, compute_rebalance, get_state

router = APIRouter()


@router.get("/api/finance")
async def get_finance() -> dict[str, Any]:
    with session_scope() as session:
        return compute_finance(session)


# ---------------- 資産バケット ----------------
class AssetIn(BaseModel):
    id: int | None = None
    name: str
    category: str = "other"
    value_jpy: float = 0.0
    target_weight: float = 0.0
    note: str | None = None


@router.post("/api/finance/asset")
async def put_asset(body: AssetIn) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(AssetHolding, body.id) if body.id else None
        if row is None:
            row = AssetHolding(name=body.name)
            session.add(row)
        row.name = body.name
        row.category = body.category
        row.value_jpy = body.value_jpy
        row.target_weight = body.target_weight
        row.note = body.note
        session.flush()
        return compute_finance(session)


@router.delete("/api/finance/asset/{asset_id}")
async def delete_asset(asset_id: int) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(AssetHolding, asset_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        session.delete(row)
        session.flush()
        return compute_finance(session)


# ---------------- ROI 候補 ----------------
class RoiIn(BaseModel):
    id: int | None = None
    name: str
    url: str | None = None
    cost_jpy: float = 0.0
    period: str = "onetime"
    monthly_use_days: float = 0.0
    monthly_time_saved_h: float = 0.0
    monthly_revenue_jpy: float = 0.0
    resale_jpy: float = 0.0
    status: str = "considering"
    note: str | None = None


@router.post("/api/finance/roi")
async def put_roi(body: RoiIn) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(RoiCandidate, body.id) if body.id else None
        if row is None:
            row = RoiCandidate(name=body.name)
            session.add(row)
        for f in ("name", "url", "cost_jpy", "period", "monthly_use_days",
                  "monthly_time_saved_h", "monthly_revenue_jpy", "resale_jpy", "status", "note"):
            setattr(row, f, getattr(body, f))
        session.flush()
        return compute_finance(session)


@router.delete("/api/finance/roi/{roi_id}")
async def delete_roi(roi_id: int) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(RoiCandidate, roi_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        session.delete(row)
        session.flush()
        return compute_finance(session)


# ---------------- 設定(防衛資金・時給) ----------------
class ConfigIn(BaseModel):
    reserve_jpy: float | None = None
    wage_jpy_per_h: float | None = None
    reserve_months: int | None = None
    apply_suggested_reserve: bool = False  # True: 月支出×月数 を防衛資金に再設定


@router.put("/api/finance/config")
async def put_config(body: ConfigIn) -> dict[str, Any]:
    with session_scope() as session:
        st = get_state(session)
        if body.reserve_jpy is not None:
            st.reserve_jpy = body.reserve_jpy
        if body.wage_jpy_per_h is not None:
            st.wage_jpy_per_h = body.wage_jpy_per_h
        if body.reserve_months is not None:
            st.reserve_months = max(0, body.reserve_months)
        if body.apply_suggested_reserve:
            reb = compute_rebalance(session)
            cf = compute_cashflow(session, reb["total"] or 0.0)
            if cf.get("_avg_exp"):
                st.reserve_jpy = round(cf["_avg_exp"] * st.reserve_months)
        session.flush()
        return compute_finance(session)


# ---------------- 取込(CSV / スクショ) ----------------
_NUM = re.compile(r"-?[\d,]+")


def _parse_csv_assets(text: str) -> list[dict]:
    """name,value の2列(MoneyForward エクスポート想定)を緩く読む。"""
    out: list[dict] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        name = row[0].strip()
        m = _NUM.search(row[-1].replace("¥", ""))
        if not name or not m:
            continue
        try:
            out.append({"name": name[:120], "value": float(m.group().replace(",", ""))})
        except ValueError:
            continue
    return out


class ImageItem(BaseModel):
    image_base64: str
    media_type: str = "image/png"


class AssetImportIn(BaseModel):
    csv: str | None = None
    image_base64: str | None = None  # 後方互換(単一画像)
    media_type: str = "image/png"
    images: list[ImageItem] | None = None  # 複数スクショ(MoneyForwardは1画面に収まらない)


@router.post("/api/finance/import-assets")
async def import_assets(body: AssetImportIn) -> dict[str, Any]:
    """資産を CSV か スクショ(複数可・OCR)から取り込み、name 一致で upsert(全画面を合算)。"""
    images = list(body.images or [])
    if body.image_base64:
        images.append(ImageItem(image_base64=body.image_base64, media_type=body.media_type))

    items: list[dict] = []
    for im in images:
        got = await extract_assets(image_b64=im.image_base64, media_type=im.media_type)
        if got:
            items.extend(got)
    if body.csv:
        items.extend(_parse_csv_assets(body.csv))
    if not items:
        raise HTTPException(status_code=422, detail="取り込める資産がありませんでした(LLM 未設定/読取不可の可能性)")
    with session_scope() as session:
        existing = {h.name: h for h in session.execute(select(AssetHolding)).scalars()}
        for it in items:
            row = existing.get(it["name"])
            if row is None:
                row = AssetHolding(name=it["name"][:120], category="import")
                session.add(row)
                existing[it["name"]] = row
            row.value_jpy = float(it["value"])
        session.flush()
        return compute_finance(session)


def _parse_cashflow_csv(text: str) -> list[dict]:
    """MoneyForward 入出金 CSV(計算対象/日付/内容/金額/保有金融機関/大項目/中項目/メモ/振替/ID)。"""
    out: list[dict] = []
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    for row in reader:
        rid = (row.get("ID") or "").strip()
        ds = (row.get("日付") or "").strip()
        amt = (row.get("金額（円）") or row.get("金額(円)") or "").strip().replace(",", "")
        if not rid or not ds or not amt:
            continue
        try:
            d = date_type.fromisoformat(ds.replace("/", "-"))
            amount = float(amt)
        except ValueError:
            continue
        out.append({
            "id": rid[:64], "date": d, "amount_jpy": amount,
            "major_category": (row.get("大項目") or "").strip()[:64] or None,
            "minor_category": (row.get("中項目") or "").strip()[:64] or None,
            "account": (row.get("保有金融機関") or "").strip()[:120] or None,
            "content": (row.get("内容") or "").strip()[:300] or None,
            "counted": (row.get("計算対象") or "").strip() == "1",
            "is_transfer": (row.get("振替") or "").strip() == "1",
        })
    return out


class CashflowImportIn(BaseModel):
    csv: str


@router.post("/api/finance/import-cashflow")
async def import_cashflow(body: CashflowImportIn) -> dict[str, Any]:
    """入出金 CSV を取り込み(ID で重複排除)、月支出から防衛資金を自動設定。"""
    rows = _parse_cashflow_csv(body.csv)
    if not rows:
        raise HTTPException(status_code=422, detail="取り込める入出金がありませんでした(CSV を確認)")
    with session_scope() as session:
        for r in rows:
            tx = session.get(CashflowTx, r["id"])
            if tx is None:
                tx = CashflowTx(id=r["id"])
                session.add(tx)
            for k, v in r.items():
                if k != "id":
                    setattr(tx, k, v)
        session.flush()
        # 月平均支出 × 防衛月数 を防衛資金に自動設定。
        st = get_state(session)
        reb = compute_rebalance(session)
        cf = compute_cashflow(session, reb["total"] or 0.0)
        if cf.get("_avg_exp"):
            st.reserve_jpy = round(cf["_avg_exp"] * st.reserve_months)
        session.flush()
        return compute_finance(session)
