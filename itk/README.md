# slima2a ITK agent

The system under test the [A2A Integration Test Kit](https://github.com/a2aproject/a2a-itk)
runs to check slima2a against the A2A conformance corpus (ACTS).

One agent serves the same executor and task store over every binding:

| Binding | Where |
|---|---|
| `slimrpc` | the SLIM name `agntcy/itk/agent-<httpPort>`, when `SLIM_ENDPOINT` is set |
| `GRPC` | `127.0.0.1:<grpcPort>` |
| `JSONRPC` | `http://127.0.0.1:<httpPort>/jsonrpc/` |
| `HTTP+JSON` | `http://127.0.0.1:<httpPort>/rest` |

Because the agent is the same, a run over `slimrpc` and a run over `grpc` differ
only in transport. `slimrpc` carries the gRPC binding's service over SLIM, so
gRPC is the baseline to compare it with.

## Files

- `main.py`: the entrypoint the ITK launcher starts with
  `uv run --locked main.py --httpPort N --grpcPort M`. It serves the agent card at
  `http://127.0.0.1:N/.well-known/agent-card.json` once every other binding is up.
- `tck_executor.py`: the `tck-*` behaviors the corpus drives the agent with.
- `../acts/sut-behaviors.yaml`: which of those behaviors this agent claims. A test
  needing an unclaimed one fails rather than skips.

slima2a is installed from the parent directory, so the ITK always tests this
working copy.

## Running the conformance suite

From an a2a-itk checkout that has the `slimrpc` binding, next to this repo:

```sh
uv run --extra slimrpc run_acts.py --mount ../slim-a2a-python/itk \
    --sdk slim-a2a-python --language python \
    --transport grpc --transport slimrpc
```

The ITK starts a SLIM node for the `slimrpc` run and passes it to the agent as
`SLIM_ENDPOINT` and `SLIM_SHARED_SECRET`. Add `-t CORE-SEND-001` to run one test,
or `--out DIR` to keep the JSON reports.
