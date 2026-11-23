# Appointment Booking and Reminder System

Students submit campus appointment requests and see their status on the dashboard. A request stays pending until a teacher approves it in the Teacher Panel. The dashboard shows reminders for approved appointments scheduled within the next 24 hours. The app uses Python, Flask, SQLite, HTML and CSS.

## Run locally on Windows

Open PowerShell in the folder containing app.py and run:

    python -m pip install -r requirements.txt
    $env:TEACHER_PASSWORD = 'replace-with-your-teacher-password'
    python app.py

Choose your own password and open http://127.0.0.1:5000. Use the same password to sign in to the Teacher Panel. This college demo has a shared student dashboard and a separate teacher sign-in.

## Demonstration

1. Submit an appointment request for a time within the next 24 hours.
2. Check that the student dashboard shows Pending approval.
3. Open Teacher Panel, sign in, review the details, and click Approve.
4. Return to the dashboard to see Approved and the reminder.
5. Edit the request to send the changed details back for review. You can also cancel either a pending or an approved request.

## Database

SQLite stores the requests in instance/appointments.db. On startup, bookings from before the approval feature enter the pending queue. Existing cancelled records keep their status. Approved requests stay approved after an app restart unless they are changed or cancelled.
