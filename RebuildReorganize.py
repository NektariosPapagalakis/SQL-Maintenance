import pyodbc
#import time


def run_sql_agent_job():
    print("--- Ρυθμίσεις Σύνδεσης SQL Server ---")
    server = input("Δώσε τον Server (π.χ. localhost ή SERVER_NAME\\SQLEXPRESS): ")
    database = input("Δώσε τη Βάση Δεδομένων (π.χ. msdb): ")

    auth_type = input("Τύπος σύνδεσης; (1 για Windows Authentication, 2 για SQL Server Authentication): ")

    if auth_type == "2":
        username = input("Δώσε το Username (sa): ")
        password = input("Δώσε το Password: ")
        connection_string = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password};'
    else:
        connection_string = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};Trusted_Connection=yes;'

    job_name = input("\nΔώσε το ακριβές όνομα του SQL Agent Job που θες να τρέξεις: ")

    try:
        # Σύνδεση στη βάση (για Agent Jobs συνδεόμαστε συνήθως στη msdb)
        print("\nΣύνδεση στον server...")
        conn = pyodbc.connect(connection_string, autocommit=True)
        cursor = conn.cursor()

        # T-SQL εντολή για να ξεκινήσει το Job
        sql_command = f"EXEC msdb.dbo.sp_start_job @job_name = ?;"

        print(f"Εκκίνηση του Job '{job_name}'...")
        cursor.execute(sql_command, (job_name,))
        print("🚀 Το Job ξεκίνησε με επιτυχία στο background!")

        # Κλείσιμο σύνδεσης
        cursor.close()
        conn.close()

    except pyodbc.Error as e:
        print(f"\n❌ Σφάλμα SQL Server: {e}")
    except Exception as e:
        print(f"\n❌ Κάτι πήγε στραβά: {e}")


# Κλήση της συνάρτησης
#if __name__ == "__main__":
    #run_sql_agent_job()