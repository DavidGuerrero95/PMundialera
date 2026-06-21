from __future__ import annotations

from mundialera.domain.models import Match, Team
from mundialera.interfaces.factory import (
    build_golpredictor_client,
    build_orchestrator,
    build_prediction_model,
    build_research_agent,
)


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        msg = "Install MCP support with: python -m pip install -e \".[mcp]\""
        raise RuntimeError(msg) from exc

    server = FastMCP("pmundialera")

    @server.tool()
    def golpredictor_login_check() -> dict[str, bool]:
        client = build_golpredictor_client()
        try:
            return {"ok": client.login()}
        finally:
            client.close()

    @server.tool()
    def golpredictor_list_groups() -> dict[str, list[str]]:
        client = build_golpredictor_client()
        try:
            return {"groups": client.list_groups()}
        finally:
            client.close()

    @server.tool()
    def golpredictor_scrape_group(group_name: str) -> dict[str, list[dict[str, object]]]:
        client = build_golpredictor_client()
        try:
            matches = client.list_matches(group_name)
        finally:
            client.close()
        return {
            "matches": [
                {
                    "id": match.match_id,
                    "kickoff": match.kickoff.isoformat() if match.kickoff else None,
                    "home": match.home.name,
                    "away": match.away.name,
                    "prediction": match.prediction.label() if match.prediction else None,
                    "result": match.result.label() if match.result else None,
                    "points": match.points,
                }
                for match in matches
            ]
        }

    @server.tool()
    def predict_match(home: str, away: str) -> dict[str, object]:
        match = Match(match_id="manual", kickoff=None, home=Team(home), away=Team(away))
        brief = build_research_agent().research(match)
        prediction = build_prediction_model().predict(brief)
        return {
            "match": match.label,
            "primary": prediction.primary.label(),
            "confidence": prediction.confidence,
            "rationale": prediction.rationale,
        }

    @server.tool()
    def run_prediction_window(group_name: str, dry_run: bool = True) -> dict[str, object]:
        result = build_orchestrator().run_group_window(group_name, dry_run=dry_run)
        return {
            "group": result.group_name,
            "evaluated": [
                {
                    "match": item.match.label,
                    "primary": item.primary.label(),
                    "confidence": item.confidence,
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
        }

    @server.tool()
    def preview_upcoming_predictions(group_name: str, limit: int = 2) -> dict[str, object]:
        predictions = build_orchestrator().preview_upcoming(group_name, limit=limit)
        return {
            "group": group_name,
            "predictions": [
                {
                    "match_id": item.match.match_id,
                    "match": item.match.label,
                    "kickoff": item.match.kickoff.isoformat() if item.match.kickoff else None,
                    "primary": item.primary.label(),
                    "confidence": item.confidence,
                    "rationale": item.rationale,
                }
                for item in predictions
            ],
        }

    server.run()


if __name__ == "__main__":
    main()
