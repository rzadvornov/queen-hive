"""Revenue per customer, ranked."""

import csv


def read_orders(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return [(row["customer"], float(row["amount"])) for row in csv.DictReader(handle)]


def customer_report(orders):
    """One line per customer: rank, name, total revenue and order count, highest revenue first.
    Customers with equal revenue keep the order in which they first appear."""
    customers = []
    totals = []
    counts = []
    for name, amount in orders:
        index = -1
        for i in range(len(customers)):
            if customers[i] == name:
                index = i
                break
        if index == -1:
            customers.append(name)
            totals.append(0.0)
            counts.append(0)
            index = len(customers) - 1
        totals[index] = totals[index] + amount
        counts[index] = counts[index] + 1

    order = list(range(len(customers)))
    for i in range(1, len(order)):   # insertion sort by total, descending; stable
        j = i
        while j > 0 and totals[order[j - 1]] < totals[order[j]]:
            order[j - 1], order[j] = order[j], order[j - 1]
            j -= 1

    text = ""
    for rank, i in enumerate(order, 1):
        text += f"{rank}. {customers[i]}: {totals[i]:.2f} ({counts[i]} orders)\n"
    return text
