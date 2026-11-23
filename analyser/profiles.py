"""Load bank profiles (one YAML file per bank)."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

PROFILE_DIR = Path(__file__).parent / "readers" / "profiles"


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    detect_header: tuple[str, ...] = ()
    detect_footer: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict, compare=False, hash=False)


@cache
def load_profiles(directory: Path = PROFILE_DIR) -> tuple[Profile, ...]:
    profiles = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if data.get("id") != path.stem:
            raise ValueError(f"{path.name}: id must equal the file name ({path.stem})")
        detect = data.get("detect") or {}
        profiles.append(
            Profile(
                id=data["id"],
                name=data.get("name", data["id"]),
                detect_header=tuple(detect.get("header", [])),
                detect_footer=tuple(detect.get("footer", [])),
                raw=data,
            )
        )
    return tuple(profiles)
