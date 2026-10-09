# EnergyPilot Connected Dashboard

This React/Vite dashboard fetches live data from the matching Python Flask backend.

## Setup
```bash
cp .env.example .env
npm install
npm run dev
```

## Backend
- Default API URL comes from `.env`.
- Before starting the dashboard, start the matching backend and its simulator/ingestion service.
- The dashboard automatically refreshes API data every few seconds and displays an error if the backend is unavailable.
