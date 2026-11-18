# Equipment Damage Tracker: Architecture

**Status:** v7. All open questions answered. The MVP (section 11, step 1) is built; see README.md.
**Last updated:** 2026-11-18

## 1. Purpose

Once a year, staff check the site's equipment. This program lets them log every fault they find as a **ticket** against the specific item, with photos, and follow the ticket until the work is done. Any change to a ticket is recorded, and anyone can see who changed a field and when.

### Goals

- Find an item fast by barcode, serial number or ticket number, or create it if it isn't in the system yet.
- Open a new ticket, edit an existing one, mark it resolved, or reopen a resolved one.
- Give every ticket its own identifier.
- Keep the ticket screen short: Status, Fault Type, Severity, Fault Description, Photos, Work Done.
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
| Items | Every stock item has two unique identifiers, a barcode and a serial number, plus an item type shared by items of the same kind. Created manually in the program (stock system export later). |
| Lookup | Enter a barcode, ticket number or serial number to find the item or ticket; create the item if it doesn't exist. |
| Tickets | Each has its own identifier. Can be created, edited, resolved and reopened. |
| Ticket fields | Status (Open, Repair in Progress, Resolved), Fault Type (Cosmetic, Functionality, Safety), Severity, Fault Description (text box), Photos (shows all uploaded photos), Work Done (text box). |
| Item vs ticket | An item is one physical unit and can have many tickets over the years. Ticket numbers look like `T-00042`. Resolved is the final state, but any resolved ticket can be reopened. |
| Access | Local network only. |
| Field history | Long-press a field to see a popup of its edit history: user, date and time. |
| Connectivity | Signal everywhere, so no offline mode. |
| Hosting | A local Windows machine at work. Users open a web page from their browser. |
| Login | Username and password stored in the program. Not tied to email or Microsoft 365. |

## 3. Decisions

Confirmed by Leon on 2026-11-18:

- An item is one physical unit with many tickets over time. **An item can have several open tickets at once, with no warning.**
- Ticket numbers look like `T-00042`.
- Resolved is the final status, but any resolved ticket can be reopened.
- Access is over the local network only.
- Severity has three levels: **Low**, **Medium**, **High**.
- On a PC, where there's no long press, a right-click or a small history icon next to the field opens the same history popup.
- Permissions are configurable per role by an admin, and any user can be given admin rights. The default User and Admin roles in section 4 are the starting point.
- Item types are a list managed in the program (e.g. "Step ladder 3m", "Drill 18V"). By default only roles with `manage_item_types` can add or rename them.
- Barcodes are **typed in by hand or read with a handheld scanner**. No phone camera scanning.
- The program is served over **HTTPS**.
- The host is a **desktop PC running Windows Home**, switched on during working hours. It may be migrated to another machine later.
- No backups are needed for now (see 7.7).
- Tech stack: Option A (Django).

## 4. Users, roles and permissions

Permissions are not hard-coded to roles. Each **permission** is a single switch, each **role** is a named set of switches, and each user has one role. An admin can change which switches a role has, create new roles, and move any user to a different role, all from the **Roles** and **Users** screens. That means a normal user can be given admin rights at any time, either by moving them to the Admin role or by switching on individual permissions for their role.

### Permissions

| Permission | Allows |
|------------|--------|
| `view` | Search, view items, tickets, photos and field history. |
| `create_item` | Create new items. |
| `edit_item` | Change an item's type, barcode or serial number. |
| `create_ticket` | Start new tickets. |
| `edit_ticket` | Change ticket fields and add photos. |
| `resolve_ticket` | Set a ticket to Resolved. |
| `reopen_ticket` | Reopen a resolved ticket. |
| `remove_photo` | Hide a photo from a ticket (it is kept and the removal is logged). |
| `manage_item_types` | Add, rename and deactivate item types. |
| `manage_checks` | Start and close yearly checks. |
| `export` | Export lists to CSV and print ticket sheets. |
| `manage_users` | Create and deactivate users, reset passwords, change a user's role. |
| `manage_roles` | Create roles and change which permissions each role has. |

### Default roles

These are set up on first install and can be changed afterwards.

| Role | Permissions |
|------|-------------|
| **User** | `view`, `create_item`, `create_ticket`, `edit_ticket`, `resolve_ticket`, `reopen_ticket` |
| **Admin** | All permissions |

### Roles screen (admin)

```
┌───────────── Roles ─────────────┐
│ Role: [ User            ▼ ]     │
│                                 │
│ [x] View                        │
│ [x] Create item                 │
│ [ ] Edit item                   │
│ [x] Create ticket               │
│ [x] Edit ticket                 │
│ [x] Resolve ticket              │
│ [x] Reopen ticket               │
│ [ ] Remove photo                │
│ [ ] Manage item types           │
│ [ ] Manage checks               │
│ [ ] Export                      │
│ [ ] Manage users                │
│ [ ] Manage roles                │
│                                 │
│ [ Save ]     [ + New role ]     │
└─────────────────────────────────┘
```

### Rules

- Every request is checked on the server against the user's role, so hiding a button is never the only protection.
- A change to a role takes effect for its users on their next page load.
- The program refuses any change that would leave **no active user with `manage_roles` and `manage_users`**, so nobody can lock everyone out.
- Every change to a role's permissions or a user's role is recorded (who, what, when) in a **PermissionChange** history, viewable by admins.
- Accounts are created by someone with `manage_users` (no self sign-up). Passwords are stored hashed, never in plain text, and can be reset by an admin.

## 5. Screens and workflows

### 5.1 Home / lookup screen

After login, the user lands on one search box. The cursor is already in it, so a handheld scanner can be used straight away: the scanner "types" the barcode and presses Enter, which runs the search. Typing a barcode, serial or ticket number by hand and pressing Search works the same way.

```
┌───────────────────────────────────────┐
│  Barcode, serial or ticket number     │
│  [______________________] [Search]    │
│                                       │
│  Open tickets (12)  ·  All items      │
└───────────────────────────────────────┘
```

What happens when they search:

| Input matches | Result |
|---------------|--------|
| A ticket number (e.g. `T-00042` or `42`) | Opens that ticket. |
| An item's barcode or serial number | Opens that item's page. |
| Several items (partial match, or an item type name) | Shows a short list to pick from. |
| Nothing | Offers **Create item**, with the entered value already filled in as barcode or serial. |

### 5.2 Item page

Shows the item's type, barcode and serial number, and its tickets newest first.

```
┌───────────────────────────────────────┐
│  Step ladder 3m (item type)           │
│  Barcode 501234567  ·  Serial LD-0087 │
│                                       │
│  [ + Start new ticket ]               │
│                                       │
│  T-00042  Open         18 Nov 2026    │
│  T-00017  Resolved     12 Nov 2025    │
└───────────────────────────────────────┘
```

From here the user can open any existing ticket to edit, resolve or reopen it, or start a new one. An item can have any number of open tickets at once.

### 5.3 Create item

A short form: **Item type** (pick from the list), **Barcode** and **Serial number**, all three required. The value the user searched for is pre-filled in the right box. Saving checks that neither the barcode nor the serial number is already used by another item. After saving, the app goes straight to a new ticket for that item.

### 5.4 Ticket screen

The ticket number, item type and serial number sit at the top, then the fields:

```
┌───────────────────────────────────────┐
│  T-00042 · Step ladder 3m (LD-0087)   │
│                                       │
│  Status                               │
│  [ Open | Repair in Progress | Resolved ]    │
│                                       │
│  Fault Type                           │
│  [ Cosmetic | Functionality | Safety ]│
│                                       │
│  Severity                             │
│  [ Low | Medium | High ]              │
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

- **Status:** Open, Repair in Progress, Resolved. A new ticket starts as Open.
- **Fault Type:** Cosmetic, Functionality or Safety. Required.
- **Severity:** Low, Medium or High. Required.
- **Fault Description:** multi-line text.
- **Photos:** shows every photo uploaded to the ticket as thumbnails. Tap to view full size. **Add photo** opens the phone camera or the file picker. Photos are never silently deleted; removing one hides it and is logged.
- **Work Done:** multi-line text describing the repair or action taken.
- **Resolve:** set Status to Resolved and save. **Reopen:** on a resolved ticket, set Status back to Open (or Repair in Progress) and save. Both are logged like any other change.
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
- On a PC the same popup opens by right-click or a small clock icon beside the field.
- Times are shown in UK local time.

### 5.6 Yearly checks

Someone with `manage_checks` starts a **Check** (e.g. "Annual check 2026") when the yearly inspection begins and closes it when done. Every ticket created while a check is open is tagged with it automatically; the user never has to pick it. This allows "all faults found in the 2026 check" reports and year-on-year comparison.

### 5.7 Lists and export

- **Open tickets:** everything Open or Repair in Progress. Safety faults and High severity first, then oldest first. Filter by fault type, severity and item type.
- **Check summary:** tickets created during a chosen check, by status, fault type, severity and item type.
- **Item history:** every ticket for one item.
- **Item type history:** every ticket across all items of one type, to spot types that fail often.
- **Export:** any list to CSV (opens in Excel). A printable ticket sheet with photos.

## 6. Data model

```
ItemType 1──* Item
Item 1──* Ticket
Check 1──* Ticket  (optional)
Ticket 1──* Photo
Ticket 1──* FieldChange
User 1──* FieldChange
Role 1──* User
Role *──* Permission
```

| Entity | Key fields |
|--------|-----------|
| **Role** | id, name (unique), description |
| **Permission** | id, code (e.g. `reopen_ticket`), description |
| **RolePermission** | role_id, permission_id |
| **User** | id, username, display_name, password_hash, role_id, active, created_at |
| **PermissionChange** | id, changed_by, target (role or user), change (e.g. "added reopen_ticket to User"), changed_at |
| **ItemType** | id, name (unique), description, active |
| **Item** | id, item_type_id, barcode (unique, required), serial_number (unique, required), notes, created_by, created_at, active |
| **Check** | id, name, started_on, closed_on |
| **Ticket** | id, number (unique, shown as `T-00042`), item_id, check_id (nullable), status, fault_type, severity, fault_description, work_done, created_by, created_at, updated_at, version |
| **Photo** | id, ticket_id, file_name, thumbnail_file_name, content_type, size, uploaded_by, uploaded_at, removed_by, removed_at |
| **FieldChange** | id, ticket_id, field (`status`, `fault_type`, `severity`, `fault_description`, `work_done`, `photos`), old_value, new_value, user_id, changed_at |

Notes:

- **Field history** comes from FieldChange. Every save compares the old and new value of each field and writes one row per changed field, in the same database transaction as the save, so history can never be missing or out of step. The long-press popup is just "FieldChange rows for this ticket and field, newest first". Creating a ticket writes a "created" row for each filled-in field.
- Item edits (item type, barcode, serial) are logged the same way in an **ItemChange** table with the same shape, so wrong barcodes can be traced.
- `version` on Ticket is a counter that goes up on each save; it's how the app detects two people editing at once (5.4).
- Nothing is hard-deleted. Photos are marked removed; items and users are deactivated.

## 7. Components

Everything runs on the one Windows machine.

```
 Phones / tablets / PCs on the work network
            │  browser, https://faults.local (example)
            ▼
┌─────────────────────────────────────────────┐
│  Desktop PC, Windows Home                   │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │ Caddy (Windows service)               │  │
│  │  - HTTPS on port 443                  │  │
│  │  - forwards to the web application    │  │
│  └──────────────────┬────────────────────┘  │
│                     │ http://127.0.0.1:8000 │
│                     ▼                       │
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
└─────────────────────────────────────────────┘
```

### 7.1 Web application

A single program that serves the pages and holds all the rules. Pages are built on the server and kept simple, with large touch targets. A small amount of JavaScript handles the long press, the history popup, and photo previews. No app needs installing.

### 7.2 Database

**SQLite**: a single file, no database server to run. It comfortably handles 5 concurrent users at this volume. The data model moves to PostgreSQL or SQL Server unchanged if ever needed.

### 7.3 Photos

Uploaded photos are resized (longest edge about 2000 px) and saved in a folder on the machine, with a thumbnail for the ticket screen. Files get random names, not user-supplied ones, and are only served to logged-in users.

### 7.4 Running on Windows Home

- The web application (Waitress) and Caddy are each installed as a Windows service with NSSM or WinSW, so they start with the PC, run without anyone logged in, and restart if they crash. This works on Windows Home; no Windows Server or IIS is needed.
- The web application only listens on `127.0.0.1`, so it can't be reached except through Caddy.
- One Windows Firewall rule opens port 443 to the local network only.
- The PC needs a fixed IP address (a DHCP reservation on the router) and a name staff can type, e.g. `faults.local` or the PC's own name.
- Power settings: sleep and hibernate turned off, so the PC stays reachable during working hours. Windows Update "active hours" set to working hours so it doesn't restart mid-check.

### 7.5 HTTPS

- **Caddy** sits in front of the web application and handles HTTPS. It is a single program with a short config file.
- Because the site is only on the local network, a public certificate isn't available. Caddy creates its own small certificate authority ("internal CA") and issues the site certificate from it, renewing it automatically.
- Each phone, tablet and PC that uses the program must **trust Caddy's root certificate once**. On Windows PCs this can be pushed out or installed by double-clicking; on phones it's installed as a profile (iPhone) or under security settings (Android). Until then, browsers show a "not secure" warning.
- If the workplace's IT or security systems already have their own internal certificate authority, a certificate from it can be used instead, and devices that already trust that authority need no setup. Worth asking IT.
- Django is set to require HTTPS: secure cookies, redirect HTTP to HTTPS, and HSTS.

### 7.6 Migrating to another machine later

Everything the program needs is in one folder: the code, the SQLite database file, the photos folder and the Caddy config and certificates. Moving to a new PC or server is: install Python and Caddy, copy the folder, install the two services, point the name `faults.local` (or whatever is chosen) at the new machine. Keeping the same name and Caddy certificate authority means devices don't need to trust a new certificate.

### 7.7 Backups

Not needed for now, at Leon's request. Note the risk: all data lives on one machine, so a disk failure, theft or accidental deletion would lose every ticket and photo.

Because everything is in two places (the database file and the photos folder), adding backups later is simple: a Windows scheduled task copies both to a network share, external drive or OneDrive-synced folder each night. No design change is needed.

## 8. Tech stack

### Option A: Python + Django (chosen)

- **Framework:** Django. Includes username/password login, password hashing, sessions and a built-in groups-and-permissions system that maps directly onto the roles in section 4 (a role is a Django group). The Roles screen is a simple custom page on top of it.
- **Pages:** Django templates, a small CSS framework (e.g. Bootstrap or Pico.css), and HTMX for the history popup and photo uploads without full page reloads.
- **Long press:** a few lines of plain JavaScript (pointer events with a ~500 ms timer, plus right-click and a history icon for PCs).
- **Barcode input:** a normal text box. Handheld USB or Bluetooth scanners act like a keyboard, so no extra code or drivers are needed.
- **Database:** SQLite (built in).
- **Photos:** Pillow for resizing and thumbnails.
- **Running on Windows:** Waitress web server and Caddy (for HTTPS), each wrapped as a Windows service with NSSM or WinSW.

Why: login, admin and database handling come out of the box, so the effort goes into the lookup and ticket screens. Runs well on Windows with nothing else to install.

### Option B: Node.js + TypeScript

Express or Fastify with server-rendered pages or a small React front end, SQLite via Prisma or Drizzle, run as a Windows service. Fine if you'd rather work in JavaScript, but login, sessions and admin screens have to be built or assembled.

### Option C: Microsoft 365 (Power Apps + SharePoint lists)

Not recommended: you'd prefer local logins, and per-field history with a long-press popup is awkward to build in Power Apps.

### Decision

**Option A: Django + SQLite + Waitress, behind Caddy for HTTPS, as Windows services.** Confirmed by Leon on 2026-11-18.

## 9. Security

- Passwords stored with a strong hash. No length or complexity rules (Leon's choice: low security needs). Lock out after repeated failed logins.
- Every page and photo requires login; each action requires the matching permission (section 4).
- Framework defaults protect against CSRF, XSS and SQL injection.
- Uploads limited to image types and a maximum size.
- **HTTPS everywhere** via Caddy with an internal certificate (7.5). HTTP requests are redirected to HTTPS.
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

1. **MVP:** login, configurable roles and permissions, lookup by barcode/serial/ticket number (typed or handheld scanner), create item, ticket screen with all six fields, item types, photo upload and display, resolve/reopen, field change history with long-press popup, open-tickets list. HTTPS via Caddy. Install both as Windows services on the desktop PC.
2. **Phase 2:** yearly checks and check summary, CSV export, printable ticket sheet.
3. **Later (optional):** nightly backups, phone camera barcode scanning, migration to another machine, import items from the stock system's barcode export, move to a server.

## 12. Open questions

None outstanding. All questions were answered by Leon on 2026-11-18 (see section 3).

One thing to check before installing: whether the workplace's IT or security team has an internal certificate authority that should issue the HTTPS certificate instead of Caddy's own (7.5).
