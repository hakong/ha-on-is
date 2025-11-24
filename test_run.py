import asyncio
import os
import sys
from custom_components.on_is.api import OnIsClient  # Assumes you renamed on_is_client.py to api.py

# Get credentials from Environment Variables
EMAIL = os.getenv("ON_IS_EMAIL")
PASSWORD = os.getenv("ON_IS_PASSWORD")

async def main():
    if not EMAIL or not PASSWORD:
        print("Error: Environment variables ON_IS_EMAIL and ON_IS_PASSWORD are not set.")
        print("Usage (Linux/Mac/Git Bash): export ON_IS_EMAIL='me@gmail.com' && export ON_IS_PASSWORD='...'; python test_run.py")
        print("Usage (PowerShell): $env:ON_IS_EMAIL='me@gmail.com'; $env:ON_IS_PASSWORD='...'; python test_run.py")
        sys.exit(1)

    print(f"Initializing client for {EMAIL}...")
    client = OnIsClient(EMAIL, PASSWORD)
    
    try:
        print("Logging in...")
        await client.login()
        print("Login success!")

        print("Fetching Online Data...")
        sessions = await client.get_online_data()
        
        if not sessions:
            print("No active sessions found (Car not plugged in?).")
        else:
            for session in sessions:
                evse = session.get("Evse", {})
                connector = session.get("Connector", {})
                cp = session.get("ChargePoint", {})
                status = connector.get("Status", {}).get("Title", "Unknown")
                measurements = session.get("Measurements", {})
                
                print(f"\n--- ACTIVE SESSION FOUND ---")
                print(f"Location:  {session['Location']['FriendlyName']}")
                print(f"Status:    {status}")
                print(f"Power:     {measurements.get('Power', 0)} kW")
                print(f"Energy:    {measurements.get('ActiveEnergyConsumed', 0)} kWh")
                
                # Dynamic ID Construction
                # Logic confirmed: ChargePoint-Evse-Connector
                calculated_evse_code = f"{cp['FriendlyCode']}-{evse['FriendlyCode']}-{connector['Code']}"
                print(f"EvseCode:  {calculated_evse_code}")
                print(f"Ids:       CP: {cp.get('Id')} | Conn: {connector.get('Id')}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())