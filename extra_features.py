### Extra imports for email features ###
import uuid
import smtplib
from email.mime.text import MIMEText
from flask import url_for

### Email Features ###

def send_email_verification(user):
    if not user.email:
        return

    verification_link = url_for('verify_email', token=user.verification_token, _external=True)
    subject = "Verify Your Email for IMS"
    body = f"""
    Hi {user.username},

    Please verify your email by clicking the link below:

    {verification_link}

    If you did not request this, please ignore this message.
    """

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = "villageinventorysystem@gmail.com"
    msg['To'] = user.email

    try:
        smtp_server = smtplib.SMTP('smtp.gmail.com', 587)
        smtp_server.starttls()
        smtp_server.login('villageinventorysystem@gmail.com', 'aqrpnrgupkvrizls')  # <== your app password
        smtp_server.sendmail(msg['From'], [msg['To']], msg.as_string())
        smtp_server.quit()
        print(f"✅ Verification email sent to {user.email}")
    except Exception as e:
        print(f"❌ Failed to send verification email: {e}")

def send_password_reset_email(user):
    reset_link = url_for('reset_password', token=user.reset_token, _external=True)
    subject = "Reset Your Password for IMS"
    body = f"""
    Hi {user.username},

    Click the link below to reset your password. This link is valid for 1 hour:

    {reset_link}

    If you didn't request a password reset, just ignore this email.
    """
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = "The Village IMS <villageinventorysystem@gmail.com>"
    msg['To'] = user.email

    try:
        smtp_server = smtplib.SMTP('smtp.gmail.com', 587)
        smtp_server.starttls()
        smtp_server.login('villageinventorysystem@gmail.com', 'your-app-password-here')
        smtp_server.sendmail(msg['From'], [msg['To']], msg.as_string())
        smtp_server.quit()
        print(f"✅ Password reset email sent to {user.email}")
    except Exception as e:
        print(f"❌ Failed to send password reset email: {e}")


### Settings Route ###

#settings route
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_email':
            new_email = request.form.get('email', '').strip()
            if not new_email:
                flash("Email cannot be empty.", "danger")
            elif User.query.filter(User.email == new_email, User.id != current_user.id).first():
                flash("Email is already in use.", "danger")
            else:
                current_user.email = new_email
                current_user.is_verified = False
                current_user.verification_token = str(uuid.uuid4())
                db.session.commit()
                send_email_verification(current_user)
                flash("Email updated. Please check your inbox to verify.", "success")

        elif action == 'change_password':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')

            if not current_user.check_password(current_password):
                flash("Current password is incorrect.", "danger")
            elif new_password != confirm_password:
                flash("New passwords do not match.", "danger")
            elif len(new_password) < 6:
                flash("Password must be at least 6 characters long.", "danger")
            else:
                current_user.set_password(new_password)
                db.session.commit()
                flash("Password updated successfully.", "success")

    return render_template("settings.html", user=current_user)


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    return render_template("forgot_password.html")

@app.route('/verify-email/<token>')
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    if user:
        user.is_verified = True
        user.verification_token = None
        db.session.commit()
        flash('Email verified successfully!', 'success')
    else:
        flash('Invalid or expired verification link.', 'danger')
    return redirect(url_for('login'))

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    if not user or user.reset_token_expiration < datetime.utcnow():
        flash("This password reset link is invalid or has expired.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
        elif len(new_password) < 6:
            flash("Password must be at least 6 characters.", "danger")
        else:
            user.set_password(new_password)
            user.reset_token = None
            user.reset_token_expiration = None
            db.session.commit()
            flash("Password reset successful. Please log in.", "success")
            return redirect(url_for('login'))

    return render_template('reset_password.html')