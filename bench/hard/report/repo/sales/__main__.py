import sys

from sales.report import customer_report, read_orders

if len(sys.argv) != 3 or sys.argv[1] != "report":
    sys.exit("usage: python3 -m sales report ORDERS.csv")
sys.stdout.write(customer_report(read_orders(sys.argv[2])))
