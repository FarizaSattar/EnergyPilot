# ⚡ EnergyPilot
**Your home's co-pilot for cutting energy costs**

## 👋 What is this?
- Most homeowners know their energy bill is high. They just don't know *why*, or what to actually do about it. There's a whole landscape of rebates and conservation programs (heat pumps, smart thermostats, time-of-use pricing) that most people never hear about because nothing connects their actual usage data to the incentives that would help them.
- EnergyPilot closes that loop. It's a full-stack energy analytics platform that ingests household electricity usage data, forecasts future consumption, and generates personalized recommendations such as which specific rebate program or price plan would actually save a given household money.

## ❓ Why I built this
- During my internships, I had some opportunities to work with energy analytics to reduce costs for clients. I saw firsthand how much value gets left on the table simply because usage data and savings programs live in two completely separate worlds. A household running a heavy HVAC load overnight might save significantly just by switching to an Ultra-Low Overnight plan. They'd never know that from their bill alone. I wanted to build a tool that closes that gap: take in real usage patterns, forecast where they're headed, and translate that into concrete, dollar-figure actions.

## 🚀 What it actually does
- Ingests household electricity usage data from simulated **ESP32 smart meters** over **MQTT**. The hardware for this tool is a work-in-progress. Simulated values will be used in the repo.
- Stores time-series readings in **InfluxDB** and visualizes trends in **Grafana**
- Runs a **load forecasting model** (scikit-learn) to predict next week's/month's usage based on historical patterns
- Analyzes usage against **Ontario's three electricity price plans** which is Time-of-Use, Tiered, and Ultra-Low Overnight to figure out which one actually fits your household
- Flags high-impact opportunities: since HVAC accounts for roughly half of a typical bill, the engine weighs heating/cooling patterns heavily in its recommendations
- Matches usage patterns to real conservation programs (e.g. Home Renovation Savings Program rebates on insulation, heat pumps, smart thermostats, and rooftop solar) and estimates the ROI of each
- Displays everything on a **React** dashboard: usage trends, forecasted costs, and a ranked list of savings opportunities

## 📈 A quick example
- Say a household's data shows consistent overnight AC use and a load pattern that spikes between 5–7pm — squarely inside peak Time-of-Use pricing.
- EnergyPilot's forecasting model flags the pattern, calculates that switching to Ultra-Low Overnight pricing plus shifting laundry/dishwasher loads to off-peak hours would cut their bill noticeably, and separately flags that their attic insulation profile makes them a strong candidate for the Home Renovation Savings Program — surfacing both the "do this today" fix and the "worth the paperwork" rebate in one place.

## 👥 Who this is for
- Energy analysts and sustainability teams who want a working example of usage-to-savings analytics
- Homeowners curious about where their electricity costs actually come from
- Students learning IoT-to-cloud pipelines paired with applied machine learning
- Anyone interested in how conservation program design connects to real usage data

## 🛠️ What you'll need to run it
- **Hardware (optional):** ESP32 dev board (or use the included simulator — no hardware required to run it). The hardware details will be included after it is finished.
- **Software:** Python 3.12, Node.js (v18+), Docker, Git
- **Built with:** Python · Pandas · NumPy · Scikit-learn · Flask · React · MQTT · SQLite · InfluxDB · Grafana
- **Helpful background:** basic Python/JavaScript and an interest in energy systems — the setup docs walk through the rest.

## 💡 How it flows, visually
```
ESP32 Smart Meter (real or simulated)
        │
        ▼
      MQTT
        │
        ▼
  InfluxDB (time-series storage)
        │
        ▼
  Load Forecasting Model (scikit-learn)
        │
        ▼
  Recommendation Engine
   │              │
   ▼              ▼
Price Plan     Rebate Program
Matching       Matching
   │              │
   └──────┬───────┘
          ▼
   React Dashboard
   (Usage · Forecast · Savings)
```

## ⚠️ A quick honest note
- EnergyPilot's forecasting runs on simulated household data and publicly available Ontario program details (Save on Energy, Enbridge Gas conservation programs) rather than a live connection to a utility's billing system. Rebate eligibility and savings estimates are illustrative, not official quotes — it's built to demonstrate the analytics and recommendation pipeline, not to replace a real energy audit.

## 🧰 Built with
Python · Pandas · NumPy · Scikit-learn · Flask · React · MQTT · ESP32 · SQLite · InfluxDB · Grafana
---

*Built by [Fariza Sattar](https://github.com/FarizaSattar)*
