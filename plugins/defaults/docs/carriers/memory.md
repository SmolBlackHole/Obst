# Memory carrier: `obst.memory@1`

Parent: [obst-defaults Carriers](README.md)

The memory carrier adapts one complete OBST byte stream to or from immutable
Python `bytes`. It is useful for tests, examples and applications that already
own the complete container in memory. It is intentionally not a streaming or
zero-copy abstraction.

## Table of contents

- [Memory carrier: `obst.memory@1`](#memory-carrier-obstmemory1)
	- [Table of contents](#table-of-contents)
	- [Capabilities](#capabilities)
	- [Read bytes](#read-bytes)
	- [Publish bytes](#publish-bytes)
	- [Limits of the adapter](#limits-of-the-adapter)

## Capabilities

| Property          | Value                                                  |
| ----------------- | ------------------------------------------------------ |
| Extension ID      | `obst.memory@1`                                        |
| Extension kind    | Carrier                                                |
| Reader            | Yes                                                    |
| Streaming writer  | No                                                     |
| Publisher         | Yes                                                    |
| Request types     | `MemoryReadRequest`, `MemoryPublishRequest`            |
| Publication value | `PublicationReceipt[bytes]`                            |
| Python provider   | `obst_defaults.carriers.memory.MemoryCarrierExtension` |

The runtime ID is never written to a container. A receiver cannot learn or
care whether the same bytes came from memory, a file or an object store.

## Read bytes

```python
from obst_defaults.carriers.memory import MemoryCarrierExtension, MemoryReadRequest

memory = MemoryCarrierExtension()
session = memory.bind_reader(MemoryReadRequest(container_bytes))
source = session.open()
try:
    ...
finally:
    session.close()
```

`MemoryReadRequest` accepts exact built-in `bytes`. The bound session exposes a
binary reader once and closes its internal buffer when the session closes.

## Publish bytes

```python
from obst_defaults.carriers.memory import (
    MemoryCarrierExtension,
    MemoryPublishRequest,
)

memory = MemoryCarrierExtension()
publisher = memory.bind_publisher(MemoryPublishRequest())
target = publisher.open()
# A complete PackageWriteOperation writes to target here.
receipt = publisher.commit()
container_bytes = receipt.reference
```

The mutable buffer remains private until `commit()` returns a new immutable
`bytes` value. `abort()` discards it. The plugin's [package-execution
helper](package-execution.md#publish-transactionally) applies that transaction
boundary around a prepared package operation.

## Limits of the adapter

The completed container must fit in memory, and committing creates an immutable
byte string from the internal buffer. For large or continuously arriving data,
select a carrier with a streaming writer or an external transactional target.
The [resource policy](../../../../docs/core/resources.md) bounds OBST parsing and recipe
work, but it does not turn this adapter into bounded external storage.
