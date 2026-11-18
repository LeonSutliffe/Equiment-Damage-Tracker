# Equipment Damage Tracker: Architecture

**Status:** Draft v2 for review. No code yet.
**Last updated:** 2026-11-18

## 1. Purpose

Once a year, staff check the site's equipment and stock items. Today the faults they find are recorded informally. This program gives them one place to log every fault found during the check, with photos, and to follow each fault until it is dealt with (repaired, replaced, written off).

### Goals

- Log a fault in under a minute from a phone or PC while walking the site.
- Attach one or more photos to each fault.
- Group faults by the yearly check they were found in, so each year can be reviewed and compared.
- Track each fault from "found" to "closed".
- Simple reports and CSV export: faults per check, per item type, per location, still open.
- Keep a history of who changed what and when.

### Non-goals (for now)

- Integration with the stock system. Item types are created by hand. (A CSV import from the stock system's barcode and name export can be added later.)
- Email, Microsoft 365 or single sign-on. Users log in with a name and password.
- Offline use. Every area has signal.
- Hosting on the internet. The program runs on one Windows machine on the work network.

## 2. Confirmed requirements

From Leon, 2026-11-18:

| Topic | Answer |
|-------|--------|
| Sites | One site. |
| Users | Up to about 5 at the same time. |
| Volume | Low. Mostly during the yearly equipment check. |
| Use case | Log every fault found during the yearly check, with photos. |
| Items | Item types created manually in the program for now. Stock system can export barcodes and names (later). |
| Connectivity | Signal everywhere, so no offline mode. |
| Hosting | A local Windows machine at work. Users open a web page from their browser. |
| Login | Username and password stored in the program. Not tied to email or Microsoft 365. |

## 3. Assumptions still to confirm

| # | Assumption |
|---|------------|
| A1 | Users reach the program over the work Wi-Fi/network from phones, tablets and PCs. It is not reachable from outside the site. |
| A2 | The check records **faults only**, not a pass/fail line for every item checked. (See Q1.) |
| A3 | A fault can be logged against an item type, with an optional identifier for the specific unit (asset tag, serial number or barcode) and where it is. |
| A4 | There are two kinds of user: normal users and an admin. (See Q2.) |
| A5 | The Windows machine is left on during working hours and is backed up. |

## 4. Users and roles

| Role | Can do |
|------|--------|
| **User** | Log faults, add photos and comments, view all faults, change status of faults. |
| **Admin** | Everything a User can, plus manage user accounts, item types, locations, fault categories, start and close yearly checks, reopen closed faults, and export data. |

Accounts are created by the Admin (no self sign-up). Passwords are stored hashed, never in plain text. The Admin can reset a password.

## 5. Core workflows

### 5.1 Start a yearly check (Admin)

The Admin creates a **Check**, e.g. "Annual check 2026", with a start date. While a check is open, every new fault is attached to it automatically. When the check is finished the Admin closes it; faults logged after that are not part of it (they can still be logged as "ad-hoc" faults outside any check).

### 5.2 Log a fault

1. User opens the program in their browser and logs in.
2. Taps **Log fault**.
3. Picks the **item type** from a searchable list (or, if allowed, creates a new one on the spot; see Q3).
4. Optionally enters the unit identifier (asset tag / serial / barcode) and quantity affected.
5. Picks the **location** (e.g. "Workshop", "Store room 2") and a **fault category** (e.g. broken, worn, missing parts, electrical, safety), sets **severity** (minor / needs repair / unsafe, do not use) and writes a short description.
6. Takes photos with the phone camera or attaches files from the PC.
7. Saves. The fault gets a reference such as `F-2026-0042` and status **Open**.

"Unsafe, do not use" faults are highlighted at the top of the list.

### 5.3 Deal with a fault

Status lifecycle:

```
Open ──► In progress ──► Resolved ──► Closed
  │                                     ▲
  └──► No action needed ────────────────┘
```

- **In progress:** someone is dealing with it (repair booked, replacement ordered).
- **Resolved:** record the outcome (repaired, replaced, written off, other) and an optional cost.
- **Closed:** locked. Only the Admin can reopen it.
- Comments can be added at any time. Every change is written to the history.

### 5.4 Review and report

- **Check summary:** for a chosen check, the number of faults by status, category, severity, location and item type.
- **Open faults list:** everything not yet closed, oldest first, unsafe items first.
- **Year-on-year:** faults per check, to see whether things are getting better or worse.
- **Item type history:** every fault logged against an item type across all years.
- **Export:** any filtered list to CSV (opens in Excel). A printable fault sheet with photos for a single fault or a whole check.

### 5.5 Administration

- Create, rename and deactivate item types, locations and fault categories.
- Create and deactivate user accounts, reset passwords.
- Start and close checks.
- Later: import item types from the stock system's CSV export.

## 6. Data model

```
Check 1──* Fault
ItemType 1──* Fault
Location 1──* Fault
FaultCategory 1──* Fault
Fault 1──* Photo
Fault 1──* Comment
Fault 1──* HistoryEntry
User 1──* Fault (reported_by)
```

| Entity | Key fields |
|--------|-----------|
| **User** | id, username, display_name, password_hash, is_admin, active, created_at |
| **Check** | id, name, started_on, closed_on, notes |
| **ItemType** | id, name, description, barcode (optional), active |
| **Location** | id, name, active |
| **FaultCategory** | id, name, active |
| **Fault** | id, reference, check_id (nullable for ad-hoc), item_type_id, unit_identifier, quantity, location_id, category_id, severity, description, status, outcome, cost, reported_by, reported_at, resolved_at, closed_at, updated_at |
| **Photo** | id, fault_id, file_name, thumbnail_file_name, content_type, size, uploaded_by, created_at |
| **Comment** | id, fault_id, author_id, body, created_at |
| **HistoryEntry** | id, fault_id, user_id, action, field, old_value, new_value, created_at |

Notes:

- Nothing is hard-deleted. Faults are closed; item types, locations and users are deactivated.
- `barcode` on ItemType is optional now, so the stock system's export can be matched later.
- If a specific unit needs its own history (e.g. "drill #7 has failed three years running"), an **Item** table (one row per physical unit) can be added between ItemType and Fault. Not needed for the first version. See Q4.

## 7. Components

Everything runs on the one Windows machine.

```
 Phones / tablets / PCs on the work network
            │  browser, http(s)://<server-name>:<port>
            ▼
┌─────────────────────────────────────────────┐
│  Windows machine                            │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │ Web application (runs as a Windows    │  │
│  │ service, starts with the machine)     │  │
│  │  - login and sessions                 │  │
│  │  - pages: log fault, lists, reports,  │  │
│  │    admin                              │  │
│  │  - photo upload, resize, thumbnails   │  │
│  │  - CSV export, printable sheets       │  │
│  └───────────┬─────────────────┬─────────┘  │
│              │                 │            │
│  ┌───────────▼───────┐  ┌──────▼─────────┐  │
│  │ Database file      │  │ Photos folder  │  │
│  │ (SQLite)           │  │ on local disk  │  │
│  └────────────────────┘  └────────────────┘  │
│                                             │
│  Nightly backup ──► network share / USB /   │
│                     OneDrive folder          │
└─────────────────────────────────────────────┘
```

### 7.1 Web application

A single program that serves the web pages and handles all the logic. Pages are built on the server and kept simple, with large buttons so they work well on a phone. The phone's camera is used through the browser's normal file/photo picker, so no app needs installing.

### 7.2 Database

**SQLite**: a single file on disk, no separate database server to install or maintain. It handles 5 concurrent users and this volume with ease. If the program ever moves to a bigger setup, the same data model moves to PostgreSQL or SQL Server.

### 7.3 Photos

Uploaded photos are resized (e.g. longest edge 2000 px) and saved in a folder on the machine, with a small thumbnail for lists. File names are random IDs, not user-supplied names. Photos are only served to logged-in users.

### 7.4 Running on Windows

- The program is installed as a Windows service so it starts automatically when the machine boots and restarts if it crashes.
- Windows Firewall gets one inbound rule for the program's port, limited to the local network.
- Staff use a short address such as `http://faults-pc:8000`, or a bookmark / home-screen shortcut.

### 7.5 Backups

A scheduled task copies the database file and photos folder every night to a second place (a network share, an external drive, or a OneDrive-synced folder), keeping e.g. 30 days of copies. Restore is "stop service, copy files back, start service". This is the most important operational piece, since everything lives on one machine.

## 8. Tech stack

### Option A: Python + Django (recommended)

- **Framework:** Django. It includes username/password login, password hashing, sessions, a permission system and a ready-made admin site for managing item types, locations, categories and users.
- **Pages:** Django templates with a small CSS framework (e.g. Bootstrap or Pico.css) for a mobile-friendly layout; a little HTMX for smoother forms if wanted.
- **Database:** SQLite (built in).
- **Photos:** Pillow library for resizing and thumbnails.
- **Running on Windows:** Waitress (a production web server that works on Windows) wrapped as a Windows service with NSSM or WinSW.
- **Reports/export:** Python's built-in CSV module; printable pages via the browser's print-to-PDF.

Why: it covers the login, admin and database needs out of the box, so most of the effort goes into the fault screens. It runs well on Windows with no extra servers, and it's easy to read and maintain for one person.

### Option B: Node.js + TypeScript

Express or Fastify with server-rendered pages (or a small React front end), SQLite via Prisma or Drizzle, run as a Windows service. A good fit if you'd rather work in JavaScript, but login, sessions and admin screens all need to be built or assembled from libraries.

### Option C: Microsoft 365 (Power Apps + SharePoint lists)

Since the workplace has Microsoft 365, a Power App over SharePoint lists could do this without hosting anything. Not recommended here because you'd prefer local logins over Microsoft accounts, and Power Apps licensing and customisation limits can get in the way.

### Recommendation

**Option A: Django + SQLite + Waitress, as a Windows service, with nightly backups.** It's the least moving parts for one site and five users, and nothing about it stops a later move to a proper server or the cloud.

## 9. Security

The program is only on the internal network, but it still holds staff logins.

- Passwords stored with a strong hash (Django's default PBKDF2 or Argon2). Minimum length enforced. Lock out after repeated failed logins.
- Every page and photo requires login; admin pages require the admin role.
- Protection against common web attacks (CSRF, XSS, SQL injection) via the framework defaults.
- Uploads limited to image types and a maximum size.
- **HTTPS:** plain HTTP on the local network is the simplest start, but passwords then cross the Wi-Fi unencrypted. Recommended: a self-signed or internal certificate, or a reverse proxy such as Caddy in front of the app. See Q5.
- Firewall rule restricts access to the local network.

## 10. Non-functional requirements

| Area | Target |
|------|--------|
| Speed | Pages load in under 2 s on a phone over the site Wi-Fi. |
| Availability | Working hours, while the Windows machine is on. |
| Capacity | 5 concurrent users; tens of thousands of photos before disk space needs a look. |
| Retention | Keep all checks and faults indefinitely unless told otherwise. |
| Usability | Large touch targets; logging a fault takes at most one screen plus photos. |
| Browsers | Current Chrome/Safari/Edge on phones and PCs. |

## 11. Delivery plan (suggested)

1. **MVP:** login, user/item type/location/category admin, start a check, log fault with photos, fault list and detail, status changes, history, CSV export. Install as a Windows service with nightly backup.
2. **Phase 2:** check summary and year-on-year reports, printable fault sheets, HTTPS.
3. **Later (optional):** import item types from the stock system's barcode export, barcode scanning, per-unit item history, move to a server or cloud host.

## 12. Open questions for Leon

1. **Faults only, or every item?** Should the check record only faults, or a pass/fail line for every item checked (so you can prove an item was checked and was fine)?
2. **Roles:** Is "normal user + admin" enough, or do you need someone who can view but not edit, or someone who approves outcomes?
3. **Item types:** Can any user add a new item type while logging a fault, or only the admin?
4. **Individual units:** Do you need to track specific units (e.g. "ladder #3") over the years, or is the item type plus a free-text identifier enough?
5. **HTTPS:** Is plain HTTP acceptable on your internal network for now, or should we set up HTTPS from day one?
6. **Backups:** Where should nightly backups go (network share, external drive, OneDrive folder)?
7. **The Windows machine:** Is it a normal desktop PC or a server? Is it on all day and is anyone responsible for Windows updates on it?
8. **After a fault:** What outcomes do you need (repaired, replaced, written off, other)? Do you want to record cost?
