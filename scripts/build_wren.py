"""Build the four Wren knowledge configurations.

    python scripts/build_wren.py            # all four
    python scripts/build_wren.py --only D   # just one

Configuration D loads NL-SQL exemplars into LanceDB-backed query memory; the
first run downloads a sentence-transformers model and can take several minutes.
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401  (sys.path + UTF-8 stdout)

from config.logging import get_logger, register_secrets
from config.settings import CONFIG_NAMES, load_settings
from wren_setup.build import (
    CONFIG_FEATURES, build_config, load_exemplars, validate_config,
    write_connection_profile,
)
from wren_setup.helpers import WrenError, wren_version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=list(CONFIG_NAMES), help="build one configuration")
    parser.add_argument("--level", default="warning", choices=["error", "warning", "strict"],
                        help="validation depth (default: warning)")
    args = parser.parse_args()

    settings = load_settings()
    register_secrets(settings.secrets())
    log = get_logger("build_wren", settings.debug)

    version = wren_version(settings)
    if not version:
        log.error(
            "`wren` not found. Install it with:\n"
            "    pip install 'wrenai[postgres,mcp,memory]'"
        )
        return 1
    print(f"Using {version}\n")

    targets = [args.only] if args.only else list(CONFIG_NAMES)
    settings.wren_project_root.mkdir(parents=True, exist_ok=True)
    settings.wren_home.mkdir(parents=True, exist_ok=True)
    write_connection_profile(settings)

    failed = False
    for name in targets:
        features = CONFIG_FEATURES[name]
        try:
            build_config(name, settings)
            exemplars = load_exemplars(name, settings) if features["exemplars"] else 0
        except WrenError as exc:
            log.error("config %s failed: %s", name, exc)
            failed = True
            continue

        report = validate_config(name, settings, args.level)
        errors = "0 errors" not in report and "error" in report.lower()

        print(f"config {name}")
        print(f"  path         {settings.project_dir(name)}")
        print(f"  descriptions {'yes' if features['descriptions'] else 'no'}")
        print(f"  rules        {'yes' if features['rules'] else 'no'}")
        print(f"  exemplars    {exemplars}")
        for line in report.splitlines():
            if line.strip():
                print(f"  | {line}")
        print()
        if errors:
            failed = True

    if failed:
        print("Build finished with errors.")
        return 1
    print("All configurations built. Next: python scripts/verify_ground_truth.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
