import os
import sys
import subprocess
import json
import logging
import shutil
from datetime import datetime, timedelta
import pyodbc
from cryptography.fernet import Fernet

# Application Metadata
VERSION = "1.1.0"  # <--- Αναβάθμιση έκδοσης λόγω νέας λειτουργίας χώρου

CONFIG_FILE = "config.json"
KEY_FILE = "secret.key"
LOG_FILE = "maintenance_log.txt"

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)


def is_admin():
    """Ελέγχει αν το πρόγραμμα εκτελείται με δικαιώματα Διαχειριστή."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def generate_and_save_key():
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as key_file:
        key_file.write(key)
    return key


def load_key():
    if not os.path.exists(KEY_FILE):
        return generate_and_save_key()
    with open(KEY_FILE, "rb") as key_file:
        return key_file.read()


def load_full_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_full_config(config_data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)


def get_credentials():
    config = load_full_config()
    if "username" not in config or "password" not in config:
        return None, None
    key = load_key()
    fernet = Fernet(key)
    try:
        username = config["username"]
        decrypted_password = fernet.decrypt(config["password"].encode()).decode()
        return username, decrypted_password
    except Exception:
        return None, None


def save_credentials(username, password):
    config = load_full_config()
    key = load_key()
    fernet = Fernet(key)
    config["username"] = username
    config["password"] = fernet.encrypt(password.encode()).decode()
    if "paths" not in config:
        config["paths"] = {}
    save_full_config(config)


def get_databases(username, password):
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER=DESKTOP-JROIMSG\\SQLEXPRESS;"
        f"UID={username};"
        f"PWD={password};"
    )
    try:
        conn = pyodbc.connect(conn_str, autocommit=True)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name 
            FROM sys.databases 
            WHERE name NOT IN ('master', 'model', 'msdb', 'tempdb')
        """)
        databases = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return databases
    except pyodbc.Error as e:
        logging.error(f"SQL Server connection failed: {e}")
        return None


def run_integrity_check(db_name, username, password):
    logging.info(f"[{db_name}] DBCC CHECKDB started.")
    integrity_query = f"DBCC CHECKDB ('{db_name}') WITH PHYSICAL_ONLY, NO_INFOMSGS;"
    cmd = f'sqlcmd -S DESKTOP-JROIMSG\\SQLEXPRESS -U {username} -P "{password}" -Q "{integrity_query}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        logging.info(f"[{db_name}] DBCC CHECKDB passed.")
    else:
        logging.error(f"[{db_name}] DBCC CHECKDB failed: {result.stderr or result.stdout}")


def run_update_statistics(db_name, username, password):
    logging.info(f"[{db_name}] sp_updatestats started.")
    stats_query = f"USE [{db_name}]; EXEC sp_updatestats;"
    cmd = f'sqlcmd -S DESKTOP-JROIMSG\\SQLEXPRESS -U {username} -P "{password}" -Q "{stats_query}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        logging.info(f"[{db_name}] sp_updatestats completed.")
    else:
        logging.error(f"[{db_name}] sp_updatestats failed: {result.stderr or result.stdout}")


def analyze_and_save_index_stats(db_name, username, password, config):
    logging.info(f"[{db_name}] Index analysis started.")
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER=DESKTOP-JROIMSG\\SQLEXPRESS;"
        f"DATABASE={db_name};"
        f"UID={username};"
        f"PWD={password};"
    )
    query = """
    WITH IndexStats AS ( 
        SELECT avg_fragmentation_in_percent, page_count 
        FROM sys.dm_db_index_physical_stats (DB_ID(), NULL, NULL, NULL, 'SAMPLED') 
        WHERE page_count > 50 AND index_id > 0
    ) 
    SELECT 'Optimal Fragmentation >' AS [Parameter], CAST(CAST(CEILING(AVG(avg_fragmentation_in_percent)) AS INT) AS VARCHAR) + '%' AS [Suggested Value] FROM IndexStats 
    UNION ALL 
    SELECT 'Optimal Page Count >' AS [Parameter], CASE WHEN AVG(page_count) < 1000 THEN '1000' ELSE CAST(CAST(AVG(page_count) / 10 AS INT) * 10 AS VARCHAR) END AS [Suggested Value] FROM IndexStats;
    """
    try:
        conn = pyodbc.connect(conn_str, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if "index_analysis" not in config:
            config["index_analysis"] = {}
        config["index_analysis"][db_name] = {}
        for row in rows:
            config["index_analysis"][db_name][row[0]] = row[1] if row[1] is not None else "N/A"
            logging.info(f"[{db_name}] {row[0]}: {config['index_analysis'][db_name][row[0]]}")
        save_full_config(config)
        logging.info(f"[{db_name}] Index metrics saved successfully.")
    except pyodbc.Error as e:
        logging.error(f"[{db_name}] Index analysis failed: {e}")


def get_free_disk_space_mb(folder_path):
    """Επιστρέφει τον ελεύθερο χώρο του δίσκου σε Megabytes (MB)."""
    try:
        # Παίρνουμε το απόλυτο path για σιγουριά
        abs_path = os.path.abspath(folder_path)
        # Στα Windows χρειαζόμαστε μόνο τη ρίζα (π.χ. "C:")
        drive, _ = os.path.splitdrive(abs_path)
        total, used, free = shutil.disk_usage(drive if drive else abs_path)
        return free / (1024 * 1024)
    except Exception:
        return 0.0


def create_backup(db_name, username, password, base_target_folder, config):
    db_folder = os.path.join(base_target_folder, db_name)
    if not os.path.exists(db_folder):
        try:
            os.makedirs(db_folder)
        except Exception as e:
            logging.error(f"[{db_name}] Failed to create directory: {e}")
            return

    # --- ΕΛΕΓΧΟΣ ΔΙΑΘΕΣΙΜΟΥ ΧΩΡΟΥ ΠΡΙΝ ΤΟ BACKUP ---
    if "last_backup_sizes" in config and db_name in config["last_backup_sizes"]:
        last_size_mb = config["last_backup_sizes"][db_name]
        free_space_mb = get_free_disk_space_mb(db_folder)

        # Απαιτούμενος χώρος = Μέγεθος τελευταίου backup + 10% buffer ασφαλείας
        required_space_mb = last_size_mb * 1.10

        if free_space_mb < required_space_mb:
            logging.critical(
                f"[{db_name}] BACKUP ABORTED: Insufficient disk space! "
                f"Required estimate: {required_space_mb:.2f} MB, Free space: {free_space_mb:.2f} MB."
            )
            return

    date_str = datetime.now().strftime("%Y_%m_%d")
    backup_filename = f"{db_name}_{date_str}.bak"
    backup_path = os.path.join(db_folder, backup_filename)

    backup_query = f"BACKUP DATABASE [{db_name}] TO DISK='{backup_path}' WITH FORMAT, MEDIANAME='SQLServerBackup', NAME='Full Backup of {db_name}';"

    logging.info(f"[{db_name}] Backup process started.")
    cmd = f'sqlcmd -S DESKTOP-JROIMSG\\SQLEXPRESS -U {username} -P "{password}" -Q "{backup_query}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        # --- ΥΠΟΛΟΓΙΣΜΟΣ ΚΑΙ ΑΠΟΘΗΚΕΥΣΗ ΜΕΓΕΘΟΥΣ ---
        file_size_mb = 0.0
        if os.path.exists(backup_path):
            file_size_bytes = os.path.getsize(backup_path)
            file_size_mb = file_size_bytes / (1024 * 1024)

        logging.info(f"[{db_name}] Backup created successfully: {backup_path} (Size: {file_size_mb:.2f} MB)")

        # Αποθήκευση στο config
        if "last_backup_sizes" not in config:
            config["last_backup_sizes"] = {}
        config["last_backup_sizes"][db_name] = round(file_size_mb, 2)
        save_full_config(config)
    else:
        logging.error(f"[{db_name}] Backup failed: {result.stderr or result.stdout}")


def cleanup_backups(config):
    if "paths" not in config or not config["paths"]:
        logging.warning("Cleanup skipped: No target paths defined in config.json.")
        return
    if "retention_days" not in config:
        while True:
            try:
                days = int(input("\n[?] Πόσων ημερών παλιά αρχεία backup θέλεις να διαγράφονται; (e.g. 7): "))
                if days > 0:
                    config["retention_days"] = days
                    save_full_config(config)
                    break
                else:
                    print("[!] Δώσε έναν αριθμό μεγαλύτερο από το 0.")
            except ValueError:
                print("[!] Παρακαλώ δώσε έγκυρο αριθμό ημερών.")

    retention_days = config["retention_days"]
    logging.info(f"[CLEANUP] Retention filter: > {retention_days} days old.")
    now = datetime.now()
    deleted_count = 0
    for db, base_path in config["paths"].items():
        db_folder = os.path.join(base_path, db)
        if not os.path.exists(db_folder):
            continue
        for filename in os.listdir(db_folder):
            if filename.endswith(".bak"):
                file_path = os.path.join(db_folder, filename)
                try:
                    name_without_ext = filename[:-4]
                    date_part = name_without_ext[-10:]
                    file_time = datetime.strptime(date_part, "%Y_%m_%d")
                    if (now - file_time) > timedelta(days=retention_days):
                        os.remove(file_path)
                        logging.info(f"[CLEANUP] Purged historical backup: {filename}")
                        deleted_count += 1
                except (ValueError, Exception):
                    pass
    logging.info(f"[CLEANUP] Process finished. Purged {deleted_count} file(s).")


def select_databases(databases):
    while True:
        print("\nΕπίλεξε τις βάσεις που θέλεις (π.χ. 1,3,4) ή γράψε 'all' για όλες:")
        user_input = input("Επιλογή: ").strip().lower()
        if user_input == 'all':
            return databases
        try:
            choices = [int(x.strip()) for x in user_input.split(",") if x.strip()]
            valid = True
            temp_selection = []
            for choice in choices:
                if 1 <= choice <= len(databases):
                    temp_selection.append(databases[choice - 1])
                else:
                    print(f"[!] Ο αριθμός {choice} είναι εκτός ορίων.")
                    valid = False
                    break
            if valid and temp_selection:
                return temp_selection
        except ValueError:
            print("[!] Μη έγκυρη μορφή.")


def create_sequence(config, databases):
    print("\n=== Δημιουργία Νέας Αλληλουχίας ===")

    print("\nΒήμα 1: Επιλογή Βάσεων Δεδομένων για την Αλληλουχία")
    print("--------------------------------------------------")
    for idx, db in enumerate(databases, 1):
        print(f"{idx}. {db}")
    selected_dbs = select_databases(databases)

    print("\nΒήμα 2: Καταγραφή Εντολών")
    print("--------------------------------------------------")
    print("Πληκτρολόγησε με τη σειρά τις εντολές που θέλεις να εκτελούνται.")
    print("Διαθέσιμες επιλογές: 1 (Backup), 2 (Cleanup), 3 (Integrity Check), 4 (Update Stats), 5 (Index Analysis)")
    print("Πατήστε 0 για ολοκλήρωση της καταγραφής.\n")

    sequence_steps = []
    while True:
        step = input(f"Βήμα {len(sequence_steps) + 1} (ή 0 για έξοδο): ").strip()
        if step == "0":
            break
        if step in ["1", "2", "3", "4", "5"]:
            sequence_steps.append(step)
            print(f"[+] Προστέθηκε η εντολή {step} στην αλληλουχία.")
        else:
            print("[!] Μη έγκυρη εντολή! Διάλεξε μεταξύ 1, 2, 3, 4, 5 ή 0.")

    if not sequence_steps:
        print("[*] Δεν προστέθηκαν βήματα. Η δημιουργία ακυρεύτηκε.")
        return

    print("\nΒήμα 3: Ρυθμίσεις Αυτοματοποίησης & Επανάληψης")
    print("--------------------------------------------------")

    is_auto = False
    auto_input = input("[?] Θέλεις αυτή η αλληλουχία να εκτελείται αυτόματα κατά την εκκίνηση; (y/n): ").strip().lower()
    if auto_input == 'y':
        is_auto = True

    recurrence_type = "none"
    schedule_data = {}

    if is_auto:
        while True:
            rec_input = input("[?] Τύπος επανάληψης - 'daily' ή 'weekly': ").strip().lower()
            if rec_input in ['daily', 'weekly']:
                recurrence_type = rec_input
                break
            print("[!] Λανθασμένη επιλογή. Γράψε 'daily' ή 'weekly'.")

        if recurrence_type == "daily":
            while True:
                time_input = input("[?] Δώσε ώρα εκτέλεσης σε μορφή HH:MM (π.χ. 22:30): ").strip()
                try:
                    datetime.strptime(time_input, "%H:%M")
                    schedule_data["time"] = time_input
                    break
                except ValueError:
                    print("[!] Μη έγκυρη μορφή ώρας. Προσπάθησε ξανά (HH:MM).")

        elif recurrence_type == "weekly":
            print("Ημέρες: 0=Δευτέρα, 1=Τρίτη, 2=Τετάρτη, 3=Πέμπτη, 4=Παρασκευή, 5=Σάββατο, 6=Κυριακή")
            while True:
                days_input = input("[?] Δώσε ημέρες χωρισμένες με κόμμα (π.χ. 0,3,4 για Δευτ,Πεμ,Παρ): ").strip()
                try:
                    selected_days = [int(d.strip()) for d in days_input.split(",") if d.strip()]
                    if all(0 <= d <= 6 for d in selected_days):
                        schedule_data["days"] = selected_days
                        break
                    print("[!] Οι αριθμοί πρέπει να είναι από το 0 έως το 6.")
                except ValueError:
                    print("[!] Μη έγκυρη μορφή. Δώσε αριθμούς χωρισμένους με κόμμα.")

    name = input("\n[?] Δώσε ένα όνομα για αυτή την αλληλουχία (π.χ. Nightly_Maintenance): ").strip()
    if not name:
        name = f"Sequence_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if "sequences" not in config:
        config["sequences"] = {}

    config["sequences"][name] = {
        "steps": sequence_steps,
        "databases": selected_dbs,
        "last_run": "-",
        "auto": is_auto,
        "recurrence": "none",
        "schedule_data": schedule_data
    }

    save_full_config(config)
    print(f"\n[✓] Η αλληλουχία '{name}' αποθηκεύτηκε επιτυχώς!")


def execute_action_direct(choice, config, username, password, selected_databases):
    action_names = {
        "1": "BACKUP",
        "2": "CLEANUP",
        "3": "INTEGRITY_CHECK",
        "4": "UPDATE_STATS",
        "5": "INDEX_ANALYSIS"
    }
    action_tag = action_names.get(choice, "UNKNOWN")
    logging.info(f">> Task Started: {action_tag}")

    if choice == "2":
        cleanup_backups(config)
        logging.info(f"<< Task Completed: {action_tag}")
        return

    if choice == "5":
        for db in selected_databases:
            analyze_and_save_index_stats(db, username, password, config)
    elif choice == "3":
        for db in selected_databases:
            run_integrity_check(db, username, password)
    elif choice == "4":
        for db in selected_databases:
            run_update_statistics(db, username, password)
    elif choice == "1":
        if "paths" not in config:
            config["paths"] = {}
        config_changed = False
        for db in selected_databases:
            if db not in config["paths"]:
                if config.get("global_auto", False):
                    config["paths"][db] = os.getcwd()
                    config_changed = True
                else:
                    print(f"\n[?] Path missing for database '{db}'.")
                    ans = input(f"Path for {db}: ").strip()
                    config["paths"][db] = ans if ans else os.getcwd()
                    config_changed = True
        if config_changed:
            save_full_config(config)

        for db in selected_databases:
            create_backup(db, username, password, config["paths"][db], config)

    logging.info(f"<< Task Completed: {action_tag}")


def execute_macro_sequence(seq_name, macro_data, config, username, password, databases):
    if isinstance(macro_data, dict):
        steps_to_run = macro_data.get("steps", [])
        macro_databases = macro_data.get("databases", [])
    else:
        steps_to_run = macro_data
        macro_databases = databases

    logging.info(f"==================== [MACRO START: {seq_name}] ====================")
    logging.info(f"Target Scope: {macro_databases}")

    for step in steps_to_run:
        execute_action_direct(step, config, username, password, macro_databases)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(config["sequences"][seq_name], dict):
        config["sequences"][seq_name]["last_run"] = now_str
    else:
        config["sequences"][seq_name] = {
            "steps": steps_to_run,
            "databases": macro_databases,
            "last_run": now_str,
            "auto": False,
            "recurrence": "none",
            "schedule_data": {}
        }
    save_full_config(config)
    logging.info(f"Metadata updated. Last execution timestamp: {now_str}")
    logging.info(f"==================== [MACRO END: {seq_name}] ====================")


def check_and_run_autos(config, username, password, databases):
    sequences = config.get("sequences", {})
    if not sequences:
        return False

    now = datetime.now()
    today_date = now.date()
    current_time_str = now.strftime("%H:%M")
    current_weekday = now.weekday()

    executed_any = False

    for seq_name, macro_data in sequences.items():
        if not isinstance(macro_data, dict) or not macro_data.get("auto", False):
            continue

        last_run_str = macro_data.get("last_run", "-")
        last_run_date = None
        if last_run_str != "-":
            try:
                last_run_date = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M:%S").date()
            except ValueError:
                pass

        recurrence = macro_data.get("recurrence", "none")
        sched = macro_data.get("schedule_data", {})
        should_run = False

        if recurrence == "daily":
            target_time_str = sched.get("time", "00:00")
            if (last_run_date is None or last_run_date < today_date) and current_time_str >= target_time_str:
                should_run = True

        elif recurrence == "weekly":
            target_days = sched.get("days", [])
            if current_weekday in target_days:
                if last_run_date is None or last_run_date < today_date:
                    should_run = True

        if should_run:
            logging.info(f"[SCHEDULER] Triggered auto-execution for macro: '{seq_name}'")
            execute_macro_sequence(seq_name, macro_data, config, username, password, databases)
            executed_any = True

    return executed_any


def setup_windows_task():
    """Δημιουργεί το Windows Scheduled Task αυτόματα μέσω PowerShell."""
    print("\n=== Δημιουργία Windows Scheduled Task ===")

    if not is_admin():
        print("[!] Σφάλμα: Για τη δημιουργία Task απαιτούνται δικαιώματα Διαχειριστή.")
        print("[*] Παρακαλώ ξανατρέξτε την εφαρμογή κάνοντας δεξί κλικ -> 'Εκτέλεση ως Διαχειριστής'.")
        input("\nΠιέστε Enter για επιστροφή στο μενού...")
        return

    if getattr(sys, 'frozen', False):
        exe_path = sys.executable
    else:
        exe_path = os.path.abspath(sys.argv[0])
        print("[*] Σημείωση: Αυτή τη στιγμή τρέχετε το αρχείο ως script (.py).")
        print("    Το Task θα δημιουργηθεί, αλλά προτείνεται να το κάνετε αφού το μετατρέψετε σε .exe.")

    ps_command = (
        f'$action = New-ScheduledTaskAction -Execute "{exe_path}"; '
        f'$trigger = New-ScheduledTaskTrigger -Daily -At 11:00AM; '
        f'$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; '
        f'Register-ScheduledTask -TaskName "Maintenance Plan Custom Logistic-i" '
        f'-Description "Nektarios Papagalakis" -Action $action -Trigger $trigger -Settings $settings '
        f'-User "NT AUTHORITY\\SYSTEM" -RunLevel Highest'
    )

    try:
        print("[*] Γίνεται εγγραφή της εργασίας στο Windows Task Scheduler...")
        result = subprocess.run(
            ["powershell", "-Command", ps_command],
            capture_output=True, text=True, check=True
        )

        config = load_full_config()
        config["global_auto"] = True
        save_full_config(config)

        print("\n[✓] Το Task δημιουργήθηκε με επιτυχία!")
        print("    Όνομα: Maintenance Plan Custom Logistic-i")
        print("    Περιγραφή: Nektarios Papagalakis")
        print("    Χρονοδιάγραμμα: Κάθε μέρα στις 11:00 AM")
        print("[*] Η παράμετρος 'global_auto' άλλαξε αυτόματα σε true.")
    except subprocess.CalledProcessError as e:
        print(f"\n[!] Αποτυχία δημιουργίας Task: {e.stderr}")

    input("\nΠιέστε Enter για επιστροφή στο μενού...")


def main():
    config = load_full_config()
    is_global_auto = config.get("global_auto", False)

    if not is_global_auto:
        print("=== SQL Server Maintenance Utility ===")

        if "installation_name" not in config:
            print("\n[*] Πρώτη εκκίνηση: Παρακαλώ ορίστε ένα όνομα για αυτή την εγκατάσταση (π.χ. Client_A_Athens):")
            inst_name = input("Όνομα Εγκατάστασης: ").strip()
            config["installation_name"] = inst_name if inst_name else "Default_Installation"
            save_full_config(config)

        if config.get("version") != VERSION:
            config["version"] = VERSION
            save_full_config(config)

        print(f"Εγκατάσταση: {config['installation_name']} | Έκδοση: {config['version']}\n")

    username, password = get_credentials()
    if not username or not password:
        if is_global_auto:
            logging.error("Execution failed: global_auto is enabled but no stored credentials found.")
            return
        print("[*] Δεν βρέθηκαν στοιχεία σύνδεσης. Παρακαλώ εισάγετε τα στοιχεία σας:")
        username = input("Username: ")
        password = input("Password: ")
        save_credentials(username, password)
        config = load_full_config()

    databases = get_databases(username, password)
    if not databases:
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        return

    # Trigger Automated Macros
    executed_autos = check_and_run_autos(config, username, password, databases)

    # Headless Exit (if global_auto is active)
    if is_global_auto:
        if executed_autos:
            logging.info(
                f"[GLOBAL AUTO] Scheduled sequences completed for {config.get('installation_name', 'Unknown')}. Exiting.")
        return

    # Main Interactive Menu
    print("Επίλεξε ενέργεια:")
    print("1. Λήψη Back up")
    print("2. Clean up παλιών Back up")
    print("3. Έλεγχος Ακεραιότητας Βάσεων (Database Integrity Check)")
    print("4. Ενημέρωση Στατιστικών (Update Statistics)")
    print("5. Ανάλυση Βάσης & Αποθήκευση Προτεινόμενων Τιμών (Index Analysis)")
    print("6. Δημιουργία Νέας Αλληλουχίας Εντολών (Record Macro)")
    print("7. Εκτέλεση Αποθηκευμένης Αλληλουχίας (Run Macro)")
    print("8. Εγκατάσταση Αυτόματου Windows Task (11:00 AM Daily)")

    while True:
        menu_choice = input("Επιλογή (1-8): ").strip()
        if menu_choice in ["1", "2", "3", "4", "5", "6", "7", "8"]:
            break
        print("[!] Μη έγκυρη επιλογή. Παρακαλώ πατήστε έναν αριθμό από το 1 έως το 8.")

    config = load_full_config()

    if menu_choice == "6":
        create_sequence(config, databases)
        return

    if menu_choice == "8":
        setup_windows_task()
        return

    if menu_choice == "7":
        sequences = config.get("sequences", {})
        if not sequences:
            print("[!] Δεν υπάρχουν αποθηκευμένες αλληλουχίες στο config.json.")
            return

        print("\nΔιαθέσιμες Αλληλουχίες:")
        seq_list = list(sequences.keys())
        for idx, seq_name in enumerate(seq_list, 1):
            macro_item = sequences[seq_name]

            if isinstance(macro_item, dict):
                target_dbs = macro_item.get("databases", [])
                target_steps = macro_item.get("steps", [])
                last_run = macro_item.get("last_run", "-")
                auto_status = "ΝΑΙ" if macro_item.get("auto", False) else "ΟΧΙ"
                rec_type = macro_item.get("recurrence", "none")
            else:
                target_dbs = ["Όλες οι βάσεις (Παλιά μορφή)"]
                target_steps = macro_item
                last_run = "-"
                auto_status = "ΟΧΙ"
                rec_type = "none"

            print(f"{idx}. {seq_name}")
            print(f"   -> Βάσεις: {target_dbs}")
            print(f"   -> Βήματα: {target_steps}")
            print(f"   -> Αυτόματο: {auto_status} (Τύπος: {rec_type})")
            print(f"   -> Τελευταία εκτέλεση: {last_run}")
            print("-" * 40)

        while True:
            try:
                seq_choice = int(input(f"\nΕπίλεξε αλληλουχία (1-{len(seq_list)}): "))
                if 1 <= seq_choice <= len(seq_list):
                    selected_seq_name = seq_list[seq_choice - 1]
                    macro_data = sequences[selected_seq_name]
                    break
                print("[!] Εκτός ορίων.")
            except ValueError:
                print("[!] Δώσε έγκυρο αριθμό.")

        execute_macro_sequence(selected_seq_name, macro_data, config, username, password, databases)
        return

    print("\nΔιαθέσιμες Βάσεις Δεδομένων:")
    for idx, db in enumerate(databases, 1):
        print(f"{idx}. {db}")
    selected_databases = select_databases(databases)

    execute_action_direct(menu_choice, config, username, password, selected_databases)
    logging.info("--- Execution Cycle Finished ---")


if __name__ == "__main__":
    main()