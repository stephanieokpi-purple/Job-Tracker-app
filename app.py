from flask import Flask, render_template, request, redirect, session, Response
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime, timedelta
from flask_bcrypt import Bcrypt
import csv
import io

app = Flask(__name__)
app.secret_key = "jobtracker_secret_key_2026"
bcrypt = Bcrypt(app)

client = MongoClient("mongodb://localhost:27017/")
db = client["job_application_tracker"]
applications_collection = db["applications"]
jobs_collection = db["jobs"]
users_collection = db["users"]


def logged_in():
    return "user_email" in session


@app.route('/')
def home():
    if not logged_in():
        return redirect('/login')
    all_apps = list(applications_collection.find({"user_email": session["user_email"]}))
    stats = {
        "total":     len(all_apps),
        "applied":   sum(1 for a in all_apps if a.get("status") == "Applied"),
        "interview": sum(1 for a in all_apps if a.get("status") == "Interview Scheduled"),
        "offer":     sum(1 for a in all_apps if a.get("status") == "Offer Received"),
        "rejected":  sum(1 for a in all_apps if a.get("status") == "Rejected"),
        "withdrawn": sum(1 for a in all_apps if a.get("status") == "Withdrawn"),
    }
    recent_apps = list(applications_collection.find({"user_email": session["user_email"]}).sort("_id", -1).limit(5))
    today = datetime.today()
    cutoff = today - timedelta(days=14)
    notifications = []
    for a in all_apps:
        if a.get("status") in ["Rejected", "Withdrawn", "Offer Received"]:
            continue
        date_str = a.get("date_applied")
        if date_str:
            try:
                date_applied = datetime.strptime(date_str, "%Y-%m-%d")
                if date_applied <= cutoff:
                    notifications.append(a)
            except:
                pass
    return render_template('index.html', stats=stats, recent_apps=recent_apps, notifications=notifications)


@app.route('/analytics')
def analytics():
    if not logged_in():
        return redirect('/login')
    all_apps = list(applications_collection.find({"user_email": session["user_email"]}))
    total = len(all_apps)
    rejected = [a for a in all_apps if a.get("status") == "Rejected"]
    rejection_rate = round((len(rejected) / total * 100), 1) if total > 0 else 0
    interviews = sum(1 for a in all_apps if a.get("status") == "Interview Scheduled")
    offers = sum(1 for a in all_apps if a.get("status") == "Offer Received")

    today = datetime.today()
    week_start = today - timedelta(days=7)
    this_week = 0
    response_times = []
    for a in all_apps:
        date_str = a.get("date_applied")
        if date_str:
            try:
                date_applied = datetime.strptime(date_str, "%Y-%m-%d")
                if date_applied >= week_start:
                    this_week += 1
                if a.get("status") != "Applied":
                    diff = (today - date_applied).days
                    response_times.append(diff)
            except:
                pass

    avg_response = round(sum(response_times) / len(response_times)) if response_times else 0

    rejection_by_company = {}
    for a in rejected:
        company = a.get("company_name", "Unknown")
        rejection_by_company[company] = rejection_by_company.get(company, 0) + 1
    rejection_by_company = [{"company": k, "count": v} for k, v in sorted(rejection_by_company.items(), key=lambda x: x[1], reverse=True)]

    source_counts = {}
    for a in all_apps:
        source = a.get("source", "Unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
    source_performance = [{"source": k, "count": v} for k, v in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)]

    salary_data = [a for a in all_apps if a.get("salary_range")]

    analytics_data = {
        "total": total,
        "avg_response": avg_response,
        "rejection_rate": rejection_rate,
        "this_week": this_week,
        "interviews": interviews,
        "offers": offers,
        "rejection_by_company": rejection_by_company,
        "source_performance": source_performance,
        "salary_data": salary_data,
    }
    return render_template('analytics.html', analytics=analytics_data)


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not logged_in():
        return redirect('/login')
    user = users_collection.find_one({"email": session["user_email"]})
    if request.method == 'POST':
        updated = {
            "name":         request.form.get("name"),
            "linkedin":     request.form.get("linkedin"),
            "target_title": request.form.get("target_title"),
            "location":     request.form.get("location"),
            "bio":          request.form.get("bio"),
        }
        users_collection.update_one({"email": session["user_email"]}, {"$set": updated})
        session["user_name"] = updated["name"]
        return redirect('/profile')
    return render_template('profile.html', user=user)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get("email")
        password = request.form.get("password")
        name = request.form.get("name")
        existing = users_collection.find_one({"email": email})
        if existing:
            return render_template('register.html', error="Email already registered.")
        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        users_collection.insert_one({"email": email, "password": hashed, "name": name})
        session["user_email"] = email
        session["user_name"] = name
        return redirect('/')
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get("email")
        password = request.form.get("password")
        user = users_collection.find_one({"email": email})
        if user and bcrypt.check_password_hash(user["password"], password):
            session["user_email"] = email
            session["user_name"] = user.get("name", "")
            return redirect('/')
        return render_template('login.html', error="Invalid email or password.")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/applications')
def view_applications():
    if not logged_in():
        return redirect('/login')
    apps = list(applications_collection.find({"user_email": session["user_email"]}).sort("_id", -1))
    return render_template('applications.html', applications=apps)


@app.route('/applications/add', methods=['GET', 'POST'])
def add_application():
    if not logged_in():
        return redirect('/login')
    if request.method == 'POST':
        data = {
            "user_email":       session["user_email"],
            "company_name":     request.form.get("company_name"),
            "job_title":        request.form.get("job_title"),
            "date_applied":     request.form.get("date_applied"),
            "status":           request.form.get("status"),
            "priority":         request.form.get("priority"),
            "interview_date":   request.form.get("interview_date"),
            "location":         request.form.get("location"),
            "work_type":        request.form.get("work_type"),
            "employment_type":  request.form.get("employment_type"),
            "salary_range":     request.form.get("salary_range"),
            "contact_person":   request.form.get("contact_person"),
            "followup_date":    request.form.get("followup_date"),
            "job_url":          request.form.get("job_url"),
            "source":           request.form.get("source"),
            "notes":            request.form.get("notes"),
        }
        applications_collection.insert_one(data)
        return redirect('/applications')
    return render_template('add.html')


@app.route('/applications/edit/<id>', methods=['GET', 'POST'])
def edit_application(id):
    if not logged_in():
        return redirect('/login')
    app_doc = applications_collection.find_one({"_id": ObjectId(id)})
    if request.method == 'POST':
        updated = {
            "company_name":     request.form.get("company_name"),
            "job_title":        request.form.get("job_title"),
            "date_applied":     request.form.get("date_applied"),
            "status":           request.form.get("status"),
            "priority":         request.form.get("priority"),
            "interview_date":   request.form.get("interview_date"),
            "location":         request.form.get("location"),
            "work_type":        request.form.get("work_type"),
            "employment_type":  request.form.get("employment_type"),
            "salary_range":     request.form.get("salary_range"),
            "contact_person":   request.form.get("contact_person"),
            "followup_date":    request.form.get("followup_date"),
            "job_url":          request.form.get("job_url"),
            "source":           request.form.get("source"),
            "notes":            request.form.get("notes"),
        }
        applications_collection.update_one({"_id": ObjectId(id)}, {"$set": updated})
        return redirect('/applications')
    return render_template('edit.html', app=app_doc)


@app.route('/applications/detail/<id>')
def application_detail(id):
    if not logged_in():
        return redirect('/login')
    app_doc = applications_collection.find_one({"_id": ObjectId(id)})
    return render_template('detail.html', app=app_doc)


@app.route('/applications/delete/<id>', methods=['POST'])
def delete_application(id):
    if not logged_in():
        return redirect('/login')
    applications_collection.delete_one({"_id": ObjectId(id)})
    return redirect('/applications')


@app.route('/applications/withdraw/<id>', methods=['POST'])
def withdraw_application(id):
    if not logged_in():
        return redirect('/login')
    applications_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": "Withdrawn"}}
    )
    return redirect('/applications')


@app.route('/applications/export')
def export_csv():
    if not logged_in():
        return redirect('/login')
    apps = list(applications_collection.find({"user_email": session["user_email"]}))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Company", "Job Title", "Date Applied", "Status", "Priority",
        "Interview Date", "Location", "Work Type", "Employment Type",
        "Salary Range", "Contact Person", "Follow-up Date", "Source", "Job URL", "Notes"
    ])
    for a in apps:
        writer.writerow([
            a.get("company_name", ""),
            a.get("job_title", ""),
            a.get("date_applied", ""),
            a.get("status", ""),
            a.get("priority", ""),
            a.get("interview_date", ""),
            a.get("location", ""),
            a.get("work_type", ""),
            a.get("employment_type", ""),
            a.get("salary_range", ""),
            a.get("contact_person", ""),
            a.get("followup_date", ""),
            a.get("source", ""),
            a.get("job_url", ""),
            a.get("notes", ""),
        ])
    output.seek(0)
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=applications.csv"}
    )


@app.route('/jobs')
def browse_jobs():
    if not logged_in():
        return redirect('/login')
    jobs = list(jobs_collection.find().sort("_id", -1))
    return render_template('jobs.html', jobs=jobs)


@app.route('/jobs/add', methods=['GET', 'POST'])
def add_job():
    if not logged_in():
        return redirect('/login')
    if request.method == 'POST':
        data = {
            "title":            request.form.get("title"),
            "company":          request.form.get("company"),
            "location":         request.form.get("location"),
            "work_type":        request.form.get("work_type"),
            "employment_type":  request.form.get("employment_type"),
            "salary":           request.form.get("salary"),
            "source":           request.form.get("source"),
            "url":              request.form.get("url"),
            "notes":            request.form.get("notes"),
        }
        jobs_collection.insert_one(data)
        return redirect('/jobs')
    return render_template('add_job.html')


@app.route('/jobs/delete/<id>', methods=['POST'])
def delete_job(id):
    if not logged_in():
        return redirect('/login')
    jobs_collection.delete_one({"_id": ObjectId(id)})
    return redirect('/jobs')


if __name__ == '__main__':
    app.run(debug=True)