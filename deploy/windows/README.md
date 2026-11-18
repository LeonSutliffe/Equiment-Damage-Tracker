# Installing on the Windows PC

This sets the program up on a desktop PC running Windows 10 or 11 Home, as described in sections 7.4 and 7.5 of the architecture. It ends with two Windows services that start with the PC:

- **DamageTrackerWeb**: the program itself (Waitress, only reachable from the PC itself on port 8000).
- **DamageTrackerCaddy**: HTTPS on port 443 for everyone on the work network.

Everything lives in `C:\DamageTracker`. Allow about 30 minutes.

## 1. Prepare the PC

1. **Fixed address.** Ask whoever runs the router to give this PC a fixed IP address (a DHCP reservation).
2. **A name staff can type.** Pick one, for example `faults.local`, and ask for a DNS entry on the router pointing it at the PC's IP address. If that isn't possible, staff can use the PC's own name (shown in *Settings → System → About*); the install script sets that name up too.
3. **Stay awake.** *Settings → System → Power*: set *Sleep* to *Never*. In *Windows Update → Advanced options → Active hours*, set your working hours so it doesn't restart mid-check.
4. **Private network.** *Settings → Network & internet → (your connection) → Properties*: set the network profile to **Private**.

## 2. Install the tools

1. Install **Python 3.12 or 3.13** from python.org. Tick *Add python.exe to PATH* in the installer.
2. Copy this whole repository to `C:\DamageTracker` (or `git clone` it there), so that `C:\DamageTracker\manage.py` exists.
3. Create the folder `C:\DamageTracker\tools` and put two files in it:
   - `caddy.exe`: from https://caddyserver.com/download (Windows amd64). Rename the download to `caddy.exe`.
   - `nssm.exe`: from https://nssm.cc/download. Take `win64\nssm.exe` out of the zip.

## 3. Run the install script

Open **PowerShell as administrator** (right-click Start → *Terminal (Admin)*) and run:

```powershell
cd C:\DamageTracker
powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1 -HostName faults.local
```

Use the name you picked in step 1 instead of `faults.local`. The script:

- creates a Python environment and installs the program,
- writes `faults.env` with your settings and sets up the database,
- asks you to create the **first admin account** (email can be left blank),
- writes `C:\DamageTracker\Caddyfile`,
- installs and starts both Windows services,
- opens ports 80 and 443 in Windows Firewall for the local network only,
- saves the certificate devices need to trust as `C:\DamageTracker\DamageTracker-root.crt`.

It's safe to run again; it keeps your data and settings.

## 4. Check it works

On the PC, open https://faults.local (or your chosen name). You should see the login page with no certificate warning. Log in with the admin account.

## 5. First setup in the program

1. **Item types**: add the kinds of equipment you check (e.g. *Step ladder 3m*, *Drill 18V*).
2. **Users**: add an account for each person. New users get the *User* role unless you pick another.
3. **Roles**: change what each role can do if needed.

## 6. Trust the certificate on each device (once per device)

Because the site is only on the local network, Caddy makes its own certificate. Each device must trust `DamageTracker-root.crt` once, or browsers will show a "not secure" warning. Copy the file to the device (email, USB stick or a shared folder), then:

- **Windows PC**: double-click the file → *Install Certificate* → *Local Machine* → *Place all certificates in the following store* → *Trusted Root Certification Authorities*.
- **iPhone / iPad**: open the file, then *Settings → Profile Downloaded → Install*. Then *Settings → General → About → Certificate Trust Settings* and switch it on.
- **Android**: *Settings → Security → More security settings → Encryption & credentials → Install a certificate → CA certificate*, and pick the file. (Menu names vary by phone.)

If your workplace IT already runs its own certificate authority, they can issue a certificate for the site instead, and devices that already trust it need nothing. Ask them, then replace `tls internal` in the Caddyfile with `tls C:/path/cert.pem C:/path/key.pem`.

## Everyday running

- Both services start by themselves when the PC starts, even if nobody logs in, and restart if they crash.
- Logs are in `C:\DamageTracker\logs`.
- To stop or start: *Services* app, or `tools\nssm.exe restart DamageTrackerWeb` in an admin terminal.

## Updating to a new version

Replace the code in `C:\DamageTracker` (e.g. `git pull`), then in an admin PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File C:\DamageTracker\deploy\windows\update.ps1
```

## Where the data is

Everything is in `C:\DamageTracker\data`: the database (`db.sqlite3`), the `photos` folder and the secret key. **There are no backups** (architecture 7.7): if this PC's disk fails, everything is lost. To add backups later, copy the `data` folder somewhere else each night with a scheduled task.

## Moving to another PC later

Install Python on the new PC, copy the whole `C:\DamageTracker` folder (including `data`, `caddy\data` and `tools`), run `install.ps1` again, and point the name at the new PC's IP address. Because the Caddy certificate authority comes with the folder, devices don't need to trust a new certificate.
