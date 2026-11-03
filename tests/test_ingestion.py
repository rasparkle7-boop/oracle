from oracle.ingest.cricbuzz import extract_match_infos, normalise_matches
from oracle.ingest.fotmob import normalise_feed


def test_fotmob_normalisation():
    payload = {"leagues": [{"id": 47, "name": "Premier League", "ccode": "ENG", "matches": [{
        "id": 123, "home": {"id": 1, "name": "Home", "score": 0},
        "away": {"id": 2, "name": "Away", "score": 0},
        "status": {"utcTime": "2026-11-07T15:00:00Z", "started": False, "finished": False,
                   "reason": {"short": "NS"}},
    }]}]}
    comps, teams, fixtures = normalise_feed(payload)
    assert len(fixtures) == 1
    assert fixtures[0]["sport"] == "football"
    assert fixtures[0]["status"] == "scheduled"
    assert fixtures[0]["home_team_id"] == "fb:t1"
    assert len(teams) == 2


def test_cricbuzz_normalisation_with_score():
    match = {"matchInfo": {
        "matchId": 1, "seriesId": 2, "seriesName": "Test Series", "matchDesc": "1st T20",
        "matchFormat": "T20", "startDate": 1793597400000, "state": "Complete",
        "status": "Home won by 5 wkts", "matchType": "international",
        "team1": {"teamId": 10, "teamName": "Home"}, "team2": {"teamId": 11, "teamName": "Away"},
        "venueInfo": {"ground": "Ground", "city": "City"},
    }, "matchScore": {
        "team1Score": {"inngs1": {"runs": 180, "wickets": 6, "overs": 20}},
        "team2Score": {"inngs1": {"runs": 160, "wickets": 9, "overs": 20}},
    }}
    comps, teams, fixtures = normalise_matches([match])
    assert len(fixtures) == 1
    fx = fixtures[0]
    assert fx["sport"] == "cricket"
    assert fx["status"] == "finished"
    assert "180/6" in fx["home_score"]
    assert fx["winner_team_id"] == "cr:t10"
