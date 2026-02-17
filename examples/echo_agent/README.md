# Echo Agent

## Run SLIM node

Download the slimctl version for your system from the [release page.](https://github.com/agntcy/slim/releases/tag/slimctl-v1.0.0)

```shell
slimctl slim start --endpoint 127.0.0.1:46357
```

## Run echo agent server

```shell
uv run python -m examples.echo_agent.server
```

## Run echo agent client

```shell
uv run python -m examples.echo_agent.client --text "hi, this is a text message"
```
