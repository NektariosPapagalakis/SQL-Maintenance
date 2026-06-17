# 🛠️ SQL Server Maintenance Utility

![Python Version](https://img.shields.io/badge/python-3.x-blue.svg)
![Platform](https://img.shields.io/badge/platform-windows-lightgrey.svg)
![SQL Server](https://img.shields.io/badge/database-MS%20SQL%20Server-red.svg)
![Automation](https://img.shields.io/badge/integration-Activepieces-orange.svg)

Μια αυτοματοποιημένη κονσόλα (CLI) σε Python σχεδιασμένη για τη συντήρηση, τη λήψη αντιγράφων ασφαλείας (Backup) και τον έλεγχο ακεραιότητας βάσεων δεδομένων Microsoft SQL Server.[cite: 1]

Το εργαλείο υποστηρίζει τη δημιουργία προσαρμοσμένων μακροεντολών (Macros), χρονοπρογραμματισμό μέσω Windows Task Scheduler και αποστολή αναλυτικών logs/alerts σε πραγματικό χρόνο μέσω Webhooks στο Activepieces.[cite: 1]

---

## 🚀 Χαρακτηριστικά

* **💾 Έξυπνη Λήψη Full Backup (`.bak`):** Πριν την εκτέλεση, πραγματοποιείται αυτόματος έλεγχος διαθέσιμου χώρου στον δίσκο με safety margin (+10%) με βάση το μέγεθος του προηγούμενου backup για την αποφυγή κρασαρισμάτων.[cite: 1]
* **🧹 Αυτόματο Clean up:** Διαγραφή αρχείων backup που έχουν ξεπεράσει το καθορισμένο όριο ημερών διακράτησης (`retention_days`).[cite: 1]
* **🔍 Έλεγχος Ακεραιότητας (`DBCC CHECKDB`):** Έλεγχος φυσικής και λογικής δομής της βάσης με άμεση καταγραφή σφαλμάτων.[cite: 1]
* **📊 Ενημέρωση Στατιστικών (`sp_updatestats`):** Βελτιστοποίηση των query execution plans του SQL Server Optimizer.[cite: 1]
* **📈 Index Analysis:** Ανάλυση του βαθμού κατακερματισμού (fragmentation) και αυτόματη πρόταση βέλτιστων τιμών για ανασυγκρότηση.[cite: 1]
* **🤖 Record & Run Macros:** Δημιουργία αλληλουχίας εργασιών (π.χ. *Backup ➡️ Cleanup ➡️ Update Stats*) για επιλεγμένες βάσεις δεδομένων.[cite: 1]
* **⚙️ Background Λειτουργία (global_auto):** Πλήρης συμβατότητα με Windows Task Scheduler. Όταν εκτελείται αυτόματα, τρέχει εντελώς αθόρυβα στο background χωρίς να εμφανίζει παράθυρα κονσόλας.[cite: 1]
* **🔗 Activepieces Integration:** Αποστολή JSON Payloads με metadata, status (`SUCCESS`/`FAILED`), τύπο καταγραφής (`Log`/`Error`) και το πλήρες log output της τρέχουσας εκτέλεσης.[cite: 1]

---

## 📂 Δομή Αρχείων

Μετά την πρώτη εκκίνηση και τη δημιουργία των απαραίτητων κλειδιών, ο φάκελος της εφαρμογής διαμορφώνεται ως εξής:[cite: 1]

```text
├── maintenance_utility.py     # Ο κύριος κώδικας της εφαρμογής
├── config.json                # Ρυθμίσεις, macros και metadata (Παράγεται αυτόματα)
├── secret.key                 # Κρυπτογραφικό κλειδί Fernet για τα SQL Credentials (Παράγεται αυτόματα)
└── maintenance_log.txt        # Τοπικό αρχείο ιστορικού καταγραφών (Append-only)

```

---

## 💻 Δομή Μενού (CLI)

Η πλοήγηση στην κονσόλα γίνεται μέσω αριθμητικών επιλογών και είναι δομημένη ως εξής:

### 1. Κεντρικό Μενού

* **`1. Direct Actions`** ➡️ Μετάβαση στις άμεσες ενέργειες συντήρησης.
* **`2. Macros`** ➡️ Διαχείριση και εκτέλεση αυτοματοποιημένων σεναρίων.
* **`3. Settings`** ➡️ Ρυθμίσεις συστήματος, webhooks και Tasks.
* **`4. Exit`** ➡️ Τερματισμός της εφαρμογής.

### 2. Υπομενού Direct Actions

* **`1. Λήψη Back up`**
* **`2. Clean up παλιών Back up`**
* **`3. Database Integrity Check`**
* **`4. Update Statistics`**
* **`5. Index Analysis`**
* **`6. Back`** ➡️ Επιστροφή στο Κεντρικό Μενού.

### 3. Υπομενού Macros

* **`1. Record Macro`**
* **`2. Run Macro`**
* **`3. Back`** ➡️ Επιστροφή στο Κεντρικό Μενού.

### 4. Υπομενού Settings

* **`1. Setup Task`**
* **`2. Test Webhook Connection`** ➡️ Άμεση δοκιμή της σύνδεσης με το Webhook.
* **`3. Update Webhook URL`**
* **`4. Back`** ➡️ Επιστροφή στο Κεντρικό Μενού.

---

## ⚙️ Ρυθμίσεις (`config.json`)

Το αρχείο `config.json` δημιουργείται αυτόματα. Μπορείς να ορίσεις custom paths αποθήκευσης ανά βάση, καθώς και τις ημέρες διακράτησης (`retention_days`).

### Παράμετροι Ρυθμίσεων

| Παράμετρος | Τύπος | Περιγραφή |
| --- | --- | --- |
| `installation_name` | `String` | Το αναγνωριστικό όνομα του πελάτη/εγκατάστασης (π.χ. `Client_A`).
|
| `retention_days` | `Integer` | Πόσες ημέρες θα διατηρούνται τα αρχεία `.bak` πριν διαγραφούν.
|
| `global_auto` | `Boolean` | `true` όταν εκτελείται από τα Windows Tasks για αθόρυβη λειτουργία.
|
| `paths` | `Object` | Key-value ζεύγη με το Target Folder για κάθε Database.
|

### Παράδειγμα Δομής Αρχείου

```json
{
    "installation_name": "Client_Athens_Office",
    "version": "1.3.2",
    "username": "sa",
    "password": "gAAAAABm...", 
    "global_auto": false,
    "retention_days": 7,
    "paths": {
        "ProductionDB": "D:\\SQL_Backups",
        "TestDB": "D:\\SQL_Backups\\Test"
    },
    "last_backup_sizes": {
        "ProductionDB": 1540.20
    },
    "sequences": {
        "Daily_Maintenance": {
            "steps": ["1", "2", "3", "4"],
            "databases": ["ProductionDB"],
            "last_run": "2026-05-25 11:01:18",
            "auto": true,
            "recurrence": "daily",
            "schedule_data": {
                "time": "23:00"
            }
        }
    }
}

```

> ⚠️ **Σημαντικό:** Ο κωδικός πρόσβασης (`password`) κρυπτογραφείται αυτόματα με αλγόριθμο AES-128 (Fernet). **Μην μοιράζεστε ή διαγράφετε το αρχείο `secret.key**`, καθώς είναι απαραίτητο για την αποκρυπτογράφηση.
> 
> 

---

## 🔗 Activepieces Webhook Payload

Η εφαρμογή στέλνει ειδοποιήσεις στο Activepieces Webhook URL τόσο για την αυτόματη εκτέλεση των Macros όσο και για τις μεμονωμένες (Direct) ενέργειες από το μενού.

### Παράδειγμα JSON (Επιτυχής Εκτέλεση - Log)

```json
{
  "job": "MaintenancePlan",
  "installation_name": "Client_Athens_Office",
  "status": "SUCCESS",
  "log_type": "Log",
  "macro_name": "Daily_Maintenance",
  "log_output": "2026-05-25 23:00:01 [Log :] >> Task Started: BACKUP\n2026-05-25 23:01:15 [Log :] [ProductionDB] Backup completed successfully.\n2026-05-25 23:01:16 [Log :] >> Task Started: CLEANUP\n2026-05-25 23:01:18 [Log :] Purged 1 file(s)."
}

```

### Παράδειγμα JSON (Αποτυχία - Error)

```json
{
  "job": "MaintenancePlan",
  "installation_name": "Client_Athens_Office",
  "status": "FAILED",
  "log_type": "Error",
  "macro_name": "Daily_Maintenance",
  "log_output": "2026-05-25 23:00:01 [Log :] >> Task Started: BACKUP\n2026-05-25 23:00:02 [Error :] [ProductionDB] BACKUP ABORTED: Insufficient disk space!\n2026-05-25 23:00:02 [Error :] [MACRO FAILED] 'Daily_Maintenance' | Unresolved issues listed below:\n2026-05-25 23:00:02 [Error :]    ↳ Task BACKUP on [ProductionDB] failed"
}

```

---

## 🛠️ Προϋποθέσεις Εγκατάστασης

1. **Python 3.x** εγκατεστημένη στο σύστημα.


2. Εγκατάσταση των απαραίτητων βιβλιοθηκών:

```bash
pip install pyodbc cryptography

```

3. **Microsoft ODBC Driver** για SQL Server (προεπιλογή: *ODBC Driver 17*).


4. Το εργαλείο **`sqlcmd`** πρέπει να είναι προσβάσιμο από τα Environment Variables (`PATH`) του συστήματος.



---

## 📅 Αυτοματοποίηση μέσω Windows Task Scheduler

Για να ρυθμίσετε την αυτόματη εκτέλεση των εργασιών συντήρησης:

1. Πλοηγηθείτε στο κεντρικό μενού και επιλέξτε **`3. Settings`**.
2. Στη συνέχεια, επιλέξτε **`1. Setup Task`**.
3. Το εργαλείο θα δημιουργήσει αυτόματα ένα Windows Scheduled Task με το όνομα `"Maintenance Plan Custom Logistic-i"`.

> 💡 **Tip:** Για τη δημιουργία του Task, το τερματικό/κονσόλα θα πρέπει να έχει ανοίξει απαραίτητα με δικαιώματα **Διαχειριστή (Run as Administrator)**.
