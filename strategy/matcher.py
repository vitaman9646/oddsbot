import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

logger = logging.getLogger("odds_bot.matcher")


# ── Ручные алиасы: гарантированный матчинг ──────────────────
# Ключ = lowercase, значение = каноническое имя
TEAM_ALIASES: dict[str, str] = {
    # NBA
    "boston celtics": "celtics",
    "celtics": "celtics",
    "golden state warriors": "warriors",
    "gs warriors": "warriors",
    "warriors": "warriors",
    "los angeles lakers": "lakers",
    "la lakers": "lakers",
    "lakers": "lakers",
    "milwaukee bucks": "bucks",
    "bucks": "bucks",
    "denver nuggets": "nuggets",
    "nuggets": "nuggets",
    "oklahoma city thunder": "thunder",
    "okc thunder": "thunder",
    "thunder": "thunder",
    "new york knicks": "knicks",
    "ny knicks": "knicks",
    "knicks": "knicks",
    "dallas mavericks": "mavericks",
    "mavs": "mavericks",
    "mavericks": "mavericks",
    "philadelphia 76ers": "76ers",
    "philly 76ers": "76ers",
    "76ers": "76ers",
    "sixers": "76ers",
    "minnesota timberwolves": "timberwolves",
    "timberwolves": "timberwolves",
    "miami heat": "heat",
    "heat": "heat",
    "cleveland cavaliers": "cavaliers",
    "cavs": "cavaliers",
    "cavaliers": "cavaliers",
    "phoenix suns": "suns",
    "suns": "suns",
    "la clippers": "clippers",
    "los angeles clippers": "clippers",
    "clippers": "clippers",
    "indiana pacers": "pacers",
    "pacers": "pacers",
    "sacramento kings": "kings",
    "kings": "kings",
    "memphis grizzlies": "grizzlies",
    "grizzlies": "grizzlies",
    "orlando magic": "magic",
    "magic": "magic",
    "new orleans pelicans": "pelicans",
    "pelicans": "pelicans",
    "houston rockets": "rockets",
    "rockets": "rockets",
    "atlanta hawks": "hawks",
    "hawks": "hawks",

    # NHL
    "florida panthers": "panthers",
    "panthers": "panthers",
    "edmonton oilers": "oilers",
    "oilers": "oilers",
    "dallas stars": "stars",
    "stars": "stars",
    "new york rangers": "rangers",
    "ny rangers": "rangers",
    "rangers": "rangers",
    "carolina hurricanes": "hurricanes",
    "hurricanes": "hurricanes",
    "vancouver canucks": "canucks",
    "canucks": "canucks",
    "colorado avalanche": "avalanche",
    "avalanche": "avalanche",
    "winnipeg jets": "jets",
    "jets": "jets",
    "boston bruins": "bruins",
    "bruins": "bruins",
    "toronto maple leafs": "maple leafs",
    "maple leafs": "maple leafs",
    "tampa bay lightning": "lightning",
    "lightning": "lightning",

    # Premier League / Soccer
    "manchester city": "man city",
    "man city": "man city",
    "man. city": "man city",
    "manchester united": "man united",
    "man united": "man united",
    "man utd": "man united",
    "man. united": "man united",
    "arsenal fc": "arsenal",
    "arsenal": "arsenal",
    "liverpool fc": "liverpool",
    "liverpool": "liverpool",
    "chelsea fc": "chelsea",
    "chelsea": "chelsea",
    "tottenham hotspur": "tottenham",
    "tottenham": "tottenham",
    "spurs": "tottenham",
    "newcastle united": "newcastle",
    "newcastle utd": "newcastle",
    "newcastle": "newcastle",
    "aston villa": "aston villa",
    "west ham united": "west ham",
    "west ham utd": "west ham",
    "west ham": "west ham",
    "brighton and hove albion": "brighton",
    "brighton & hove albion": "brighton",
    "brighton": "brighton",

    # FIFA World Cup — крупные сборные
    "brazil": "brazil",
    "argentina": "argentina",
    "france": "france",
    "england": "england",
    "germany": "germany",
    "spain": "spain",
    "portugal": "portugal",
    "netherlands": "netherlands",
    "holland": "netherlands",
    "belgium": "belgium",
    "italy": "italy",
    "united states": "usa",
    "usa": "usa",
    "us": "usa",
    # Golf
    "joohyung kim": "tom kim",
    "tom kim": "tom kim",
    "si woo kim": "si woo kim",
    "s.w. kim": "si woo kim",
    "matthew fitzpatrick": "matt fitzpatrick",
    "matt fitzpatrick": "matt fitzpatrick",
    "christopher gotterup": "chris gotterup",
    "chris gotterup": "chris gotterup",
    "alexander noren": "alex noren",
    "alex noren": "alex noren",
    "j.j. spaun": "j.j. spaun",
    "j. j. spaun": "j.j. spaun",
    "jj spaun": "j.j. spaun",
    "ludvig aberg": "ludvig aberg",
    "jacob bridgeman": "jake bridgeman",
    "harris english": "harris english",
    "marco penge": "marco penge",
    "matt mccarty": "matt mccarty",
    "ben griffin": "ben griffin",

}


@dataclass
class MatchResult:
    """Результат матчинга команды между источниками"""
    bookmaker_name: str
    polymarket_name: str
    canonical_name: str
    confidence: float      # 0.0 - 1.0
    method: str            # "exact", "alias", "fuzzy", "contains"


def _clean(name: str) -> str:
    """Базовая очистка имени"""
    name = name.lower().strip()
    # Убираем "FC", "SC" и подобное в конце
    name = re.sub(r'\s+(fc|sc|cf|ac)$', '', name)
    # Убираем лишние пробелы
    name = re.sub(r'\s+', ' ', name)
    return name


def _canonicalize(name: str) -> str:
    """Приводим к каноническому виду через алиасы"""
    cleaned = _clean(name)
    return TEAM_ALIASES.get(cleaned, cleaned)


def match_team(
    bookmaker_name: str,
    polymarket_name: str,
    threshold: float = 0.70,
) -> MatchResult | None:
    """
    Пытаемся сматчить имя команды из двух источников.
    Возвращает MatchResult или None если не совпало.
    """
    clean_bk = _clean(bookmaker_name)
    clean_pm = _clean(polymarket_name)

    canon_bk = _canonicalize(bookmaker_name)
    canon_pm = _canonicalize(polymarket_name)

    # Уровень 1: точное совпадение после очистки
    if clean_bk == clean_pm:
        return MatchResult(
            bookmaker_name=bookmaker_name,
            polymarket_name=polymarket_name,
            canonical_name=canon_bk,
            confidence=1.0,
            method="exact",
        )

    # Уровень 2: совпадение через алиасы
    if canon_bk == canon_pm:
        return MatchResult(
            bookmaker_name=bookmaker_name,
            polymarket_name=polymarket_name,
            canonical_name=canon_bk,
            confidence=0.95,
            method="alias",
        )

    # Уровень 3: один содержит другого
    if canon_bk in canon_pm or canon_pm in canon_bk:
        return MatchResult(
            bookmaker_name=bookmaker_name,
            polymarket_name=polymarket_name,
            canonical_name=canon_bk,
            confidence=0.85,
            method="contains",
        )

    # Уровень 4: fuzzy matching
    ratio = SequenceMatcher(None, canon_bk, canon_pm).ratio()
    if ratio >= threshold:
        return MatchResult(
            bookmaker_name=bookmaker_name,
            polymarket_name=polymarket_name,
            canonical_name=canon_bk,
            confidence=ratio,
            method="fuzzy",
        )

    return None


def match_teams_bulk(
    bookmaker_teams: list[str],
    polymarket_teams: list[str],
    threshold: float = 0.70,
) -> dict[str, MatchResult]:
    """
    Матчим списки команд из двух источников.
    Возвращает dict: bookmaker_name -> MatchResult

    Жадный алгоритм: лучшие совпадения первыми,
    каждая команда PM используется максимум один раз.
    """
    candidates: list[tuple[float, str, str, MatchResult]] = []

    for bk_name in bookmaker_teams:
        for pm_name in polymarket_teams:
            result = match_team(bk_name, pm_name, threshold)
            if result:
                candidates.append((
                    result.confidence,
                    bk_name,
                    pm_name,
                    result,
                ))

    # Сортируем по confidence (лучшие первыми)
    candidates.sort(key=lambda x: x[0], reverse=True)

    matched: dict[str, MatchResult] = {}
    used_pm: set[str] = set()

    for confidence, bk_name, pm_name, result in candidates:
        if bk_name in matched:
            continue
        if pm_name in used_pm:
            continue

        matched[bk_name] = result
        used_pm.add(pm_name)

    # Логируем результаты
    total_bk = len(bookmaker_teams)
    total_matched = len(matched)
    unmatched = [
        n for n in bookmaker_teams if n not in matched
    ]

    logger.info(
        f"Matched {total_matched}/{total_bk} teams"
    )
    if unmatched:
        logger.warning(
            f"Unmatched bookmaker teams: {unmatched[:10]}"
        )

    # Предупреждаем о fuzzy-матчах (могут быть ошибочными)
    fuzzy_matches = [
        r for r in matched.values() if r.method == "fuzzy"
    ]
    if fuzzy_matches:
        for fm in fuzzy_matches:
            logger.warning(
                f"Fuzzy match: '{fm.bookmaker_name}' ↔ "
                f"'{fm.polymarket_name}' "
                f"(confidence: {fm.confidence:.2f}) — "
                f"VERIFY MANUALLY"
            )

    return matched


# ── Утилита для быстрого добавления алиасов ──────────────────

def add_alias(name: str, canonical: str) -> None:
    """Добавляем алиас в рантайме (не персистится)"""
    TEAM_ALIASES[_clean(name)] = _clean(canonical)
    logger.info(f"Added alias: '{name}' -> '{canonical}'")


def get_unmatched_report(
    bookmaker_teams: list[str],
    polymarket_teams: list[str],
    matched: dict[str, MatchResult],
) -> str:
    """Формируем отчёт о несовпавших для ручного маппинга"""
    unmatched_bk = [
        t for t in bookmaker_teams if t not in matched
    ]
    unmatched_pm = [
        t for t in polymarket_teams
        if t not in {m.polymarket_name for m in matched.values()}
    ]

    lines = ["=" * 50, "UNMATCHED TEAMS REPORT", "=" * 50]

    if unmatched_bk:
        lines.append(f"\nBookmaker ({len(unmatched_bk)}):")
        for t in sorted(unmatched_bk):
            lines.append(f"  • {t}")

    if unmatched_pm:
        lines.append(f"\nPolymarket ({len(unmatched_pm)}):")
        for t in sorted(unmatched_pm):
            lines.append(f"  • {t}")

    if not unmatched_bk and not unmatched_pm:
        lines.append("\n✅ All teams matched!")

    return "\n".join(lines)
