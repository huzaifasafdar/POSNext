# -*- coding: utf-8 -*-
# Copyright (c) 2024, POS Next and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _


def validate_item(doc, method):
	"""
	Validate Item doctype
	- Allow items with or without company
	- Items without company are treated as global items (available to all companies)
	- Explicitly set custom_company to empty string for new global items
	"""
	# Only set custom_company for new items, don't modify existing items
	if doc.is_new():
		if not doc.get("custom_company"):
			doc.custom_company = ""

	ensure_item_code_barcode(doc)


def ensure_item_code_barcode(doc):
	"""Allow core purchase/sales barcode scan fields to resolve the item code."""
	barcode = (doc.get("item_code") or doc.get("name") or "").strip()
	if not barcode:
		return

	for row in doc.get("barcodes") or []:
		if row.get("barcode") == barcode:
			if doc.get("stock_uom") and not row.get("uom"):
				row.uom = doc.stock_uom
			return

	existing_parent = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
	if existing_parent:
		if existing_parent != doc.name:
			frappe.log_error(
				title="POS Next Item Barcode Sync Skipped",
				message=(
					f"Could not add barcode {barcode} to item {doc.name}; "
					f"it already belongs to item {existing_parent}."
				),
			)
		return

	doc.append("barcodes", {
		"barcode": barcode,
		"uom": doc.get("stock_uom"),
	})


def repair_item_purchase_lookup_data(item_code=None):
	"""Backfill item-code barcode rows for existing items."""
	filters = {"disabled": 0}
	if item_code:
		filters["name"] = item_code

	updated_items = 0

	items = frappe.get_all(
		"Item",
		filters=filters,
		fields=["name"],
		limit=1 if item_code else 0,
	)

	for row in items:
		item_doc = frappe.get_doc("Item", row.name)
		before = len(item_doc.get("barcodes") or [])
		ensure_item_code_barcode(item_doc)
		if len(item_doc.get("barcodes") or []) != before:
			item_doc.save(ignore_permissions=True)
			updated_items += 1

	frappe.db.commit()
	return {"updated_items": updated_items}


@frappe.whitelist()
def item_query(doctype, txt, searchfield, start, page_len, filters):
	"""
	Custom query to filter items by company
	- If company is specified in filters, show:
	  1. Items belonging to that company
	  2. Global items (where custom_company is empty)
	- If no company specified, show all items
	"""
	import json

	# Parse filters if it's a string (when called from frontend)
	if isinstance(filters, str):
		filters = json.loads(filters)

	conditions = ["disabled = 0"]
	values = []

	if txt:
		conditions.append(f"({searchfield} LIKE %s OR item_name LIKE %s)")
		values.extend([f"%{txt}%", f"%{txt}%"])

	company = filters.get("company") if filters else None

	if company:
		# Show items for specific company + global items
		conditions.append("(custom_company = %s OR custom_company IS NULL OR custom_company = '')")
		values.append(company)

	query = f"""
		SELECT name, item_name, item_group
		FROM `tabItem`
		WHERE {' AND '.join(conditions)}
		ORDER BY
			CASE WHEN name LIKE %s THEN 0 ELSE 1 END,
			item_name
		LIMIT %s, %s
	"""

	values.extend([f"{txt}%", start, page_len])

	return frappe.db.sql(query, values)
