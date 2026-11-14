# Order fixtures

Redacted examples of the shop's `OrderDetails` answer. Everything personal is replaced by an obvious
`REDACTED-…` value, which the privacy test searches the tool's output for.

- `order_ordered.json` has the structure of a real ordered (not yet packed) order: packing and bag
  lines in the `Services` and `Emballage` groups, a Mix deal, a member (Plus) price and a placeholder
  offer text.
- `order_invoiced.json` follows real invoiced orders: the lines that were ordered stay, in full, and a line the
  shop could not deliver is struck through (`strikethrough: true`) with the reason as `tagline` (`"udsolgt"`
  for sold out). A line it **replaced** is struck through with the tagline `"erstattet"`, and the substitute
  is a full order line in that line's `children` (its own quantity and price; `replacement` stays null). The
  totals (`stat`, `price`, `totalProductAmount`) are the invoiced ones, so they include the substitute.
  A **return** and a **comment** are synthetic (their shapes are inferred from the shop's order model, not
  seen on a real order); replace them with a redacted real example when one is available.
