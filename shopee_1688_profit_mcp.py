from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP


PROJECT_ROOT = Path(__file__).resolve().parent
SHOPEE_DIR = PROJECT_ROOT / "shopee-ad-dashboard"
PROFIT_CONFIG_FILE = SHOPEE_DIR / "profit_config.json"

mcp = FastMCP("shopee-1688-profit")


def _load_profit_config() -> dict[str, Any]:
    if not PROFIT_CONFIG_FILE.exists():
        return {}
    return json.loads(PROFIT_CONFIG_FILE.read_text(encoding="utf-8"))


def _save_profit_config(config: dict[str, Any]) -> None:
    PROFIT_CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _rate(value: float | int | None) -> float:
    if not value:
        return 0.0
    value = float(value)
    return value / 100 if value > 1 else value


def _safe_script_path(script_name: str) -> Path:
    script_path = (SHOPEE_DIR / script_name).resolve()
    if not script_path.is_relative_to(SHOPEE_DIR.resolve()):
        raise ValueError("script_name must stay inside shopee-ad-dashboard")
    if script_path.suffix.lower() != ".py":
        raise ValueError("script_name must be a Python file")
    if not script_path.exists():
        raise FileNotFoundError(f"script not found: {script_name}")
    return script_path


@mcp.tool()
def list_shopee_python_scripts() -> dict[str, Any]:
    """List Python scripts under shopee-ad-dashboard."""
    scripts = []
    for path in sorted(SHOPEE_DIR.rglob("*.py")):
        if "__pycache__" in path.parts or "venv" in path.parts:
            continue
        scripts.append(str(path.relative_to(SHOPEE_DIR)).replace("\\", "/"))
    return {"ok": True, "root": str(SHOPEE_DIR), "scripts": scripts}


@mcp.tool()
def run_shopee_python_script(
    script_name: str,
    args: list[str] | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Run one Python script from shopee-ad-dashboard with optional args."""
    args = args or []
    timeout_seconds = max(1, min(int(timeout_seconds), 900))
    script_path = _safe_script_path(script_name)
    cmd = [sys.executable, str(script_path), *[str(arg) for arg in args]]

    try:
        completed = subprocess.run(
            cmd,
            cwd=str(SHOPEE_DIR),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error": "timeout",
            "timeout_seconds": timeout_seconds,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }

    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "command": cmd,
        "stdout": completed.stdout[-12000:],
        "stderr": completed.stderr[-12000:],
    }


@mcp.tool()
def calculate_1688_profit(
    product_id: str,
    shopee_price_twd: float,
    cost_1688_rmb: float,
    quantity: int = 1,
    rmb_to_twd: float = 4.45,
    china_shipping_rmb: float = 0,
    international_shipping_twd: float = 0,
    domestic_shipping_twd: float = 60,
    ad_spend_twd: float = 0,
    platform_fee_rate: float = 0.055,
    payment_fee_rate: float = 0.03,
    other_fee_twd: float = 0,
    save_to_profit_config: bool = False,
) -> dict[str, Any]:
    """Calculate Shopee net profit from a 1688 cost and optionally save config."""
    quantity = max(1, int(quantity))
    platform_fee_rate = _rate(platform_fee_rate)
    payment_fee_rate = _rate(payment_fee_rate)

    unit_cost_twd = (float(cost_1688_rmb) + float(china_shipping_rmb)) * float(rmb_to_twd)
    landed_unit_cost_twd = unit_cost_twd + (float(international_shipping_twd) / quantity)
    revenue = float(shopee_price_twd) * quantity
    cogs = landed_unit_cost_twd * quantity
    domestic_shipping_total = float(domestic_shipping_twd)
    platform_fee = revenue * platform_fee_rate
    payment_fee = revenue * payment_fee_rate
    total_cost = (
        cogs
        + domestic_shipping_total
        + float(ad_spend_twd)
        + platform_fee
        + payment_fee
        + float(other_fee_twd)
    )
    net_profit = revenue - total_cost

    result = {
        "ok": True,
        "product_id": product_id,
        "quantity": quantity,
        "revenue_twd": round(revenue, 2),
        "unit_cost_twd": round(unit_cost_twd, 2),
        "landed_unit_cost_twd": round(landed_unit_cost_twd, 2),
        "cogs_twd": round(cogs, 2),
        "domestic_shipping_twd": round(domestic_shipping_total, 2),
        "ad_spend_twd": round(float(ad_spend_twd), 2),
        "platform_fee_twd": round(platform_fee, 2),
        "payment_fee_twd": round(payment_fee, 2),
        "other_fee_twd": round(float(other_fee_twd), 2),
        "total_cost_twd": round(total_cost, 2),
        "net_profit_twd": round(net_profit, 2),
        "profit_margin_pct": round(net_profit / revenue * 100, 2) if revenue else 0,
        "break_even_roas": round(revenue / max(revenue - cogs - domestic_shipping_total - platform_fee - payment_fee - float(other_fee_twd), 0.01), 2),
        "saved_to_profit_config": False,
    }

    if save_to_profit_config:
        config = _load_profit_config()
        config[product_id] = {
            "cost": round(landed_unit_cost_twd, 2),
            "shipping": round(domestic_shipping_total, 2),
            "platform_fee_rate": platform_fee_rate,
            "payment_fee_rate": payment_fee_rate,
            "selling_price": round(float(shopee_price_twd), 2),
            "source": "1688",
            "cost_1688_rmb": float(cost_1688_rmb),
            "china_shipping_rmb": float(china_shipping_rmb),
            "rmb_to_twd": float(rmb_to_twd),
            "international_shipping_twd": float(international_shipping_twd),
        }
        _save_profit_config(config)
        result["saved_to_profit_config"] = True
        result["profit_config_file"] = str(PROFIT_CONFIG_FILE)

    return result


@mcp.tool()
def read_profit_config(product_id: str | None = None) -> dict[str, Any]:
    """Read shopee-ad-dashboard/profit_config.json."""
    config = _load_profit_config()
    if product_id:
        return {
            "ok": True,
            "product_id": product_id,
            "item": config.get(product_id),
            "exists": product_id in config,
        }
    return {"ok": True, "count": len(config), "items": config}


@mcp.tool()
def shopee_profit_summary(shop: str | None = None, period: str = "month") -> dict[str, Any]:
    """Read current dashboard data and return aggregate profit."""
    if period not in {"yesterday", "week", "month"}:
        return {"ok": False, "error": "period must be yesterday, week, or month"}

    sys.path.insert(0, str(SHOPEE_DIR))
    import ad_data_store

    result = ad_data_store.aggregate_profit(
        shop=shop,
        period=period,
        profit_config=_load_profit_config(),
    )
    return {"ok": True, "summary": result}


if __name__ == "__main__":
    mcp.run()
