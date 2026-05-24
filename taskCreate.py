import datetime
import win32com.client


def create_windows_task():
    # Σύνδεση με τον Task Scheduler των Windows
    scheduler = win32com.client.Dispatch("Schedule.Service")
    scheduler.Connect()

    root_folder = scheduler.GetFolder("\\")

    # Δημιουργία ενός νέου Task Definition
    # Το '0' ορίζει ένα κενό task definition object
    task_def = scheduler.NewTask(0)

    # 1. Γενικές Ρυθμίσεις (Registration Info)
    task_def.RegistrationInfo.Description = (
        "Αυτόματη εργασία που δημιουργήθηκε μέσω Python"
    )
    task_def.RegistrationInfo.Author = "Python Script"

    # 2. Ρυθμίσεις Συμπεριφοράς (Settings)
    settings = task_def.Settings
    settings.Enabled = True
    settings.AllowDemandStart = True
    settings.Hidden = False

    # 3. Ορισμός του Trigger (Πότε θα τρέχει)
    # 2 = Daily Trigger (Καθημερινά)
    TASK_TRIGGER_DAILY = 2
    triggers = task_def.Triggers
    trigger = triggers.Create(TASK_TRIGGER_DAILY)

    # Ώρα έναρξης: Σήμερα στις 12:00:00 (Μορφή ISO: YYYY-MM-DDTHH:MM:SS)
    now = datetime.datetime.now()
    start_time = datetime.datetime(now.year, now.month, now.day, 12, 0, 0)
    trigger.StartBoundary = start_time.isoformat()
    trigger.DaysInterval = 1  # Κάθε 1 ημέρα
    trigger.Id = "DailyTrigger"

    # 4. Ορισμός της Ενέργειας (Action - Τι θα κάνει)
    # 0 = Executable Action (Εκτέλεση προγράμματος)
    TASK_ACTION_EXECUTE = 0
    actions = task_def.Actions
    action = actions.Create(TASK_ACTION_EXECUTE)

    # Εδώ ορίζεις τι θέλεις να τρέχει.
    # Αν θες να τρέχει ένα python script, βάζεις το path του python.exe
    # και στα Arguments το path του script σου.
    action.Path = r"C:\Windows\System32\notepad.exe"  # Παράδειγμα με το Notepad
    # action.Arguments = r"C:\path\to\your\script.py" # Αν χρειάζεται arguments
    action.WorkingDirectory = r"C:\Windows\System32"

    # 5. Καταγραφή/Αποθήκευση της εργασίας
    TASK_CREATE_OR_UPDATE = 6
    TASK_LOGON_NONE = 0

    # NPTESTPYTHON είναι το όνομα της εργασίας σας
    task_name = "NPTESTPYTHON"

    try:
        root_folder.RegisterTaskDefinition(
            task_name,
            task_def,
            TASK_CREATE_OR_UPDATE,
            None,  # User ID (None για τον τρέχοντα χρήστη)
            None,  # Password
            TASK_LOGON_NONE,
        )
        print(f"Η εργασία '{task_name}' δημιουργήθηκε με επιτυχία!")
    except Exception as e:
        print(f"Σφάλμα κατά τη δημιουργία της εργασίας: {e}")


if __name__ == "__main__":
    create_windows_task()