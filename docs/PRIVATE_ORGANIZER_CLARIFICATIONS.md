# Private dataset organizer clarifications

## Restricted payments to related parties — 2026-08-09

Question: When a contract does not separately define “Restricted Payments and distributions,” is an ordinary service payment to an affiliate included solely because of the counterparty's status, or only when explicitly labelled/reclassified as a Restricted Payment, distribution, or dividend?

Organizer answer (Fatikh): counterparty status is sufficient; the amount includes every outgoing payment to a related party regardless of its accounting description. The dataset will not contain a Restricted Payment / distribution / dividend label.

Implementation consequence: apply the exact governing relationship test first, aggregate all outflows to qualifying counterparties, and then apply any explicit contractual basket or deduction. For an inactive conditional restriction, retain that measured post-basket aggregate as `actual` while returning `COMPLIANT`.
