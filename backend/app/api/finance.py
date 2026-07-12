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
from app.llm.finance_roi_ai import extract_wishlist_items, suggest_roi
from app.models.health import AssetHolding, CashflowTx, RoiCandidate
from app.scoring.finance import (
    compute_cashflow,
    compute_finance,
    compute_rebalance,
    get_life_profile,
    get_state,
    life_profile_to_dict,
)

router = APIRouter()


@router.get("/api/finance")
async def get_finance() -> dict[str, Any]:
    with session_scope() as session:
        return compute_finance(session)


# ---------------- 生活状況プロフィール ----------------
class LifeProfileIn(BaseModel):
    partner: bool | None = None
    children: int | None = None
    dependents: int | None = None
    housing: str | None = None  # rent|own
    housing_cost_jpy: float | None = None
    monthly_income_jpy: float | None = None
    income_type: str | None = None  # employee|self_employed|mixed
    debt_balance_jpy: float | None = None
    debt_rate_pct: float | None = None
    nisa_monthly_jpy: float | None = None
    ideco_monthly_jpy: float | None = None
    note: str | None = None


@router.get("/api/finance/profile")
async def get_profile() -> dict[str, Any]:
    with session_scope() as session:
        return life_profile_to_dict(get_life_profile(session))


@router.put("/api/finance/profile")
async def put_profile(body: LifeProfileIn) -> dict[str, Any]:
    from datetime import datetime

    with session_scope() as session:
        lp = get_life_profile(session)
        # 送られたフィールドだけ上書き (未指定=変更しない)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(lp, k, v)
        lp.updated_at = datetime.utcnow()
        session.flush()
        return compute_finance(session)


# ---------------- 資産バケット ----------------
class AssetIn(BaseModel):
    id: int | None = None
    name: str
    category: str = "other"
    value_jpy: float = 0.0
    target_weight: float = 0.0
    risk_tier: int | None = None
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
        row.risk_tier = body.risk_tier
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


class RoiSuggestIn(BaseModel):
    name: str | None = None
    url: str | None = None
    image_base64: str | None = None
    media_type: str = "image/png"


@router.post("/api/finance/roi-suggest")
async def roi_suggest(body: RoiSuggestIn) -> dict[str, Any]:
    """品目名/URL/画像からAIでROI項目を推定して返す(DB保存しない。フォーム prefill 用)。"""
    with session_scope() as session:
        cands = list(session.execute(select(RoiCandidate)).scalars())
    # 既存候補を相場観コンテキストに(名前/価格/区分)。
    context = "\n".join(f"- {c.name}: {int(c.cost_jpy)}円/{c.period}" for c in cands[:20])
    out = await suggest_roi(
        name=body.name, url=body.url,
        image_b64=body.image_base64, media_type=body.media_type, context=context,
    )
    if out is None:
        return {"fields": None, "reasons": {}}
    return out


_WISHLIST_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


async def _fetch_url(url: str) -> str | None:
    """URL を取得して HTML を返す。bot対策/エラー/空応答時は None(→呼び出し側でフォールバック)。"""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers={
            "User-Agent": _WISHLIST_UA, "Accept-Language": "ja,en;q=0.8",
        }) as client:
            r = await client.get(url)
        if r.status_code == 200 and len(r.text) > 500:
            return r.text
    except Exception:
        return None
    return None


class WishlistImportIn(BaseModel):
    url: str | None = None
    image_base64: str | None = None
    media_type: str = "image/png"


@router.post("/api/finance/roi-import-wishlist")
async def roi_import_wishlist(body: WishlistImportIn) -> dict[str, Any]:
    """欲しいものリスト(URL主/画像フォールバック)から候補を抽出して返す(DB保存しない)。"""
    items: list[dict[str, Any]] = []
    fetched = False
    if body.url:
        html = await _fetch_url(body.url)
        if html:
            fetched = True
            items = await extract_wishlist_items(html=html)
    # URL取得失敗 or 抽出0件で、画像があればスクショOCRにフォールバック。
    if not items and body.image_base64:
        items = await extract_wishlist_items(image_b64=body.image_base64, media_type=body.media_type)
    return {"items": items, "fetched": fetched}


# ---------------- 設定(防衛資金・時給) ----------------
class ConfigIn(BaseModel):
    reserve_jpy: float | None = None
    wage_jpy_per_h: float | None = None
    reserve_months: int | None = None
    risk_tolerance: int | None = None
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
        if body.risk_tolerance is not None:
            st.risk_tolerance = max(1, min(7, body.risk_tolerance))
        if body.apply_suggested_reserve:
            reb = compute_rebalance(session)
            cf = compute_cashflow(session, reb["total"] or 0.0)
            if cf.get("_avg_exp"):
                st.reserve_jpy = round(cf["_avg_exp"] * st.reserve_months)
        session.flush()
        return compute_finance(session)


class AutoAllocIn(BaseModel):
    tolerance: int | None = None


@router.post("/api/finance/auto-allocate")
async def auto_allocate_endpoint(body: AutoAllocIn) -> dict[str, Any]:
    """リスク許容度に基づき、全資産の目標ウェイトをリスク階層の再帰分割で自動設定。"""
    from app.scoring.finance import auto_allocate

    with session_scope() as session:
        st = get_state(session)
        if body.tolerance is not None:
            st.risk_tolerance = max(1, min(7, body.tolerance))
        holdings = list(session.execute(select(AssetHolding)).scalars())
        weights = auto_allocate(holdings, st.risk_tolerance)
        for h in holdings:
            h.target_weight = weights.get(h.id, 0.0)
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
    # True: この取込を「正」とし、写っていない過去の import 行を削除する (既定)。
    # 手動追加 (category != "import") と、一致行のユーザー設定 (目標ウェイト等) は守る。
    replace: bool = True


def merge_asset_items(items: list[dict]) -> list[dict]:
    """取込バッチ内の重複を整理する (eMAXIS 2口座が1つに潰れるバグの修正)。

    - **銘柄+金額が完全一致** = 複数スクショの重なりで同じ行が2回写った → 1つに排除。
    - **同名で金額が違う** = 本当に別の保有 (特定口座/NISA 等で MoneyForward が同名表示)
      → 潰さず「名前 (2)」の連番サフィックスで別行として残す。
    金額を DB の照合キーにはしない (評価額は毎日変わり、再取込のたびに全資産が複製されるため)。
    """
    seen_exact: set[tuple[str, float]] = set()
    count_by_name: dict[str, int] = {}
    out: list[dict] = []
    for it in items:
        name, value = str(it["name"]), float(it["value"])
        if (name, value) in seen_exact:
            continue  # 画面の重なり
        seen_exact.add((name, value))
        n = count_by_name.get(name, 0) + 1
        count_by_name[name] = n
        final = name if n == 1 else f"{name} ({n})"
        out.append({"name": final, "value": value})
    return out


@router.post("/api/finance/import-assets")
async def import_assets(body: AssetImportIn) -> dict[str, Any]:
    """資産を CSV か スクショ(複数可・OCR)から取り込み、name 一致で upsert。

    バッチ内の同名異額は連番サフィックスで別行に保存 (merge_asset_items)。
    次回取込も同じ並びなら同じサフィックスに解決され、値が更新される。
    """
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
        merged = merge_asset_items(items)
        for it in merged:
            row = existing.get(it["name"])
            if row is None:
                row = AssetHolding(name=it["name"][:120], category="import")
                session.add(row)
                existing[it["name"]] = row
            row.value_jpy = float(it["value"])
        if body.replace:
            # この取込を「正」とする: 写っていない過去の import 行を一掃。
            # 手動追加 (category != "import") は対象外。一致行はユーザー設定ごと温存済み。
            new_names = {it["name"] for it in merged}
            for h in list(existing.values()):
                if h.category == "import" and h.name not in new_names:
                    session.delete(h)
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
