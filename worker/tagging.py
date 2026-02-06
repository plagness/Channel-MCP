from __future__ import annotations

import json
import re
from typing import Iterable

DEFAULT_ALIASES = {
    "цб": "ЦБ",
    "центральный банк": "ЦБ",
    "central bank": "ЦБ",
    "central bank of russia": "ЦБ",
    "бпла": "БПЛА",
    "аси": "АСИ",
    "рф": "РФ",
    "урале": "Урал",
    "t-technologies": "Т-Технологии",
    "t‑technologies": "Т-Технологии",
    "alfa investments": "Альфа-Инвестиции",
    "alfa-investments": "Альфа-Инвестиции",
    "alpha investments": "Альфа-Инвестиции",
    "alpha-investments": "Альфа-Инвестиции",
    "alfa investment": "Альфа-Инвестиции",
    "alpha investment": "Альфа-Инвестиции",
    "альфа инвестиции": "Альфа-Инвестиции",
    "альфаиндекс": "Альфа-Индекс",
    "альфа индекс": "Альфа-Индекс",
    "дом.рф": "ДОМ.РФ",
    "valutnye": "Валютные",
    "valyutnye": "Валютные",
    "что купить": "Что Купить",
    "чтокупить": "Что Купить",
    "сельгдар": "Селигдар",
    "аэрофлота": "Аэрофлот",
    "сербанк": "Сбербанк",
    "соединенные штаты": "США",
    "соединённые штаты": "США",
    "сша": "США",
    "рынк": "Рынок",
    "рынки": "Рынок",
    "цены": "Цены",
    "дефисит": "Дефицит",
    "geopolitica": "Геополитика",
    "мосбиржи": "Мосбиржа",
    "озона": "Озон",
    "совкомбанка": "Совкомбанк",
    "полюса": "Полюс",
    "дзень": "Дзен",
    "драгметалы": "Драгметаллы",
    "банк россии": "ЦБ",
    "икс 5": "ИКС 5",
    "глоракс": "Глоракс",
    "мд медикал груп": "МД Медикал Груп",
    "ипо": "IPO",
    "ipo": "IPO",
    "татнефти": "Татнефть",
    "ростелекома": "Ростелеком",
    "пика": "ПИК",
    "банка санкт-петербург": "Банк Санкт-Петербург",
    "эн+ груп": "ЭН+ Груп",
    "минцифра": "Минцифры",
    "keystavka": "Ключевая Ставка",
}

_STOP_TAGS = {
    "сфера",
    "сектор",
    "услуги",
    "покупки",
    "продукции",
    "активность",
    "крупные",
    "крупный",
    "крупная",
    "крупного",
    "крупной",
    "крупным",
    "частный",
    "частная",
    "частные",
    "частного",
    "частной",
    "частным",
    "деловая",
    "деловой",
    "деловые",
    "делового",
    "экономическая",
    "экономический",
    "экономические",
    "экономической",
    "экономического",
    "потребительская",
    "продовольственная",
    "логистические",
    "транспортные",
    "туристическая",
    "общественный",
    "общественная",
    "общественные",
    "будний день",
    "на",
    "в",
    "по",
    "к",
    "из",
    "за",
    "для",
    "о",
    "об",
    "обо",
    "у",
    "от",
    "до",
    "при",
    "про",
    "под",
    "над",
    "между",
    "без",
    "live",
    "stream",
    "started",
    "рост",
}

_GENERIC_TAGS = {
    "рынок",
    "продукция",
    "погода",
    "интернет",
    "сад",
    "ремонт",
    "аккаунты",
    "поездки",
    "новости",
    "экспресс",
    "подкаст",
    "компания",
    "компании",
    "граждане",
    "бизнес",
    "операции",
    "платежи",
    "бюджет",
    "цена",
    "стрим",
    "старт",
    "вывод",
}

_ADJ_ENDINGS = (
    "ая",
    "яя",
    "ое",
    "ее",
    "ый",
    "ий",
    "ые",
    "ие",
    "ой",
    "ого",
    "его",
    "ему",
    "ими",
    "ыми",
    "ым",
    "ую",
)

_VERB_ENDINGS = (
    "лся",
    "лась",
    "лись",
    "лось",
    "ли",
    "ло",
    "ла",
)

_ADJ_KEEP = {
    "первичный",
    "вторичный",
    "валютные",
    "валютный",
}

_DROP_PREFIXES = (
    "Рост",
    "Снижение",
    "Падение",
    "Увеличение",
    "Сокращение",
    "Уменьшение",
    "Повышение",
)

try:  # Optional heavy dependency (Py3.11+)
    import pymorphy3 as _pymorphy  # type: ignore
except Exception:  # pragma: no cover - optional
    try:
        import pymorphy2 as _pymorphy  # type: ignore
    except Exception:
        _pymorphy = None

_MORPH = None


def _get_morph():
    global _MORPH
    if _MORPH is None and _pymorphy is not None:
        _MORPH = _pymorphy.MorphAnalyzer()
    return _MORPH


_SERVICE_PATTERNS = [
    r"^live stream started$",
    r"стрим начался",
    r"прямая трансляция",
    r"эфир начался",
    r"подключайтесь к трансляции",
    r"прямой эфир",
]


def is_service_post(text: str) -> bool:
    if not text:
        return False
    cleaned = re.sub(r"\s+", " ", text).strip().lower()
    if len(cleaned) <= 32:
        for pattern in _SERVICE_PATTERNS:
            if re.search(pattern, cleaned):
                return True
    return False

_CYR_TO_LAT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sh",
        "ы": "y",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


def _fold_key(text: str) -> str:
    lowered = text.lower()
    return lowered.translate(_CYR_TO_LAT)


def build_alias_map(raw_json: str | None) -> dict[str, str]:
    aliases: dict[str, str] = {}

    def add(alias: str, canonical: str) -> None:
        alias = alias.strip()
        canonical = canonical.strip()
        if not alias or not canonical:
            return
        aliases[alias.lower()] = canonical
        aliases[_fold_key(alias)] = canonical

    for alias, canonical in DEFAULT_ALIASES.items():
        add(alias, canonical)

    if raw_json:
        try:
            data = json.loads(raw_json)
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, list):
                        for item in value:
                            if not isinstance(item, str):
                                continue
                            add(item, str(key))
                    elif isinstance(value, str):
                        add(str(key), value)
            elif isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    alias = str(item.get("alias", "")).strip()
                    canonical = str(item.get("canonical", "")).strip()
                    if alias and canonical:
                        add(alias, canonical)
        except json.JSONDecodeError:
            pass

    return aliases


def _title_case(text: str) -> str:
    parts = []
    for token in text.split(" "):
        if not token:
            continue
        if token.isupper():
            parts.append(token)
            continue
        subtokens = []
        for sub in token.split("-"):
            if not sub:
                continue
            if sub.isupper():
                subtokens.append(sub)
            else:
                subtokens.append(sub[:1].upper() + sub[1:])
        parts.append("-".join(subtokens))
    return " ".join(parts)


def _is_single_word(tag: str) -> bool:
    return " " not in tag and "-" not in tag


def _is_stop_tag(tag: str) -> bool:
    lowered = tag.lower()
    if lowered in _STOP_TAGS:
        return True
    if not _is_single_word(tag):
        return False
    if lowered in _ADJ_KEEP:
        return False
    if lowered.endswith("ся"):
        return True
    if any(lowered.endswith(end) for end in _VERB_ENDINGS):
        return True
    if any(lowered.endswith(end) for end in _ADJ_ENDINGS):
        return True
    return False


def normalize_tag(raw: str, alias_map: dict[str, str]) -> str | None:
    tag = raw.strip()
    if not tag:
        return None

    if len(tag) <= 2 and not tag.isupper():
        return None

    if tag.startswith("#"):
        tag = tag[1:].strip()

    if not tag:
        return None

    tag = tag.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    tag = tag.strip(" \t\r\n\"'`()[]{}<>")
    tag = re.sub(r"\s+", " ", tag)

    lowered = tag.lower()
    for prefix in _DROP_PREFIXES:
        prefix_l = prefix.lower() + " "
        if lowered.startswith(prefix_l):
            tag = tag[len(prefix) + 1 :].strip()
            if not tag:
                return None
            tag = _title_case(tag)
            lowered = tag.lower()
            break
    if not re.fullmatch(r"[A-Za-zА-Яа-я0-9 ./&()+-]+", tag):
        return None

    alias_key = tag.lower()
    if alias_key in alias_map:
        return alias_map[alias_key]

    folded = _fold_key(tag)
    if folded in alias_map:
        return alias_map[folded]

    if re.search(r"\d", tag):
        if re.fullmatch(r"[A-ZА-Я0-9./&-]+", tag):
            pass
        elif re.fullmatch(r"[A-ZА-Я]{2,}\\s?[0-9]+", tag):
            pass
        else:
            return None

    if re.fullmatch(r"[0-9]+([.,][0-9]+)?", tag):
        return None

    if re.search(r"[A-Za-z]", tag):
        if re.fullmatch(r"[A-Z0-9./&-]+", tag):
            return tag
        return None

    if re.fullmatch(r"[A-Z0-9./&-]+", tag) or re.fullmatch(r"[А-Я0-9./&-]+", tag):
        return tag

    morph = _get_morph()
    if morph and _is_single_word(tag):
        if tag[:1].isupper() and tag[1:].islower():
            parsed = morph.parse(tag.lower())
            if parsed:
                lemma = parsed[0].normal_form
                if lemma and lemma != tag.lower():
                    tag = _title_case(lemma)

    if _is_stop_tag(tag):
        return None

    return _title_case(tag)


def normalize_tags(raw_tags: Iterable[str], alias_map: dict[str, str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in raw_tags:
        if not raw:
            continue
        tag = normalize_tag(str(raw), alias_map)
        if not tag:
            continue
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return _filter_generic(_merge_compounds(result))


def _merge_compounds(tags: list[str]) -> list[str]:
    merges = [
        ("Валютные", "Бумаги", "Валютные Бумаги"),
        ("Первичный", "Рынок", "Первичный Рынок"),
        ("Вторичный", "Рынок", "Вторичный Рынок"),
    ]
    tag_set = set(tags)
    for left, right, combined in merges:
        if left in tag_set and right in tag_set:
            tag_set.discard(left)
            tag_set.discard(right)
            tag_set.add(combined)

    merged: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if tag in tag_set and tag not in seen:
            merged.append(tag)
            seen.add(tag)
    for _, _, combined in merges:
        if combined in tag_set and combined not in seen:
            merged.append(combined)
            seen.add(combined)
    return merged


def _filter_generic(tags: list[str]) -> list[str]:
    if len(tags) <= 6:
        return tags
    filtered = [tag for tag in tags if tag.lower() not in _GENERIC_TAGS]
    if len(filtered) >= 3:
        return filtered
    return tags


def extract_candidates(text: str) -> list[str]:
    if not text:
        return []
    candidates: list[str] = []

    for match in re.findall(r"#([\w\-]+)", text, flags=re.UNICODE):
        if match:
            candidates.append(match)

    for match in re.findall(r"\b[A-Z]{2,5}/[A-Z]{2,5}\b", text):
        candidates.append(match)

    for match in re.findall(r"\b[A-Z0-9]{3,}\b", text):
        candidates.append(match)

    return candidates


def prepare_text_for_tagging(text: str, max_chars: int) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\\s+", " ", text).strip()
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned
    head = int(max_chars * 0.7)
    tail = max_chars - head
    return cleaned[:head] + " ... " + cleaned[-tail:]
