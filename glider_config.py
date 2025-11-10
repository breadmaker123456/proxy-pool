import os
from pathlib import Path
from typing import Optional


def _clean_env_var(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def ensure_config_dir(base_dir: Path, default_relative: str = "glider") -> Path:
    config_dir = resolve_config_dir(base_dir, default_relative)
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def resolve_config_dir(base_dir: Path, default_relative: str = "glider") -> Path:
    env_value = _clean_env_var("GLIDER_CONFIG_DIR")
    if env_value:
        config_dir = Path(env_value)
        if not config_dir.is_absolute():
            config_dir = (base_dir / env_value).resolve()
        return config_dir
    return base_dir / default_relative


def listen_address(default_port: str) -> str:
    value = _clean_env_var("LISTEN_PORT") or default_port
    if value.startswith(":") or ":" in value:
        return value
    return f":{value}"


def strategy(default: str = "rr") -> str:
    return _clean_env_var("STRATEGY") or default


def check_interval(default: int) -> int:
    value = _clean_env_var("CHECK_INTERVAL")
    if not value:
        return default
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except ValueError:
        return default
