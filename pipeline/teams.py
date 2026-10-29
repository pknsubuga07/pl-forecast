"""Team-name normalisation. data/team_aliases.csv is the single source of truth; it is loaded
into the team_aliases table and every source goes through TeamMapper.resolve()."""
from __future__ import annotations

import csv
import logging
import re
import sqlite3
import unicodedata
from pathlib import Path

from .config import DATA_DIR, TEAM_ALIASES_CSV
from .db import upsert

log = logging.getLogger(__name__)
TEAMS_CSV = DATA_DIR / "teams.csv"
US_TEAMS_CSV = DATA_DIR / "us_teams.csv"
US_SOURCES = ("nflverse", "espn-nfl", "espn-nba")  # exact-match only; never loose-matched


class UnknownTeamError(KeyError):
    pass


_STOPWORDS = {"fc", "afc", "the"}


def normalise_name(name: str) -> str:
    """Loose key for matching: lowercase, ascii, no punctuation or 'FC'/'AFC'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(w for w in s.split() if w not in _STOPWORDS)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalise_name(name)).strip("-")


class TeamMapper:
    def __init__(self, aliases: dict[tuple[str, str], str], names: dict[str, str]):
        self.aliases = aliases
        self.names = names  # team_id -> display name
        self._loose: dict[str, str] = {}
        for (source, alias), tid in aliases.items():
            if source not in US_SOURCES:
                self._loose.setdefault(normalise_name(alias), tid)
        for tid, name in names.items():
            if not tid.startswith(("nba-", "nfl-")):
                self._loose.setdefault(normalise_name(name), tid)
        self.new_teams: list[dict] = []

    @classmethod
    def from_csv(cls, aliases_csv: Path = TEAM_ALIASES_CSV, teams_csv: Path = TEAMS_CSV) -> "TeamMapper":
        with open(aliases_csv, newline="") as f:
            aliases = {(r["source"], r["alias"]): r["team_id"] for r in csv.DictReader(f)}
        with open(teams_csv, newline="") as f:
            names = {r["team_id"]: r["name"] for r in csv.DictReader(f)}
        if US_TEAMS_CSV.exists():
            with open(US_TEAMS_CSV, newline="") as f:
                names.update({r["team_id"]: r["name"] for r in csv.DictReader(f)})
        unknown = {t for t in aliases.values() if t not in names}
        if unknown:
            raise ValueError(f"team_aliases.csv references unknown team ids: {sorted(unknown)}")
        return cls(aliases, names)

    def resolve(self, source: str, alias: str, *, allow_new: bool = False) -> str:
        """Map a source spelling to a canonical team_id.

        Exact (source, alias) match first, then a loose normalised match. Unknown names raise
        UnknownTeamError unless allow_new (used for Championship-only clubs, which only feed Elo).
        """
        alias = alias.strip()
        tid = self.aliases.get((source, alias))
        if tid:
            return tid
        if source in US_SOURCES:
            raise UnknownTeamError(f"Unmapped {source} team {alias!r}. Add a row to data/team_aliases.csv.")
        tid = self._loose.get(normalise_name(alias))
        if tid:
            self.aliases[(source, alias)] = tid
            return tid
        if allow_new:
            tid = slugify(alias)
            log.warning("Registering new team %r from %s as %r", alias, source, tid)
            self.names[tid] = alias
            self.aliases[(source, alias)] = tid
            self._loose[normalise_name(alias)] = tid
            self.new_teams.append({"team_id": tid, "name": alias, "short_name": alias[:3].upper()})
            return tid
        raise UnknownTeamError(
            f"Unmapped team name {alias!r} from source {source!r}. "
            f"Add a row to data/team_aliases.csv (and data/teams.csv if it is a new club)."
        )

    def sync_to_db(self, conn: sqlite3.Connection) -> None:
        with open(TEAMS_CSV, newline="") as f:
            teams = [dict(r) for r in csv.DictReader(f)]
        for t in teams:
            t["stadium"] = t.get("stadium") or None
        upsert(conn, "teams", teams + self.new_teams, key=("team_id",))
        upsert(conn, "team_aliases",
               [{"source": s, "alias": a, "team_id": t} for (s, a), t in self.aliases.items() if s not in US_SOURCES],
               key=("source", "alias"), keep_existing_when_null=False)
