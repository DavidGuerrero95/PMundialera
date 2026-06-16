from __future__ import annotations

import json
import time
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from mundialera.application.clock import SystemClock
from mundialera.application.scheduler import plan_next_wake
from mundialera.domain.models import Match, Prediction, Team
from mundialera.interfaces.factory import (
    build_feedback_service,
    build_golpredictor_client,
    build_orchestrator,
    build_prediction_model,
    build_prediction_store,
    build_research_agent,
)
from mundialera.settings import get_settings

app = typer.Typer(no_args_is_help=True)
golpredictor_app = typer.Typer(no_args_is_help=True)
run_app = typer.Typer(no_args_is_help=True)
feedback_app = typer.Typer(no_args_is_help=True)
app.add_typer(golpredictor_app, name="golpredictor")
app.add_typer(run_app, name="run")
app.add_typer(feedback_app, name="feedback")
console = Console()


@golpredictor_app.command("login-check")
def login_check() -> None:
    client = build_golpredictor_client()
    try:
        ok = client.login()
    finally:
        client.close()
    if not ok:
        raise typer.Exit(code=1)
    console.print("[green]GolPredictor login OK[/green]")


@golpredictor_app.command("groups")
def groups() -> None:
    client = build_golpredictor_client()
    try:
        for group in client.list_groups():
            console.print(group)
    finally:
        client.close()


@golpredictor_app.command("fixtures")
def fixtures(group: Annotated[str, typer.Argument(help="GolPredictor group name")]) -> None:
    client = build_golpredictor_client()
    try:
        matches = client.list_matches(group)
    finally:
        client.close()
    table = Table("Id", "Kickoff", "Match", "Prediction", "Result", "Points")
    for match in matches:
        table.add_row(
            match.match_id,
            match.kickoff.isoformat() if match.kickoff else "-",
            match.label,
            match.prediction.label() if match.prediction else "-",
            match.result.label() if match.result else "-",
            str(match.points) if match.points is not None else "-",
        )
    console.print(table)


@golpredictor_app.command("inspect")
def inspect_group(group: Annotated[str, typer.Argument(help="GolPredictor group name")]) -> None:
    client = build_golpredictor_client()
    try:
        matches = client.list_matches(group)
    finally:
        client.close()
    editable = sum(1 for match in matches if match.prediction_form is not None)
    console.print(f"Group: {group}")
    console.print(f"Matches scraped: {len(matches)}")
    console.print(f"Editable prediction rows: {editable}")
    table = Table("Id", "Match", "Kickoff", "Can submit", "Fields")
    for match in matches[:12]:
        fields = "-"
        if match.prediction_form is not None:
            fields = f"{match.prediction_form.home_field} / {match.prediction_form.away_field}"
        table.add_row(
            match.match_id,
            match.label,
            match.kickoff.isoformat() if match.kickoff else "-",
            "yes" if match.prediction_form is not None else "no",
            fields,
        )
    console.print(table)


@app.command("predict")
def predict(
    home: Annotated[str, typer.Option(help="Home team")],
    away: Annotated[str, typer.Option(help="Away team")],
) -> None:
    settings = get_settings()
    match = Match(match_id="manual", kickoff=None, home=Team(home), away=Team(away))
    brief = build_research_agent(settings).research(match)
    prediction = build_prediction_model(settings).predict(brief)
    console.print_json(
        data={
            "match": match.label,
            "primary": prediction.primary.label(),
            "hedge": prediction.hedge.label(),
            "confidence": prediction.confidence,
            "rationale": prediction.rationale,
        }
    )


@run_app.command("window")
def run_window(
    group: Annotated[str, typer.Option(help="GolPredictor group name")],
    dry_run: Annotated[bool, typer.Option(help="Preview without submitting")] = True,
    submit: Annotated[bool, typer.Option(help="Submit predictions when inside window")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON result")] = False,
) -> None:
    settings = get_settings()
    effective_dry_run = dry_run and not submit
    orchestrator = build_orchestrator(settings)
    result = orchestrator.run_group_window(group, dry_run=effective_dry_run)
    if json_output:
        console.print(
            json.dumps(
                {
                    "group": result.group_name,
                    "evaluated": [
                        {
                            "match": item.match.label,
                            "primary": item.primary.label(),
                            "hedge": item.hedge.label(),
                            "confidence": item.confidence,
                            "rationale": item.rationale,
                        }
                        for item in result.evaluated
                    ],
                    "submitted": [
                        {
                            "match": item.match.label,
                            "scoreline": item.scoreline.label(),
                            "submitted": item.submitted,
                            "dry_run": item.dry_run,
                            "message": item.message,
                        }
                        for item in result.submitted
                    ],
                    "skipped": result.skipped,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    console.print(f"Group: {result.group_name}")
    for submission in result.submitted:
        color = "yellow" if submission.dry_run else "green"
        console.print(f"[{color}]{submission.message}[/{color}]")
    for skipped in result.skipped:
        console.print(f"[dim]{skipped}[/dim]")


@run_app.command("once")
def run_once(
    dry_run: Annotated[bool, typer.Option(help="Preview without submitting")] = True,
    submit: Annotated[bool, typer.Option(help="Submit predictions when inside window")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON result")] = False,
) -> None:
    settings = get_settings()
    effective_dry_run = dry_run and not submit
    orchestrator = build_orchestrator(settings)
    results = [
        orchestrator.run_group_window(group, dry_run=effective_dry_run)
        for group in settings.configured_groups()
    ]
    payload = [
        {
            "group": result.group_name,
            "evaluated": [_prediction_to_dict(item) for item in result.evaluated],
            "submitted": [
                {
                    "match": item.match.label,
                    "scoreline": item.scoreline.label(),
                    "submitted": item.submitted,
                    "dry_run": item.dry_run,
                    "message": item.message,
                }
                for item in result.submitted
            ],
            "skipped": result.skipped,
        }
        for result in results
    ]
    if json_output:
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for result in results:
        console.print(f"Group: {result.group_name}")
        for submission in result.submitted:
            color = "yellow" if submission.dry_run else "green"
            console.print(f"[{color}]{submission.message}[/{color}]")
        console.print(f"[dim]Skipped: {len(result.skipped)}[/dim]")


@run_app.command("next")
def run_next(
    limit: Annotated[int, typer.Option(help="Upcoming matches per group")] = 2,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON result")] = False,
) -> None:
    settings = get_settings()
    orchestrator = build_orchestrator(settings)
    payload = {
        group: [
            _prediction_to_dict(prediction)
            for prediction in orchestrator.preview_upcoming(group, limit=limit)
        ]
        for group in settings.configured_groups()
    }
    if json_output:
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for group, predictions in payload.items():
        console.print(f"Group: {group}")
        for prediction in predictions:
            console.print(
                f"{prediction['match']}: {prediction['primary']} "
                f"(hedge {prediction['hedge']}, conf {prediction['confidence']})"
            )


@run_app.command("watch")
def run_watch(
    interval_seconds: Annotated[int, typer.Option(help="Seconds between cycles")] = 60,
    iterations: Annotated[int | None, typer.Option(help="Stop after N cycles")] = None,
    dry_run: Annotated[bool, typer.Option(help="Preview without submitting")] = True,
    submit: Annotated[bool, typer.Option(help="Submit predictions when inside window")] = False,
) -> None:
    cycle = 0
    while iterations is None or cycle < iterations:
        cycle += 1
        console.rule(f"PMundialera cycle {cycle}")
        try:
            run_once(dry_run=dry_run, submit=submit, json_output=False)
            feedback_settle(json_output=False)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Cycle failed: {exc.__class__.__name__}: {exc}[/red]")
        if iterations is not None and cycle >= iterations:
            break
        time.sleep(interval_seconds)


@run_app.command("schedule")
def run_schedule(
    idle_poll_seconds: Annotated[
        int,
        typer.Option(help="Maximum seconds to sleep when no match window is near"),
    ] = 21600,
    active_poll_seconds: Annotated[
        int,
        typer.Option(help="Seconds between cycles while inside or near a window"),
    ] = 60,
    pre_window_buffer_seconds: Annotated[
        int,
        typer.Option(help="Wake this many seconds before the submission window opens"),
    ] = 300,
) -> None:
    settings = get_settings()
    client = build_golpredictor_client(settings)
    try:
        matches = [
            match
            for group in settings.configured_groups()
            for match in client.list_matches(group)
        ]
    finally:
        client.close()
    decision = plan_next_wake(
        matches,
        now=SystemClock(settings.pmundialera_timezone).now(),
        submission_window_minutes=settings.pmundialera_submission_window_minutes,
        idle_poll_seconds=idle_poll_seconds,
        active_poll_seconds=active_poll_seconds,
        pre_window_buffer_seconds=pre_window_buffer_seconds,
    )
    next_match = decision.next_match
    console.print(
        json.dumps(
            {
                "now": decision.now.isoformat(),
                "in_window": decision.in_window,
                "sleep_seconds": decision.sleep_seconds,
                "reason": decision.reason,
                "next_match": None
                if next_match is None
                else {
                    "match_id": next_match.match_id,
                    "match": next_match.label,
                    "kickoff": next_match.kickoff.isoformat()
                    if next_match.kickoff is not None
                    else None,
                    "group": next_match.group,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _prediction_to_dict(prediction: Prediction) -> dict[str, object]:
    return {
        "match_id": prediction.match.match_id,
        "match": prediction.match.label,
        "kickoff": prediction.match.kickoff.isoformat() if prediction.match.kickoff else None,
        "primary": prediction.primary.label(),
        "hedge": prediction.hedge.label(),
        "confidence": prediction.confidence,
        "rationale": prediction.rationale,
    }


@feedback_app.command("settle")
def feedback_settle(
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON result")] = False,
) -> None:
    settings = get_settings()
    service = build_feedback_service(settings)
    try:
        count = service.settle_groups(settings.configured_groups())
    finally:
        service.close()
    payload = {
        "new_outcomes": count,
        "groups": settings.configured_groups(),
        "learning_memory": str(build_prediction_store(settings).learning_path),
    }
    if json_output:
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    console.print(f"Feedback settled. New outcomes: {count}")
    console.print(f"Learning memory: {payload['learning_memory']}")


@feedback_app.command("status")
def feedback_status() -> None:
    store = build_prediction_store()
    records = store.load_prediction_records()
    outcomes = store.load_outcomes()
    console.print(f"Prediction records: {len(records)}")
    console.print(f"Settled outcomes: {len(outcomes)}")
    console.print(f"Learning memory: {store.learning_path}")
    if store.load_learning_memory():
        console.print(store.load_learning_memory())


if __name__ == "__main__":
    app()
