"""
odoo_mcp.py
-----------
Gold Tier — Odoo Community MCP Server (JSON-RPC integration).

Connects to a self-hosted Odoo 19+ instance via JSON-RPC API and exposes
accounting and business operations to Claude as MCP tools.

Tools exposed:
  odoo_get_invoices        — List invoices (customer or vendor) with filters
  odoo_create_invoice      — Draft a new customer invoice in Odoo
  odoo_get_invoice_detail  — Get full detail of one invoice by ID or name
  odoo_get_customers       — List customers / partners
  odoo_get_products        — List products/services
  odoo_get_account_balance — Get current balance per account (P&L / BS)
  odoo_run_report          — Request a financial summary (trial balance)
  log_action               — Write a structured entry to today's vault log

SENSITIVE RULE:
  odoo_create_invoice only creates a DRAFT in Odoo.
  It never confirms/posts unless the plan has approved_by: human in Approved/.

Transport: stdio (Claude Desktop / Claude Code MCP integration)

Run (directly for testing):
    python odoo_mcp.py

Add to mcp.json:
    {
      "odoo": {
        "command": "python",
        "args": ["watcher/odoo_mcp.py"],
        "env": {
          "ODOO_URL": "http://localhost:8069",
          "ODOO_DB": "odoo",
          "ODOO_USERNAME": "admin",
          "ODOO_PASSWORD": "admin",
          "VAULT_PATH": "..."
        }
      }
    }

Environment variables:
    ODOO_URL        Odoo base URL (default: http://localhost:8069)
    ODOO_DB         Odoo database name (default: odoo)
    ODOO_USERNAME   Odoo login (default: admin)
    ODOO_PASSWORD   Odoo password (default: admin)
    VAULT_PATH      Vault root (auto-detected from script location)
    DRY_RUN         If "true", skips all writes to Odoo (default: false)
    LOG_LEVEL       INFO / DEBUG (default: INFO)

Dependencies:
    pip install mcp pyyaml
    (urllib is Python stdlib — no extra install)
"""

import os
import sys
import json
import asyncio
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

# ── Config ────────────────────────────────────────────────────────────

VAULT_PATH   = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent))).resolve()
LOGS_PATH    = VAULT_PATH / "Logs"
ACCOUNTING_PATH = VAULT_PATH / "Accounting"

ODOO_URL      = os.getenv("ODOO_URL",      "http://localhost:8069").rstrip("/")
ODOO_DB       = os.getenv("ODOO_DB",       "odoo")
ODOO_USERNAME = os.getenv("ODOO_USERNAME", "admin")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "admin")
DRY_RUN       = os.getenv("DRY_RUN",       "false").lower() == "true"

# Cached session UID (set after authenticate())
_odoo_uid: int | None = None


# ── Odoo JSON-RPC helpers ─────────────────────────────────────────────

def _jsonrpc(endpoint: str, method: str, params: dict) -> dict:
    """Low-level JSON-RPC call. Returns the 'result' field or raises."""
    url     = f"{ODOO_URL}{endpoint}"
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "id": 1,
        "params": params,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise ConnectionError(f"Cannot reach Odoo at {ODOO_URL}: {exc}") from exc

    if "error" in data:
        err = data["error"]
        raise RuntimeError(f"Odoo JSON-RPC error: {err.get('message', str(err))}")

    return data.get("result")


def _authenticate() -> int:
    """Authenticate and return UID. Caches result in _odoo_uid."""
    global _odoo_uid
    if _odoo_uid is not None:
        return _odoo_uid

    uid = _jsonrpc("/web/dataset/call_kw", "call", {
        "model":  "res.users",
        "method": "authenticate",
        "args":   [ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {}],
        "kwargs": {},
    })
    # Odoo 17+ uses /web/session/authenticate instead
    if uid is None or uid is False:
        # Try common auth endpoint
        result = _jsonrpc("/web/session/authenticate", "call", {
            "db":       ODOO_DB,
            "login":    ODOO_USERNAME,
            "password": ODOO_PASSWORD,
        })
        uid = result.get("uid") if isinstance(result, dict) else None

    if not uid:
        raise PermissionError(
            f"Odoo authentication failed for user '{ODOO_USERNAME}' on db '{ODOO_DB}'. "
            "Check ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD."
        )

    _odoo_uid = int(uid)
    return _odoo_uid


def _execute(model: str, method: str, args: list, kwargs: dict | None = None) -> object:
    """Authenticated execute_kw call."""
    uid = _authenticate()
    return _jsonrpc("/web/dataset/call_kw", "call", {
        "model":  model,
        "method": method,
        "args":   [ODOO_DB, uid, ODOO_PASSWORD] + args,
        "kwargs": kwargs or {},
    })


def _search_read(model: str, domain: list, fields: list, limit: int = 50, offset: int = 0) -> list:
    return _execute(model, "search_read", [domain, fields], {
        "limit": limit,
        "offset": offset,
        "order": "id desc",
    }) or []


# ── Vault helpers ─────────────────────────────────────────────────────

def _write_vault_log(
    action_type: str,
    source: str,
    destination: str = "—",
    outcome: str = "success",
    notes: str = "",
) -> None:
    today     = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_file  = LOGS_PATH / f"{today}.md"
    icon      = "✅" if outcome == "success" else "❌"
    entry     = (
        f"- `{timestamp}` | **{action_type}** | `{source}` → `{destination}` "
        f"| {icon} {outcome} | {notes}\n"
    )
    if not log_file.exists():
        LOGS_PATH.mkdir(parents=True, exist_ok=True)
        header = (
            f"---\ntitle: \"Agent Log — {today}\"\ndate: {today}\ntags: [log, agent]\n---\n\n"
            f"# Agent Log — {today}\n\n> Append-only.\n\n---\n\n"
        )
        log_file.write_text(header, encoding="utf-8")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(entry)


def _fmt_currency(amount, currency: str = "USD") -> str:
    try:
        return f"{currency} {float(amount):,.2f}"
    except Exception:
        return str(amount)


# ── MCP Server ────────────────────────────────────────────────────────

server = Server("odoo-mcp")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [

        types.Tool(
            name="odoo_get_invoices",
            description=(
                "List invoices from Odoo. Supports filtering by type "
                "(customer_invoice / vendor_bill), state (draft/posted/cancel), "
                "customer name, and date range. Returns at most 50 records."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "move_type": {
                        "type": "string",
                        "enum": ["out_invoice", "in_invoice", "out_refund", "in_refund"],
                        "description": "out_invoice=customer invoice, in_invoice=vendor bill",
                        "default": "out_invoice",
                    },
                    "state": {
                        "type": "string",
                        "enum": ["draft", "posted", "cancel", "all"],
                        "default": "all",
                        "description": "Filter by invoice state",
                    },
                    "partner_name": {
                        "type": "string",
                        "description": "Optional: filter by customer/vendor name (partial match)",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Optional: start date YYYY-MM-DD",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Optional: end date YYYY-MM-DD",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "Max records to return (1-50)",
                    },
                },
                "required": [],
            },
        ),

        types.Tool(
            name="odoo_get_invoice_detail",
            description="Get full detail of a single Odoo invoice by its ID or reference number.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "integer",
                        "description": "Odoo invoice ID (integer)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Invoice reference/number e.g. INV/2026/0001",
                    },
                },
                "required": [],
            },
        ),

        types.Tool(
            name="odoo_create_invoice",
            description=(
                "Create a DRAFT customer invoice in Odoo. "
                "The invoice stays as a draft — it is never posted/confirmed automatically. "
                "Always requires human approval before posting."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "partner_name": {
                        "type": "string",
                        "description": "Customer name (must exist in Odoo as a partner)",
                    },
                    "invoice_date": {
                        "type": "string",
                        "description": "Invoice date YYYY-MM-DD (defaults to today)",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Payment due date YYYY-MM-DD (optional)",
                    },
                    "lines": {
                        "type": "array",
                        "description": "Invoice line items",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "quantity":    {"type": "number", "default": 1},
                                "price_unit":  {"type": "number"},
                            },
                            "required": ["description", "price_unit"],
                        },
                    },
                    "notes": {
                        "type": "string",
                        "description": "Internal notes for the invoice",
                    },
                },
                "required": ["partner_name", "lines"],
            },
        ),

        types.Tool(
            name="odoo_get_customers",
            description="List customers (partners) from Odoo. Supports name search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Partial name to search (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 20,
                    },
                },
                "required": [],
            },
        ),

        types.Tool(
            name="odoo_get_products",
            description="List products/services from Odoo. Supports name search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Partial product name to search (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 20,
                    },
                },
                "required": [],
            },
        ),

        types.Tool(
            name="odoo_get_account_balance",
            description=(
                "Get the current balance of Odoo accounts. "
                "Optionally filter by account type: asset, liability, equity, income, expense."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "account_type": {
                        "type": "string",
                        "enum": ["asset", "liability", "equity", "income", "expense", "all"],
                        "default": "all",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Balance as of this date YYYY-MM-DD (optional, defaults to today)",
                    },
                },
                "required": [],
            },
        ),

        types.Tool(
            name="odoo_run_report",
            description=(
                "Generate a financial summary from Odoo and save it to Accounting/. "
                "Report types: trial_balance, income_summary, outstanding_invoices."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "report_type": {
                        "type": "string",
                        "enum": ["trial_balance", "income_summary", "outstanding_invoices"],
                        "default": "income_summary",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Start date YYYY-MM-DD (optional)",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "End date YYYY-MM-DD (defaults to today)",
                    },
                },
                "required": [],
            },
        ),

        types.Tool(
            name="log_action",
            description="Write a structured entry to today's vault log (Logs/YYYY-MM-DD.md).",
            inputSchema={
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": ["CREATE", "MOVE", "EDIT", "DELETE", "SKILL_RUN", "TRIAGE", "CLOSE", "ERROR"],
                    },
                    "source":      {"type": "string"},
                    "destination": {"type": "string", "default": "—"},
                    "outcome":     {"type": "string", "enum": ["success", "failed"], "default": "success"},
                    "notes":       {"type": "string"},
                },
                "required": ["action_type", "source", "notes"],
            },
        ),
    ]


# ── Tool implementations ──────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    # ── odoo_get_invoices ────────────────────────────────────────────
    if name == "odoo_get_invoices":
        move_type    = arguments.get("move_type", "out_invoice")
        state        = arguments.get("state", "all")
        partner_name = arguments.get("partner_name", "")
        date_from    = arguments.get("date_from", "")
        date_to      = arguments.get("date_to", "")
        limit        = min(int(arguments.get("limit", 20)), 50)

        domain = [("move_type", "=", move_type)]
        if state != "all":
            domain.append(("state", "=", state))
        if partner_name:
            domain.append(("partner_id.name", "ilike", partner_name))
        if date_from:
            domain.append(("invoice_date", ">=", date_from))
        if date_to:
            domain.append(("invoice_date", "<=", date_to))

        try:
            records = _search_read(
                "account.move", domain,
                ["name", "partner_id", "invoice_date", "invoice_date_due",
                 "amount_total", "amount_residual", "state", "currency_id"],
                limit=limit,
            )
        except Exception as exc:
            _write_vault_log("ERROR", "odoo:invoices", notes=str(exc), outcome="failed")
            return [types.TextContent(type="text", text=f"❌ Odoo error: {exc}")]

        if not records:
            return [types.TextContent(type="text", text="No invoices found matching the filters.")]

        type_label = {"out_invoice": "Customer Invoice", "in_invoice": "Vendor Bill",
                      "out_refund": "Credit Note", "in_refund": "Vendor Refund"}.get(move_type, move_type)
        lines = [f"**{type_label}s** ({len(records)} records)\n"]
        for r in records:
            partner = r["partner_id"][1] if r.get("partner_id") else "—"
            currency = r["currency_id"][1] if r.get("currency_id") else "USD"
            total    = _fmt_currency(r.get("amount_total", 0), currency)
            residual = _fmt_currency(r.get("amount_residual", 0), currency)
            lines.append(
                f"- **{r['name']}** | {partner} | {r.get('invoice_date', '—')} "
                f"| Total: {total} | Due: {residual} | State: `{r.get('state','?')}`"
            )

        _write_vault_log("SKILL_RUN", "odoo:get_invoices", notes=f"Listed {len(records)} {move_type}")
        return [types.TextContent(type="text", text="\n".join(lines))]

    # ── odoo_get_invoice_detail ──────────────────────────────────────
    elif name == "odoo_get_invoice_detail":
        invoice_id = arguments.get("invoice_id")
        inv_name   = arguments.get("name", "")

        if not invoice_id and not inv_name:
            return [types.TextContent(type="text", text="❌ Provide either invoice_id or name.")]

        try:
            if invoice_id:
                domain = [("id", "=", int(invoice_id))]
            else:
                domain = [("name", "=", inv_name)]

            records = _search_read(
                "account.move", domain,
                ["name", "partner_id", "invoice_date", "invoice_date_due",
                 "amount_untaxed", "amount_tax", "amount_total", "amount_residual",
                 "state", "narration", "invoice_line_ids", "currency_id"],
                limit=1,
            )
        except Exception as exc:
            return [types.TextContent(type="text", text=f"❌ Odoo error: {exc}")]

        if not records:
            return [types.TextContent(type="text", text="❌ Invoice not found.")]

        r        = records[0]
        currency = r["currency_id"][1] if r.get("currency_id") else "USD"
        partner  = r["partner_id"][1] if r.get("partner_id") else "—"

        # Fetch invoice lines
        line_ids = r.get("invoice_line_ids", [])
        lines_detail = ""
        if line_ids:
            try:
                inv_lines = _execute(
                    "account.move.line", "read",
                    [line_ids, ["name", "quantity", "price_unit", "price_subtotal"]],
                )
                lines_detail = "\n\n**Lines:**\n"
                for l in (inv_lines or []):
                    lines_detail += (
                        f"- {l.get('name','—')} | Qty: {l.get('quantity',0)} "
                        f"| Unit: {_fmt_currency(l.get('price_unit',0), currency)} "
                        f"| Subtotal: {_fmt_currency(l.get('price_subtotal',0), currency)}\n"
                    )
            except Exception:
                lines_detail = "\n\n_Could not load line details._"

        text = (
            f"## Invoice: {r['name']}\n\n"
            f"**Partner:** {partner}  \n"
            f"**Date:** {r.get('invoice_date', '—')}  \n"
            f"**Due:** {r.get('invoice_date_due', '—')}  \n"
            f"**State:** `{r.get('state', '?')}`  \n\n"
            f"| | Amount |\n|---|---|\n"
            f"| Subtotal | {_fmt_currency(r.get('amount_untaxed',0), currency)} |\n"
            f"| Tax      | {_fmt_currency(r.get('amount_tax',0), currency)} |\n"
            f"| **Total**| **{_fmt_currency(r.get('amount_total',0), currency)}** |\n"
            f"| **Due**  | **{_fmt_currency(r.get('amount_residual',0), currency)}** |\n"
            f"{lines_detail}"
            f"\n**Notes:** {r.get('narration') or '_None_'}"
        )
        return [types.TextContent(type="text", text=text)]

    # ── odoo_create_invoice ──────────────────────────────────────────
    elif name == "odoo_create_invoice":
        if DRY_RUN:
            return [types.TextContent(type="text", text="🔍 DRY_RUN — invoice NOT created in Odoo.")]

        partner_name  = arguments["partner_name"].strip()
        invoice_date  = arguments.get("invoice_date", datetime.now().strftime("%Y-%m-%d"))
        due_date      = arguments.get("due_date", "")
        lines_input   = arguments.get("lines", [])
        notes         = arguments.get("notes", "")

        # Find partner
        try:
            partners = _search_read(
                "res.partner", [("name", "ilike", partner_name)],
                ["id", "name"], limit=5,
            )
        except Exception as exc:
            return [types.TextContent(type="text", text=f"❌ Odoo error looking up partner: {exc}")]

        if not partners:
            return [types.TextContent(
                type="text",
                text=f"❌ No partner found matching '{partner_name}'. Create the customer in Odoo first.",
            )]

        partner_id = partners[0]["id"]
        partner_label = partners[0]["name"]

        # Build invoice lines (account.move.line vals)
        invoice_line_ids = []
        for li in lines_input:
            vals = {
                "name":       li.get("description", "Service"),
                "quantity":   float(li.get("quantity", 1)),
                "price_unit": float(li.get("price_unit", 0)),
            }
            invoice_line_ids.append((0, 0, vals))

        inv_vals: dict = {
            "move_type":      "out_invoice",
            "partner_id":     partner_id,
            "invoice_date":   invoice_date,
            "narration":      notes,
            "invoice_line_ids": invoice_line_ids,
        }
        if due_date:
            inv_vals["invoice_date_due"] = due_date

        try:
            inv_id = _execute("account.move", "create", [inv_vals])
        except Exception as exc:
            _write_vault_log("ERROR", "odoo:create_invoice", notes=str(exc), outcome="failed")
            return [types.TextContent(type="text", text=f"❌ Failed to create invoice in Odoo: {exc}")]

        total = sum(float(l.get("price_unit", 0)) * float(l.get("quantity", 1)) for l in lines_input)

        _write_vault_log(
            "CREATE", f"odoo:invoice:{inv_id}",
            notes=f"Draft invoice created for {partner_label} — total {total:.2f}",
        )

        return [types.TextContent(
            type="text",
            text=(
                f"✅ Draft invoice created in Odoo (ID: {inv_id})\n\n"
                f"**Partner:** {partner_label}  \n"
                f"**Date:** {invoice_date}  \n"
                f"**Lines:** {len(lines_input)} items  \n"
                f"**Estimated total:** {total:,.2f}\n\n"
                f"The invoice is in **DRAFT** state — it has NOT been posted/confirmed.\n"
                f"A human must review and post it in Odoo."
            ),
        )]

    # ── odoo_get_customers ───────────────────────────────────────────
    elif name == "odoo_get_customers":
        search = arguments.get("search", "")
        limit  = min(int(arguments.get("limit", 20)), 50)

        domain = [("is_company", "=", True)]
        if search:
            domain.append(("name", "ilike", search))

        try:
            records = _search_read(
                "res.partner", domain,
                ["name", "email", "phone", "city", "country_id"],
                limit=limit,
            )
        except Exception as exc:
            return [types.TextContent(type="text", text=f"❌ Odoo error: {exc}")]

        if not records:
            return [types.TextContent(type="text", text="No customers found.")]

        lines = [f"**Customers** ({len(records)} records)\n"]
        for r in records:
            country = r["country_id"][1] if r.get("country_id") else "—"
            lines.append(
                f"- **{r['name']}** | {r.get('email','—')} | {r.get('phone','—')} "
                f"| {r.get('city','—')}, {country}"
            )
        return [types.TextContent(type="text", text="\n".join(lines))]

    # ── odoo_get_products ────────────────────────────────────────────
    elif name == "odoo_get_products":
        search = arguments.get("search", "")
        limit  = min(int(arguments.get("limit", 20)), 50)

        domain = [("active", "=", True)]
        if search:
            domain.append(("name", "ilike", search))

        try:
            records = _search_read(
                "product.template", domain,
                ["name", "list_price", "type", "categ_id"],
                limit=limit,
            )
        except Exception as exc:
            return [types.TextContent(type="text", text=f"❌ Odoo error: {exc}")]

        if not records:
            return [types.TextContent(type="text", text="No products found.")]

        lines = [f"**Products** ({len(records)} records)\n"]
        for r in records:
            cat = r["categ_id"][1] if r.get("categ_id") else "—"
            lines.append(
                f"- **{r['name']}** | Type: {r.get('type','?')} "
                f"| Price: {_fmt_currency(r.get('list_price', 0))} | Category: {cat}"
            )
        return [types.TextContent(type="text", text="\n".join(lines))]

    # ── odoo_get_account_balance ─────────────────────────────────────
    elif name == "odoo_get_account_balance":
        account_type = arguments.get("account_type", "all")
        date_to      = arguments.get("date_to", datetime.now().strftime("%Y-%m-%d"))

        # Map friendly names to Odoo internal types
        type_map = {
            "asset":     ["asset_receivable", "asset_cash", "asset_current", "asset_non_current",
                          "asset_prepayments", "asset_fixed"],
            "liability": ["liability_payable", "liability_current", "liability_non_current"],
            "equity":    ["equity", "equity_unaffected"],
            "income":    ["income", "income_other"],
            "expense":   ["expense", "expense_depreciation", "expense_direct_cost"],
        }

        domain = [("deprecated", "=", False)]
        if account_type != "all":
            types_list = type_map.get(account_type, [account_type])
            domain.append(("account_type", "in", types_list))

        try:
            accounts = _search_read(
                "account.account", domain,
                ["code", "name", "account_type", "balance"],
                limit=100,
            )
        except Exception as exc:
            return [types.TextContent(type="text", text=f"❌ Odoo error: {exc}")]

        if not accounts:
            return [types.TextContent(type="text", text="No accounts found.")]

        total = sum(float(a.get("balance", 0)) for a in accounts)
        lines = [f"**Account Balances** (as of {date_to}) — {len(accounts)} accounts\n"]
        for a in sorted(accounts, key=lambda x: x.get("code", "")):
            bal = float(a.get("balance", 0))
            if abs(bal) < 0.01:
                continue
            lines.append(f"- `{a['code']}` {a['name']} | {a.get('account_type','?')} | **{bal:+,.2f}**")

        lines.append(f"\n**Total:** {total:+,.2f}")
        _write_vault_log("SKILL_RUN", "odoo:account_balance", notes=f"Balance report as of {date_to}")
        return [types.TextContent(type="text", text="\n".join(lines))]

    # ── odoo_run_report ──────────────────────────────────────────────
    elif name == "odoo_run_report":
        report_type = arguments.get("report_type", "income_summary")
        date_to     = arguments.get("date_to",   datetime.now().strftime("%Y-%m-%d"))
        date_from   = arguments.get("date_from", datetime.now().strftime("%Y-01-01"))

        ACCOUNTING_PATH.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")

        if report_type == "outstanding_invoices":
            try:
                records = _search_read(
                    "account.move",
                    [("move_type", "=", "out_invoice"), ("state", "=", "posted"),
                     ("payment_state", "in", ["not_paid", "partial"])],
                    ["name", "partner_id", "invoice_date_due", "amount_residual", "currency_id"],
                    limit=100,
                )
            except Exception as exc:
                return [types.TextContent(type="text", text=f"❌ Odoo error: {exc}")]

            total_outstanding = sum(float(r.get("amount_residual", 0)) for r in records)
            overdue = [r for r in records if r.get("invoice_date_due", "9999") < today]

            report_md = (
                f"---\ntitle: \"Outstanding Invoices Report — {today}\"\n"
                f"date: {today}\ntags: [accounting, odoo, report]\n---\n\n"
                f"# Outstanding Invoices Report\n\n"
                f"**Generated:** {today}  \n"
                f"**Total outstanding:** {total_outstanding:,.2f}  \n"
                f"**Overdue:** {len(overdue)} invoices\n\n"
                f"## Unpaid Invoices ({len(records)})\n\n"
            )
            for r in records:
                currency = r["currency_id"][1] if r.get("currency_id") else "USD"
                partner  = r["partner_id"][1] if r.get("partner_id") else "—"
                due      = r.get("invoice_date_due", "—")
                flag     = " ⚠️ OVERDUE" if due < today else ""
                report_md += (
                    f"- **{r['name']}** | {partner} | Due: {due}{flag} "
                    f"| Remaining: {_fmt_currency(r.get('amount_residual',0), currency)}\n"
                )

        elif report_type == "income_summary":
            try:
                income_accs = _search_read(
                    "account.account",
                    [("account_type", "in", ["income", "income_other"]), ("deprecated", "=", False)],
                    ["code", "name", "balance"], limit=50,
                )
                expense_accs = _search_read(
                    "account.account",
                    [("account_type", "in", ["expense", "expense_depreciation", "expense_direct_cost"]),
                     ("deprecated", "=", False)],
                    ["code", "name", "balance"], limit=50,
                )
            except Exception as exc:
                return [types.TextContent(type="text", text=f"❌ Odoo error: {exc}")]

            total_income  = sum(abs(float(a.get("balance", 0))) for a in income_accs)
            total_expense = sum(abs(float(a.get("balance", 0))) for a in expense_accs)
            net           = total_income - total_expense

            report_md = (
                f"---\ntitle: \"Income Summary — {today}\"\n"
                f"date: {today}\ntags: [accounting, odoo, income]\n---\n\n"
                f"# Income Summary\n\n"
                f"**Period:** {date_from} → {date_to}  \n"
                f"**Generated:** {today}\n\n"
                f"## Income Accounts\n\n"
            )
            for a in sorted(income_accs, key=lambda x: x.get("code", "")):
                report_md += f"- `{a['code']}` {a['name']} — {abs(float(a.get('balance',0))):,.2f}\n"
            report_md += f"\n**Total Income: {total_income:,.2f}**\n\n## Expense Accounts\n\n"
            for a in sorted(expense_accs, key=lambda x: x.get("code", "")):
                report_md += f"- `{a['code']}` {a['name']} — {abs(float(a.get('balance',0))):,.2f}\n"
            report_md += (
                f"\n**Total Expenses: {total_expense:,.2f}**\n\n"
                f"---\n\n## Net Profit / Loss\n\n"
                f"**Net: {net:+,.2f}** ({'Profit' if net >= 0 else 'Loss'})\n"
            )

        else:  # trial_balance
            try:
                accounts = _search_read(
                    "account.account",
                    [("deprecated", "=", False)],
                    ["code", "name", "account_type", "balance"], limit=200,
                )
            except Exception as exc:
                return [types.TextContent(type="text", text=f"❌ Odoo error: {exc}")]

            report_md = (
                f"---\ntitle: \"Trial Balance — {today}\"\n"
                f"date: {today}\ntags: [accounting, odoo, trial-balance]\n---\n\n"
                f"# Trial Balance\n\n"
                f"**As of:** {date_to}  \n"
                f"**Generated:** {today}\n\n"
                f"| Code | Account | Type | Balance |\n|---|---|---|---|\n"
            )
            total_debit = total_credit = 0.0
            for a in sorted(accounts, key=lambda x: x.get("code", "")):
                bal = float(a.get("balance", 0))
                if bal > 0:
                    total_debit += bal
                else:
                    total_credit += abs(bal)
                report_md += f"| `{a['code']}` | {a['name']} | {a.get('account_type','?')} | {bal:+,.2f} |\n"
            report_md += f"\n**Total Debit: {total_debit:,.2f}** | **Total Credit: {total_credit:,.2f}**\n"

        # Save report to Accounting/
        filename = f"{today} — {report_type.replace('_', '-')}.md"
        out_path = ACCOUNTING_PATH / filename
        if DRY_RUN:
            return [types.TextContent(type="text", text=f"🔍 DRY_RUN — report NOT saved.\n\n{report_md}")]

        out_path.write_text(report_md, encoding="utf-8")
        _write_vault_log(
            "CREATE", f"odoo:{report_type}",
            f"Accounting/{filename}",
            notes=f"Odoo {report_type} report generated",
        )
        return [types.TextContent(
            type="text",
            text=(
                f"✅ Report saved: `Accounting/{filename}`\n\n"
                f"---\n\n{report_md}"
            ),
        )]

    # ── log_action ───────────────────────────────────────────────────
    elif name == "log_action":
        _write_vault_log(
            action_type=arguments["action_type"],
            source=arguments["source"],
            destination=arguments.get("destination", "—"),
            outcome=arguments.get("outcome", "success"),
            notes=arguments.get("notes", ""),
        )
        return [types.TextContent(type="text", text="✅ Log entry written.")]

    return [types.TextContent(type="text", text=f"❌ Unknown tool: {name}")]


# ── Entry point ───────────────────────────────────────────────────────

async def main() -> None:
    LOGS_PATH.mkdir(parents=True, exist_ok=True)
    ACCOUNTING_PATH.mkdir(parents=True, exist_ok=True)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
