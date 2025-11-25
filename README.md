# ON (Orka náttúrunnar) for Home Assistant

Unofficial Home Assistant integration for the Icelandic [ON (Orka náttúrunnar)](https://on.is) EV charging network. 

Built for the **Etrel OCEAN** white-label platform.

## Features
*   **Monitoring:** Live Power (kW), Energy Added (kWh), and Charger Status.
*   **Control:** Start and Stop charging sessions remotely.
*   **Dynamic:** Entities appear automatically when a car is plugged in.

## Installation

### Option 1: HACS (Recommended)
1.  Open **HACS** > **Integrations**.
2.  Click the **3 dots** (top right) > **Custom repositories**.
3.  Add this repository URL.
4.  Category: **Integration**.
5.  Search for **ON** and click **Download**.
6.  Restart Home Assistant.

### Option 2: Manual
1.  Copy the `custom_components/on_is` folder to your Home Assistant `config/custom_components/` directory.
2.  Restart Home Assistant.

## Configuration
1.  Go to **Settings** > **Devices & Services**.
2.  Click **Add Integration**.
3.  Search for **ON (Orka náttúrunnar)**.
4.  Enter your app email and password.

## Disclaimer
This is a reverse-engineered integration and is not affiliated with Orka náttúrunnar or Etrel. Use at your own risk.