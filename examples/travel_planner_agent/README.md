# Travel Planner Example
This is the Travel Planner Example from the A2A repo, modified to use SLIM A2A

## Getting started

1. Create an environment file with your API key:
> You need to set the value corresponding AZURE_OPENAI_API_KEY.

   ```bash
   echo "AZURE_OPENAI_API_KEY=your_api_key_here" > .env
   ```

2. Start SLIM
3. 
Download the slimctl version for your system from the [release page.](https://github.com/agntcy/slim/releases/tag/slimctl-v1.0.0)

```shell
slimctl slim start --endpoint 127.0.0.1:46357
```

3. Start the server

```bash
uv run python -m examples.travel_planner_agent.server
```

4. Run the loop client

```bash
uv run python -m examples.travel_planner_agent.client
```
