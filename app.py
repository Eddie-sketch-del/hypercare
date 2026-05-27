from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import requests
import json
import os

app = Flask(__name__, static_folder='.')
CORS(app)

# Database setup
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hypercare.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'hypercare-secret-key-2024'
db = SQLAlchemy(app)

# =============================================
# WIGAL FROG API CREDENTIALS
# =============================================
FROG_API_KEY = "$2a$10$w49jQNCs1QcGIVcodv0y9OkRWxJKob83WxUJ/tQEU.9IojEJf7fPC"
FROG_USERNAME = "Eddie"
FROG_CALLER_ID = "233308249886"
FROG_MED_AUDIO_URL = "https://res.cloudinary.com/dqnceqtxf/video/upload/v1779874586/Medication.mp31_G711.org__1_iejruj.wav"
FROG_LIFE_AUDIO_URL = "https://res.cloudinary.com/dqnceqtxf/video/upload/v1779874753/Lifestyle.mp3copy_G711.org__1_jvr209.wav"

# =============================================
# IMPORTANT: Update this with your current ngrok URL
# =============================================
CALLBACK_BASE_URL = "https://dismantle-transpire-pegboard.ngrok-free.dev"

# Store which audio to play for each call
call_audio_map = {}

# =============================================
# DATABASE MODELS
# =============================================

class Nurse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    systolic = db.Column(db.Integer, nullable=False)
    diastolic = db.Column(db.Integer, nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

class CallLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    patient_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    call_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    med_time = db.Column(db.String(10), default="08:00")
    med_days = db.Column(db.String(100), default="Mon,Tue,Wed,Thu,Fri,Sat,Sun")
    med_active = db.Column(db.Boolean, default=True)
    life_time = db.Column(db.String(10), default="12:00")
    life_days = db.Column(db.String(100), default="Mon,Wed,Fri")
    life_active = db.Column(db.Boolean, default=True)

# =============================================
# HELPER FUNCTIONS
# =============================================

def format_phone(phone):
    phone = str(phone).strip().replace(" ", "")
    if phone.startswith("0"):
        phone = "233" + phone[1:]
    elif phone.startswith("+"):
        phone = phone[1:]
    return phone

def make_voice_call(phone, audio_url, call_type, patient_id, patient_name):
    url = "https://frogapi.wigal.com.gh/api/v3/voice/send"
    headers = {
        "Content-Type": "application/json",
        "API-KEY": FROG_API_KEY,
        "USERNAME": FROG_USERNAME
    }
    msgid = f"MSG{patient_id}{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    
    # Store audio URL for callback
    call_audio_map[msgid] = audio_url
    
    payload = {
        "callerid": FROG_CALLER_ID,
        "soundurl": audio_url,
        "servicetype": "CALL",
        "callbackurl": f"{CALLBACK_BASE_URL}/api/voice/callback",
        "destinations": [
            {
                "destination": format_phone(phone),
                "msgid": msgid
            }
        ]
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        result = response.json()
        status = "answered" if response.status_code == 200 else "missed"
        print(f"Call to {patient_name} ({phone}): {result}")
    except Exception as e:
        status = "missed"
        print(f"Call failed for {patient_name}: {str(e)}")

    log = CallLog(
        patient_id=patient_id,
        patient_name=patient_name,
        phone=phone,
        call_type=call_type,
        status=status
    )
    db.session.add(log)
    db.session.commit()

def send_calls(call_type):
    with app.app_context():
        patients = Patient.query.filter_by(is_active=True).all()
        audio_url = FROG_MED_AUDIO_URL if call_type == "medication" else FROG_LIFE_AUDIO_URL
        for patient in patients:
            make_voice_call(patient.phone, audio_url, call_type, patient.id, patient.name)
            print(f"Call sent to {patient.name} - {call_type}")

# =============================================
# SCHEDULER
# =============================================

scheduler = BackgroundScheduler()

def setup_scheduler():
    with app.app_context():
        schedule = Schedule.query.first()
        if schedule:
            if schedule.med_active:
                hour, minute = schedule.med_time.split(":")
                scheduler.add_job(
                    func=lambda: send_calls("medication"),
                    trigger="cron",
                    hour=int(hour),
                    minute=int(minute),
                    id="med_job",
                    replace_existing=True
                )
            if schedule.life_active:
                hour, minute = schedule.life_time.split(":")
                scheduler.add_job(
                    func=lambda: send_calls("lifestyle"),
                    trigger="cron",
                    hour=int(hour),
                    minute=int(minute),
                    id="life_job",
                    replace_existing=True
                )

# =============================================
# SERVE FRONTEND
# =============================================

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# =============================================
# VOICE CALLBACK
# =============================================

@app.route("/api/voice/callback", methods=["POST"])
def voice_callback():
    try:
        data = request.get_json()
        print(f"Voice callback received: {data}")
        
        event = data.get("event", "")
        msgid = data.get("clientid", "")
        channelid = data.get("channelid", "")
        batchid = data.get("batchid", "")
        callfrom = data.get("callfrom", "")
        callto = data.get("callto", "")
        
        # Get the audio URL for this call
        audio_url = call_audio_map.get(msgid, FROG_MED_AUDIO_URL)
        
        if event == "ANSWERED":
            print(f"Patient answered! Playing audio: {audio_url}")
            return jsonify({
                "channelid": channelid,
                "action": "PLAY",
                "soundurl": audio_url,
                "batchid": batchid,
                "callfrom": callfrom,
                "callto": callto,
                "clientid": msgid
            })
        elif event == "PlaybackFinished":
            print(f"Playback finished for {callto} - disconnecting")
            return jsonify({
                "channelid": channelid,
                "action": "DISCONNECT",
                "batchid": batchid,
                "callfrom": callfrom,
                "callto": callto,
                "clientid": msgid
            })
        else:
            print(f"Event received: {event}")
            return jsonify({"status": "ok"})
    except Exception as e:
        print(f"Callback error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})

# =============================================
# API ROUTES
# =============================================

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    nurse = Nurse.query.filter_by(username=data.get("username")).first()
    if nurse and nurse.password == data.get("password"):
        return jsonify({"success": True, "name": nurse.name, "message": "Login successful"})
    return jsonify({"success": False, "message": "Invalid username or password"}), 401

@app.route("/api/patients", methods=["GET"])
def get_patients():
    patients = Patient.query.order_by(Patient.date_added.desc()).all()
    return jsonify([{
        "id": p.id,
        "name": p.name,
        "phone": p.phone,
        "systolic": p.systolic,
        "diastolic": p.diastolic,
        "date_added": p.date_added.strftime("%d/%m/%Y"),
        "is_active": p.is_active
    } for p in patients])

@app.route("/api/patients", methods=["POST"])
def add_patient():
    data = request.get_json()
    patient = Patient(
        name=data["name"],
        phone=data["phone"],
        systolic=data["systolic"],
        diastolic=data["diastolic"]
    )
    db.session.add(patient)
    db.session.commit()
    return jsonify({"success": True, "message": "Patient added successfully"})

@app.route("/api/patients/<int:patient_id>", methods=["DELETE"])
def delete_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    db.session.delete(patient)
    db.session.commit()
    return jsonify({"success": True, "message": "Patient removed"})

@app.route("/api/calls", methods=["GET"])
def get_calls():
    calls = CallLog.query.order_by(CallLog.timestamp.desc()).limit(50).all()
    return jsonify([{
        "id": c.id,
        "patient_name": c.patient_name,
        "phone": c.phone,
        "call_type": c.call_type,
        "status": c.status,
        "timestamp": c.timestamp.strftime("%d/%m/%Y %I:%M %p")
    } for c in calls])

@app.route("/api/calls/stats", methods=["GET"])
def get_stats():
    today = datetime.utcnow().date()
    total_patients = Patient.query.filter_by(is_active=True).count()
    answered_today = CallLog.query.filter(
        db.func.date(CallLog.timestamp) == today,
        CallLog.status == "answered"
    ).count()
    missed_today = CallLog.query.filter(
        db.func.date(CallLog.timestamp) == today,
        CallLog.status == "missed"
    ).count()
    return jsonify({
        "total_patients": total_patients,
        "answered_today": answered_today,
        "missed_today": missed_today
    })

@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    schedule = Schedule.query.first()
    if not schedule:
        schedule = Schedule()
        db.session.add(schedule)
        db.session.commit()
    return jsonify({
        "med_time": schedule.med_time,
        "med_days": schedule.med_days,
        "med_active": schedule.med_active,
        "life_time": schedule.life_time,
        "life_days": schedule.life_days,
        "life_active": schedule.life_active
    })

@app.route("/api/schedule", methods=["POST"])
def update_schedule():
    data = request.get_json()
    schedule = Schedule.query.first()
    if not schedule:
        schedule = Schedule()
        db.session.add(schedule)
    schedule.med_time = data.get("med_time", schedule.med_time)
    schedule.med_days = data.get("med_days", schedule.med_days)
    schedule.med_active = data.get("med_active", schedule.med_active)
    schedule.life_time = data.get("life_time", schedule.life_time)
    schedule.life_days = data.get("life_days", schedule.life_days)
    schedule.life_active = data.get("life_active", schedule.life_active)
    db.session.commit()
    setup_scheduler()
    return jsonify({"success": True, "message": "Schedule updated successfully"})

@app.route("/api/calls/trigger", methods=["POST"])
def trigger_calls():
    data = request.get_json()
    call_type = data.get("call_type", "medication")
    send_calls(call_type)
    return jsonify({"success": True, "message": f"{call_type} calls triggered successfully"})

# =============================================
# INITIALIZE DATABASE AND RUN
# =============================================

def init_db():
    with app.app_context():
        db.create_all()
        if not Nurse.query.first():
            nurse = Nurse(name="Nurse", username="nurse", password="1234")
            db.session.add(nurse)
        if not Schedule.query.first():
            schedule = Schedule()
            db.session.add(schedule)
        db.session.commit()
        print("Database initialized successfully!")

if __name__ == "__main__":
    init_db()
    setup_scheduler()
    scheduler.start()
    print("HyperCare backend is running!")
    print("Open your browser and go to http://localhost:5000")
    app.run(debug=True, port=5000)
