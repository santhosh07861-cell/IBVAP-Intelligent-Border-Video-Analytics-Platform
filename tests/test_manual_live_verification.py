"""
Live Manual Verification Test of Alert Deletion, SQLite Persistence & Page Refresh
Prints exact database rows, HTTP requests/responses, and verifies SQLite state.
"""

import sqlite3
import requests
from pathlib import Path

def test_live_manual_flow():
    print("=" * 80)
    print("  IBVAP LIVE RUNTIME MANUAL VERIFICATION TEST")
    print("=" * 80)

    # Authenticate to get valid Bearer token
    login_res = requests.post(
        "http://127.0.0.1:8000/api/auth/login",
        data={"username": "admin", "password": "Admin Pass123!"}
    )
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    db_file = str(Path(__file__).parent / "ibvap.db")
    conn = sqlite3.connect(db_file)
    c = conn.cursor()

    # Step 1: Initial query of SQLite database
    c.execute("SELECT count(*) FROM alerts")
    total_before = c.fetchone()[0]
    print(f"\n[1] TOTAL ALERTS IN DATABASE BEFORE TEST: {total_before}")
    print(f"    Database File: {db_file}")

    # Fetch top alerts via GET /api/alerts
    get_res_1 = requests.get("http://127.0.0.1:8000/api/alerts?limit=10", headers=headers)
    assert get_res_1.status_code == 200
    alerts_list_1 = get_res_1.json()
    assert len(alerts_list_1) > 0, "No alerts available to delete!"

    target = alerts_list_1[0]
    target_id = target["id"]
    target_type = target["event_type"]
    target_time = target["timestamp"]

    print(f"\n[2] TARGET ALERT SELECTED FOR DELETION:")
    print(f"    Alert ID:   {target_id}")
    print(f"    Event Type: {target_type}")
    print(f"    Timestamp:  {target_time}")

    # Inspect row in SQLite BEFORE deletion
    c.execute("SELECT id, camera_id, event_type, severity, timestamp FROM alerts WHERE id = ?", (target_id,))
    row_before = c.fetchone()
    print(f"\n[3] DATABASE ROW BEFORE DELETION:")
    print(f"    {row_before}")
    assert row_before is not None, "Target alert not found in SQLite before deletion!"

    # Step 2: Perform DELETE /api/alerts/{target_id}
    print(f"\n[4] EXECUTING API REQUEST: DELETE /api/alerts/{target_id}")
    del_res = requests.delete(f"http://127.0.0.1:8000/api/alerts/{target_id}", headers=headers)
    print(f"    HTTP Status: {del_res.status_code}")
    print(f"    HTTP Response Body: {del_res.json()}")
    assert del_res.status_code == 200

    # Step 3: Immediately query SQLite directly after deletion
    c.execute("SELECT * FROM alerts WHERE id = ?", (target_id,))
    rows_after = c.fetchall()
    print(f"\n[5] DIRECT SQLITE QUERY AFTER DELETION:")
    print(f"    SELECT * FROM alerts WHERE id = '{target_id}';")
    print(f"    Result Rows Returned: {len(rows_after)}")
    assert len(rows_after) == 0, f"CRITICAL: Alert row {target_id} still exists in SQLite!"
    print(f"    ✓ Row count in SQLite is EXACTLY 0.")

    c.execute("SELECT count(*) FROM alerts")
    total_after_delete = c.fetchone()[0]
    print(f"    Total alerts in SQLite now: {total_after_delete} (Was {total_before})")
    assert total_after_delete == total_before - 1

    # Step 4: Simulate Page Refresh (GET /api/alerts?limit=100)
    print(f"\n[6] SIMULATING PAGE REFRESH (GET /api/alerts?limit=100)...")
    get_res_2 = requests.get("http://127.0.0.1:8000/api/alerts?limit=100", headers=headers)
    assert get_res_2.status_code == 200
    refreshed_alerts = get_res_2.json()
    refreshed_ids = [a["id"] for a in refreshed_alerts]

    print(f"    Total alerts returned by GET /api/alerts: {len(refreshed_alerts)}")
    print(f"    First 5 Alert IDs returned on refresh:")
    for i, a in enumerate(refreshed_alerts[:5]):
        print(f"      [{i+1}] ID: {a['id'][:8]}... | Type: {a['event_type']} | Time: {a['timestamp']}")

    # Step 5: Verify whether deleted ID returns
    is_deleted_id_in_response = target_id in refreshed_ids
    print(f"\n[7] VERIFICATION CHECK:")
    print(f"    Was deleted ID ({target_id}) returned in GET /api/alerts? {is_deleted_id_in_response}")
    assert not is_deleted_id_in_response, f"CRITICAL: Deleted ID {target_id} returned on refresh!"
    print(f"    ✓ CONFIRMED: The deleted Alert ID is NOT in the refreshed list.")

    # Step 6: Query SQLite again after refresh to verify it remains 0
    c.execute("SELECT count(*) FROM alerts WHERE id = ?", (target_id,))
    count_final = c.fetchone()[0]
    c.execute("SELECT count(*) FROM alerts")
    total_final = c.fetchone()[0]
    print(f"\n[8] SQLITE STATE AFTER REFRESH:")
    print(f"    Rows for deleted ID {target_id}: {count_final} (Must be 0)")
    print(f"    Total rows in alerts table: {total_final}")
    assert count_final == 0
    assert total_final == total_after_delete
    print(f"    ✓ CONFIRMED: Deleted record remains permanently removed from SQLite database.")

    conn.close()
    print("\n" + "=" * 80)
    print("  LIVE RUNTIME MANUAL TEST PASSED 100% SUCCESSFULLY!")
    print("=" * 80)

if __name__ == "__main__":
    test_live_manual_flow()
