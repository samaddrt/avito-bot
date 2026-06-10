"""FastAPI backend для Mini App: REST по сделкам, статистике, мониторингу,
ручной анализ, экспорт CSV и бэкап БД."""
from __future__ import annotations

import csv
import io
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.ai import analyzer
from app.config import settings
from app.core import calibration, opportunities, pricebook
from app.core import deals as deals_service
from app.db import get_session
from app.models import Deal, DealStatus
from app.watcher import monitor, searches
from app.web.security import is_owner_request

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="SoloMoney Avito OS", docs_url=None, redoc_url=None)


async def require_owner(
    request: Request,
    x_init_data: str | None = Header(default=None, alias="X-Init-Data"),
) -> None:
    client_host = request.client.host if request.client else None
    if not is_owner_request(x_init_data, client_host):
        raise HTTPException(status_code=403, detail="Доступ только для владельца")


def serialize_deal(d: Deal, full: bool = False) -> dict:
    data = {
        "id": d.id,
        "status": d.status.value,
        "verdict": d.verdict.value if d.verdict else None,
        "title": d.title,
        "category": d.category,
        "model_name": d.model_name,
        "url": d.url,
        "city": d.city,
        "seller_price": d.seller_price,
        "market_price": d.market_price,
        "quick_sale_price": d.quick_sale_price,
        "target_buy_price": d.target_buy_price,
        "expected_costs": d.expected_costs,
        "gross_profit": d.gross_profit,
        "expected_profit": d.expected_profit,
        "margin_pct": d.margin_pct,
        "liquidity": d.liquidity,
        "risk_score": d.risk_score,
        "hotness": d.hotness,
        "days_to_sell_est": d.days_to_sell_est,
        "next_action": d.next_action,
        "seller_replied": d.seller_replied,
        "agreed_price": d.agreed_price,
        "extra_costs": d.extra_costs,
        "actual_buy_price": d.actual_buy_price,
        "actual_sell_price": d.actual_sell_price,
        "actual_profit": d.actual_profit,
        "roi_pct": d.roi_pct,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }
    if full and d.analysis:
        a = d.analysis
        data["analysis"] = {
            "why_good": a.why_good,
            "what_to_check": a.what_to_check,
            "questions_to_seller": a.questions_to_seller,
            "scam_flags": a.scam_flags,
            "negotiation_messages": a.negotiation_messages,
            "meeting_checklist": a.meeting_checklist,
            "resale_draft": a.resale_draft,
        }
    return data


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "solomoney-avito-os"}


@app.get("/api/deals", dependencies=[Depends(require_owner)])
async def api_deals(status: str | None = None) -> list[dict]:
    statuses = None
    if status:
        try:
            statuses = [DealStatus(s) for s in status.split(",")]
        except ValueError:
            raise HTTPException(400, "Неизвестный статус")
    async with get_session() as session:
        deals = await deals_service.list_deals(session, statuses=statuses, limit=200)
        return [serialize_deal(d) for d in deals]


@app.get("/api/deals/{deal_id}", dependencies=[Depends(require_owner)])
async def api_deal(deal_id: int) -> dict:
    async with get_session() as session:
        deal = await deals_service.get_deal(session, deal_id)
        if not deal:
            raise HTTPException(404, "Сделка не найдена")
        return serialize_deal(deal, full=True)


@app.post("/api/deals/{deal_id}/status", dependencies=[Depends(require_owner)])
async def api_set_status(deal_id: int, payload: dict) -> dict:
    status = payload.get("status")
    try:
        new_status = DealStatus(status)
    except ValueError:
        raise HTTPException(400, "Неизвестный статус")
    def _int(key):
        v = payload.get(key)
        return int(v) if v not in (None, "") else None

    async with get_session() as session:
        deal = await deals_service.get_deal(session, deal_id)
        if not deal:
            raise HTTPException(404, "Сделка не найдена")
        await deals_service.record_numbers(
            session, deal,
            buy=_int("actual_buy_price"), sell=_int("actual_sell_price"),
            costs=_int("extra_costs"), agreed=_int("agreed_price"),
            seller_replied=payload.get("seller_replied"),
        )
        await deals_service.change_status(session, deal, new_status)
        return serialize_deal(deal, full=True)


@app.post("/api/analyze", dependencies=[Depends(require_owner)])
async def api_analyze(payload: dict) -> dict:
    raw = (payload.get("text") or "").strip()
    if len(raw) < 15:
        raise HTTPException(400, "Слишком короткий текст")
    if not settings.gemini_enabled:
        raise HTTPException(400, "GEMINI_API_KEY не задан")
    try:
        result = await analyzer.analyze_listing(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Анализ не удался: {exc}")
    async with get_session() as session:
        deal = await deals_service.save_analyzed(session, result, source="manual")
        return serialize_deal(deal, full=True)


@app.post("/api/deals/{deal_id}/resale", dependencies=[Depends(require_owner)])
async def api_resale(deal_id: int) -> dict:
    async with get_session() as session:
        deal = await deals_service.get_deal(session, deal_id)
        if not deal:
            raise HTTPException(404, "Сделка не найдена")
        cached = deal.analysis.resale_draft if deal.analysis else None
        title, model = deal.title, deal.model_name or deal.title
        buy = deal.actual_buy_price or deal.target_buy_price or 0
        market, quick = deal.market_price or 0, deal.quick_sale_price or 0
    if cached:
        return {"resale_draft": cached}
    if not settings.gemini_enabled:
        raise HTTPException(400, "GEMINI_API_KEY не задан")
    draft = await analyzer.generate_resale(
        title=title, model_name=model, buy_price=buy,
        market_price=market, quick_sale_price=quick,
    )
    async with get_session() as session:
        deal = await deals_service.get_deal(session, deal_id)
        if deal and deal.analysis:
            deal.analysis.resale_draft = draft.model_dump()
    return {"resale_draft": draft.model_dump()}


@app.get("/api/stats", dependencies=[Depends(require_owner)])
async def api_stats() -> dict:
    async with get_session() as session:
        return await deals_service.stats(session)


@app.get("/api/calibration", dependencies=[Depends(require_owner)])
async def api_calibration() -> list[dict]:
    async with get_session() as session:
        suggestions = await calibration.suggest(session)
    return [
        {
            "model_name": s.model_name, "category": s.category, "samples": s.samples,
            "current_market": s.current_market, "suggested_market": s.suggested_market,
            "suggested_quick": s.suggested_quick,
        }
        for s in suggestions
    ]


@app.post("/api/calibration/apply", dependencies=[Depends(require_owner)])
async def api_calibration_apply() -> dict:
    async with get_session() as session:
        suggestions = await calibration.suggest(session)
    n = calibration.apply(suggestions)
    return {"ok": True, "updated": n}


@app.get("/api/products", dependencies=[Depends(require_owner)])
async def api_products() -> list[dict]:
    return pricebook.list_products()


@app.post("/api/products", dependencies=[Depends(require_owner)])
async def api_add_product(payload: dict) -> dict:
    try:
        category = str(payload["category"]).lower().replace(" ", "_")
        model = str(payload["model_name"]).strip()
        market = int(payload["market_price"])
        quick = int(payload["quick_sale_price"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(400, "Нужны: category, model_name, market_price, quick_sale_price")
    if not model:
        raise HTTPException(400, "Пустое название модели")
    liquidity = str(payload.get("liquidity") or "medium").lower()
    pricebook.add_product(category, model, market, quick, liquidity)
    return {"ok": True, "model_name": model}


@app.delete("/api/products/{model_name}", dependencies=[Depends(require_owner)])
async def api_remove_product(model_name: str) -> dict:
    if not pricebook.remove_product(model_name):
        raise HTTPException(404, "Товар не найден")
    return {"ok": True}


@app.get("/api/opportunities", dependencies=[Depends(require_owner)])
async def api_opportunities(budget: int) -> list[dict]:
    async with get_session() as session:
        opps = await opportunities.suggest_for_budget(session, budget, limit=10)
    return [
        {
            "category": o.category, "model_name": o.model_name, "liquidity": o.liquidity,
            "market_price": o.market_price, "est_buy_price": o.est_buy_price,
            "quick_sale_price": o.quick_sale_price, "net_profit": o.net_profit,
            "margin_pct": o.margin_pct, "units": o.units, "total_potential": o.total_potential,
            "est_days": o.est_days, "real_data": o.real_data,
        }
        for o in opps
    ]


@app.get("/api/searches", dependencies=[Depends(require_owner)])
async def api_searches() -> list[dict]:
    return [
        {"index": i, "name": s.name, "url": s.url, "enabled": s.enabled,
         "category_hint": s.category_hint}
        for i, s in enumerate(searches.load_searches())
    ]


@app.post("/api/searches", dependencies=[Depends(require_owner)])
async def api_add_search(payload: dict) -> dict:
    url = (payload.get("url") or "").strip()
    try:
        s = searches.add_search(url, name=payload.get("name"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "name": s.name}


@app.post("/api/searches/{index}/toggle", dependencies=[Depends(require_owner)])
async def api_toggle_search(index: int) -> dict:
    s = searches.toggle_search(index)
    if not s:
        raise HTTPException(404, "Поиск не найден")
    return {"ok": True, "enabled": s.enabled}


@app.delete("/api/searches/{index}", dependencies=[Depends(require_owner)])
async def api_remove_search(index: int) -> dict:
    if not searches.remove_search(index):
        raise HTTPException(404, "Поиск не найден")
    return {"ok": True}


@app.get("/api/watcher", dependencies=[Depends(require_owner)])
async def api_watcher() -> dict:
    return {"status": await monitor.status_text()}


@app.post("/api/watcher/pause", dependencies=[Depends(require_owner)])
async def api_pause() -> dict:
    await monitor.pause("Пауза из дашборда")
    return {"ok": True}


@app.post("/api/watcher/resume", dependencies=[Depends(require_owner)])
async def api_resume() -> dict:
    await monitor.resume()
    return {"ok": True}


@app.get("/api/export.csv", dependencies=[Depends(require_owner)])
async def api_export_csv() -> StreamingResponse:
    async with get_session() as session:
        deals = await deals_service.list_deals(session, limit=10000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "status", "verdict", "title", "seller_price", "market_price",
        "quick_sale_price", "target_buy_price", "expected_profit", "margin_pct",
        "risk_score", "actual_buy_price", "actual_sell_price", "created_at",
    ])
    for d in deals:
        writer.writerow([
            d.id, d.status.value, d.verdict.value if d.verdict else "", d.title,
            d.seller_price or "", d.market_price or "", d.quick_sale_price or "",
            d.target_buy_price or "", d.expected_profit or "", d.margin_pct or "",
            d.risk_score or "", d.actual_buy_price or "", d.actual_sell_price or "",
            d.created_at.isoformat() if d.created_at else "",
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=deals.csv"},
    )


@app.post("/api/backup", dependencies=[Depends(require_owner)])
async def api_backup() -> dict:
    src = settings.db_path
    if not src.exists():
        raise HTTPException(404, "БД ещё не создана")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dst = settings.backups_dir / f"solomoney_{ts}.db"
    shutil.copy2(src, dst)
    return {"ok": True, "backup": dst.name}


# Статика Mini App (в самом конце, чтобы не перехватывать /api).
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
