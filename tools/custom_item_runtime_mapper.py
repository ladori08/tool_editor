#!/usr/bin/env python
"""Compatibility shim for legacy custom-item runtime-mapper path."""

from custom_item.runtime_mapper import main


if __name__ == "__main__":
    raise SystemExit(main())

