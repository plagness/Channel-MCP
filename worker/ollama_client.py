from __future__ import annotations

import json
import re
import time
from typing import Any, Tuple

import aiohttp

DEFAULT_SYSTEM_PROMPT = (
    "Ты извлекаешь теги и короткие сигналы из текста. "
    "Верни ТОЛЬКО JSON вида: "
    "{\"tags\": [\"...\"], \"emoji\": [\"...\"], "
    "\"code\": {\"sentiment\":0.0, \"urgency\":0.0, \"market\":0.0, "
    "\"macro\":0.0, \"geopolitics\":0.0, \"company\":0.0, "
    "\"commodities\":0.0, \"fx\":0.0, \"rates\":0.0, \"crypto\":0.0, "
    "\"usefulness\":0.0, \"ad\":0.0}}. "
    "Строго один JSON-объект без пояснений, без Markdown и без кода. "
    "Если нечего добавить — верни пустые массивы и нули. "
    "Теги на русском, без эмодзи и без #. "
    "Каждое слово с большой буквы. "
    "Аббревиатуры сохраняй (например, ЦБ, IMOEX2, USD/RUB). "
    "Если встречаются полные формы (например, Центральный банк), "
    "предпочитай сокращение (ЦБ). "
    "Теги должны быть короткими (1-3 слова) и в именительном падеже "
    "(Мосбиржа, Озон, Совкомбанк — не склоняй). "
    "Не добавляй фразы вроде 'Рост выручки Аэрофлота' — "
    "выделяй сущность (Аэрофлот) и тему (Выручка). "
    "Избегай общих прилагательных/глаголов (Крупные, Частный, Замедлился). "
    "Не добавляй отдельные числа, цены, проценты или даты. "
    "Не используй латиницу, если есть русское написание. "
    "Эмодзи только из списка: "
    "⚠️ 🔥 📉 📈 💰 🪙 💱 🛢️ 🏦 🏭 🧾 📰 🧠 🌍 🛡️ 🧪 🚀 🎯 ✅ ❌ 😡 😢 😊 🎉 "
    "🥇 🥈 🥉 🪨 🪵 🌾 🌽 🍬 🌱 ⛽️ ⚡️ ✈️ 🛰️ 🏠 🐄 🐟 📊 💹 ☢️ "
    "🚢 💥 💣 🎮 🕹️ 🏆 ⚔️ 🇷🇺 🇺🇸 🇨🇳 🇪🇺 🇬🇧 🇩🇪 🇫🇷 🇮🇹 🇯🇵 🇰🇷 🇮🇳 🇧🇷 🇹🇷 🇺🇦 🇨🇦 🇦🇺 "
    "🇸🇦 🇦🇪 🇮🇱 🇮🇷 🇮🇶 🇪🇬 🇵🇱 🇨🇿 🇳🇱 🇧🇪 🇪🇸 🇵🇹 🇸🇪 🇳🇴 🇫🇮 🇩🇰 🇨🇭 🇦🇹 "
    "🇲🇽 🇦🇷 🇨🇱 🇨🇴 🇰🇿 🇧🇾 ⬆️ ⬇️ "
    "(обычно 4–8, максимум 10). "
    "Старайся делать эмодзи-ребус в порядке: событие → направление → ресурс → страна. "
    "Пример: 🚢💣📉🛢🇷🇺. "
    "Коды: sentiment в диапазоне -1..1, остальные 0..1. "
    "usefulness = полезность (0..1), ad = вероятность рекламы (0..1). "
    "Не дублируй теги и не выдумывай."
)


def _repair_json(blob: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", blob)


def _extract_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    blob = match.group(0).strip()
    for candidate in (blob, _repair_json(blob)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _tokens_per_second(count: int | None, duration_ns: int | None) -> float | None:
    if not count or not duration_ns or duration_ns <= 0:
        return None
    seconds = duration_ns / 1_000_000_000
    if seconds <= 0:
        return None
    return count / seconds


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _normalize_code(payload: dict[str, Any] | None) -> dict[str, float]:
    keys = [
        "sentiment",
        "urgency",
        "market",
        "macro",
        "geopolitics",
        "company",
        "commodities",
        "fx",
        "rates",
        "crypto",
        "usefulness",
        "ad",
    ]
    result: dict[str, float] = {}
    for key in keys:
        raw = payload.get(key) if isinstance(payload, dict) else None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        if key == "sentiment":
            result[key] = _clamp(value, -1.0, 1.0)
        else:
            result[key] = _clamp(value, 0.0, 1.0)
    return result


MAX_EMOJI = 10


def _merge_code(base: dict[str, float], fallback: dict[str, float]) -> dict[str, float]:
    merged = dict(base)
    for key, value in fallback.items():
        if key == "sentiment":
            if abs(value) > abs(merged.get(key, 0.0)):
                merged[key] = value
            continue
        merged[key] = max(merged.get(key, 0.0), value)
    return merged

FLAG_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "🇷🇺": [re.compile(r"\bросси\w*\b"), re.compile(r"\bрф\b")],
    "🇺🇸": [re.compile(r"\bсша\b"), re.compile(r"\busa\b"), re.compile(r"\bunited states\b"), re.compile(r"\bамерик\w*\b")],
    "🇨🇳": [re.compile(r"\bкитай\w*\b"), re.compile(r"\bкнр\b"), re.compile(r"\bchina\b")],
    "🇪🇺": [re.compile(r"\bевросоюз\b"), re.compile(r"\bевропа\b"), re.compile(r"\beu\b"), re.compile(r"\beurozone\b")],
    "🇬🇧": [re.compile(r"\bвеликобрит\w*\b"), re.compile(r"\bбритан\w*\b"), re.compile(r"\buk\b"), re.compile(r"\bангли\w*\b")],
    "🇩🇪": [re.compile(r"\bгерман\w*\b"), re.compile(r"\bнемец\w*\b"), re.compile(r"\bdeutsch\w*\b")],
    "🇫🇷": [re.compile(r"\bфранц\w*\b"), re.compile(r"\bfrance\b")],
    "🇮🇹": [re.compile(r"\bитал\w*\b"), re.compile(r"\bitaly\b")],
    "🇯🇵": [re.compile(r"\bяпон\w*\b"), re.compile(r"\bjapan\b")],
    "🇰🇷": [re.compile(r"\bкоре\w*\b"), re.compile(r"\bkorea\b")],
    "🇮🇳": [re.compile(r"\bиндия\b"), re.compile(r"\bиндийск\w*\b"), re.compile(r"\bindia\b")],
    "🇧🇷": [re.compile(r"\bбразил\w*\b"), re.compile(r"\bbrazil\b")],
    "🇹🇷": [re.compile(r"\bтурц\w*\b"), re.compile(r"\bturkey\b")],
    "🇺🇦": [re.compile(r"\bукраин\w*\b"), re.compile(r"\bukraine\b")],
    "🇨🇦": [re.compile(r"\bканада\b"), re.compile(r"\bcanada\b")],
    "🇦🇺": [re.compile(r"\bавстрал\w*\b"), re.compile(r"\baustralia\b")],
    "🇸🇦": [re.compile(r"\bсауд\w*\b"), re.compile(r"\bksa\b"), re.compile(r"\bsaudi\b")],
    "🇦🇪": [re.compile(r"\bоаэ\b"), re.compile(r"\bэмират\w*\b"), re.compile(r"\buae\b")],
    "🇮🇱": [re.compile(r"\bизраил\w*\b"), re.compile(r"\bisrael\b")],
    "🇮🇷": [re.compile(r"\bиран\b"), re.compile(r"\biran\b")],
    "🇮🇶": [re.compile(r"\bирак\b"), re.compile(r"\biraq\b")],
    "🇪🇬": [re.compile(r"\bегипт\w*\b"), re.compile(r"\begypt\b")],
    "🇵🇱": [re.compile(r"\bпольш\w*\b"), re.compile(r"\bpoland\b")],
    "🇨🇿": [re.compile(r"\bчех\w*\b"), re.compile(r"\bczech\b")],
    "🇳🇱": [re.compile(r"\bнидерланд\w*\b"), re.compile(r"\bголланд\w*\b"), re.compile(r"\bnetherlands\b")],
    "🇧🇪": [re.compile(r"\bбельг\w*\b"), re.compile(r"\bbelgium\b")],
    "🇪🇸": [re.compile(r"\bиспан\w*\b"), re.compile(r"\bspain\b")],
    "🇵🇹": [re.compile(r"\bпортугал\w*\b"), re.compile(r"\bportugal\b")],
    "🇸🇪": [re.compile(r"\bшвец\w*\b"), re.compile(r"\bsweden\b")],
    "🇳🇴": [re.compile(r"\bнорвег\w*\b"), re.compile(r"\bnorway\b")],
    "🇫🇮": [re.compile(r"\bфинлянд\w*\b"), re.compile(r"\bfinland\b")],
    "🇩🇰": [re.compile(r"\bдани\w*\b"), re.compile(r"\bдатск\w*\b"), re.compile(r"\bdenmark\b")],
    "🇨🇭": [re.compile(r"\bшвейцар\w*\b"), re.compile(r"\bswitzerland\b")],
    "🇦🇹": [re.compile(r"\bавстр\w*\b"), re.compile(r"\baustria\b")],
    "🇲🇽": [re.compile(r"\bмексик\w*\b"), re.compile(r"\bmexico\b")],
    "🇦🇷": [re.compile(r"\bаргентин\w*\b"), re.compile(r"\bargentina\b")],
    "🇨🇱": [re.compile(r"\bчили\b"), re.compile(r"\bchile\b")],
    "🇨🇴": [re.compile(r"\bколумб\w*\b"), re.compile(r"\bcolombia\b")],
    "🇰🇿": [re.compile(r"\bказах\w*\b"), re.compile(r"\bkazakhstan\b")],
    "🇧🇾": [re.compile(r"\bбеларус\w*\b"), re.compile(r"\bрб\b"), re.compile(r"\bbelarus\b")],
}

ALLOWED_EMOJI = {
    "⚠️",
    "🔥",
    "📉",
    "📈",
    "💰",
    "🪙",
    "💱",
    "🛢️",
    "🏦",
    "🏭",
    "🧾",
    "📰",
    "🧠",
    "🌍",
    "🛡️",
    "🧪",
    "🚀",
    "🎯",
    "✅",
    "❌",
    "😡",
    "😢",
    "😊",
    "🎉",
    "🥇",
    "🥈",
    "🥉",
    "🪨",
    "🪵",
    "🌾",
    "🌽",
    "🍬",
    "🌱",
    "⛽️",
    "⚡️",
    "✈️",
    "🛰️",
    "🏠",
    "🐄",
    "🐟",
    "📊",
    "💹",
    "☢️",
    "🚢",
    "💥",
    "💣",
    "🎮",
    "🕹️",
    "🏆",
    "⚔️",
    "🇷🇺",
    "🇺🇸",
    "🇨🇳",
    "🇪🇺",
    "🇬🇧",
    "🇩🇪",
    "🇫🇷",
    "🇮🇹",
    "🇯🇵",
    "🇰🇷",
    "🇮🇳",
    "🇧🇷",
    "🇹🇷",
    "🇺🇦",
    "🇨🇦",
    "🇦🇺",
    "🇸🇦",
    "🇦🇪",
    "🇮🇱",
    "🇮🇷",
    "🇮🇶",
    "🇪🇬",
    "🇵🇱",
    "🇨🇿",
    "🇳🇱",
    "🇧🇪",
    "🇪🇸",
    "🇵🇹",
    "🇸🇪",
    "🇳🇴",
    "🇫🇮",
    "🇩🇰",
    "🇨🇭",
    "🇦🇹",
    "🇲🇽",
    "🇦🇷",
    "🇨🇱",
    "🇨🇴",
    "🇰🇿",
    "🇧🇾",
    "⬆️",
    "⬇️",
}


def _fallback_emoji(tags: list[str], code: dict[str, float], text: str | None) -> list[str]:
    result: list[str] = []
    short_cache: dict[str, re.Pattern[str]] = {}

    def add(emoji: str) -> None:
        if emoji in ALLOWED_EMOJI and emoji not in result:
            result.append(emoji)

    tag_text = " ".join(tags).lower()
    text_l = (text or "").lower()

    def match_key(value: str, key: str) -> bool:
        if len(key) <= 4:
            pattern = short_cache.get(key)
            if pattern is None:
                pattern = re.compile(rf"\b{re.escape(key)}\w*\b")
                short_cache[key] = pattern
            return bool(pattern.search(value))
        return key in value

    def has_any(keys: tuple[str, ...]) -> bool:
        return any(match_key(text_l, k) for k in keys) or any(match_key(tag_text, k) for k in keys)

    def has_any_text(keys: tuple[str, ...]) -> bool:
        return any(match_key(text_l, k) for k in keys)

    # Event / incident (order matters)
    if has_any_text(("танкер", "судно", "корабл", "порт", "мор")):
        add("🚢")
    if has_any_text(("взрыв", "взорвал", "взрыво", "удар", "обстрел", "бомб", "взрывчат")):
        add("💣")
    elif has_any_text(("авар", "катастроф", "пожар")):
        add("💥")

    # Direction
    if has_any_text(("упал", "сниз", "паден", "обвал", "просел")):
        add("📉")
    elif has_any_text(("вырос", "поднял", "увелич", "прибав", "раст")):
        add("📈")
    elif code.get("market", 0) > 0.6:
        add("📈" if code.get("sentiment", 0) >= 0 else "📉")

    # Commodity / domain
    if has_any(("золот", "gold", "золото")):
        add("🥇")
    if has_any(("серебр", "silver")):
        add("🥈")
    if has_any(("медь", "copper", "bronze", "бронз")):
        add("🥉")
    if has_any(("платин", "паллад")):
        add("🪙")
    if has_any(("нефт", "brent", "urals")):
        add("🛢️")
    if has_any(("газ", "lng")):
        add("⛽️")
    if has_any(("уголь", "руда", "желез", "алюмин", "никел", "литий", "кобальт", "уран")):
        add("🪨")
    if has_any(("лес", "древесин", "пиломат", "лесомат")):
        add("🪵")
    if has_any(("зерн", "пшениц", "ячмен", "овес")):
        add("🌾")
    if has_any(("кукуруз",)):
        add("🌽")
    if has_any(("сахар",)):
        add("🍬")
    if has_any(("удобр", "агро", "аграр", "посев")):
        add("🌱")
    if has_any(("мясо", "говя", "скот", "молок")):
        add("🐄")
    if has_any(("рыб", "seafood")):
        add("🐟")
    if has_any(("электроэнерг", "мощност", "энергосистем")):
        add("⚡️")
    if has_any(("авиа", "самолет", "аэропорт")):
        add("✈️")
    if has_any(("космос", "спутник", "space")):
        add("🛰️")
    if has_any(("недвиж", "ипотек", "строительств")):
        add("🏠")
    if has_any(("ядер", "атом", "радиац")):
        add("☢️")
    if has_any(("рынок", "индекс", "котиров")):
        add("📊")
    if code.get("commodities", 0) > 0.7 and "🥇" not in result and "🛢️" not in result and "🪨" not in result:
        add("🪙")

    # Gaming / esports
    if has_any(("dota", "dota 2", "cs2", "cs:go", "counter-strike", "киберспорт", "esports", "гейм", "игр", "геймер")):
        add("🎮")
    if has_any(("турнир", "чемпионат", "лига", "season", "финал", "playoff", "плей-офф")):
        add("🏆")
    if has_any(("матч", "серия", "против", "vs")):
        add("⚔️")
    if has_any(("приз", "призов", "выиграл", "побед", "$", "миллион", "тыс")) and "💰" not in result:
        add("💰")

    # Geography (strict word-boundary match)
    for flag, patterns in FLAG_PATTERNS.items():
        if any(p.search(text_l) for p in patterns):
            add(flag)

    # Finance / policy / urgency
    if "/" in tag_text or code.get("fx", 0) > 0.6:
        add("💱")
    if "банк" in tag_text or "цб" in tag_text or code.get("rates", 0) > 0.7:
        add("🏦")
    if code.get("geopolitics", 0) > 0.6 and "🌍" not in result:
        add("🌍")
    if code.get("urgency", 0) > 0.7:
        add("⚠️")

    if not result:
        add("📰")

    return result[:MAX_EMOJI]


def _fallback_code(tags: list[str], text: str | None) -> dict[str, float]:
    code = {
        "sentiment": 0.0,
        "urgency": 0.0,
        "market": 0.0,
        "macro": 0.0,
        "geopolitics": 0.0,
        "company": 0.0,
        "commodities": 0.0,
        "fx": 0.0,
        "rates": 0.0,
        "crypto": 0.0,
        "usefulness": 0.0,
        "ad": 0.0,
    }

    tag_text = " ".join(tags).lower()
    text_l = (text or "").lower()

    def has_any(keys: tuple[str, ...]) -> bool:
        return any(k in text_l for k in keys) or any(k in tag_text for k in keys)

    if has_any(("срочно", "молния", "breaking", "важно", "urgent")):
        code["urgency"] = 0.8
    if has_any(("рынок", "индекс", "акци", "котиров", "s&p", "nasdaq", "dow", "imoex", "ртс")):
        code["market"] = 0.7
    if has_any(("инфляц", "ввп", "gdp", "безработ", "экономик", "макро")):
        code["macro"] = 0.7
    if has_any(("санкц", "переговор", "конфликт", "обострен", "украин", "сша", "китай", "ес", "геополит")):
        code["geopolitics"] = 0.7
    if has_any(("нефт", "газ", "brent", "urals", "золот", "серебр", "металл", "уголь", "руда", "commod")):
        code["commodities"] = 0.7
    if has_any(("валют", "usd", "eur", "юань", "курс", "fx")):
        code["fx"] = 0.7
    if has_any(("цб", "ставк", "ключев", "rates")):
        code["rates"] = 0.8
    if has_any(("btc", "eth", "биткоин", "крипт", "blockchain", "crypto")):
        code["crypto"] = 0.8
        code["market"] = max(code["market"], 0.6)

    if has_any(("вырос", "рост", "прибав", "подорож", "увелич")):
        code["sentiment"] = 0.4
    if has_any(("упал", "сниз", "обвал", "подешев", "просел")):
        code["sentiment"] = -0.4

    ad_hit = has_any(
        (
            "реклам",
            "промокод",
            "скидк",
            "купон",
            "подпис",
            "партнер",
            "спонсор",
            "купить",
            "заказать",
            "акция",
            "розыгрыш",
            "конкурс",
            "регистрац",
            "перейди",
            "ссылка",
        )
    )
    if ad_hit:
        code["ad"] = 0.85

    usefulness = 0.25
    if code["urgency"] >= 0.7:
        usefulness = max(usefulness, 0.6)
    if has_any(("впервые", "рекорд", "аномал", "необыч")):
        usefulness = max(usefulness, 0.6)
    if has_any(("отчет", "результат", "дивиден", "ipo", "ставк", "инфляц")):
        usefulness = max(usefulness, 0.5)
    if has_any(("подкаст", "стрим", "интервью")):
        usefulness = min(usefulness, 0.25)
    if code["ad"] >= 0.7:
        usefulness = min(usefulness, 0.15)
    code["usefulness"] = usefulness

    return code


async def generate_tags(
    session: aiohttp.ClientSession,
    base_url: str,
    model: str,
    text: str,
    max_count: int,
    temperature: float = 0.1,
    system_prompt: str | None = None,
    candidates: list[str] | None = None,
) -> Tuple[list[str], list[str], dict[str, float], dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/api/chat"
    started = time.perf_counter()
    prompt = (
        f"Выдели до {max_count} тегов. Верни только JSON.\n\n{text}"
    )
    if candidates:
        uniq = ", ".join(dict.fromkeys(candidates))
        prompt = (
            f"Возможные кандидаты (используй если релевантно): {uniq}\n\n"
            + prompt
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "options": {"temperature": temperature},
        "stream": False,
    }
    async with session.post(url, json=payload) as resp:
        resp.raise_for_status()
        data = await resp.json()
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        content = data.get("message", {}).get("content", "")
        parsed = _extract_json(content)
        meta = {
            "model": data.get("model", model),
            "prompt_eval_count": data.get("prompt_eval_count"),
            "prompt_eval_duration": data.get("prompt_eval_duration"),
            "eval_count": data.get("eval_count"),
            "eval_duration": data.get("eval_duration"),
            "total_duration": data.get("total_duration"),
            "elapsed_ms": elapsed_ms,
        }
        meta["prompt_tps"] = _tokens_per_second(
            meta.get("prompt_eval_count"),
            meta.get("prompt_eval_duration"),
        )
        meta["eval_tps"] = _tokens_per_second(
            meta.get("eval_count"),
            meta.get("eval_duration"),
        )
        if not parsed:
            code_norm = _normalize_code({})
            fallback_tags = candidates or []
            fallback_code = _fallback_code(fallback_tags, text)
            code_norm = _merge_code(code_norm, fallback_code)
            return fallback_tags, _fallback_emoji(fallback_tags, code_norm, text), code_norm, meta
        tags = parsed.get("tags")
        emoji = parsed.get("emoji")
        code = parsed.get("code")
        emoji_list: list[str] = []
        if isinstance(emoji, list):
            for item in emoji:
                if not isinstance(item, str):
                    continue
                item = item.strip()
                if item in ALLOWED_EMOJI and item not in emoji_list:
                    emoji_list.append(item)
            if len(emoji_list) > MAX_EMOJI:
                emoji_list = emoji_list[:MAX_EMOJI]

        code_norm = _normalize_code(code if isinstance(code, dict) else {})
        if isinstance(tags, list):
            tags_list = [str(t) for t in tags]
        else:
            tags_list = []

        fallback_code = _fallback_code(tags_list, text)
        code_norm = _merge_code(code_norm, fallback_code)
        fallback = _fallback_emoji(tags_list, code_norm, text)
        safe = {"📰", "⚠️", "😡", "😢", "😊", "🎉", "🧠"}
        if emoji_list:
            filtered: list[str] = []
            for item in emoji_list:
                if item in fallback or item in safe:
                    if item not in filtered:
                        filtered.append(item)
            for item in fallback:
                if item not in filtered:
                    filtered.append(item)
            emoji_list = filtered[:MAX_EMOJI]
        else:
            emoji_list = fallback

        return tags_list, emoji_list, code_norm, meta


async def embed_text(
    session: aiohttp.ClientSession,
    base_url: str,
    model: str,
    text: str,
) -> list[float]:
    url = f"{base_url.rstrip('/')}/api/embeddings"
    payload = {
        "model": model,
        "prompt": text,
    }
    async with session.post(url, json=payload) as resp:
        resp.raise_for_status()
        data = await resp.json()
        embedding = data.get("embedding")
        if isinstance(embedding, list):
            return embedding
        return []
