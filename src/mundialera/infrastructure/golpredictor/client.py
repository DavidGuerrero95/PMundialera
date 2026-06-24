from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from mundialera.domain.models import Match, PredictionFormRef, Scoreline, SubmissionResult, Team
from mundialera.domain.ports import FixtureRepository, PredictionSink

HIDDEN_FIELDS = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")
LOGIN_USER_FIELD = "Header1$UserInfo1$LoginView1$login1$UserName"
LOGIN_PASSWORD_FIELD = "Header1$UserInfo1$LoginView1$login1$Password"  # noqa: S105
LOGIN_BUTTON_FIELD = "Header1$UserInfo1$LoginView1$login1$LoginButton"
SCORE_RE = re.compile(r"(?P<home>\d+)\s*-\s*(?P<away>\d+)")
DATE_RE = re.compile(
    r"(?P<day>\d{1,2})\s+"
    r"(?P<month>[A-Za-zÁÉÍÓÚáéíóú]+)\s*-\s*"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})"
)
POSTBACK_RE = re.compile(r"__doPostBack\('(?P<target>[^']*)','(?P<argument>[^']*)'\)")

MONTHS_ES = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}


@dataclass(frozen=True, slots=True)
class GolPredictorCredentials:
    username: str
    password: str


class GolPredictorClient(FixtureRepository, PredictionSink):
    def __init__(
        self,
        *,
        base_url: str,
        credentials: GolPredictorCredentials,
        timezone_name: str,
        tournament_year: int = 2026,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._credentials = credentials
        self._timezone = ZoneInfo(timezone_name)
        self._year = tournament_year
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "PMundialera/0.1 (+local operator)"},
        )
        self._logged_in = False
        self._page_cache: dict[tuple[str, str], str] = {}

    def close(self) -> None:
        self._client.close()

    def login(self) -> bool:
        page = self._get("home.aspx")
        form = self._extract_form_fields(page.text)
        form.update(
            {
                LOGIN_USER_FIELD: self._credentials.username,
                LOGIN_PASSWORD_FIELD: self._credentials.password,
                f"{LOGIN_BUTTON_FIELD}.x": "10",
                f"{LOGIN_BUTTON_FIELD}.y": "10",
            }
        )
        response = self._post("home.aspx", data=form)
        self._logged_in = not self._page_contains_login(response.text)
        return self._logged_in

    def list_groups(self) -> list[str]:
        self._ensure_login()
        response = self._get("myaccount.aspx")
        return sorted(_parse_account_groups(response.text).keys())

    def list_matches(self, group_name: str) -> list[Match]:
        self._ensure_login()
        pages = self._open_prediction_pages(group_name)
        matches: list[Match] = []
        seen: set[str] = set()
        for page in pages:
            parsed = parse_matches(page, group_name=group_name, timezone_name=str(self._timezone))
            for match in parsed:
                if match.match_id in seen:
                    continue
                seen.add(match.match_id)
                self._page_cache[(group_name, match.match_id)] = page
                matches.append(match)
        return matches

    def submit_prediction(
        self,
        match: Match,
        scoreline: Scoreline,
        *,
        dry_run: bool,
    ) -> SubmissionResult:
        self._ensure_login()
        if dry_run:
            return SubmissionResult(
                match=match,
                scoreline=scoreline,
                submitted=False,
                dry_run=True,
                message=f"Dry-run: would submit {scoreline.label()} for {match.label}",
            )

        cached_page = self._page_cache.get((match.group or "", match.match_id))
        if cached_page is None and match.group:
            for candidate in self.list_matches(match.group):
                if candidate.match_id == match.match_id:
                    match = candidate
                    cached_page = self._page_cache.get((match.group or "", match.match_id))
                    break

        form_ref = match.prediction_form
        if cached_page is None or form_ref is None:
            return SubmissionResult(
                match=match,
                scoreline=scoreline,
                submitted=False,
                dry_run=False,
                message="Prediction form fields unavailable; cannot submit safely",
            )

        form = self._extract_form_fields(cached_page)
        form[form_ref.home_field] = str(scoreline.home)
        form[form_ref.away_field] = str(scoreline.away)
        if form_ref.submit_field:
            form[f"{form_ref.submit_field}.x"] = "10"
            form[f"{form_ref.submit_field}.y"] = "10"
        response = self._client.post(form_ref.form_action, data=form)
        response.raise_for_status()
        if match.group:
            self._refresh_page_cache(match.group, response.text)
        return SubmissionResult(
            match=match,
            scoreline=scoreline,
            submitted=True,
            dry_run=False,
            message=f"Submitted {scoreline.label()} for {match.label}",
        )

    def _ensure_login(self) -> None:
        if not self._logged_in and not self.login():
            msg = "GolPredictor login failed"
            raise RuntimeError(msg)

    def _open_prediction_pages(self, group_name: str) -> list[str]:
        account = self._get("myaccount.aspx")
        groups = _parse_account_groups(account.text)
        target = groups.get(group_name)
        if target is None:
            return []

        first = self._postback(account.text, str(account.url), target, "")
        pages = [first]
        for page_target, page_argument in _parse_match_grid_page_postbacks(first):
            pages.append(
                self._postback(
                    first,
                    _form_action(first, str(account.url)),
                    page_target,
                    page_argument,
                )
            )
        return pages

    def _postback(self, html: str, page_url: str, target: str, argument: str) -> str:
        form = self._extract_form_fields(html)
        form["__EVENTTARGET"] = target
        form["__EVENTARGUMENT"] = argument
        response = self._post(_form_action(html, page_url), data=form)
        return response.text

    def _refresh_page_cache(self, group_name: str, html: str) -> None:
        for match in parse_matches(html, group_name=group_name, timezone_name=str(self._timezone)):
            self._page_cache[(group_name, match.match_id)] = html

    @retry(
        retry=retry_if_exception_type(httpx.HTTPStatusError),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _get(self, url: str) -> httpx.Response:
        response = self._client.get(url)
        response.raise_for_status()
        return response

    @retry(
        retry=retry_if_exception_type(httpx.HTTPStatusError),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _post(self, url: str, *, data: dict[str, str]) -> httpx.Response:
        response = self._client.post(url, data=data)
        response.raise_for_status()
        return response

    @staticmethod
    def _extract_form_fields(html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        fields: dict[str, str] = {}
        for item in soup.find_all("input"):
            if not isinstance(item, Tag):
                continue
            name = item.get("name")
            if not name:
                continue
            input_type = str(item.get("type", "")).lower()
            if input_type in {"hidden", "text", "password"}:
                fields[str(name)] = str(item.get("value", ""))
        for field in HIDDEN_FIELDS:
            value = soup.find("input", {"name": field})
            if isinstance(value, Tag):
                fields[field] = str(value.get("value", ""))
        return fields

    @staticmethod
    def _page_contains_login(html: str) -> bool:
        return LOGIN_USER_FIELD in html and LOGIN_PASSWORD_FIELD in html


def parse_matches(html: str, *, group_name: str | None, timezone_name: str) -> list[Match]:
    soup = BeautifulSoup(html, "html.parser")
    action = _form_action(html, "")
    submit_field = _submit_field(html)
    matches: list[Match] = []
    for row in soup.find_all("tr"):
        if not isinstance(row, Tag):
            continue
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        teams = _parse_teams(cells[2])
        if teams is None:
            continue
        detail_url = _extract_detail_url(row)
        form_ref = _prediction_form_ref(row, action, submit_field)
        matches.append(
            Match(
                match_id=cells[0],
                kickoff=_parse_kickoff(cells[1], timezone_name=timezone_name),
                home=Team(teams[0]),
                away=Team(teams[1]),
                group=group_name,
                prediction=_parse_score(cells[3]),
                result=_parse_score(cells[4]),
                points=int(cells[5]) if cells[5].isdigit() else None,
                detail_url=detail_url,
                prediction_form=form_ref,
            )
        )
    return matches


def _parse_teams(value: str) -> tuple[str, str] | None:
    if " - " not in value:
        return None
    home, away = value.split(" - ", 1)
    home = home.strip()
    away = away.strip()
    if not home or not away:
        return None
    return home, away


def _parse_score(value: str) -> Scoreline | None:
    match = SCORE_RE.search(value)
    if not match:
        return None
    return Scoreline(home=int(match.group("home")), away=int(match.group("away")))


def _parse_kickoff(value: str, *, timezone_name: str) -> datetime | None:
    match = DATE_RE.search(value)
    if not match:
        return None
    month_key = match.group("month").lower()[:3]
    month = MONTHS_ES.get(month_key)
    if month is None:
        return None
    return datetime(
        2026,
        month,
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        tzinfo=ZoneInfo(timezone_name),
    )


def _extract_detail_url(row: Tag) -> str | None:
    anchor = row.find("a")
    if not isinstance(anchor, Tag):
        return None
    return _attr_to_str(anchor.get("href"))


def _prediction_form_ref(
    row: Tag,
    action: str,
    submit_field: str | None,
) -> PredictionFormRef | None:
    inputs = [
        item
        for item in row.find_all("input")
        if isinstance(item, Tag) and _attr_to_str(item.get("name"))
    ]
    home_field = next(
        (
            _attr_to_str(item.get("name"))
            for item in inputs
            if "txtGolLocal" in str(item.get("name"))
        ),
        None,
    )
    away_field = next(
        (
            _attr_to_str(item.get("name"))
            for item in inputs
            if "txtGolVisitante" in str(item.get("name"))
        ),
        None,
    )
    if not home_field or not away_field:
        return None
    return PredictionFormRef(
        form_action=action,
        home_field=home_field,
        away_field=away_field,
        submit_field=submit_field,
    )


def _attr_to_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return " ".join(str(item) for item in value) if isinstance(value, list) else str(value)


def _submit_field(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for item in soup.find_all("input"):
        if not isinstance(item, Tag):
            continue
        name = _attr_to_str(item.get("name"))
        src = _attr_to_str(item.get("src")) or ""
        value = _attr_to_str(item.get("value")) or ""
        if name and (
            "guardar" in src.casefold()
            or "guardar" in value.casefold()
            or name.endswith("$butGuardar")
        ):
            return name
    return None


def _form_action(html: str, fallback_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if not isinstance(form, Tag):
        return fallback_url
    action = _attr_to_str(form.get("action"))
    if not action:
        return fallback_url
    return urljoin(fallback_url or "https://www.golpredictor.com/", action)


def _parse_postback(href: str | None) -> tuple[str, str] | None:
    if not href:
        return None
    match = POSTBACK_RE.search(href)
    if not match:
        return None
    return match.group("target"), match.group("argument")


def _parse_account_groups(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    groups: dict[str, str] = {}
    for row in soup.find_all("tr"):
        if not isinstance(row, Tag):
            continue
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        if len(cells) < 2 or "Copa Mundo" not in cells[1]:
            continue
        group_name = cells[0]
        for anchor in row.find_all("a"):
            if not isinstance(anchor, Tag):
                continue
            href = _attr_to_str(anchor.get("href"))
            postback = _parse_postback(href)
            if postback and "lnkUrlPronostico" in postback[0]:
                groups[group_name] = postback[0]
                break
    return groups


def _parse_match_grid_page_postbacks(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    postbacks: list[tuple[str, str]] = []
    for anchor in soup.find_all("a"):
        if not isinstance(anchor, Tag):
            continue
        text = anchor.get_text(" ", strip=True)
        href = _attr_to_str(anchor.get("href"))
        postback = _parse_postback(href)
        if (
            text.isdigit()
            and postback
            and postback[0].endswith("$gvPartidos")
            and postback[1].startswith("Page$")
        ):
            postbacks.append(postback)
    return postbacks


def _guess_score_fields(html: str) -> tuple[str, str, str | None] | None:
    soup = BeautifulSoup(html, "html.parser")
    text_inputs = [
        str(item.get("name"))
        for item in soup.find_all("input")
        if isinstance(item, Tag)
        and item.get("name")
        and str(item.get("type", "text")).lower() in {"text", "number"}
    ]
    score_like = [
        name
        for name in text_inputs
        if any(token in name.lower() for token in ("local", "visit", "home", "away", "gol"))
    ]
    if len(score_like) < 2:
        return None

    submit_name: str | None = None
    for item in soup.find_all("input"):
        if not isinstance(item, Tag):
            continue
        name = item.get("name")
        value = str(item.get("value", "")).lower()
        if name and any(token in value for token in ("guardar", "salvar", "actualizar")):
            submit_name = str(name)
            break
    return score_like[0], score_like[1], submit_name
