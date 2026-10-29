import pandas as pd
import pytest

from pipeline.http import SourceError
from pipeline.sources import espn, football_data as fd
from pipeline.teams import TeamMapper, UnknownTeamError, normalise_name


# ------------------------------------------------------------------ team-name mapping
@pytest.fixture(scope="module")
def mapper():
    return TeamMapper.from_csv()


@pytest.mark.parametrize("source,alias,expected", [
    ("football-data", "Man United", "man-united"),
    ("fpl", "Man Utd", "man-united"),
    ("espn", "Manchester United", "man-united"),
    ("football-data", "Nott'm Forest", "nottm-forest"),
    ("espn", "Nottingham Forest", "nottm-forest"),
    ("fpl", "Spurs", "tottenham"),
    ("espn", "Tottenham Hotspur", "tottenham"),
    ("espn", "AFC Bournemouth", "bournemouth"),
    ("espn", "Brighton & Hove Albion", "brighton"),
    ("fpl", "Coventry City", "coventry"),
])
def test_aliases_map_to_one_canonical_team(mapper, source, alias, expected):
    assert mapper.resolve(source, alias) == expected


def test_loose_matching_handles_fc_and_punctuation(mapper):
    assert mapper.resolve("espn", "Manchester United FC") == "man-united"
    assert mapper.resolve("other", "Brighton and Hove Albion") == "brighton"
    assert normalise_name("AFC Bournemouth") == "bournemouth"


def test_unknown_team_fails_loudly(mapper):
    with pytest.raises(UnknownTeamError, match="team_aliases.csv"):
        mapper.resolve("fpl", "Real Madrid")


def test_championship_only_club_can_be_registered(mapper):
    tid = mapper.resolve("football-data", "Stockport", allow_new=True)
    assert tid == "stockport"
    assert mapper.resolve("football-data", "Stockport") == "stockport"


def test_every_alias_points_to_a_known_team(mapper):
    assert set(mapper.aliases.values()) <= set(mapper.names)


# ------------------------------------------------------------------ football-data cleaning
def test_kickoff_converts_uk_local_time_to_utc():
    # British Summer Time (UTC+1) in October before the clocks change...
    assert fd.parse_kickoff("24/10/2026", "15:00") == ("2026-10-24T14:00:00Z", True)
    # ...and GMT (UTC+0) in winter.
    assert fd.parse_kickoff("26/12/2026", "15:00") == ("2026-12-26T15:00:00Z", True)


def test_kickoff_two_digit_year_and_missing_time():
    utc, has_time = fd.parse_kickoff("13/08/05", None)
    assert utc == "2005-08-13T14:00:00Z" and has_time is False


def test_html_instead_of_csv_is_a_source_error():
    with pytest.raises(SourceError, match="HTML"):
        fd.read_csv_bytes(b"<html><body>Service unavailable</body></html>", source="test")


def test_missing_columns_is_a_source_error():
    with pytest.raises(SourceError, match="missing expected columns"):
        fd.read_csv_bytes(b"Div,Date,Home,Away\nE0,01/01/2020,A,B\n", source="test")


def test_normalise_uses_old_betbrain_columns_and_coerces_numbers():
    raw = pd.DataFrame({
        "Div": ["E0"], "Date": ["13/08/05"], "HomeTeam": [" Arsenal "], "AwayTeam": ["Chelsea"],
        "FTHG": ["2"], "FTAG": ["x"], "BbAvH": [1.9], "BbAvD": [3.4], "BbAvA": [4.2],
    })
    out = fd.normalise(raw)
    row = out.iloc[0]
    assert row["home_alias"] == "Arsenal"
    assert row["fthg"] == 2 and pd.isna(row["ftag"])
    assert (row["avg_h"], row["avg_d"], row["avg_a"]) == (1.9, 3.4, 4.2)
    assert pd.isna(row["pinnacle_h"])


def test_rows_without_teams_are_dropped():
    csv = b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,01/01/2020,Arsenal,Chelsea,1,0\n,,,,,\n"
    assert len(fd.read_csv_bytes(csv, source="test")) == 1


# ------------------------------------------------------------------ ESPN odds
@pytest.mark.parametrize("ml,dec", [("+150", 2.5), ("-200", 1.5), (100, 2.0), ("EVEN", 2.0), (None, None), ("OFF", None)])
def test_american_odds_to_decimal(ml, dec):
    assert espn.american_to_decimal(ml) == dec


def test_competitive_filter_excludes_friendlies():
    assert espn.is_competitive("uefa.champions")
    assert espn.is_competitive("eng.league_cup")
    assert not espn.is_competitive("club.friendly")
    assert not espn.is_competitive(None)
