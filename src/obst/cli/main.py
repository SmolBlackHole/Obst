# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Generic OBST command host and explicit plugin composition root."""

from __future__ import annotations

import argparse
import json
import sys
from io import TextIOWrapper
from typing import cast

from obst.cli.commands import (
    EXIT_INTERNAL,
    EXIT_INVALID_CONTAINER,
    EXIT_IO,
    EXIT_LIMIT_STATE,
    EXIT_PIPELINE,
    EXIT_PLUGIN,
    EXIT_RESOURCE_LIMIT,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED,
    CliCommandError,
    CliContext,
)
from obst.cli.inspection import run_inspect
from obst.cli.output import (
    render_extension_inventory_human,
    render_extension_inventory_json,
    render_limit_profile_human,
    render_limit_profile_json,
    render_limit_profiles_human,
    render_limit_profiles_json,
    render_plugin_catalog_human,
    render_plugin_catalog_json,
    render_plugin_conformance_human,
    render_plugin_conformance_json,
)
from obst.cli.parser import (
    PLUGIN_TEST_WARNING,
    build_parser_tree,
    requires_plugin_commands,
)
from obst.cli.presentation import HumanOutputStyle, escape_human_text
from obst.core.errors import (
    BinaryIOContractError,
    CorruptContainerError,
    InvalidContainerError,
    MissingExtensionCapabilityError,
    ObstError,
    TruncatedContainerError,
    UnsupportedVersionError,
)
from obst.core.io import BinaryReader
from obst.core.resource_accounting import ResourceAccounting, ResourceLimitError
from obst.plugins import PluginError, PluginManager, PluginRuntime
from obst.resources.profiles import LimitProfileManager, LimitProfileStateError


def _plugin_manager() -> PluginManager:
    """Create one host manager without implicitly trusted plugins."""
    return PluginManager.discover()


def main(argv: list[str] | None = None) -> int:
    """Run the OBST CLI and return a process exit code."""
    _configure_standard_streams()
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        manager = _plugin_manager()
        plugin_commands = (
            manager.commands() if requires_plugin_commands(arguments) else ()
        )
        parser, command_parsers, contributed = build_parser_tree(plugin_commands)
        args = parser.parse_args(arguments)

        if args.command == "help":
            selected_parser = (
                parser if args.topic is None else command_parsers[args.topic]
            )
            sys.stdout.write(selected_parser.format_help())
            return EXIT_SUCCESS

        if args.command == "plugins":
            return _run_plugin_management(manager, args)

        additional_plugins = tuple(getattr(args, "plugin", ()))
        runtime = manager.runtime(additional_plugins)

        if args.command == "extensions":
            return _list_extensions(runtime, as_json=args.json)

        if args.command == "limits":
            return _run_limit_management(
                LimitProfileManager.discover(),
                runtime,
                args,
            )

        accounting = ResourceAccounting(
            LimitProfileManager.discover().policy(runtime.resources)
        )

        if args.command == "inspect":
            return run_inspect(
                args,
                registry=runtime.registry,
                stdin=_binary_stdin(),
                stdout=sys.stdout,
                accounting=accounting,
            )

        contributed_command = contributed.get(args.command)
        if contributed_command is not None:
            return contributed_command.run(
                args,
                CliContext(
                    registry=runtime.registry,
                    plugin_names=runtime.plugin_names,
                    stdin=_binary_stdin(),
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                    accounting=accounting,
                ),
            )
    except CliCommandError as exc:
        return _fail(exc.kind, exc.cause, exc.exit_code)
    except TruncatedContainerError as exc:
        return _fail("truncated_container", exc, EXIT_INVALID_CONTAINER)
    except CorruptContainerError as exc:
        return _fail("corrupt_container", exc, EXIT_INVALID_CONTAINER)
    except UnsupportedVersionError as exc:
        return _fail("unsupported_version", exc, EXIT_UNSUPPORTED)
    except InvalidContainerError as exc:
        return _fail("invalid_container", exc, EXIT_INVALID_CONTAINER)
    except ResourceLimitError as exc:
        return _fail("resource_limit", exc, EXIT_RESOURCE_LIMIT)
    except LimitProfileStateError as exc:
        return _fail("limit_state", exc, EXIT_LIMIT_STATE)
    except MissingExtensionCapabilityError as exc:
        return _fail("plugin_error", exc, EXIT_PLUGIN)
    except BinaryIOContractError as exc:
        return _fail("binary_io_contract_error", exc, EXIT_IO)
    except PluginError as exc:
        return _fail("plugin_error", exc, EXIT_PLUGIN)
    except OSError as exc:
        return _fail("io_error", exc, EXIT_IO)
    except ObstError as exc:
        return _fail("pipeline_error", exc, EXIT_PIPELINE)
    return _fail("internal_error", RuntimeError("unknown command"), EXIT_INTERNAL)


def _run_plugin_management(
    manager: PluginManager,
    args: argparse.Namespace,
) -> int:
    if args.plugin_command == "list":
        plugins = manager.catalog()
        rendered = (
            render_plugin_catalog_json(plugins)
            if args.json
            else render_plugin_catalog_human(
                plugins,
                style=HumanOutputStyle.for_stream(sys.stdout),
            )
        )
        sys.stdout.write(rendered)
        return EXIT_SUCCESS
    if args.plugin_command == "enable":
        status = manager.enable(args.name)
        style = HumanOutputStyle.for_stream(sys.stdout)
        sys.stdout.write(
            f"{style.success('Enabled')} plugin "
            f"{style.contributed(escape_human_text(status.name))}\n"
        )
        return EXIT_SUCCESS
    if args.plugin_command == "disable":
        status = manager.disable(args.name)
        style = HumanOutputStyle.for_stream(sys.stdout)
        sys.stdout.write(
            f"{style.warning('Disabled')} plugin "
            f"{style.contributed(escape_human_text(status.name))}\n"
        )
        return EXIT_SUCCESS
    if args.plugin_command == "test":
        warning_style = HumanOutputStyle.for_stream(sys.stderr)
        print(
            f"{warning_style.warning('obst: warning:')} {PLUGIN_TEST_WARNING}",
            file=sys.stderr,
        )
        report = manager.test(args.name, tuple(args.plugin))
        rendered = (
            render_plugin_conformance_json(args.name, report)
            if args.json
            else render_plugin_conformance_human(
                args.name,
                report,
                style=HumanOutputStyle.for_stream(sys.stdout),
            )
        )
        sys.stdout.write(rendered)
        return EXIT_SUCCESS if report.passed else EXIT_PLUGIN
    raise PluginError(f"unknown plugin command {args.plugin_command}")


def _run_limit_management(
    manager: LimitProfileManager,
    runtime: PluginRuntime,
    args: argparse.Namespace,
) -> int:
    catalog = runtime.resources
    style = HumanOutputStyle.for_stream(sys.stdout)
    if args.limit_command == "profiles":
        profiles = manager.profiles(catalog)
        sys.stdout.write(
            render_limit_profiles_json(profiles)
            if args.json
            else render_limit_profiles_human(profiles, style=style)
        )
        return EXIT_SUCCESS
    if args.limit_command == "show":
        view = manager.show(catalog, args.profile)
        sys.stdout.write(
            render_limit_profile_json(view)
            if args.json
            else render_limit_profile_human(view, style=style)
        )
        return EXIT_SUCCESS
    if args.limit_command == "create":
        manager.create(args.profile, catalog)
        view = manager.show(catalog, args.profile)
        sys.stdout.write(
            render_limit_profile_json(view)
            if args.json
            else render_limit_profile_human(view, style=style)
        )
        return EXIT_SUCCESS
    if args.limit_command == "set":
        manager.set(args.profile, args.resource, args.maximum, catalog)
        view = manager.show(catalog, args.profile)
        sys.stdout.write(
            render_limit_profile_json(view)
            if args.json
            else render_limit_profile_human(view, style=style)
        )
        return EXIT_SUCCESS
    if args.limit_command == "use":
        manager.use(args.profile, catalog)
        view = manager.show(catalog, args.profile)
        sys.stdout.write(
            render_limit_profile_json(view)
            if args.json
            else render_limit_profile_human(view, style=style)
        )
        return EXIT_SUCCESS
    if args.limit_command == "delete":
        manager.delete(args.profile, catalog)
        if args.json:
            sys.stdout.write(
                '{\n    "deleted_profile": '
                f'{json.dumps(args.profile)},\n    "schema_version": 1\n}}\n'
            )
        else:
            sys.stdout.write(
                f"{style.success('Deleted')} limit profile "
                f"{style.identifier(escape_human_text(args.profile))}\n"
            )
        return EXIT_SUCCESS
    raise LimitProfileStateError(
        manager.state_path, f"unknown limit command {args.limit_command}"
    )


def _list_extensions(runtime: PluginRuntime, *, as_json: bool) -> int:
    capabilities = runtime.registry.capabilities()
    rendered = (
        render_extension_inventory_json(capabilities)
        if as_json
        else render_extension_inventory_human(
            capabilities,
            style=HumanOutputStyle.for_stream(sys.stdout),
        )
    )
    sys.stdout.write(rendered)
    return EXIT_SUCCESS


def _fail(kind: str, error: BaseException, exit_code: int) -> int:
    style = HumanOutputStyle.for_stream(sys.stderr)
    print(
        f"{style.error('obst:')} "
        f"{style.error(escape_human_text(kind))}: {escape_human_text(error)}",
        file=sys.stderr,
    )
    return exit_code


def _configure_standard_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8")


def _binary_stdin() -> BinaryReader:
    source = getattr(sys.stdin, "buffer", sys.stdin)
    return cast(BinaryReader, source)


if __name__ == "__main__":
    raise SystemExit(main())
