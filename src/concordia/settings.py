from pathlib import Path
from typing import Self

import yaml
from attrs import define
from cattrs import structure, transform_error
from cattrs.errors import ClassValidationError


Pathy = str | Path


@define
class FtpSettings:
    server: str
    port: int

    user: str
    password: str


@define
class Settings:
    version: str

    base_year: int
    luc_sectors: list[str]
    regionmappings: dict[str, dict[str, str]]
    country_combinations: dict[str, list[str]]
    variable_template: str

    encoding: dict

    ftp: FtpSettings

    # where to save outputs
    out_path: Path
    # where to load data from
    data_path: Path
    # where historical data is stored
    history_path: Path
    # where scenario data is stored
    scenario_path: Path
    # where proxies are stored
    proxy_path: Path
    # where gridding process files are kept (should contain non-ceds-input and
    # ceds-input folders for proxy generation)
    gridding_path: Path
    # where postprocessing related files are kept
    postprocess_path: Path

    @staticmethod
    def resolve_paths(config, base_path=None):
        def expand(path):
            if path[0] == "$":
                reference, relative = path[1:].split("/", 1)
                return expand(config[reference]) / relative

            if base_path is not None:
                return (base_path / path).expanduser()

            return Path(path).expanduser()

        expanded = {
            key: (expand(val) if key.endswith("_path") else val)
            for key, val in config.items()
        }

        # Special treatment for path entry in regionmappings
        regionmappings = config.get("regionmappings")
        if regionmappings is not None:
            expanded["regionmappings"] = {
                key: val | dict(path=expand(val["path"]))
                for key, val in regionmappings.items()
            }

        return expanded

    @classmethod
    def from_config(
        cls,
        config_path: Pathy = "config.yaml",
        base_path: Pathy | None = None,
        **overwrites,
    ) -> Self:
        if base_path is not None:
            base_path = Path(base_path)
            config_path = base_path / config_path

        with open(config_path) as f:
            config = yaml.safe_load(f)

        # TODO might want to replace with merge for nested dictionaries
        try:
            return structure(
                cls.resolve_paths(config | overwrites, base_path=base_path), cls
            )
        except ClassValidationError as exc:
            raise ValueError(", ".join(transform_error(exc, path="config"))) from None
