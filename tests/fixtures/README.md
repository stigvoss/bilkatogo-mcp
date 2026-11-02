# Order fixtures

Redacted examples of the shop's `OrderDetails` answer. Everything personal is replaced by an obvious
`REDACTED-…` value, which the privacy test searches the tool's output for.

- `order_ordered.json` has the structure of a real ordered (not yet packed) order: packing and bag
  lines in the `Services` and `Emballage` groups, a Mix deal, a member (Plus) price and a placeholder
  offer text.
- `order_invoiced.json` is **synthetic**: it covers a missing, a replaced and a returned line and a
  comment, as the order-intake skill needs. The shapes of `replacement` and `returns` are inferred
  from how the shop's own order model is written, not from a real invoiced order. Replace this file
  with a redacted real one when available.
