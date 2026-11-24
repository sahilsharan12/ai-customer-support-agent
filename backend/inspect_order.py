
from pprint import pprint

from backend.database_tools import get_order_details

ORDER_ID = "e481f51cbdc54678b7cc49136f2d6af7"

result = get_order_details(ORDER_ID)

if result is None:
    print("Order not found.")
else:
    print("\nORDER DETAILS:")
    pprint(result.get("order", {}))

    print("\nSUMMARY:")
    pprint(result.get("summary", {}))
