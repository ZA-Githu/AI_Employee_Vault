---
name: odoo-accounting
tier: gold
description: >
  Odoo Community accounting skill. Query invoices, customers, products,
  account balances, and generate financial reports. Create draft invoices
  (never auto-post — human approval required).
mcp_server: odoo
tools:
  - odoo_get_invoices
  - odoo_get_invoice_detail
  - odoo_create_invoice
  - odoo_get_customers
  - odoo_get_products
  - odoo_get_account_balance
  - odoo_run_report
  - log_action
---

# Skill: Odoo Accounting

## Purpose

Connect Claude to a self-hosted **Odoo 19+** instance via JSON-RPC.
Enables the AI Employee Vault to read and draft accounting data without
giving the AI the ability to confirm/post anything without human approval.

## Tools Available

| Tool | What it does |
|------|-------------|
| `odoo_get_invoices` | List customer invoices or vendor bills with filters |
| `odoo_get_invoice_detail` | Get full detail of one invoice by ID or number |
| `odoo_create_invoice` | Create a **DRAFT** invoice (never auto-posted) |
| `odoo_get_customers` | Search/list Odoo partners |
| `odoo_get_products` | Search/list Odoo products/services |
| `odoo_get_account_balance` | Get balances by account type |
| `odoo_run_report` | Generate and save a financial report to `Accounting/` |
| `log_action` | Append a structured entry to today's vault log |

## Safety Rules

1. **odoo_create_invoice** always creates a DRAFT — never posts.
2. A human must log in to Odoo and click **Confirm** to post an invoice.
3. Always log every Odoo operation via `log_action` or the MCP server's
   built-in auto-logging.
4. Never expose Odoo credentials in vault notes or logs.

## Report Types

| Report | Description |
|--------|-------------|
| `income_summary` | Income vs. expense totals from Odoo accounts |
| `outstanding_invoices` | Unpaid customer invoices, with overdue flags |
| `trial_balance` | All account codes with current debit/credit balances |

Reports are saved to `Accounting/YYYY-MM-DD — <report-type>.md`.

## Environment Variables (watcher/.env or MCP env block)

```
ODOO_URL=http://localhost:8069
ODOO_DB=odoo
ODOO_USERNAME=admin
ODOO_PASSWORD=your-secure-password
```

## Setup Checklist

- [ ] Install Odoo 19 Community (Docker or native)
- [ ] Create a dedicated API user in Odoo with Accounting access
- [ ] Add credentials to `watcher/.env`
- [ ] Add `odoo` to `mcp.json` (already done if this vault is set up)
- [ ] Run `python watcher/odoo_mcp.py` to test connectivity

## Weekly Audit Integration

The `weekly_audit.py` script's **Section 3 — Accounting** reads from
`Accounting/*.md` files. After running `odoo_run_report`, the CEO Briefing
will automatically include the Odoo financial summary.

## Example Prompts

```
List all unpaid customer invoices
Show me outstanding invoices overdue more than 30 days
Generate an income summary for this month
What is the current account balance for expense accounts?
Create a draft invoice for Acme Corp — 5 hours consulting at $150/hr
Get details on invoice INV/2026/0001
```

## Error Recovery

| Error | Recovery |
|-------|----------|
| Cannot reach Odoo | Check ODOO_URL, ensure Odoo is running, check firewall |
| Authentication failed | Verify ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD |
| Partner not found | Create the customer in Odoo first |
| JSON-RPC error | Check Odoo logs at Settings → Technical → Logging |
