# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Static validation for changes under samples/. See README.md."""

from .checks import Result, Status, run_all_checks

__all__ = ["Result", "Status", "run_all_checks"]
