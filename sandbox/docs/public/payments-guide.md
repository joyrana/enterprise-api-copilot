# Payments guide

## Amounts and currencies

Amounts are integers in the smallest currency unit. For INR this is paise, so 500 rupees is an amount of 50000. Supported currencies are INR, USD and EUR. The minimum amount is 100.

## Payment lifecycle

A new payment starts as authorized. Authorized payments can be captured, cancelled or refunded. A cancelled payment cannot be reinstated. Refunds can be partial; the total refunded can never exceed the original amount.

## Refunds

Use refundPayment with the payment identifier and the amount to refund. Refund reasons are requested_by_customer, duplicate or fraudulent.

## Pagination

List endpoints accept a limit parameter between 1 and 100 and return items newest first.
