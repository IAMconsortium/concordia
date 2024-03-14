from pathlib import Path
from typing import Self

import yaml
from attrs import define
from cattrs import structure, transform_error


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
    # where gridding process files are kept (should contain non-ceds-input and ceds-input folders for proxy generation)
    gridding_path: Path
    # where postprocessing related files are kept
    postprocess_path: Path

    @staticmethod
    def resolve_paths(config):
        base_path = Path(config["base_path"]) if "base_path" in config else None

        def expand(path):
            if path[0] == "$":
                ind = path.index("/")
                reference = path[1:ind]
                return expand(config[reference]) / path[ind + 1 :]

            if base_path is not None:
                return (base_path / path).expanduser()

            return Path(path).expanduser()

        return {
            key: (expand(val) if key.endswith("_path") else val)
            for key, val in config.items()
            if key != "base_path"
        }

    @classmethod
    def from_config(cls, config_path: Pathy = "config.yaml", **overwrites) -> Self:
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # TODO might want to replace with merge for nested dictionaries
        try:
            return structure(cls.resolve_paths(config | overwrites), cls)
        except Exception as exc:
            raise ValueError(", ".join(transform_error(exc, path="config"))) from None
