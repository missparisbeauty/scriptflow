# Shopee 1688 Profit MCP

This repo now exposes a minimal FastMCP server named `shopee-1688-profit`.

Configured in `.mcp.json`:

```json
"shopee-1688-profit": {
  "command": "C:\\Users\\user\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe",
  "args": [
    "C:\\Users\\user\\Desktop\\scriptflow-dev-docs.zip\\shopee_1688_profit_mcp.py"
  ],
  "env": {
    "DATA_DIR": "C:\\Users\\user\\Desktop\\scriptflow-dev-docs.zip\\shopee-ad-dashboard",
    "PYTHONPATH": "C:\\Users\\user\\Desktop\\scriptflow-dev-docs.zip\\shopee-ad-dashboard"
  }
}
```

Available tools:

- `list_shopee_python_scripts`: list Python files under `shopee-ad-dashboard`.
- `run_shopee_python_script`: run a Python file inside `shopee-ad-dashboard`.
- `calculate_1688_profit`: calculate Shopee profit from a 1688 RMB cost.
- `read_profit_config`: read `shopee-ad-dashboard/profit_config.json`.
- `shopee_profit_summary`: calculate the dashboard's aggregate profit from current CSV data.

Example prompt:

```text
Use shopee-1688-profit to calculate P123:
Shopee price 690 TWD, 1688 cost 42 RMB, China shipping 3 RMB,
international shipping 35 TWD, domestic shipping 60 TWD, ad spend 80 TWD.
Save it to profit_config.
```

Restart Claude/Codex after changing `.mcp.json` so the new MCP server is loaded.
