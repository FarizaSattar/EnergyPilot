# EnergyPilot Backend

Python backend for smart-meter ingestion, PostgreSQL storage, MQTT telemetry, Ontario tariff estimation, and load forecasting.

## Quick start
1. `python -m venv .venv`
2. Activate the environment.
3. `pip install -r requirements.txt`
4. Copy `.env.example` to `.env`.
5. `docker compose up -d`
6. Run `python -m app.mqtt_ingestor`
7. In another terminal run `python simulator/smart_meter.py`
8. In another terminal run `python -m app.api`

API: `http://localhost:5000/api/health`

The tariff numbers are explicitly demo/configuration values and should be replaced with current official rates before real billing use.

## Future Hardware Architecture

EnergyPilot is currently designed around a simulated residential smart meter. The simulator represents the hardware device that would eventually be installed in a real home and continuously collect electrical measurements.

The long-term goal is to build a compact **EnergyPilot Home Energy Monitor** that measures electrical consumption at the circuit/panel level, processes the measurements locally, and publishes telemetry to the EnergyPilot backend over MQTT.

### 1. High-Level Architecture

The future system would follow this architecture:

```text
                 RESIDENTIAL ELECTRICAL PANEL
                            │
              ┌─────────────┴─────────────┐
              │                           │
       Current Sensors               Voltage Sensing
       (CT Clamps)                  (AC Voltage)
              │                           │
              └─────────────┬─────────────┘
                            │
                    Signal Conditioning
                            │
                     ADC / Metering IC
                            │
                            ▼
                    ┌─────────────────┐
                    │  ESP32 / MCU    │
                    │                 │
                    │ - Sampling      │
                    │ - RMS           │
                    │ - Power         │
                    │ - Energy        │
                    │ - Power Factor  │
                    │ - Diagnostics   │
                    └────────┬────────┘
                             │
                        Wi-Fi / Ethernet
                             │
                           MQTT
                             │
                             ▼
                    ┌─────────────────┐
                    │ EnergyPilot     │
                    │ MQTT Ingestor   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ PostgreSQL      │
                    │ Telemetry       │
                    └────────┬────────┘
                             │
                 ┌───────────┴───────────┐
                 ▼                       ▼
          Analytics / ML           Recommendations
                 │                       │
                 └───────────┬───────────┘
                             ▼
                    EnergyPilot Dashboard