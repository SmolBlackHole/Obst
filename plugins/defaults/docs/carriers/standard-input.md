# Standard-input carrier: `obst.stdin@1`

Parent: [obst-defaults Carriers](README.md)

<!--
SPDX-FileCopyrightText: 2026 SmolBlackHole
SPDX-License-Identifier: MPL-2.0
-->

The standard-input carrier exposes a host-owned binary input stream as an OBST
container source. It reads only; standard output is a different capability and
is not implied by the name. Closing the bound carrier session does not close
the host process's input object.

## Table of contents

- [Standard-input carrier: `obst.stdin@1`](#standard-input-carrier-obststdin1)
	- [Table of contents](#table-of-contents)
	- [Capabilities](#capabilities)
	- [Bind host-owned input](#bind-host-owned-input)
	- [Ownership and terminal state](#ownership-and-terminal-state)
	- [Shell safety](#shell-safety)

## Capabilities

| Property         | Value                                                |
| ---------------- | ---------------------------------------------------- |
| Extension ID     | `obst.stdin@1`                                       |
| Extension kind   | Carrier                                              |
| Reader           | Yes                                                  |
| Streaming writer | No                                                   |
| Publisher        | No                                                   |
| Request type     | `StdinReadRequest`                                   |
| Python provider  | `obst_defaults.carriers.stdin.StdinCarrierExtension` |

The absence of writer and publisher capabilities is explicit. A future stdout
carrier would be a separate provider rather than hidden behind this read-only
ID.

## Bind host-owned input

```python
import sys

from obst_defaults.carriers.stdin import StdinCarrierExtension, StdinReadRequest

stdin = StdinCarrierExtension()
session = stdin.bind_reader(StdinReadRequest(sys.stdin.buffer))
source = session.open()
try:
    ...
finally:
    session.close()
```

The request contains the already selected `BinaryReader`. The carrier does not
look up a global stdin object, reopen a path or infer text encoding.

## Ownership and terminal state

`open()` may be called once. `close()` transitions the session to its terminal
state but deliberately leaves the host-owned reader open. Invalid lifecycle
transitions raise `CarrierStateError` through the shared carrier contract.

## Shell safety

OBST requires binary input. POSIX redirection is binary-safe. Windows
PowerShell 5.1's object pipeline can alter arbitrary bytes; the
[CLI guide](../../../../docs/toolchain/cli.md#inspect-from-stdin) documents a binary-safe redirect.
