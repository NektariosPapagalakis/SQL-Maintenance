import os
import subprocess
import json
from datetime import datetime
import pyodbc
from cryptography.fernet import Fernet

CONFIG_FILE = "config.json"
KEY_FILE = "secret.key"


def generate_and_save_key():
    """Παράγει ένα κλειδί κρυπτογράφησης και το αποθηκεύει σε ξεχωριστό αρχείο."""
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as key_file:
        key_file.write(key)
    return key


def load_key():
    """Φορτώνει το κλειδί κρυπτογράφησης από το αρχείο."""
    if not os.path.exists(KEY_FILE):
        return generate_and_save_key()
    with open(KEY_FILE, "rb") as key_file:
        return key_file.read()


def save_config(username, password):
    """Κρυπτογραφεί τον κωδικό και αποθηκεύει τα στοιχεία στο config.json."""
    key = load_key()
    fernet = Fernet(key)

    # Κρυπτογράφηση του κωδικού (πρέπει να μετατραπεί πρώτα σε bytes)
    encrypted_password = fernet.encrypt(password.encode()).decode()

    config_data = {
        "username": username,
        "password": encrypted_password
    }

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4)
    print(f"[*] Τα στοιχεία σύνδεσης αποθηκεύτηκαν με ασφάλεια στο {CONFIG_FILE}")


def load_config():
    """Φορτώνει και αποκρυπτογραφεί τα στοιχεία σύνδεσης."""
    if not os.path.exists(CONFIG_FILE):
        return None, None

    key = load_key()
    fernet = Fernet(key)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    username = config_data["username"]
    encrypted_password = config_data["password"]

    # Αποκρυπτογράφηση του κωδικού
    decrypted_password = fernet.decrypt(encrypted_password.encode()).decode()

    return username, decrypted_password


def get_databases(username, password):
    """Συνδέεται στον SQL Server Express και επιστρέφει μια λίστα με τις βάσεις."""
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
        print(f"\n[!] Σφάλμα σύνδεσης: {e}")
        return None


def create_backup(db_name, username, password, target_folder):
    """Δημιουργεί το αρχείο .bak στο επιλεγμένο path."""
    date_str = datetime.now().strftime("%Y_%m_%d")
    backup_filename = f"{db_name}_{date_str}.bak"
    backup_path = os.path.join(target_folder, backup_filename)

    backup_query = f"BACKUP DATABASE [{db_name}] TO DISK='{backup_path}' WITH FORMAT, MEDIANAME='SQLServerBackup', NAME='Full Backup of {db_name}';"

    print(f"\n[... ] Ξεκινάει το backup για τη βάση '{db_name}'...")

    cmd = f'sqlcmd -S DESKTOP-JROIMSG\\SQLEXPRESS -U {username} -P "{password}" -Q "{backup_query}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"[✓] Το backup ολοκληρώθηκε επιτυχώς!")
        print(f"[*] Αρχείο: {backup_path}")
    else:
        print(f"[!] Κάτι πήγε στραβά κατά το backup:")
        print(result.stderr or result.stdout)


def main():
    print("=== SQL Server Backup Utility ===")

    # 1. Έλεγχος ή λήψη στοιχείων σύνδεσης
    username, password = load_config()

    if not username or not password:
        print("[*] Δεν βρέθηκε αρχείο ρυθμίσεων. Παρακαλώ εισάγετε τα στοιχεία σας:")
        username = input("Username: ")
        password = input("Password: ")
        save_config(username, password)

    print("\n[... ] Αναζήτηση διαθέσιμων βάσεων δεδομένων...")
    databases = get_databases(username, password)

    if not databases:
        print("[!] Δεν βρέθηκαν βάσεις δεδομένων ή απέτυχε η σύνδεση. Ελέγξτε τα στοιχεία στο config.json.")
        # Αν αποτύχει, ίσως ο χρήστης θέλει να αλλάξει κωδικό, οπότε σβήνουμε το config για να ξαναρωτήσει την επόμενη φορά
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        return

    # 2. Εμφάνιση Βάσεων
    print("\nΔιαθέσιμες Βάσεις Δεδομένων:")
    for idx, db in enumerate(databases, 1):
        print(f"{idx}. {db}")

    # 3. Επιλογή Βάσης
    while True:
        try:
            choice = int(input("\nΕπίλεξε τον αριθμό της βάσης που θέλεις για backup: "))
            if 1 <= choice <= len(databases):
                selected_db = databases[choice - 1]
                break
            else:
                print(f"[!] Παρακαλώ βάλε έναν αριθμό από το 1 έως το {len(databases)}.")
        except ValueError:
            print("[!] Μη έγκυρη καταχώρηση. Δώσε έναν αριθμό.")

    # 4. Ερώτηση για το Path αποθήκευσης
    print("\n[?] Πού θέλεις να αποθηκευτεί το backup;")
    print("    (Πληκτρολόγησε το path, π.χ., C:\\SQLBackups ή πάτα Enter για τον τρέχοντα φάκελο)")
    user_path = input("Path: ").strip()

    if not user_path:
        target_folder = os.getcwd()
    else:
        target_folder = user_path

    if not os.path.exists(target_folder):
        try:
            os.makedirs(target_folder)
            print(f"[*] Ο φάκελος '{target_folder}' δεν υπήρχε και δημιουργήθηκε.")
        except Exception as e:
            print(f"[!] Αδυναμία δημιουργίας του φακελού: {e}. Το backup θα ακυρωθεί.")
            return

    # 5. Εκτέλεση
    create_backup(selected_db, username, password, target_folder)


if __name__ == "__main__":
    main()