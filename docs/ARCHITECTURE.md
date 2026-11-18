# Equipment Damage Tracker: Architecture

**Status:** Draft v3 for review. No code yet.
**Last updated:** 2026-11-18

## 1. Purpose

Once a year, staff check the site's equipment. This program lets them log every fault they find as a **ticket** against the specific item, with photos, and follow the ticket until the work is done. Any change to a ticket is recorded, and anyone can see who changed a field and when.

### Goals

- Find an item fast by barcode, serial number or ticket number, or create it if it isn't in the system yet.
- Open a new ticket, edit an existing one, mark it resolved, or reopen a resolved one.
- Give every ticket its own identifier.
- Keep the ticket screen to four fields: Status, Fault Description, Photos, Work Done.
- Show the edit history of any field with a long press.
- Simple lists and CSV export: open tickets, tickets per yearly check, ticket history per item.

### Non-goals (for now)

- Integration with the stock system. Items are created by hand. (A CSV import of the stock system's barcodes and names can come later.)
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
| Items | Created manually in the program. Stock system can export barcodes and names (later). |
| Lookup | Enter a barcode, ticket number or serial number to find the item or ticket; create the item if it doesn't exist. |
| Tickets | Each has its own identifier. Can be created, edited, resolved and reopened. |
| Ticket fields | Status (Open, In Progress, Resolved), Fault Description (text box), Photos (shows all uploaded photos), Work Done (text box). |
| Field history | Long-press a field to see a popup of its edit history: user, date and time. |
| Connectivity | Signal everywhere, so no offline mode. |
| Hosting | A local Windows machine at work. Users open a web page from their browser. |
| Login | Username and password stored in the program. Not tied to email or Microsoft 365. |

## 3. Assumptions still to confirm

| # | Assumption |
|---|------------|
| A1 | Users reach the program over the work network from phones, tablets and PCs. It is not reachable from outside the site. |
| A2 | An **item** is one physical unit (e.g. "Ladder, serial 12345"). An item can have many tickets over the years, but normally only one open at a time. (See Q1.) |
| A3 | A barcode and a serial number each identify at most one item. An item may have a barcode, a serial number, both, or neither (then it is found by name). |
| A4 | Ticket identifiers are short numbers with a prefix, e.g. `T-00042`, so they're easy to read out or write on a tag. |
| A5 | "Resolved" is the final state, but any resolved ticket can be reopened. There's no separate "Closed". |
| A6 | On a PC, where there's no long press, a right-click or a small history icon next to the field opens the same popup. |
| A7 | Two kinds of user: normal users and an admin. |
| A8 | The Windows machine is on during working hours and is backed up. |

## 4. Users and roles

| Role | Can do |
|------|--------|
| **User** | Look up and create items, create, edit, resolve and reopen tickets, upload photos, view history. |
| **Admin** | Everything a User can, plus manage user accounts, start and close yearly checks, fix item details (e.g. a wrong barcode), and export data. |

Accounts are created by the Admin (no self sign-up). Passwords are stored hashed, never in plain text. The Admin can reset a password.

## 5. Screens and workflows

### 5.1 Home / lookup screen

After login, the user lands on one search box with a camera button for barcode scanning (see Q4):

```
┌───────────────────────────────────────┐
│  Barcode, serial or ticket number     │
│  [______________________] [Search] 📷 │
│                                       │
│  Open tickets (12)  ·  All items      │
└───────────────────────────────────────┘
```

What happens when they search:

| Input matches | Result |
|---------------|--------|
| A ticket number (e.g. `T-00042` or `42`) | Opens that ticket. |
| An item's barcode or serial number | Opens that item's page. |
| Several items (partial match or name) | Shows a short list to pick from. |
| Nothing | Offers **Create item**, with the entered value already filled in as barcode or serial. |

### 5.2 Item page

Shows the item's name, barcode and serial number, and its tickets newest first.

```
┌───────────────────────────────────────┐
│  Step ladder 3m                       │
│  Barcode 501234567  ·  Serial LD-0087 │
│                                       │
│  [ + Start new ticket ]               │
│                                       │
│  T-00042  Open         18 Nov 2026    │
│  T-00017  Resolved     12 Nov 2025    │
└───────────────────────────────────────┘
```

From here the user can open any existing ticket to edit, resolve or reopen it, or start a new one. If the item already has an open ticket, the app shows it first and asks "Start another ticket anyway?" to avoid duplicates.

### 5.3 Create item

A short form: **Name** (required), **Barcode**, **Serial number**. The value the user searched for is pre-filled. Saving checks that the barcode/serial isn't already used by another item. After saving, the app goes straight to a new ticket for that item.

### 5.4 Ticket screen

The ticket number and item name sit at the top, then the four fields:

```
┌───────────────────────────────────────┐
│  T-00042 · Step ladder 3m (LD-0087)   │
│                                       │
│  Status                               │
│  [ Open | In Progress | Resolved ]    │
│                                       │
│  Fault Description                    │
│  ┌─────────────────────────────────┐  │
│  │ Rung 4 cracked on left side     │  │
│  └─────────────────────────────────┘  │
│                                       │
│  Photos                               │
│  [img] [img] [img]  [ + Add photo ]   │
│                                       │
│  Work Done                            │
│  ┌─────────────────────────────────┐  │
│  │                                 │  │
│  └─────────────────────────────────┘  │
│                                       │
│  [ Save ]                             │
└───────────────────────────────────────┘
```

- **Status:** Open, In Progress, Resolved. A new ticket starts as Open.
- **Fault Description:** multi-line text.
- **Photos:** shows every photo uploaded to the ticket as thumbnails. Tap to view full size. **Add photo** opens the phone camera or the file picker. Photos are never silently deleted; removing one hides it and is logged.
- **Work Done:** multi-line text describing the repair or action taken.
- **Resolve:** set Status to Resolved and save. **Reopen:** on a resolved ticket, set Status back to Open (or In Progress) and save. Both are logged like any other change.
- If two people edit the same ticket at once, the second save is warned that the ticket changed and shown the latest version, so nothing is overwritten unseen.

### 5.5 Field edit history (long press)

Long-pressing (about half a second) on any field's label or box opens a popup listing every change to that field, newest first:

```
┌──────── Fault Description history ────────┐
│ 18 Nov 2026 14:32   J. Smith              │
│   "Rung 4 cracked on left side"           │
│ 18 Nov 2026 14:05   L. Sutliffe           │
│   "Rung cracked"                          │
│ 18 Nov 2026 14:05   L. Sutliffe  created  │
└───────────────────────────────────────────┘
```

- **Status:** each change shows old → new value, user, date and time. This doubles as the record of who resolved or reopened the ticket.
- **Text fields:** each entry shows the user, date and time and the text as saved at that point.
- **Photos:** each entry shows who added or removed which photo, and when.
- On a PC the same popup opens by right-click or a small clock icon beside the field (A6).
- Times are shown in UK local time.

### 5.6 Yearly checks (Admin)

The Admin starts a **Check** (e.g. "Annual check 2026") when the yearly inspection begins and closes it when done. Every ticket created while a check is open is tagged with it automatically; the user never has to pick it. This allows "all faults found in the 2026 check" reports and year-on-year comparison.

### 5.7 Lists and export

- **Open tickets:** everything Open or In Progress, oldest first.
- **Check summary:** tickets created during a chosen check, by status.
- **Item history:** every ticket for one item.
- **Export:** any list to CSV (opens in Excel). A printable ticket sheet with photos.

## 6. Data model

```
Item 1──* Ticket
Check 1──* Ticket  (optional)
Ticket 1──* Photo
Ticket 1──* FieldChange
User 1──* FieldChange
```

| Entity | Key fields |
|--------|-----------|
| **User** | id, username, display_name, password_hash, is_admin, active, created_at |
| **Item** | id, name, barcode (unique, optional), serial_number (unique, optional), notes, created_by, created_at, active |
| **Check** | id, name, started_on, closed_on |
| **Ticket** | id, number (unique, shown as `T-00042`), item_id, check_id (nullable), status, fault_description, work_done, created_by, created_at, updated_at, version |
| **Photo** | id, ticket_id, file_name, thumbnail_file_name, content_type, size, uploaded_by, uploaded_at, removed_by, removed_at |
| **FieldChange** | id, ticket_id, field (`status`, `fault_description`, `work_done`, `photos`), old_value, new_value, user_id, changed_at |

Notes:

- **Field history** comes from FieldChange. Every save compares the old and new value of each field and writes one row per changed field, in the same database transaction as the save, so history can never be missing or out of step. The long-press popup is just "FieldChange rows for this ticket and field, newest first". Creating a ticket writes a "created" row for each filled-in field.
- Item edits (name, barcode, serial) are logged the same way in an **ItemChange** table with the same shape, so wrong barcodes can be traced.
- `version` on Ticket is a counter that goes up on each save; it's how the app detects two people editing at once (5.4).
- Nothing is hard-deleted. Photos are marked removed; items and users are deactivated.

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
│  │ Web application (Windows service)     │  │
│  │  - login and sessions                 │  │
│  │  - lookup, item and ticket screens    │  │
│  │  - change tracking (FieldChange)      │  │
│  │  - photo upload, resize, thumbnails   │  │
│  │  - lists, CSV export, print sheets    │  │
│  │  - admin                              │  │
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

A single program that serves the pages and holds all the rules. Pages are built on the server and kept simple, with large touch targets. A small amount of JavaScript handles the long press, the history popup, photo previews and barcode scanning. No app needs installing.

### 7.2 Database

**SQLite**: a single file, no database server to run. It comfortably handles 5 concurrent users at this volume. The data model moves to PostgreSQL or SQL Server unchanged if ever needed.

### 7.3 Photos

Uploaded photos are resized (longest edge about 2000 px) and saved in a folder on the machine, with a thumbnail for the ticket screen. Files get random names, not user-supplied ones, and are only served to logged-in users.

### 7.4 Running on Windows

- Installed as a Windows service so it starts with the machine and restarts if it crashes.
- One Windows Firewall rule opens the program's port to the local network only.
- Staff use a short address such as `http://faults-pc:8000`, saved as a bookmark or home-screen shortcut.

### 7.5 Backups

A scheduled task copies the database file and photos folder every night to a second place (network share, external drive, or OneDrive-synced folder), keeping about 30 days of copies. Restore is "stop service, copy files back, start service".

## 8. Tech stack

### Option A: Python + Django (recommended)

- **Framework:** Django. Includes username/password login, password hashing, sessions, permissions and an admin site for users and checks.
- **Pages:** Django templates, a small CSS framework (e.g. Bootstrap or Pico.css), and HTMX for the history popup and photo uploads without full page reloads.
- **Long press:** a few lines of plain JavaScript (pointer events with a ~500 ms timer, plus right-click and a history icon for PCs).
- **Barcode scanning:** the browser's BarcodeDetector API where available (Chrome/Edge on Android), with a JavaScript library such as ZXing as a fallback for iPhones.
- **Database:** SQLite (built in).
- **Photos:** Pillow for resizing and thumbnails.
- **Running on Windows:** Waitress web server wrapped as a Windows service with NSSM or WinSW.

Why: login, admin and database handling come out of the box, so the effort goes into the lookup and ticket screens. Runs well on Windows with nothing else to install.

### Option B: Node.js + TypeScript

Express or Fastify with server-rendered pages or a small React front end, SQLite via Prisma or Drizzle, run as a Windows service. Fine if you'd rather work in JavaScript, but login, sessions and admin screens have to be built or assembled.

### Option C: Microsoft 365 (Power Apps + SharePoint lists)

Not recommended: you'd prefer local logins, and per-field history with a long-press popup is awkward to build in Power Apps.

### Recommendation

**Option A: Django + SQLite + Waitress as a Windows service, with nightly backups.**

## 9. Security

- Passwords stored with a strong hash. Minimum length enforced. Lock out after repeated failed logins.
- Every page and photo requires login; admin pages require the admin role.
- Framework defaults protect against CSRF, XSS and SQL injection.
- Uploads limited to image types and a maximum size.
- **HTTPS:** plain HTTP on the local network is simplest, but passwords then cross the Wi-Fi unencrypted. Note that some phone browsers only allow live camera access for barcode scanning over HTTPS. Recommended: an internal certificate or a reverse proxy such as Caddy. See Q5.
- Firewall rule restricts access to the local network.

## 10. Non-functional requirements

| Area | Target |
|------|--------|
| Speed | Lookup result and ticket screen in under 2 s on a phone over the site Wi-Fi. |
| Availability | Working hours, while the Windows machine is on. |
| Capacity | 5 concurrent users; tens of thousands of photos before disk space needs a look. |
| Retention | Keep all items, tickets, photos and history indefinitely unless told otherwise. |
| Usability | Large touch targets; finding an item and starting a ticket takes two screens. |
| Browsers | Current Chrome/Safari/Edge on phones and PCs. |

## 11. Delivery plan (suggested)

1. **MVP:** login, lookup by barcode/serial/ticket number (typed), create item, ticket screen with the four fields, photo upload and display, resolve/reopen, field change history with long-press popup, open-tickets list. Install as a Windows service with nightly backup.
2. **Phase 2:** camera barcode scanning, yearly checks and check summary, CSV export, printable ticket sheet, HTTPS.
3. **Later (optional):** import items from the stock system's barcode export, move to a server.

## 12. Open questions for Leon

1. **One open ticket per item?** Should the app block a second open ticket on the same item, warn (current design), or allow it freely?
2. **Item fields:** Is Name + Barcode + Serial number enough for an item, or do you also want e.g. item type, location or notes?
3. **Ticket number format:** Is `T-00042` fine, or do you have an existing numbering scheme (e.g. a year prefix like `2026-0042`)?
4. **Barcode scanning:** Will people type/paste barcodes, use the phone camera, or use a handheld USB/Bluetooth scanner? (A handheld scanner just "types" into the search box, so it works with no extra effort.)
5. **HTTPS:** Is plain HTTP acceptable on your internal network, given that phone camera scanning may need HTTPS?
6. **Who can reopen and edit?** Can any user reopen a resolved ticket and edit its text, or only the admin?
7. **Backups:** Where should nightly backups go?
8. **The Windows machine:** Desktop PC or server? On all day? Who handles Windows updates?
