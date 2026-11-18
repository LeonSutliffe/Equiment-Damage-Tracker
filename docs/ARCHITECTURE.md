# Equipment Damage Tracker: Architecture

**Status:** Draft for review. No code yet.
**Last updated:** 2026-11-18

## 1. Purpose

Staff need a quick, reliable way to record damage to stock items at work, attach photo evidence, and follow each case through to a resolution (repair, write-off, supplier claim, and so on). Managers need to see what is damaged, where, how much it costs, and whether damage is trending up.

The system replaces ad-hoc methods (paper forms, chat photos, spreadsheets) with a single record per incident that is searchable and auditable.

### Goals

- Log a damage report in under a minute from a phone on the shop or warehouse floor.
- Attach photos at the time of logging.
- Look up an item by barcode/SKU, or by searching its name.
- Track each report from "reported" to "closed" with a clear owner.
- Produce simple reports: damage by item, location, cause, cost and period. Export to CSV.
- Keep a full history of who changed what and when.

### Non-goals (for the first version)

- Full inventory or stock-level management. The tracker reads item data; it is not the system of record for stock counts.
- Accounting or purchase-order integration.
- Native iOS/Android app-store apps.

## 2. Assumptions

Requirements are still thin, so the design rests on these assumptions. Each one is also listed as a question in section 11.

| # | Assumption |
|---|------------|
| A1 | One organisation, one to a handful of sites (stores, warehouses). Tens of users, not thousands. |
| A2 | Hundreds to low thousands of damage reports per year, with 1 to 5 photos each. |
| A3 | Staff use their own or company phones; managers also use a desktop browser. |
| A4 | Items have a SKU and usually a barcode. An item list can be imported from a CSV export of the existing stock system. |
| A5 | Damage may affect a single unit or a quantity of the same SKU. |
| A6 | The network on the floor is usually available but can drop out (back of warehouse, cold rooms). |
| A7 | No hard regulatory requirement, but records should be kept and not silently deleted. |
| A8 | Small budget and a small (possibly one-person) team will build and run it. |

## 3. Users and roles

| Role | Who | Can do |
|------|-----|--------|
| **Reporter** | Floor staff, receiving staff | Log damage, add photos, view and comment on their own reports, look up items. |
| **Reviewer** | Supervisors, team leads | Everything a Reporter can, plus view all reports at their site, assign, change status, set the resolution and cost. |
| **Manager** | Store or operations managers | Everything a Reviewer can, across all sites, plus reports and exports. |
| **Admin** | System owner (likely Leon) | Manage users, roles, sites, locations, item catalogue, damage categories and settings. |

Permissions are checked on the server for every request, never only in the user interface. Roles are scoped to one or more sites.

## 4. Core workflows

### 4.1 Log damage

1. Reporter opens the app and taps **Report damage**.
2. Identifies the item: scan the barcode with the phone camera, type a SKU, or search by name. If the item is not in the catalogue, they can enter a free-text description, and the report is flagged "unknown item" for a Reviewer.
3. Enters quantity, damage category (e.g. crushed, water, broken, expired, missing parts), severity (minor / moderate / write-off), where it happened (site and location), how it was found (on receipt, in storage, in handling, customer return) and an optional note.
4. Takes or attaches photos. Photos are resized on the phone before upload.
5. Submits. The report gets a short human-readable reference (e.g. `DMG-2026-00042`) and status **Reported**. Reviewers for that site are notified.

If the phone is offline, the report and photos are saved on the device and sent automatically when the connection returns (see 6.3).

### 4.2 Item lookup

- Barcode scan uses the phone camera in the browser.
- Search matches SKU, barcode and name.
- An item page shows its details and every damage report against it.

### 4.3 Review and resolution

Status lifecycle:

```
Reported ──► Under review ──► Action pending ──► Resolved ──► Closed
    │              │                                   ▲
    └──────────────┴──► Rejected (not damage / duplicate) ─┘
```

- A Reviewer picks up a report (assigns it to themselves or someone else) and moves it to **Under review**.
- They choose a **resolution type**: repair, return to supplier, supplier/carrier claim, sell as discounted, write off / dispose, or no action.
- **Action pending** is used while waiting on something outside the system (a supplier credit, a repair).
- On **Resolved**, the Reviewer records the outcome, estimated loss and any amount recovered.
- **Closed** locks the report. Only an Admin can reopen it, and the reopening is logged.
- Every change of status, assignee, or field is written to the audit log. Comments can be added at any stage.

### 4.4 Reporting

- Dashboard: open reports by status and age, damage this month vs last month, top items, top categories, top locations, total estimated loss and recovered amounts.
- Filtered list: by date range, site, location, category, status, item, reporter.
- Export the filtered list to CSV. A printable single-report view (or PDF) for supplier claims, including the photos.

### 4.5 Administration

- Import or update the item catalogue from CSV.
- Manage sites, locations within sites, damage categories and resolution types (configurable lists, not hard-coded).
- Invite and deactivate users, assign roles and sites.

## 5. Data model

```
Site 1──* Location
Site 1──* UserSite *──1 User
Item 1──* DamageReport *──1 Location
DamageReport 1──* Photo
DamageReport 1──* Comment
DamageReport 1──* AuditEvent
DamageReport *──1 DamageCategory
DamageReport *──1 ResolutionType (nullable)
```

| Entity | Key fields |
|--------|-----------|
| **User** | id, name, email, active, created_at |
| **UserSite** | user_id, site_id, role (reporter / reviewer / manager / admin) |
| **Site** | id, name, address |
| **Location** | id, site_id, name (e.g. "Aisle 4", "Loading bay") |
| **Item** | id, sku, barcode, name, category, unit_cost, supplier, active |
| **DamageCategory** | id, name, active |
| **ResolutionType** | id, name, active |
| **DamageReport** | id, reference, item_id (nullable), unknown_item_description, quantity, category_id, severity, site_id, location_id, discovered_how, description, status, reported_by, assigned_to, reported_at, resolution_type_id, resolution_notes, estimated_loss, amount_recovered, resolved_at, closed_at, client_id (for offline de-duplication), created_at, updated_at |
| **Photo** | id, report_id, storage_key, thumbnail_key, content_type, size, width, height, taken_at, uploaded_by, created_at |
| **Comment** | id, report_id, author_id, body, created_at |
| **AuditEvent** | id, report_id, actor_id, action, field, old_value, new_value, created_at |

Notes:

- `unit_cost` on Item is copied to the report as the starting `estimated_loss` (unit_cost × quantity), so later price changes do not rewrite history.
- Records are never hard-deleted. Reports are closed or rejected; catalogue entries are deactivated.
- `client_id` is a UUID created on the phone so a report sent twice after a dropped connection is stored once.

## 6. Components

```
┌────────────────────────────┐
│  Web app (PWA)             │  phone + desktop browser
│  - report form, camera,    │
│    barcode scan            │
│  - offline queue           │
│  - dashboard / admin       │
└─────────────┬──────────────┘
              │ HTTPS (JSON API)
┌─────────────▼──────────────┐       ┌──────────────────────┐
│  API server                │──────►│  Object storage      │
│  - auth & permissions      │ signed│  (photos, thumbnails)│
│  - reports, items, users   │  URLs └──────────────────────┘
│  - status rules, audit log │
│  - CSV import / export     │       ┌──────────────────────┐
│  - background jobs         │──────►│  Email (notifications)│
└─────────────┬──────────────┘       └──────────────────────┘
              │
┌─────────────▼──────────────┐
│  Relational database       │
└────────────────────────────┘
```

### 6.1 Web app (Progressive Web App)

A single responsive web app, installable to the phone's home screen. It covers both the quick floor workflow (mobile-first) and the manager dashboard (desktop). A PWA avoids app-store publishing while still giving camera access, barcode scanning and offline support.

### 6.2 API server

A single backend service exposing a JSON API. It owns all business rules: who can see and edit what, which status changes are allowed, writing the audit log, and generating report references. One deployable unit (a "modular monolith") is the right size for the expected load; there is no need for microservices.

Main API areas: `/auth`, `/reports`, `/reports/{id}/photos`, `/reports/{id}/comments`, `/items`, `/sites`, `/users`, `/stats`, `/exports`.

### 6.3 Photo handling and offline support

- The phone resizes photos (e.g. longest edge 2000 px, JPEG) before upload, which keeps uploads fast on poor signal.
- The API returns a short-lived signed upload URL; the phone uploads straight to object storage, then confirms with the API. A background job makes a thumbnail.
- Photos are served through short-lived signed URLs, never public links.
- Offline: drafts and photos are kept in browser storage (IndexedDB) with a sync queue. On reconnect the app sends the report (with its `client_id`) and then the photos. The user sees which reports are "waiting to send".

### 6.4 Database

A relational database. The data is structured and related (items, reports, users, sites), reporting needs grouping and filtering, and the audit log benefits from transactions.

### 6.5 Background jobs

Thumbnail generation, notification emails, and large CSV imports/exports run as background jobs so the app stays responsive. At this scale a simple database-backed job queue is enough.

### 6.6 Notifications

Email (and optionally in-app) notices when: a report is logged at your site (Reviewers), a report is assigned to you, a report you logged is resolved. A daily digest option avoids inbox noise.

## 7. Tech stack options

### Option A: TypeScript full stack (recommended)

- **Frontend:** React with Vite, as a PWA. Barcode scanning via the browser's BarcodeDetector API with a JavaScript fallback library (e.g. ZXing).
- **Backend:** Node.js with a typed framework (e.g. Fastify or NestJS) and an ORM with migrations (e.g. Prisma or Drizzle).
- **Database:** PostgreSQL.
- **Photos:** S3-compatible object storage (AWS S3, Cloudflare R2, Backblaze B2, or MinIO when self-hosting).
- **Auth:** Email magic link or password plus optional Microsoft/Google sign-in if the workplace uses it.
- **Hosting:** A managed platform (e.g. Render, Fly.io, Railway) with managed Postgres, or a single small VM with Docker Compose.

Why: one language across the app, strong PWA and camera support, large ecosystem, easy to hire for or get help with.

### Option B: Python / Django

Django gives a ready-made admin site, authentication and ORM, which covers the admin and catalogue screens almost for free. The floor-facing report form could be server-rendered with light JavaScript (e.g. HTMX). Offline support is harder in this model than in a React PWA. A good choice if offline logging turns out not to matter.

### Option C: Low-code / backend-as-a-service

Supabase (Postgres, auth, storage) with a thin frontend, or a tool such as Power Apps / AppSheet if the workplace already uses Microsoft 365 or Google Workspace. Fastest to a first version and least to operate, but less control over offline behaviour, permissions edge cases and long-term cost, and some lock-in.

### Recommendation

**Option A**, deployed as one API service, one Postgres database and one storage bucket on a managed host. It meets the offline and camera needs well, stays cheap at this scale, and has no exotic parts. If Leon's workplace is a Microsoft 365 shop and offline use is rare, Option C (Power Apps) is worth a second look; see question Q9.

## 8. Security and privacy

- HTTPS everywhere; secure, HTTP-only session cookies or short-lived tokens.
- Role and site checks on every API call.
- Photos in a private bucket, reachable only through signed URLs.
- Strip GPS and device metadata (EXIF) from photos on upload unless location tracking is wanted.
- Audit log is append-only from the application's point of view.
- Daily database backups with tested restore; object storage versioning on the photo bucket.
- Staff names and emails are the only personal data; no customer data is stored.

## 9. Non-functional requirements

| Area | Target |
|------|--------|
| Speed | Report form ready in under 2 s on a mid-range phone on 4G. |
| Availability | Business hours; a short maintenance window out of hours is acceptable. |
| Scale | Comfortably handles 10× the assumed volume without design changes. |
| Retention | Reports and photos kept for at least 7 years unless told otherwise. |
| Accessibility | Large touch targets, works one-handed, readable in bright warehouse light. |
| Browsers | Current Chrome/Safari on iOS and Android; current desktop browsers. |

## 10. Delivery plan (suggested)

1. **MVP:** login, item catalogue import, log damage with photos, list and detail views, status changes, audit log, CSV export.
2. **Phase 2:** barcode scanning, offline queue, notifications, dashboard.
3. **Phase 3:** printable claim pack (PDF), single sign-on, integration with the stock system (automatic catalogue sync, or posting write-offs back).

## 11. Open questions for Leon

1. **Scale:** How many sites, staff, and damage reports per month do you expect? (A1, A2)
2. **Items:** Does your stock system export items with SKU and barcode? Which system is it, and could we sync with it later? (A4)
3. **Devices:** Will staff use their own phones, company phones, or shared tablets/scanners? Do any handheld scanners already exist on site? (A3)
4. **Connectivity:** Are there areas with no signal or Wi-Fi where damage is found? This decides how important offline mode is. (A6)
5. **Workflow:** Who decides the outcome of a damage report today, and what outcomes are possible (write-off, supplier claim, repair, discount sale, other)?
6. **Money:** Should the system track cost and recovered amounts, or only the fact that damage occurred?
7. **Suppliers/carriers:** Do you file claims with suppliers or delivery carriers? If so, what evidence do they ask for?
8. **Sign-in:** Does your workplace use Microsoft 365 or Google Workspace accounts that staff could sign in with?
9. **Platform preference:** Is there an IT policy about where data may be hosted, or a preference for tools already in use (e.g. Microsoft Power Apps, SharePoint)?
10. **Retention and compliance:** How long must records be kept? Any insurance, health and safety, or audit requirements?
11. **Reporting:** What reports does management want to see, and how often?
12. **Who runs it:** Who will host, maintain and pay for the system once built?
