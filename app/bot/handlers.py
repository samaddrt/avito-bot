"""Хендлеры бота: приём текста объявления, карточки, кнопки, команды."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.ai import analyzer
from app.bot import formatting, keyboards
from app.config import settings
from app.core import calibration, opportunities, pricebook
from app.core import deals as deals_service
from app.db import get_session
from app.models import DealStatus
from app.watcher import monitor, searches

logger = logging.getLogger(__name__)
router = Router()


# --------- Доступ только владельцу ---------
@router.message(F.from_user.id != settings.owner_telegram_id)
async def _deny_message(message: Message) -> None:
    await message.answer("Это личный агент. Доступ только у владельца.")


@router.callback_query(F.from_user.id != settings.owner_telegram_id)
async def _deny_cb(cb: CallbackQuery) -> None:
    await cb.answer("Доступ запрещён", show_alert=True)


# --------- Команды ---------
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    text = (
        "👋 <b>SoloMoney Avito OS</b> — твой личный агент по арбитражу.\n\n"
        "Я мониторю Avito и присылаю только выгодные варианты с готовым решением.\n\n"
        "<b>Что умею:</b>\n"
        "• Пришли текст объявления — дам полный анализ сделки\n"
        "• Сам нахожу выгодные лоты по твоим поискам\n"
        "• Готовлю сообщения для торга и черновики перепродажи\n\n"
        "<b>Поиск и анализ:</b>\n"
        "/find БЮДЖЕТ — что выгодно брать на сумму\n"
        "/products — каталог товаров\n"
        "/addproduct — добавить свой товар\n"
        "/searches /addsearch URL — поиски мониторинга\n\n"
        "<b>Сделки и деньги:</b>\n"
        "/today /deals — активные сделки\n"
        "/stats — заработок, ROI, воронка\n"
        "/price ID buy|sell|cost СУММА — записать цифры\n"
        "/calibrate — подстроить цены под твои продажи\n"
        "/watch /pause /resume — мониторинг\n\n"
        "Просто вставь текст объявления, чтобы начать."
    )
    await message.answer(text, reply_markup=keyboards.open_app())


@router.message(Command("watch"))
async def cmd_watch(message: Message) -> None:
    await message.answer(await monitor.status_text())


@router.message(Command("pause"))
async def cmd_pause(message: Message) -> None:
    await monitor.pause("Пауза по команде /pause")
    await message.answer("⏸ Мониторинг на паузе. /resume — возобновить.")


@router.message(Command("resume"))
async def cmd_resume(message: Message) -> None:
    await monitor.resume()
    await message.answer("▶️ Мониторинг возобновлён.")


def _searches_keyboard():
    kb = InlineKeyboardBuilder()
    for i, s in enumerate(searches.load_searches()):
        mark = "✅" if s.enabled else "⏹"
        kb.button(text=f"{mark} {s.name[:28]}", callback_data=f"search_toggle:{i}")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("searches"))
async def cmd_searches(message: Message) -> None:
    all_s = searches.load_searches()
    if not all_s:
        await message.answer(
            "Поиски не настроены.\n\nДобавь так: <code>/addsearch URL_поиска_Avito</code>\n"
            "(на Avito настрой фильтры, сортировку «по дате», скопируй ссылку)."
        )
        return
    await message.answer(
        "<b>Поиски мониторинга</b> (нажми, чтобы вкл/выкл):\n"
        "Добавить новый: <code>/addsearch URL</code>",
        reply_markup=_searches_keyboard(),
    )


@router.message(Command("addsearch"))
async def cmd_addsearch(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: <code>/addsearch URL_поиска_Avito [название]</code>")
        return
    arg = parts[1].strip()
    bits = arg.split(maxsplit=1)
    url = bits[0]
    name = bits[1] if len(bits) > 1 else None
    try:
        s = searches.add_search(url, name=name)
    except ValueError as exc:
        await message.answer(f"Не получилось: {exc}")
        return
    await message.answer(
        f"✅ Поиск добавлен: <b>{s.name}</b>\nКатегория: {s.category_hint or 'авто'}\n"
        f"Мониторинг подхватит его в следующем проходе.",
        reply_markup=_searches_keyboard(),
    )


@router.callback_query(F.data.startswith("search_toggle:"))
async def cb_search_toggle(cb: CallbackQuery) -> None:
    idx = int(cb.data.split(":")[1])
    s = searches.toggle_search(idx)
    if not s:
        await cb.answer("Не найдено", show_alert=True)
        return
    await cb.answer(f"{'Включён' if s.enabled else 'Выключен'}: {s.name}")
    try:
        await cb.message.edit_reply_markup(reply_markup=_searches_keyboard())
    except Exception:  # noqa: BLE001
        pass


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    async with get_session() as session:
        s = await deals_service.stats(session)
    funnel = s["funnel"]
    funnel_txt = "\n".join(f"  • {k}: {v}" for k, v in funnel.items()) or "  • пусто"

    def m(v):
        return f"{v:,}".replace(",", " ") if v is not None else "—"

    roi = f"{s['roi_pct']}%" if s.get("roi_pct") is not None else "—"
    wr = f"{s['win_rate']}%" if s.get("win_rate") is not None else "—"
    avg = f"{s['avg_days_to_sell']} дн." if s.get("avg_days_to_sell") is not None else "—"
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"<b>Воронка:</b>\n{funnel_txt}\n\n"
        f"💰 Чистый заработок: <b>{m(s['realized_profit'])}</b> ₽\n"
        f"📅 За неделю: {m(s['week_profit'])} ₽ · за месяц: {m(s['month_profit'])} ₽\n"
        f"📈 ROI: <b>{roi}</b> · Win-rate: {wr} · Ср. срок продажи: {avg}\n"
        f"🧊 Заморожено в товаре: {m(s['capital_tied'])} ₽\n"
        f"🔮 Потенциал активных: {m(s['potential_profit'])} ₽\n"
        f"✅ Продано сделок: {s['sold_count']}"
    )
    await message.answer(text)


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    async with get_session() as session:
        active = await deals_service.list_deals(
            session,
            statuses=[DealStatus.new, DealStatus.contacted, DealStatus.negotiating],
            limit=10,
        )
    if not active:
        await message.answer("Сегодня активных сделок нет. Жду новые объявления 👀")
        return
    lines = ["<b>🗓 Сводка дня — топ активных сделок:</b>\n"]
    for d in active:
        lines.append(formatting.short_line(d))
    await message.answer("\n".join(lines))


@router.message(Command("price"))
async def cmd_price(message: Message) -> None:
    """Зафиксировать цифры: /price <id> buy|sell|cost <сумма>"""
    parts = (message.text or "").split()
    if len(parts) != 4 or not parts[1].isdigit() or not parts[3].isdigit():
        await message.answer(
            "Формат: <code>/price ID buy|sell|cost СУММА</code>\n"
            "Например: <code>/price 12 buy 28000</code>"
        )
        return
    deal_id, field, amount = int(parts[1]), parts[2].lower(), int(parts[3])
    kwargs = {"buy": amount} if field == "buy" else \
             {"sell": amount} if field == "sell" else \
             {"costs": amount} if field == "cost" else None
    if kwargs is None:
        await message.answer("Поле должно быть buy, sell или cost.")
        return
    async with get_session() as session:
        deal = await deals_service.get_deal(session, deal_id)
        if not deal:
            await message.answer("Сделка не найдена.")
            return
        await deals_service.record_numbers(session, deal, **kwargs)
        profit = deal.actual_profit
        title = deal.title
    extra = f"\nЧистая прибыль: <b>{profit:,}</b> ₽".replace(",", " ") if profit is not None else ""
    await message.answer(f"✅ «{title}»: {field} = {amount:,} ₽{extra}".replace(",", " "))


@router.callback_query(F.data.startswith("replied:"))
async def cb_replied(cb: CallbackQuery) -> None:
    deal_id = int(cb.data.split(":")[1])
    async with get_session() as session:
        deal = await deals_service.get_deal(session, deal_id)
        if not deal:
            await cb.answer("Не найдено", show_alert=True)
            return
        await deals_service.record_numbers(session, deal, seller_replied=True)
        await deals_service.change_status(session, deal, DealStatus.negotiating)
    await cb.answer("Отмечено: продавец ответил")


@router.message(Command("products"))
async def cmd_products(message: Message) -> None:
    products = pricebook.list_products()
    if not products:
        await message.answer("Каталог пуст. Добавь товар: /addproduct")
        return
    by_cat: dict[str, list] = {}
    for p in products:
        by_cat.setdefault(p["category"], []).append(p)
    lines = ["<b>📦 Каталог товаров</b>\n"]
    liq_ru = {"high": "🟢", "medium": "🟡", "low": "🔴"}
    for cat, items in by_cat.items():
        lines.append(f"\n<b>{cat}</b>:")
        for p in items:
            lines.append(
                f"  {liq_ru.get(p['liquidity'],'⚪️')} {p['model_name']} — "
                f"рынок {p['market_price']:,}₽, быстрая {p['quick_sale_price']:,}₽".replace(",", " ")
            )
    lines.append(
        "\n\nДобавить: <code>/addproduct категория | модель | рынок | быстрая | high/medium/low</code>\n"
        "Удалить: <code>/delproduct модель</code>"
    )
    await message.answer("\n".join(lines))


@router.message(Command("addproduct"))
async def cmd_addproduct(message: Message) -> None:
    raw = (message.text or "").split(maxsplit=1)
    if len(raw) < 2 or "|" not in raw[1]:
        await message.answer(
            "Формат (через |):\n"
            "<code>/addproduct категория | модель | рыночная_цена | быстрая_цена | ликвидность</code>\n\n"
            "Пример:\n<code>/addproduct airpods | AirPods Pro 2 | 18000 | 16000 | high</code>\n"
            "Ликвидность: high / medium / low (необязательно, по умолчанию medium)."
        )
        return
    parts = [p.strip() for p in raw[1].split("|")]
    if len(parts) < 4:
        await message.answer("Нужно минимум 4 поля: категория | модель | рынок | быстрая")
        return
    category, model, market_s, quick_s = parts[0], parts[1], parts[2], parts[3]
    liquidity = parts[4].lower() if len(parts) > 4 else "medium"
    market = "".join(ch for ch in market_s if ch.isdigit())
    quick = "".join(ch for ch in quick_s if ch.isdigit())
    if not market or not quick:
        await message.answer("Цены должны быть числами.")
        return
    pricebook.add_product(category.lower().replace(" ", "_"), model, int(market), int(quick), liquidity)
    await message.answer(
        f"✅ Добавлено в каталог: <b>{model}</b>\n"
        f"Категория: {category} · рынок {int(market):,}₽ · быстрая {int(quick):,}₽ · {liquidity}".replace(",", " ")
        + "\n\nТеперь он участвует в анализе. Создай поиск под него: /addsearch URL"
    )


@router.message(Command("delproduct"))
async def cmd_delproduct(message: Message) -> None:
    raw = (message.text or "").split(maxsplit=1)
    if len(raw) < 2:
        await message.answer("Использование: <code>/delproduct точное название модели</code>")
        return
    if pricebook.remove_product(raw[1].strip()):
        await message.answer(f"🗑 Удалено из каталога: {raw[1].strip()}")
    else:
        await message.answer("Не найдено. Точное имя смотри в /products.")


@router.message(Command("find"))
async def cmd_find(message: Message) -> None:
    parts = (message.text or "").split()
    budget = next((int("".join(ch for ch in p if ch.isdigit()))
                   for p in parts[1:] if any(ch.isdigit() for ch in p)), None)
    if not budget:
        await message.answer(
            "Укажи бюджет: <code>/find 50000</code>\n"
            "Покажу, что выгоднее всего брать на эту сумму."
        )
        return
    async with get_session() as session:
        opps = await opportunities.suggest_for_budget(session, budget, limit=8)
    if not opps:
        await message.answer(
            f"На {budget:,}₽ в каталоге нет подходящих позиций.\n".replace(",", " ")
            + "Добавь товары дешевле бюджета через /addproduct."
        )
        return
    liq_ru = {"high": "ходовой", "medium": "средний", "low": "медленный"}
    lines = [f"<b>💡 Что брать на бюджет {budget:,}₽</b>".replace(",", " "),
             "<i>(ранжировано по марже и ликвидности)</i>\n"]
    for i, o in enumerate(opps, 1):
        star = " ⭐️" if o.real_data else ""
        lines.append(
            f"{i}. <b>{o.model_name}</b>{star}\n"
            f"   Купить ~{o.est_buy_price:,}₽ → продать ~{o.quick_sale_price:,}₽\n".replace(",", " ")
            + f"   Чистыми ~{o.net_profit:,}₽ за штуку · маржа {o.margin_pct:.0f}% · {liq_ru.get(o.liquidity)}\n".replace(",", " ")
            + f"   В бюджет влезает: {o.units} шт → потенциал ~{o.total_potential:,}₽".replace(",", " ")
        )
    lines.append("\n⭐️ — маржа уточнена по твоим реальным продажам.")
    await message.answer("\n".join(lines))


@router.message(Command("calibrate"))
async def cmd_calibrate(message: Message) -> None:
    async with get_session() as session:
        suggestions = await calibration.suggest(session)
    if not suggestions:
        await message.answer(
            "Пока нечего калибровать. Нужно ≥2 проданных сделок по модели с "
            "фактическими ценами — тогда подстрою прайсбук под твою реальную статистику."
        )
        return
    lines = ["<b>📐 Калибровка цен по твоим продажам:</b>\n"]
    for s in suggestions:
        cur = f"{s.current_market}₽" if s.current_market else "—"
        lines.append(
            f"• {s.model_name}: {cur} → <b>{s.suggested_market}₽</b> "
            f"(по {s.samples} продаж.)"
        )
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Применить", callback_data="calib:apply")
    await message.answer("\n".join(lines), reply_markup=kb.as_markup())


@router.callback_query(F.data == "calib:apply")
async def cb_calib_apply(cb: CallbackQuery) -> None:
    async with get_session() as session:
        suggestions = await calibration.suggest(session)
    n = calibration.apply(suggestions)
    await cb.answer(f"Обновлено моделей: {n}")
    await cb.message.answer(f"✅ Прайсбук обновлён по {n} моделям из твоей статистики.")


@router.message(Command("deals"))
async def cmd_deals(message: Message) -> None:
    async with get_session() as session:
        active = await deals_service.list_deals(
            session,
            statuses=[DealStatus.new, DealStatus.contacted, DealStatus.negotiating,
                      DealStatus.bought, DealStatus.listed, DealStatus.watching],
            limit=20,
        )
    if not active:
        await message.answer("Активных сделок нет.")
        return
    lines = ["<b>Активные сделки:</b>\n"]
    for d in active:
        lines.append(f"#{d.id} {formatting.short_line(d)}")
    await message.answer("\n".join(lines))


# --------- Приём текста объявления ---------
@router.message(F.text & ~F.text.startswith("/"))
async def on_listing_text(message: Message) -> None:
    raw = message.text or ""
    if len(raw.strip()) < 15:
        await message.answer("Пришли текст объявления (заголовок, цена, описание).")
        return

    if not settings.gemini_enabled:
        await message.answer(
            "⚠️ Не задан GEMINI_API_KEY в .env — анализ недоступен. "
            "Получи ключ на https://aistudio.google.com/app/apikey"
        )
        return

    wait = await message.answer("🔎 Анализирую сделку…")
    try:
        result = await analyzer.analyze_listing(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Анализ не удался: %s", exc)
        await wait.edit_text(f"Не получилось проанализировать: {exc}")
        return

    async with get_session() as session:
        deal = await deals_service.save_analyzed(session, result, source="manual")
        deal_id = deal.id
        card = formatting.deal_card(deal)

    await wait.edit_text(card, reply_markup=keyboards.deal_actions(deal_id),
                         disable_web_page_preview=True)


# --------- Колбэки ---------
@router.callback_query(F.data.startswith("status:"))
async def cb_status(cb: CallbackQuery) -> None:
    _, deal_id, status = cb.data.split(":")
    async with get_session() as session:
        deal = await deals_service.get_deal(session, int(deal_id))
        if not deal:
            await cb.answer("Сделка не найдена", show_alert=True)
            return
        await deals_service.change_status(session, deal, DealStatus(status))
        title = deal.title
    await cb.answer(f"Статус: {status}")
    if status == "contacted":
        kb = InlineKeyboardBuilder()
        kb.button(text="📩 Продавец ответил", callback_data=f"replied:{deal_id}")
        await cb.message.answer(
            f"📌 «{title}» — в работе. Отметь, когда продавец ответит.\n"
            f"Цифры фиксируй так: <code>/price {deal_id} buy 28000</code>",
            reply_markup=kb.as_markup(),
        )
    elif status == "bought":
        await cb.message.answer(
            f"✅ «{title}» — куплено. Запиши цену покупки: "
            f"<code>/price {deal_id} buy СУММА</code>, затем жми «📦 → перепродажа».",
            reply_markup=keyboards.deal_status_flow(int(deal_id)),
        )
    elif status == "sold":
        await cb.message.answer(
            f"💰 «{title}» — продано! Запиши цену продажи: "
            f"<code>/price {deal_id} sell СУММА</code> — посчитаю чистую прибыль и ROI."
        )


@router.callback_query(F.data.startswith("msg:"))
async def cb_messages(cb: CallbackQuery) -> None:
    deal_id = int(cb.data.split(":")[1])
    await cb.answer()
    await cb.message.answer(
        "Выбери тон сообщения продавцу:",
        reply_markup=keyboards.negotiation_tones(deal_id),
    )


@router.callback_query(F.data.startswith("tone:"))
async def cb_tone(cb: CallbackQuery) -> None:
    _, deal_id, tone = cb.data.split(":")
    async with get_session() as session:
        deal = await deals_service.get_deal(session, int(deal_id))
        if not deal:
            await cb.answer("Сделка не найдена", show_alert=True)
            return
        nego = (deal.analysis.negotiation_messages if deal.analysis else None) or {}
        text = nego.get(tone)
        title = deal.title
        seller = deal.seller_price or deal.market_price or 0
        target = deal.target_buy_price or 0
        checks = (deal.analysis.what_to_check if deal.analysis else []) or []

    if not text:
        await cb.answer("Генерирую…")
        try:
            msgs = await analyzer.generate_negotiation(
                title=title, seller_price=seller, target_price=target, what_to_check=checks
            )
            text = getattr(msgs, tone, None)
            async with get_session() as session:
                deal = await deals_service.get_deal(session, int(deal_id))
                if deal and deal.analysis:
                    deal.analysis.negotiation_messages = msgs.model_dump()
        except Exception as exc:  # noqa: BLE001
            await cb.message.answer(f"Не удалось сгенерировать: {exc}")
            return
    else:
        await cb.answer()

    await cb.message.answer(
        f"💬 <b>Сообщение продавцу:</b>\n\n<code>{text}</code>\n\n"
        "<i>Скопируй и отправь в чате Avito сам.</i>"
    )


@router.callback_query(F.data.startswith("resale:"))
async def cb_resale(cb: CallbackQuery) -> None:
    deal_id = int(cb.data.split(":")[1])
    await cb.answer("Готовлю черновик…")
    async with get_session() as session:
        deal = await deals_service.get_deal(session, deal_id)
        if not deal:
            await cb.answer("Сделка не найдена", show_alert=True)
            return
        # Если ещё не куплено — переводим в bought.
        if deal.status not in (DealStatus.bought, DealStatus.listed, DealStatus.sold):
            await deals_service.change_status(session, deal, DealStatus.bought)
        cached = deal.analysis.resale_draft if deal.analysis else None
        title, model = deal.title, deal.model_name or deal.title
        buy = deal.actual_buy_price or deal.target_buy_price or 0
        market = deal.market_price or 0
        quick = deal.quick_sale_price or 0

    if cached:
        await cb.message.answer(formatting.resale_card(cached),
                                reply_markup=keyboards.deal_status_flow(deal_id))
        return

    try:
        draft = await analyzer.generate_resale(
            title=title, model_name=model, buy_price=buy,
            market_price=market, quick_sale_price=quick,
        )
    except Exception as exc:  # noqa: BLE001
        await cb.message.answer(f"Не удалось сгенерировать черновик: {exc}")
        return

    async with get_session() as session:
        deal = await deals_service.get_deal(session, deal_id)
        if deal and deal.analysis:
            deal.analysis.resale_draft = draft.model_dump()
    await cb.message.answer(formatting.resale_card(draft.model_dump()),
                            reply_markup=keyboards.deal_status_flow(deal_id))
