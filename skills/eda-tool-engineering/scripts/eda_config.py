"""Strict project configuration and ordered RTL source resolution."""
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path


class ConfigError(ValueError):
    pass


def load(path):
    try:
        import yaml
    except ImportError:
        ruby = shutil.which("ruby")
        if not ruby:
            raise ConfigError("YAML parser unavailable: install PyYAML or Ruby")
        script = "require 'yaml'; require 'json'; puts JSON.generate(YAML.safe_load(File.read(ARGV[0])))"
        result = subprocess.run([ruby, "-e", script, str(path)], universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise ConfigError(f"invalid YAML: {result.stderr.strip()}")
        data = json.loads(result.stdout)
    else:
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("eda.yaml must contain a mapping")
    for key in ("name", "top"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ConfigError(f"{key} must be a nonempty string")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9$]*", data["top"]):
        raise ConfigError("top must be an RTL identifier")
    for key in ("rtl", "filelists", "include_dirs", "defines"):
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
            raise ConfigError(f"{key} must be a list of nonempty strings")
        data[key] = value
    for key in ("pdk", "flows", "dft"):
        if key in data and not isinstance(data[key], dict):
            raise ConfigError(f"{key} must be a mapping")
    for flow, value in data.get("flows", {}).items():
        if not isinstance(value, dict):
            raise ConfigError(f"flows.{flow} must be a mapping")
    return data


def resolve(root, value, *, must_exist=True):
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    path = (path if path.is_absolute() else root / path).resolve()
    if must_exist and not path.exists():
        raise ConfigError(f"missing input: {path}")
    return path


def sources(root, cfg):
    """Resolve config RTL, nested filelists, include dirs and defines in order."""
    found, includes, defines, filelists = [], [], [], []
    active = set()

    def add_source(value, base):
        expanded = os.path.expandvars(os.path.expanduser(value))
        pattern = str(Path(expanded) if Path(expanded).is_absolute() else base / expanded)
        matches = sorted(glob.glob(pattern, recursive=True)) if glob.has_magic(pattern) else [pattern]
        if not matches:
            raise ConfigError(f"RTL pattern matched no files: {value}")
        for match in matches:
            path = resolve(root, str(Path(match)))
            if path.is_file() and path not in found:
                found.append(path)

    def add_filelist(value, base):
        path = resolve(base, value)
        if path in active:
            raise ConfigError(f"recursive filelist: {path}")
        active.add(path)
        if path not in filelists:
            filelists.append(path)
        # Filelist paths are relative to the project root, as in common VCS flows.
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "//")):
                continue
            tokens = shlex.split(line, comments=True)
            index = 0
            while index < len(tokens):
                token = tokens[index]
                if token.startswith("+incdir+"):
                    includes.extend(resolve(root, x) for x in token[len("+incdir+"):].split("+") if x)
                elif token.startswith("+define+"):
                    defines.extend(x for x in token[len("+define+"):].split("+") if x)
                elif token in ("-f", "-F"):
                    index += 1
                    if index >= len(tokens):
                        raise ConfigError(f"missing filelist after {token} in {path}")
                    add_filelist(tokens[index], root)
                elif token.startswith("-f") or token.startswith("-F"):
                    add_filelist(token[2:], root)
                elif token.startswith("-"):
                    raise ConfigError(f"unsupported filelist option {token} in {path}")
                else:
                    add_source(token, root)
                index += 1
        active.remove(path)

    for value in cfg["filelists"]:
        add_filelist(value, root)
    for value in cfg["rtl"]:
        add_source(value, root)
    includes.extend(resolve(root, x) for x in cfg["include_dirs"])
    defines.extend(cfg["defines"])
    if not found:
        raise ConfigError("no RTL sources configured")
    return {"rtl": [str(x) for x in found],
            "filelists": [str(x) for x in filelists],
            "include_dirs": list(dict.fromkeys(str(x) for x in includes)),
            "defines": list(dict.fromkeys(defines))}
