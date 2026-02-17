# Travel Planner Example

This is the Travel Planner Example from the A2A repo, modified to use SLIM A2A

## Getting started

1. Configure your Azure OpenAI credentials:

   You can set the required values either via a `.env` file or as environment variables.

   | Variable                       | Required | Default              |
   | ------------------------------ | -------- | -------------------- |
   | `AZURE_OPENAI_API_KEY`         | ✅       | —                    |
   | `AZURE_OPENAI_ENDPOINT`        | ✅       | —                    |
   | `AZURE_OPENAI_API_VERSION`     | ❌       | `2024-08-01-preview` |
   | `AZURE_OPENAI_DEPLOYMENT_NAME` | ❌       | `gpt-4o`             |

   **Option A:** Create a `.env` file:

   ```bash
   echo "AZURE_OPENAI_API_KEY=your_api_key_here" > .env
   echo "AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/" >> .env
   # Optional: override the default API version and deployment name
   # echo "AZURE_OPENAI_API_VERSION=2024-08-01-preview" >> .env
   # echo "AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o" >> .env
   ```

   **Option B:** Export environment variables directly:

   ```bash
   export AZURE_OPENAI_API_KEY="your_api_key_here"
   export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
   # Optional
   # export AZURE_OPENAI_API_VERSION="2024-08-01-preview"
   # export AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4o"
   ```

2. Start SLIM
3. Download the slimctl version for your system from the [release page.](https://github.com/agntcy/slim/releases/tag/slimctl-v1.0.0)

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
