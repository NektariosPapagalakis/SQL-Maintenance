import os
import json
import argparse
import sys
from datetime import datetime
from cryptography.fernet import Fernet
import pyodbc

# --- ΡΥΘΜΙΣΕΙΣ ΚΑΙ ΑΡΧΕΙΑ ---
USERS_FILE = "users_config.json"
KEY_FILE = "secret.key"
SQL_SERVER_NAME = r"DESKTOP-JROIMSG\SQLEXPRESS"

if not os.path.exists(KEY_FILE):
    with open(KEY_FILE, "wb") as key_file:
        key_file.write(Fernet.generate_key())

with open(KEY_FILE, "rb") as key_file:
    cipher_suite = Fernet(key_file.read())


# --- ΣΥΝΑΡΤΗΣΕΙΣ ΔΙΑΧΕΙΡΙΣΗΣ ΑΡΧΕΙΟΥ JSON ---

def load_profiles():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_profiles(profiles):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=4, ensure_ascii=False)


# --- ΚΑΤΑΧΩΡΗΣΗ & ΕΠΕΞΕΡΓΑΣΙΑ ΧΡΗΣΤΩΝ ---

def register_user():
    print("\n--- 📝 Καταχώρηση Νέου Προφίλ ---")
    title = input("Ορίστε έναν Τίτλο για τη Σύνδεση (π.χ. Production_Server): ").strip()
    username = input("Δώστε το username: ").strip()
    password = input("Δώστε το password: ").strip()

    if not title or not username or not password:
        print("❌ Ο Τίτλος, το username και το password είναι υποχρεωτικά!")
        return

    profiles = load_profiles()
    if title in profiles:
        print("❌ Αυτός ο Τίτλος Σύνδεσης υπάρχει ήδη!")
        return

    db_input = input("Δώστε τις βάσεις δεδομένων (π.χ. Hell_Protein, Test): ")
    databases = [db.strip() for db in db_input.split(",") if db.strip()]

    backup_path = input("Δώστε την ΑΠΟΛΥΤΗ διαδρομή για τα backup (π.χ. C:\\SQLBackups): ").strip()
    if not backup_path:
        backup_path = "C:\\SQLBackups"

    print("\nΟρίστε τη δομή ονόματος του αρχείου backup.")
    print("Χρησιμοποιήστε τα μεταβλητά πεδία {db} και {datetime}")
    fn_format = input("Format ονόματος [Προεπιλογή: backup_{db}_{datetime}]: ").strip()
    if not fn_format:
        fn_format = "backup_{db}_{datetime}"

    encrypted_password = cipher_suite.encrypt(password.encode('utf-8')).decode('utf-8')

    profiles[title] = {
        "username": username,
        "password": encrypted_password,
        "databases": databases,
        "backup_path": backup_path,
        "filename_format": fn_format
    }

    save_profiles(profiles)
    print(f"✔️ Το προφίλ με τίτλο '{title}' δημιουργήθηκε με επιτυχία!")


def view_and_edit_profiles():
    """Εμφανίζει τις καταχωρίσεις και επιτρέπει την επεξεργασία τους."""
    profiles = load_profiles()
    if not profiles:
        print("\n❌ Δεν υπάρχουν καταχωρημένα προφίλ.")
        return

    print("\n==================================================")
    print("           ΛΙΣΤΑ ΚΑΤΑΧΩΡΗΜΕΝΩΝ ΠΡΟΦΙΛ             ")
    print("==================================================")

    for idx, (title, data) in enumerate(profiles.items(), 1):
        fn_fmt = data.get("filename_format", "backup_{db}_{datetime}")
        # Υποστήριξη για παλιά logs που ίσως δεν είχαν το πεδίο username ως εσωτερικό key
        uname = data.get("username", title)
        print(f"{idx}. Τίτλος Σύνδεσης: {title}")
        print(f"   Username:       {uname}")
        print(f"   Password:       ******** (Κρυπτογραφημένο)")
        print(f"   Databases:      {', '.join(data['databases'])}")
        print(f"   Path:           {data['backup_path']}")
        print(f"   Format:         {fn_fmt}")
        print("-" * 50)

    choice = input("Θέλετε να επεξεργαστείτε κάποιο προφίλ; Γράψτε τον Τίτλο Σύνδεσης (ή Enter για ακύρωση): ").strip()
    if not choice:
        return

    if choice in profiles:
        print(f"\n--- ✏️ Επεξεργασία Προφίλ: {choice} ---")
        print("(Αφήστε κενό αν δεν θέλετε να αλλάξετε το συγκεκριμένο πεδίο)")

        # Νέο Username
        new_user = input(f"Νέο Username (Τρέχον: {profiles[choice].get('username', '')}): ").strip()
        if new_user:
            profiles[choice]["username"] = new_user

        # Νέος Κωδικός
        new_pass = input("Νέο Password: ").strip()
        if new_pass:
            profiles[choice]["password"] = cipher_suite.encrypt(new_pass.encode('utf-8')).decode('utf-8')

        # Νέες Βάσεις
        new_db = input("Νέες Βάσεις (χωρισμένες με κόμμα): ").strip()
        if new_db:
            profiles[choice]["databases"] = [db.strip() for db in new_db.split(",") if db.strip()]

        # Νέο Path
        new_path = input("Νέο Backup Path: ").strip()
        if new_path:
            profiles[choice]["backup_path"] = new_path

        # Νέο Format
        new_fmt = input("Νέο Format Ονόματος (π.χ. {db}_backup_{datetime}): ").strip()
        if new_fmt:
            profiles[choice]["filename_format"] = new_fmt

        save_profiles(profiles)
        print(f"✔️ Το προφίλ '{choice}' ενημερώθηκε επιτυχώς!")
    else:
        print("❌ Δεν βρέθηκε προφίλ με αυτόν τον τίτλο.")


# --- ΑΥΤΟΜΑΤΟΠΟΙΗΜΕΝΟ Ή INTERACTIVE LOGIN ---

def verify_and_run(username, password, selected_title=None):
    profiles = load_profiles()
    target_profile = None
    profile_title = ""

    # Αν είμαστε σε Interactive Mode, ξέρουμε ακριβώς ποιο προφίλ επέλεξε ο χρήστης
    if selected_title:
        if selected_title in profiles:
            target_profile = profiles[selected_title]
            profile_title = selected_title
    else:
        # Αν είμαστε σε Silent Mode (CLI args), ψάχνουμε ποιο προφίλ ταιριάζει με το username
        for title, data in profiles.items():
            if data.get("username") == username:
                target_profile = data
                profile_title = title
                break

    if not target_profile:
        print("❌ Λάθος στοιχεία σύνδεσης ή το προφίλ δεν βρέθηκε.")
        return False

    encrypted_password = target_profile["password"]
    try:
        decrypted_password = cipher_suite.decrypt(encrypted_password.encode('utf-8')).decode('utf-8')
    except Exception:
        print("❌ Σφάλμα κατά την αποκρυπτογράφηση. Το κλειδί ασφαλείας ίσως άλλαξε.")
        return False

    if password != decrypted_password:
        print("❌ Λάθος username ή password.")
        return False

    print(f"✔️ Επιτυχής σύνδεση στο προφίλ: [{profile_title}] (Χρήστης: {username})")

    databases = target_profile["databases"]
    backup_dir = target_profile["backup_path"]
    fn_format = target_profile.get("filename_format", "backup_{db}_{datetime}")

    if not databases:
        print("⚠️ Δεν υπάρχουν καταχωρημένες βάσεις για αυτό το προφίλ.")
        return False

    # Εκτέλεση των διαδικασιών
    run_full_backup(databases, backup_dir, fn_format)
    cleanup_backups(backup_dir, keep_count=3)
    return True


# --- ΣΥΝΑΡΤΗΣΕΙΣ BACKUP ΚΑΙ CLEANUP ---

def run_full_backup(databases, backup_dir, filename_format):
    print("\n--- 📂 Έναρξη Full Backup (SQL Server) ---")

    if not os.path.exists(backup_dir):
        try:
            os.makedirs(backup_dir)
        except Exception as e:
            print(f"❌ Αποτυχία δημιουργίας φακέλου {backup_dir}: {e}")
            return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={SQL_SERVER_NAME};"
        f"DATABASE=master;"
        f"Trusted_Connection=yes;"
    )

    try:
        conn = pyodbc.connect(conn_str, autocommit=True)
        cursor = conn.cursor()
    except Exception as e:
        print(f"❌ Αποτυχία σύνδεσης στον SQL Server: {e}")
        return

    for db in databases:
        try:
            formatted_name = filename_format.format(db=db, datetime=timestamp)
        except KeyError as e:
            print(f"❌ Σφάλμα στο Format ονόματος. Μη έγκυρο πεδίο: {e}. Χρήση προεπιλογής.")
            formatted_name = f"backup_{db}_{timestamp}"

        if not formatted_name.endswith(".bak"):
            formatted_name += ".bak"

        full_backup_file_path = os.path.join(backup_dir, formatted_name)

        sql_query = f"BACKUP DATABASE [{db}] TO DISK = '{full_backup_file_path}' WITH FORMAT, MEDIANAME = 'SQLServerBackup', NAME = 'Full Backup of {db}';"

        print(f"Δημιουργία backup για τη βάση '{db}'...")
        try:
            cursor.execute(sql_query)
            print(f"✅ Επιτυχές Backup -> {formatted_name}")
        except Exception as e:
            print(f"❌ Σφάλμα κατά το backup της βάσης '{db}': {e}")

    cursor.close()
    conn.close()


def cleanup_backups(backup_dir, keep_count=3):
    print("\n--- 🧹 Εκκαθάριση Παλιών Backups (Clean up) ---")
    if not os.path.exists(backup_dir):
        return

    files = [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".bak")]
    files.sort(key=os.path.getmtime)

    if len(files) <= keep_count:
        print(f"ℹ️ Βρέθηκαν {len(files)} backups. Το όριο είναι {keep_count}, δεν χρειάζεται διαγραφή.")
        return

    files_to_delete = files[:-keep_count]
    for file_path in files_to_delete:
        try:
            os.remove(file_path)
            print(f"🗑️ Διαγράφηκε το παλαιότερο αρχείο: {os.path.basename(file_path)}")
        except Exception as e:
            print(f"❌ Αποτυχία διαγραφή {file_path}: {e}")

    print("✨ Η εκκαθάριση ολοκληρώθηκε!")


# --- ΚΥΡΙΩΣ ΜΕΝΟΥ (INTERACTIVE) ---

def interactive_menu():
    while True:
        print("\n=====================================")
        print("   MSSQL SERVER SECURE BACKUP SYSTEM ")
        print("=====================================")
        print("1. Καταχώρηση Νέου Προφίλ (Με Τίτλο)")
        print("2. Προβολή & Επεξεργασία Προφίλ")
        print("3. Σύνδεση (Login) & Εκτέλεση Backup")
        print("4. Έξοδος")

        choice = input("Επιλέξτε ενέργεια (1-4): ").strip()

        if choice == "1":
            register_user()
        elif choice == "2":
            view_and_edit_profiles()
        elif choice == "3":
            profiles = load_profiles()
            if not profiles:
                print("❌ Δεν υπάρχουν καταχωρημένα προφίλ. Φτιάξτε ένα πρώτα.")
                continue

            print("\nΔιαθέσιμα Προφίλ Σύνδεσης:")
            for title in profiles.keys():
                print(f" - {title}")

            t = input("\nΕπιλέξτε Τίτλο Σύνδεσης: ").strip()
            u = input("Username: ").strip()
            p = input("Password: ").strip()
            verify_and_run(u, p, selected_title=t)
        elif choice == "4":
            print("Έξοδος από την εφαρμογή.")
            break
        else:
            print("Μη έγκυρη επιλογή.")


def main():
    parser = argparse.ArgumentParser(description="Secure MSSQL Backup Manager.")
    parser.add_argument('-u', '--username', type=str, help="Username για silent backup")
    parser.add_argument('-p', '--password', type=str, help="Password για silent backup")

    args = parser.parse_args()

    if args.username and args.password:
        # Στο silent mode, ψάχνει αυτόματα βάσει username
        success = verify_and_run(args.username, args.password)
        if not success:
            sys.exit(1)
        sys.exit(0)
    else:
        interactive_menu()


if __name__ == "__main__":
    main()