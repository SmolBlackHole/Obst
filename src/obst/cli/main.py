"""Generic OBST command host and explicit plugin composition root."""

from __future__ import annotations

import argparse
import sys
from io import TextIOWrapper
from typing import cast

from obst.cli.commands import (
    EXIT_INTERNAL,
    EXIT_INVALID_CONTAINER,
    EXIT_IO,
    EXIT_PIPELINE,
    EXIT_PLUGIN,
    EXIT_RESOURCE_LIMIT,
    EXIT_SUCCESS,
    EXIT_UNSUPPORTED,
    CliCommand,
    CliCommandError,
    CliContext,
)
from obst.cli.inspection import configure_inspect_parser, run_inspect
from obst.cli.output import (
    render_extension_inventory_human,
    render_extension_inventory_json,
    render_plugin_catalog_human,
    render_plugin_catalog_json,
    render_plugin_conformance_human,
    render_plugin_conformance_json,
)
from obst.cli.presentation import HumanOutputStyle, escape_human_text
from obst.core.errors import (
    BinaryIOContractError,
    CorruptContainerError,
    InvalidContainerError,
    MissingExtensionCapabilityError,
    ObstError,
    ResourceLimitError,
    TruncatedContainerError,
    UnsupportedVersionError,
)
from obst.core.io import BinaryReader
from obst.core.resources import DEFAULT_RESOURCE_LIMITS
from obst.core.wire import format_version
from obst.plugins import PluginError, PluginManager, PluginRuntime

_PLUGIN_TEST_WARNING = (
    "plugin conformance executes installed plugin code with your current process "
    "privileges. No sandbox is used. Test only plugins you trust."
)
_HOST_COMMANDS = frozenset({"extensions", "help", "inspect", "plugins"})


def _plugin_manager() -> PluginManager:
    """Create one host manager without implicitly trusted plugins."""
    return PluginManager.discover()


def build_parser() -> argparse.ArgumentParser:
    """Build the generic parser without loading plugin code."""
    parser, _, _ = _build_parser_tree()
    return parser


def _build_parser_tree(
    plugin_commands: tuple[CliCommand, ...] = (),
) -> tuple[
    argparse.ArgumentParser,
    dict[str, argparse.ArgumentParser],
    dict[str, CliCommand],
]:
    parser = argparse.ArgumentParser(
        prog="obst",
        epilog="Run 'obst help COMMAND' for command-specific help.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s format {format_version.label}",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    command_parsers: dict[str, argparse.ArgumentParser] = {}

    plugins_parser = commands.add_parser(
        "plugins",
        help="inspect and manage installed plugins",
    )
    command_parsers["plugins"] = plugins_parser
    plugin_subcommands = plugins_parser.add_subparsers(
        dest="plugin_command",
        required=True,
    )
    plugins_list_parser = plugin_subcommands.add_parser(
        "list",
        help="list installed and enabled plugins without loading code",
    )
    plugins_list_parser.add_argument(
        "--json",
        action="store_true",
        help="emit a stable machine-readable plugin catalog",
    )
    plugins_enable_parser = plugin_subcommands.add_parser(
        "enable",
        help="persistently enable one installed plugin",
    )
    plugins_enable_parser.add_argument("name", metavar="NAME")
    plugins_disable_parser = plugin_subcommands.add_parser(
        "disable",
        help="persistently disable one plugin",
    )
    plugins_disable_parser.add_argument("name", metavar="NAME")
    plugins_test_parser = plugin_subcommands.add_parser(
        "test",
        help="run one plugin's conformance cases (executes plugin code)",
        description=(
            "Run one plugin's published portable conformance cases. "
            f"Warning: {_PLUGIN_TEST_WARNING}"
        ),
    )
    plugins_test_parser.add_argument("name", metavar="NAME")
    plugins_test_parser.add_argument(
        "--json",
        action="store_true",
        help="emit a stable machine-readable conformance report",
    )
    _add_plugin_selection(plugins_test_parser)

    extensions_parser = commands.add_parser(
        "extensions",
        help="show capabilities provided by enabled and one-shot plugins",
    )
    command_parsers["extensions"] = extensions_parser
    extensions_parser.add_argument(
        "--json",
        action="store_true",
        help="emit a stable machine-readable capability inventory",
    )
    _add_plugin_selection(extensions_parser)

    inspect_parser = commands.add_parser(
        "inspect",
        help="validate and describe a container without decoding payloads",
    )
    command_parsers["inspect"] = inspect_parser
    _add_plugin_selection(inspect_parser)
    configure_inspect_parser(inspect_parser)

    contributed: dict[str, CliCommand] = {}
    for contributed_command in plugin_commands:
        if (
            contributed_command.name in command_parsers
            or contributed_command.name == "help"
        ):
            raise PluginError(
                "plugin command name conflicts with host command "
                f"{contributed_command.name}"
            )
        command_parser = commands.add_parser(
            contributed_command.name,
            help=contributed_command.summary,
        )
        _add_plugin_selection(command_parser)
        contributed_command.configure_parser(command_parser)
        command_parsers[contributed_command.name] = command_parser
        contributed[contributed_command.name] = contributed_command

    help_parser = commands.add_parser(
        "help",
        help="show general help or help for a command",
    )
    command_parsers["help"] = help_parser
    help_parser.add_argument(
        "topic",
        nargs="?",
        choices=tuple(command_parsers),
        metavar="COMMAND",
        help="command whose help should be shown",
    )
    return parser, command_parsers, contributed


def _add_plugin_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--plugin",
        action="append",
        default=[],
        metavar="NAME",
        help="load one explicitly trusted installed plugin for this command",
    )


def main(argv: list[str] | None = None) -> int:
    """Run the OBST CLI and return a process exit code."""
    _configure_standard_streams()
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        manager = _plugin_manager()
        plugin_commands = (
            manager.commands() if _requires_plugin_commands(arguments) else ()
        )
        parser, command_parsers, contributed = _build_parser_tree(plugin_commands)
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

        if args.command == "inspect":
            return run_inspect(
                args,
                registry=runtime.registry,
                stdin=_binary_stdin(),
                stdout=sys.stdout,
                limits=DEFAULT_RESOURCE_LIMITS,
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
                    limits=DEFAULT_RESOURCE_LIMITS,
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


def _requires_plugin_commands(arguments: list[str]) -> bool:
    if not arguments or arguments[0].startswith("-"):
        return False
    command = arguments[0]
    if command != "help":
        return command not in _HOST_COMMANDS
    return len(arguments) > 1 and arguments[1] not in _HOST_COMMANDS


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
            f"{style.identifier(escape_human_text(status.name))}\n"
        )
        return EXIT_SUCCESS
    if args.plugin_command == "disable":
        status = manager.disable(args.name)
        style = HumanOutputStyle.for_stream(sys.stdout)
        sys.stdout.write(
            f"{style.warning('Disabled')} plugin "
            f"{style.identifier(escape_human_text(status.name))}\n"
        )
        return EXIT_SUCCESS
    if args.plugin_command == "test":
        warning_style = HumanOutputStyle.for_stream(sys.stderr)
        print(
            f"{warning_style.warning('obst: warning:')} {_PLUGIN_TEST_WARNING}",
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
