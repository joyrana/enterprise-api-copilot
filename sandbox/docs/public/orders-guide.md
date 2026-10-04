# Orders guide

## Creating orders

Create an order with a customer_id and at least one line item containing a sku and a quantity. Orders start in the pending fulfilment status.

## Shipment tracking

Use getShipmentTracking with the order identifier to see the carrier, the tracking number and delivery events. Tracking becomes available once an order is shipped.

## Returns

Delivered orders can be marked as returned by support staff. Returned orders keep their original line items for auditing.
