## Visa Appointment Bot (Firefox + PwnFox)

This bot logs in to `almaviva-visa.it`, opens the appointment page, selects required values, accepts terms, and presses Check availability. It runs multiple accounts concurrently, each in its own Firefox instance (separate session). If you provide the PwnFox extension `.xpi`, it will be installed temporarily per instance.

### Files
- `main.py`: Entry point.
- `config.json`: Configuration for URLs and defaults.
- `accounts.txt`: Create this file with one account per line: `email,password[,visa_type]`.
- `requirements.txt`: Python dependencies.

### Example `accounts.txt`
```
user1@example.com,MyPassword,Schengen Tourist
user2@example.com,AnotherPass,Work Visa
user3@example.com,ThirdPass
```

### Configuration (`config.json`)
- `center_value`: e.g., `Cairo`.
- `service_level_value`: e.g., `Standard - EGP 1750`.
- `destination_value`: defaults to `Italy`.
- `pwnfox_xpi_path`: optional local path to `pwnfox.xpi`.
- `firefox_binary_path`: optional path to Firefox binary (if not on PATH).
- `headless`: set to `false` to see the browsers. Keep `false` for extensions.
- `max_workers`: limit concurrent browsers. `null` = one per account.

### Run Locally (Linux/macOS/WSL)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --accounts accounts.txt --config config.json
```

### Build Windows .exe
Use PyInstaller (runs fine on Windows):
```bash
pyinstaller --noconfirm --onefile --name visa-bot \
  --add-data config.json:. \
  main.py
```
Copy the generated `dist/visa-bot.exe` next to your `accounts.txt` and (optionally) the `pwnfox.xpi`. Then run:
```bash
visa-bot.exe --accounts accounts.txt --config config.json
```

### Notes
- The site is an Angular app; selectors aim to be robust. If labels change, update `center_value`, etc., or tweak XPath helpers in `main.py`.
- Each account gets its own Firefox profile/process, which naturally isolates sessions similar to PwnFox containers.
- If you must open tabs in a single window under PwnFox containers, adapt code to reuse one driver and call the PwnFox API per tab (not covered here due to add-on specifics).

