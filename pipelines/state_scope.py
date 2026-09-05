"""Canonical state scopes for public-data acquisition; topology remains TX-only."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_DATA = """01|AL|Alabama
02|AK|Alaska
04|AZ|Arizona
05|AR|Arkansas
06|CA|California
08|CO|Colorado
09|CT|Connecticut
10|DE|Delaware
11|DC|District of Columbia
12|FL|Florida
13|GA|Georgia
15|HI|Hawaii
16|ID|Idaho
17|IL|Illinois
18|IN|Indiana
19|IA|Iowa
20|KS|Kansas
21|KY|Kentucky
22|LA|Louisiana
23|ME|Maine
24|MD|Maryland
25|MA|Massachusetts
26|MI|Michigan
27|MN|Minnesota
28|MS|Mississippi
29|MO|Missouri
30|MT|Montana
31|NE|Nebraska
32|NV|Nevada
33|NH|New Hampshire
34|NJ|New Jersey
35|NM|New Mexico
36|NY|New York
37|NC|North Carolina
38|ND|North Dakota
39|OH|Ohio
40|OK|Oklahoma
41|OR|Oregon
42|PA|Pennsylvania
44|RI|Rhode Island
45|SC|South Carolina
46|SD|South Dakota
47|TN|Tennessee
48|TX|Texas
49|UT|Utah
50|VT|Vermont
51|VA|Virginia
53|WA|Washington
54|WV|West Virginia
55|WI|Wisconsin
56|WY|Wyoming"""

SOURCE_ENCODINGS = {"census_tiger_counties": "fips", "eaglei": "name", "eaglei_coverage": "usps",
    "fema_nri": "usps", "noaa_storm_events": "upper_name", "nws_zone_county_crosswalk": "usps",
    "pudl_eia860": "usps", "ntad_military_bases": "lower_usps"}


class StateScopeError(ValueError): pass

def _key(value: str) -> str: return re.sub(r"[^a-z0-9]", "", value.lower())

@dataclass(frozen=True, order=True)
class State:
    fips: str
    usps: str
    name: str
    def source_value(self, encoding: str) -> str:
        return {"fips": self.fips, "usps": self.usps, "name": self.name, "upper_name": self.name.upper(), "lower_usps": self.usps.lower()}[encoding]

STATES = tuple(State(*line.split("|")) for line in _DATA.splitlines())
_BY_KEY = {_key(value): state for state in STATES for value in (state.fips, state.usps, state.name)}
_BY_KEY[_key("Washington DC")] = _BY_KEY["dc"]

def normalize_state(value: str | int | State) -> State:
    if isinstance(value, State): return value
    if isinstance(value, bool): raise StateScopeError("boolean is not a state")
    text = str(value).strip()
    if text.isdigit():
        if len(text) > 2: raise StateScopeError(f"expected state FIPS, not {value!r}")
        text = text.zfill(2)
    try: return _BY_KEY[_key(text)]
    except KeyError as error: raise StateScopeError(f"unknown state {value!r}; use USPS, full name, or two-digit FIPS") from error

def _flatten(values) -> tuple:
    if values is None: return ("TX",)
    if isinstance(values, (str, int, State)): values = (values,)
    result = []
    for value in values:
        result.extend(part.strip() for part in value.split(",") if part.strip()) if isinstance(value, str) else result.append(value)
    return tuple(result)

@dataclass(frozen=True)
class StateScope:
    states: tuple[State, ...]
    @classmethod
    def parse(cls, values=None):
        states = tuple(sorted(set(normalize_state(item) for item in _flatten(values))))
        if not states: raise StateScopeError("at least one state is required")
        return cls(states)
    @property
    def fips(self): return tuple(item.fips for item in self.states)
    @property
    def usps(self): return tuple(item.usps for item in self.states)
    @property
    def names(self): return tuple(item.name for item in self.states)
    @property
    def slug(self): return "-".join(item.usps.lower() for item in self.states)
    @property
    def is_texas_only(self): return self.usps == ("TX",)
    def source_values(self, source_id: str):
        try: encoding = SOURCE_ENCODINGS[source_id]
        except KeyError as error: raise StateScopeError(f"source {source_id!r} has no declared state encoding") from error
        return tuple(item.source_value(encoding) for item in self.states)
    def raw_dir(self, root: str | Path, source: str, release: str, *, shared_national_artifact=False) -> Path:
        return Path(root) / source / release / ("national" if shared_national_artifact else f"scope={self.slug}")

def scope(values=None) -> StateScope: return StateScope.parse(values)
STATE_CODES = frozenset(state.usps for state in STATES)

def parse_states(values: list[str] | None, *, default=("TX",)) -> tuple[str, ...]:
    """Legacy ``--states`` parser: USPS-only and preserves caller order."""
    if not values:
        return default
    result: list[str] = []
    for value in values:
        for part in value.split(","):
            code = part.strip().upper()
            if code not in STATE_CODES:
                raise ValueError(f"unsupported state {part!r}; use two-letter US postal abbreviations")
            if code not in result:
                result.append(code)
    if not result:
        raise ValueError("at least one state is required")
    return tuple(result)
def synthetic_topology_supported(values=None) -> bool: return (values if isinstance(values, StateScope) else scope(values)).is_texas_only
def sql_in(column: str, values: tuple[str, ...]) -> tuple[str, list[str]]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column) or not values: raise StateScopeError("unsafe/empty predicate")
    return f"{column} IN ({', '.join('?' for _ in values)})", list(values)
