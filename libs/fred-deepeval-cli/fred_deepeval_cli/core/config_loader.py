from __future__ import annotations

import logging

from fred_core.common import ConfigFiles, load_configuration_with_config_files
from pydantic import BaseModel


class JudgeProfileSettings(BaseModel):
    api_base: str | None = None
    api_key_env: str | None = None
    request_timeout: int = 120


class JudgeProfile(BaseModel):
    profile_id: str
    provider: str
    model: str
    settings: JudgeProfileSettings = JudgeProfileSettings()


class JudgeConfig(BaseModel):
    default: str
    profiles: list[JudgeProfile]

    def active(self) -> JudgeProfile:
        for p in self.profiles:
            if p.profile_id == self.default:
                return p
        raise ValueError(
            f"Judge profile '{self.default}' not found. "
            f"Available: {[p.profile_id for p in self.profiles]}"
        )


class Configuration(BaseModel):
    version: str = "v1"
    judge: JudgeConfig


def parse_configuration(config_file: str) -> Configuration:
    import yaml

    with open(config_file, encoding="utf-8") as file:
        payload = yaml.safe_load(file)

    if payload is None:
        raise ValueError(f"Configuration file is empty: {config_file}")
    if not isinstance(payload, dict):
        raise ValueError(f"Configuration file must be a mapping object: {config_file}")

    return Configuration.model_validate(payload)


_config_files = ConfigFiles(logger=logging.getLogger(__name__))


def load_configuration() -> Configuration:
    return load_configuration_with_config_files(
        _config_files,
        parse_configuration,
    )
