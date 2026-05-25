import os
import sys
import subprocess
import json
import logging
import shutil
from datetime import datetime, timedelta
import pyodbc
from cryptography.fernet import Fernet
import urllib.request

# Application Metadata
VERSION = "1.3.1"
WEBHOOK_URL = "https://cloud.activepieces.com/api/v1/webhooks/YZDmbN3jTJBJYZV8oFZGj"

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
KEY_FILE = os.path.join(BASE_DIR, "secret.key")
LOG_FILE = os.path.join(BASE_DIR, "maintenance_log.txt")

# Λίστα στη μνήμη για να κρατάει τα logs ΜΟΝΟ του τρέχοντος run για το Webhook
current_run_logs = []


class CustomPrefixFormatter(logging.Formatter):
    def format(self, record):
        prefix = "Error :" if record.levelno >= logging.ERROR else "Log :"
        log_msg = f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} [{prefix}] {record.getMessage()}"
        current_run_logs.append(log_msg)  # Κρατάμε το log για το webhook
        return log_msg


def send_webhook_notification(installation_name, status, log_type, macro_name):
    """Στέλνει JSON Payload στο Activepieces Webhook με την προσθήκη του log_type."""
    payload = {
        "installation_name": installation_name,
        "status": status,
        "log_type": log_type,  # "Log" ή "Error"
        "macro_name": macro_name,
        "log_output": "\n".join(current_run_logs)
    }

    try:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=data,
            headers={'Content-Type': 'application/json; charset=utf-8'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status in [200, 201, 204]:
                pass
    except Exception as e:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [Error :] Failed to send webhook: {e}\n")


def is_admin():
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
    integrity_query = f"DBCC CHECKDB ('{db_name}') WITH PHYSICAL_ONLY, NO_INFOMSGS;"
    cmd = f'sqlcmd -S DESKTOP-JROIMSG\\SQLEXPRESS -U {username} -P "{password}" -Q "{integrity_query}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        return True, None
    return False, f"[{db_name}] DBCC CHECKDB failed: {result.stderr or result.stdout}"


def run_update_statistics(db_name, username, password):
    stats_query = f"USE [{db_name}]; EXEC sp_updatestats;"
    cmd = f'sqlcmd -S DESKTOP-JROIMSG\\SQLEXPRESS -U {username} -P "{password}" -Q "{stats_query}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        return True, None
    return False, f"[{db_name}] sp_updatestats failed: {result.stderr or result.stdout}"


def analyze_and_save_index_stats(db_name, username, password, config):
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
        save_full_config(config)
        return True, None
    except pyodbc.Error as e:
        return False, f"[{db_name}] Index analysis failed: {e}"


def get_free_disk_space_mb(folder_path):
    try:
        abs_path = os.path.abspath(folder_path)
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
            return False, f"[{db_name}] Failed to create directory: {e}"

    if "last_backup_sizes" in config and db_name in config["last_backup_sizes"]:
        last_size_mb = config["last_backup_sizes"][db_name]
        free_space_mb = get_free_disk_space_mb(db_folder)
        required_space_mb = last_size_mb * 1.10

        if free_space_mb < required_space_mb:
            return False, f"[{db_name}] BACKUP ABORTED: Insufficient disk space! Required estimate: {required_space_mb:.2f} MB, Free space: {free_space_mb:.2f} MB."

    date_str = datetime.now().strftime("%Y_%m_%d")
    backup_filename = f"{db_name}_{date_str}.bak"
    backup_path = os.path.join(db_folder, backup_filename)

    backup_query = f"BACKUP DATABASE [{db_name}] TO DISK='{backup_path}' WITH FORMAT, MEDIANAME='SQLServerBackup', NAME='Full Backup of {db_name}';"

    cmd = f'sqlcmd -S DESKTOP-JROIMSG\\SQLEXPRESS -U {username} -P "{password}" -Q "{backup_query}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        file_size_mb = 0.0
        if os.path.exists(backup_path):
            file_size_bytes = os.path.getsize(backup_path)
            file_size_mb = file_size_bytes / (1024 * 1024)

        if "last_backup_sizes" not in config:
            config["last_backup_sizes"] = {}
        config["last_backup_sizes"][db_name] = round(file_size_mb, 2)
        save_full_config(config)
        return True, None
    else:
        return False, f"[{db_name}] Backup failed: {result.stderr or result.stdout}"


def cleanup_backups(config):
    if "paths" not in config or not config["paths"]:
        return False, "Cleanup skipped: No target paths defined in config.json."

    if "retention_days" not in config:
        return False, "Cleanup skipped: retention_days definition missing."

    retention_days = config["retention_days"]
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
                        deleted_count += 1
                except (ValueError, Exception):
                    pass
    return True, f"Purged {deleted_count} file(s)."


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
    print("Διαθέσιμες επιλογές: 1 (Backup), 2 (Cleanup), 3 (Integrity Check), 4 (Update Stats), 5 (Index Analysis)")
    sequence_steps = []
    while True:
        step = input(f"Βήμα {len(sequence_steps) + 1} (ή 0 για έξοδο): ").strip()
        if step == "0":
            break
        if step in ["1", "2", "3", "4", "5"]:
            sequence_steps.append(step)
            print(f"[+] Προστέθηκε η εντολή {step} στην αλληλουχία.")
        else:
            print("[!] Μη έγκυρη εντολή!")

    if not sequence_steps:
        return

    print("\nΒήμα 3: Ρυθμίσεις Αυτοματοποίησης & Επανάληψης")
    is_auto = input(
        "[?] Θέλεις αυτή η αλληλουχία να εκτελείται αυτόματα κατά την εκκίνηση; (y/n): ").strip().lower() == 'y'
    recurrence_type = "none"
    schedule_data = {}

    if is_auto:
        rec_input = input("[?] Τύπος επανάληψης - 'daily' ή 'weekly': ").strip().lower()
        if rec_input in ['daily', 'weekly']:
            recurrence_type = rec_input
        if recurrence_type == "daily":
            time_input = input("[?] Δώσε ώρα εκτέλεσης σε μορφή HH:MM: ").strip()
            schedule_data["time"] = time_input
        elif recurrence_type == "weekly":
            days_input = input("[?] Δώσε ημέρες (0-6) χωρισμένες με κόμμα: ").strip()
            schedule_data["days"] = [int(d.strip()) for d in days_input.split(",") if d.strip()]

    name = input("\n[?] Δώσε ένα όνομα για αυτή την αλληλουχία: ").strip()
    if not name:
        name = f"Sequence_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if "sequences" not in config:
        config["sequences"] = {}

    config["sequences"][name] = {
        "steps": sequence_steps,
        "databases": selected_dbs,
        "last_run": "-",
        "auto": is_auto,
        "recurrence": recurrence_type,
        "schedule_data": schedule_data
    }
    save_full_config(config)
    print(f"\n[✓] Η αλληλουχία '{name}' αποθηκεύτηκε επιτυχώς!")


def execute_action_direct(choice, config, username, password, selected_databases):
    action_names = {"1": "BACKUP", "2": "CLEANUP", "3": "INTEGRITY_CHECK", "4": "UPDATE_STATS", "5": "INDEX_ANALYSIS"}
    tag = action_names.get(choice, "UNKNOWN")
    logging.info(f">> Task Started: {tag}")

    errors = []
    if choice == "2":
        success, msg = cleanup_backups(config)
        if not success: errors.append(msg)
    else:
        for db in selected_databases:
            if choice == "1":
                if "paths" not in config: config["paths"] = {}
                if db not in config["paths"]: config["paths"][db] = BASE_DIR
                success, msg = create_backup(db, username, password, config["paths"][db], config)
            elif choice == "3":
                success, msg = run_integrity_check(db, username, password)
            elif choice == "4":
                success, msg = run_update_statistics(db, username, password)
            elif choice == "5":
                success, msg = analyze_and_save_index_stats(db, username, password, config)

            if not success:
                errors.append(msg)
                logging.error(msg)

    if errors:
        logging.error(f"<< Task Completed with errors: {tag}")
    else:
        logging.info(f"<< Task Completed successfully: {tag}")


def execute_macro_sequence(seq_name, macro_data, config, username, password, databases):
    """Εκτελεί μια αλληλουχία, παράγει συμπυκνωμένο log, υπολογίζει το log_type και στέλνει στο Webhook."""
    global current_run_logs
    current_run_logs = []  # Καθαρισμός για το τρέχον run

    start_time = datetime.now()
    inst_name = config.get("installation_name", "Unknown_Installation")

    if isinstance(macro_data, dict):
        steps_to_run = macro_data.get("steps", [])
        macro_databases = macro_data.get("databases", [])
    else:
        steps_to_run = macro_data
        macro_databases = databases

    action_names = {"1": "BACKUP", "2": "CLEANUP", "3": "INTEGRITY_CHECK", "4": "UPDATE_STATS", "5": "INDEX_ANALYSIS"}
    macro_errors = []

    for step in steps_to_run:
        step_tag = action_names.get(step, f"STEP_{step}")
        if step == "2":
            success, msg = cleanup_backups(config)
            if not success:
                macro_errors.append(f"Task {step_tag} failed: {msg}")
        else:
            for db in macro_databases:
                if step == "1":
                    if "paths" not in config: config["paths"] = {}
                    if db not in config["paths"]: config["paths"][db] = BASE_DIR; save_full_config(config)
                    success, msg = create_backup(db, username, password, config["paths"][db], config)
                elif step == "3":
                    success, msg = run_integrity_check(db, username, password)
                elif step == "4":
                    success, msg = run_update_statistics(db, username, password)
                elif step == "5":
                    success, msg = analyze_and_save_index_stats(db, username, password, config)

                if not success:
                    macro_errors.append(f"Task {step_tag} on [{db}] failed -> {msg}")

    end_time = datetime.now()
    start_str = start_time.strftime("%H:%M:%S")
    end_str = end_time.strftime("%H:%M:%S")

    # Καθορισμός status και log_type δυναμικά
    if not macro_errors:
        status = "SUCCESS"
        log_type = "Log"
        logging.info(f"[MACRO SUCCESS] '{seq_name}' | Duration: {start_str} -> {end_str} | Scope: {macro_databases}")
    else:
        status = "FAILED"
        log_type = "Error"
        logging.error(
            f"[MACRO FAILED] '{seq_name}' | Duration: {start_str} -> {end_str} | Unresolved issues listed below:")
        for err in macro_errors:
            logging.error(f"   ↳ {err}")

    # Αποστολή στο Activepieces Webhook (Προστέθηκε η παράμετρος log_type)
    send_webhook_notification(inst_name, status, log_type, seq_name)

    # Ενημέρωση Metadata στο config
    now_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(config["sequences"][seq_name], dict):
        config["sequences"][seq_name]["last_run"] = now_str
    else:
        config["sequences"][seq_name] = {
            "steps": steps_to_run, "databases": macro_databases, "last_run": now_str,
            "auto": False, "recurrence": "none", "schedule_data": {}
        }
    save_full_config(config)


def check_and_run_autos(config, username, password, databases):
    sequences = config.get("sequences", {})
    if not sequences: return False

    now = datetime.now()
    today_date = now.date()
    current_time_str = now.strftime("%H:%M")
    current_weekday = now.weekday()
    executed_any = False

    for seq_name, macro_data in sequences.items():
        if not isinstance(macro_data, dict) or not macro_data.get("auto", False): continue

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
            execute_macro_sequence(seq_name, macro_data, config, username, password, databases)
            executed_any = True

    return executed_any


def setup_windows_task():
    print("\n=== Δημιουργία Windows Scheduled Task ===")
    if not is_admin():
        print("[!] Σφάλμα: Απαιτούνται δικαιώματα Διαχειριστή.")
        return

    exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
    ps_command = (
        f'$action = New-ScheduledTaskAction -Execute "{exe_path}"; '
        f'$trigger = New-ScheduledTaskTrigger -Daily -At 11:00AM; '
        f'$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; '
        f'Register-ScheduledTask -TaskName "Maintenance Plan Custom Logistic-i" '
        f'-Description "Nektarios Papagalakis" -Action $action -Trigger $trigger -Settings $settings '
        f'-User "NT AUTHORITY\\SYSTEM" -RunLevel Highest'
    )
    try:
        subprocess.run(["powershell", "-Command", ps_command], capture_output=True, text=True, check=True)
        config = load_full_config()
        config["global_auto"] = True
        save_full_config(config)
        print("\n[✓] Το Task δημιουργήθηκε με επιτυχία!")
    except subprocess.CalledProcessError as e:
        print(f"\n[!] Αποτυχία δημιουργίας Task: {e.stderr}")


def main():
    config = load_full_config()
    is_global_auto = config.get("global_auto", False)

    if is_global_auto:
        f_null = open(os.devnull, 'w')
        sys.stdout = f_null
        sys.stderr = f_null

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers = []

    handler_file = logging.FileHandler(LOG_FILE, encoding='utf-8')
    formatter = CustomPrefixFormatter(datefmt='%Y-%m-%d %H:%M:%S')
    handler_file.setFormatter(formatter)
    logger.addHandler(handler_file)

    if not is_global_auto:
        handler_stream = logging.StreamHandler()
        handler_stream.setFormatter(formatter)
        logger.addHandler(handler_stream)
        print("=== SQL Server Maintenance Utility ===")

    if "installation_name" not in config:
        print("\n[*] Πρώτη εκκίνηση: Ορίστε ένα όνομα για αυτή την εγκατάσταση (π.χ. Client_A):")
        inst_name = input("Όνομα Εγκατάστασης: ").strip()
        config["installation_name"] = inst_name if inst_name else "Default_Installation"
        save_full_config(config)
    if config.get("version") != VERSION:
        config["version"] = VERSION
        save_full_config(config)

    username, password = get_credentials()
    if not username or not password:
        if is_global_auto: return
        username = input("Username: ")
        password = input("Password: ")
        save_credentials(username, password)
        config = load_full_config()

    databases = get_databases(username, password)
    if not databases: return

    executed_autos = check_and_run_autos(config, username, password, databases)

    if is_global_auto:
        return

    # --- INTERACTIVE MENU ---
    print(
        "1. Λήψη Back up\n2. Clean up παλιών Back up\n3. Database Integrity Check\n4. Update Statistics\n5. Index Analysis\n6. Record Macro\n7. Run Macro\n8. Setup Task")
    menu_choice = input("Επιλογή (1-8): ").strip()

    if menu_choice == "6": create_sequence(config, databases); return
    if menu_choice == "8": setup_windows_task(); return
    if menu_choice == "7":
        sequences = config.get("sequences", {})
        if not sequences: print("[!] Δεν υπάρχουν αποθηκευμένες αλληλουχίες."); return
        seq_list = list(sequences.keys())
        for idx, seq_name in enumerate(seq_list, 1):
            print(f"{idx}. {seq_name}")
        seq_choice = int(input(f"Επίλεξε αλληλουχία (1-{len(seq_list)}): "))
        selected_seq_name = seq_list[seq_choice - 1]
        execute_macro_sequence(selected_seq_name, sequences[selected_seq_name], config, username, password, databases)
        return

    selected_databases = select_databases(databases)
    execute_action_direct(menu_choice, config, username, password, selected_databases)


if __name__ == "__main__":
    main()