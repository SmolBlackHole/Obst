"""Argument parser composition for native and plugin-contributed commands."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from functools import partial

from obst.cli.commands import CliCommand
from obst.cli.inspection import configure_inspect_parser
from obst.cli.presentation import HumanOutputStyle, strip_ansi
from obst.core.wire import format_version
from obst.plugins import PluginError

PLUGIN_TEST_WARNING = (
    "plugin conformance executes installed plugin code with your current process "
    "privileges. No sandbox is used. Test only plugins you trust."
)
_HOST_COMMANDS = frozenset({"extensions", "help", "inspect", "limits", "plugins"})


class _ObstHelpFormatter(argparse.HelpFormatter):
    """Distinguish host commands from activated plugin contributions."""

    def __init__(
        self,
        prog: str,
        *,
        plugin_command_names: frozenset[str],
    ) -> None:
        super().__init__(prog)
        self._plugin_command_names = plugin_command_names

    def _format_action_invocation(self, action: argparse.Action) -> str:
        invocation = super()._format_action_invocation(action)
        if action.dest not in self._plugin_command_names:
            return invocation
        return self._style().contributed(strip_ansi(invocation))

    def _metavar_formatter(
        self,
        action: argparse.Action,
        default_metavar: str,
    ) -> Callable[[int], tuple[str, ...]]:
        if action.dest != "command" or action.choices is None:
            return super()._metavar_formatter(action, default_metavar)
        style = self._style()
        choices = (
            style.contributed(choice)
            if choice in self._plugin_command_names
            else style.success(choice)
            for choice in map(str, action.choices)
        )
        metavar = "{" + ",".join(choices) + "}"
        return lambda tuple_size: (metavar,) * tuple_size

    def _style(self) -> HumanOutputStyle:
        theme = getattr(self, "_theme", None)
        return HumanOutputStyle(color=bool(getattr(theme, "reset", "")))


def build_parser() -> argparse.ArgumentParser:
    """Build the generic parser without loading plugin code."""
    parser, _, _ = build_parser_tree()
    return parser


def build_parser_tree(
    plugin_commands: tuple[CliCommand, ...] = (),
) -> tuple[
    argparse.ArgumentParser,
    dict[str, argparse.ArgumentParser],
    dict[str, CliCommand],
]:
    """Build the parser tree for native and already selected plugin commands."""
    plugin_command_names = frozenset(command.name for command in plugin_commands)
    formatter_class = partial(
        _ObstHelpFormatter,
        plugin_command_names=plugin_command_names,
    )
    parser = argparse.ArgumentParser(
        prog="obst",
        epilog="Run 'obst help COMMAND' for command-specific help.",
        formatter_class=formatter_class,
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
            f"Warning: {PLUGIN_TEST_WARNING}"
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

    limits_parser = commands.add_parser(
        "limits",
        help="inspect and manage local resource limit profiles",
    )
    command_parsers["limits"] = limits_parser
    limit_subcommands = limits_parser.add_subparsers(
        dest="limit_command",
        required=True,
    )
    limit_profiles_parser = limit_subcommands.add_parser(
        "profiles",
        help="list built-in, contributed and custom profiles",
    )
    _add_limit_command_options(limit_profiles_parser)
    limit_show_parser = limit_subcommands.add_parser(
        "show",
        help="show resolved resource ceilings for one profile",
    )
    limit_show_parser.add_argument("profile", nargs="?", metavar="PROFILE")
    _add_limit_command_options(limit_show_parser)
    limit_create_parser = limit_subcommands.add_parser(
        "create",
        help="create one empty custom profile",
    )
    limit_create_parser.add_argument("profile", metavar="PROFILE")
    _add_limit_command_options(limit_create_parser)
    limit_set_parser = limit_subcommands.add_parser(
        "set",
        help="set one resource override on a custom profile",
    )
    limit_set_parser.add_argument("profile", metavar="PROFILE")
    limit_set_parser.add_argument("resource", metavar="RESOURCE")
    limit_set_parser.add_argument(
        "maximum",
        metavar="MAXIMUM|none",
        type=_parse_limit_maximum,
    )
    _add_limit_command_options(limit_set_parser)
    limit_use_parser = limit_subcommands.add_parser(
        "use",
        help="persistently select one available profile",
    )
    limit_use_parser.add_argument("profile", metavar="PROFILE")
    _add_limit_command_options(limit_use_parser)
    limit_delete_parser = limit_subcommands.add_parser(
        "delete",
        help="delete one inactive custom profile",
    )
    limit_delete_parser.add_argument("profile", metavar="PROFILE")
    _add_limit_command_options(limit_delete_parser)

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


def requires_plugin_commands(arguments: list[str]) -> bool:
    """Return whether parsing this invocation needs enabled plugin commands."""
    if not arguments:
        return True
    if arguments[0] in {"-h", "--help"}:
        return True
    if arguments[0].startswith("-"):
        return False
    command = arguments[0]
    if command != "help":
        return command not in _HOST_COMMANDS
    return len(arguments) == 1 or arguments[1] not in _HOST_COMMANDS


def _add_plugin_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--plugin",
        action="append",
        default=[],
        metavar="NAME",
        help="load one explicitly trusted installed plugin for this command",
    )


def _add_limit_command_options(parser: argparse.ArgumentParser) -> None:
    _add_plugin_selection(parser)
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit stable machine-readable profile output",
    )


def _parse_limit_maximum(value: str) -> int | None:
    if value == "none":
        return None
    try:
        maximum = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "maximum must be a non-negative integer or 'none'"
        ) from exc
    if maximum < 0:
        raise argparse.ArgumentTypeError(
            "maximum must be a non-negative integer or 'none'"
        )
    return maximum


__all__ = [
    "PLUGIN_TEST_WARNING",
    "build_parser",
    "build_parser_tree",
    "requires_plugin_commands",
]
