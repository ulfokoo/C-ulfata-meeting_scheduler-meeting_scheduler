# Meeting Log — Flask web app

A small multi-user web app to log partner/branch meetings: agenda, discussion
points, decisions, action items, attendees, ideas, and status — with each
user only seeing their own meetings.

## Features
- User registration and login (passwords hashed, sessions via Flask-Login)
- Each user has their own private list of meetings
- Add / edit / delete / view meetings
- Dashboard with counts and status filters (Scheduled, Completed,
  Follow-up Needed, Cancelled)
- SQLite database (created automatically on first run, no setup needed)

## Run it locally

```bash
cd meeting_scheduler
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 app.py
```

Then open **http://127.0.0.1:5000** in your browser. Click "Create an
account", register, log in, and start logging meetings.

The database file `scheduler.db` is created automatically in the project
folder the first time you run the app.

## Project structure

```
meeting_scheduler/
├── app.py                # Flask app: models, auth, meeting routes
├── requirements.txt
├── static/
│   └── style.css
└── templates/
    ├── base.html
    ├── login.html
    ├── register.html
    ├── dashboard.html
    ├── meeting_form.html     # used for both "add" and "edit"
    └── meeting_detail.html
```

## Notes for going to production
- Set a real `SECRET_KEY` environment variable instead of the dev default.
- Switch `debug=True` off in `app.py`.
- Consider Postgres instead of SQLite if multiple people will use it at once.
- Add HTTPS / a proper WSGI server (e.g. gunicorn) behind a reverse proxy.
