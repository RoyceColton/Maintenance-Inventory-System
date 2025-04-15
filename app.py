import logging
logging.basicConfig(level=logging.DEBUG)


from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, timezone, date
from sqlalchemy import or_
from flask_migrate import Migrate  
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SECRET_KEY'] = 'secretkey'
db = SQLAlchemy(app)
migrate = Migrate(app, db)  

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
            flash(f'Added part: {part.name}', "success")
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error adding part: {str(e)}', "danger")
            return redirect(url_for('add_part'))
    recent_parts = Part.query.order_by(Part.id.desc()).limit(10).all()
    return render_template('add_part.html', recent_parts=recent_parts, rooms=ROOMS)

@app.route('/update/<int:part_id>', methods=['GET', 'POST'])
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
            flash(f'Updated part: {part.name}', "success")
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error updating part: {str(e)}', "danger")
            return redirect(url_for('update_part', part_id=part_id))
    return render_template('update_part.html', part=part, rooms=ROOMS)

@app.route('/delete/<int:part_id>', methods=['POST'])
def delete_part(part_id):
    part = db.session.get(Part, part_id)
    if not part:
        flash("Part not found.", "warning")
    else:
        db.session.delete(part)
        db.session.commit()
        flash(f"Deleted part: {part.name}", "success")
    return redirect(url_for('index'))

@app.route('/api/increment/<int:part_id>', methods=['POST'])
def api_increment_part(part_id):
    part = db.session.get(Part, part_id)
    if part:
        part.count += 1
        db.session.commit()
        return jsonify({'success': True, 'new_count': part.count})
    return jsonify({'success': False, 'error': 'Part not found'}), 404

@app.route('/api/decrement/<int:part_id>', methods=['POST'])
def api_decrement_part(part_id):
    part = db.session.get(Part, part_id)
    if part:
        if part.count > 0:
            part.count -= 1
            db.session.commit()
            return jsonify({'success': True, 'new_count': part.count})
        else:
            return jsonify({'success': False, 'error': 'Count already 0'}), 400
    return jsonify({'success': False, 'error': 'Part not found'}), 404

# Combined Orders, Purchases & Delivered History Route
@app.route('/combined')
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

# Purchase Update Route: Create an OrderHistory record and update Part status to "Purchased"
@app.route('/purchase/update/<int:part_id>', methods=['GET', 'POST'])
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
            estimated_delivery=estimated_delivery
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
def budget():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        import os
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        sheet = client.open("Test Budget").sheet1
    except Exception as e:
        app.logger.error("Google Sheet error: %s", e)
        abort(500, description="Failed to access budget data")

    try:
        overall_budget = float(sheet.acell("B2").value)
        expense_line1 = float(sheet.acell("B3").value)
        expense_line2 = float(sheet.acell("B4").value)
    except Exception as e:
        app.logger.error("Budget value error: %s", e)
        abort(500, description="Failed to read budget cells")

    delivered_orders = OrderHistory.query.filter(OrderHistory.delivered_date != None).all()
    spent_total = sum(order.total_cost for order in delivered_orders)
    over_budget = max(0, spent_total - overall_budget)
    percent_spent = round((spent_total / overall_budget) * 100, 1) if overall_budget else 0

    return render_template("budget.html",
                           overall_budget=overall_budget,
                           spent_total=spent_total,
                           over_budget=over_budget,
                           is_over=spent_total > overall_budget,
                           percent_spent=percent_spent,
                           expense_line1=expense_line1,
                           expense_line2=expense_line2)


@app.route('/order/error')
def order_error():
    abort(404)

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template("error.html", error_code=404, error_message="The page you requested could not be found."), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template("error.html", error_code=500, error_message="An internal error occurred. Please try again later."), 500

@app.errorhandler(Exception)
def generic_error(error):
    return render_template("error.html", error_code=500, error_message="An unexpected error occurred."), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
