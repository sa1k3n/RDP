### Visa Appointment Bot (Firefox + Selenium)

- Place your accounts in `accounts.txt` with one per line:
```
email1@example.com,password123,Schengen Tourist
email2@example.com,password456,Family Reunion,Cairo,Standard - EGP 1750
```
- Fields: `email,password,visa_type[,center][,service_level]`

- Optional: Download PwnFox XPI and pass its path with `--pwnfox-xpi /absolute/path/PwnFox.xpi`.

#### Run (Linux/Mac)
```
pip3 install -r requirements.txt
python3 bot.py --accounts-file accounts.txt --pwnfox-xpi /path/to/PwnFox.xpi
```

#### Build Windows .exe
Build on Windows:
```
py -m pip install -r requirements.txt
py -m PyInstaller --onefile --name visa-bot bot.py
```
The exe will be at `dist/visa-bot.exe`. Run with:
```
visa-bot.exe --accounts-file accounts.txt --pwnfox-xpi C:\\path\\to\\PwnFox.xpi
```

Notes:
- Ensure Firefox is installed. Selenium 4 auto-manages geckodriver (Selenium Manager).
- The bot opens one Firefox window per account (separate temp profile) to guarantee isolated sessions equivalent to PwnFox containers.