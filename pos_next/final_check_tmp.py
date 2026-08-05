import frappe

def run():
    COMP = "GOLDEN SMASHING PRICE TRADING COMPANY"
    def bal(acc):
        r = frappe.db.sql("""SELECT ROUND(SUM(credit)-SUM(debit),2) net, COUNT(*) n
                             FROM `tabGL Entry` WHERE account=%s AND is_cancelled=0""",
                          acc, as_dict=True)[0]
        return r.net or 0, r.n

    print("STAGING (tahteem.site) status\n" + "="*50)
    for acc in ["Tax Deduction - GSPT","VAT Payable - GSPT","Store Sales - GSPT","Sales - GSPT"]:
        net, n = bal(acc)
        dis = frappe.db.get_value("Account", acc, "disabled")
        print(f"  {acc}: net_credit={net} | entries={n} | disabled={dis}")

    print("\nConfig:")
    print("  Company default income:", frappe.db.get_value("Company", COMP, "default_income_account"))
    for p in frappe.get_all("POS Profile", filters={"company":COMP}, fields=["name","income_account","taxes_and_charges"]):
        print(f"  POS Profile {p.name}: income={p.income_account} tax={p.taxes_and_charges}")
    # tax template head
    for t in ["VAT-15 SAR - GSPT"]:
        head = frappe.get_all("Sales Taxes and Charges", filters={"parent":t}, fields=["account_head"])
        print(f"  Sales tax template {t} head:", [h.account_head for h in head])
    # item defaults still pointing to store sales
    n_ss = frappe.db.count("Item Default", {"company":COMP, "income_account":"Store Sales - GSPT"})
    n_s = frappe.db.count("Item Default", {"company":COMP, "income_account":"Sales - GSPT"})
    print(f"  Item Defaults -> Store Sales: {n_ss} | -> Sales: {n_s}")

    print("\nDraft/unsubmitted JVs:")
    for je in frappe.get_all("Journal Entry", filters={"company":COMP,"docstatus":0}, fields=["name","user_remark"]):
        print("  DRAFT:", je.name, "-", (je.user_remark or "")[:50])
