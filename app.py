import logging
logging.basicConfig(level=logging.DEBUG)
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate  
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone, date
from sqlalchemy import or_, extract
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from collections import defaultdict
import os


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SECRET_KEY'] = 'secretkey'
db = SQLAlchemy(app)
migrate = Migrate(app, db)
#login spot
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class TurnTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)  # Example: 2025
    building = db.Column(db.String(50))
    side = db.Column(db.String(50))  # East or West
    floor = db.Column(db.Integer)
    unit_number = db.Column(db.String(10))
    task_name = db.Column(db.String(100))
    is_completed = db.Column(db.Boolean, default=False)
    completed_by = db.Column(db.String(100))
    completed_at = db.Column(db.DateTime)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(50), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class ActionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.String(50))
    entity = db.Column(db.String(50))
    entity_id = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details = db.Column(db.Text)
    user = db.relationship('User')

def log_action(user, action, entity, entity_id, details=""):
    log = ActionLog(
        user_id=user.id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=details
    )
    db.session.add(log)
    db.session.commit()
    
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Data Model – Part plus OrderHistory for recording each purchase instance.
class Part(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    model_number = db.Column(db.String(50), unique=True, nullable=False)
    count = db.Column(db.Integer, default=0)
    cost = db.Column(db.Float)
    room = db.Column(db.String(50))
    threshold = db.Column(db.Integer, default=5)  # Alert threshold for low stock
    is_misc = db.Column(db.Boolean, default=False)
    appliance_type = db.Column(db.String(50))
    order_status = db.Column(db.String(50), default="Not Ordered")
    order_link = db.Column(db.String(255), nullable=True)
    tracking_number = db.Column(db.String(50), nullable=True)
    estimated_delivery = db.Column(db.Date, nullable=True)
    delivered_date = db.Column(db.Date, nullable=True)


    @property
    def active_order(self):
        undelivered = [order for order in self.orders if order.delivered_date is None]
        if undelivered:
            undelivered.sort(key=lambda o: o.order_date, reverse=True)
            return undelivered[0]
        return None

# OrderHistory model with cascade deletion and relationship back to Part.
class OrderHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey('part.id'), nullable=False)
    order_date = db.Column(db.Date, default=date.today)
    purchased_quantity = db.Column(db.Integer, nullable=False)
    total_cost = db.Column(db.Float, nullable=False)
    tracking_number = db.Column(db.String(50))
    estimated_delivery = db.Column(db.Date, nullable=True)
    delivered_date = db.Column(db.Date, nullable=True)
    part = db.relationship("Part", backref=db.backref("orders", cascade="all, delete-orphan"))
    expense_line = db.Column(db.String(50))

ROOMS = {
    "Kitchen": ["Oven", "Fridge", "Garbage Disposal", "Microwave", "Faucet", "Other"],
    "Bathroom": ["Shower", "Toilet", "Electrical", "Other"],
    "Laundry": ["Washing Machine", "Dryer", "Other"],
    "Bedroom": ["Electrical", "Desk", "Other"],
    "Living": ["Blind Slats", "TV", "Other"],
    "HVAC": ["Furnace", "Waterheater", "Air Conditioning", "Other"],
    "Other": ["Miscellaneous"]
}

@app.route('/')
@login_required
def index():
    search = request.args.get('search', '')
    room_filter = request.args.get('room', '')
    appliance_filter = request.args.get('appliance', '')
    query = Part.query
    if search:
        search_term = f"%{search}%"
        query = query.filter(or_(Part.name.ilike(search_term),
                                 Part.model_number.ilike(search_term)))
    if room_filter:
        query = query.filter_by(room=room_filter)
    if appliance_filter:
        query = query.filter_by(appliance_type=appliance_filter)
    parts = query.order_by(Part.room).all()
    alerts = [p for p in parts if p.count < p.threshold]
    return render_template('index.html', parts=parts, alerts=alerts, 
                           rooms=ROOMS, selected_room=room_filter, selected_appliance=appliance_filter, search=search)

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_part():
    if request.method == 'POST':
        if Part.query.filter_by(model_number=request.form['model_number']).first():
            flash("A part with this model number already exists.", "danger")
            return redirect(url_for('add_part'))
        try:
            appliance_type = request.form.get('appliance_type', '')
            if appliance_type == 'add_new':
                appliance_type = request.form.get('new_appliance', '').strip()
            part = Part(
                name=request.form['name'],
                model_number=request.form['model_number'],
                count=int(request.form['count']),
                cost=float(request.form['cost']),
                room=request.form['room'],
                threshold=int(request.form.get('threshold', 5)),
                is_misc='is_misc' in request.form,
                appliance_type=appliance_type,
                order_link=request.form.get('order_link', '')
            )
            db.session.add(part)
            db.session.commit()
            log_action(current_user, "create", "Part", part.id, f"Added {part.name}")
            flash(f'Added part: {part.name}', "success")
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error adding part: {str(e)}', "danger")
            return redirect(url_for('add_part'))
    recent_parts = Part.query.order_by(Part.id.desc()).limit(10).all()
    return render_template('add_part.html', recent_parts=recent_parts, rooms=ROOMS)


@app.route('/update/<int:part_id>', methods=['GET', 'POST'])
@login_required
def update_part(part_id):
    part = db.session.get(Part, part_id)
    if not part:
        flash("Part not found.", "warning")
        return redirect(url_for('index'))
    if request.method == 'POST':
        try:
            part.name = request.form['name']
            part.model_number = request.form['model_number']
            part.count = int(request.form['count'])
            part.cost = float(request.form['cost'])
            part.room = request.form['room']
            part.threshold = int(request.form.get('threshold', part.threshold))
            part.is_misc = 'is_misc' in request.form
            part.appliance_type = request.form.get('appliance_type', '')
            part.order_link = request.form.get('order_link', part.order_link)
            db.session.commit()
            log_action(current_user, "update", "Part", part.id, f"Updated {part.name}")
            flash(f'Updated part: {part.name}', "success")
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error updating part: {str(e)}', "danger")
            return redirect(url_for('update_part', part_id=part_id))
    return render_template('update_part.html', part=part, rooms=ROOMS)

@app.route('/delete/<int:part_id>', methods=['POST'])
@login_required
def delete_part(part_id):
    part = db.session.get(Part, part_id)
    if not part:
        flash("Part not found.", "warning")
    else:
        db.session.delete(part)
        db.session.commit()
        log_action(current_user, "delete", "Part", part.id, f"Deleted {part.name}")
        flash(f"Deleted part: {part.name}", "success")
    return redirect(url_for('index'))

@app.route('/api/increment/<int:part_id>', methods=['GET', 'POST'])
@login_required
def api_increment_part(part_id):
    part = db.session.get(Part, part_id)
    if part:
        part.count += 1
        db.session.commit()
        log_action(current_user, "increment", "Part", part.id, f"Count changed to {part.count}")
        if request.method == 'GET':
            return redirect(url_for('index'))
        return jsonify({'success': True, 'new_count': part.count})
    return jsonify({'success': False, 'error': 'Part not found'}), 404

@app.route('/api/decrement/<int:part_id>', methods=['GET', 'POST'])
@login_required
def api_decrement_part(part_id):
    part = db.session.get(Part, part_id)
    if part:
        if part.count > 0:
            part.count -= 1
            db.session.commit()
            log_action(current_user, "decrement", "Part", part.id, f"Count changed to {part.count}")
            if request.method == 'GET':
                return redirect(url_for('index'))
            return jsonify({'success': True, 'new_count': part.count})
        else:
            if request.method == 'GET':
                flash("Part count is already 0.", "warning")
                return redirect(url_for('index'))
            return jsonify({'success': False, 'error': 'Count already 0'}), 400
    if request.method == 'GET':
        flash("Part not found.", "danger")
        return redirect(url_for('index'))
    return jsonify({'success': False, 'error': 'Part not found'}), 404




# Combined Orders, Purchases & Delivered History Route
@app.route('/combined')
@login_required
def combined_orders():
    # Pending orders: only show if count is below threshold, order_status "Not Ordered", and has an order_link.
    pending_orders = Part.query.filter(
        Part.order_link != None,
        Part.order_status == "Not Ordered",
        Part.count < Part.threshold
    ).all()
    # Purchased orders: OrderHistory records with no delivered_date (pending delivery)
    purchased_orders = OrderHistory.query.filter(OrderHistory.delivered_date == None).all()
    # Delivered orders: OrderHistory records with delivered_date
    delivered_orders = OrderHistory.query.filter(OrderHistory.delivered_date != None).all()
    overall_total = sum(order.total_cost for order in delivered_orders)
    return render_template('combined.html',
                           pending_orders=pending_orders,
                           purchased_orders=purchased_orders,
                           delivered_orders=delivered_orders,
                           overall_total=overall_total)

@app.route('/purchase/update/<int:part_id>', methods=['GET', 'POST'])
@login_required
def purchase_update(part_id):
    part = db.session.get(Part, part_id)
    if not part:
        flash("Part not found", "warning")
        return redirect(url_for('combined_orders'))

    if request.method == 'POST':
        quantity = int(request.form.get('quantity', 0))
        total_cost = float(request.form.get('total_cost', 0))
        tracking_number = request.form.get('tracking_number', '')
        estimated_delivery_str = request.form.get('estimated_delivery', '')
        estimated_delivery = None

        valid_categories = [
            "Appliances", "HVAC" "Mechanical",
            "Pools & Exterior", "Interior Unit Work",
            "Fire & Safety", "Janitorial"
        ]
        expense_line = request.form.get('expense_line', '').strip()
        if expense_line not in valid_categories:
            flash("Please select a valid budget category.", "danger")
            return redirect(url_for('purchase_update', part_id=part.id))

        if estimated_delivery_str:
            try:
                estimated_delivery = datetime.strptime(estimated_delivery_str, "%Y-%m-%d").date()
            except ValueError:
                flash("Invalid estimated delivery date", "danger")
                return redirect(url_for('purchase_update', part_id=part.id))

        new_order = OrderHistory(
            part_id=part.id,
            purchased_quantity=quantity,
            total_cost=total_cost,
            tracking_number=tracking_number,
            estimated_delivery=estimated_delivery,
            expense_line=expense_line
        )
        db.session.add(new_order)
        part.order_status = "Purchased"
        db.session.commit()

        flash(f"Purchase for part {part.name} recorded with total cost {total_cost}.", "success")
        return redirect(url_for('combined_orders'))

    return render_template('purchase_update.html', part=part)


# API endpoint to mark an order as delivered, update the Part count, and reset its status
@app.route('/api/deliver/<int:order_id>', methods=['POST'])
def api_deliver(order_id):
    order = db.session.get(OrderHistory, order_id)
    if not order:
        return jsonify({'success': False, 'error': 'Order not found'}), 404
    if order.delivered_date:
        return jsonify({'success': False, 'error': 'Order already delivered'}), 400
    part = db.session.get(Part, order.part_id)
    if not part:
        return jsonify({'success': False, 'error': 'Part not found'}), 404
    part.count += order.purchased_quantity
    order.delivered_date = date.today()
    part.order_status = "Not Ordered"  # Reset so part can be reordered
    db.session.commit()
    return jsonify({'success': True, 'new_count': part.count})

# History Route: Display delivered orders grouped by month for a given year.
@app.route('/history')
@login_required
def history():
    year = request.args.get('year', datetime.today().year, type=int)
    delivered_orders = OrderHistory.query.filter(OrderHistory.delivered_date != None).all()
    history_data = {}
    for m in range(1, 13):
        history_data[m] = {
            'orders': [],
            'total_cost': 0.0
        }
    for order in delivered_orders:
        if order.delivered_date.year == year:
            month = order.delivered_date.month
            history_data[month]['orders'].append(order)
            history_data[month]['total_cost'] += order.total_cost
    overall_total = sum(history_data[m]['total_cost'] for m in history_data)
    return render_template('history.html', history_data=history_data, overall_total=overall_total, year=year)

# Order Edit Route: Allows editing of a pending OrderHistory record.
@app.route('/order/edit/<int:order_id>', methods=['GET', 'POST'])
@login_required
def order_edit(order_id):
    order = db.session.get(OrderHistory, order_id)
    if not order:
        flash("Order not found.", "warning")
        return redirect(url_for('combined_orders'))
    if request.method == 'POST':
        try:
            quantity = int(request.form.get('quantity', order.purchased_quantity))
            total_cost = float(request.form.get('total_cost', order.total_cost))
            tracking_number = request.form.get('tracking_number', order.tracking_number)
            estimated_delivery_str = request.form.get('estimated_delivery', '')
            estimated_delivery = order.estimated_delivery
            if estimated_delivery_str:
                try:
                    estimated_delivery = datetime.strptime(estimated_delivery_str, "%Y-%m-%d").date()
                except ValueError:
                    flash("Invalid estimated delivery date", "danger")
                    return redirect(url_for('order_edit', order_id=order.id))
            order.purchased_quantity = quantity
            order.total_cost = total_cost
            order.tracking_number = tracking_number
            order.estimated_delivery = estimated_delivery
            db.session.commit()
            flash("Order updated successfully.", "success")
            return redirect(url_for('combined_orders'))
        except Exception as e:
            flash(f"Error updating order: {str(e)}", "danger")
            return redirect(url_for('order_edit', order_id=order.id))
    return render_template('order_edit.html', order=order)


@app.route('/budget')
@login_required
def budget():
    from datetime import datetime, date
    import os

    # Determine quarter
    q_param = request.args.get('q', type=int)
    current_month = datetime.now().month
    default_quarter = (current_month - 1) // 3 + 1
    selected_quarter = q_param if q_param in [1, 2, 3, 4] else default_quarter

    quarter_start_month = (selected_quarter - 1) * 3 + 1
    quarter_start = date(datetime.now().year, quarter_start_month, 1)
    quarter_end_month = quarter_start_month + 3
    quarter_end = date(datetime.now().year + 1, 1, 1) if quarter_end_month > 12 else date(datetime.now().year, quarter_end_month, 1)

    quarter_label = f"Q{selected_quarter}"
    quarter_range = f"{quarter_start.strftime('%b %d')} – {quarter_end.strftime('%b %d, %Y')}"

    # Spreadsheet setup
    import socket
    hostname = socket.gethostname()
    credentials_file = "credentials.json" if "ip-" in hostname else "dev_credentials.json"
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_file, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key("1-6FhHu-Sq9LXjJxGBYiMK353nKEiOzsZtVGcTG_to5Y").sheet1

    # Month labels in the spreadsheet (Row 1)
    quarter_months = {
        1: ["JAN", "FEB", "MARCH"],
        2: ["APRIL", "MAY", "JUNE"],
        3: ["JULY", "AUGUST", "SEPT"],
        4: ["OCT", "NOV", "DEC"]
    }

    # Group definitions
    category_map = {
        "Appliances": [
            "Appliance Parts", "Appliance - Non-Routine Labor", "Electrical Parts - Including Light Fixtures"
        ],
        "HVAC": [
            "HVAC Parts", "HVAC - Freon", "HVAC"
        ],
        "Mechanical": [
            "Boiler Parts", "Boiler - Non-Routine Labor", "Plumbing Parts", "Elevator Maintenance", "Gate/Garage Repair and Supply", "Keys Locks"
        ],
        "Pools & Exterior": [
            "Swimming- Non-Routine Labor", "Swimming Pool Supplies", "Irrigation/ Sprinkler Repairs", "Snow Removal", "Snow Removal Supplies"
        ],
        "Interior Unit Work": [
            "Windows", "Doors", "Blinds and Screens", "Apartment Interiors"
        ],
        "Fire & Safety": [
            "Fire Alarm"
        ],
        "Janitorial": [
            "Non-Routine Janitorial", "Janitorial Supplies", "Pest Control Supply"
        ]
    }

    category_totals = {group: {"budget": 0, "spent": 0} for group in category_map}

    values = sheet.get_all_values()
    headers = values[0]
    rows = values[1:]

    # Budget lookup using month names
    for row in rows:
        if not row or not row[0]:
            continue
        name = row[0].strip()
        category_group = next((g for g, items in category_map.items() if name in items), None)
        if not category_group:
            continue
        row_total = 0
        for month_label in quarter_months[selected_quarter]:
            try:
                col_index = headers.index(month_label)
                if col_index < len(row):
                    val = row[col_index]
                    if val:
                        row_total += float(val)
            except (ValueError, IndexError):
                continue
        category_totals[category_group]["budget"] += row_total

    # Delivered Orders Spend — use only if expense_line matches
    delivered_orders = OrderHistory.query.filter(
        OrderHistory.delivered_date != None,
        OrderHistory.delivered_date >= quarter_start,
        OrderHistory.delivered_date < quarter_end
    ).all()

    spent_total = 0
    for order in delivered_orders:
        line = order.expense_line
        if line in category_totals:
            category_totals[line]["spent"] += order.total_cost
            spent_total += order.total_cost

    overall_budget = sum(group["budget"] for group in category_totals.values())
    over_budget = max(0, spent_total - overall_budget)
    percent_spent = round((spent_total / overall_budget) * 100, 1) if overall_budget else 0

    return render_template("budget.html",
        quarter_label=quarter_label,
        quarter_range=quarter_range,
        current_quarter=selected_quarter,
        overall_budget=overall_budget,
        spent_total=spent_total,
        over_budget=over_budget,
        is_over=spent_total > overall_budget,
        percent_spent=percent_spent,
        category_totals=category_totals
    )

#logout route
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You’ve been logged out.", "info")
    return redirect(url_for('login'))

@app.route('/trends')
@login_required
def trends():
    from collections import defaultdict
    from datetime import date, timedelta

    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)
    quarter = (today.month - 1) // 3 + 1
    start_of_quarter = date(today.year, 3 * (quarter - 1) + 1, 1)

    parts = Part.query.all()
    usage = []

    for part in parts:
        orders = part.orders
        week_used = sum(o.purchased_quantity for o in orders if o.delivered_date and o.delivered_date >= start_of_week)
        month_used = sum(o.purchased_quantity for o in orders if o.delivered_date and o.delivered_date >= start_of_month)
        quarter_used = sum(o.purchased_quantity for o in orders if o.delivered_date and o.delivered_date >= start_of_quarter)
        quarter_cost = sum(o.total_cost for o in orders if o.delivered_date and o.delivered_date >= start_of_quarter)

        usage.append({
            'part': part,
            'week_used': week_used,
            'month_used': month_used,
            'quarter_used': quarter_used,
            'quarter_cost': quarter_cost
        })

    total_quarter_cost = sum(item['quarter_cost'] for item in usage)
    for item in usage:
        item['budget_pct'] = round((item['quarter_cost'] / total_quarter_cost) * 100, 1) if total_quarter_cost > 0 else 0

    return render_template("trends.html", usage=usage, total_quarter_cost=total_quarter_cost)

@app.route('/turn', methods=['GET'])
@login_required
def turn():
    year = request.args.get('year', datetime.today().year, type=int)
    building = request.args.get('building', '')
    floor = request.args.get('floor', type=int)

    # Base query with filters
    query = TurnTask.query.filter_by(year=year)
    if building:
        query = query.filter_by(building=building)
    if floor:
        query = query.filter_by(floor=floor)

    tasks = query.all()

    # Group tasks by unit number for collapsible display
    grouped_tasks = defaultdict(list)
    for task in tasks:
        grouped_tasks[task.unit_number].append(task)

    # Dropdown options
    available_years = sorted({task.year for task in TurnTask.query.all()}, reverse=True)
    buildings = sorted({task.building for task in TurnTask.query.filter_by(year=year).all()})

    return render_template("turn.html",
        tasks=tasks,
        year=year,
        available_years=available_years,
        buildings=buildings,
        selected_building=building,
        selected_floor=floor,
        grouped_tasks=grouped_tasks
    )


@app.route('/turn/complete/<int:task_id>', methods=['POST'])
@login_required
def complete_turn_task(task_id):
    task = TurnTask.query.get_or_404(task_id)
    if not task.is_completed:
        task.is_completed = True
        task.completed_by = current_user.username
        task.completed_at = datetime.utcnow()
        db.session.commit()
    return redirect(url_for('turn', year=task.year))


@app.route('/turn/uncomplete/<int:task_id>', methods=['POST'])
@login_required
def uncomplete_turn_task(task_id):
    task = TurnTask.query.get_or_404(task_id)
    if task.is_completed:
        task.is_completed = False
        task.completed_by = None
        task.completed_at = None
        db.session.commit()
    return redirect(url_for('turn', year=task.year))

@app.route('/turn/setup', methods=['POST'])
@login_required
def setup_turn_2025():
    if current_user.role != 'warden':
        abort(403)

    existing = TurnTask.query.filter_by(year=2025).first()
    if existing:
        flash("Turn tasks for 2025 already exist.", "warning")
        return redirect(url_for('turn'))

    # Include the apartment layout and task seeding logic here...

    db.session.commit()
    flash("Turn setup for 2025 completed successfully!", "success")
    return redirect(url_for('turn'))

@app.route('/warden/logs')
@login_required
def view_logs():
    if current_user.role != "warden":
        abort(403)
    logs = ActionLog.query.order_by(ActionLog.timestamp.desc()).all()
    return render_template("warden_logs.html", logs=logs)



#Error handling stuff
@app.route('/order/error')
def order_error():
    abort(404)

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template("error.html", error_code=404, error_message="The page you requested could not be found."), 404

# @app.errorhandler(500)
# def internal_error(error):
#     import traceback
#     print("🔥 500 ERROR TRIGGERED 🔥")
#     traceback.print_exc()
#     db.session.rollback()
#     return render_template("error.html", error_code=500, error_message="An internal error occurred. Please try again later."), 500


@app.errorhandler(Exception)
def generic_error(error):
    import traceback
    traceback.print_exc()  # ⬅️ THIS will print the error
    return render_template("error.html", error_code=500, error_message="An unexpected error occurred."), 500


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
