# obst-defaults stream contracts

Parent: [obst-defaults contracts](../README.md)

These contracts define application-owned metadata around logical OBST byte
streams. They remain independent of Recipes and the Stages used to represent
the stream's chunks.

## Contracts

- [`obst.file@1`](file.md): one portable basename and its exact file bytes.

The generic [stream-profile API](../../../../../docs/extensions/profiles.md)
owns provider composition and optional metadata interpretation.
