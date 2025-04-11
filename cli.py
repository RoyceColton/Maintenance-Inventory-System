import argparse
from datetime import datetime, timedelta, timezone
from app import app, db, Part, Expense  

def list_parts():
    with app.app_context():
        parts = Part.query.all()
        if not parts:
            print("No parts found.")
            return
        for p in parts:
            print(f"ID: {p.id} | Name: {p.name} | Model: {p.model_number} | Count: {p.count} | "
                  f"Cost: {p.cost} | Room: {p.room} | Threshold: {p.threshold} | Misc: {p.is_misc}")

def add_part(args):
    with app.app_context():
        part = Part(
            name=args.name,
            model_number=args.model,
            count=args.count,
            cost=args.cost,
            room=args.room,
            threshold=args.threshold,
            is_misc=args.misc
        )
        db.session.add(part)
        db.session.commit()
        print(f"Added part: {part.name} (ID: {part.id})")

def update_part(args):
    with app.app_context():
        part = db.session.get(Part, args.id)
        if part is None:
            print(f"Part with ID {args.id} not found.")
            return
        if args.name:
            part.name = args.name
        if args.model:
            part.model_number = args.model
        if args.count is not None:
            part.count = args.count
        if args.cost is not None:
            part.cost = args.cost
        if args.room:
            part.room = args.room
        if args.threshold is not None:
            part.threshold = args.threshold
        if args.misc is not None:
            part.is_misc = args.misc
        db.session.commit()
        print(f"Updated part: {part.name} (ID: {part.id})")

def delete_part(args):
    with app.app_context():
        part = db.session.get(Part, args.id)
        if part is None:
            print(f"Part with ID {args.id} not found.")
            return
        db.session.delete(part)
        db.session.commit()
        print(f"Deleted part: {part.name} (ID: {part.id})")

def list_expenses():
    with app.app_context():
        six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)
        expenses = Expense.query.filter(Expense.expense_date >= six_months_ago).all()
        if not expenses:
            print("No expenses found in the last six months.")
            return
        for e in expenses:
            print(f"ID: {e.id} | Part ID: {e.part_id} | Date: {e.expense_date:%Y-%m-%d} | Amount: {e.amount}")

def add_expense(args):
    with app.app_context():
        expense = Expense(part_id=args.part_id, amount=args.amount)
        db.session.add(expense)
        db.session.commit()
        print(f"Added expense for part ID: {expense.part_id}, amount: {expense.amount}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Maintenance Inventory System CLI")
    subparsers = parser.add_subparsers(help="Available commands", dest="command")
    
    # List parts command
    subparsers.add_parser("list", help="List all parts")
    
    # Add part command
    parser_add = subparsers.add_parser("add", help="Add a new part")
    parser_add.add_argument("--name", required=True, help="Name of the part")
    parser_add.add_argument("--model", required=True, help="Model number")
    parser_add.add_argument("--count", type=int, default=0, help="Stock count")
    parser_add.add_argument("--cost", type=float, required=True, help="Cost of the part")
    parser_add.add_argument("--room", required=True, help="Room where the part is located")
    parser_add.add_argument("--threshold", type=int, default=5, help="Low stock threshold")
    parser_add.add_argument("--misc", action="store_true", help="Mark as a miscellaneous part")
    
    # Update part command
    parser_update = subparsers.add_parser("update", help="Update an existing part")
    parser_update.add_argument("--id", type=int, required=True, help="ID of the part to update")
    parser_update.add_argument("--name", help="New name")
    parser_update.add_argument("--model", help="New model number")
    parser_update.add_argument("--count", type=int, help="New stock count")
    parser_update.add_argument("--cost", type=float, help="New cost")
    parser_update.add_argument("--room", help="New room")
    parser_update.add_argument("--threshold", type=int, help="New low stock threshold")
    parser_update.add_argument("--misc", type=bool, help="New misc flag (True/False)")
    
    # Delete part command
    parser_delete = subparsers.add_parser("delete", help="Delete a part")
    parser_delete.add_argument("--id", type=int, required=True, help="ID of the part to delete")
    
    # List expenses command
    subparsers.add_parser("expenses", help="List expenses from the last six months")
    
    # Add expense command
    parser_expense = subparsers.add_parser("add_expense", help="Add an expense record")
    parser_expense.add_argument("--part_id", type=int, required=True, help="ID of the part")
    parser_expense.add_argument("--amount", type=float, required=True, help="Expense amount")
    
    args = parser.parse_args()
    
    if args.command == "list":
        list_parts()
    elif args.command == "add":
        add_part(args)
    elif args.command == "update":
        update_part(args)
    elif args.command == "delete":
        delete_part(args)
    elif args.command == "expenses":
        list_expenses()
    elif args.command == "add_expense":
        add_expense(args)
    else:
        parser.print_help()
