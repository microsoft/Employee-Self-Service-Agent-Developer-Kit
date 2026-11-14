# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Roles attestation support for the ESS Maker Kit.

Home of the deterministic glue the ``/roles`` skill leans on. Today that is a
single Graph hop — turning a person's name into the Entra object id the shared
planner service (WeveNova) stores role assignments against — kept here so the
skill stays free of network detail. See ``roles/cli.py``.
"""
