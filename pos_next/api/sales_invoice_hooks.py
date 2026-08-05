# Copyright (c) 2025, BrainWise and contributors
# For license information, please see license.txt

"""
Sales Invoice Hooks
Event handlers for Sales Invoice document events
"""

import frappe
from frappe import _
from frappe.utils import flt


def validate(doc, method=None):
	"""
	Validate hook for Sales Invoice.
	Apply tax inclusive settings based on POS Profile configuration.

	Args:
		doc: Sales Invoice document
		method: Hook method name (unused)
	"""
	set_sales_return_income_account(doc)
	set_sales_tax_liability_account(doc)
	apply_tax_inclusive(doc)
	route_return_income_to_sales_return(doc)


def route_return_income_to_sales_return(doc):
	"""
	For return invoices (is_return=1), route each item's income_account to the
	company's dedicated Sales Return account, so returns accumulate in Sales
	Return instead of debiting the regular Sales income account.

	The target account is read from the Company custom field
	`custom_default_sales_return_account`. If that field is empty for the
	company, this function does nothing (safe no-op) — so companies without a
	Sales Return account keep standard ERPNext behaviour.

	Runs in `validate`, after ERPNext has already populated each item's
	income_account, so we simply override it for returns.

	Args:
		doc: Sales Invoice document
	"""
	if not cint(doc.get("is_return")):
		return

	sales_return_account = frappe.db.get_value(
		"Company", doc.company, "custom_default_sales_return_account"
	)
	if not sales_return_account:
		# Not configured for this company -> keep standard behaviour.
		return

	for item in doc.get("items", []):
		if item.income_account != sales_return_account:
			item.income_account = sales_return_account


def purchase_invoice_validate(doc, method=None):
	"""Validate hook for Purchase Invoice."""
	set_sales_tax_liability_account(doc)


def set_sales_tax_liability_account(doc):
	"""Route tax rows to one GSPT VAT Payable account."""
	if doc.doctype not in ("Sales Invoice", "Purchase Invoice") or not doc.get("company"):
		return

	company_abbr = frappe.get_cached_value("Company", doc.company, "abbr")
	if company_abbr != "GSPT":
		return

	tax_account = get_sales_tax_liability_account(doc.company)
	if not tax_account:
		return

	for tax in doc.get("taxes", []):
		if tax.get("account_head") and flt(tax.get("rate")):
			tax.account_head = tax_account


def get_vat_component_account(company, doctype=None, is_return=False):
	ensure_vat_breakdown_accounts(company)

	if doctype == "Purchase Invoice":
		return "Purchase VAT - GSPT"
	if doctype == "Sales Invoice" and is_return:
		return "Return VAT - GSPT"
	return "Sales VAT - GSPT"


def set_sales_return_income_account(doc):
	"""Route sales return rows to the company's Sales Return account when it exists."""
	if not doc.get("is_return") or not doc.get("company"):
		return

	sales_return_account = get_sales_return_account(doc.company)
	if not sales_return_account:
		return

	for item in doc.get("items", []):
		if item.get("income_account") != sales_return_account:
			item.income_account = sales_return_account


def get_sales_return_account(company):
	company_abbr = frappe.get_cached_value("Company", company, "abbr")
	if not company_abbr:
		return None

	account = f"Sales Return - {company_abbr}"
	if frappe.db.exists(
		"Account",
		{
			"name": account,
			"company": company,
			"root_type": "Income",
			"is_group": 0,
			"disabled": 0,
		},
	):
		return account

	return frappe.db.get_value(
		"Account",
		{
			"account_name": "Sales Return",
			"company": company,
			"root_type": "Income",
			"is_group": 0,
			"disabled": 0,
		},
		"name",
	)


@frappe.whitelist()
def repair_submitted_sales_returns(company=None, from_date=None, to_date=None):
	"""Move submitted return invoice item rows to Sales Return and repost their GL entries."""
	filters = {"docstatus": 1, "is_return": 1}
	if company:
		filters["company"] = company
	if from_date:
		filters["posting_date"] = [">=", from_date]
	if to_date:
		filters["posting_date"] = ["between", [from_date or "1900-01-01", to_date]]

	invoices = frappe.get_all("Sales Invoice", filters=filters, pluck="name")
	repaired = []

	for invoice_name in invoices:
		doc = frappe.get_doc("Sales Invoice", invoice_name)
		sales_return_account = get_sales_return_account(doc.company)
		if not sales_return_account:
			continue

		changed = False
		for item in doc.get("items", []):
			if item.income_account != sales_return_account:
				frappe.db.set_value(
					"Sales Invoice Item",
					item.name,
					"income_account",
					sales_return_account,
					update_modified=False,
				)
				item.income_account = sales_return_account
				changed = True

		if changed:
			doc.make_gl_entries()
			repaired.append(invoice_name)

	return {"checked": len(invoices), "repaired": len(repaired), "invoices": repaired}


@frappe.whitelist()
def get_sales_return_status(company=None):
	"""Return posted Sales/Sales Return balances for quick verification."""
	filters = {"docstatus": 1, "is_return": 1}
	if company:
		filters["company"] = company

	companies = [company] if company else frappe.get_all("Company", pluck="name")
	status = {}
	for company_name in companies:
		sales_return_account = get_sales_return_account(company_name)
		if not sales_return_account:
			continue

		company_abbr = frappe.get_cached_value("Company", company_name, "abbr")
		sales_account = f"Sales - {company_abbr}"
		accounts = [sales_account, sales_return_account]
		gl_balances = frappe.db.sql(
			"""
			select account, sum(debit) as debit, sum(credit) as credit,
				sum(debit - credit) as net_debit, sum(credit - debit) as net_credit
			from `tabGL Entry`
			where is_cancelled = 0 and account in %(accounts)s
			group by account
			""",
			{"accounts": accounts},
			as_dict=True,
		)
		return_total = frappe.db.get_value(
			"Sales Invoice",
			filters,
			"sum(grand_total)",
		)
		return_net_total = frappe.db.get_value(
			"Sales Invoice",
			filters,
			"sum(net_total)",
		)
		return_tax_total = frappe.db.get_value(
			"Sales Invoice",
			filters,
			"sum(total_taxes_and_charges)",
		)
		status[company_name] = {
			"sales_account": sales_account,
			"sales_return_account": sales_return_account,
			"return_invoice_grand_total": return_total,
			"return_invoice_net_total": return_net_total,
			"return_invoice_tax_total": return_tax_total,
			"gl_balances": gl_balances,
		}

	return status


@frappe.whitelist()
def get_return_gl_accounts(company=None):
	"""Show where submitted Sales Return amounts are posted in GL."""
	conditions = ["si.docstatus = 1", "si.is_return = 1", "gle.is_cancelled = 0"]
	values = {}
	if company:
		conditions.append("si.company = %(company)s")
		values["company"] = company

	return frappe.db.sql(
		f"""
		select
			gle.account,
			sum(gle.debit) as debit,
			sum(gle.credit) as credit,
			sum(gle.debit - gle.credit) as net_debit
		from `tabGL Entry` gle
		inner join `tabSales Invoice` si on si.name = gle.voucher_no
		where {" and ".join(conditions)}
			and gle.voucher_type = 'Sales Invoice'
		group by gle.account
		order by abs(sum(gle.debit - gle.credit)) desc
		""",
		values,
		as_dict=True,
	)


@frappe.whitelist()
def get_return_gl_by_voucher(limit=10):
	"""Show submitted return GL grouped by invoice for troubleshooting."""
	return frappe.db.sql(
		"""
		select
			gle.voucher_no,
			count(*) as rows_count,
			sum(gle.debit) as debit,
			sum(gle.credit) as credit,
			sum(gle.debit - gle.credit) as difference
		from `tabGL Entry` gle
		inner join `tabSales Invoice` si on si.name = gle.voucher_no
		where si.docstatus = 1
			and si.is_return = 1
			and gle.is_cancelled = 0
			and gle.voucher_type = 'Sales Invoice'
		group by gle.voucher_no
		order by gle.voucher_no desc
		limit %(limit)s
		""",
		{"limit": int(limit)},
		as_dict=True,
	)


@frappe.whitelist()
def get_return_gl_entries(voucher_no="SI-GSPT-9931"):
	"""Show GL rows for a return invoice."""
	return frappe.db.get_all(
		"GL Entry",
		filters={"voucher_type": "Sales Invoice", "voucher_no": voucher_no, "is_cancelled": 0},
		fields=["name", "creation", "account", "debit", "credit", "remarks"],
		order_by="creation asc, name asc",
	)


@frappe.whitelist()
def cleanup_sales_return_repair_duplicates(company=None):
	"""Remove duplicate GL rows created by the repair and move original income rows."""
	filters = {"docstatus": 1, "is_return": 1}
	if company:
		filters["company"] = company

	invoices = frappe.get_all("Sales Invoice", filters=filters, fields=["name", "company"])
	deleted = 0
	updated = 0

	for invoice in invoices:
		sales_return_account = get_sales_return_account(invoice.company)
		company_abbr = frappe.get_cached_value("Company", invoice.company, "abbr")
		sales_account = f"Sales - {company_abbr}"
		if not sales_return_account:
			continue

		duplicate_rows = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Sales Invoice",
				"voucher_no": invoice.name,
				"is_cancelled": 0,
				"creation": [">=", "2026-07-29 09:00:00"],
			},
			pluck="name",
		)
		for gle_name in duplicate_rows:
			frappe.db.delete("GL Entry", {"name": gle_name})
			deleted += 1

		frappe.db.sql(
			"""
			update `tabGL Entry`
			set account = %(sales_return_account)s
			where voucher_type = 'Sales Invoice'
				and voucher_no = %(voucher_no)s
				and is_cancelled = 0
				and account = %(sales_account)s
			""",
			{
				"sales_return_account": sales_return_account,
				"voucher_no": invoice.name,
				"sales_account": sales_account,
			},
		)
		updated += 1

	frappe.db.commit()
	return {"invoices": len(invoices), "deleted_duplicate_gl_rows": deleted, "updated_gl_rows": updated}


def get_gspt_company():
	return frappe.db.get_value("Company", {"abbr": "GSPT"}, "name")


def get_sales_tax_liability_account(company=None):
	company = company or get_gspt_company()
	if not company:
		return None

	company_abbr = frappe.get_cached_value("Company", company, "abbr")
	account = f"VAT Payable - {company_abbr}"
	if frappe.db.exists("Account", account):
		if not frappe.db.get_value("Account", account, "is_group"):
			frappe.db.set_value("Account", account, {"disabled": 0})
		return account

	old_summary = f"VAT Payable Summary - {company_abbr}"
	if frappe.db.exists("Account", old_summary):
		return old_summary

	old_payable = f"Sales Tax Payable - {company_abbr}"
	if frappe.db.exists("Account", old_payable):
		return old_payable

	old_account = f"Sales Tax Liability - {company_abbr}"
	if frappe.db.exists("Account", old_account):
		return old_account

	parent_account = f"Duties and Taxes - {company_abbr}"
	if not frappe.db.exists("Account", parent_account):
		parent_account = frappe.db.get_value(
			"Account",
			{"company": company, "account_name": "Duties and Taxes", "is_group": 1},
			"name",
		)

	if not parent_account:
		frappe.throw(_("Duties and Taxes account not found for {0}").format(company))

	account_doc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": "VAT Payable",
			"parent_account": parent_account,
			"company": company,
			"root_type": "Liability",
			"report_type": "Balance Sheet",
			"account_type": "Tax",
			"is_group": 0,
		}
	)
	account_doc.insert(ignore_permissions=True)
	return account_doc.name


def ensure_vat_breakdown_accounts(company=None):
	company = company or get_gspt_company()
	company_abbr = frappe.get_cached_value("Company", company, "abbr")
	parent_account = get_sales_tax_liability_account(company)
	accounts = [
		("Sales VAT", f"Sales VAT - {company_abbr}"),
		("Purchase VAT", f"Purchase VAT - {company_abbr}"),
		("Return VAT", f"Return VAT - {company_abbr}"),
	]

	for account_name, account in accounts:
		if frappe.db.exists("Account", account):
			if frappe.db.get_value("Account", account, "parent_account") != parent_account:
				frappe.db.set_value("Account", account, "parent_account", parent_account)
				frappe.get_doc("Account", account).save(ignore_permissions=True)
			continue

		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": account_name,
				"parent_account": parent_account,
				"company": company,
				"root_type": "Liability",
				"report_type": "Balance Sheet",
				"account_type": "Tax",
				"is_group": 0,
			}
		).insert(ignore_permissions=True)


@frappe.whitelist()
def get_tax_account_setup_status():
	"""Show current tax accounts and templates for GSPT."""
	company = get_gspt_company()
	accounts = frappe.get_all(
		"Account",
		filters={"company": company},
		or_filters=[
			["account_name", "like", "%Tax%"],
			["parent_account", "like", "%Duties and Taxes%"],
		],
		fields=["name", "account_name", "parent_account", "root_type", "account_type", "is_group", "disabled"],
		order_by="lft asc",
		limit_page_length=500,
	)
	sales_taxes = frappe.get_all(
		"Sales Taxes and Charges",
		fields=["parent", "account_head", "rate", "charge_type"],
		limit_page_length=500,
	)
	purchase_taxes = frappe.get_all(
		"Purchase Taxes and Charges",
		fields=["parent", "account_head", "rate", "charge_type"],
		limit_page_length=500,
	)
	return {"company": company, "accounts": accounts, "sales_taxes": sales_taxes, "purchase_taxes": purchase_taxes}


@frappe.whitelist()
def move_all_tax_to_sales_tax_liability():
	"""Move GSPT sales/purchase tax configuration and GL rows to one payable account."""
	company = get_gspt_company()
	tax_account = get_sales_tax_liability_account(company)
	old_sales_tax_accounts = ["Tax Deduction - GSPT", "VAT Payable - GSPT", "Accrued Tax - GSPT"]
	old_purchase_tax_accounts = ["Expenses Included In Valuation - GSPT"]
	old_tax_accounts = old_sales_tax_accounts + old_purchase_tax_accounts

	updates = {}

	updates["sales_tax_rows"] = frappe.db.sql(
		"""
		update `tabSales Taxes and Charges`
		set account_head = %(tax_account)s
		where account_head in %(old_accounts)s
			and ifnull(rate, 0) != 0
		""",
		{"tax_account": tax_account, "old_accounts": old_tax_accounts},
	)

	updates["purchase_tax_rows"] = frappe.db.sql(
		"""
		update `tabPurchase Taxes and Charges`
		set account_head = %(tax_account)s
		where account_head in %(old_accounts)s
			and ifnull(rate, 0) != 0
		""",
		{"tax_account": tax_account, "old_accounts": old_tax_accounts},
	)

	updates["sales_invoice_gl"] = frappe.db.sql(
		"""
		update `tabGL Entry` gle
		inner join `tabSales Invoice` si on si.name = gle.voucher_no
		set gle.account = %(tax_account)s
		where gle.voucher_type = 'Sales Invoice'
			and si.company = %(company)s
			and gle.account in %(old_accounts)s
			and gle.is_cancelled = 0
		""",
		{"tax_account": tax_account, "company": company, "old_accounts": old_tax_accounts},
	)

	updates["purchase_invoice_gl"] = frappe.db.sql(
		"""
		update `tabGL Entry` gle
		inner join `tabPurchase Invoice` pi on pi.name = gle.voucher_no
		set gle.account = %(tax_account)s
		where gle.voucher_type = 'Purchase Invoice'
			and pi.company = %(company)s
			and gle.account in %(old_accounts)s
			and gle.is_cancelled = 0
		""",
		{"tax_account": tax_account, "company": company, "old_accounts": old_tax_accounts},
	)

	frappe.db.commit()
	return {"company": company, "tax_account": tax_account, "updates": updates}


@frappe.whitelist()
def get_sales_tax_liability_summary():
	company = get_gspt_company()
	tax_account = get_sales_tax_liability_account(company)
	accounts = [
		tax_account,
		"Tax Deduction - GSPT",
		"VAT Payable - GSPT",
		"Accrued Tax - GSPT",
		"Expenses Included In Valuation - GSPT",
	]
	return frappe.db.sql(
		"""
		select account, voucher_type, sum(debit) as debit, sum(credit) as credit,
			sum(credit - debit) as net_credit
		from `tabGL Entry`
		where is_cancelled = 0
			and account in %(accounts)s
		group by account, voucher_type
		order by account, voucher_type
		""",
		{"accounts": accounts},
		as_dict=True,
	)


@frappe.whitelist()
def rename_sales_tax_liability_to_payable():
	"""Rename the common tax account to a clearer user-facing name."""
	company = get_gspt_company()
	company_abbr = frappe.get_cached_value("Company", company, "abbr")
	old_account = f"Sales Tax Payable - {company_abbr}"
	new_account = f"VAT Payable Summary - {company_abbr}"

	if frappe.db.exists("Account", new_account):
		tax_account = new_account
	elif frappe.db.exists("Account", old_account):
		tax_account = frappe.rename_doc("Account", old_account, new_account, force=True)
		frappe.db.set_value("Account", tax_account, "account_name", "VAT Payable Summary")
		frappe.db.set_value("Account", tax_account, "is_group", 1)
	else:
		tax_account = get_sales_tax_liability_account(company)

	frappe.db.commit()
	return {"company": company, "tax_account": tax_account}


@frappe.whitelist()
def split_vat_into_readable_accounts():
	"""Split existing GSPT VAT postings into Sales, Purchase, and Return VAT accounts."""
	company = get_gspt_company()
	rename_sales_tax_liability_to_payable()
	ensure_vat_breakdown_accounts(company)

	summary_account = get_sales_tax_liability_account(company)
	sales_vat = get_vat_component_account(company, "Sales Invoice", False)
	purchase_vat = get_vat_component_account(company, "Purchase Invoice", False)
	return_vat = get_vat_component_account(company, "Sales Invoice", True)
	old_tax_accounts = (
		summary_account,
		"Sales Tax Liability - GSPT",
		"Sales Tax Payable - GSPT",
		"Tax Deduction - GSPT",
		"VAT Payable - GSPT",
		"Accrued Tax - GSPT",
		"Expenses Included In Valuation - GSPT",
	)

	frappe.db.sql(
		"""
		update `tabSales Taxes and Charges` stc
		inner join `tabSales Invoice` si on si.name = stc.parent
		set stc.account_head = case when si.is_return = 1 then %(return_vat)s else %(sales_vat)s end
		where si.company = %(company)s
			and stc.account_head in %(old_tax_accounts)s
			and ifnull(stc.rate, 0) != 0
		""",
		{
			"return_vat": return_vat,
			"sales_vat": sales_vat,
			"company": company,
			"old_tax_accounts": old_tax_accounts,
		},
	)
	frappe.db.sql(
		"""
		update `tabSales Taxes and Charges`
		set account_head = %(sales_vat)s
		where parenttype = 'Sales Taxes and Charges Template'
			and account_head in %(old_tax_accounts)s
			and ifnull(rate, 0) != 0
		""",
		{"sales_vat": sales_vat, "old_tax_accounts": old_tax_accounts},
	)
	frappe.db.sql(
		"""
		update `tabPurchase Taxes and Charges`
		set account_head = %(purchase_vat)s
		where account_head in %(old_tax_accounts)s
			and ifnull(rate, 0) != 0
		""",
		{"purchase_vat": purchase_vat, "old_tax_accounts": old_tax_accounts},
	)
	frappe.db.sql(
		"""
		update `tabGL Entry` gle
		inner join `tabSales Invoice` si on si.name = gle.voucher_no
		set gle.account = case when si.is_return = 1 then %(return_vat)s else %(sales_vat)s end
		where gle.voucher_type = 'Sales Invoice'
			and si.company = %(company)s
			and gle.account in %(old_tax_accounts)s
			and gle.is_cancelled = 0
		""",
		{
			"return_vat": return_vat,
			"sales_vat": sales_vat,
			"company": company,
			"old_tax_accounts": old_tax_accounts,
		},
	)
	frappe.db.sql(
		"""
		update `tabGL Entry` gle
		inner join `tabPurchase Invoice` pi on pi.name = gle.voucher_no
		set gle.account = %(purchase_vat)s
		where gle.voucher_type = 'Purchase Invoice'
			and pi.company = %(company)s
			and gle.account in %(old_tax_accounts)s
			and gle.is_cancelled = 0
		""",
		{"purchase_vat": purchase_vat, "company": company, "old_tax_accounts": old_tax_accounts},
	)

	frappe.db.commit()
	return get_vat_breakdown_summary()


@frappe.whitelist()
def flatten_vat_accounts_under_duties_and_taxes():
	"""Show VAT components directly under Duties and Taxes and hide unused old tax heads."""
	company = get_gspt_company()
	company_abbr = frappe.get_cached_value("Company", company, "abbr")
	parent_account = f"Duties and Taxes - {company_abbr}"
	ensure_vat_breakdown_accounts(company)

	visible_accounts = (
		f"Sales VAT - {company_abbr}",
		f"Purchase VAT - {company_abbr}",
		f"Return VAT - {company_abbr}",
	)
	for account in visible_accounts:
		frappe.db.set_value("Account", account, {"parent_account": parent_account, "disabled": 0})
		frappe.get_doc("Account", account).save(ignore_permissions=True)

	accounts_to_hide = (
		f"VAT Payable Summary - {company_abbr}",
		f"Sales Tax Payable - {company_abbr}",
		f"Sales Tax Liability - {company_abbr}",
		f"VAT Payable - {company_abbr}",
		f"Accrued Tax - {company_abbr}",
	)
	hidden = []
	not_hidden = []
	for account in accounts_to_hide:
		if not frappe.db.exists("Account", account):
			continue
		balance = frappe.db.sql(
			"""
			select sum(debit - credit)
			from `tabGL Entry`
			where is_cancelled = 0 and account = %(account)s
			""",
			{"account": account},
		)[0][0] or 0
		child_count = frappe.db.count("Account", {"parent_account": account, "disabled": 0})
		if not balance and not child_count:
			frappe.db.set_value("Account", account, "disabled", 1)
			hidden.append(account)
		else:
			not_hidden.append({"account": account, "balance": balance, "child_count": child_count})

	frappe.db.commit()
	return {
		"parent_account": parent_account,
		"visible_accounts": visible_accounts,
		"hidden_accounts": hidden,
		"not_hidden": not_hidden,
		"summary": get_vat_breakdown_summary(),
	}


@frappe.whitelist()
def group_vat_accounts_under_vat_payable():
	"""Show Sales/Purchase/Return VAT inside one VAT Payable folder."""
	company = get_gspt_company()
	company_abbr = frappe.get_cached_value("Company", company, "abbr")
	duties_account = f"Duties and Taxes - {company_abbr}"
	vat_payable = f"VAT Payable - {company_abbr}"

	if not frappe.db.exists("Account", vat_payable):
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": "VAT Payable",
				"parent_account": duties_account,
				"company": company,
				"root_type": "Liability",
				"report_type": "Balance Sheet",
				"account_type": "Tax",
				"is_group": 1,
			}
		).insert(ignore_permissions=True)
	else:
		frappe.db.set_value(
			"Account",
			vat_payable,
			{"account_name": "VAT Payable", "parent_account": duties_account, "is_group": 1, "disabled": 0},
		)

	for account in ("Sales VAT - GSPT", "Purchase VAT - GSPT", "Return VAT - GSPT"):
		if frappe.db.exists("Account", account):
			frappe.db.set_value("Account", account, {"parent_account": vat_payable, "disabled": 0})
			frappe.get_doc("Account", account).save(ignore_permissions=True)

	for account in ("VAT Payable Summary - GSPT", "Sales Tax Payable - GSPT", "Sales Tax Liability - GSPT", "Accrued Tax - GSPT"):
		if frappe.db.exists("Account", account):
			frappe.db.set_value("Account", account, "disabled", 1)

	frappe.db.commit()
	return {"vat_payable": vat_payable, "children": get_vat_breakdown_summary()}


@frappe.whitelist()
def make_single_vat_payable_account():
	"""Move all VAT entries into one VAT Payable account and hide component accounts."""
	company = get_gspt_company()
	company_abbr = frappe.get_cached_value("Company", company, "abbr")
	duties_account = f"Duties and Taxes - {company_abbr}"
	vat_payable = f"VAT Payable - {company_abbr}"
	component_accounts = (
		f"Sales VAT - {company_abbr}",
		f"Purchase VAT - {company_abbr}",
		f"Return VAT - {company_abbr}",
		f"VAT Payable Summary - {company_abbr}",
		f"Sales Tax Payable - {company_abbr}",
		f"Sales Tax Liability - {company_abbr}",
		f"Tax Deduction - {company_abbr}",
		f"Accrued Tax - {company_abbr}",
	)

	if not frappe.db.exists("Account", vat_payable):
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": "VAT Payable",
				"parent_account": duties_account,
				"company": company,
				"root_type": "Liability",
				"report_type": "Balance Sheet",
				"account_type": "Tax",
				"is_group": 0,
			}
		).insert(ignore_permissions=True)

	for account in component_accounts:
		if not frappe.db.exists("Account", account) or account == vat_payable:
			continue
		frappe.db.sql(
			"""
			update `tabGL Entry`
			set account = %(vat_payable)s
			where account = %(account)s
			""",
			{"vat_payable": vat_payable, "account": account},
		)
		frappe.db.sql(
			"""
			update `tabSales Taxes and Charges`
			set account_head = %(vat_payable)s
			where account_head = %(account)s
			""",
			{"vat_payable": vat_payable, "account": account},
		)
		frappe.db.sql(
			"""
			update `tabPurchase Taxes and Charges`
			set account_head = %(vat_payable)s
			where account_head = %(account)s
			""",
			{"vat_payable": vat_payable, "account": account},
		)

	for account in (f"Sales VAT - {company_abbr}", f"Purchase VAT - {company_abbr}", f"Return VAT - {company_abbr}"):
		if frappe.db.exists("Account", account):
			frappe.db.set_value("Account", account, "disabled", 1)

	frappe.db.set_value(
		"Account",
		vat_payable,
		{"account_name": "VAT Payable", "parent_account": duties_account, "is_group": 0, "disabled": 0},
	)
	frappe.db.commit()
	return get_single_vat_payable_summary()


@frappe.whitelist()
def get_single_vat_payable_summary():
	return frappe.db.sql(
		"""
		select account, sum(debit) as debit, sum(credit) as credit, sum(credit - debit) as net_credit
		from `tabGL Entry`
		where is_cancelled = 0 and account = 'VAT Payable - GSPT'
		group by account
		""",
		as_dict=True,
	)


@frappe.whitelist()
def get_vat_breakdown_summary():
	accounts = ("Sales VAT - GSPT", "Purchase VAT - GSPT", "Return VAT - GSPT")
	rows = frappe.db.sql(
		"""
		select account, sum(debit) as debit, sum(credit) as credit, sum(credit - debit) as net_credit
		from `tabGL Entry`
		where is_cancelled = 0 and account in %(accounts)s
		group by account
		order by field(account, 'Sales VAT - GSPT', 'Purchase VAT - GSPT', 'Return VAT - GSPT')
		""",
		{"accounts": accounts},
		as_dict=True,
	)
	final_amount = sum((row.net_credit or 0) for row in rows)
	return {"rows": rows, "final_vat_payable_credit": final_amount}


def apply_tax_inclusive(doc):
	"""
	Mark taxes as inclusive based on POS Profile setting.

	This function reads the tax_inclusive setting from POS Settings
	and applies it to all taxes in the invoice (except Actual charge type).

	Args:
		doc: Sales Invoice document
	"""
	if not doc.pos_profile:
		return

	try:
		# Get POS Settings for this profile
		pos_settings = frappe.db.get_value(
			"POS Settings",
			{"pos_profile": doc.pos_profile},
			["tax_inclusive"],
			as_dict=True
		)
		tax_inclusive = pos_settings.get("tax_inclusive", 0) if pos_settings else 0
	except Exception:
		tax_inclusive = 0

	has_changes = False
	for tax in doc.get("taxes", []):
		# Skip Actual charge type - these can't be inclusive
		if tax.charge_type == "Actual":
			if tax.included_in_print_rate:
				tax.included_in_print_rate = 0
				has_changes = True
			continue

		# Apply tax inclusive setting
		if tax_inclusive and not tax.included_in_print_rate:
			tax.included_in_print_rate = 1
			has_changes = True
		elif not tax_inclusive and tax.included_in_print_rate:
			tax.included_in_print_rate = 0
			has_changes = True

	# Recalculate if we made changes
	if has_changes:
		doc.calculate_taxes_and_totals()


def before_cancel(doc, method=None):
	"""
	Before Cancel hook for Sales Invoice.
	Cancel any credit redemption journal entries.

	Args:
		doc: Sales Invoice document
		method: Hook method name (unused)
	"""
	try:
		from pos_next.api.credit_sales import cancel_credit_journal_entries
		cancel_credit_journal_entries(doc.name)
	except Exception as e:
		frappe.log_error(
			title="Credit Sale JE Cancellation Error",
			message=f"Invoice: {doc.name}, Error: {str(e)}\n{frappe.get_traceback()}"
		)
		# Don't block invoice cancellation if JE cancellation fails
		frappe.msgprint(
			_("Warning: Some credit journal entries may not have been cancelled. Please check manually."),
			alert=True,
			indicator="orange"
		)
