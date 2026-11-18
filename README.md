# Equipment Damage Tracker

Log faults found on stock items during the yearly equipment check, with photos, and follow each ticket until the work is done. Every change to a ticket is recorded, and pressing and holding a field (or right-clicking it on a PC) shows who changed it and when.

The design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). This is the **first version (MVP, section 11 step 1)**.

## What's in this version

- **Login** with username and password. Accounts lock for 15 minutes after 5 wrong passwords.
- **Roles made of on/off permissions** (section 4). Default roles are *User* and *Admin*. Admins can change any role, create new ones and move users between roles from the **Users** and **Roles** screens. The program refuses any change that would leave nobody able to manage users and roles. Every change is in the role change log.
- **Search** by barcode, serial number or ticket number (`T-00042`, `t42` or `42`), typed or from a handheld scanner. The cursor starts in the search box, so scanning a barcode opens the item straight away. If nothing matches, it offers to create the item with the scanned value filled in.
- **Items** with an item type, a unique barcode and a unique serial number. An item can have any number of tickets. Item edits are logged.
- **Tickets** numbered `T-00001` onwards, with Status, Fault Type, Severity, Fault Description, Photos and Work Done. Resolving and reopening need their own permissions.
- **Photos** from the phone camera or files. They're shrunk to 2000 px, location data is stripped, and they're only shown to logged-in users. Removing a photo hides it and logs who did it; the file is kept.
- **Field history**: press and hold any field (about half a second), right-click it, or tap the clock icon.
- **Two people editing at once**: the second save is refused, the latest version is shown, and what they typed is shown so it isn't lost.
- **Open tickets list**: Safety faults and High severity first, then oldest first. Filter by fault type, severity and item type.
- **Item types** screen.
- **Reports** (needs the `export` permission, which Admin has): filter tickets by creation date range, item type, status, fault type, severity and text, then view on screen or download as an Excel spreadsheet or a PDF, optionally with photos.

Not yet built: yearly checks. The `manage_checks` permission already exists so roles don't need changing later.

## Installing on the Windows PC

See **[deploy/windows/README.md](deploy/windows/README.md)**.

## Trying it on your own computer

Needs Python 3.12 or newer.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip ...
export FAULTS_DEBUG=1                             # Windows: set FAULTS_DEBUG=1
python manage.py migrate
python manage.py createsuperuser                  # gets the Admin role
python manage.py runserver
```

Then open http://127.0.0.1:8000, add an item type under **Item types**, and search for any barcode to create your first item.

Run the tests with `python manage.py test`.

## Where things are

| Path | What |
|------|------|
| `accounts/` | Users, roles, permissions, login and lockout |
| `tracker/` | Items, item types, tickets, photos, field history, search |
| `tracker/services.py` | The rules for saving tickets and writing history |
| `templates/`, `static/` | Pages, styles and the long-press script |
| `serve.py` | Starts the app with Waitress (used by the Windows service) |
| `deploy/windows/` | Install script, update script and Caddy config |
| `data/` | Database, photos and secret key when running locally (not in git). On the Windows PC they live in `C:\ProgramData\DamageTracker\data`, locked against accidental deletion |
