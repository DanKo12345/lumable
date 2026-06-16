#!/usr/bin/env python3
from __future__ import annotations

import getpass

from app.feature_gate import is_pro
from app.license import activate_license_key
from app.storage import load_settings, save_settings


def main() -> int:
    key = getpass.getpass("Lemon Squeezy license key: ").strip()
    if not key:
        print("No key entered.")
        return 2

    settings = load_settings()
    if activate_license_key(key, settings):
        save_settings(settings)
        print("License activated and saved. Normal app launch should show Pro.")
        return 0

    print("License activation failed. Check the key, product variant, and Lemon Squeezy test/live mode.")
    print(f"Current Pro state: {is_pro()}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
