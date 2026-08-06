import { call } from "@/utils/apiWrapper"
import { logger } from "@/utils/logger"

const log = logger.create('PrintInvoice')
const preloadedPrintViews = new Map()

function isIframeLoaded(iframe) {
	return iframe?.contentWindow?.document?.readyState === "complete"
}

function createPrintViewIframe(invoiceName, printFormat = "POS QR Format", letterhead = null) {
	const params = new URLSearchParams({
		doctype: "Sales Invoice",
		name: invoiceName,
		format: printFormat,
		no_letterhead: letterhead ? 0 : 1,
		_lang: "en",
		_t: Date.now(),
	})

	if (letterhead) {
		params.append("letterhead", letterhead)
	}

	const iframe = document.createElement("iframe")
	iframe.style.cssText = "position:fixed;left:-10000px;top:0;width:820px;height:1200px;border:0;background:white;"
	iframe.src = `/printview?${params.toString()}`
	document.body.appendChild(iframe)
	return iframe
}

async function waitForIframePrintReady(iframe, timeoutMs = 10000) {
	if (!iframe?.contentWindow) {
		throw new Error("Print iframe is not available")
	}

	await new Promise((resolve, reject) => {
		let settled = false
		const finish = () => {
			if (settled) return
			settled = true
			clearTimeout(timer)
			iframe.removeEventListener("load", finish)
			resolve()
		}
		const timer = setTimeout(() => {
			if (settled) return
			settled = true
			iframe.removeEventListener("load", finish)
			reject(new Error("Print preview took too long to load"))
		}, timeoutMs)

		const doc = iframe.contentWindow?.document
		if (doc?.readyState === "complete") {
			finish()
			return
		}

		iframe.addEventListener("load", finish, { once: true })
	})

	const doc = iframe.contentWindow.document
	if (doc.fonts?.ready) {
		await Promise.race([
			doc.fonts.ready,
			new Promise((resolve) => setTimeout(resolve, 3000)),
		])
	}

	const images = Array.from(doc.images || [])
	await Promise.race([
		Promise.all(
			images.map((img) => {
				if (img.complete) return Promise.resolve()
				return new Promise((resolve) => {
					img.addEventListener("load", resolve, { once: true })
					img.addEventListener("error", resolve, { once: true })
				})
			}),
		),
		new Promise((resolve) => setTimeout(resolve, 3000)),
	])

	await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
}

function escapeHtml(value) {
	return String(value ?? "")
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;")
		.replaceAll("'", "&#039;")
}

export function openPrintView(
	invoiceName,
	printFormat = "POS QR Format",
	letterhead = null,
	reservedWindow = null,
) {
	if (!invoiceName) {
		throw new Error("Invalid invoice name")
	}

	const params = new URLSearchParams({
		doctype: "Sales Invoice",
		name: invoiceName,
		format: printFormat,
		no_letterhead: letterhead ? 0 : 1,
		_lang: "en",
		trigger_print: 1,
		_t: Date.now(),
	})

	if (letterhead) {
		params.append("letterhead", letterhead)
	}

	const printUrl = `/printview?${params.toString()}`

	if (reservedWindow && !reservedWindow.closed) {
		reservedWindow.location.replace(printUrl)
		reservedWindow.focus()
		return true
	}

	const printWindow = window.open(printUrl, "_blank", "width=800,height=600")
	if (!printWindow) {
		return printViaIframe(printUrl)
	}
	return true
}

export function printPrintViewIframe(
	invoiceName,
	printFormat = "POS QR Format",
	letterhead = null,
) {
	if (!invoiceName) {
		throw new Error("Invalid invoice name")
	}

	const params = new URLSearchParams({
		doctype: "Sales Invoice",
		name: invoiceName,
		format: printFormat,
		no_letterhead: letterhead ? 0 : 1,
		_lang: "en",
		trigger_print: 1,
		_t: Date.now(),
	})

	if (letterhead) {
		params.append("letterhead", letterhead)
	}

	return printViaIframe(`/printview?${params.toString()}`)
}

export function preloadPrintView(
	invoiceName,
	printFormat = "POS QR Format",
	letterhead = null,
) {
	if (!invoiceName || preloadedPrintViews.has(invoiceName)) return false
	const iframe = createPrintViewIframe(invoiceName, printFormat, letterhead)
	preloadedPrintViews.set(invoiceName, iframe)
	return true
}

export function printPreloadedPrintView(invoiceName, printFormat = "POS QR Format") {
	const iframe = preloadedPrintViews.get(invoiceName)
	if (!iframe?.contentWindow) {
		return printPrintViewIframe(invoiceName, printFormat)
	}

	try {
		iframe.contentWindow.focus()
		iframe.contentWindow.print()
		setTimeout(() => {
			preloadedPrintViews.delete(invoiceName)
			if (document.body.contains(iframe)) document.body.removeChild(iframe)
		}, 30000)
		return true
	} catch (error) {
		log.warn("Preloaded print failed, using fresh printview", error)
		preloadedPrintViews.delete(invoiceName)
		if (document.body.contains(iframe)) document.body.removeChild(iframe)
		return printPrintViewIframe(invoiceName, printFormat)
	}
}

export function printPreloadedPrintViewFast(invoiceName, printFormat = "POS QR Format") {
	const iframe = preloadedPrintViews.get(invoiceName)
	if (!isIframeLoaded(iframe)) {
		return false
	}

	try {
		iframe.contentWindow.focus()
		iframe.contentWindow.print()
		setTimeout(() => {
			preloadedPrintViews.delete(invoiceName)
			if (document.body.contains(iframe)) document.body.removeChild(iframe)
		}, 30000)
		return true
	} catch (error) {
		log.warn("Fast preloaded print failed", error)
		return false
	}
}

export async function printPreloadedPrintViewWhenReady(invoiceName, printFormat = "POS QR Format") {
	let iframe = preloadedPrintViews.get(invoiceName)
	if (!iframe?.contentWindow) {
		iframe = createPrintViewIframe(invoiceName, printFormat)
		preloadedPrintViews.set(invoiceName, iframe)
	}

	try {
		await waitForIframePrintReady(iframe)
		iframe.contentWindow.focus()
		iframe.contentWindow.print()
		setTimeout(() => {
			preloadedPrintViews.delete(invoiceName)
			if (document.body.contains(iframe)) document.body.removeChild(iframe)
		}, 30000)
		return true
	} catch (error) {
		preloadedPrintViews.delete(invoiceName)
		if (document.body.contains(iframe)) document.body.removeChild(iframe)
		throw error
	}
}

export function printCartReceiptNow(receiptData) {
	const rows = (receiptData.items || []).map((item) => {
		const qty = Number.parseFloat(item.quantity || item.qty || 0) || 0
		const rate = Number.parseFloat(item.rate || item.price_list_rate || 0) || 0
		const amount = Number.parseFloat(item.amount || qty * rate || 0) || 0
		return `
			<tr>
				<td class="desc">${escapeHtml(item.item_name || item.item_code || "")}<br><small>${escapeHtml(item.item_code || "")}</small></td>
				<td>${formatCurrency(qty)}</td>
				<td>${formatCurrency(rate)}</td>
				<td>${formatCurrency(amount)}</td>
			</tr>
		`
	}).join("")

	const receiptHtml = `
		<style>
			body { margin: 0; }
			.pos-receipt { width: 80mm; max-width: 80mm; padding: 3mm; color: #000; font-family: Arial, sans-serif; font-size: 10px; line-height: 1.25; }
			.center { text-align: center; }
			.bold { font-weight: 700; }
			.box { border: 1px solid #000; margin: 3px 0; padding: 3px; }
			table { width: 100%; border-collapse: collapse; }
			th, td { border-bottom: 1px solid #999; padding: 2px; text-align: right; vertical-align: top; }
			th:first-child, td:first-child { text-align: left; }
			.desc { width: 43%; }
			.totals td { border-bottom: 0; }
			.grand td { border-top: 1px solid #000; font-weight: 700; }
			.arabic { direction: rtl; }
			@page { size: 80mm auto; margin: 0; }
			@media print { body { margin: 0; } .pos-receipt { padding: 2mm; } }
		</style>
		<div class="pos-receipt">
			<div class="center">
				<div>Thank you for shopping with us</div>
				<div class="arabic">شكراً لتسوقكم معنا</div>
				<div class="bold">${escapeHtml(receiptData.company || "GOLDEN SHMASHI PRICE TRADING COMPANY")}</div>
				<div class="arabic">شركة جولدن مشمشي التجارية</div>
				<div class="box bold">POS Receipt<br><span class="arabic">إيصال نقطة بيع</span></div>
			</div>
			<table>
				<tr><td>No / رقم</td><td class="bold">Creating...</td></tr>
				<tr><td>Customer / العميل</td><td>${escapeHtml(receiptData.customer || "B2C")}</td></tr>
				<tr><td>Date / تاريخ</td><td>${escapeHtml(receiptData.date)}</td></tr>
				<tr><td>Time / الوقت</td><td>${escapeHtml(receiptData.time)}</td></tr>
			</table>
			<table>
				<thead>
					<tr>
						<th>Item<br><span class="arabic">الصنف</span></th>
						<th>Qty<br><span class="arabic">كمية</span></th>
						<th>Rate<br><span class="arabic">السعر</span></th>
						<th>Amount<br><span class="arabic">المبلغ</span></th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
			<table class="totals">
				<tr><td>Net Total<br><span class="arabic">الإجمالي غير الضريبي</span></td><td>${formatCurrency(receiptData.netTotal)}</td></tr>
				<tr><td>VAT @15.0%<br><span class="arabic">ضريبة القيمة المضافة</span></td><td>${formatCurrency(receiptData.taxTotal)}</td></tr>
				<tr class="grand"><td>Grand Total<br><span class="arabic">الإجمالي الكلي</span></td><td>${formatCurrency(receiptData.grandTotal)}</td></tr>
			</table>
		</div>
	`

	return printHtmlViaIframe(receiptHtml, "Receipt")
}

export async function printReceiptHtml(
	invoiceName,
	printFormat = "POS QR Format",
	letterhead = null,
	reservedWindow = null,
) {
	if (!invoiceName) {
		throw new Error("Invalid invoice name")
	}

	const receiptHtml = await call("pos_next.api.invoices.get_pos_receipt_html", {
		invoice_name: invoiceName,
		print_format: printFormat,
		letterhead,
	})

	const printWindow =
		reservedWindow && !reservedWindow.closed
			? reservedWindow
			: null

	if (!printWindow) {
		return printHtmlViaIframe(receiptHtml, invoiceName)
	}

	printWindow.document.open()
	printWindow.document.write(`
		<!DOCTYPE html>
		<html>
		<head>
			<meta charset="UTF-8">
			<title>Receipt - ${invoiceName}</title>
		</head>
		<body>
			${receiptHtml}
			<script>
				window.addEventListener("load", function () {
					setTimeout(function () {
						window.focus();
						window.print();
					}, 0);
				});
			</script>
		</body>
		</html>
	`)
	printWindow.document.close()
	printWindow.focus()
	return true
}

export function printReceiptContent(receiptHtml, invoiceName = "Receipt", reservedWindow = null) {
	if (!receiptHtml) return false

	const printWindow =
		reservedWindow && !reservedWindow.closed
			? reservedWindow
			: null

	if (!printWindow) {
		return printHtmlViaIframe(receiptHtml, invoiceName)
	}

	printWindow.document.open()
	printWindow.document.write(`
		<!DOCTYPE html>
		<html>
		<head>
			<meta charset="UTF-8">
			<title>Receipt - ${invoiceName}</title>
		</head>
		<body>
			${receiptHtml}
			<script>
				window.addEventListener("load", function () {
					setTimeout(function () {
						window.focus();
						window.print();
					}, 0);
				});
			</script>
		</body>
		</html>
	`)
	printWindow.document.close()
	printWindow.focus()
	return true
}

function printHtmlViaIframe(receiptHtml, invoiceName) {
	const iframe = document.createElement("iframe")
	iframe.style.cssText = "position:fixed;left:-10000px;top:0;width:820px;height:1200px;border:0;background:white;"
	document.body.appendChild(iframe)

	const doc = iframe.contentWindow?.document
	if (!doc) return false

	doc.open()
	doc.write(`
		<!DOCTYPE html>
		<html>
		<head>
			<meta charset="UTF-8">
			<title>Receipt - ${invoiceName}</title>
		</head>
		<body>${receiptHtml}</body>
		</html>
	`)
	doc.close()

	setTimeout(() => {
		iframe.contentWindow?.focus()
		iframe.contentWindow?.print()
		setTimeout(() => {
			if (document.body.contains(iframe)) document.body.removeChild(iframe)
		}, 30000)
	}, 0)

	return true
}

/**
 * Print invoice using Frappe's print format system
 * @param {Object} invoiceData - The invoice document data
 * @param {string} printFormat - The print format name (optional)
 * @param {string} letterhead - The letterhead name (optional)
 * @param {boolean} useIframe - Use hidden iframe instead of popup (for thermal/silent print)
 * @param {Window} reservedWindow - Window opened during the user's click event
 */
export async function printInvoice(
	invoiceData,
	printFormat = null,
	letterhead = null,
	useIframe = false,
	reservedWindow = null,
) {
	try {
		if (!invoiceData || !invoiceData.name) {
			throw new Error("Invalid invoice data")
		}

		const doctype = invoiceData.doctype || "Sales Invoice"
		const format = printFormat || "POS QR Format"

		const params = new URLSearchParams({
			doctype: doctype,
			name: invoiceData.name,
			format: format,
			no_letterhead: letterhead ? 0 : 1,
			_lang: "en",
			trigger_print: 1,
			_t: Date.now(),
		})

		if (letterhead) {
			params.append("letterhead", letterhead)
		}

		const printUrl = `/printview?${params.toString()}`

		if (reservedWindow && !reservedWindow.closed) {
			reservedWindow.location.href = printUrl
			reservedWindow.focus()
			return true
		}

		if (useIframe) {
			// Hidden iframe: trigger_print=1 in Frappe's printview auto-calls window.print().
			// Combine with Chrome --kiosk-printing for truly silent output to thermal printer.
			return printViaIframe(printUrl)
		}

		const printWindow = window.open(printUrl, "_blank", "width=800,height=600")

		if (!printWindow) {
			log.warn("Popup blocked — falling back to iframe print")
			return printViaIframe(printUrl)
		}

		return true
	} catch (error) {
		log.error("Error printing with Frappe print format:", error)
		return printInvoiceCustom(invoiceData)
	}
}

function printViaIframe(printUrl) {
	const iframe = document.createElement("iframe")
	iframe.style.cssText = "position:fixed;left:-10000px;top:0;width:820px;height:1200px;border:none;background:white;"
	iframe.src = printUrl
	document.body.appendChild(iframe)
	iframe.addEventListener("load", () => {
		// Frappe's trigger_print=1 will auto-call window.print() inside the iframe.
		// Remove the iframe after a generous delay to allow the print job to spool.
		setTimeout(() => {
			if (document.body.contains(iframe)) document.body.removeChild(iframe)
		}, 30000)
	})
	return true
}

/**
 * Generates and prints a custom POS receipt using a thermal printer layout.
 *
 * This fallback printer is used when Frappe's standard print format is unavailable.
 * The receipt is optimized for 80mm thermal printers with clean, readable formatting.
 *
 * Receipt Structure:
 * - Header: Company name and invoice type
 * - Info: Invoice number, date, customer, payment status
 * - Items: Each item shows quantity × original price = subtotal
 * - Discounts: Displayed as separate line items with negative amounts
 * - Totals: Subtotal, tax, and grand total
 * - Payments: Payment methods and amounts, change, outstanding balance
 * - Footer: Thank you message and branding
 *
 * @param {Object} invoiceData - The invoice document data from ERPNext
 * @param {string} invoiceData.name - Invoice number
 * @param {string} invoiceData.company - Company name
 * @param {Array} invoiceData.items - Invoice line items
 * @param {Array} invoiceData.payments - Payment records
 * @param {number} invoiceData.grand_total - Invoice total amount
 */
export function printInvoiceCustom(invoiceData) {
	// Open print window with receipt size dimensions (80mm ≈ 302px at 96 DPI)
	const printWindow = window.open("", "_blank", "width=350,height=600")

	const printContent = `
		<!DOCTYPE html>
		<html>
		<head>
			<meta charset="UTF-8">
			<title>Invoice - ${invoiceData.name}</title>
			<style>
				* {
					margin: 0;
					padding: 0;
					box-sizing: border-box;
				}

				body {
					font-family: 'Courier New', monospace;
					padding: 10px;
					width: 80mm;
					margin: 0;
					max-width: 80mm;
				}

				.receipt {
					width: 100%;
				}

				.header {
					text-align: center;
					margin-bottom: 20px;
					border-bottom: 2px dashed #000;
					padding-bottom: 10px;
				}

				.company-name {
					font-size: 18px;
					font-weight: bold;
					margin-bottom: 5px;
				}

				.invoice-info {
					margin-bottom: 15px;
					font-size: 12px;
				}

				.invoice-info div {
					display: flex;
					justify-content: space-between;
					margin-bottom: 3px;
				}

				.partial-status {
					color: #dc3545;
					font-weight: bold;
					margin-bottom: 5px;
				}

				.items-table {
					width: 100%;
					margin-bottom: 15px;
					border-top: 1px dashed #000;
					border-bottom: 1px dashed #000;
					padding: 10px 0;
				}

				.item-row {
					margin-bottom: 10px;
					font-size: 12px;
				}

				.item-name {
					font-weight: bold;
					margin-bottom: 3px;
				}

				.item-details {
					display: flex;
					justify-content: space-between;
					font-size: 11px;
					color: #333;
				}

				.item-discount {
					display: flex;
					justify-content: space-between;
					font-size: 10px;
					color: #28a745;
					margin-top: 2px;
				}

				.totals {
					margin-top: 15px;
					border-top: 1px dashed #000;
					padding-top: 10px;
				}

				.total-row {
					display: flex;
					justify-content: space-between;
					margin-bottom: 5px;
					font-size: 12px;
				}

				.grand-total {
					font-size: 16px;
					font-weight: bold;
					border-top: 2px solid #000;
					padding-top: 10px;
					margin-top: 10px;
				}

				.payments {
					margin-top: 15px;
					border-top: 1px dashed #000;
					padding-top: 10px;
				}

				.payment-row {
					display: flex;
					justify-content: space-between;
					margin-bottom: 3px;
					font-size: 11px;
				}

				.total-paid {
					font-weight: bold;
					border-top: 1px solid #ccc;
					padding-top: 5px;
					margin-top: 5px;
				}

				.outstanding-row {
					display: flex;
					justify-content: space-between;
					font-size: 13px;
					font-weight: bold;
					color: #dc3545;
					background-color: #fff3cd;
					padding: 8px;
					margin-top: 8px;
					border-radius: 4px;
				}

				.footer {
					text-align: center;
					margin-top: 20px;
					padding-top: 10px;
					border-top: 2px dashed #000;
					font-size: 11px;
				}

				@media print {
					@page {
						size: 80mm auto;
						margin: 0;
					}

					body {
						width: 80mm;
						padding: 5mm;
						margin: 0;
					}

					.no-print {
						display: none;
					}
				}
			</style>
		</head>
		<body>
			<div class="receipt">
				<!-- Header -->
				<div class="header">
					<div class="company-name">${invoiceData.company || invoiceData.pos_profile?.company || "POS Next"}</div>
					<div style="font-size: 12px;">TAX INVOICE</div>
				</div>

				<!-- Invoice Info -->
				<div class="invoice-info">
					<div>
						<span>Invoice #:</span>
						<span><strong>${invoiceData.name || "Receipt"}</strong></span>
					</div>
					<div>
						<span>Date:</span>
						<span>${new Date(invoiceData.posting_date || Date.now()).toLocaleString()}</span>
					</div>
					${
						invoiceData.customer_name || invoiceData.customer
							? `
					<div>
						<span>Customer:</span>
						<span>${invoiceData.customer_name || invoiceData.customer}</span>
					</div>
					`
							: ""
					}
					${
						(invoiceData.status === "Partly Paid" || (invoiceData.outstanding_amount && invoiceData.outstanding_amount > 0 && invoiceData.outstanding_amount < invoiceData.grand_total))
							? `
					<div class="partial-status">
						<span>Status:</span>
						<span>PARTIAL PAYMENT</span>
					</div>
					`
							: ""
					}
				</div>

				<!-- Items -->
				<div class="items-table">
					${(invoiceData.items || [])
						.map((item) => {
							// Determine if item has promotional pricing
							const hasItemDiscount =
								(item.discount_percentage &&
									Number.parseFloat(item.discount_percentage) > 0) ||
								(item.discount_amount &&
									Number.parseFloat(item.discount_amount) > 0)
							const isFree = item.is_free_item
							const qty = item.qty || item.quantity

							// Display original list price for transparency
							const displayRate = item.price_list_rate || item.rate
							// Calculate subtotal before any price reductions
							const subtotal = qty * displayRate

							return `
						<div class="item-row">
							<div class="item-name">
								${item.item_name || item.item_code}${isFree ? " (FREE)" : ""}
							</div>
							<div class="item-details">
								<span>${qty} × ${formatCurrency(displayRate)}</span>
								<span><strong>${formatCurrency(subtotal)}</strong></span>
							</div>
							${
								hasItemDiscount
									? `
							<div class="item-discount">
								<span>Discount ${item.discount_percentage ? `(${Number(item.discount_percentage).toFixed(2)}%)` : ""}</span>
								<span>-${formatCurrency(item.discount_amount || 0)}</span>
							</div>
							`
									: ""
							}
						</div>
						`
						})
						.join("")}
				</div>

				<!-- Totals -->
				<div class="totals">
					${
						(invoiceData.total_taxes_and_charges || invoiceData.total_tax) &&
						(invoiceData.total_taxes_and_charges || invoiceData.total_tax) > 0
							? `
					<div class="total-row">
						<span>Subtotal:</span>
						<span>${formatCurrency((invoiceData.grand_total || 0) - (invoiceData.total_taxes_and_charges || invoiceData.total_tax || 0))}</span>
					</div>
					<div class="total-row">
						<span>Tax:</span>
						<span>${formatCurrency(invoiceData.total_taxes_and_charges || invoiceData.total_tax)}</span>
					</div>
					`
							: ""
					}
					${
						invoiceData.discount_amount
							? `
					<div class="total-row" style="color: #28a745;">
						<span>Additional Discount${invoiceData.additional_discount_percentage ? ` (${Number(invoiceData.additional_discount_percentage).toFixed(1)}%)` : ""}:</span>
						<span>-${formatCurrency(Math.abs(invoiceData.discount_amount))}</span>
					</div>
					`
							: ""
					}
					<div class="total-row grand-total">
						<span>TOTAL:</span>
						<span>${formatCurrency(invoiceData.grand_total)}</span>
					</div>
				</div>

				<!-- Payments -->
				${
					invoiceData.payments && invoiceData.payments.length > 0
						? `
				<div class="payments">
					<div style="font-weight: bold; margin-bottom: 5px; font-size: 12px;">Payments:</div>
					${invoiceData.payments
						.map(
							(payment) => `
						<div class="payment-row">
							<span>${payment.mode_of_payment}:</span>
							<span>${formatCurrency(payment.amount)}</span>
						</div>
					`,
						)
						.join("")}
					<div class="payment-row total-paid">
						<span>Total Paid:</span>
						<span>${formatCurrency(invoiceData.paid_amount || 0)}</span>
					</div>
					${
						invoiceData.change_amount && invoiceData.change_amount > 0
							? `
					<div class="payment-row" style="font-weight: bold; margin-top: 5px;">
						<span>Change:</span>
						<span>${formatCurrency(invoiceData.change_amount)}</span>
					</div>
					`
							: ""
					}
					${
						invoiceData.outstanding_amount && invoiceData.outstanding_amount > 0
							? `
					<div class="outstanding-row">
						<span>BALANCE DUE:</span>
						<span>${formatCurrency(invoiceData.outstanding_amount)}</span>
					</div>
					`
							: ""
					}
				</div>
				`
						: ""
				}

				<!-- Footer -->
				<div class="footer">
					<div style="margin-bottom: 5px;">Thank you for your business!</div>
					<div style="font-size: 10px;">Powered by <a href="https://nexus.brainwise.me" target="_blank" style="color: #3b82f6; text-decoration: none; font-weight: 600;">BrainWise</a></div>
				</div>
			</div>

			<div class="no-print" style="text-align: center; margin-top: 20px;">
				<button onclick="window.print()" style="padding: 10px 20px; font-size: 14px; cursor: pointer;">
					Print Receipt
				</button>
				<button onclick="window.close()" style="padding: 10px 20px; font-size: 14px; cursor: pointer; margin-left: 10px;">
					Close
				</button>
			</div>
		</body>
		</html>
	`

	printWindow.document.write(printContent)
	printWindow.document.close()

	// Auto print after load
	printWindow.onload = () => {
		setTimeout(() => {
			printWindow.print()
		}, 250)
	}
}

function formatCurrency(amount) {
	return Number.parseFloat(amount || 0).toFixed(2)
}

/**
 * Print invoice by name, fetching print format from POS Profile
 * @param {string} invoiceName - The name of the invoice to print
 * @param {string} printFormat - Optional print format override
 * @param {string} letterhead - Optional letterhead override
 */
export async function printInvoiceByName(
	invoiceName,
	printFormat = null,
	letterhead = null,
	useIframe = false,
	reservedWindow = null,
) {
	try {
		const invoiceDoc = await call("pos_next.api.invoices.get_invoice", {
			invoice_name: invoiceName,
		})

		if (!invoiceDoc) {
			throw new Error("Invoice not found")
		}

		if (!printFormat && invoiceDoc.pos_profile) {
			try {
				const posProfileDoc = await call("frappe.client.get", {
					doctype: "POS Profile",
					name: invoiceDoc.pos_profile,
				})

				if (posProfileDoc) {
					printFormat = posProfileDoc.print_format
					letterhead = letterhead || posProfileDoc.letter_head
				}
			} catch (error) {
				log.warn("Could not fetch POS Profile print settings:", error)
			}
		}

		return await printInvoice(invoiceDoc, printFormat, letterhead, useIframe, reservedWindow)
	} catch (error) {
		log.error("Error fetching invoice for print:", error)
		throw error
	}
}
